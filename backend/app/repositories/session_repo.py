"""会话时间线只读仓储：会话头（`v_session_risk_summary`）+ 事件 + 规则命中 + 告警。

排序口径严格对齐契约 3.5：

- 事件按 `event_time ASC, event_id ASC`（FR-018/SC-003 的稳定排序）；
- 规则命中按 `triggered_at ASC, hit_id ASC`；
- 告警按 `created_at ASC, alert_id ASC`。

所有函数只读，不提交事务。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.query_repo import fetch_all, fetch_one

#: 会话头：视图提供重算值，`sessions` 表补充客户端特征（视图未输出该列）
SESSION_HEADER_SQL = """
SELECT v.session_id,
       v.source_ip,
       v.source_port,
       v.target_service,
       s.client_fingerprint,
       v.started_at,
       v.ended_at,
       v.session_status,
       v.stored_request_count,
       v.event_count,
       v.query_count,
       v.stored_max_risk_score,
       v.calculated_risk_score,
       v.risk_level,
       v.alert_count
FROM v_session_risk_summary AS v
JOIN sessions AS s ON s.session_id = v.session_id
WHERE v.session_id = :session_id
"""

#: 时间线事件：一次取 `limit + 1` 条用于判断是否截断（契约 3.5 `events_truncated`）
EVENTS_SQL = """
SELECT event_id,
       event_uuid,
       event_type,
       event_time,
       source_ip,
       username,
       credential_test_id,
       sql_statement,
       normalized_sql,
       returned_rows,
       response_ms,
       status,
       payload_truncated
FROM attack_log
WHERE session_id = :session_id
ORDER BY event_time ASC, event_id ASC
LIMIT :_limit
"""

#: 会话规则命中：`rule_name` 取该规则编码的当前（最高）版本名称
RULE_HITS_SQL = """
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
WHERE rh.session_id = :session_id
ORDER BY rh.triggered_at ASC, rh.hit_id ASC
"""

#: 会话告警（时间线对齐用，字段为契约 3.5 `alerts[]` 子集）
ALERTS_SQL = """
SELECT alert_id,
       alert_type,
       severity,
       title,
       occurrence_count,
       created_at,
       is_read
FROM alerts
WHERE session_id = :session_id
ORDER BY created_at ASC, alert_id ASC
"""


async def get_session_header(
    session: AsyncSession,
    session_id: str,
) -> dict[str, Any] | None:
    """按会话编号取会话头；不存在返回 `None`（路由层转 404 SESSION_NOT_FOUND）。"""
    return await fetch_one(session, SESSION_HEADER_SQL, {"session_id": session_id})


async def list_session_events(
    session: AsyncSession,
    session_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """取会话事件（`limit` 由调用方按上限 +1 传入以判断截断）。"""
    return await fetch_all(session, EVENTS_SQL, {"session_id": session_id, "_limit": limit})


async def list_session_rule_hits(
    session: AsyncSession,
    session_id: str,
) -> list[dict[str, Any]]:
    """取会话规则命中（按触发时间升序）。"""
    return await fetch_all(session, RULE_HITS_SQL, {"session_id": session_id})


async def list_session_alerts(
    session: AsyncSession,
    session_id: str,
) -> list[dict[str, Any]]:
    """取会话关联告警（按创建时间升序）。"""
    return await fetch_all(session, ALERTS_SQL, {"session_id": session_id})
