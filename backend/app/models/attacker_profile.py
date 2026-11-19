"""`attacker_profile` 表 ORM 模型：按来源地址聚合的攻击者画像。

一行一个 `source_ip`；首次出现插入，后续事件在同一事务内更新计数、时间与风险分。
不保存多值意图列表（FR-025），主要意图由 `v_attacker_profile_summary` 计算（data-model 4.3）。
`risk_level` 是数据库生成列（VIRTUAL），由 `risk_score` 自动推导，禁止手工写入；
分数—等级永不漂移，视图共用同一 CASE 口径。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Computed, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import (
    datetime6,
    int_unsigned,
    source_ip,
    tinyint_unsigned,
)

if TYPE_CHECKING:
    from app.models.alerts import Alert
    from app.models.attacker_intent import AttackerIntent


# 风险等级生成列表达式：与 data-model 9.3 / 5.5 及四个视图使用完全相同的 CASE 口径
RISK_LEVEL_EXPRESSION = (
    "CASE WHEN risk_score >= 80 THEN 'critical' "
    "WHEN risk_score >= 60 THEN 'high' "
    "WHEN risk_score >= 30 THEN 'medium' "
    "ELSE 'low' END"
)


class AttackerProfile(Base):
    """攻击者画像表：按来源地址聚合，一行一个来源；不保存意图列表。"""

    __tablename__ = "attacker_profile"
    __table_args__ = (
        UniqueConstraint("source_ip", name="uk_attacker_profile_source_ip"),
        Index("idx_profile_risk", "risk_score", "last_seen"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "攻击者画像表：按来源地址聚合的画像，一行一个来源；不保存意图列表，"
                "主要意图由 v_attacker_profile_summary 计算"
            ),
        },
    )

    attacker_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="画像编号；被 attacker_intent 与 alerts 引用",
    )
    source_ip: Mapped[str] = mapped_column(
        source_ip(),
        nullable=False,
        comment="攻击者聚合键（来源地址），唯一；同一来源仅一行画像",
    )
    first_seen: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="该来源首次出现时间（UTC），取首次会话开始时间",
    )
    last_seen: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="该来源最近出现时间（UTC），取最新事件时间",
    )
    total_connections: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="累计连接次数（connect 事件数）",
    )
    total_auth_attempts: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="累计认证尝试次数（auth 事件数，含成功与失败）",
    )
    total_auth_failures: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="累计认证失败次数（auth 且 status 为 failure/denied），供爆破意图解释",
    )
    total_queries: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="累计 SQL 数量（query 事件数）",
    )
    risk_score: Mapped[int] = mapped_column(
        tinyint_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="来源画像风险分 0-100，按 9.2 公式（按 rule_code 去重取最大权重后求和并封顶）计算",
    )
    risk_level: Mapped[str] = mapped_column(
        mysql.VARCHAR(16),
        Computed(RISK_LEVEL_EXPRESSION, persisted=False),
        nullable=False,
        comment="风险等级生成列：critical 严重(80-100) / high 高(60-79) / medium 中(30-59) / low 低(0-29)；由 risk_score 自动推导，禁止手工写入",
    )
    evidence_summary: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="最近一次计算的证据摘要（命中的规则编码与代表性语句类型），供列表页与答辩解释",
    )
    last_calculated_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="最近一次风险重算时间（UTC），用于判断画像是否为最新口径",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="行创建时间（UTC）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        comment="行最近更新时间（UTC）",
    )

    intents: Mapped[list[AttackerIntent]] = relationship(
        back_populates="attacker", cascade="save-update, merge"
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="attacker", cascade="save-update, merge"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AttackerProfile {self.attacker_id} {self.source_ip} {self.risk_score}>"
