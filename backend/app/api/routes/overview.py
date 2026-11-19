"""概览路由：`GET /api/overview` 与 `GET /api/trend`（只读，走只读会话）。

前缀 `/api` 由 `app.main` 注入，本模块路由路径不重复写 `/api`。
空库时返回全 0 指标与 `days` 条全 0 趋势点，不返回 404/500（契约 1.6/3.10）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import RODB
from app.repositories import overview_repo
from app.schemas.api import OverviewResponse, TrendResponse, request_context
from app.schemas.common import utc_now

router = APIRouter(dependencies=[Depends(request_context)])


@router.get("/overview", response_model=OverviewResponse, summary="首页概览四项指标")
async def get_overview(rodb: RODB) -> OverviewResponse:
    """与会话/查询/告警/高风险攻击者四项累计指标。

    数据全部来自 `v_session_risk_summary` 与 `v_attacker_profile_summary`，
    与答辩现场执行的视图查询口径一致（SC-009/SC-010）。
    """
    metrics = await overview_repo.fetch_overview(rodb)
    generated_at = utc_now()
    return OverviewResponse(**metrics, generated_at=generated_at)


@router.get("/trend", response_model=TrendResponse, summary="每日攻击趋势（连续日历补齐）")
async def get_trend(
    rodb: RODB,
    days: int = Query(14, ge=1, le=90, description="以 UTC 今日为终点，向前取的天数"),
) -> TrendResponse:
    """按 UTC 自然日的攻击趋势，空白日由 API 聚合层补 0 行（契约 3.10）。"""
    rows = await overview_repo.fetch_trend_rows(rodb, days)
    points = overview_repo.build_trend_series(rows, days)
    return TrendResponse(days=days, items=points)
