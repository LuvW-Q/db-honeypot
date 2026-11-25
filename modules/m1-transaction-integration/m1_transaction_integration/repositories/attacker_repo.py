"""攻击者只读仓储：`v_attacker_profile_summary` 分页/排序与画像详情四块数据。

数据来源与口径（契约 3.3/3.4）：

- 列表与画像统计来自 `v_attacker_profile_summary`（风险分取画像存储值，风险等级为
  视图生成列；主要意图由视图窗口函数选出）；
- 意图明细来自 `attacker_intent`，会话摘要来自 `v_session_risk_summary`，
  最近规则命中来自 `rule_hits`（证据摘要不可省略，FR-051）。

所有函数只读，不提交事务。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.data.query import (
    build_in_clause,
    fetch_all,
    fetch_one,
    fetch_page,
)

#: 列表可选排序字段 -> ORDER BY 片段（含稳定次级键，契约 1.4/3.3 + 002 §6.2）
ORDER_BY_TEMPLATES: dict[str, str] = {
    "risk_score": "v.stored_risk_score {order}, v.last_seen DESC, v.source_ip ASC",
    "last_seen": "v.last_seen {order}, v.source_ip ASC",
    "first_seen": "v.first_seen {order}, v.source_ip ASC",
    "total_queries": "v.total_queries {order}, v.source_ip ASC",
    # 002 增量：按连接数排序（契约 §6.2）
    "total_connections": "v.total_connections {order}, v.source_ip ASC",
}

#: 排序字段白名单（契约 3.3 + 002 §6.2）
SORT_FIELDS = tuple(ORDER_BY_TEMPLATES)

#: 列表页每行所需列；主要意图的证据次数需回连 `attacker_intent`（视图未输出该列）。
#: `intent_labels`/`triggered_rule_codes` 为视图 `GROUP_CONCAT` 字符串，路由层拆分去重。
LIST_COLUMNS = """
SELECT v.attacker_id,
       v.source_ip,
       v.first_seen,
       v.last_seen,
       v.total_connections,
       v.total_auth_attempts,
       v.total_queries,
       v.primary_intent_type,
       v.primary_intent_score,
       v.primary_intent_last_detected_at,
       COALESCE(ai.evidence_count, 0) AS primary_intent_evidence_count,
       v.intent_labels,
       v.triggered_rule_codes,
       v.stored_risk_score,
       v.risk_level,
       v.alert_count
FROM v_attacker_profile_summary AS v
LEFT JOIN attacker_intent AS ai
       ON ai.attacker_id = v.attacker_id
      AND ai.intent_type = v.primary_intent_type
"""

#: 画像统计（详情页 `attacker`）
PROFILE_SQL = """
SELECT attacker_id,
       source_ip,
       first_seen,
       last_seen,
       total_connections,
       total_auth_attempts,
       total_auth_failures,
       total_queries,
       stored_risk_score,
       calculated_risk_score,
       risk_level,
       session_count,
       high_risk_session_count,
       alert_count,
       unread_alert_count,
       intent_labels,
       triggered_rule_codes,
       evidence_summary
FROM v_attacker_profile_summary
WHERE source_ip = :source_ip
"""

#: 意图明细：按分数、最近识别时间、类型稳定排序（契约 3.4）
INTENTS_SQL = """
SELECT intent_type,
       intent_score,
       evidence_count,
       first_detected_at,
       last_detected_at
FROM attacker_intent
WHERE attacker_id = :attacker_id
ORDER BY intent_score DESC, last_detected_at DESC, intent_type ASC
"""

#: 会话摘要：按开始时间倒序、会话编号升序稳定排序（契约 3.4）
SESSIONS_SQL = """
SELECT session_id,
       source_port,
       target_service,
       started_at,
       ended_at,
       session_status,
       event_count,
       query_count,
       hit_rule_count,
       hit_rule_codes,
       calculated_risk_score AS risk_score,
       risk_level,
       stored_max_risk_score,
       alert_count
FROM v_session_risk_summary
WHERE source_ip = :source_ip
ORDER BY started_at DESC, session_id ASC
LIMIT :_limit
"""

#: 最近规则命中：`rule_name` 取该规则编码的当前（最高）版本名称
RECENT_RULE_HITS_SQL = """
SELECT rh.hit_id,
       rh.event_id,
       rh.rule_code,
       COALESCE(rc.rule_name, rh.rule_code) AS rule_name,
       rh.intent_type,
       rh.rule_version,
       rh.risk_weight,
       rh.triggered_at,
       rh.evidence_summary
FROM rule_hits AS rh
JOIN attack_log AS al ON al.event_id = rh.event_id
LEFT JOIN (
    SELECT d.rule_code, d.rule_name
    FROM detection_rules AS d
    JOIN (
        SELECT rule_code, MAX(rule_version) AS max_version
        FROM detection_rules
        GROUP BY rule_code
    ) AS latest
      ON latest.rule_code = d.rule_code
     AND latest.max_version = d.rule_version
) AS rc ON rc.rule_code = rh.rule_code
WHERE al.source_ip = :source_ip
ORDER BY rh.triggered_at DESC, rh.hit_id DESC
LIMIT :_limit
"""


#: 攻击者摘要（契约 §5.2）：画像行数 + 高风险（high/critical）行数
ATTACKER_SUMMARY_SQL = """
SELECT COUNT(*)                                              AS total,
       COALESCE(SUM(risk_level IN ('high', 'critical')), 0)  AS high_risk_count
