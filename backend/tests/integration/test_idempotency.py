"""幂等集成测试：同一 event_uuid 重复提交仅入库一次（SC-011）。"""

from __future__ import annotations

from sqlalchemy import text

from app.schemas.events import EventStatus, EventType
from tests.support import count_rows


async def test_repeated_event_uuid_ingested_once(db_session, event_factory, ingest_event):
    """同一事件重复提交 10 次：只 1 条日志，其余 duplicate=True，计数不重复累加。"""
    event = event_factory(
        event_type=EventType.CONNECT,
        source_ip="198.51.100.100",
        session_id="11111111-1111-4111-8111-111111111111",
    )

    results = [await ingest_event(event) for _ in range(10)]

    assert results[0].duplicate is False
    assert all(result.duplicate is True for result in results[1:])
    assert len({result.event_id for result in results}) == 1

    assert await count_rows(db_session, "attack_log") == 1
    assert await count_rows(db_session, "sessions") == 1
    assert await count_rows(db_session, "attacker_profile") == 1
    assert await count_rows(db_session, "attacker_intent") == 0

    session_row = (
        await db_session.execute(
            text(
                "SELECT request_count, max_risk_score FROM sessions "
                "WHERE session_id = :sid"
            ),
            {"sid": event.session_id},
        )
    ).mappings().one()
    assert int(session_row["request_count"]) == 1
    assert int(session_row["max_risk_score"]) == 0

    profile = (
        await db_session.execute(
            text(
                "SELECT total_connections, total_auth_attempts, total_queries "
                "FROM attacker_profile WHERE source_ip = :ip"
            ),
            {"ip": "198.51.100.100"},
        )
    ).mappings().one()
    assert int(profile["total_connections"]) == 1
    assert int(profile["total_auth_attempts"]) == 0
    assert int(profile["total_queries"]) == 0


async def test_repeated_query_event_does_not_repeat_rule_hit(
    db_session, event_factory, ingest_event
):
    """重复提交同一条 R03 事件：规则命中仍只有一条，风险分不翻倍。"""
    event = event_factory(
        event_type=EventType.QUERY,
        source_ip="198.51.100.101",
        session_id="22222222-2222-4222-8222-222222222222",
        sql_statement="SHOW TABLES",
        status=EventStatus.SUCCESS,
    )

    first = await ingest_event(event)
    assert [hit.rule_code for hit in first.rule_hits] == ["R03"]

    for _ in range(9):
        duplicate = await ingest_event(event)
        assert duplicate.duplicate is True
        assert duplicate.rule_hits == []

    assert await count_rows(db_session, "attack_log") == 1
    assert await count_rows(db_session, "rule_hits") == 1

    session_row = (
        await db_session.execute(
            text("SELECT max_risk_score FROM sessions WHERE session_id = :sid"),
            {"sid": event.session_id},
        )
    ).scalar_one()
    assert int(session_row) == 15

    profile_score = (
        await db_session.execute(
            text("SELECT risk_score FROM attacker_profile WHERE source_ip = :ip"),
            {"ip": "198.51.100.101"},
        )
    ).scalar_one()
    assert int(profile_score) == 15
