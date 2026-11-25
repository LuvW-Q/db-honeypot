"""标准事件契约（捕获层 → 存储层）。

字段与 contracts/events.md 第 3 章、data-model.md 的 `attack_log` 对齐。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EventType(StrEnum):
    """事件类型枚举。"""

    CONNECT = "connect"
    AUTH = "auth"
    QUERY = "query"
    DISCONNECT = "disconnect"


class EventStatus(StrEnum):
    """事件处理结果枚举。"""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


class CapturedEvent(BaseModel):
    """捕获层产生的标准事件（尚未落库）。"""

    event_uuid: str = Field(description="幂等键，UUID v4 文本")
    session_id: str = Field(description="所属会话编号，UUID v4 文本")
    event_type: EventType
    source_ip: str = Field(max_length=45, description="客户端地址，兼容 IPv6")
    source_port: int | None = Field(default=None, ge=0, le=65535)
    username: str | None = Field(default=None, max_length=128)
    credential_test_id: str | None = Field(default=None, max_length=64)
    sql_statement: str | None = Field(default=None, max_length=65535)
    normalized_sql: str | None = Field(default=None, max_length=65535)
    event_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    returned_rows: int = Field(default=0, ge=0)
    response_ms: int = Field(default=0, ge=0)
    status: EventStatus = EventStatus.SUCCESS
    payload_truncated: bool = False
    client_info: str | None = Field(default=None, max_length=255)

    @field_validator("event_time", mode="before")
    @classmethod
    def _ensure_utc(cls, value: datetime | str) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class SessionInfo(BaseModel):
    """会话对外摘要。"""

    session_id: str
    source_ip: str
    source_port: int | None = None
    target_service: str
    started_at: datetime
    ended_at: datetime | None = None
    session_status: str
    request_count: int
    max_risk_score: int
    client_fingerprint: str | None = None


class IngestResult(BaseModel):
    """事件入库结果（幂等语义）。"""

    event_id: int
    session_id: str
    duplicate: bool = Field(description="True 表示 event_uuid 已存在，本次未新增记录")
    rule_hits: list[RuleHitSummary] = Field(default_factory=list)
    alerts: list[int] = Field(default_factory=list)


class RuleHitSummary(BaseModel):
    """规则命中摘要。"""

    rule_code: str
    rule_name: str
    intent_type: str
    risk_weight: int
    evidence_summary: str


class AnalysisResult(BaseModel):
    """分析结果汇总。"""

    rule_hits: list[RuleHitSummary] = Field(default_factory=list)
    alert_ids: list[int] = Field(default_factory=list)
    session_risk_score: int = 0
    profile_risk_score: int = 0
    intent_scores: dict[str, int] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


IngestResult.model_rebuild()
