"""告警路由：列表筛选分页（只读）与已读状态更新（写）。

- `GET /api/alerts`：按 `alert_type`/`severity`/`is_read`/`from`/`to` 过滤，分页与
  白名单排序对齐契约 3.6；`is_read` 只接受 `true`/`false`（传 `1/0` 视为非法 → 422）；
- `PATCH /api/alerts/{alert_id}`：系统仅有的两个写接口之一，单事务内
  `SELECT ... FOR UPDATE` 后写入并返回数据库实际状态（幂等），同时写审计留痕。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import DB, RODB
from app.repositories import alert_repo
from app.repositories.audit_repo import write_audit
from app.repositories.query_repo import (
    parse_time_range,
    split_multi_value,
    total_pages,
    validate_enum_values,
    validate_order,
    validate_sort,
)
from app.schemas.api import (
    AlertItem,
    AlertListResponse,
    AlertUpdateRequest,
    not_found,
    request_context,
    unprocessable,
)

router = APIRouter(dependencies=[Depends(request_context)])

#: 告警类型与等级枚举（契约 3.6）
ALERT_TYPES = ("bruteforce", "data_dump", "destructive")
SEVERITIES = ("low", "medium", "high", "critical")


def _parse_is_read(raw: str | None) -> bool | None:
    """严格解析 `is_read` 查询参数：只接受 true/false（`1/0` → 422，契约 3.6）。"""
    if raw is None:
        return None
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise unprocessable(
        "VALIDATION_ERROR",
        "请求参数校验失败",
        {"field": "is_read", "reason": "只能是 true 或 false", "input": raw[:64]},
    )


@router.get("/alerts", response_model=AlertListResponse, summary="告警列表（筛选+分页）")
async def list_alerts(
    rodb: RODB,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    alert_type: list[str] | None = Query(None, description="告警类型，可重复或逗号分隔"),
    severity: list[str] | None = Query(None, description="告警等级，可重复或逗号分隔"),
    is_read: str | None = Query(None, description="已读状态：true/false"),
    from_: str | None = Query(None, alias="from", description="起始时间（含）"),
    to: str | None = Query(None, description="结束时间（不含）"),
    sort: str | None = Query("created_at", description="排序字段：created_at/severity"),
    order: str | None = Query("desc", description="排序方向：asc/desc"),
) -> AlertListResponse:
    """告警列表：空数据返回 `items: []` 与 `total: 0`，不返回 404。"""
    sort_field = validate_sort(sort, alert_repo.SORT_FIELDS, default="created_at")
    sort_order = validate_order(order)
    alert_types = validate_enum_values(
        split_multi_value(alert_type), ALERT_TYPES, field="alert_type"
    )
    severities = validate_enum_values(
        split_multi_value(severity), SEVERITIES, field="severity"
    )
    is_read_value = _parse_is_read(is_read)
    from_time, to_time = parse_time_range(from_, to)

    rows, total = await alert_repo.list_alerts(
        rodb,
        page=page,
        page_size=page_size,
        sort=sort_field,
        order=sort_order,
        alert_types=alert_types,
        severities=severities,
        is_read=is_read_value,
        from_time=from_time,
        to_time=to_time,
    )
    return AlertListResponse(
        items=[AlertItem(**row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.patch("/alerts/{alert_id}", response_model=AlertItem, summary="更新告警已读状态")
async def update_alert(
    alert_id: int,
    payload: AlertUpdateRequest,
    db: DB,
    request: Request,
) -> AlertItem:
    """置已读/未读；不存在返回 404 ALERT_NOT_FOUND，返回值反映数据库实际状态。"""
    locked = await alert_repo.lock_alert_for_update(db, alert_id)
    if not locked:
        raise not_found("ALERT_NOT_FOUND", "未找到告警", {"alert_id": alert_id})

    await alert_repo.set_alert_read(db, alert_id, payload.is_read)
    await write_audit(
        db,
        operation="alert_ack",
        target_table="alerts",
        target_key=str(alert_id),
        detail=(
            f"告警 {alert_id} 已读状态更新为 {'true' if payload.is_read else 'false'}"
        ),
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()

    row = await alert_repo.get_alert_by_id(db, alert_id)
    if row is None:  # pragma: no cover - 刚提交的行必然存在
        raise not_found("ALERT_NOT_FOUND", "未找到告警", {"alert_id": alert_id})
    return AlertItem(**row)
