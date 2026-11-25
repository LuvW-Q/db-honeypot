"""演示数据重置（data-model 8.6 / impl-contract.md）。

`reset_demo_data` 在**单个事务**内按外键依赖顺序删除观测数据，保留：
- `detection_rules`（规则配置，规则改版走 T3 事务，不属于演示重置）；
- `fake_users` / `fake_orders` / `fake_config`（诱饵种子，保持展示数据稳定）；
- `audit_log`（仅追加审计表，不清理）。

删除顺序必须满足 RESTRICT 外键：
`alerts → rule_hits → attack_log → attacker_intent → attacker_profile → sessions`。
重置完成后写一条 `audit_log(operation='reset', result='success')` 留痕。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 严格按外键依赖顺序：子表在前、父表在后
DELETE_ORDER: tuple[str, ...] = (
    "alerts",
    "rule_hits",
    "attack_log",
    "attacker_intent",
    "attacker_profile",
    "sessions",
)


def _utc_now() -> datetime:
    """当前 UTC 时刻（naive，与 DATETIME(6) 列口径一致）。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def _write_audit(
    db: AsyncSession,
    *,
    operation: str,
    result: str,
    detail: str,
    account_name: str = "honeypot_app_rw",
    target_table: str | None = None,
    target_key: str | None = None,
) -> None:
    """写入一条审计记录（本层内部实现，避免依赖捕获层尚未落地的模块）。"""
    await db.execute(
        text(
            """
            INSERT INTO audit_log
                (occurred_at, account_name, operation, target_table, target_key, result, detail)
            VALUES
                (:occurred_at, :account_name, :operation, :target_table, :target_key, :result, :detail)
            """
        ),
        {
            "occurred_at": _utc_now(),
            "account_name": account_name[:64],
            "operation": operation[:32],
            "target_table": target_table[:64] if target_table else None,
            "target_key": target_key[:128] if target_key else None,
            "result": result[:16],
            "detail": detail[:1000] if detail else None,
        },
    )


async def _delete_all(db: AsyncSession) -> dict[str, int]:
    """按固定顺序逐表清空业务数据，返回每表删除行数。"""
    counts: dict[str, int] = {}
    for table in DELETE_ORDER:
        result = await db.execute(text(f"DELETE FROM {table}"))
        counts[table] = int(result.rowcount or 0)
    return counts


async def reset_demo_data(
    db: AsyncSession, *, operator: str = "cli"
) -> dict[str, int]:
    """单事务重置演示数据，返回每表删除行数。

    Args:
        db: 异步数据库会话；若调用方已开启事务则复用该事务，否则由本函数开启。
        operator: 操作者标识，写入审计 `detail` 便于追溯（如 cli / api / test）。

    Returns:
        形如 `{"alerts": 3, "rule_hits": 5, ...}` 的每表删除行数。
    """
    if db.in_transaction():
        counts = await _reset_in_transaction(db, operator)
    else:
        async with db.begin():
            counts = await _reset_in_transaction(db, operator)
    return counts


async def _reset_in_transaction(db: AsyncSession, operator: str) -> dict[str, int]:
    """事务内的实际重置逻辑（调用方负责 commit/rollback）。"""
    counts = await _delete_all(db)
    total = sum(counts.values())
    summary = "；".join(f"{table}={rows}" for table, rows in counts.items())
    await _write_audit(
        db,
        operation="reset",
        result="success",
        detail=f"演示数据重置（operator={operator}）：共删除 {total} 行 [{summary}]",
    )
    logger.info("演示数据重置完成：operator=%s counts=%s", operator, counts)
    return counts


__all__: list[Any] = ["reset_demo_data", "DELETE_ORDER"]
