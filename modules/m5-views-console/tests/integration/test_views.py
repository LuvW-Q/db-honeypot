"""核心分析视图集成测试：两来源 / 三会话 / 多日志下的计数与排序。

场景（所有事件都在 UTC 今日，事件时间相同以便稳定断言）：

- 会话 A（来源 ip1）：SHOW TABLES（R03/15） + DROP TABLE（R05/35，告警 critical）
  → 会话分 50、medium，命中编码 R03,R05；
- 会话 B（来源 ip1）：connect + 8 次失败认证（R02/25，告警 medium）→ 会话分 25；
- 会话 C（来源 ip2）：1 次返回 1000 行的 SELECT（R04/25，告警 high）→ 会话分 25。

因此：ip1 画像分 75（high）、ip2 画像分 25（low）；今日事件 12 条、告警 3 条。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from shared.events.schema import EventStatus, EventType

BASE = datetime.now(UTC).replace(microsecond=0, hour=12, minute=0, second=0)
IP1 = "198.51.100.160"
IP2 = "198.51.100.161"
SESSION_A = "d0000000-aaaa-4aaa-8aaa-00000000000a"
SESSION_B = "d0000000-bbbb-4bbb-8bbb-00000000000b"
SESSION_C = "d0000000-cccc-4ccc-8ccc-00000000000c"


async def _build_scenario(event_factory, ingest_event) -> None:
    """构造两来源三会话多日志的固定场景（全部经真实分析流水线）。"""
    # 会话 A：踩点 + 破坏性操作
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            session_id=SESSION_A,
            source_ip=IP1,
            sql_statement="SHOW TABLES",
            status=EventStatus.SUCCESS,
            event_time=BASE,
        )
    )
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            session_id=SESSION_A,
            source_ip=IP1,
            sql_statement="DROP TABLE fake_orders",
            status=EventStatus.DENIED,
            event_time=BASE,
        )
    )

    # 会话 B：连接 + 8 次多凭据失败认证（第 8 次触发 R02）
    await ingest_event(
        event_factory(
            event_type=EventType.CONNECT,
            session_id=SESSION_B,
            source_ip=IP1,
            event_time=BASE,
        )
    )
    for index in range(8):
        await ingest_event(
            event_factory(
                event_type=EventType.AUTH,
                session_id=SESSION_B,
                source_ip=IP1,
                username=f"cred_user_{index}",
                credential_test_id=f"TEST-ONLY-CRED-{index:02d}",
                status=EventStatus.FAILURE,
                event_time=BASE,
            )
        )

    # 会话 C：单次返回 1001 行的 SELECT（触发 R04 行数条件，严格大于 1000）
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            session_id=SESSION_C,
            source_ip=IP2,
            sql_statement="SELECT * FROM fake_orders",
            returned_rows=1001,
            status=EventStatus.SUCCESS,
            event_time=BASE,
        )
    )


async def test_v_session_risk_summary_counts_and_order(
    db_session, event_factory, ingest_event
):
    """会话风险汇总：会话数、重算风险分、命中编码与告警数。"""
    await _build_scenario(event_factory, ingest_event)

    rows = (
        await db_session.execute(
            text(
                """
                SELECT session_id, source_ip, event_count, query_count,
                       stored_request_count, calculated_risk_score, risk_level,
                       hit_rule_count, hit_rule_codes, alert_count
                FROM v_session_risk_summary
                ORDER BY calculated_risk_score DESC, session_id ASC
                """
            )
        )
    ).mappings().all()

    assert len(rows) == 3
    first = rows[0]
    assert first["session_id"] == SESSION_A
    assert int(first["event_count"]) == 2
    assert int(first["query_count"]) == 2
    assert int(first["stored_request_count"]) == 2
    assert int(first["calculated_risk_score"]) == 50
    assert first["risk_level"] == "medium"
    assert int(first["hit_rule_count"]) == 2
    assert first["hit_rule_codes"] == "R03,R05"
    assert int(first["alert_count"]) == 1

    session_b = next(row for row in rows if row["session_id"] == SESSION_B)
    assert int(session_b["event_count"]) == 9
    assert int(session_b["calculated_risk_score"]) == 25
    assert session_b["hit_rule_codes"] == "R02"
    assert int(session_b["alert_count"]) == 1

    session_c = next(row for row in rows if row["session_id"] == SESSION_C)
    assert int(session_c["event_count"]) == 1
    assert int(session_c["calculated_risk_score"]) == 25
    assert session_c["hit_rule_codes"] == "R04"

    # 存储分与视图重算分一致（无漂移）
    drift = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM v_session_risk_summary "
                "WHERE stored_max_risk_score <> calculated_risk_score"
            )
        )
    ).scalar_one()
    assert int(drift) == 0


async def test_v_attacker_profile_summary_counts_and_primary_intent(
    db_session, event_factory, ingest_event
):
    """攻击者画像汇总：来源数、会话/告警计数、重算风险分与主要意图。"""
    await _build_scenario(event_factory, ingest_event)

    rows = (
        await db_session.execute(
            text(
                """
                SELECT source_ip, session_count, alert_count, unread_alert_count,
                       stored_risk_score, calculated_risk_score, risk_level,
                       primary_intent_type, primary_intent_score, intent_labels
                FROM v_attacker_profile_summary
                ORDER BY calculated_risk_score DESC, source_ip ASC
                """
            )
        )
    ).mappings().all()
    assert len(rows) == 2

    ip1 = rows[0]
    assert ip1["source_ip"] == IP1
    assert int(ip1["session_count"]) == 2
    assert int(ip1["alert_count"]) == 2
    assert int(ip1["unread_alert_count"]) == 2
    assert int(ip1["stored_risk_score"]) == 75
    assert int(ip1["calculated_risk_score"]) == 75
    assert ip1["risk_level"] == "high"
    # 主要意图按分数排序：destructive(35) > bruteforce(25) > recon(15)
    assert ip1["primary_intent_type"] == "destructive"
    assert int(ip1["primary_intent_score"]) == 35
    assert ip1["intent_labels"] == "destructive,bruteforce,recon"

    ip2 = rows[1]
    assert ip2["source_ip"] == IP2
    assert int(ip2["session_count"]) == 1
    assert int(ip2["alert_count"]) == 1
    assert int(ip2["calculated_risk_score"]) == 25
    assert ip2["risk_level"] == "low"
    assert ip2["primary_intent_type"] == "data_dump"


async def test_v_daily_attack_trend_today_counts(
    db_session, event_factory, ingest_event
):
    """每日趋势：今日事件/会话/来源/查询/拒绝/告警与高等级告警计数。"""
    await _build_scenario(event_factory, ingest_event)

    row = (
        await db_session.execute(
            text(
                """
                SELECT stat_date, event_count, session_count, source_count,
                       query_count, denied_count, alert_count, high_level_alert_count,
                       cumulative_event_count, busy_day_rank
                FROM v_daily_attack_trend
                WHERE stat_date = :today
                """
            ),
            {"today": BASE.date()},
        )
    ).mappings().one()

    assert int(row["event_count"]) == 12
    assert int(row["session_count"]) == 3
    assert int(row["source_count"]) == 2
    assert int(row["query_count"]) == 3
    assert int(row["denied_count"]) == 1
    assert int(row["alert_count"]) == 3
    assert int(row["high_level_alert_count"]) == 2  # R05 critical + R04 high
    assert int(row["cumulative_event_count"]) == 12
    assert int(row["busy_day_rank"]) == 1


async def test_v_rule_effectiveness_counts_and_ranking(
    db_session, event_factory, ingest_event
):
    """规则效果：命中覆盖、告警数、命中率与排名。"""
    await _build_scenario(event_factory, ingest_event)

    rows = (
        await db_session.execute(
            text(
                """
                SELECT rule_code, hit_count, affected_session_count,
                       affected_event_count, affected_attacker_count,
                       used_version_count, alert_count, unread_alert_count,
                       alert_per_hit_ratio, hit_rank
                FROM v_rule_effectiveness
                ORDER BY hit_rank ASC, rule_code ASC
                """
            )
        )
    ).mappings().all()

    assert len(rows) == 5
    by_code = {row["rule_code"]: row for row in rows}

    assert int(by_code["R02"]["hit_count"]) == 1
    assert int(by_code["R02"]["alert_count"]) == 1
    assert float(by_code["R02"]["alert_per_hit_ratio"]) == 1.0
    assert int(by_code["R03"]["hit_count"]) == 1
    assert int(by_code["R03"]["alert_count"]) == 0
    assert float(by_code["R03"]["alert_per_hit_ratio"]) == 0.0
    assert int(by_code["R04"]["alert_count"]) == 1
    assert int(by_code["R05"]["alert_count"]) == 1
    assert int(by_code["R05"]["affected_attacker_count"]) == 1
    assert int(by_code["R05"]["used_version_count"]) == 1

    # R01 无命中：仍出现在效果视图（当前规则全集），排名末位
    assert int(by_code["R01"]["hit_count"]) == 0
    assert int(by_code["R01"]["hit_rank"]) == 5
    assert int(by_code["R01"]["alert_per_hit_ratio"]) == 0.0

    # 视图 RANK 口径为 hit_count DESC, rule_code ASC；4 条各命中 1 次的规则
    # 依编码稳定占据第 1–4 名，R01 无命中排第 5
    assert [row["rule_code"] for row in rows] == ["R02", "R03", "R04", "R05", "R01"]
    assert {row["rule_code"]: int(row["hit_rank"]) for row in rows} == {
        "R02": 1,
        "R03": 2,
        "R04": 3,
        "R05": 4,
        "R01": 5,
    }
