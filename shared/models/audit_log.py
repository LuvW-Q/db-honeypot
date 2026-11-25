"""`audit_log` 表 ORM 模型：仅追加的审计日志。

记录关键写操作（重置、规则变更、告警已读、导出、迁移、失败登录等）的留痕，
从权限层保证业务账号仅有 INSERT/SELECT（data-model 4.11 / 11.2）。
`audit_log` 是受控新增的第 11 张表，不与其他业务表建外键。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base
from shared.models._types import ascii_bin, datetime6, uuid_char


class AuditLog(Base):
    """审计日志表：仅追加记录关键写操作，业务账号仅可插入与查询。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_time", "occurred_at"),
        Index("idx_audit_operation_time", "operation", "occurred_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "审计日志表：仅追加重放记录关键写操作（重置、规则变更、告警已读、导出、迁移）；"
                "业务账号仅可插入与查询，不可修改删除"
            ),
        },
    )

    audit_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="审计编号",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="操作发生时间（UTC）",
    )
    account_name: Mapped[str] = mapped_column(
        ascii_bin(64),
        nullable=False,
        comment="执行操作的数据库账号名（非应用用户），如 honeypot_app_rw",
    )
    operation: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="操作类型：reset 演示重置 / rule_change 规则版本变更 / alert_ack 告警已读 / export 数据导出 / migration 迁移执行 / manual_query 人工查询 / login_failed 连接失败",
    )
    target_table: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="涉及的业务表名，如 attack_log",
    )
    target_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="涉及的主键或去重键（脱敏后），如告警去重键或规则编码",
    )
    result: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="操作结果：success 成功 / failure 失败",
    )
    detail: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="结构化说明；禁止写入口令、完整 SQL 原文或任何真实凭据",
    )
    request_id: Mapped[str | None] = mapped_column(
        uuid_char(),
        nullable=True,
        comment="一次业务操作的关联编号（UUID v4 文本），用于串联同一操作的多条审计记录",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AuditLog {self.audit_id} {self.operation} {self.result}>"
