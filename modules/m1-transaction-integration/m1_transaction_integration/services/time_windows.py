"""时间窗口辅助：`range` 窗口与今日/昨日（UTC+8 自然日）半开区间。

契约 `contracts/api-extensions.md` §1.1/§1.2：

- `range ∈ {all, 7d, 24h}`，以服务端当前 UTC 时刻为终点；`all` 无窗口（起点 `None`）；
- `today`/`yesterday` 固定使用 **UTC+8（Asia/Shanghai）自然日**——与页面时钟一致，
  写成 `[start, end)` 半开区间后转换为 UTC 返回，供 SQL 的 `>= start AND < end` 使用。

UTC+8 无夏令时，因此用固定偏移 `timezone(timedelta(hours=8))` 即可，不引入 `zoneinfo`
与系统时区数据依赖；该口径写入代码注释与契约，不新增配置项。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Final

#: 契约 §1.2：今日/昨日固定 UTC+8（Asia/Shanghai，无夏令时）
CN_TZ: Final = timezone(timedelta(hours=8), name="Asia/Shanghai")

#: `range` 白名单（契约 §1.1）与对应窗口长度
RANGE_DELTAS: Final[dict[str, timedelta]] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
RANGE_KEYS: Final[tuple[str, ...]] = ("all", *RANGE_DELTAS)


def _local_day_start(moment: datetime) -> datetime:
    """返回 `moment` 所在 UTC+8 自然日的 00:00（带时区）。"""
    local = moment.astimezone(CN_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def today_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """今日（UTC+8）半开区间 `[start, end)`，返回 UTC 带时区时刻。"""
    moment = now or datetime.now(UTC)
    start_local = _local_day_start(moment)
    return start_local.astimezone(UTC), (start_local + timedelta(days=1)).astimezone(UTC)


def yesterday_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """昨日（UTC+8）半开区间 `[start, end)`，返回 UTC 带时区时刻。"""
    moment = now or datetime.now(UTC)
    start_local = _local_day_start(moment) - timedelta(days=1)
    return start_local.astimezone(UTC), (start_local + timedelta(days=1)).astimezone(UTC)


def resolve_range_start(range_key: str, now: datetime | None = None) -> datetime | None:
    """把 `range` 解析为窗口起点（UTC）；`all` 返回 `None`。

    调用方需先用 `RANGE_KEYS` 做白名单校验（非法值在路由层转 422）。
    """
    delta = RANGE_DELTAS.get(range_key)
    if delta is None:
        return None
    moment = now or datetime.now(UTC)
    return moment - delta


def delta_pct(today_value: int, yesterday_value: int) -> float | None:
    """今日相对昨日的变化百分比（保留 1 位小数）；昨日为 0 → `None`。"""
    if yesterday_value <= 0:
        return None
    return round((today_value - yesterday_value) * 100.0 / yesterday_value, 1)


def ratio(numerator: int, denominator: int) -> float | None:
    """比率（保留 4 位小数）；分母 0 → `None`。"""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


__all__ = [
    "CN_TZ",
    "RANGE_DELTAS",
    "RANGE_KEYS",
    "delta_pct",
    "ratio",
    "resolve_range_start",
    "today_window",
    "yesterday_window",
]
