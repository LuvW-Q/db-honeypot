"""规则列表、版本变更与效果统计接口测试（契约 3.8 / 3.9 / 3.11）。"""

from __future__ import annotations

from sqlalchemy import text

from shared.events.schema import EventStatus, EventType

RULE_CODES = ["R01", "R02", "R03", "R04", "R05"]


async def test_rules_list_default_current_versions(client):
    """默认每个 rule_code 只返回当前版本：5 条、全部启用、参数结构齐全。"""
    response = await client.get("/api/rules")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 5
    codes = [item["rule_code"] for item in body["items"]]
    assert codes == RULE_CODES
    by_code = {item["rule_code"]: item for item in body["items"]}
    for code in RULE_CODES:
        assert by_code[code]["rule_version"] == 1
        assert by_code[code]["enabled"] is True
        assert isinstance(by_code[code]["parameters"], dict)
        assert by_code[code]["created_at"].endswith("Z")
    assert by_code["R01"]["parameters"]["window_seconds"] == 60
    assert by_code["R01"]["parameters"]["min_connect_count"] == 10
    assert by_code["R02"]["parameters"]["min_auth_attempts"] == 8
    assert by_code["R05"]["parameters"]["count_status"] == ["denied", "error", "success"]
    assert by_code["R03"]["rule_type"] == "keyword"


async def test_rules_list_enabled_filter(client):
    """enabled=true 返回全部启用规则；停用后该规则不再出现在筛选结果。"""
    enabled = (await client.get("/api/rules", params={"enabled": "true"})).json()
    assert enabled["total"] == 5

    disabled = (await client.get("/api/rules", params={"enabled": "false"})).json()
    assert disabled["total"] == 0


async def test_patch_rule_creates_new_version(client, db_session):
    """PATCH 生成新版本：版本 +1、previous_version 回显、旧版本被冻结、写审计。"""
    response = await client.patch(
        "/api/rules/R01",
        json={
            "risk_weight": 12,
            "expected_version": 1,
            "change_reason": "测试：调整扫描规则权重",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rule_code"] == "R01"
    assert body["rule_version"] == 2
    assert body["previous_version"] == 1
    assert body["risk_weight"] == 12
    assert body["enabled"] is True
    assert body["parameters"]["window_seconds"] == 60  # 未提供字段从旧版本复制

    current = (await client.get("/api/rules")).json()
    by_code = {item["rule_code"]: item for item in current["items"]}
    assert by_code["R01"]["rule_version"] == 2
    assert by_code["R01"]["risk_weight"] == 12
    assert current["total"] == 5

    history = (
        await client.get("/api/rules", params={"include_history": "true"})
    ).json()
    assert history["total"] == 6
    r01_versions = [
        item["rule_version"] for item in history["items"] if item["rule_code"] == "R01"
    ]
    assert r01_versions == [2, 1]

    rows = (
        await db_session.execute(
            text(
                "SELECT rule_version, enabled FROM detection_rules "
                "WHERE rule_code = 'R01' ORDER BY rule_version DESC"
            )
        )
    ).all()
    assert [tuple(row) for row in rows] == [(2, 1), (1, 0)]

    audit = (
        await db_session.execute(
            text("SELECT operation, target_key FROM audit_log WHERE operation = 'rule_change'")
        )
    ).mappings().all()
    assert len(audit) == 1
    assert audit[0]["target_key"] == "R01"


async def test_patch_rule_disable_and_reenable(client):
    """停用规则也生成新版本；enabled 筛选与列表状态同步。"""
    disabled = await client.patch(
        "/api/rules/R02", json={"enabled": False, "expected_version": 1}
    )
    assert disabled.status_code == 200
    assert disabled.json()["rule_version"] == 2
    assert disabled.json()["enabled"] is False

    enabled_rules = (await client.get("/api/rules", params={"enabled": "true"})).json()
    assert "R02" not in {item["rule_code"] for item in enabled_rules["items"]}

    reenabled = await client.patch(
        "/api/rules/R02", json={"enabled": True, "expected_version": 2}
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["rule_version"] == 3
    assert reenabled.json()["enabled"] is True


async def test_patch_rule_validation_errors(client):
    """空变更 / 权重越界 / 未知参数 / 参数类型错误 → 422。"""
    empty = await client.patch("/api/rules/R01", json={})
    assert empty.status_code == 422
    assert empty.json()["code"] == "VALIDATION_ERROR"

    out_of_range = await client.patch("/api/rules/R01", json={"risk_weight": 0})
    assert out_of_range.status_code == 422

    unknown_param = await client.patch(
        "/api/rules/R01", json={"parameters": {"unknown_key": 1}}
    )
    assert unknown_param.status_code == 422
    assert unknown_param.json()["code"] == "VALIDATION_ERROR"

    wrong_type = await client.patch(
        "/api/rules/R01", json={"parameters": {"window_seconds": "60"}}
    )
    assert wrong_type.status_code == 422


async def test_patch_rule_version_conflict_and_not_found(client):
    """expected_version 不一致 → 409 RULE_VERSION_CONFLICT；不存在规则 → 404。"""
    conflict = await client.patch(
        "/api/rules/R03", json={"risk_weight": 20, "expected_version": 99}
    )
    assert conflict.status_code == 409
    body = conflict.json()
    assert body["code"] == "RULE_VERSION_CONFLICT"
    assert body["detail"]["expected_version"] == 99
    assert body["detail"]["current_version"] == 1

    not_found = await client.patch("/api/rules/R06", json={"risk_weight": 20})
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "RULE_NOT_FOUND"

    invalid_code = await client.patch("/api/rules/R99", json={"risk_weight": 20})
    assert invalid_code.status_code == 422


async def test_rules_effectiveness_empty(client):
    """无命中时：5 条规则全部出现，命中数为 0，比率为 0。"""
    response = await client.get("/api/rules/effectiveness")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 5
    assert len(body["items"]) == 5
    for item in body["items"]:
        assert item["hit_count"] == 0
        assert item["affected_session_count"] == 0
        assert item["alert_count"] == 0
        assert item["alert_per_hit_ratio"] == 0.0
        assert item["first_hit_at"] is None
        assert item["last_hit_at"] is None
        assert item["is_enabled"] is True
        assert item["current_version"] == 1


async def test_rules_effectiveness_after_event(
    client, event_factory, ingest_event
):
    """R05 命中后：效果视图计数、告警数、比率与排名更新。"""
    await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip="198.51.100.220",
            sql_statement="DROP TABLE users",
            status=EventStatus.DENIED,
        )
    )

    body = (await client.get("/api/rules/effectiveness")).json()
    by_code = {item["rule_code"]: item for item in body["items"]}
    assert by_code["R05"]["hit_count"] == 1
    assert by_code["R05"]["alert_count"] == 1
    assert by_code["R05"]["unread_alert_count"] == 1
    assert by_code["R05"]["alert_per_hit_ratio"] == 1.0
    assert by_code["R05"]["hit_rank"] == 1
    assert by_code["R05"]["affected_attacker_count"] == 1
    assert by_code["R05"]["first_hit_at"].endswith("Z")
    assert by_code["R01"]["hit_count"] == 0

    limited = (
        await client.get("/api/rules/effectiveness", params={"limit": 2})
    ).json()
    assert limited["total"] == 5
    assert len(limited["items"]) == 2

    invalid_limit = await client.get("/api/rules/effectiveness", params={"limit": 0})
    assert invalid_limit.status_code == 422
