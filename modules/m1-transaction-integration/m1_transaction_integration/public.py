"""M1 对外稳定门面：事务写入与演示重置。

跨模块只允许调用本文件的函数（contracts/module-boundaries.md §2）：

- `ingest_event(event)`：把一条标准事件写入数据库，内部开启独立事务并完成
  规则分析、画像/意图派生与告警去重；返回 `IngestResult`；
- `reset_demo(operator)`：单事务清理观测数据并写审计，保留规则与诱饵种子。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from m1_transaction_integration.services.ingest import IngestService
from m1_transaction_integration.services.reset import reset_demo_data
from shared.db.session import get_rw_factory
from shared.events.schema import CapturedEvent, IngestResult


async def ingest_event(event: CapturedEvent) -> IngestResult:
    """写入一条事件（独立事务；调用方无需关心会话与提交）。"""
    factory = get_rw_factory()
    async with factory() as session:
        async with session.begin():
            return await IngestService(session).ingest(event)


async def reset_demo(operator: str = "reset_demo") -> dict[str, Any]:
    """重置演示观测数据（保留规则与诱饵种子），返回删除计数。"""
    factory = get_rw_factory()
    async with factory() as session:
        async with session.begin():
            return await reset_demo_data(session, operator=operator)


async def ingest_events_in_session(
    session: AsyncSession, events: list[CapturedEvent]
) -> list[IngestResult]:
    """在同一会话内顺序写入多条事件（供迁移/验证工具使用，不提交显式事务）。

    说明：`IngestService.ingest` 内部自行提交；本函数仅用于需要复用会话的
    测试与数据加载工具，不属于跨模块公开契约的核心路径。
    """
    service = IngestService(session)
    return [await service.ingest(event) for event in events]


__all__ = ["ingest_event", "ingest_events_in_session", "reset_demo"]
