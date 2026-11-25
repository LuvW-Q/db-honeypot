"""审计日志写入（`audit_log`，仅追加）。

按 `impl-contract.md` 第 2 章签名实现：只做 INSERT，**不 commit**，
事务边界由调用方（ingest/API/CLI）统一控制。

`audit_log` 用于 reset / rule_change / alert_ack / export / migration /
manual_query / login_failed 等关键写操作留痕；普通事件写入不必每条审计。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.audit_log import AuditLog

# data-model 4.11 的 CHECK 枚举（写库前校验，避免触发 3819 检查约束失败）
ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "reset",
        "rule_change",
        "alert_ack",
        "export",
        "migration",
        "manual_query",
        "login_failed",
    }
)
ALLOWED_RESULTS: frozenset[str] = frozenset({"success", "failure"})

# 列长度上限（data-model 4.11）
_ACCOUNT_NAME_MAX = 64
_OPERATION_MAX = 32
_TARGET_TABLE_MAX = 64
_TARGET_KEY_MAX = 128
_RESULT_MAX = 16
_DETAIL_MAX = 1000
_REQUEST_ID_MAX = 36


def _clip(value: str | None, limit: int) -> str | None:
    """按列长度截断；None 原样返回。"""
    if value is None:
        return None
    return value[:limit]


async def write_audit(
    db: AsyncSession,
    *,
    operation: str,
    result: str,
    account_name: str | None = None,
    target_table: str | None = None,
    target_key: str | None = None,
    detail: str | None = None,
    request_id: str | None = None,
) -> None:
    """追加一条审计记录（不提交事务）。

    参数与 `impl-contract.md` 一致；``operation`` / ``result`` 必须是模型 CHECK
    允许的枚举值，否则抛 ``ValueError``（避免把非法值送到数据库才失败）。
    """
    operation = (operation or "").strip()
    result = (result or "").strip()
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(f"非法审计操作类型：{operation!r}")
    if result not in ALLOWED_RESULTS:
        raise ValueError(f"非法审计结果：{result!r}")

    row = AuditLog(
        occurred_at=datetime.now(UTC).replace(tzinfo=None),
        account_name=_clip(account_name or "honeypot_app_rw", _ACCOUNT_NAME_MAX) or "",
        operation=_clip(operation, _OPERATION_MAX) or "",
        target_table=_clip(target_table, _TARGET_TABLE_MAX),
        target_key=_clip(target_key, _TARGET_KEY_MAX),
        result=_clip(result, _RESULT_MAX) or "",
        detail=_clip(detail, _DETAIL_MAX),
        request_id=_clip(request_id, _REQUEST_ID_MAX),
    )
    db.add(row)
    # 仅 flush，不 commit：事务由调用方控制（impl-contract.md 2 章）。
    await db.flush()
