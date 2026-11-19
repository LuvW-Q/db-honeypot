"""三张诱饵表 ORM 模型：完全虚构的展示数据，与观测数据物理隔离。

- `fake_users`：30 条虚构用户；`password_hash` 由 CHECK 约束强制 `TEST-ONLY$` 前缀；
- `fake_orders`：120 条虚构订单，构造大结果集演示；
- `fake_config`：5 条看似敏感但完全无效的配置，`config_value` 强制 `TEST-ONLY` 前缀。

诱饵表不参与任何检测、画像或告警计算（data-model 4.8-4.10）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import ascii_bin, ascii_char, datetime6, tinyint_bool


class FakeUser(Base):
    """诱饵用户表：完全虚构的展示数据，仅用于诱饵层返回。"""

    __tablename__ = "fake_users"
    __table_args__ = (
        UniqueConstraint("username", name="uk_fake_users_username"),
        UniqueConstraint("email", name="uk_fake_users_email"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "诱饵用户表：完全虚构的展示数据，仅用于诱饵层返回；"
                "password_hash 为不可用伪哈希，检查约束强制 TEST-ONLY$ 前缀"
            ),
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="诱饵用户编号",
    )
    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="虚构诱饵账号，形如 demo_user_01，明显非真实人员",
    )
    email: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="虚构邮箱，统一使用 example.test 保留域名",
    )
    phone: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="虚构手机号，统一使用 199-0000-00NN 号段，明显非真实号码",
    )
    password_hash: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="不可用的伪哈希，必须以 TEST-ONLY$ 开头（检查约束强制），不参与任何真实认证",
    )
    display_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="虚构显示名，形如 演示用户01",
    )
    is_synthetic: Mapped[int] = mapped_column(
        tinyint_bool(),
        nullable=False,
        server_default=text("1"),
        comment="合成标记，检查约束强制恒为 1，保证所有诱饵数据可识别为人工生成",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="行创建时间（UTC）",
    )

    orders: Mapped[list[FakeOrder]] = relationship(
        back_populates="user", cascade="save-update, merge"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<FakeUser {self.id} {self.username}>"


class FakeOrder(Base):
    """诱饵订单表：完全虚构的业务数据，仅用于诱饵层展示。"""

    __tablename__ = "fake_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uk_fake_orders_order_no"),
        Index("idx_fake_orders_user", "user_id", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "诱饵订单表：完全虚构的业务数据，含 120 条种子记录用于构造大结果集；"
                "仅用于诱饵层展示，不参与检测"
            ),
        },
    )

    order_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="诱饵订单编号",
    )
    order_no: Mapped[str] = mapped_column(
        ascii_bin(32),
        nullable=False,
        comment="虚构订单号，形如 FAKE-202611-00001",
    )
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "fake_users.id",
            name="fk_fake_orders_user",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="所属诱饵用户编号，引用 fake_users.id",
    )
    amount: Mapped[Decimal] = mapped_column(
        mysql.DECIMAL(12, 2),
        nullable=False,
        comment="虚构订单金额（元），精确小数，非负",
    )
    currency: Mapped[str] = mapped_column(
        ascii_char(3),
        nullable=False,
        server_default="CNY",
        comment="币种代码，默认 CNY",
    )
    order_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="paid",
        comment="订单状态：pending 待支付 / paid 已支付 / shipped 已发货 / cancelled 已取消 / refunded 已退款",
    )
    remark: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="虚构备注，用于构造更真实的大结果集响应",
    )
    is_synthetic: Mapped[int] = mapped_column(
        tinyint_bool(),
        nullable=False,
        server_default=text("1"),
        comment="合成标记，强制恒为 1",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="虚构下单时间（UTC）",
    )

    user: Mapped[FakeUser] = relationship(back_populates="orders", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<FakeOrder {self.order_no} {self.amount}>"


class FakeConfig(Base):
    """诱饵配置表：看似敏感但完全无效的配置项。"""

    __tablename__ = "fake_config"
    __table_args__ = (
        UniqueConstraint("config_key", name="uk_fake_config_config_key"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "诱饵配置表：看似敏感但完全无效的配置项；检查约束强制 config_value 以 TEST-ONLY 开头，"
                "禁止真实凭据入库"
            ),
        },
    )

    config_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="诱饵配置编号",
    )
    config_key: Mapped[str] = mapped_column(
        ascii_bin(64),
        nullable=False,
        comment="配置项键名，如 db.primary.connection_string",
    )
    config_value: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="无效的诱饵值，必须以 TEST-ONLY 开头；连接串只指向本机无效端口，密钥为占位串",
    )
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="配置分类：database 数据库 / mail 邮件 / api 第三方接口 / storage 对象存储",
    )
    description: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="配置项说明（中文），说明这是测试数据",
    )
    is_invalid: Mapped[int] = mapped_column(
        tinyint_bool(),
        nullable=False,
        server_default=text("1"),
        comment="无效标记，强制恒为 1",
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

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<FakeConfig {self.config_key}>"
