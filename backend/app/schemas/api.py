"""控制台 API 的 Pydantic 响应模型（严格对齐 contracts/api.md）。

约定：

- 字段名一律 `snake_case`，与数据库列名/视图列名一致（契约 1.1 字段名一致性约定）；
- 时间字段统一序列化为 ISO 8601 UTC、秒级精度、以 `Z` 结尾（契约 1.5）；
- 列表接口统一分页信封 `{items, page, page_size, total, total_pages}`（契约 1.4）；
- 空数据时数组字段返回 `[]`、可空标量返回 `null`，不得省略字段（契约 1.6）。

此外，本模块提供两个 API 层横切辅助（受写入范围限制，未放进 `api/errors.py`）：

- `ContractApiError`：带显式 HTTP 状态码的 `ApiError` 子类，用于契约中的细分
  404/409/422 错误码（`SESSION_NOT_FOUND` 等）；仍由全局异常处理器统一渲染；
- `request_context`：路由级依赖，生成 `request_id` 并设置 `Cache-Control: no-store`。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import Request, Response
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
)

from app.api.errors import ApiError

# ---------------------------------------------------------------------------
# 时间序列化：数据库 DATETIME(6) 为 UTC 朴素时间，这里统一补时区并截断到秒
# ---------------------------------------------------------------------------


def ensure_utc(value: datetime) -> datetime:
    """把朴素 datetime 视为 UTC，带时区值统一转换为 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc_seconds(value: datetime | None) -> str | None:
    """序列化为契约要求的 `2026-11-19T12:30:48Z`（秒级、Z 结尾）。"""
    if value is None:
        return None
    return ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


#: 统一 UTC 时间字段类型：入参补时区，出参固定 ISO8601 UTC 秒级字符串
UtcTime = Annotated[
    datetime,
    BeforeValidator(ensure_utc),
    PlainSerializer(iso_utc_seconds, return_type=str),
]

#: 日期字段（趋势统计日）固定 `YYYY-MM-DD`
StatDate = Annotated[
    date,
    PlainSerializer(lambda value: value.isoformat(), return_type=str),
]


# ---------------------------------------------------------------------------
# API 层错误辅助（errors.py 不在本次写入范围，故用子类指定契约状态码）
# ---------------------------------------------------------------------------


