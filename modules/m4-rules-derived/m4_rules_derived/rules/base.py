"""规则判定公共契约：规则上下文、命中候选与规则注册表。

本模块是分析层内部的最小契约（不属于 impl-contract.md 的对外稳定接口）：

- `RuleContext`：一次判定的输入，包含数据库会话、本事件行、所属会话行与规则行；
- `RuleHitCandidate`：单条规则命中的候选结果，由分析层负责落库为 `rule_hits`；
- `RULES`：`rule_code -> 判定协程` 的注册表，由各规则模块导入时自动注册。

设计约束（data-model 10.2 / contracts/events.md 6.3）：

1. 每条规则只针对“本事件”返回命中/不命中，窗口统计只读 `attack_log`；
2. 规则不得执行原始 SQL、不访问诱饵数据、不做字符串拼接（SQL 参数一律绑定）；
3. 阈值全部来自 `detection_rules.parameters_json`，缺失时使用本模块给出的安全缺省值；
4. 时间窗口为“当前事件 `event_time` 向前回溯 `window_seconds`”，窗口内**含当前事件**。

关于 SQL 文本工具：捕获层拥有 `app/utils/sql.py` 的所有权；本层为避免跨工作流写文件，
在未发现该模块时使用本文件内的本地只读工具（只做字符串识别，绝不执行 SQL），
若捕获层后续提供同名能力，可直接替换这些私有实现而不影响规则签名。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# 捕获层拥有 `app/utils/sql.py` 的所有权；若已实现则复用其去注释能力，
# 未实现时回落到本文件的本地正则实现（不创建/修改 utils/sql.py）。
try:  # pragma: no cover - 依赖捕获层是否已落地该模块
    from shared.utils.sql import strip_sql_comments as _strip_sql_comments
except Exception:  # noqa: BLE001 - 分析层不得因可选依赖缺失而导入失败
    _strip_sql_comments = None  # type: ignore[assignment]


@dataclass(slots=True)
class RuleContext:
    """单条规则的判定上下文。

    Attributes:
        db: 当前分析事务的异步数据库会话（只读查询 + 规则命中由分析层写入）。
        event_row: 本事件 `attack_log` ORM 行（已 flush，`event_id` 可用）。
        session_row: 本事件所属 `sessions` ORM 行。
        rule_row: 本事件采用的 `detection_rules` ORM 行（已是最大启用版本）。
    """

    db: AsyncSession
    event_row: Any
    session_row: Any
    rule_row: Any

    @property
    def rule_code(self) -> str:
        """规则编码（R01–R05），用于证据与注册表定位。"""
        return str(self.rule_row.rule_code)

    @property
    def parameters(self) -> dict[str, Any]:
        """规则参数：优先 ORM 的 `parameters` 属性，其次解析 JSON 文本。"""
        getter = getattr(self.rule_row, "parameters", None)
        if isinstance(getter, dict):
            return getter
        raw = getattr(self.rule_row, "parameters_json", None)
        if isinstance(raw, dict):
            return raw
        return {}

    @property
    def source_ip(self) -> str:
        """来源地址（小写归一化），窗口统计按该字段过滤。"""
        ip = getattr(self.event_row, "source_ip", None) or getattr(
            self.session_row, "source_ip", ""
        )
        return str(ip).lower()

    @property
    def event_time(self) -> datetime:
        """本事件时间（naive UTC），窗口计算的基准点。"""
        return naive_utc(self.event_row.event_time)


@dataclass(slots=True)
class RuleHitCandidate:
    """单条规则的命中候选。

    `rule_code/intent_type/risk_weight` 由分析层以规则行快照覆盖写入 `rule_hits`；
    `evidence_summary` 必须说明“为什么命中”，长度受数据库列 `VARCHAR(1024)` 限制；
    `details` 仅用于分析结果与调试（不落库），可携带统计值、关键词等结构化信息。
    """

    rule_code: str
    intent_type: str
    risk_weight: int
    evidence_summary: str
    details: dict[str, Any] = field(default_factory=dict)


# 判定协程类型：输入上下文，命中返回候选，不命中返回 None
RuleCallable = Callable[[RuleContext], Awaitable[RuleHitCandidate | None]]

# 规则注册表：由各规则模块在导入时注册；分析层按 detection_rules.rule_code 查找
RULES: dict[str, RuleCallable] = {}


def register(rule_code: str) -> Callable[[RuleCallable], RuleCallable]:
    """装饰器：把一条规则判定函数注册到 `RULES`。

    同一 rule_code 重复注册时以最后一次为准（便于测试替换），生产路径不会重复导入。
    """

    def _decorator(func: RuleCallable) -> RuleCallable:
        RULES[rule_code] = func
        return func

    return _decorator


# ---------------------------------------------------------------------------
# 本地只读 SQL 文本工具（不执行、不改写数据库；捕获层提供 utils/sql.py 时可替换）
# ---------------------------------------------------------------------------

# 写操作首关键词集合（R05）
WRITE_KEYWORDS: frozenset[str] = frozenset(
    {"DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "REPLACE"}
)

# 可能出现在 SQL 前的注释/空白/分号，用于定位“首关键词”
_LEADING_NOISE_RE = re.compile(r"^(?:\s+|--[^\n]*\n?|/\*.*?\*/|;)+", re.DOTALL)
# 词边界匹配：避免 UPDATE_TIME 之类被误判为 UPDATE
_WORD_RE_TEMPLATE = r"(?<![A-Za-z0-9_]){keyword}(?![A-Za-z0-9_])"


def naive_utc(value: datetime | None) -> datetime:
    """把时间统一为 naive UTC（数据库 DATETIME(6) 口径），无时区按 UTC 处理。"""
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def window_range(event_time: datetime, window_seconds: int) -> tuple[datetime, datetime]:
    """返回窗口的 (start, end)：`[event_time - window_seconds, event_time]`。"""
    seconds = max(int(window_seconds), 1)
    end = naive_utc(event_time)
    return end - timedelta(seconds=seconds), end


def event_sql_text(event_row: Any) -> str:
    """取本事件用于匹配的 SQL 文本：优先 `normalized_sql`，回落 `sql_statement`。"""
    normalized = getattr(event_row, "normalized_sql", None)
    if normalized:
        return str(normalized)
    raw = getattr(event_row, "sql_statement", None)
    return str(raw) if raw else ""


def strip_leading_noise(sql: str) -> str:
    """去掉 SQL 开头的空白、注释与分号，便于读取首关键词。

    优先复用捕获层的 `shared.utils.sql.strip_sql_comments`；该模块缺失时使用本地
    正则兜底，保证分析层可独立导入（两实现均只做字符串处理，不执行 SQL）。
    """
    if not sql:
        return ""
    if _strip_sql_comments is not None:
        return _strip_sql_comments(sql).lstrip(" \t\r\n;")
    return _LEADING_NOISE_RE.sub("", sql, count=1).lstrip()


def first_keyword(sql: str) -> str:
    """抽取 SQL 的首个关键词（大写），无内容时返回空串。"""
    cleaned = strip_leading_noise(sql)
    if not cleaned:
        return ""
    match = re.match(r"[A-Za-z_]+", cleaned)
    return match.group(0).upper() if match else ""


def is_select_statement(sql: str) -> bool:
    """判断语句是否以 SELECT 开头（R04 连续 SELECT 口径）。"""
    return first_keyword(sql) == "SELECT"


def contains_keyword(
    sql: str, keyword: str, *, case_sensitive: bool = False, word_boundary: bool = True
) -> bool:
    """判断 SQL 文本是否包含指定关键词。

    Args:
        sql: 待匹配文本（通常是 normalized_sql）。
        keyword: 关键词，如 SHOW TABLES、DROP。
        case_sensitive: 是否区分大小写；默认不区分（R03/R05 均为 false）。
        word_boundary: 是否要求词边界，避免 `UPDATE_TIME` 误报（R05）。
    """
    if not sql or not keyword:
        return False
    haystack = sql if case_sensitive else sql.upper()
    needle = keyword if case_sensitive else keyword.upper()
    if word_boundary:
        return re.search(_WORD_RE_TEMPLATE.format(keyword=re.escape(needle)), haystack) is not None
    return needle in haystack


def match_any_keyword(
    sql: str,
    keywords: list[str] | tuple[str, ...],
    *,
    case_sensitive: bool = False,
    word_boundary: bool = True,
) -> str | None:
    """返回命中的第一个关键词（保持配置顺序，便于证据稳定），未命中返回 None。"""
    for keyword in keywords:
        if contains_keyword(
            sql, keyword, case_sensitive=case_sensitive, word_boundary=word_boundary
        ):
            return keyword
    return None


def clamp_limit(max_len: int, default: int) -> int:
    """把规则参数里的批量上限收敛到 [1, 1000]，避免配置错误导致全表扫描。"""
    try:
        value = int(max_len)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 1000))


def safe_int(value: Any, default: int) -> int:
    """把驱动返回的 Decimal/str/None 安全转成 int。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
