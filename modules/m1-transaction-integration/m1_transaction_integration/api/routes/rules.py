"""规则路由：列表（只读）、效果统计（只读）与规则变更（写，生成新版本）。

- `GET /api/rules`：默认每个 `rule_code` 只返回当前生效版本；
- `GET /api/rules/effectiveness`：规则效果视图，**定义在 `/{rule_code}` 之前**，
  避免路径参数吞掉固定路径（本层虽无 `GET /rules/{rule_code}`，顺序仍保持安全）；
- `PATCH /api/rules/{rule_code}`：单事务内生成新版本（旧版本 `enabled=0`），
  不存在 404 RULE_NOT_FOUND，期望版本不符 409 RULE_VERSION_CONFLICT，
  参数模式不合法 422 VALIDATION_ERROR（契约 3.8/3.9/3.11）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request
from m4_rules_derived import public as rules_engine

from m1_transaction_integration.api.deps import DB, RODB
from m1_transaction_integration.schemas.api import (
    RuleEffectivenessResponse,
    RuleItem,
    RuleListResponse,
    RuleUpdateRequest,
    RuleUpdateResponse,
    request_context,
    unprocessable,
)

router = APIRouter(dependencies=[Depends(request_context)])


@router.get("/rules", response_model=RuleListResponse, summary="规则配置列表")
async def list_rules(
    rodb: RODB,
    include_history: bool = Query(False, description="是否返回同一 rule_code 的全部历史版本"),
    enabled: bool | None = Query(None, description="按启用状态筛选"),
) -> RuleListResponse:
    """规则列表：默认每个 `rule_code` 只返回当前（最大版本）行。"""
    rows, total = await rules_engine.list_rules(
        rodb, include_history=include_history, enabled=enabled
    )
    return RuleListResponse(items=[RuleItem(**row) for row in rows], total=total)


@router.get(
    "/rules/effectiveness",
    response_model=RuleEffectivenessResponse,
    summary="规则效果统计",
)
async def get_rules_effectiveness(
    rodb: RODB,
    limit: int = Query(50, ge=1, le=100, description="返回规则条数上限"),
) -> RuleEffectivenessResponse:
    """规则命中覆盖、告警数与排名（数据来自 `v_rule_effectiveness`）。"""
    rows, total = await rules_engine.list_rule_effectiveness(rodb, limit=limit)
    return RuleEffectivenessResponse(items=rows, total=total)


@router.patch(
    "/rules/{rule_code}",
    response_model=RuleUpdateResponse,
    summary="规则变更并生成新版本",
)
async def update_rule(
    rule_code: str = Path(..., pattern=r"^R0[1-8]$", description="稳定规则编码 R01-R08"),
    *,
    payload: RuleUpdateRequest,
    db: DB,
    request: Request,
) -> RuleUpdateResponse:
    """规则变更：事务内冻结旧版本、插入新版本、写审计，返回新版本对象。"""
    if payload.enabled is None and payload.parameters is None and payload.risk_weight is None:
        # 契约 3.9：三项至少提供一项（放在路由层校验，避免 Pydantic 校验上下文无法序列化）
        raise unprocessable(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            {"field": "body", "reason": "enabled、parameters、risk_weight 至少提供一项"},
        )
    result = await rules_engine.update_rule(
        db,
        rule_code,
        enabled=payload.enabled,
        parameters=payload.parameters,
        risk_weight=payload.risk_weight,
        expected_version=payload.expected_version,
        change_reason=payload.change_reason,
        request_id=getattr(request.state, "request_id", None),
    )
    return RuleUpdateResponse(**result)
