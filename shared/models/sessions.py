"""`sessions` 表 ORM 模型：一次诱饵连接一行。

数据来源：捕获层在 TCP 连接建立（MySQL 握手开始）时生成 UUID v4 并写入，
在认证、查询、断开事件中更新计数与状态。是 `attack_log`、`rule_hits`、`alerts`
的归集根（data-model 4.1）。

数据库级 CHECK 约束（`ck_sessions_*`）由迁移 `0001_initial_schema` 定义，
ORM 元数据不重复声明，避免与 `Base` 的 CHECK 命名约定叠加产生双重前缀。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base
from shared.models._types import (
    datetime6,
    int_unsigned,
    smallint_unsigned,
    source_ip,
    tinyint_unsigned,
    uuid_char,
)

if TYPE_CHECKING:
    from shared.models.alerts import Alert
    from shared.models.attack_log import AttackLog
    from shared.models.rule_hits import RuleHit


class Session(Base):
    """会话主表：一次诱饵连接一行，记录来源、起止时间、状态与事件计数。"""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_source_started", "source_ip", "started_at"),
        Index("idx_sessions_status_started", "session_status", "started_at"),
        Index("idx_sessions_started", "started_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "会话主表：一次诱饵连接一行，记录来源、起止时间、状态与事件计数；"
                "数据来源为捕获层的连接与断开事件"
            ),
        },
    )

    session_id: Mapped[str] = mapped_column(
        uuid_char(),
        primary_key=True,
        comment="会话唯一标识，UUID v4 文本（36 字符），由捕获层在连接建立时生成，全局唯一且不可复用",
    )
    source_ip: Mapped[str] = mapped_column(
        source_ip(),
        nullable=False,
        comment="测试端来源地址，IPv4 或 IPv6 文本规范形式（如 192.0.2.10、2001:db8::10），写入前统一小写",
    )
    source_port: Mapped[int | None] = mapped_column(
        smallint_unsigned(),
        nullable=True,
        comment="测试端源端口 1-65535；报文缺失或 NAT 重写导致不可知时为 NULL",
    )
    target_service: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="mysql-honeypot",
        comment="被访问的诱饵服务标识，形如 mysql-honeypot:13306，用于多端口演示时区分诱饵实例",
    )
    client_fingerprint: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="客户端特征摘要（协议版本、客户端能力标志等），已脱敏，不保存原始可识别信息",
    )
    started_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="会话开始时间（UTC），由捕获层显式写入，不使用数据库默认时间",
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        datetime6(),
        nullable=True,
        comment="会话结束时间（UTC）；未结束或异常断连未回填时为 NULL；不得早于开始时间",
    )
    session_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="active",
        comment="会话状态枚举：active 进行中 / closed 正常断开 / timeout 空闲超时 / error 协议错误终止",
    )
    request_count: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="会话内事件计数（connect/auth/query/disconnect 均计 1）；由事件写入事务原子自增",
    )
    max_risk_score: Mapped[int] = mapped_column(
        tinyint_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="本会话最高风险分 0-100，写入事件时以 GREATEST 更新；权威值由 v_session_risk_summary 重算校验",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="行创建时间（UTC），由数据库默认值填充，仅用于运维排查",
    )
    updated_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        comment="行最近更新时间（UTC），用于排查计数是否停滞",
    )

    events: Mapped[list[AttackLog]] = relationship(
        back_populates="session", cascade="save-update, merge"
    )
    # 与 AttackLog.hits 共享 rule_hits.session_id：用 overlaps 明确写入归属
    hits: Mapped[list[RuleHit]] = relationship(
        back_populates="session", cascade="save-update, merge", overlaps="hits"
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="session", cascade="save-update, merge"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Session {self.session_id} {self.source_ip} {self.session_status}>"
