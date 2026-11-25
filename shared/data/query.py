"""通用只读查询辅助：执行 SQL、行列映射、分页与参数校验。

只读仓储一律接收 `AsyncSession`（由 `m1_transaction_integration.api.deps.RODB` 注入的只读会话），
因此本模块的函数都不提交事务；写仓储由各自模块显式提交。

设计要点：

- 统一用 SQLAlchemy `text()` + 命名参数执行，避免字符串拼接注入；
- `normalize_row` 把 MySQL 返回的朴素 `datetime` 补成 UTC 带时区值，
  并把 `Decimal` 转 `float`、`bytes` 转 `str`，便于 Pydantic 校验；
- `fetch_page` 先查 `COUNT(*)` 再查当前页，列表接口因此总能给出真实 `total`；
- 契约 1.5 的 `from`/`to` 解析与 1.4 的排序校验集中在这里，路由层只做白名单声明。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.errors import unprocessable

#: 分页每页条数上限（契约 1.4，越界由 FastAPI Query 校验拦截）
MAX_PAGE_SIZE = 100


def normalize_value(value: Any) -> Any:
    """规整单个列值：时间补 UTC、Decimal 转 float、bytes 解码。"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - 异常编码兜底
            return value.decode("utf-8", errors="replace")
    return value


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """把 SQLAlchemy RowMapping 转成规整 dict。"""
    return {key: normalize_value(value) for key, value in row.items()}


