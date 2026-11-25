"""M4 对外稳定门面：规则配置与派生分析。

跨模块只允许调用本文件的函数（contracts/module-boundaries.md §2）：

- `analyze_and_derive(session, event_row, session_row)`：规则判定 → 命中落库 →
  分数/画像/意图更新 → 告警生成；**不提交事务**，由调用方统一 commit/rollback；
- `list_rules` / `list_rule_effectiveness`：只读查询，不提交事务；
- `update_rule`：生成新规则版本（内部单事务并提交），返回新版本字典。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from m4_rules_derived import analysis
from m4_rules_derived.alerts import ALERTABLE_INTENTS
from m4_rules_derived.repositories import rule_repo
from shared.events.schema import AnalysisResult


async def analyze_and_derive(
    session: AsyncSession, event_row: Any, session_row: Any
) -> AnalysisResult:
    """执行完整分析流水线（不提交事务）。"""
    return await analysis.analyze_event(session, event_row, session_row)


async def list_rules(
    session: AsyncSession,
    *,
    include_history: bool = False,
    enabled: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """规则列表：默认每个 rule_code 只返回当前版本。"""
    return await rule_repo.list_rules(
        session, include_history=include_history, enabled=enabled
    )


async def list_rule_effectiveness(
    session: AsyncSession, *, limit: int = 50
) -> tuple[list[dict[str, Any]], int]:
    """规则效果统计（来自 v_rule_effectiveness）。"""
    return await rule_repo.list_rule_effectiveness(session, limit=limit)


async def update_rule(
    session: AsyncSession,
    rule_code: str,
    *,
    enabled: bool | None = None,
    parameters: dict[str, Any] | None = None,
    risk_weight: int | None = None,
    expected_version: int | None = None,
    change_reason: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """规则变更：生成新版本并提交（返回新版本行）。"""
    return await rule_repo.update_rule(
        session,
        rule_code,
        enabled=enabled,
        parameters=parameters,
        risk_weight=risk_weight,
        expected_version=expected_version,
        change_reason=change_reason,
        request_id=request_id,
    )


__all__ = [
    "ALERTABLE_INTENTS",
    "analyze_and_derive",
    "list_rule_effectiveness",
    "list_rules",
    "update_rule",
]
