"""会话时间线接口测试（契约 3.5）：排序、脱敏、证据与 404。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared.events.schema import EventStatus, EventType


async def test_timeline_unknown_session_returns_404(client):
    """不存在的会话 → 404 SESSION_NOT_FOUND（统一错误结构）。"""
    response = await client.get(
        "/api/sessions/00000000-0000-4000-8000-000000000000/timeline"
    )
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "SESSION_NOT_FOUND"
    assert body["detail"]["session_id"] == "00000000-0000-4000-8000-000000000000"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_timeline_event_order_and_masking(client, event_factory, ingest_event):
    """事件按 event_time/event_id 升序；用户名脱敏、认证事件固定凭据掩码。"""
    session_id = "f0000000-1111-4111-8111-000000000001"
    source_ip = "198.51.100.200"
    base = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)

    connect = await ingest_event(
        event_factory(
            event_type=EventType.CONNECT,
            session_id=session_id,
            source_ip=source_ip,
            client_info="mysql-cli/8.4.0",
            event_time=base,
        )
    )
    auth = await ingest_event(
        event_factory(
            event_type=EventType.AUTH,
            session_id=session_id,
            source_ip=source_ip,
            username="suspicious_user",
            credential_test_id="TEST-ONLY-ACC-01",
            status=EventStatus.FAILURE,
            event_time=base + timedelta(seconds=1),
        )
    )
    query = await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            session_id=session_id,
            source_ip=source_ip,
            username="suspicious_user",
            sql_statement="SHOW TABLES",
            status=EventStatus.SUCCESS,
            event_time=base + timedelta(seconds=2),
        )
    )

    response = await client.get(f"/api/sessions/{session_id}/timeline")
    assert response.status_code == 200
    body = response.json()

    header = body["session"]
    assert header["session_id"] == session_id
    assert header["client_fingerprint"] == "mysql-cli/8.4.0"
    assert header["request_count"] == 3
    assert header["event_count"] == 3
    assert header["query_count"] == 1
    assert header["max_risk_score"] == 15
    assert header["calculated_risk_score"] == 15
    assert header["risk_level"] == "low"
    assert header["alert_count"] == 0
    assert header["session_status"] == "active"
    assert header["ended_at"] is None

    events = body["events"]
    assert [event["event_id"] for event in events] == [
        connect.event_id,
        auth.event_id,
        query.event_id,
    ]
    assert [event["event_type"] for event in events] == ["connect", "auth", "query"]
    times = [event["event_time"] for event in events]
    assert times == sorted(times)

    auth_event = events[1]
    assert auth_event["username"] != "suspicious_user"
    assert "*" in auth_event["username"]
    assert auth_event["username"].startswith("su")
    assert auth_event["username"].endswith("er")
    assert auth_event["credential_masked"] == "****"
    assert auth_event["credential_test_id"] == "TEST-ONLY-ACC-01"
    assert auth_event["status"] == "failure"

    query_event = events[2]
    assert query_event["credential_masked"] is None
    assert query_event["sql_statement"] == "SHOW TABLES"
    assert query_event["normalized_sql"] == "show tables"
    assert query_event["statement_type"] == "SHOW"
    assert query_event["payload_truncated"] is False

    connect_event = events[0]
    assert connect_event["sql_statement"] is None
    assert connect_event["statement_type"] is None

    assert body["rule_hits"][0]["rule_code"] == "R03"
    assert body["alerts"] == []
    assert body["events_truncated"] is False

    # 脱敏红线：接口任何位置都不得出现口令明文/可逆凭据
    raw = response.text
    assert "TestOnly" not in raw  # 仓库内所有测试口令均以 TestOnly 前缀标识
    assert "password" not in raw.lower()
    assert '"credential_masked":"****"' in raw  # Starlette 紧凑 JSON 分隔符


async def test_timeline_with_alert_and_rule_hit(client, event_factory, ingest_event):
    """破坏性操作会话：时间线包含规则证据与告警摘要。"""
    session_id = "f0000000-2222-4222-8222-000000000002"
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            session_id=session_id,
            source_ip="198.51.100.201",
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
        )
    )

    body = (await client.get(f"/api/sessions/{session_id}/timeline")).json()
    assert len(body["rule_hits"]) == 1
    hit = body["rule_hits"][0]
    assert hit["rule_code"] == "R05"
    assert hit["intent_type"] == "destructive"
    assert hit["rule_version"] == 1
    assert hit["risk_weight"] == 35
    assert hit["evidence_summary"]

    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    assert alert["alert_type"] == "destructive"
    assert alert["severity"] == "critical"
    assert alert["occurrence_count"] == 1
    assert alert["is_read"] is False
    assert alert["created_at"].endswith("Z")


async def test_timeline_empty_related_arrays(client, event_factory, ingest_event):
    """会话存在但无命中/告警时，rule_hits 与 alerts 返回空数组。"""
    session_id = "f0000000-3333-4333-8333-000000000003"
    await ingest_event(
        event_factory(
            event_type=EventType.CONNECT,
            session_id=session_id,
            source_ip="198.51.100.202",
        )
    )

    body = (await client.get(f"/api/sessions/{session_id}/timeline")).json()
    assert body["rule_hits"] == []
    assert body["alerts"] == []
    assert len(body["events"]) == 1
