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

from m1_transaction_integration.services.time_windows import today_window, yesterday_window
from shared.errors import AppError

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

#: 业务异常基类别名：`api/errors.py` 的全局处理器捕获同一基类
ApiError = AppError


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


class TimeWindow(BaseModel):
    """UTC 半开区间 `[start, end)`（契约 api-extensions.md §1.2/§2.2）。"""

    start: UtcTime = Field(description="窗口起点（含），UTC")
    end: UtcTime = Field(description="窗口终点（不含），UTC")


def _default_today_window() -> TimeWindow:
    """模型独立实例化时的默认今日窗口（UTC+8 自然日，路由层总会显式传入）。"""
    start, end = today_window()
    return TimeWindow(start=start, end=end)


def _default_yesterday_window() -> TimeWindow:
    """模型独立实例化时的默认昨日窗口（UTC+8 自然日）。"""
    start, end = yesterday_window()
    return TimeWindow(start=start, end=end)


def _zero_severity_counts() -> dict[str, int]:
    """四档严重度全 0 计数（键齐全，契约 §2.2/§4.2）。"""
    return {"low": 0, "medium": 0, "high": 0, "critical": 0}


class OverviewResponse(BaseModel):
    """GET /api/overview 响应：首页指标（基契约 3.2 + 002 增量 §2.2）。"""

    sessions: int = Field(ge=0, description="会话总数")
    queries: int = Field(ge=0, description="查询事件总数")
    alerts: int = Field(ge=0, description="告警总数")
    high_risk_attackers: int = Field(
        ge=0, description="高风险攻击者数（risk_level 为 high/critical）"
    )
    generated_at: UtcTime = Field(description="响应生成时间（UTC）")
    # —— 002 增量字段：全部有默认值，001 客户端忽略后仍可用（§8.1） ——
    range: str = Field(default="all", description="生效时间范围：all/7d/24h")
    window_start: UtcTime | None = Field(default=None, description="窗口起点；all 为 null")
    attackers_total: int = Field(default=0, ge=0, description="窗口内攻击者总数")
    high_risk_ratio: float = Field(
        default=0.0, ge=0.0, le=1.0, description="高风险攻击者占比；分母 0 → 0.0"
    )
    alerts_unread: int = Field(default=0, ge=0, description="窗口内未读告警数")
    alerts_by_severity: dict[str, int] = Field(
        default_factory=_zero_severity_counts, description="窗口内各等级告警数"
    )
    sessions_today: int = Field(default=0, ge=0, description="今日（UTC+8）会话数")
    queries_today: int = Field(default=0, ge=0, description="今日（UTC+8）查询事件数")
    sessions_delta_pct: float | None = Field(
        default=None, description="今日相对昨日会话数变化百分比；昨日 0 → null"
    )
    queries_delta_pct: float | None = Field(
        default=None, description="今日相对昨日查询数变化百分比；昨日 0 → null"
    )
    query_blocked_rate: float | None = Field(
        default=None, ge=0.0, le=1.0, description="查询被拒绝率；窗口内查询 0 → null"
    )
    today_window: TimeWindow = Field(
        default_factory=_default_today_window, description="今日 UTC+8 自然日的 UTC 区间"
    )
    yesterday_window: TimeWindow = Field(
        default_factory=_default_yesterday_window, description="昨日 UTC+8 自然日的 UTC 区间"
    )


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
    # —— 002 增量字段：意图族命中数（来自 rule_hits，按 UTC 统计日聚合，缺列补 0） ——
    hit_bruteforce: int = Field(default=0, ge=0, description="爆破命中数（R02）")
    hit_data_dump: int = Field(default=0, ge=0, description="拖库命中数（R04）")
    hit_scanning: int = Field(default=0, ge=0, description="扫描命中数（R01）")
    hit_recon: int = Field(default=0, ge=0, description="侦察命中数（R03）")
    hit_destructive: int = Field(default=0, ge=0, description="破坏性操作命中数（R05）")


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
    # —— 002 增量字段（契约 §6.2）：派生自画像视图与来源地址 ——
    intent_labels: list[str] = Field(default_factory=list, description="拆分后的意图标签")
    triggered_rule_codes: list[str] = Field(
        default_factory=list, description="拆分后的命中规则编码"
    )
    network_scope: str = Field(default="public", description="网络位置：private/loopback/reserved/public")
    network_scope_label: str = Field(default="公网", description="网络位置中文标签")


