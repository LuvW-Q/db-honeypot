"""审计留痕写入（共享数据辅助）。

`audit_log` 仅追加；业务账号 `honeypot_app_rw` 只有 INSERT/SELECT 权限。
本函数只插入、不提交：审计与业务写入在同一事务内由调用方统一提交，
失败则整体回滚。M1 的告警处置与 M4 的规则变更共用此实现，避免跨模块导入内部仓储。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: 审计记录写入（occurred_at 取数据库 UTC 时间，避免应用时钟与库时钟漂移）
INSERT_AUDIT_SQL = """
INSERT INTO audit_log
    (occurred_at, account_name, operation, target_table, target_key, result, detail, request_id)
VALUES
    (UTC_TIMESTAMP(6), :account_name, :operation, :target_table,
     :target_key, :result, :detail, :request_id)
"""

#: 业务写连接使用的数据库账号名（审计要求记录数据库账号而非应用用户）
APP_RW_ACCOUNT = "honeypot_app_rw"

_INSERT_STATEMENT = text(INSERT_AUDIT_SQL)


async def write_audit(
    session: AsyncSession,
    *,
    operation: str,
    target_table: str,
    target_key: str,
    detail: str,
    request_id: str | None = None,
    result: str = "success",
) -> None:
    """写入一条审计记录（不提交事务）；参数长度按列定义截断。"""
    await session.execute(
        _INSERT_STATEMENT,
        {
            "account_name": APP_RW_ACCOUNT,
            "operation": operation,
            "target_table": target_table,
            "target_key": target_key[:128],
            "result": result,
            "detail": detail[:1000],
            "request_id": request_id,
        },
    )


__all__ = ["APP_RW_ACCOUNT", "write_audit"]
