"""事件分析主流程：规则判定 → 命中落库 → 分数/画像/意图更新 → 告警生成。

对外稳定入口（impl-contract.md）：

    async def analyze_event(db, event_row, session_row) -> schemas.events.AnalysisResult

执行口径（contracts/events.md 6.1 步骤 4–9）：

1. 读取 `detection_rules WHERE enabled = 1`，同一 `rule_code` 只取**最大启用版本**；
2. 逐条执行规则判定（见 `m4_rules_derived.rules`），命中则写 `rule_hits`，
   以 `uk_rule_hits_event_rule_version` 防重复分析（冲突跳过，不重复计数、不重复告警）；
3. 用 `risk.py` 的纯函数计算会话分/意图分/画像分（按 `rule_code` 取最大权重后求和封顶）；
4. UPSERT `attacker_profile`（计数按事件类型增量、风险分与证据摘要重算）；
5. UPSERT `attacker_intent`（更新意图分、证据计数与首末识别时间）；
6. 调用 `alerts.generate_alerts` 生成/更新告警。

本函数**不提交事务**：由 ingest 的单事务统一 commit / rollback（FR-039/FR-042）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from m4_rules_derived import alerts as alerts_service
from m4_rules_derived.risk import (
    compute_intent_scores,
    compute_profile_risk,
    compute_session_risk,
    risk_level,
)
from m4_rules_derived.rules import RULES, RuleContext
from m4_rules_derived.rules.base import naive_utc
from shared.events.schema import AnalysisResult, RuleHitSummary
from shared.models import DetectionRule, RuleHit
from shared.utils.masking import safe_display

logger = logging.getLogger(__name__)

# 认证失败口径（与 data-model 4.3 total_auth_failures 一致）
_FAILED_AUTH_STATUSES: frozenset[str] = frozenset({"failure", "denied"})


# ---------------------------------------------------------------------------
# 规则加载与命中写入
# ---------------------------------------------------------------------------


async def _load_enabled_rules(db: AsyncSession) -> list[DetectionRule]:
    """读取启用规则，并按 rule_code 仅保留最大启用版本。

    迁移中的 `uk_detection_rules_enabled_code` 已保证同一编码至多一个启用版本，
    这里仍显式取最大版本，以符合“若同 code 多版本，仅最新启用版本参与”的口径。
    """
    rows = (
        (
            await db.execute(
                select(DetectionRule)
                .where(DetectionRule.enabled == 1)
                .order_by(DetectionRule.rule_code, DetectionRule.rule_version)
            )
        )
        .scalars()
        .all()
    )
    latest: dict[str, DetectionRule] = {}
    for rule in rows:
        code = str(rule.rule_code)
        current = latest.get(code)
        if current is None or int(rule.rule_version) > int(current.rule_version):
            latest[code] = rule
    return [latest[code] for code in sorted(latest)]


async def _insert_rule_hit(
    db: AsyncSession,
    *,
    rule: DetectionRule,
    candidate: Any,
    event_row: Any,
    session_row: Any,
) -> RuleHit | None:
    """写入一条规则命中；唯一键冲突（重复分析）时返回 None。"""
    triggered_at = naive_utc(getattr(event_row, "event_time", None))
    result = await db.execute(
        text(
            """
            INSERT IGNORE INTO rule_hits (
                event_id, session_id, rule_id, rule_code, intent_type,
                rule_version, risk_weight, evidence_summary, triggered_at
            ) VALUES (
                :event_id, :session_id, :rule_id, :rule_code, :intent_type,
                :rule_version, :risk_weight, :evidence_summary, :triggered_at
            )
            """
        ),
        {
            "event_id": int(event_row.event_id),
            "session_id": str(session_row.session_id),
            "rule_id": int(rule.rule_id),
            "rule_code": str(rule.rule_code),
            "intent_type": str(candidate.intent_type),
            "rule_version": int(rule.rule_version),
            "risk_weight": int(rule.risk_weight),
            "evidence_summary": str(candidate.evidence_summary)[:1024],
            "triggered_at": triggered_at,
        },
    )
    # INSERT IGNORE：1 = 新插入，0 = 唯一键冲突（重复分析）
    if int(result.rowcount or 0) != 1:
        return None

    hit_id = getattr(result, "lastrowid", None)
    if not hit_id:
        hit_id = (await db.execute(text("SELECT LAST_INSERT_ID()"))).scalar()
    return RuleHit(
        hit_id=int(hit_id or 0),
        event_id=int(event_row.event_id),
        session_id=str(session_row.session_id),
        rule_id=int(rule.rule_id),
        rule_code=str(rule.rule_code),
        intent_type=str(candidate.intent_type),
        rule_version=int(rule.rule_version),
        risk_weight=int(rule.risk_weight),
        evidence_summary=str(candidate.evidence_summary)[:1024],
        triggered_at=triggered_at,
    )


# ---------------------------------------------------------------------------
# 分数计算（数据库聚合 + risk.py 纯函数）
# ---------------------------------------------------------------------------


async def _fetch_session_rule_weights(
    db: AsyncSession, session_id: str
) -> list[dict[str, Any]]:
    """取本会话全部命中的 (rule_code, MAX(risk_weight))，供会话分计算。"""
    rows = (
        await db.execute(
            text(
                """
                SELECT rule_code, MAX(risk_weight) AS risk_weight
                FROM rule_hits
                WHERE session_id = :session_id
                GROUP BY rule_code
                """
            ),
            {"session_id": session_id},
        )
    ).all()
    return [
        {"rule_code": row.rule_code, "risk_weight": int(row.risk_weight or 0)}
        for row in rows
    ]


async def _fetch_profile_rule_weights(
    db: AsyncSession, source_ip: str
) -> list[dict[str, Any]]:
    """取本来源全部命中的 (rule_code, intent_type, MAX(risk_weight))，供画像分/意图分计算。"""
    rows = (
        await db.execute(
            text(
                """
                SELECT rh.rule_code, rh.intent_type, MAX(rh.risk_weight) AS risk_weight
                FROM rule_hits AS rh
                JOIN attack_log AS al ON al.event_id = rh.event_id
                WHERE al.source_ip = :source_ip
                GROUP BY rh.rule_code, rh.intent_type
                """
            ),
            {"source_ip": source_ip},
        )
    ).all()
    return [
        {
            "rule_code": row.rule_code,
            "intent_type": row.intent_type,
            "risk_weight": int(row.risk_weight or 0),
        }
        for row in rows
    ]


async def _fetch_profile_evidence(
    db: AsyncSession, source_ip: str, event_row: Any
) -> str:
    """构造画像证据摘要：命中的规则编码、权重与最近代表性语句。"""
    rows = (
        await db.execute(
            text(
                """
                SELECT rh.rule_code, MAX(rh.risk_weight) AS risk_weight, COUNT(*) AS hit_count
                FROM rule_hits AS rh
                JOIN attack_log AS al ON al.event_id = rh.event_id
                WHERE al.source_ip = :source_ip
                GROUP BY rh.rule_code
                ORDER BY risk_weight DESC, rh.rule_code
                """
            ),
            {"source_ip": source_ip},
        )
    ).all()

    parts = [
        f"{row.rule_code}×{int(row.hit_count or 0)}(权重{int(row.risk_weight or 0)})"
        for row in rows
    ]
    summary = "命中规则：" + "、".join(parts) if parts else "暂无规则命中"

    sql_preview = safe_display(
        str(getattr(event_row, "normalized_sql", None) or getattr(event_row, "sql_statement", None) or ""),
        80,
    )
    event_type = str(getattr(event_row, "event_type", "") or "")
    if sql_preview:
        summary += f"；最近事件 {event_type}：{sql_preview}"
    else:
        summary += f"；最近事件 {event_type}"
    return summary[:1024]


# ---------------------------------------------------------------------------
# 画像与意图 UPSERT
# ---------------------------------------------------------------------------


def _event_deltas(event_row: Any) -> tuple[int, int, int, int]:
    """按事件类型给出画像计数增量：(连接, 认证尝试, 认证失败, 查询)。"""
    event_type = str(getattr(event_row, "event_type", "") or "")
    status = str(getattr(event_row, "status", "") or "")
    connections = 1 if event_type == "connect" else 0
    auth_attempts = 1 if event_type == "auth" else 0
    auth_failures = 1 if event_type == "auth" and status in _FAILED_AUTH_STATUSES else 0
    queries = 1 if event_type == "query" else 0
    return connections, auth_attempts, auth_failures, queries


async def _upsert_attacker_profile(
    db: AsyncSession,
    *,
    source_ip: str,
    session_row: Any,
    event_row: Any,
    profile_score: int,
    evidence_summary: str,
    increment_counters: bool = True,
) -> int:
    """UPSERT 攻击者画像，返回 attacker_id。

    写入顺序与锁顺序遵循 contracts/events.md 6.1：`attacker_profile` 先于
    `attacker_intent` 与 `alerts`；重复执行不会重复累加计数（一次事件只调用一次）。
    """
    event_time = naive_utc(getattr(event_row, "event_time", None))
    session_started = naive_utc(getattr(session_row, "started_at", None) or event_time)
    first_seen = min(session_started, event_time)
    connections, auth_attempts, auth_failures, queries = _event_deltas(event_row)
    if not increment_counters:
        # 同一事件重复分析（显式重算路径）：不重复累加计数
        connections = auth_attempts = auth_failures = queries = 0

    result = await db.execute(
        text(
            """
            INSERT INTO attacker_profile (
                source_ip, first_seen, last_seen,
                total_connections, total_auth_attempts, total_auth_failures, total_queries,
                risk_score, evidence_summary, last_calculated_at
            ) VALUES (
                :source_ip, :first_seen, :last_seen,
                :connections, :auth_attempts, :auth_failures, :queries,
                :risk_score, :evidence_summary, :last_calculated_at
            ) AS new
            ON DUPLICATE KEY UPDATE
                attacker_id = LAST_INSERT_ID(attacker_profile.attacker_id),
                first_seen = LEAST(attacker_profile.first_seen, new.first_seen),
                last_seen = GREATEST(attacker_profile.last_seen, new.last_seen),
                total_connections = attacker_profile.total_connections + new.total_connections,
                total_auth_attempts =
                    attacker_profile.total_auth_attempts + new.total_auth_attempts,
                total_auth_failures =
                    attacker_profile.total_auth_failures + new.total_auth_failures,
                total_queries = attacker_profile.total_queries + new.total_queries,
                risk_score = new.risk_score,
                evidence_summary = new.evidence_summary,
                last_calculated_at = new.last_calculated_at
            """
        ),
        {
            "source_ip": source_ip,
            "first_seen": first_seen,
            "last_seen": event_time,
            "connections": connections,
            "auth_attempts": auth_attempts,
            "auth_failures": auth_failures,
            "queries": queries,
            "risk_score": max(0, min(int(profile_score), 100)),
            "evidence_summary": evidence_summary[:1024],
            "last_calculated_at": event_time,
        },
    )
    attacker_id = getattr(result, "lastrowid", None)
    if not attacker_id:
        attacker_id = (await db.execute(text("SELECT LAST_INSERT_ID()"))).scalar()
    return int(attacker_id or 0)


async def _upsert_attacker_intents(
    db: AsyncSession,
    *,
    attacker_id: int,
    source_ip: str,
    intent_scores: dict[str, int],
) -> None:
    """按 `(attacker_id, intent_type)` UPSERT 意图分、证据计数与首末识别时间。"""
    for intent_type in sorted(intent_scores):
        stats = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) AS evidence_count,
                           MIN(rh.triggered_at) AS first_detected_at,
                           MAX(rh.triggered_at) AS last_detected_at
                    FROM rule_hits AS rh
                    JOIN attack_log AS al ON al.event_id = rh.event_id
                    WHERE al.source_ip = :source_ip
                      AND rh.intent_type = :intent_type
                    """
                ),
                {"source_ip": source_ip, "intent_type": intent_type},
            )
        ).one()
        evidence_count = int(stats.evidence_count or 0)
        first_detected_at = naive_utc(stats.first_detected_at or datetime.now(UTC).replace(tzinfo=None))
        last_detected_at = naive_utc(stats.last_detected_at or first_detected_at)
        score = max(0, min(int(intent_scores[intent_type]), 100))

        await db.execute(
            text(
                """
                INSERT INTO attacker_intent (
                    attacker_id, intent_type, intent_score, evidence_count,
                    first_detected_at, last_detected_at
                ) VALUES (
                    :attacker_id, :intent_type, :intent_score, :evidence_count,
                    :first_detected_at, :last_detected_at
                ) AS new
                ON DUPLICATE KEY UPDATE
                    intent_score = new.intent_score,
                    evidence_count = new.evidence_count,
                    first_detected_at = LEAST(
                        attacker_intent.first_detected_at, new.first_detected_at
                    ),
                    last_detected_at = GREATEST(
                        attacker_intent.last_detected_at, new.last_detected_at
                    )
                """
            ),
            {
                "attacker_id": attacker_id,
                "intent_type": intent_type,
                "intent_score": score,
                "evidence_count": evidence_count,
                "first_detected_at": first_detected_at,
                "last_detected_at": last_detected_at,
            },
        )


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


