"""趋势接口测试（契约 3.10）：连续日历补齐、空库全 0、参数校验。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.events import EventStatus, EventType


async def test_trend_default_days_returns_continuous_calendar(client):
    """默认 14 天：返回连续、升序、全 0 的日历点。"""
    response = await client.get("/api/trend")

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 14
    assert len(body["items"]) == 14
    dates = [item["stat_date"] for item in body["items"]]
    assert dates == sorted(dates)
    assert [item["day_seq"] for item in body["items"]] == list(range(1, 15))
    assert all(item["event_count"] == 0 for item in body["items"])
    assert all(item["cumulative_event_count"] == 0 for item in body["items"])
    assert body["items"][-1]["stat_date"] == datetime.now(UTC).date().isoformat()
    assert body["items"][-1]["busy_day_rank"] == 1


async def test_trend_custom_days(client):
    """days=3 返回 3 个连续日历点，首项为今日前 2 天。"""
    body = (await client.get("/api/trend", params={"days": 3})).json()
    assert body["days"] == 3
    assert len(body["items"]) == 3
    today = datetime.now(UTC).date()
    assert body["items"][0]["stat_date"] == (today - timedelta(days=2)).isoformat()
    assert body["items"][-1]["stat_date"] == today.isoformat()


async def test_trend_counts_today_events(client, event_factory, ingest_event):
    """写入事件后，今日趋势点计数与视图一致。"""
    base = datetime.now(UTC).replace(microsecond=0)
    session_id = "aaaa0000-1111-4111-8111-000000000180"
    await ingest_event(
        event_factory(
            event_type=EventType.CONNECT,
            session_id=session_id,
            source_ip="198.51.100.180",
            event_time=base,
        )
    )
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            session_id=session_id,
            source_ip="198.51.100.180",
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
            event_time=base,
        )
    )

    body = (await client.get("/api/trend", params={"days": 1})).json()
    today = body["items"][-1]
    assert today["event_count"] == 2
    assert today["session_count"] == 1
    assert today["source_count"] == 1
    assert today["query_count"] == 1
    assert today["denied_count"] == 1
    assert today["alert_count"] == 1
    assert today["high_level_alert_count"] == 1


async def test_trend_rejects_out_of_range_days(client):
    """days 越界（0 / 91）→ 422 VALIDATION_ERROR 且带 request_id。"""
    for days in (0, 91):
        response = await client.get("/api/trend", params={"days": days})
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert isinstance(body["detail"], list)


async def test_trend_rejects_non_integer_days(client):
    """days 非整数 → 422。"""
    response = await client.get("/api/trend", params={"days": "abc"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
