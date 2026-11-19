"""审计写仓储：两个写接口（告警已读、规则变更）的审计留痕。

`audit_log` 仅追加；业务账号 `honeypot_app_rw` 只有 INSERT/SELECT 权限（data-model 4.11）。
本模块只负责插入，不提交事务：审计与业务写入在同一事务内由调用方统一提交，
失败则整体回滚（契约 3.7/3.9 的“全部写入落在数据库事务中”）。
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

#: 业务写连接使用的数据库账号名（data-model 11.2；审计要求记录数据库账号而非应用用户）
APP_RW_ACCOUNT = "honeypot_app_rw"


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
    """写入一条审计记录（不提交事务）。

    参数：

    - `operation`：`alert_ack` / `rule_change`（data-model 4.11 的允许枚举）；
    - `target_table` / `target_key`：涉及业务表与主键或规则编码；
    - `detail`：中文结构化说明，禁止写入口令与完整 SQL（契约 1.7 脱敏约定）。
    """
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


#: 预编译的审计插入语句
_INSERT_STATEMENT = text(INSERT_AUDIT_SQL)

__all__ = ["APP_RW_ACCOUNT", "write_audit"]