async def analyze_event(
    db: AsyncSession, event_row: object, session_row: object
) -> AnalysisResult:
    """在 ingest 事务内分析一条事件并返回 `AnalysisResult`（不 commit）。

    Args:
        db: 当前事务的异步数据库会话。
        event_row: 已落库的 `attack_log` ORM 行。
        session_row: 对应 `sessions` ORM 行。

    Returns:
        AnalysisResult：本次新增命中摘要、告警编号、会话分、画像分、意图分与证据。
    """
    # 确保 event_id / 会话行已 flush 可见（ingest 可能在 flush 前调用）
    await db.flush()

    event_id = int(getattr(event_row, "event_id", 0) or 0)
    session_id = str(getattr(session_row, "session_id", "") or "")
    source_ip = str(
        getattr(event_row, "source_ip", "") or getattr(session_row, "source_ip", "")
    ).lower()
    event_time = naive_utc(getattr(event_row, "event_time", None))

    # 判断该事件是否已被分析过：重复分析不再累加画像计数（避免计数污染）
    already_analyzed = bool(
        await db.scalar(
            text("SELECT COUNT(*) FROM rule_hits WHERE event_id = :event_id"),
            {"event_id": int(event_id)},
        )
    )
    rules = await _load_enabled_rules(db)

    # ---- 步骤 4–5：逐规则判定并写命中 ----
    hit_summaries: list[RuleHitSummary] = []
    new_hits: list[RuleHit] = []
    evaluated_codes: list[str] = []
    skipped_codes: list[str] = []

    for rule in rules:
        rule_code = str(rule.rule_code)
        rule_func = RULES.get(rule_code)
        if rule_func is None:
            logger.warning("检测规则 %s 未实现判定逻辑，已跳过（配置错误需排查）", rule_code)
            skipped_codes.append(rule_code)
            continue

        evaluated_codes.append(rule_code)
        context = RuleContext(
            db=db,
            event_row=event_row,
            session_row=session_row,
            rule_row=rule,
        )
        try:
            candidate = await rule_func(context)
        except SQLAlchemyError:
            # 数据库错误必须上抛，交由 ingest 回滚，避免“半分析成功”
            raise
        except Exception:  # noqa: BLE001 - 单条规则逻辑异常不应拖垮整条事件
            logger.exception("规则 %s 判定异常，本事件跳过该规则", rule_code)
            skipped_codes.append(rule_code)
            continue

        if candidate is None:
            continue

        hit = await _insert_rule_hit(
            db,
            rule=rule,
            candidate=candidate,
            event_row=event_row,
            session_row=session_row,
        )
        if hit is None:
            # 唯一键冲突：该事件已被分析过，冲突跳过（幂等）
            logger.debug("规则 %s 对事件 %s 已存在命中，跳过重复写入", rule_code, event_id)
            continue

        new_hits.append(hit)
        hit_summaries.append(
            RuleHitSummary(
                rule_code=rule_code,
                rule_name=str(rule.rule_name or rule_code),
                intent_type=str(candidate.intent_type),
                risk_weight=int(rule.risk_weight),
                evidence_summary=str(candidate.evidence_summary)[:1024],
            )
        )

    # ---- 分数计算（数据库全量命中 + risk.py 纯函数） ----
    session_weights = await _fetch_session_rule_weights(db, session_id)
    profile_weights = await _fetch_profile_rule_weights(db, source_ip)
    session_score = compute_session_risk(session_weights)
    profile_score = compute_profile_risk(profile_weights)
    intent_scores = compute_intent_scores(profile_weights)

    # ---- 步骤 6–8：画像与意图 UPSERT ----
    evidence_summary = await _fetch_profile_evidence(db, source_ip, event_row)
    attacker_id = await _upsert_attacker_profile(
        db,
        source_ip=source_ip,
        session_row=session_row,
        event_row=event_row,
        profile_score=profile_score,
        evidence_summary=evidence_summary,
        increment_counters=not already_analyzed,
    )
    await _upsert_attacker_intents(
        db,
        attacker_id=attacker_id,
        source_ip=source_ip,
        intent_scores=intent_scores,
    )

    # ---- 步骤 9：告警生成（仅 R02/R04/R05 对应意图） ----
    alert_ids = await alerts_service.generate_alerts(
        db,
        session_row=session_row,
        attacker_id=attacker_id,
        event_row=event_row,
        hits=new_hits,
    )

    evidence: dict[str, Any] = {
        "event_id": event_id,
        "session_id": session_id,
        "source_ip": source_ip,
        "event_type": str(getattr(event_row, "event_type", "") or ""),
        "status": str(getattr(event_row, "status", "") or ""),
        "triggered_at": event_time.isoformat(timespec="seconds") + "Z",
        "evaluated_rule_codes": evaluated_codes,
        "skipped_rule_codes": skipped_codes,
        "hit_rule_codes": [hit.rule_code for hit in new_hits],
        "risk_level": risk_level(profile_score),
        "attacker_id": attacker_id,
        "profile_evidence": evidence_summary,
    }
    logger.debug(
        "事件分析完成：event_id=%s 新命中=%s 会话分=%s 画像分=%s 告警=%s",
        event_id,
        evidence["hit_rule_codes"],
        session_score,
        profile_score,
        alert_ids,
    )

    return AnalysisResult(
        rule_hits=hit_summaries,
        alert_ids=alert_ids,
        session_risk_score=session_score,
        profile_risk_score=profile_score,
        intent_scores=intent_scores,
        evidence=evidence,
    )
