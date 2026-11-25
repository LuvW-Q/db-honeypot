"""攻击者列表与详情接口测试（契约 3.3 / 3.4）。"""

from __future__ import annotations

import pytest

from shared.events.schema import EventStatus, EventType


async def _seed_two_attackers(event_factory, ingest_event) -> tuple[str, str]:
    """构造两个风险分不同的来源：destructive(35/medium) 与 recon(15/low)。"""
    ip_high = "198.51.100.190"
    ip_low = "198.51.100.191"
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip=ip_high,
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
        )
    )
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip=ip_low,
            sql_statement="SHOW TABLES",
        )
    )
    return ip_high, ip_low


async def test_attackers_empty_list(client):
    """空库：items=[]、total=0、total_pages=0。"""
    response = await client.get("/api/attackers")
    body = response.json()

    assert response.status_code == 200
    assert body == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }
    assert response.headers["Cache-Control"] == "no-store"


async def test_attackers_list_fields_and_sorting(
    client, event_factory, ingest_event
):
    """列表按风险分降序，契约字段齐全。"""
    ip_high, ip_low = await _seed_two_attackers(event_factory, ingest_event)

    response = await client.get("/api/attackers")
    body = response.json()

    assert body["total"] == 2
    assert body["total_pages"] == 1
    first, second = body["items"]
    assert first["source_ip"] == ip_high
    assert second["source_ip"] == ip_low
    assert first["risk_score"] == 35
    assert first["risk_level"] == "medium"
    assert first["alert_count"] == 1
    assert first["main_intent"]["intent_type"] == "destructive"
    assert first["main_intent"]["intent_score"] == 35
    assert second["risk_score"] == 15
    assert second["risk_level"] == "low"
    assert second["main_intent"]["intent_type"] == "recon"
    assert first["first_seen"].endswith("Z")
    assert first["last_seen"].endswith("Z")


async def test_attackers_filters(client, event_factory, ingest_event):
    """risk_level / intent_type 支持逗号分隔筛选；非法枚举 422。"""
    await _seed_two_attackers(event_factory, ingest_event)

    by_risk = (await client.get("/api/attackers", params={"risk_level": "medium"})).json()
    assert by_risk["total"] == 1
    assert by_risk["items"][0]["risk_level"] == "medium"

    combined = (
        await client.get("/api/attackers", params={"risk_level": "medium,low"})
    ).json()
    assert combined["total"] == 2

    by_intent = (
        await client.get("/api/attackers", params={"intent_type": "recon"})
    ).json()
    assert by_intent["total"] == 1
    assert by_intent["items"][0]["main_intent"]["intent_type"] == "recon"

    invalid = await client.get("/api/attackers", params={"risk_level": "bogus"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_ERROR"


async def test_attackers_sort_and_order_validation(client):
    """sort 白名单外 → SORT_FIELD_INVALID；order 非法 → VALIDATION_ERROR。"""
    invalid_sort = await client.get("/api/attackers", params={"sort": "drop_table"})
    assert invalid_sort.status_code == 422
    assert invalid_sort.json()["code"] == "SORT_FIELD_INVALID"

    invalid_order = await client.get("/api/attackers", params={"order": "sideways"})
    assert invalid_order.status_code == 422
    assert invalid_order.json()["code"] == "VALIDATION_ERROR"


async def test_attackers_pagination_beyond_last_page(client, event_factory, ingest_event):
    """页码超出范围不返回 404：items=[] + 真实 total。"""
    await _seed_two_attackers(event_factory, ingest_event)

    body = (await client.get("/api/attackers", params={"page": 99})).json()
    assert body["items"] == []
    assert body["total"] == 2
    assert body["total_pages"] == 1

    too_large = await client.get("/api/attackers", params={"page_size": 101})
    assert too_large.status_code == 422
    assert too_large.json()["code"] == "VALIDATION_ERROR"


async def test_attacker_detail_fields(client, event_factory, ingest_event):
    """详情：画像存储分与重算分一致、意图/会话/最近命中齐全。"""
    ip_high, _ = await _seed_two_attackers(event_factory, ingest_event)

    response = await client.get(f"/api/attackers/{ip_high}")
    assert response.status_code == 200
    body = response.json()

    attacker = body["attacker"]
    assert attacker["source_ip"] == ip_high
    assert attacker["risk_score"] == 35
    assert attacker["calculated_risk_score"] == 35
    assert attacker["risk_level"] == "medium"
    assert attacker["session_count"] == 1
    assert attacker["alert_count"] == 1
    assert attacker["unread_alert_count"] == 1
    assert attacker["triggered_rule_codes"] == "R05"
    assert attacker["evidence_summary"]
    assert 0 <= attacker["total_auth_failures"] <= attacker["total_auth_attempts"]

    assert [item["intent_type"] for item in body["intents"]] == ["destructive"]
    assert body["intents"][0]["intent_score"] == 35
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["risk_score"] == 35
    assert body["sessions"][0]["hit_rule_codes"] == "R05"
    assert len(body["recent_rule_hits"]) == 1
    assert body["recent_rule_hits"][0]["rule_code"] == "R05"
    assert body["recent_rule_hits"][0]["rule_version"] == 1
    assert body["recent_rule_hits"][0]["risk_weight"] == 35
    assert body["recent_rule_hits"][0]["evidence_summary"]


@pytest.mark.parametrize(
    ("ip", "expected_code"),
    [
        ("198.51.100.199", "ATTACKER_NOT_FOUND"),
        ("not-an-ip", "IP_FORMAT_INVALID"),
        ("999.999.999.999", "IP_FORMAT_INVALID"),
    ],
)
async def test_attacker_detail_errors(client, ip, expected_code):
    """合法但无画像 → 404 ATTACKER_NOT_FOUND；非法地址 → 422 IP_FORMAT_INVALID。"""
    response = await client.get(f"/api/attackers/{ip}")
    expected_status = 404 if expected_code == "ATTACKER_NOT_FOUND" else 422
    assert response.status_code == expected_status
    body = response.json()
    assert body["code"] == expected_code
    assert body["message"]
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_attacker_detail_limit_parameters(client, event_factory, ingest_event):
    """session_limit / hit_limit 越界 → 422。"""
    ip_high, _ = await _seed_two_attackers(event_factory, ingest_event)
    assert (
        await client.get(
            f"/api/attackers/{ip_high}", params={"session_limit": 0}
        )
    ).status_code == 422
    assert (
        await client.get(
            f"/api/attackers/{ip_high}", params={"hit_limit": 101}
        )
    ).status_code == 422
