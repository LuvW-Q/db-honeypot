"""审计写仓储（M1）：转引共享审计插入实现。

`audit_log` 仅追加；审计与业务写入同事务提交，失败整体回滚（契约 3.7/3.9）。
"""

from __future__ import annotations

from shared.data.audit import APP_RW_ACCOUNT, write_audit

__all__ = ["APP_RW_ACCOUNT", "write_audit"]
