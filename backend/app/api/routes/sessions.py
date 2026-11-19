"""会话时间线路由：`GET /api/sessions/{session_id}/timeline`（只读）。

返回会话头 + 事件（`event_time ASC, event_id ASC`）+ 规则命中 + 告警，
未知会话返回 404 SESSION_NOT_FOUND；事件超过 1000 条时截断并置 `events_truncated`。
脱敏要求（契约 1.7/3.5）：用户名脱敏后返回，凭据只给固定掩码 `"****"`，
SQL 文本按 2000 字符截断（SQL 是观测对象，可展示但不得撑爆页面）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import RODB
from app.repositories import session_repo
from app.repositories.query_repo import derive_statement_type, truncate_text
from app.schemas.api import (
    TimelineResponse,
    not_found,
    request_context,
)
from app.utils.masking import mask_username

router = APIRouter(dependencies=[Depends(request_context)])

#: 单会话事件返回上限（契约 3.5 `events_truncated`）
EVENTS_LIMIT = 1000

#: SQL / 标准化 SQL 的展示截断长度（任务要求 2000 字符）
SQL_DISPLAY_LIMIT = 2000

#: 用户名展示截断长度（data-model 4.2：username 上限 128 字符）
USERNAME_LIMIT = 128


def _to_session_header(row: dict[str, Any]) -> dict[str, Any]:
    """视图行 -> 会话头（`stored_*` 列映射为契约字段名）。"""
    return {
        "session_id": row["session_id"],
        "source_ip": row["source_ip"],
        "source_port": row.get("source_port"),
        "target_service": row.get("target_service") or "mysql-honeypot",
        "client_fingerprint": row.get("client_fingerprint"),
        "started_at": row["started_at"],
        "ended_at": row.get("ended_at"),
        "session_status": row.get("session_status") or "active",
        "request_count": int(row.get("stored_request_count") or 0),
        "event_count": int(row.get("event_count") or 0),
        "query_count": int(row.get("query_count") or 0),
        "max_risk_score": int(row.get("stored_max_risk_score") or 0),
        "calculated_risk_score": int(row.get("calculated_risk_score") or 0),
        "risk_level": row.get("risk_level") or "low",
        "alert_count": int(row.get("alert_count") or 0),
    }


def _to_event(row: dict[str, Any]) -> dict[str, Any]:
    """事件行 -> 时间线事件（脱敏 + 截断 + 派生 statement_type）。"""
    raw_username, username_truncated = truncate_text(row.get("username"), USERNAME_LIMIT)
    sql_statement, sql_truncated = truncate_text(
        row.get("sql_statement"), SQL_DISPLAY_LIMIT
    )
    normalized_sql, normalized_truncated = truncate_text(
        row.get("normalized_sql"), SQL_DISPLAY_LIMIT
    )
    event_type = row.get("event_type") or "query"
    statement_type = derive_statement_type(normalized_sql or sql_statement)
    return {
        "event_id": int(row["event_id"]),
        "event_uuid": row["event_uuid"],
        "event_type": event_type,
        "event_time": row["event_time"],
        "source_ip": row["source_ip"],
        # 用户名是可展示内容，但必须脱敏（保留首尾、中间打码）
        "username": mask_username(raw_username),
        "credential_test_id": row.get("credential_test_id"),
        # 认证事件固定掩码，其他事件为 null；任何情况下不返回明文口令
        "credential_masked": "****" if event_type == "auth" else None,
        "sql_statement": sql_statement,
        "normalized_sql": normalized_sql,
        "statement_type": statement_type,
        "returned_rows": int(row.get("returned_rows") or 0),
        "response_ms": int(row.get("response_ms") or 0),
        "status": row.get("status") or "success",
        "payload_truncated": bool(row.get("payload_truncated"))
        or username_truncated
        or sql_truncated
        or normalized_truncated,
    }


@router.get(
    "/sessions/{session_id}/timeline",
    response_model=TimelineResponse,
    summary="会话时间线与证据",
)
async def get_session_timeline(session_id: str, rodb: RODB) -> TimelineResponse:
    """按会话编号重建时间线；无会话返回 404，关联数据为空时返回空数组。"""
    header = await session_repo.get_session_header(rodb, session_id)
    if header is None:
        raise not_found(
            "SESSION_NOT_FOUND", "未找到会话", {"session_id": session_id}
        )

    # 多取 1 条用于判断是否超过返回上限
    raw_events = await session_repo.list_session_events(rodb, session_id, EVENTS_LIMIT + 1)
    events_truncated = len(raw_events) > EVENTS_LIMIT
    events = [_to_event(row) for row in raw_events[:EVENTS_LIMIT]]

    rule_hits = await session_repo.list_session_rule_hits(rodb, session_id)
    alerts = await session_repo.list_session_alerts(rodb, session_id)

    return TimelineResponse(
        session=_to_session_header(header),
        events=events,
        rule_hits=rule_hits,
        alerts=alerts,
        events_truncated=events_truncated,
    )
