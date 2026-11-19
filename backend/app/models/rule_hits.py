"""`rule_hits` 表 ORM 模型：一次规则命中一行（证据链关键连接点）。

写入时保存规则版本、权重与意图的**快照**，使规则改版后历史证据仍可解释
（data-model 4.6）。包含一个复合外键 `fk_hit_log(event_id, session_id)`，
保证“命中的事件与会话来自同一会话”。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import ascii_bin, datetime6, smallint_unsigned, tinyint_unsigned, uuid_char

if TYPE_CHECKING:
    from app.models.alerts import Alert
    from app.models.attack_log import AttackLog
    from app.models.detection_rules import DetectionRule
    from app.models.sessions import Session


class RuleHit(Base):
    """规则命中表：一次命中一行，保存命中时的规则版本、权重与意图快照。"""

    __tablename__ = "rule_hits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "session_id"],
            ["attack_log.event_id", "attack_log.session_id"],
            name="fk_hit_log",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "event_id", "rule_id", "rule_version", name="uk_rule_hits_event_rule_version"
        ),
        Index("idx_hit_event_session", "event_id", "session_id"),
        Index("idx_hit_rule_time", "rule_id", "created_at"),
        Index("idx_hit_session_time", "session_id", "triggered_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "规则命中表：一次命中一行，保存命中时的规则版本、权重与意图快照；"
                "与攻击日志、会话、规则构成可回溯证据链"
            ),
        },
    )

    hit_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="命中编号；被 alerts.latest_hit_id 引用",
    )
    event_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        nullable=False,
        comment="命中的事件编号，引用 attack_log.event_id；与 session_id 组成复合外键保证同源",
    )
    session_id: Mapped[str] = mapped_column(
        uuid_char(),
        ForeignKey(
            "sessions.session_id",
            name="fk_hit_session",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="命中所属会话编号，引用 sessions.session_id",
    )
    rule_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "detection_rules.rule_id",
            name="fk_hit_rule",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="命中的规则行编号，引用 detection_rules.rule_id",
    )
    rule_code: Mapped[str] = mapped_column(
        ascii_bin(16),
        nullable=False,
        comment="命中时的规则编码快照（R01-R05），便于证据展示、视图聚合而不必回连规则表",
    )
    intent_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="命中时的目标意图快照；意图分与画像分据此按历史口径复算",
    )
    rule_version: Mapped[int] = mapped_column(
        smallint_unsigned(),
        nullable=False,
        comment="命中时实际采用的规则版本快照",
    )
    risk_weight: Mapped[int] = mapped_column(
        tinyint_unsigned(),
        nullable=False,
        comment="命中时的风险权重快照 1-100；本次命中的计分贡献即该值，规则后续调整不影响历史",
    )
    evidence_summary: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="可解释证据摘要，如“会话内出现 SHOW TABLES 语句”或“5 分钟内认证 9 次、凭据组合 6 组”",
    )
    triggered_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="命中时间（UTC），由分析层写入；与 event_time 可能不同（窗口统计型规则在窗口结束时触发）",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="行落库时间（UTC）",
    )

    event: Mapped[AttackLog] = relationship(
        back_populates="hits", lazy="selectin", overlaps="hits,session"
    )
    session: Mapped[Session] = relationship(
        back_populates="hits", lazy="selectin", overlaps="event,hits"
    )
    rule: Mapped[DetectionRule] = relationship(lazy="selectin")
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="latest_hit", cascade="save-update, merge"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<RuleHit {self.hit_id} {self.rule_code} v{self.rule_version}>"
