"""`alerts` 表 ORM 模型：爆破/拖库/破坏性操作的告警。

`dedup_key = <rule_code>:<source_ip>:<YYYY-MM-DD>` 唯一，重复触发只累加
`occurrence_count` 并更新 `last_seen_at`，不插入重复行（data-model 4.7 / 9.5）。
告警等级由规则固定映射，不按分数区间计算；`latest_hit_id` 保证证据可定位（FR-057）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base
from shared.models._types import ascii_bin, datetime6, int_unsigned, tinyint_bool, uuid_char

if TYPE_CHECKING:
    from shared.models.attacker_profile import AttackerProfile
    from shared.models.detection_rules import DetectionRule
    from shared.models.rule_hits import RuleHit
    from shared.models.sessions import Session


class Alert(Base):
    """告警表：首次命中生成，`dedup_key` 唯一约束实现同日同规则同来源去重。"""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uk_alerts_dedup_key"),
        Index("idx_alert_level_time", "severity", "created_at"),
        Index("idx_alert_type_time", "alert_type", "created_at"),
        Index("idx_alert_session_time", "session_id", "created_at"),
        Index("idx_alert_attacker_time", "attacker_id", "created_at"),
        Index("idx_alert_read_time", "is_read", "created_at"),
        Index("idx_alert_latest_hit", "latest_hit_id"),
        # 外键 fk_alert_rule 必需的子表索引（data-model 7.1 未单列，0001 中显式命名）
        Index("idx_alert_rule", "rule_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "告警表：爆破/拖库/破坏性操作首次命中生成，dedup_key 唯一约束实现同日同规则"
                "同来源去重；重复触发更新次数与最近时间"
            ),
        },
    )

    alert_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="告警编号",
    )
    dedup_key: Mapped[str] = mapped_column(
        ascii_bin(160),
        nullable=False,
        comment="告警去重键，格式 <rule_code>:<source_ip>:<UTC 日期>，如 R05:192.0.2.10:2026-11-19；唯一约束保证同一触发条件同日只有一条告警",
    )
    session_id: Mapped[str] = mapped_column(
        uuid_char(),
        ForeignKey(
            "sessions.session_id",
            name="fk_alert_session",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="关联会话编号，引用 sessions.session_id；取首次触发告警的会话",
    )
    attacker_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "attacker_profile.attacker_id",
            name="fk_alert_attacker",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="关联攻击者画像编号，引用 attacker_profile.attacker_id",
    )
    rule_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "detection_rules.rule_id",
            name="fk_alert_rule",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="首次触发告警的规则行编号，引用 detection_rules.rule_id",
    )
    rule_code: Mapped[str] = mapped_column(
        ascii_bin(16),
        nullable=False,
        comment="触发规则编码快照，供列表展示与视图聚合，避免回连规则表",
    )
    latest_hit_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "rule_hits.hit_id",
            name="fk_alert_latest_hit",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="最近一次触发该告警的规则命中编号，引用 rule_hits.hit_id；证据可定位",
    )
    alert_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="告警类型枚举：bruteforce 爆破 / data_dump 拖库 / destructive 破坏性操作；仅这三类意图生成告警",
    )
    severity: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment="告警等级：low 低 / medium 中 / high 高 / critical 严重；映射规则见 data-model 9.4",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="告警标题（中文），如“疑似拖库：来自 192.0.2.10 的会话累计返回 1200 行”",
    )
    evidence_summary: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="告警证据摘要：规则编码、命中时间、代表性语句与统计值，禁止只给标签",
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="首次触发时间（UTC）；插入告警时写入",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="最近触发时间（UTC）；重复触发时以 GREATEST 更新",
    )
    occurrence_count: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("1"),
        comment="触发次数；首次为 1，重复触发原子自增",
    )
    is_read: Mapped[int] = mapped_column(
        tinyint_bool(),
        nullable=False,
        server_default=text("0"),
        comment="已读标记：0 未读 / 1 已读；已读更新是独立写操作",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        datetime6(),
        nullable=True,
        comment="标记已读的时间（UTC）；未读时为 NULL；与 is_read 的一致性由检查约束保证",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="行创建（首次告警）时间（UTC），等于 first_seen_at 的落库时刻",
    )
    updated_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        comment="行最近更新时间（UTC），重复触发与已读操作都会更新",
    )

    session: Mapped[Session] = relationship(back_populates="alerts", lazy="selectin")
    attacker: Mapped[AttackerProfile] = relationship(
        back_populates="alerts", lazy="selectin"
    )
    rule: Mapped[DetectionRule] = relationship(lazy="selectin")
    latest_hit: Mapped[RuleHit] = relationship(
        back_populates="alerts", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Alert {self.alert_id} {self.rule_code} {self.severity}>"
