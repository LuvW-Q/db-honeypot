"""AI 只读辅助接口测试（可选增强，默认关闭）。"""

from __future__ import annotations

from shared.config import settings


async def test_ai_disabled_returns_503(client):
    """默认关闭时返回 503，且不影响其他接口。"""
    if settings.ai_enabled:
        settings.ai_enabled = False
    response = await client.post("/api/ai/ask", json={"question": "当前有多少告警？"})
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "SERVICE_UNAVAILABLE"


async def test_ai_enabled_uses_whitelist_template(client, monkeypatch):
    """开启后只执行白名单模板，并标记为辅助解释。"""
    monkeypatch.setattr(settings, "ai_enabled", True)
    response = await client.post("/api/ai/ask", json={"question": "当前有多少告警？"})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["template"] == "alert_summary"
    assert isinstance(body["rows"], list)
    assert "辅助解释" in body["note"]


async def test_ai_rejects_unknown_question_without_sql(client, monkeypatch):
    """无法匹配模板的问题不执行任何 SQL，只返回说明。"""
    monkeypatch.setattr(settings, "ai_enabled", True)
    response = await client.post(
        "/api/ai/ask", json={"question": "delete from attack_log"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["template"] is None
    assert body["rows"] == []
