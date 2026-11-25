"""迁移与结构集成测试：11 张表、4 个视图、关键索引、生成列与种子数据。"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.support import EXPECTED_TABLES, EXPECTED_VIEWS

# data-model 7.1 索引总表中的关键查询索引（0001 + 0003 合并后应全部存在）
REQUIRED_INDEXES: dict[str, set[str]] = {
    "sessions": {
        "idx_sessions_source_started",
        "idx_sessions_status_started",
        "idx_sessions_started",
    },
    "attack_log": {"idx_log_session_time", "idx_log_source_time"},
    "attacker_profile": {"idx_profile_risk"},
    "attacker_intent": {"idx_intent_type_score"},
    "detection_rules": {"idx_detection_rules_intent"},
    "rule_hits": {"idx_hit_event_session", "idx_hit_rule_time", "idx_hit_session_time"},
    "alerts": {
        "idx_alert_level_time",
        "idx_alert_type_time",
        "idx_alert_session_time",
        "idx_alert_attacker_time",
        "idx_alert_read_time",
        "idx_alert_latest_hit",
        "idx_alert_rule",
    },
    "fake_orders": {"idx_fake_orders_user"},
    "audit_log": {"idx_audit_time", "idx_audit_operation_time"},
}


async def test_all_eleven_tables_exist(db_session):
    """11 张物理业务表全部存在（外加 alembic_version）。"""
    rows = (
        await db_session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'honeypot_test' AND table_type = 'BASE TABLE'
                """
            )
        )
    ).scalars()
    tables = set(rows)
    assert EXPECTED_TABLES <= tables
    assert tables - EXPECTED_TABLES == {"alembic_version"}


async def test_four_views_exist_and_are_queryable(db_session):
    """4 个分析视图存在且可以查询（空库返回 0 行，不报错）。"""
    rows = (
        await db_session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = 'honeypot_test'
                """
            )
        )
    ).scalars()
    assert set(rows) == EXPECTED_VIEWS

    for view in sorted(EXPECTED_VIEWS):
        result = await db_session.execute(text(f"SELECT * FROM `{view}` LIMIT 1"))
        result.keys()  # 能拿到列名即结构可查询


async def test_alembic_version_is_head(db_session):
    """迁移链已到 0004_seed_rules。"""
    version = (
        await db_session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one()
    assert version == "0004_seed_rules"


async def test_key_indexes_exist(db_session):
    """data-model 7.1 的关键索引全部存在。"""
    rows = await db_session.execute(
        text(
            """
            SELECT table_name, index_name
            FROM information_schema.statistics
            WHERE table_schema = 'honeypot_test'
            """
        )
    )
    existing: dict[str, set[str]] = {}
    for table_name, index_name in rows:
        existing.setdefault(str(table_name), set()).add(str(index_name))

    missing: list[str] = []
    for table_name, required in REQUIRED_INDEXES.items():
        for index_name in required:
            if index_name not in existing.get(table_name, set()):
                missing.append(f"{table_name}.{index_name}")
    assert not missing, f"缺失索引：{missing}"


async def test_generated_columns_are_defined(db_session):
    """风险等级与启用规则编码为数据库生成列。"""
    rows = await db_session.execute(
        text(
            """
            SELECT table_name, column_name, extra
            FROM information_schema.columns
            WHERE table_schema = 'honeypot_test'
              AND ((table_name = 'attacker_profile' AND column_name = 'risk_level')
                OR (table_name = 'detection_rules' AND column_name = 'enabled_rule_code'))
            """
        )
    )
    extras = {(str(table), str(column)): str(extra).upper() for table, column, extra in rows}
    assert "GENERATED" in extras[("attacker_profile", "risk_level")]
    assert "GENERATED" in extras[("detection_rules", "enabled_rule_code")]


async def test_seed_rules_present(db_session):
    """迁移种子：R01–R05 各一条 v1、全部启用。"""
    rows = (
        await db_session.execute(
            text(
                "SELECT rule_code, rule_version, enabled FROM detection_rules "
                "ORDER BY rule_code"
            )
        )
    ).all()
    assert [tuple(row) for row in rows] == [
        ("R01", 1, 1),
        ("R02", 1, 1),
        ("R03", 1, 1),
        ("R04", 1, 1),
        ("R05", 1, 1),
    ]


async def test_fake_seed_tables_retained(db_session):
    """诱饵种子数据已导入且行数符合契约（30 / 120 / 5）。"""
    counts = {}
    for table in ("fake_users", "fake_orders", "fake_config"):
        counts[table] = int(
            (await db_session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
        )
    assert counts == {"fake_users": 30, "fake_orders": 120, "fake_config": 5}


@pytest.mark.parametrize(
    ("table", "column", "data_type"),
    [
        ("sessions", "session_id", "char"),
        ("sessions", "started_at", "datetime"),
        ("attack_log", "sql_statement", "mediumtext"),
        ("attack_log", "payload_truncated", "tinyint"),
        ("attacker_profile", "risk_score", "tinyint"),
        ("rule_hits", "evidence_summary", "varchar"),
        ("alerts", "dedup_key", "varchar"),
    ],
)
async def test_column_types_follow_data_model(db_session, table, column, data_type):
    """关键列类型符合 data-model 2.5 的类型选择规范。"""
    actual = (
        await db_session.execute(
            text(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'honeypot_test'
                  AND table_name = :table AND column_name = :column
                """
            ),
            {"table": table, "column": column},
        )
    ).scalar_one()
    assert str(actual).lower() == data_type


async def test_character_sets_for_identifier_columns(db_session):
    """UUID/编码列使用 ascii 字符集，中文载荷列为 utf8mb4。"""
    rows = await db_session.execute(
        text(
            """
            SELECT table_name, column_name, character_set_name
            FROM information_schema.columns
            WHERE table_schema = 'honeypot_test'
              AND ((table_name = 'sessions' AND column_name = 'session_id')
                OR (table_name = 'attack_log' AND column_name = 'sql_statement')
                OR (table_name = 'alerts' AND column_name = 'dedup_key'))
            """
        )
    )
    charsets = {(str(t), str(c)): cs for t, c, cs in rows}
    assert charsets[("sessions", "session_id")] == "ascii"
    assert charsets[("alerts", "dedup_key")] == "ascii"
    assert charsets[("attack_log", "sql_statement")] == "utf8mb4"
