"""测试共享辅助函数：直接向真实数据库插入测试数据（不做 Mock）。

这些函数只服务于测试（不进入应用路径），用于构造规则判定、视图与约束测试所需的
最小数据行；业务行为仍由被测代码真实执行。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import AttackLog, DetectionRule
from shared.models import Session as SessionRow
from shared.utils.sql import normalize_sql

# 迁移后应存在的 11 张物理表（不含视图与 alembic_version）
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "sessions",
        "attack_log",
        "attacker_profile",
        "attacker_intent",
        "detection_rules",
        "rule_hits",
        "alerts",
        "fake_users",
        "fake_orders",
        "fake_config",
        "audit_log",
    }
)

# 4 个只读分析视图
EXPECTED_VIEWS: frozenset[str] = frozenset(
    {
        "v_session_risk_summary",
        "v_attacker_profile_summary",
        "v_daily_attack_trend",
        "v_rule_effectiveness",
    }
)

async def get_enabled_rule(db: AsyncSession, rule_code: str) -> DetectionRule:
    """按规则编码取当前启用版本（种子 v1）。"""
    rule = (
        await db.execute(
            select(DetectionRule).where(
                DetectionRule.rule_code == rule_code,
                DetectionRule.enabled == 1,
            )
        )
    ).scalar_one_or_none()
    assert rule is not None, f"未找到启用规则 {rule_code}"
    return rule


def utc_now() -> datetime:
    """当前 UTC 时间，截断到秒（与事件时间口径一致）。"""
    return datetime.now(UTC).replace(microsecond=0)


async def insert_session(
    db: AsyncSession,
    *,
    source_ip: str = "192.0.2.10",
    session_id: str | None = None,
    started_at: datetime | None = None,
    session_status: str = "active",
    request_count: int = 0,
    max_risk_score: int = 0,
    target_service: str = "mysql-honeypot",
) -> SessionRow:
    """插入一条会话行并 flush（返回 ORM 行）。"""
    row = SessionRow(
        session_id=session_id or str(uuid4()),
        source_ip=source_ip,
        source_port=51234,
        target_service=target_service,
        started_at=started_at or utc_now(),
        session_status=session_status,
        request_count=request_count,
        max_risk_score=max_risk_score,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_attack_log(
    db: AsyncSession,
    *,
    session: SessionRow,
    event_type: str = "query",
    event_time: datetime | None = None,
    source_ip: str | None = None,
    status: str = "success",
    sql_statement: str | None = None,
    username: str | None = None,
    credential_test_id: str | None = None,
    returned_rows: int = 0,
    response_ms: int = 0,
    payload_truncated: int = 0,
    event_uuid: str | None = None,
) -> AttackLog:
    """插入一条攻击日志行并 flush（normalized_sql 由 utils.sql 统一归一化）。"""
    row = AttackLog(
        event_uuid=event_uuid or str(uuid4()),
        session_id=session.session_id,
        event_type=event_type,
        source_ip=(source_ip or session.source_ip),
        username=username,
        credential_test_id=credential_test_id,
        sql_statement=sql_statement,
        normalized_sql=normalize_sql(sql_statement),
        event_time=event_time or utc_now(),
        returned_rows=max(0, returned_rows),
        response_ms=max(0, response_ms),
        status=status,
        payload_truncated=payload_truncated,
    )
    db.add(row)
    await db.flush()
    return row


async def count_rows(db: AsyncSession, table: str) -> int:
    """统计指定表的行数（表名来自测试内固定白名单，不接受外部输入）。"""
    return int(
        (await db.execute(text(f"SELECT COUNT(*) FROM `{table}`"))).scalar_one() or 0
    )


async def fetch_all(db: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> list:
    """执行只读查询并返回全部行（测试断言辅助）。"""
    result = await db.execute(text(sql), params or {})
    return result.mappings().all()


async def fetch_one(db: AsyncSession, sql: str, params: dict[str, Any] | None = None):
    """执行只读查询并返回首行（测试断言辅助）。"""
    result = await db.execute(text(sql), params or {})
    return result.mappings().first()


class RuleStub:
    """规则行替身：仅提供 ``rule_code`` 与 ``parameters``（用于参数边界测试）。

    注意：这不是数据库 Mock —— 判定逻辑仍在真实数据库上执行，这里只替换
    ``detection_rules`` 的一行配置对象，用于构造种子之外的阈值组合。
    """

    def __init__(self, rule_code: str, parameters: dict[str, Any]) -> None:
        self.rule_code = rule_code
        self.parameters = parameters