class AttackerListResponse(BaseModel):
    """GET /api/attackers 分页响应。"""

    items: list[AttackerListItem] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class LatestIntent(BaseModel):
    """最近一次规则命中摘要（契约 §5.2 `latest_intent`）。"""

    intent_type: str
    rule_code: str
    rule_name: str
    source_ip: str
    last_detected_at: UtcTime


class AttackerSummaryResponse(BaseModel):
    """GET /api/attackers/summary 响应（契约 §5.2）。"""

    total: int = Field(ge=0, description="攻击者总数（画像表行数）")
    high_risk_count: int = Field(ge=0, description="risk_level 为 high/critical 的数量")
    latest_intent: LatestIntent | None = Field(
        default=None, description="最近一次规则命中；无命中 → null"
    )
    generated_at: UtcTime = Field(description="响应生成时间（UTC）")


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
    # —— 002 增量字段（契约 §7.1） ——
    avg_session_seconds: int | None = Field(
        default=None, ge=0, description="已结束会话平均时长（秒，四舍五入）；无 → null"
    )
    auth_success_count: int = Field(
        default=0, ge=0, description="认证成功数 = max(0, 尝试数 - 失败数)"
    )
    high_risk_op_count: int = Field(
        default=0, ge=0, description="data_dump/destructive 意图的规则命中数"
    )
    network_scope: str = Field(default="public", description="网络位置")
    network_scope_label: str = Field(default="公网", description="网络位置中文标签")


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


class PeakWindow(TimeWindow):
    """今日告警最多的 1 小时桶（契约 §4.2 `peak_window`）。"""

    count: int = Field(ge=0, description="该小时桶内的告警数")


def _zero_alert_type_counts() -> dict[str, int]:
    """三类告警类型全 0 计数（筛选项键齐全，契约 §4.2）。"""
    return {"bruteforce": 0, "data_dump": 0, "destructive": 0}


class AlertSummaryResponse(BaseModel):
    """GET /api/alerts/summary 响应（契约 §4.2）。"""

    total: int = Field(default=0, ge=0, description="窗口内告警总数")
    unread: int = Field(default=0, ge=0, description="窗口内未读数")
    read: int = Field(default=0, ge=0, description="窗口内已读数（= total - unread）")
    resolution_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="read / total；分母 0 → 0.0"
    )
    by_severity: dict[str, int] = Field(
        default_factory=_zero_severity_counts, description="窗口内各等级告警数"
    )
    unread_by_severity: dict[str, int] = Field(
        default_factory=_zero_severity_counts, description="未读中各等级数"
    )
    by_alert_type: dict[str, int] = Field(
        default_factory=_zero_alert_type_counts, description="窗口内各告警类型数"
    )
    today_new: int = Field(default=0, ge=0, description="今日（UTC+8）新增告警数")
    yesterday_new: int = Field(default=0, ge=0, description="昨日（UTC+8）新增告警数")
    today_delta_pct: float | None = Field(
        default=None, description="今日相对昨日新增百分比；昨日 0 → null"
    )
    peak_window: PeakWindow | None = Field(
        default=None, description="今日告警最多的 1 小时时段；今日无告警 → null"
    )
    today_window: TimeWindow = Field(
        default_factory=_default_today_window, description="今日 UTC+8 自然日的 UTC 区间"
    )
    generated_at: UtcTime = Field(description="响应生成时间（UTC）")


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
