"""概览接口测试（契约 3.2）：空库全 0、造数后计数与只读响应头。"""

from __future__ import annotations

import re

from shared.events.schema import EventStatus, EventType

_UTC_SECONDS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


async def test_overview_empty_database_returns_zeros(client):
    """空库：四项指标全 0，不返回 404/500。"""
    response = await client.get("/api/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["sessions"] == 0
    assert body["queries"] == 0
    assert body["alerts"] == 0
    assert body["high_risk_attackers"] == 0
    assert _UTC_SECONDS_RE.match(body["generated_at"])
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]


async def test_overview_counts_after_destructive_event(
    client, event_factory, ingest_event
):
    """写入 R05 事件后：会话/查询/告警各 1，高风险攻击者仍为 0（35 分 medium）。"""
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip="198.51.100.170",
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
        )
    )

    response = await client.get("/api/overview")
    body = response.json()

    assert body["sessions"] == 1
    assert body["queries"] == 1
    assert body["alerts"] == 1
    assert body["high_risk_attackers"] == 0


async def test_overview_high_risk_attacker_count(client, event_factory, ingest_event):
    """命中 R05+R03 的来源画像 50 分仍非高风险；再叠加 R02 达 75 分后计为高风险。"""
    source_ip = "198.51.100.171"
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip=source_ip,
            sql_statement="SHOW TABLES",
        )
    )
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip=source_ip,
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
        )
    )
    # 8 次失败认证触发 R02（25），画像分 15+35+25 = 75 → high
    session_id = "eeeeeeee-5555-4555-8555-555555555555"
    for index in range(8):
        await ingest_event(
            event_factory(
                event_type=EventType.AUTH,
                session_id=session_id,
                source_ip=source_ip,
                username=f"api_user_{index}",
                credential_test_id=f"TEST-ONLY-API-{index:02d}",
                status=EventStatus.FAILURE,
            )
        )

    body = (await client.get("/api/overview")).json()
    assert body["high_risk_attackers"] == 1
    assert body["alerts"] == 2  # R05 critical + R02 medium