async def fetch_all(
    session: AsyncSession,
    sql: str,
    params: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """执行查询并返回全部行（dict 列表）。"""
    result = await session.execute(text(sql), dict(params or {}))
    return [normalize_row(row) for row in result.mappings().all()]


async def fetch_one(
    session: AsyncSession,
    sql: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """执行查询并返回首行（无结果为 `None`）。"""
    result = await session.execute(text(sql), dict(params or {}))
    row = result.mappings().first()
    return normalize_row(row) if row is not None else None


async def fetch_scalar(
    session: AsyncSession,
    sql: str,
    params: Mapping[str, Any] | None = None,
) -> Any:
    """执行查询并返回首行首列标量（无结果为 `None`）。"""
    result = await session.execute(text(sql), dict(params or {}))
    return result.scalar()


async def fetch_page(
    session: AsyncSession,
    *,
    count_sql: str,
    items_sql: str,
    params: Mapping[str, Any] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询：返回 `(当前页行, total)`。

    `items_sql` 不应自带 `LIMIT`/`OFFSET`；本函数追加分页子句。
    页码超出范围时返回空列表与真实 `total`（契约 1.4，不返回 404）。
    """
    total = int(await fetch_scalar(session, count_sql, params) or 0)
    offset = (page - 1) * page_size
    paged_params = dict(params or {})
    paged_params["_limit"] = page_size
    paged_params["_offset"] = offset
    rows = await fetch_all(
        session,
        f"{items_sql}\nLIMIT :_limit OFFSET :_offset",
        paged_params,
    )
    return rows, total


def total_pages(total: int, page_size: int) -> int:
    """计算总页数：`total=0` 时为 0（契约 1.4）。"""
    if total <= 0 or page_size <= 0:
        return 0
    return (total + page_size - 1) // page_size


def build_in_clause(
    column: str,
    values: Sequence[str],
    prefix: str,
) -> tuple[str, dict[str, Any]]:
    """构造 `column IN (:p0, :p1, ...)` 片段及其参数。"""
    keys = [f"{prefix}{index}" for index in range(len(values))]
    placeholders = ", ".join(f":{key}" for key in keys)
    return f"{column} IN ({placeholders})", dict(zip(keys, values, strict=True))


def split_multi_value(values: Sequence[str] | None) -> list[str]:
    """把「可重复参数或逗号分隔」统一展开成去重后的字符串列表。"""
    result: list[str] = []
    for raw in values or []:
        for item in str(raw).split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return result


def validate_enum_values(
    values: Sequence[str],
    allowed: Sequence[str],
    *,
    field: str,
    code: str = "VALIDATION_ERROR",
) -> list[str]:
    """校验枚举列表；非法值抛 422（契约 1.4/1.9）。"""
    allowed_set = set(allowed)
    invalid = [value for value in values if value not in allowed_set]
    if invalid:
        raise unprocessable(
            code,
            "请求参数校验失败",
            {"field": field, "reason": "取值不在允许范围内", "input": ",".join(invalid)[:64]},
        )
    return list(values)


def validate_sort(
    sort: str | None,
    allowed: Sequence[str],
    *,
    default: str,
) -> str:
    """校验排序字段白名单；非法值抛 422 SORT_FIELD_INVALID（契约 1.4）。"""
    value = (sort or default).strip().lower()
    if value not in set(allowed):
        raise unprocessable(
            "SORT_FIELD_INVALID",
            "排序字段不合法",
            {"field": "sort", "reason": "取值不在白名单内", "input": (sort or "")[:64]},
        )
    return value


def validate_order(order: str | None) -> str:
    """校验排序方向（大小写不敏感；其他值 422 VALIDATION_ERROR）。"""
    value = (order or "desc").strip().lower()
    if value not in ("asc", "desc"):
        raise unprocessable(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            {"field": "order", "reason": "只能是 asc 或 desc", "input": (order or "")[:64]},
        )
    return value


def parse_time_param(value: str | None, field: str) -> datetime | None:
    """解析 `from`/`to` 时间参数（契约 1.5）。

    支持 `YYYY-MM-DD`（按 UTC 当日 00:00:00 解释）与 ISO 8601（含 `Z` 或偏移量）。
    格式非法抛 422 TIME_RANGE_INVALID。
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        raise unprocessable(
            "TIME_RANGE_INVALID",
            "时间参数格式不合法",
            {"field": field, "reason": "不能为空字符串"},
        )
    try:
        if len(raw) == 10:
            day = date.fromisoformat(raw)
            return datetime.combine(day, time.min, tzinfo=UTC)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise unprocessable(
            "TIME_RANGE_INVALID",
            "时间参数格式不合法",
            {"field": field, "reason": "需为 ISO 8601 UTC 或 YYYY-MM-DD", "input": raw[:64]},
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_time_range(
    from_value: str | None,
    to_value: str | None,
) -> tuple[datetime | None, datetime | None]:
    """解析并校验时间区间 `[from, to)`；`from > to` 抛 422 TIME_RANGE_INVALID。"""
    start = parse_time_param(from_value, "from")
    end = parse_time_param(to_value, "to")
    if start is not None and end is not None and start > end:
        raise unprocessable(
            "TIME_RANGE_INVALID",
            "时间区间不合法",
            {"field": "from", "reason": "from 不能晚于 to"},
        )
    return start, end


def truncate_text(value: str | None, limit: int) -> tuple[str | None, bool]:
    """按字符数截断文本，返回 `(截断后的值, 是否发生截断)`。"""
    if value is None:
        return None, False
    if len(value) <= limit:
        return value, False
    return value[:limit], True


#: SQL 语句类型派生用的首关键字映射（契约 3.5 `statement_type` 由 normalized_sql 派生）
_STATEMENT_KEYWORDS = {
    "SELECT": "SELECT",
    "SHOW": "SHOW",
    "DESCRIBE": "DESCRIBE",
    "DESC": "DESCRIBE",
    "EXPLAIN": "EXPLAIN",
    "INSERT": "INSERT",
    "UPDATE": "UPDATE",
    "DELETE": "DELETE",
    "DROP": "DROP",
    "TRUNCATE": "TRUNCATE",
    "ALTER": "ALTER",
    "CREATE": "CREATE",
    "REPLACE": "REPLACE",
    "GRANT": "GRANT",
    "REVOKE": "REVOKE",
    "SET": "SET",
    "USE": "USE",
    "CALL": "CALL",
    "UNION": "SELECT",
}


def derive_statement_type(normalized_sql: str | None) -> str | None:
    """从标准化 SQL 派生语句类型（不落库，仅展示，契约 3.5）。"""
    if not normalized_sql:
        return None
    cleaned = normalized_sql.strip().lstrip("(").strip()
    if not cleaned:
        return None
    first = cleaned.split(None, 1)[0].upper().strip(";")
    return _STATEMENT_KEYWORDS.get(first, first[:32] or None)
