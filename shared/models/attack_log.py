"""`attack_log` 表 ORM 模型：标准事件表（连接/认证/查询/断开各一行）。

`event_uuid` 唯一约束是采集幂等的唯一权威（data-model 4.2 / contracts/events.md 第 4 章）；
`sql_statement`、`username` 等来自不可信输入，只存储不执行（安全不变量第 1 条）。

数据库级 CHECK 约束（`ck_attack_log_*`）由迁移 `0001_initial_schema` 定义。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base
from shared.models._types import (
    datetime6,
    int_unsigned,
    source_ip,
    tinyint_bool,
    uuid_char,
)

if TYPE_CHECKING:
    from shared.models.rule_hits import RuleHit
    from shared.models.sessions import Session


class AttackLog(Base):
    """标准事件表：一次连接/认证/查询/断开一行；SQL 与用户名为不可信数据，只存储不执行。"""

    __tablename__ = "attack_log"
    __table_args__ = (
        UniqueConstraint("event_uuid", name="uk_attack_log_event_uuid"),
        # 复合外键 fk_hit_log 的父索引，保证命中行的事件与会话同源
        UniqueConstraint("event_id", "session_id", name="uk_attack_log_event_session"),
        Index("idx_log_session_time", "session_id", "event_time"),
        Index("idx_log_source_time", "source_ip", "event_time"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_row_format": "DYNAMIC",
            "comment": (
                "标准事件表：一次连接/认证/查询/断开一行；event_uuid 唯一约束实现采集幂等；"
                "SQL 与用户名为不可信数据，只存储不执行"
            ),
        },
    )

    event_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="事件序号；全局单调递增，用于同时间戳事件的稳定排序",
    )
    event_uuid: Mapped[str] = mapped_column(
        uuid_char(),
        nullable=False,
        comment="采集事件幂等键（UUID v4 文本），重复提交时由唯一约束阻止重复入库并返回已有 event_id",
    )
    session_id: Mapped[str] = mapped_column(
        uuid_char(),
        ForeignKey(
            "sessions.session_id",
            name="fk_log_session",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment="所属会话编号，引用 sessions.session_id",
    )
    event_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="事件类型：connect 连接 / auth 认证 / query 查询或写操作 / disconnect 断开；无法识别的报文归入 query 且 status=error",
    )
    source_ip: Mapped[str] = mapped_column(
        source_ip(),
        nullable=False,
        comment="测试端来源地址；与会话行保持一致（写入事务内从会话复制，属受控反规范化）",
    )
    username: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="认证或查询使用的用户名；来自不可信输入，按 128 字符上限截断，超长时置 payload_truncated=1",
    )
    credential_test_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="合成凭据测试标识（如 TEST-ONLY-ACC-01），仅标识测试样本，任何情况下不保存口令明文或可逆凭据",
    )
    sql_statement: Mapped[str | None] = mapped_column(
        mysql.MEDIUMTEXT(),
        nullable=True,
        comment="原始 SQL 文本，只存储不执行；超过 65535 字符时截断并置 payload_truncated=1",
    )
    normalized_sql: Mapped[str | None] = mapped_column(
        mysql.MEDIUMTEXT(),
        nullable=True,
        comment="标准化 SQL（字面量替换为占位符、空白折叠、统一大小写）；供规则匹配与去重比较，不参与索引",
    )
    event_time: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        comment="事件发生时间（UTC），由捕获层在事件生成时确定并显式写入",
    )
    returned_rows: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="本次查询返回给客户端的行数；非查询事件为 0",
    )
    response_ms: Mapped[int] = mapped_column(
        int_unsigned(),
        nullable=False,
        server_default=text("0"),
        comment="模拟响应耗时（毫秒）；受控延迟场景记录实际等待时间",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="处理结果枚举：success 成功 / failure 认证失败或模拟失败 / denied 权限不足 / error 协议或语句错误",
    )
    payload_truncated: Mapped[int] = mapped_column(
        tinyint_bool(),
        nullable=False,
        server_default=text("0"),
        comment="载荷是否被截断：1 表示 SQL 或用户名超过长度上限并按策略截断，便于审计输入防线是否生效",
    )
    created_at: Mapped[datetime] = mapped_column(
        datetime6(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        comment="行落库时间（UTC），与 event_time 的差值可用于评估写入延迟",
    )

    session: Mapped[Session] = relationship(back_populates="events", lazy="selectin")
    hits: Mapped[list[RuleHit]] = relationship(
        back_populates="event",
        cascade="save-update, merge",
        overlaps="hits",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AttackLog {self.event_id} {self.event_type} {self.status}>"