FROM v_attacker_profile_summary
LIMIT 1
"""

#: 最近一次规则命中（契约 §5.2 `latest_intent`）：取 `triggered_at` 最新一行，
#: `rule_name` 取该规则编码的当前（最高）版本名称
LATEST_INTENT_SQL = """
SELECT rh.intent_type,
       rh.rule_code,
       COALESCE(rc.rule_name, rh.rule_code) AS rule_name,
       al.source_ip,
       rh.triggered_at                      AS last_detected_at
FROM rule_hits AS rh
JOIN attack_log AS al ON al.event_id = rh.event_id
LEFT JOIN (
    SELECT d.rule_code, d.rule_name
    FROM detection_rules AS d
    JOIN (
        SELECT rule_code, MAX(rule_version) AS max_version
        FROM detection_rules
        GROUP BY rule_code
    ) AS latest
      ON latest.rule_code = d.rule_code
     AND latest.max_version = d.rule_version
) AS rc ON rc.rule_code = rh.rule_code
ORDER BY rh.triggered_at DESC, rh.hit_id DESC
LIMIT 1
"""

#: 画像派生统计（契约 §7.1）：已结束会话平均时长 + 高风险操作命中数
DERIVED_STATS_SQL = """
SELECT
  (SELECT CAST(ROUND(AVG(TIMESTAMPDIFF(SECOND, started_at, ended_at))) AS SIGNED)
     FROM sessions
    WHERE source_ip = :source_ip
      AND ended_at IS NOT NULL)                                   AS avg_session_seconds,
  (SELECT COUNT(*)
     FROM rule_hits AS rh
     JOIN attack_log AS al ON al.event_id = rh.event_id
    WHERE al.source_ip = :source_ip
      AND rh.intent_type IN ('data_dump', 'destructive'))         AS high_risk_op_count
"""


def _escape_like(value: str) -> str:
    """转义 `LIKE` 元字符（`\\` 先转义，再 `%`/`_`），防止用户输入变成通配符。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_filters(
    risk_levels: list[str],
    intent_types: list[str],
    q: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """构造列表筛选 SQL 片段（风险等级、主要意图类型、来源地址子串）。"""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if risk_levels:
        clause, values = build_in_clause("v.risk_level", risk_levels, "risk_level_")
        clauses.append(clause)
        params.update(values)
    if intent_types:
        clause, values = build_in_clause("v.primary_intent_type", intent_types, "intent_")
        clauses.append(clause)
        params.update(values)
    if q:
        # 参数化 LIKE + 显式 ESCAPE，用户输入中的 % / _ / \ 按字面量匹配（契约 §6.2）
        clauses.append("v.source_ip LIKE :q_pattern ESCAPE '\\\\'")
        params["q_pattern"] = f"%{_escape_like(q)}%"
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


async def list_attackers(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    sort: str,
    order: str,
    risk_levels: list[str] | None = None,
    intent_types: list[str] | None = None,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询攻击者列表（返回当前页行与 total）。"""
    where, params = _build_filters(risk_levels or [], intent_types or [], q)
    order_by = ORDER_BY_TEMPLATES[sort].format(order=order.upper())
    count_sql = f"SELECT COUNT(*) FROM v_attacker_profile_summary AS v\n{where}"
    items_sql = f"{LIST_COLUMNS}\n{where}\nORDER BY {order_by}"
    return await fetch_page(
        session,
        count_sql=count_sql,
        items_sql=items_sql,
        params=params,
        page=page,
        page_size=page_size,
    )


async def fetch_attacker_summary(session: AsyncSession) -> dict[str, Any]:
    """攻击者摘要（契约 §5.2）：总数、高风险数、最近一次规则命中。"""
    row = await fetch_one(session, ATTACKER_SUMMARY_SQL) or {}
    latest = await fetch_one(session, LATEST_INTENT_SQL)
    return {
        "total": int(row.get("total") or 0),
        "high_risk_count": int(row.get("high_risk_count") or 0),
        "latest_intent": latest,
    }


async def fetch_profile_derived_stats(
    session: AsyncSession,
    source_ip: str,
) -> dict[str, Any]:
    """画像派生统计（契约 §7.1）：平均会话时长（秒）与高风险操作命中数。"""
    row = await fetch_one(session, DERIVED_STATS_SQL, {"source_ip": source_ip}) or {}
    avg_seconds = row.get("avg_session_seconds")
    return {
        "avg_session_seconds": None if avg_seconds is None else int(avg_seconds),
        "high_risk_op_count": int(row.get("high_risk_op_count") or 0),
    }


async def get_profile_by_ip(session: AsyncSession, source_ip: str) -> dict[str, Any] | None:
    """按来源地址取画像统计；不存在返回 `None`（路由层转 404）。"""
    return await fetch_one(session, PROFILE_SQL, {"source_ip": source_ip})


async def list_intents(session: AsyncSession, attacker_id: int) -> list[dict[str, Any]]:
    """取攻击者意图明细（无意图返回空列表）。"""
    return await fetch_all(session, INTENTS_SQL, {"attacker_id": attacker_id})


async def list_attacker_sessions(
    session: AsyncSession,
    source_ip: str,
    limit: int,
) -> list[dict[str, Any]]:
    """取攻击者会话摘要（按开始时间倒序，最多 `limit` 条）。"""
    return await fetch_all(session, SESSIONS_SQL, {"source_ip": source_ip, "_limit": limit})


async def list_recent_rule_hits(
    session: AsyncSession,
    source_ip: str,
    limit: int,
) -> list[dict[str, Any]]:
    """取攻击者最近规则命中（按触发时间倒序，最多 `limit` 条）。"""
    return await fetch_all(session, RECENT_RULE_HITS_SQL, {"source_ip": source_ip, "_limit": limit})
