"""健康检查接口测试（契约 3.1）。"""

from __future__ import annotations

import re
import uuid

from app.schemas.common import HealthResponse

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


async def test_health_returns_ok_and_database_status(client):
    """健康检查：数据库连通、诱饵状态可读、返回版本与请求编号。"""
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["database"]["status"] == "ok"
    assert isinstance(body["database"]["latency_ms"], int)
    assert body["honeypot"]["status"] in {"ok", "down"}
    assert body["honeypot"]["listen"].startswith("127.0.0.1:")
    assert isinstance(body["honeypot"]["accepted_connections"], int)
    assert isinstance(body["version"], str) and body["version"]
    assert _UUID_RE.match(response.headers["X-Request-ID"])


async def test_health_request_id_header_is_uuid(client):
    """X-Request-ID 为 UUID 且不同请求不同。"""
    first = await client.get("/api/health")
    second = await client.get("/api/health")
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    uuid.UUID(first.headers["X-Request-ID"])


async def test_health_pydantic_schema_matches_implementation(client):
    """响应可被 HealthResponse 模型解析（实现层字段）。"""
    body = (await client.get("/api/health")).json()
    parsed = HealthResponse(**body)
    assert parsed.database.status == "ok"
    assert parsed.status in {"ok", "degraded"}


async def test_health_contract_nested_shape(client):
    """契约要求 database/honeypot 为嵌套对象，且含 latency_ms/listen 等字段。"""
    body = (await client.get("/api/health")).json()
    assert isinstance(body["database"], dict)
    assert "latency_ms" in body["database"]
    assert isinstance(body["honeypot"], dict)
    assert "listen" in body["honeypot"]


async def test_unmatched_route_returns_standard_error(client):
    """未注册路径返回统一错误结构（code/message/detail/request_id）。"""
    response = await client.get("/api/not-exists")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert isinstance(body["message"], str) and body["message"]
    assert body["request_id"] == response.headers["X-Request-ID"]
