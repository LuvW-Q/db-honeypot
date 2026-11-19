"""通用响应模型：错误结构、分页与时间约定（对齐 contracts/api.md）。"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """统一返回带 UTC 时区的当前时间。"""
    return datetime.now(UTC)


def iso_utc(value: datetime | None) -> str | None:
    """把 datetime 序列化为 ISO 8601 UTC 字符串（以 Z 结尾）。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ErrorBody(BaseModel):
    """统一错误响应结构。"""

    code: str = Field(description="机器可读错误码，如 NOT_FOUND / VALIDATION_ERROR")
    message: str = Field(description="面向用户的中文错误信息")
    detail: object | None = Field(default=None, description="可选的字段级细节")
    request_id: str | None = Field(default=None, description="请求追踪编号")


class PageMeta(BaseModel):
    """分页元信息。"""

    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class Page[T](BaseModel):
    """通用分页响应。"""

    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class DatabaseHealth(BaseModel):
    """数据库健康状态。"""

    status: str = Field(description="ok / down")
    latency_ms: int | None = Field(default=None, description="探测耗时（毫秒）；down 时为 null")


class HoneypotHealth(BaseModel):
    """诱饵服务健康状态。"""

    status: str = Field(description="ok / down / disabled")
    listen: str | None = Field(default=None, description="host:port；disabled 时为 null")
    accepted_connections: int = Field(default=0, description="进程启动以来的累计连接数（内存计数）")


class HealthResponse(BaseModel):
    """健康检查响应（对齐 contracts/api.md 3.1）。"""

    status: str = Field(description="ok / degraded")
    version: str = "0.1.0"
    database: DatabaseHealth
    honeypot: HoneypotHealth
    generated_at: datetime = Field(default_factory=utc_now)
