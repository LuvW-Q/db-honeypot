"""`detection_rules` 表 ORM 模型：检测规则配置表（一行一条规则的一个版本）。

分析层只读取 `enabled = 1` 的版本；`enabled_rule_code` 是 STORED 生成列，配合唯一约束
保证“同一 rule_code 至多一个启用版本”，消除分析时版本并列的歧义（data-model 4.5 / 10.3）。

`parameters_json` 使用 MySQL 原生 JSON 类型，结构见 data-model 10.2；
修改阈值/权重必须新建版本，禁止就地 UPDATE。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Computed, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._types import (
    ascii_bin,
    datetime6,
    smallint_unsigned,
    tinyint_bool,
    tinyint_unsigned,
)

# 启用版本生成列表达式（STORED）：启用时等于 rule_code，停用时为 NULL
ENABLED_RULE_CODE_EXPRESSION = "CASE WHEN enabled = 1 THEN rule_code ELSE NULL END"


class DetectionRule(Base):
    """检测规则配置表：一行一条规则版本；分析层只执行 enabled=1 的版本。"""

    __tablename__ = "detection_rules"
    __table_args__ = (
        UniqueConstraint(
            "rule_code", "rule_version", name="uk_detection_rules_code_version"
        ),
        UniqueConstraint("enabled_rule_code", name="uk_detection_rules_enabled_code"),
        Index("idx_detection_rules_intent", "intent_type", "enabled", "rule_code"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "检测规则配置表：一行一条规则的一个版本；分析层只执行 enabled=1 的版本，"
                "历史命中保留命中时的版本与权重快照"
            ),
        },
    )

    rule_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="规则行编号；每行代表一条规则的一个版本",
    )
    rule_code: Mapped[str] = mapped_column(
        ascii_bin(16),
        nullable=False,
        comment="稳定规则编码（R01-R05），跨版本不变，禁止复用",
    )
    rule_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="规则显示名称，如“短时高频连接扫描”",
    )
    rule_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="规则类型枚举：frequency 频率统计 / keyword 关键词 / sequence 序列 / volume 体量",
    )
    intent_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="命中后归属的攻击意图：scanning/bruteforce/recon/data_dump/destructive",
    )
    parameters_json: Mapped[dict[str, Any]] = mapped_column(
        mysql.JSON(),
        nullable=False,
        comment="单条规则内部的阈值与时间窗口参数，结构见 data-model.md 第 10 章",
    )
    risk_weight: Mapped[int] = mapped_column(
        tinyint_unsigned(),
        nullable=False,
        comment="命中计入的风险权重 1-100；按 rule_code 去重后求和",
    )
    rule_version: Mapped[int] = mapped_column(
        smallint_unsigned(),
        nullable=False,
        server_default=text("1"),
        comment="规则版本号，从 1 递增；与 rule_code 复合唯一",
    )
    enabled: Mapped[int] = mapped_column(
        tinyint_bool(),
        nullable=False,
        server_default=text("1"),
        comment="是否参与检测：1 启用 / 0 停用；同一 rule_code 至多一个启用版本",
    )
    enabled_rule_code: Mapped[str | None] = mapped_column(
        ascii_bin(16),
        Computed(ENABLED_RULE_CODE_EXPRESSION, persisted=True),
        nullable=True,
        comment="生成列：启用时等于 rule_code，停用时为 NULL；用于唯一约束保证同一规则至多一个启用版本",
    )
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="规则说明、阈值依据与已知误报，供管理员与答辩解释使用",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="创建时间（UTC）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        comment="最近更新时间（UTC）",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<DetectionRule {self.rule_code} v{self.rule_version} enabled={self.enabled}>"

    @property
    def parameters(self) -> dict[str, Any]:
        """返回解析后的规则参数（驱动可能返回字符串，这里统一成 dict）。"""
        raw = self.parameters_json
        if isinstance(raw, str):
            return json.loads(raw)
        return raw or {}
