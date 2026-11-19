"""攻击者路由：`GET /api/attackers` 与 `GET /api/attackers/{ip}`（只读）。

分页、排序白名单与筛选口径对齐契约 3.3/3.4；非法 IP 返回 422 IP_FORMAT_INVALID，
合法但无画像返回 404 ATTACKER_NOT_FOUND（未知按契约错误结构返回，不抛 500）。
"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import RODB
from app.repositories import attacker_repo
from app.repositories.query_repo import (
    split_multi_value,
    total_pages,
    validate_enum_values,
    validate_order,
    validate_sort,
)
from app.schemas.api import (
    AttackerDetailResponse,
    AttackerListResponse,
    not_found,
    request_context,
    unprocessable,
)

router = APIRouter(dependencies=[Depends(request_context)])

#: 风险等级与意图枚举（契约 3.3 筛选参数）
RISK_LEVELS = ("low", "medium", "high", "critical")
INTENT_TYPES = ("scanning", "bruteforce", "recon", "data_dump", "destructive")


def _normalize_ip(raw: str) -> str:
    """校验并规范化来源地址；非法地址返回 422 IP_FORMAT_INVALID（契约 3.4）。"""
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError as exc:
        raise unprocessable(
            "IP_FORMAT_INVALID",
            "来源地址格式不合法",
            {"field": "ip", "reason": "需为合法 IPv4/IPv6 字面量", "input": raw[:64]},
        ) from exc


def _to_list_item(row: dict[str, Any]) -> dict[str, Any]:
    """视图行 -> 列表项（`stored_risk_score` 映射为 `risk_score`）。"""
    primary_type = row.get("primary_intent_type")
    main_intent = (
        {
            "intent_type": primary_type,
            "intent_score": int(row.get("primary_intent_score") or 0),
            "evidence_count": int(row.get("primary_intent_evidence_count") or 0),
            "last_detected_at": row.get("primary_intent_last_detected_at"),
        }
        if primary_type
        else None
    )
    return {
        "attacker_id": int(row["attacker_id"]),
        "source_ip": row["source_ip"],
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "total_connections": int(row.get("total_connections") or 0),
        "total_auth_attempts": int(row.get("total_auth_attempts") or 0),
        "total_queries": int(row.get("total_queries") or 0),
        "main_intent": main_intent,
        "risk_score": int(row.get("stored_risk_score") or 0),
        "risk_level": row.get("risk_level") or "low",
        "alert_count": int(row.get("alert_count") or 0),
    }


def _to_profile(row: dict[str, Any]) -> dict[str, Any]:
    """视图行 -> 画像统计（存储风险分与重算风险分并列返回，便于答辩对照）。"""
    intent_labels = row.get("intent_labels")
    return {
        "attacker_id": int(row["attacker_id"]),
        "source_ip": row["source_ip"],
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "total_connections": int(row.get("total_connections") or 0),
        "total_auth_attempts": int(row.get("total_auth_attempts") or 0),
        "total_auth_failures": int(row.get("total_auth_failures") or 0),
        "total_queries": int(row.get("total_queries") or 0),
        "risk_score": int(row.get("stored_risk_score") or 0),
        "calculated_risk_score": int(row.get("calculated_risk_score") or 0),
        "risk_level": row.get("risk_level") or "low",
        "session_count": int(row.get("session_count") or 0),
        "high_risk_session_count": int(row.get("high_risk_session_count") or 0),
        "alert_count": int(row.get("alert_count") or 0),
        "unread_alert_count": int(row.get("unread_alert_count") or 0),
        "intent_labels": intent_labels or None,
        "triggered_rule_codes": row.get("triggered_rule_codes"),
        "evidence_summary": row.get("evidence_summary"),
    }


@router.get("/attackers", response_model=AttackerListResponse, summary="攻击者列表（分页）")
async def list_attackers(
    rodb: RODB,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    sort: str | None = Query(
        "risk_score", description="排序字段：risk_score/last_seen/first_seen/total_queries"
    ),
    order: str | None = Query("desc", description="排序方向：asc/desc"),
    risk_level: list[str] | None = Query(None, description="风险等级筛选，可重复或逗号分隔"),
    intent_type: list[str] | None = Query(None, description="主要意图筛选，可重复或逗号分隔"),
) -> AttackerListResponse:
    """按风险分/时间排序的攻击者列表，空数据返回 `items: []`。"""
    sort_field = validate_sort(sort, attacker_repo.SORT_FIELDS, default="risk_score")
    sort_order = validate_order(order)
    risk_levels = validate_enum_values(
        split_multi_value(risk_level), RISK_LEVELS, field="risk_level"
    )
    intent_types = validate_enum_values(
        split_multi_value(intent_type), INTENT_TYPES, field="intent_type"
    )

    rows, total = await attacker_repo.list_attackers(
        rodb,
        page=page,
        page_size=page_size,
        sort=sort_field,
        order=sort_order,
        risk_levels=risk_levels,
        intent_types=intent_types,
    )
    items = [_to_list_item(row) for row in rows]
    return AttackerListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.get(
    "/attackers/{ip}",
    response_model=AttackerDetailResponse,
    summary="攻击者详情（画像/意图/会话摘要/最近命中）",
)
async def get_attacker(
    ip: str,
    rodb: RODB,
    session_limit: int = Query(50, ge=1, le=200, description="会话摘要条数上限"),
    hit_limit: int = Query(20, ge=1, le=100, description="最近规则命中条数上限"),
) -> AttackerDetailResponse:
    """按来源地址取画像、意图、会话摘要与最近规则证据；无画像返回 404。"""
    source_ip = _normalize_ip(ip)
    profile_row = await attacker_repo.get_profile_by_ip(rodb, source_ip)
    if profile_row is None:
        raise not_found(
            "ATTACKER_NOT_FOUND", "暂无该来源画像", {"source_ip": source_ip}
        )

    attacker_id = int(profile_row["attacker_id"])
    intents = await attacker_repo.list_intents(rodb, attacker_id)
    sessions = await attacker_repo.list_attacker_sessions(rodb, source_ip, session_limit)
    recent_hits = await attacker_repo.list_recent_rule_hits(rodb, source_ip, hit_limit)

    return AttackerDetailResponse(
        attacker=_to_profile(profile_row),
        intents=intents,
        sessions=sessions,
        recent_rule_hits=recent_hits,
    )
