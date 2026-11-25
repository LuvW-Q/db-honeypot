"""概览路由：`GET /api/overview` 与 `GET /api/trend`（只读，走只读会话）。

前缀 `/api` 由 `m1_transaction_integration.api.app` 注入，本模块路由路径不重复写 `/api`。
空库时返回全 0 指标与 `days` 条全 0 趋势点，不返回 404/500（契约 1.6/3.10）。

002 增量（contracts/api-extensions.md §1/§2/§3）：

- `/overview?range=all|7d|24h` 回显生效范围与窗口起点；非法枚举 → 422 VALIDATION_ERROR；
- `/trend` 每个趋势点补充五个 `hit_*` 意图族命中数（与 `v_daily_attack_trend` 日期对齐）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from m1_transaction_integration.api.deps import RODB
from m1_transaction_integration.repositories import overview_repo
from m1_transaction_integration.schemas.api import (
    OverviewResponse,
    TrendResponse,
    request_context,
    unprocessable,
)
from m1_transaction_integration.services.time_windows import RANGE_KEYS, resolve_range_start
from shared.schemas.common import utc_now

router = APIRouter(dependencies=[Depends(request_context)])


def _validate_range(raw: str | None) -> str:
    """校验 `range` 白名单（all/7d/24h）；非法值 → 422 VALIDATION_ERROR（契约 §2.1/§9）。"""
    value = (raw or "all").strip().lower()
    if value not in RANGE_KEYS:
        raise unprocessable(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            [
                {
                    "field": "range",
                    "reason": "只能是 all/7d/24h",
                    "input": (raw or "")[:64],
                }
            ],
        )
    return value


@router.get("/overview", response_model=OverviewResponse, summary="首页指标（可限定时间范围）")
async def get_overview(
    rodb: RODB,
    range_value: str | None = Query(
        "all", alias="range", description="时间范围：all/7d/24h"
    ),
) -> OverviewResponse:
    """首页指标：会话/查询/告警/高风险攻击者 + 今日/昨日口径与派生比率。

    数据全部来自既有表与 `v_attacker_profile_summary`，今日/昨日固定 UTC+8 自然日；
    与会话/查询/告警窗口口径一致（契约 §1.1/§1.2）。
    """
    effective_range = _validate_range(range_value)
    now = utc_now()
    window_start = resolve_range_start(effective_range, now)
    metrics = await overview_repo.fetch_overview(
        rodb,
        window_start=window_start,
        now=now,
    )
    return OverviewResponse(
        **metrics,
        range=effective_range,
        window_start=window_start,
        generated_at=now,
    )


@router.get("/trend", response_model=TrendResponse, summary="每日攻击趋势（连续日历补齐）")
async def get_trend(
    rodb: RODB,
    days: int = Query(14, ge=1, le=90, description="以 UTC 今日为终点，向前取的天数"),
) -> TrendResponse:
    """按 UTC 自然日的攻击趋势，空白日由 API 聚合层补 0 行（契约 3.10 + §3.1）。"""
    now = utc_now()
    rows = await overview_repo.fetch_trend_rows(rodb, days, now=now)
    hits_by_date = await overview_repo.fetch_trend_hits(rodb, days, now=now)
    points = overview_repo.build_trend_series(
        rows,
        days,
        end_date=now.date(),
        hits_by_date=hits_by_date,
    )
    return TrendResponse(days=days, items=points)