class ContractApiError(ApiError):
    """带显式 HTTP 状态码的业务异常。

    全局 `register_exception_handlers` 会捕获 `ApiError` 并读取 `status_code`，
    因此本子类仍走统一错误结构，只是把契约中细分的 404/409/422 码映射到正确状态。
    """

    def __init__(
        self,
        code: str,
        message: str,
        detail: object | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(code, message, detail)
        self._status_code = status_code

    @property
    def status_code(self) -> int:  # type: ignore[override]
        return self._status_code


def not_found(code: str, message: str, detail: object | None = None) -> ContractApiError:
    """构造 404 业务异常（SESSION/ATTACKER/ALERT/RULE_NOT_FOUND）。"""
    return ContractApiError(code, message, detail, status_code=404)


def unprocessable(
    code: str = "VALIDATION_ERROR",
    message: str = "请求参数校验失败",
    detail: object | None = None,
) -> ContractApiError:
    """构造 422 业务异常（VALIDATION_ERROR/SORT_FIELD_INVALID/TIME_RANGE_INVALID 等）。"""
    return ContractApiError(code, message, detail, status_code=422)


def conflict(code: str, message: str, detail: object | None = None) -> ContractApiError:
    """构造 409 业务异常（RULE_VERSION_CONFLICT）。"""
    return ContractApiError(code, message, detail, status_code=409)


async def request_context(request: Request, response: Response) -> None:
    """路由级依赖：补齐请求编号与只读缓存策略。

    契约 1.1 要求每个响应带 `X-Request-ID`、只读接口带 `Cache-Control: no-store`。
    `api/errors.py` 从 `request.state.request_id` 取编号，这里在进入处理逻辑前写入，
    后续错误处理器即可回填同一编号。
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    request.state.request_id = request_id
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------


class OverviewResponse(BaseModel):
    """GET /api/overview 响应：首页四项指标（契约 3.2）。"""

    sessions: int = Field(ge=0, description="会话总数")
    queries: int = Field(ge=0, description="查询事件总数")
    alerts: int = Field(ge=0, description="告警总数")
    high_risk_attackers: int = Field(
        ge=0, description="高风险攻击者数（risk_level 为 high/critical）"
    )
    generated_at: UtcTime = Field(description="响应生成时间（UTC）")


class TrendPoint(BaseModel):
    """每日趋势点（契约 3.10，补日后的连续日历）。"""

    stat_date: StatDate = Field(description="UTC 统计日 YYYY-MM-DD")
    day_seq: int = Field(ge=1, description="返回序列内连续序号，从 1 开始")
    event_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    query_count: int = Field(ge=0)
    denied_count: int = Field(ge=0)
    alert_count: int = Field(ge=0)
    high_level_alert_count: int = Field(ge=0)
    prev_event_count: int | None = Field(default=None, description="上一个有事件日的事件数")
    event_count_delta: int | None = Field(default=None)
    event_change_pct: float | None = Field(default=None)
    cumulative_event_count: int = Field(ge=0)
    busy_day_rank: int = Field(ge=1)


class TrendResponse(BaseModel):
    """GET /api/trend 响应。"""

    days: int = Field(ge=1)
    items: list[TrendPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 攻击者列表与详情
# ---------------------------------------------------------------------------


class IntentBrief(BaseModel):
    """主要意图摘要（列表页 `main_intent`）。"""

    intent_type: str
    intent_score: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    last_detected_at: UtcTime


class AttackerListItem(BaseModel):
    """攻击者列表行（契约 3.3）。"""

    attacker_id: int
    source_ip: str
    first_seen: UtcTime
    last_seen: UtcTime
    total_connections: int = Field(ge=0)
    total_auth_attempts: int = Field(ge=0)
    total_queries: int = Field(ge=0)
    main_intent: IntentBrief | None = None
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    alert_count: int = Field(ge=0)


class AttackerListResponse(BaseModel):
    """GET /api/attackers 分页响应。"""

    items: list[AttackerListItem] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class AttackerProfile(BaseModel):
    """攻击者画像统计（详情页 `attacker`）。"""

    attacker_id: int
    source_ip: str
    first_seen: UtcTime
    last_seen: UtcTime
    total_connections: int = Field(ge=0)
    total_auth_attempts: int = Field(ge=0)
    total_auth_failures: int = Field(ge=0)
    total_queries: int = Field(ge=0)
    risk_score: int = Field(ge=0, le=100, description="画像存储风险分")
    calculated_risk_score: int = Field(ge=0, le=100, description="视图重算风险分")
    risk_level: str
    session_count: int = Field(ge=0)
    high_risk_session_count: int = Field(ge=0)
    alert_count: int = Field(ge=0)
    unread_alert_count: int = Field(ge=0)
    intent_labels: str | None = None
    triggered_rule_codes: str | None = None
    evidence_summary: str | None = None


class IntentItem(BaseModel):
    """意图明细行（详情页 `intents`）。"""

    intent_type: str
    intent_score: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    first_detected_at: UtcTime
    last_detected_at: UtcTime


class SessionSummary(BaseModel):
    """攻击者详情页的会话摘要（取自 `v_session_risk_summary`）。"""

    session_id: str
    source_port: int | None = None
    target_service: str
    started_at: UtcTime
    ended_at: UtcTime | None = None
    session_status: str
    event_count: int = Field(ge=0)
    query_count: int = Field(ge=0)
    hit_rule_count: int = Field(ge=0)
    hit_rule_codes: str | None = None
    risk_score: int = Field(ge=0, le=100, description="会话重算风险分")
    risk_level: str
    stored_max_risk_score: int = Field(ge=0, le=100)
    alert_count: int = Field(ge=0)


class RuleHitItem(BaseModel):
    """规则命中证据行（详情页/时间线共用）。"""

    hit_id: int
    event_id: int
    rule_code: str
    rule_name: str
    intent_type: str
    rule_version: int = Field(ge=1)
    risk_weight: int = Field(ge=0, le=100)
    triggered_at: UtcTime
    evidence_summary: str


class AttackerDetailResponse(BaseModel):
    """GET /api/attackers/{ip} 响应（契约 3.4）。"""

    attacker: AttackerProfile
    intents: list[IntentItem] = Field(default_factory=list)
    sessions: list[SessionSummary] = Field(default_factory=list)
    recent_rule_hits: list[RuleHitItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 会话时间线
# ---------------------------------------------------------------------------


class TimelineSession(BaseModel):
    """时间线会话头（契约 3.5 `session`）。"""

    session_id: str
    source_ip: str
    source_port: int | None = None
    target_service: str
    client_fingerprint: str | None = None
    started_at: UtcTime
    ended_at: UtcTime | None = None
    session_status: str
    request_count: int = Field(ge=0, description="sessions.request_count 存储值")
    event_count: int = Field(ge=0, description="视图重算事件数")
    query_count: int = Field(ge=0)
    max_risk_score: int = Field(ge=0, le=100, description="sessions.max_risk_score 存储值")
    calculated_risk_score: int = Field(ge=0, le=100)
    risk_level: str
    alert_count: int = Field(ge=0)


class TimelineEvent(BaseModel):
    """时间线事件（契约 3.5 `events[]`，username 已脱敏）。"""

    event_id: int
    event_uuid: str
    event_type: str
    event_time: UtcTime
    source_ip: str
    username: str | None = None
    credential_test_id: str | None = None
    credential_masked: str | None = None
    sql_statement: str | None = None
    normalized_sql: str | None = None
    statement_type: str | None = None
    returned_rows: int = Field(ge=0)
    response_ms: int = Field(ge=0)
    status: str
    payload_truncated: bool = False


class TimelineAlert(BaseModel):
    """时间线告警（契约 3.5 `alerts[]`）。"""

    alert_id: int
    alert_type: str
    severity: str
    title: str
    occurrence_count: int = Field(ge=0)
    created_at: UtcTime
    is_read: bool


class TimelineResponse(BaseModel):
    """GET /api/sessions/{session_id}/timeline 响应（契约 3.5）。"""

    session: TimelineSession
    events: list[TimelineEvent] = Field(default_factory=list)
    rule_hits: list[RuleHitItem] = Field(default_factory=list)
    alerts: list[TimelineAlert] = Field(default_factory=list)
    events_truncated: bool = False


# ---------------------------------------------------------------------------
# 告警
# ---------------------------------------------------------------------------


class AlertItem(BaseModel):
    """告警行（契约 3.6，列表与 PATCH 返回结构一致）。"""

    alert_id: int
    dedup_key: str
    session_id: str
    attacker_id: int
    source_ip: str
    rule_code: str
    rule_name: str
    latest_hit_id: int
    alert_type: str
    severity: str
    title: str
    evidence_summary: str
    first_seen_at: UtcTime
    last_seen_at: UtcTime
    occurrence_count: int = Field(ge=0)
    created_at: UtcTime
    is_read: bool
    read_at: UtcTime | None = None


class AlertListResponse(BaseModel):
    """GET /api/alerts 分页响应。"""

    items: list[AlertItem] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class AlertUpdateRequest(BaseModel):
    """PATCH /api/alerts/{alert_id} 请求体：严格模式，只接受 JSON 布尔。"""

    model_config = ConfigDict(extra="forbid")

    is_read: StrictBool = Field(description="已读状态，只能是 JSON 布尔 true/false")


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------


class RuleItem(BaseModel):
    """规则当前版本（契约 3.8）。"""

    rule_id: int
    rule_code: str
    rule_name: str
    rule_type: str
    intent_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_weight: int = Field(ge=0, le=100)
    rule_version: int = Field(ge=1)
    enabled: bool
    description: str | None = None
    created_at: UtcTime
    updated_at: UtcTime


class RuleListResponse(BaseModel):
    """GET /api/rules 响应。"""

    items: list[RuleItem] = Field(default_factory=list)
    total: int = Field(ge=0)


class RuleUpdateRequest(BaseModel):
    """PATCH /api/rules/{rule_code} 请求体（严格模式，至少提供一项变更）。"""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool | None = None
    parameters: dict[str, Any] | None = None
    risk_weight: int | None = Field(default=None, ge=1, le=100)
    expected_version: int | None = Field(default=None, ge=1)
    change_reason: str | None = Field(default=None, max_length=200)


class RuleUpdateResponse(RuleItem):
    """PATCH /api/rules/{rule_code} 响应：新版本对象 + 上一版本号。"""

    previous_version: int = Field(ge=1)


class RuleEffectivenessItem(BaseModel):
    """规则效果行（契约 3.11）。"""

    rule_code: str
    rule_name: str
    rule_type: str
    intent_type: str
    risk_weight: int = Field(ge=0, le=100)
    current_version: int = Field(ge=1)
    is_enabled: bool
    hit_count: int = Field(ge=0)
    affected_session_count: int = Field(ge=0)
    affected_event_count: int = Field(ge=0)
    affected_attacker_count: int = Field(ge=0)
    used_version_count: int = Field(ge=0)
    first_hit_at: UtcTime | None = None
    last_hit_at: UtcTime | None = None
    alert_count: int = Field(ge=0)
    unread_alert_count: int = Field(ge=0)
    alert_per_hit_ratio: float = Field(ge=0.0, le=1.0)
    hit_rank: int = Field(ge=1)


class RuleEffectivenessResponse(BaseModel):
    """GET /api/rules/effectiveness 响应。"""

    items: list[RuleEffectivenessItem] = Field(default_factory=list)
    total: int = Field(ge=0)
