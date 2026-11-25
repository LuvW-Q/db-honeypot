"""告警路由：列表筛选分页（只读）与已读状态更新（写）。

- `GET /api/alerts`：按 `alert_type`/`severity`/`is_read`/`from`/`to` 过滤，分页与
  白名单排序对齐契约 3.6；`is_read` 只接受 `true`/`false`（传 `1/0` 视为非法 → 422）；
- `PATCH /api/alerts/{alert_id}`：系统仅有的两个写接口之一，单事务内
  `SELECT ... FOR UPDATE` 后写入并返回数据库实际状态（幂等），同时写审计留痕。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from m1_transaction_integration.api.deps import DB, RODB
from m1_transaction_integration.repositories import alert_repo
from m1_transaction_integration.repositories.audit_repo import write_audit
from m1_transaction_integration.schemas.api import (
    AlertItem,
    AlertListResponse,
    AlertSummaryResponse,
    AlertUpdateRequest,
    not_found,
    request_context,
    unprocessable,
)
from shared.data.query import (
    parse_time_param,
    parse_time_range,
    split_multi_value,
    total_pages,
    validate_enum_values,
    validate_order,
    validate_sort,
)
from shared.errors import AppError
from shared.schemas.common import utc_now

router = APIRouter(dependencies=[Depends(request_context)])

#: 告警类型与等级枚举（契约 3.6）
ALERT_TYPES = ("bruteforce", "data_dump", "destructive")
SEVERITIES = ("low", "medium", "high", "critical")

#: 时间窗口上限（契约 §10：窗口上限 366 天）
MAX_WINDOW_DAYS = 366


def _parse_paired_time_range(from_value: str | None, to_value: str | None) -> tuple[Any, Any]:
    """`from`/`to` 成对校验 + 区间与窗口上限校验（契约 §4.1/§9/§10）。

    两者必须同时出现或同时缺省；出现时要求 `from < to` 且窗口不超过 366 天，
    否则统一 422 VALIDATION_ERROR，`detail` 为字段级数组（不用旧列表端点的
    TIME_RANGE_INVALID 形态，保持新端点错误格式一致）。
    """
    if (from_value is None) != (to_value is None):
        missing = "to" if from_value is not None else "from"
        raise unprocessable(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            [
                {
                    "field": missing,
                    "reason": "from 与 to 必须成对出现（或同时缺省）",
                    "input": None,
                }
            ],
        )
    try:
        start = parse_time_param(from_value, "from")
        end = parse_time_param(to_value, "to")
    except AppError as exc:
        field, reason = _time_param_error_parts(exc, from_value, to_value)
        raise unprocessable(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            [{"field": field, "reason": reason, "input": None}],
        ) from exc
    if start is not None and end is not None:
        if start >= end:
            raise unprocessable(
                "VALIDATION_ERROR",
                "请求参数校验失败",
                [
                    {
                        "field": "to",
                        "reason": "to 必须晚于 from",
                        "input": (to_value or "")[:64],
                    }
                ],
            )
        if end - start > timedelta(days=MAX_WINDOW_DAYS):
            raise unprocessable(
                "VALIDATION_ERROR",
                "请求参数校验失败",
                [
                    {
                        "field": "from",
                        "reason": "时间窗口不能超过 366 天",
                        "input": (from_value or "")[:64],
                    }
                ],
            )
    return start, end


def _time_param_error_parts(exc: AppError, from_value: str | None, to_value: str | None) -> tuple[str, str]:
    """从旧 `TIME_RANGE_INVALID` 错误里提取字段与原因，转成新端点字段级 detail。"""
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    field = str(detail.get("field") or "from")
    reason = str(detail.get("reason") or "时间格式不合法")
    raw = from_value if field == "from" else to_value
    if raw is not None:
        reason = f"{reason}（输入：{raw[:64]}）"
    return field, reason


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


@router.get("/alerts/summary", response_model=AlertSummaryResponse, summary="告警统计摘要")
async def get_alert_summary(
    rodb: RODB,
    from_: str | None = Query(None, alias="from", description="起始时间（含），需与 to 成对"),
    to: str | None = Query(None, description="结束时间（不含），需与 from 成对"),
) -> AlertSummaryResponse:
    """告警摘要（契约 §4.2）：总数/未读/已读、等级与类型分布、今日/昨日与峰值时段。

    路由注册在 `PATCH /alerts/{alert_id}` 与任何路径参数之前，避免固定路径被吞掉。
    """
    from_time, to_time = _parse_paired_time_range(from_, to)
    summary = await alert_repo.fetch_alert_summary(
        rodb,
        from_time=from_time,
        to_time=to_time,
    )
    return AlertSummaryResponse(**summary, generated_at=utc_now())


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
