"""`attacker_intent` 表 ORM 模型：一行一条攻击者意图。

`(attacker_id, intent_type)` 唯一；命中新证据时更新分数、证据计数与首末识别时间
（data-model 4.4）。意图分只用于排序与展示，画像分按规则维度聚合，二者不混算。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import datetime6, int_unsigned, tinyint_unsigned

if TYPE_CHECKING:
    from app.models.attacker_profile import AttackerProfile


class AttackerIntent(Base):
    """攻击意图聚合表：一行一条攻击者意图，按画像编号与意图类型复合唯一。"""

    __tablename__ = "attacker_intent"
    __table_args__ = (
        UniqueConstraint(
            "attacker_id", "intent_type", name="uk_attacker_intent_attacker_type"
        ),
        Index("idx_intent_type_score", "intent_type", "intent_score"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "攻击意图聚合表：一行一条攻击者意图，按画像编号与意图类型复合唯一；"
                "命中新证据时更新分数与首末识别时间"
            ),
        },
    )

    intent_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="意图记录编号",
    )
    attacker_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "attacker_profile.attacker_id",
            name="fk_intent_profile",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="所属画像编号，引用 attacker_profile.attacker_id",
    )
    intent_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="意图类型：scanning 扫描 / bruteforce 爆破 / recon 踩点 / data_dump 拖库 / destructive 破坏性操作",
    )
    intent_score: Mapped[int] = mapped_column(
        tinyint_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="该意图累计可信分 0-100，按 9.2 公式（该意图下按 rule_code 去重取最大权重后求和并封顶）计算",
    )
    evidence_count: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="支持该意图的规则命中条数（rule_hits 计数），用于排序与解释",
    )
    first_detected_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="首次识别该意图的时间（UTC）",
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="最近识别该意图的时间（UTC）；主要意图排序的次级键",
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

    attacker: Mapped[AttackerProfile] = relationship(
        back_populates="intents", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AttackerIntent {self.intent_id} {self.intent_type} {self.intent_score}>"
