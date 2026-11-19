"""告警生成（data-model 9.4 / 9.5，contracts/events.md 6.5）。

生成条件：仅 `intent_type ∈ {bruteforce, data_dump, destructive}` 的命中生成告警
（对应 R02/R04/R05）；R01（scanning）与 R03（recon）只进入画像/意图/证据。

去重语义：`dedup_key = "<rule_code>:<source_ip>:<UTC 日期>"`，数据库
`uk_alerts_dedup_key` 是唯一防线；首次触发插入、重复触发原子更新
`last_seen_at / occurrence_count / latest_hit_id / evidence_summary / updated_at`，
不更新 `first_seen_at / created_at / severity / alert_type / rule_id / session_id`。

告警生成属于业务派生写入，**不写 audit_log**（审计仅用于规则变更、重置等运维操作）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rules.base import naive_utc

logger = logging.getLogger(__name__)

# 仅这三类意图生成告警（data-model 9.4）
ALERTABLE_INTENTS: frozenset[str] = frozenset({"bruteforce", "data_dump", "destructive"})

# 规则编码 -> 固定告警等级（不按会话分数区间计算；未来新规则默认 medium）
SEVERITY_BY_RULE: dict[str, str] = {
    "R02": "medium",
    "R04": "high",
    "R05": "critical",
}
DEFAULT_SEVERITY = "medium"

# 告警中文标题前缀（按规则编码，未识别规则回落到意图名）
TITLE_BY_RULE: dict[str, str] = {
    "R02": "疑似认证爆破",
    "R04": "疑似批量拖库",
    "R05": "疑似破坏性操作",
}
TITLE_BY_INTENT: dict[str, str] = {
    "bruteforce": "疑似认证爆破",
    "data_dump": "疑似批量拖库",
    "destructive": "疑似破坏性操作",
}


def _field(hit: Any, name: str, default: Any = None) -> Any:
    """从 ORM 命中行 / 命中摘要对象读取字段。"""
    return getattr(hit, name, default)


def _build_title(rule_code: str, intent_type: str, source_ip: str) -> str:
    """构造 ≤200 字符的中文可读标题。"""
    prefix = TITLE_BY_RULE.get(rule_code) or TITLE_BY_INTENT.get(intent_type, "疑似攻击行为")
    title = f"{prefix}：来自 {source_ip} 的规则 {rule_code} 命中"
    return title[:200]


def _build_evidence(hit: Any, source_ip: str, triggered_at: datetime) -> str:
    """构造 ≤1024 字符的告警证据摘要（含规则编码、时间、命中原因）。"""
    rule_code = str(_field(hit, "rule_code", ""))
    rule_version = _field(hit, "rule_version", None)
    reason = str(_field(hit, "evidence_summary", "") or "")
    version_text = f" v{rule_version}" if rule_version is not None else ""
    timestamp = naive_utc(triggered_at).isoformat(sep=" ", timespec="seconds")
    evidence = f"规则 {rule_code}{version_text}（命中时间 {timestamp}Z）：{reason}；来源 {source_ip}"
    return evidence[:1024]


async def _resolve_alert_id(db: AsyncSession, result: Any) -> int:
    """取 INSERT ... ON DUPLICATE KEY UPDATE 后的 alert_id。

    更新分支在 SQL 中写入 `alert_id = LAST_INSERT_ID(alert_id)`，因此 `lastrowid`
    与 `SELECT LAST_INSERT_ID()` 都能拿到既有行编号。
    """
    alert_id = getattr(result, "lastrowid", None)
    if alert_id:
        return int(alert_id)
    value = (await db.execute(text("SELECT LAST_INSERT_ID()"))).scalar()
    return int(value or 0)


async def generate_alerts(
    db: AsyncSession,
    *,
    session_row: object,
    attacker_id: int,
    event_row: object,
    hits: list,
) -> list[int]:
    """为本次新写入的命中生成/更新告警，返回受影响的 alert_id 列表。

    Args:
        db: 当前分析事务的异步会话（不 commit，由 ingest 事务控制）。
        session_row: 命中所属会话 ORM 行。
        attacker_id: 步骤 6 得到的画像编号。
        event_row: 触发告警的事件 ORM 行。
        hits: 本次**新写入**的 `rule_hits` 行列表（含 rule_code/intent_type/
            risk_weight/evidence_summary/hit_id 等字段）。
    """
    alert_ids: list[int] = []
    if not hits:
        return alert_ids

    source_ip = (
        str(getattr(event_row, "source_ip", "") or getattr(session_row, "source_ip", "")).lower()
    )
    session_id = str(
        getattr(session_row, "session_id", "") or getattr(event_row, "session_id", "")
    )
    if not source_ip or not session_id or not attacker_id:
        logger.warning("告警生成缺少必要字段，已跳过：source_ip=%s session_id=%s attacker_id=%s",
                       source_ip, session_id, attacker_id)
        return alert_ids

    # 同一批命中可能确实出现重复去重键（极端情况），本地去重保证返回列表稳定
    seen_keys: set[str] = set()

    for hit in hits:
        intent_type = str(_field(hit, "intent_type", "") or "")
        if intent_type not in ALERTABLE_INTENTS:
            continue

        rule_code = str(_field(hit, "rule_code", "") or "")
        rule_id = int(_field(hit, "rule_id", 0) or 0)
        hit_id = int(_field(hit, "hit_id", 0) or 0)
        if not rule_code or not rule_id or not hit_id:
            logger.warning("告警生成跳过缺少 rule_id/hit_id 的命中：%s", rule_code)
            continue

        triggered_at = naive_utc(
            _field(hit, "triggered_at", None) or getattr(event_row, "event_time", None)
        )
        dedup_key = f"{rule_code}:{source_ip}:{triggered_at.date().isoformat()}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        severity = SEVERITY_BY_RULE.get(rule_code, DEFAULT_SEVERITY)
        title = _build_title(rule_code, intent_type, source_ip)
        evidence = _build_evidence(hit, source_ip, triggered_at)

        result = await db.execute(
            text(
                """
                INSERT INTO alerts (
                    dedup_key, session_id, attacker_id, rule_id, rule_code,
                    latest_hit_id, alert_type, severity, title, evidence_summary,
                    first_seen_at, last_seen_at, occurrence_count, is_read
                ) VALUES (
                    :dedup_key, :session_id, :attacker_id, :rule_id, :rule_code,
                    :latest_hit_id, :alert_type, :severity, :title, :evidence_summary,
                    :first_seen_at, :last_seen_at, 1, 0
                ) AS new
                ON DUPLICATE KEY UPDATE
                    alert_id = LAST_INSERT_ID(alerts.alert_id),
                    last_seen_at = GREATEST(alerts.last_seen_at, new.last_seen_at),
                    occurrence_count = alerts.occurrence_count + 1,
                    latest_hit_id = new.latest_hit_id,
                    evidence_summary = new.evidence_summary,
                    updated_at = UTC_TIMESTAMP(6)
                """
            ),
            {
                "dedup_key": dedup_key,
                "session_id": session_id,
                "attacker_id": int(attacker_id),
                "rule_id": rule_id,
                "rule_code": rule_code,
                "latest_hit_id": hit_id,
                "alert_type": intent_type,
                "severity": severity,
                "title": title,
                "evidence_summary": evidence,
                "first_seen_at": triggered_at,
                "last_seen_at": triggered_at,
            },
        )
        alert_id = await _resolve_alert_id(db, result)
        if alert_id > 0 and alert_id not in alert_ids:
            alert_ids.append(alert_id)

    return alert_ids
