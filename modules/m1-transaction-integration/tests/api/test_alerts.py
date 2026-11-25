"""告警列表与已读更新接口测试（契约 3.6 / 3.7）。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from shared.events.schema import EventStatus, EventType


async def _create_destructive_alert(db_session, event_factory, ingest_event) -> int:
    """写入 R05 事件并返回生成的 alert_id。"""
    source_ip = "198.51.100.210"
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip=source_ip,
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
        )
    )
    alert_id = (
        await db_session.execute(text("SELECT alert_id FROM alerts"))
    ).scalar_one()
    return int(alert_id)


async def test_alerts_empty_list(client):
    """空库：items=[]、total=0。"""
    response = await client.get("/api/alerts")
    body = response.json()
    assert response.status_code == 200
    assert body["items"] == []
    assert body["total"] == 0
    assert body["total_pages"] == 0
    assert response.headers["Cache-Control"] == "no-store"


async def test_alerts_list_fields(client, db_session, event_factory, ingest_event):
    """告警字段与证据完整（含 source_ip / rule_name / dedup_key / severity）。"""
    alert_id = await _create_destructive_alert(db_session, event_factory, ingest_event)

    body = (await client.get("/api/alerts")).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["alert_id"] == alert_id
    assert item["dedup_key"].startswith("R05:198.51.100.210:")
    assert item["alert_type"] == "destructive"
    assert item["severity"] == "critical"
    assert item["source_ip"] == "198.51.100.210"
    assert item["rule_code"] == "R05"
    assert item["rule_name"]
    assert item["latest_hit_id"] > 0
    assert item["occurrence_count"] == 1
    assert item["is_read"] is False
    assert item["read_at"] is None
    assert item["title"]
    assert item["evidence_summary"]
    assert item["first_seen_at"].endswith("Z")
    assert item["created_at"].endswith("Z")


async def test_alerts_filters(client, db_session, event_factory, ingest_event):
    """alert_type/severity/is_read 筛选；非法值 422。"""
    await _create_destructive_alert(db_session, event_factory, ingest_event)

    assert (await client.get("/api/alerts", params={"severity": "critical"})).json()["total"] == 1
    assert (await client.get("/api/alerts", params={"severity": "low"})).json()["total"] == 0
    assert (
        await client.get("/api/alerts", params={"alert_type": "destructive"})
    ).json()["total"] == 1
    assert (await client.get("/api/alerts", params={"is_read": "false"})).json()["total"] == 1
    assert (await client.get("/api/alerts", params={"is_read": "true"})).json()["total"] == 0

    bad_is_read = await client.get("/api/alerts", params={"is_read": "1"})
    assert bad_is_read.status_code == 422
    assert bad_is_read.json()["code"] == "VALIDATION_ERROR"

    bad_severity = await client.get("/api/alerts", params={"severity": "fatal"})
    assert bad_severity.status_code == 422

    bad_sort = await client.get("/api/alerts", params={"sort": "severity_rank"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "SORT_FIELD_INVALID"


async def test_alerts_time_range_filter(client, db_session, event_factory, ingest_event):
    """from/to 左闭右开；from > to 返回 TIME_RANGE_INVALID；非法格式 422。"""
    await _create_destructive_alert(db_session, event_factory, ingest_event)
    today = datetime.now(UTC).date().isoformat()

    in_range = await client.get("/api/alerts", params={"from": today, "to": today})
    # from 与 to 同一天时区间为 [00:00, 00:00)，左闭右开应为空
    assert in_range.status_code == 200
    assert in_range.json()["total"] == 0

    started = await client.get("/api/alerts", params={"from": today})
    assert started.json()["total"] == 1

    reversed_range = await client.get(
        "/api/alerts", params={"from": "2026-11-20", "to": "2026-11-19"}
    )
    assert reversed_range.status_code == 422
    assert reversed_range.json()["code"] == "TIME_RANGE_INVALID"

    bad_format = await client.get("/api/alerts", params={"from": "not-a-date"})
    assert bad_format.status_code == 422
    assert bad_format.json()["code"] == "TIME_RANGE_INVALID"


async def test_patch_alert_read_idempotent(
    client, db_session, event_factory, ingest_event
):
    """PATCH 已读：返回数据库实际状态；重复置已读不刷新 read_at；可撤回未读。"""
    alert_id = await _create_destructive_alert(db_session, event_factory, ingest_event)

    first = await client.patch(f"/api/alerts/{alert_id}", json={"is_read": True})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["is_read"] is True
    assert first_body["read_at"] is not None
    read_at = first_body["read_at"]

    second = await client.patch(f"/api/alerts/{alert_id}", json={"is_read": True})
    assert second.status_code == 200
    assert second.json()["read_at"] == read_at  # 幂等：不刷新时间

    unread = await client.patch(f"/api/alerts/{alert_id}", json={"is_read": False})
    assert unread.status_code == 200
    assert unread.json()["is_read"] is False
    assert unread.json()["read_at"] is None

    filtered = await client.get("/api/alerts", params={"is_read": "true"})
    assert filtered.json()["total"] == 0


async def test_patch_alert_writes_audit_log(
    client, db_session, event_factory, ingest_event
):
    """PATCH 成功写 audit_log(operation='alert_ack')。"""
    alert_id = await _create_destructive_alert(db_session, event_factory, ingest_event)
    await client.patch(f"/api/alerts/{alert_id}", json={"is_read": True})

    # db_session 先前的查询已开启 REPEATABLE READ 快照；先结束事务再读取
    # 接口提交的审计记录，避免快照读看不到新提交。
    await db_session.rollback()
    audit = (
        await db_session.execute(
            text(
                "SELECT operation, target_table, target_key, result, request_id "
                "FROM audit_log WHERE operation = 'alert_ack'"
            )
        )
    ).mappings().all()
    assert len(audit) == 1
    assert audit[0]["target_table"] == "alerts"
    assert audit[0]["target_key"] == str(alert_id)
    assert audit[0]["result"] == "success"
    assert audit[0]["request_id"]


async def test_patch_alert_validation_and_not_found(client):
    """请求体严格校验（缺字段/多余字段/非布尔）→ 422；不存在 → 404。"""
    missing = await client.patch("/api/alerts/1", json={})
    assert missing.status_code == 422
    assert missing.json()["code"] == "VALIDATION_ERROR"

    extra = await client.patch("/api/alerts/1", json={"is_read": True, "x": 1})
    assert extra.status_code == 422

    wrong_type = await client.patch("/api/alerts/1", json={"is_read": "true"})
    assert wrong_type.status_code == 422

    not_found = await client.patch("/api/alerts/999999", json={"is_read": True})
    assert not_found.status_code == 404
    body = not_found.json()
    assert body["code"] == "ALERT_NOT_FOUND"
    assert body["request_id"] == not_found.headers["X-Request-ID"]
