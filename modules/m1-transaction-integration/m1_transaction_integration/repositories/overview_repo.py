"""概览与趋势只读仓储。

口径（contracts/api-extensions.md §1.1/§1.2/§2/§3）：

- 概览基础四项指标（会话/查询/告警/高风险攻击者）支持 `range` 窗口过滤：
  会话按 `sessions.started_at`、查询按 `attack_log.event_time`、告警按
  `alerts.created_at`、攻击者按 `attacker_profile.last_seen`（经画像汇总视图的
  `last_seen`）与窗口起点比较；`all` 不加下界；
- 今日/昨日固定 **UTC+8 自然日**半开区间（合同 §1.2，口径实现于
  `services.time_windows`），`sessions_today/queries_today` 与两个 delta 百分比均
  只依赖该区间，不受 `range` 影响；
- `query_blocked_rate` 取窗口内 `event_type='query'` 中 `status='denied'` 的占比；
  分母 0 → `null`（Python 侧计算，不除零）；
- 趋势点五个 `hit_*` 来自 `rule_hits` 按 `triggered_at` 的 UTC 统计日与意图族聚合，
  与 `v_daily_attack_trend` 的日期序列在 `build_trend_series` 中对齐补 0。

聚合一律带时间上界（`<= :upper`）或窗口终点，避免全表无界扫描；不新增索引/视图/DDL。
所有 SQL 参数化（宪法三），仓储函数只读、不提交事务。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from m1_transaction_integration.services.time_windows import (
    delta_pct,
    ratio,
    today_window,
    yesterday_window,
)
from shared.data.query import fetch_all, fetch_one

#: 趋势查询：只取窗口内日期，按日期升序；补日逻辑在 `build_trend_series`
TREND_SQL = """
SELECT stat_date,
       day_seq,
       event_count,
       session_count,
       source_count,
       query_count,
       denied_count,
       alert_count,
       high_level_alert_count,
       prev_event_count,
       event_count_delta,
       event_change_pct,
       cumulative_event_count,
       busy_day_rank
FROM v_daily_attack_trend
WHERE stat_date BETWEEN :start_date AND :end_date
ORDER BY stat_date ASC
"""

#: 趋势命中：`rule_hits` 按 `triggered_at` 的 UTC 统计日聚合意图族（契约 §3.1）
TREND_HITS_SQL = """
SELECT DATE(triggered_at) AS stat_date,
       SUM(intent_type = 'bruteforce')  AS hit_bruteforce,
       SUM(intent_type = 'data_dump')   AS hit_data_dump,
       SUM(intent_type = 'scanning')    AS hit_scanning,
       SUM(intent_type = 'recon')       AS hit_recon,
       SUM(intent_type = 'destructive') AS hit_destructive
FROM rule_hits
WHERE triggered_at >= :start_time
  AND triggered_at < :end_time
GROUP BY DATE(triggered_at)
ORDER BY stat_date ASC
"""

#: 趋势点的意图族字段（与契约 §3.1 一一对应）
HIT_FIELDS: tuple[str, ...] = (
    "hit_bruteforce",
    "hit_data_dump",
    "hit_scanning",
    "hit_recon",
    "hit_destructive",
)


def build_overview_sql(window_start: datetime | None) -> str:
    """构造概览聚合 SQL：仅在生效范围内追加窗口下界（静态片段拼接，无用户输入）。"""
    session_window = " AND started_at >= :window_start" if window_start is not None else ""
    log_window = " AND event_time >= :window_start" if window_start is not None else ""
    alert_window = " AND created_at >= :window_start" if window_start is not None else ""
    attacker_window = " AND last_seen >= :window_start" if window_start is not None else ""
    return f"""
SELECT
  (SELECT COUNT(*) FROM sessions
    WHERE started_at <= :upper{session_window})                       AS sessions,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query' AND event_time <= :upper{log_window})  AS queries,
  (SELECT COUNT(*) FROM alerts
    WHERE created_at <= :upper{alert_window})                         AS alerts,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE risk_level IN ('high', 'critical')
      AND last_seen <= :upper{attacker_window})                       AS high_risk_attackers,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE last_seen <= :upper{attacker_window})                       AS attackers_total,
  (SELECT COUNT(*) FROM alerts
    WHERE is_read = 0 AND created_at <= :upper{alert_window})         AS alerts_unread,
  (SELECT COALESCE(SUM(severity = 'low'), 0) FROM alerts
    WHERE created_at <= :upper{alert_window})                         AS alerts_low,
  (SELECT COALESCE(SUM(severity = 'medium'), 0) FROM alerts
    WHERE created_at <= :upper{alert_window})                         AS alerts_medium,
  (SELECT COALESCE(SUM(severity = 'high'), 0) FROM alerts
    WHERE created_at <= :upper{alert_window})                         AS alerts_high,
  (SELECT COALESCE(SUM(severity = 'critical'), 0) FROM alerts
    WHERE created_at <= :upper{alert_window})                         AS alerts_critical,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query' AND status = 'denied'
      AND event_time <= :upper{log_window})                           AS denied_queries,
  (SELECT COUNT(*) FROM sessions
    WHERE started_at >= :today_start AND started_at < :today_end)     AS sessions_today,
  (SELECT COUNT(*) FROM sessions
    WHERE started_at >= :yesterday_start
      AND started_at < :yesterday_end)                                AS sessions_yesterday,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query'
      AND event_time >= :today_start AND event_time < :today_end)     AS queries_today,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query'
      AND event_time >= :yesterday_start
      AND event_time < :yesterday_end)                                AS queries_yesterday
"""


async def fetch_overview(
    session: AsyncSession,
    *,
    window_start: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """查询首页指标（契约 §2.2）；空库返回全 0/None 派生值，不报错。

    返回字段与 `OverviewResponse` 对齐（`generated_at` 由路由层补充）。
    """
    moment = now or datetime.now(UTC)
    today_start, today_end = today_window(moment)
    yesterday_start, yesterday_end = yesterday_window(moment)
    params: dict[str, Any] = {
        "upper": moment,
        "today_start": today_start,
        "today_end": today_end,
        "yesterday_start": yesterday_start,
        "yesterday_end": yesterday_end,
    }
    if window_start is not None:
        params["window_start"] = window_start

    row = await fetch_one(session, build_overview_sql(window_start), params) or {}

    sessions_today = int(row.get("sessions_today") or 0)
    sessions_yesterday = int(row.get("sessions_yesterday") or 0)
    queries_today = int(row.get("queries_today") or 0)
    queries_yesterday = int(row.get("queries_yesterday") or 0)
    attackers_total = int(row.get("attackers_total") or 0)
    high_risk_attackers = int(row.get("high_risk_attackers") or 0)
    queries = int(row.get("queries") or 0)
    denied_queries = int(row.get("denied_queries") or 0)

    return {
        "sessions": int(row.get("sessions") or 0),
        "queries": queries,
        "alerts": int(row.get("alerts") or 0),
        "high_risk_attackers": high_risk_attackers,
        "attackers_total": attackers_total,
        # 分母 0 时按契约取 0.0（不是 None）
        "high_risk_ratio": ratio(high_risk_attackers, attackers_total) or 0.0,
        "alerts_unread": int(row.get("alerts_unread") or 0),
        "alerts_by_severity": {
            "low": int(row.get("alerts_low") or 0),
            "medium": int(row.get("alerts_medium") or 0),
            "high": int(row.get("alerts_high") or 0),
            "critical": int(row.get("alerts_critical") or 0),
        },
        "sessions_today": sessions_today,
        "queries_today": queries_today,
        "sessions_delta_pct": delta_pct(sessions_today, sessions_yesterday),
        "queries_delta_pct": delta_pct(queries_today, queries_yesterday),
        "query_blocked_rate": ratio(denied_queries, queries),
        "today_window": {"start": today_start, "end": today_end},
        "yesterday_window": {"start": yesterday_start, "end": yesterday_end},
    }


def _as_date(value: Any) -> date | None:
    """把视图返回的 `stat_date` 统一成 `date`。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:  # pragma: no cover - 视图列固定为 DATE
            return None
    return None


async def fetch_trend_rows(
    session: AsyncSession,
    days: int,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """查询最近 `days` 个自然日（含今日）的趋势视图行。"""
    end_date = (now or datetime.now(UTC)).date()
    start_date = end_date - timedelta(days=days - 1)
    return await fetch_all(
        session,
        TREND_SQL,
        {"start_date": start_date, "end_date": end_date},
    )


async def fetch_trend_hits(
    session: AsyncSession,
    days: int,
    *,
    now: datetime | None = None,
) -> dict[date, dict[str, int]]:
    """查询最近 `days` 个自然日的 `rule_hits` 意图族命中数（按 UTC 统计日）。"""
    end_date = (now or datetime.now(UTC)).date()
    start_date = end_date - timedelta(days=days - 1)
    start_time = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_time = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    rows = await fetch_all(
        session,
        TREND_HITS_SQL,
        {"start_time": start_time, "end_time": end_time},
    )
    hits_by_date: dict[date, dict[str, int]] = {}
    for row in rows:
        stat_date = _as_date(row.get("stat_date"))
        if stat_date is None:
            continue
        hits_by_date[stat_date] = {
            field: int(row.get(field) or 0) for field in HIT_FIELDS
        }
    return hits_by_date


def build_trend_series(
    rows: list[dict[str, Any]],
    days: int,
    *,
    end_date: date | None = None,
    hits_by_date: dict[date, dict[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """按连续 UTC 日历补齐趋势点（契约 3.10 口径说明第 2 条 + §3.1 命中数）。

    - 空白日补 `0` 计数行，`prev_event_count`/`event_count_delta`/`event_change_pct`
      为 `null`；
    - `day_seq` 为返回序列内连续序号（1..days）；
    - `cumulative_event_count` 在补日后连续累加（空白日不变）；
    - `busy_day_rank` 在补日后的序列内按 `event_count DESC` 重算，空白日为末位；
    - 五个 `hit_*` 来自 `rule_hits` 按 UTC 统计日的聚合，与序列日期对齐、无数据补 0。

    不修改数据库、不做跨视图聚合，只补齐视图本身“空白日不出行”的展示缺口。
    """
    end = end_date or datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)
    hits = hits_by_date or {}

    def _hit_values(stat_date: date) -> dict[str, int]:
        day_hits = hits.get(stat_date) or {}
        return {field: int(day_hits.get(field) or 0) for field in HIT_FIELDS}

    by_date: dict[date, dict[str, Any]] = {}
    for row in rows:
        stat_date = _as_date(row.get("stat_date"))
        if stat_date is not None:
            by_date[stat_date] = row

    points: list[dict[str, Any]] = []
    cumulative = 0
    cursor = start
    while cursor <= end:
        row = by_date.get(cursor)
        if row is None:
            points.append(
                {
                    "stat_date": cursor,
                    "event_count": 0,
                    "session_count": 0,
                    "source_count": 0,
                    "query_count": 0,
                    "denied_count": 0,
                    "alert_count": 0,
                    "high_level_alert_count": 0,
                    "prev_event_count": None,
                    "event_count_delta": None,
                    "event_change_pct": None,
                    "cumulative_event_count": cumulative,
                    **_hit_values(cursor),
                }
            )
        else:
            event_count = int(row.get("event_count") or 0)
            cumulative += event_count
            points.append(
                {
                    "stat_date": cursor,
                    "event_count": event_count,
                    "session_count": int(row.get("session_count") or 0),
                    "source_count": int(row.get("source_count") or 0),
                    "query_count": int(row.get("query_count") or 0),
                    "denied_count": int(row.get("denied_count") or 0),
                    "alert_count": int(row.get("alert_count") or 0),
                    "high_level_alert_count": int(row.get("high_level_alert_count") or 0),
                    "prev_event_count": (
                        None
                        if row.get("prev_event_count") is None
                        else int(row["prev_event_count"])
                    ),
                    "event_count_delta": (
                        None
                        if row.get("event_count_delta") is None
                        else int(row["event_count_delta"])
                    ),
                    "event_change_pct": (
                        None
                        if row.get("event_change_pct") is None
                        else float(row["event_change_pct"])
                    ),
                    "cumulative_event_count": cumulative,
                    **_hit_values(cursor),
                }
            )
        cursor += timedelta(days=1)

    # day_seq 连续编号 + busy_day_rank（竞争排名：并列同名次，空白日为末位）
    for index, point in enumerate(points, start=1):
        point["day_seq"] = index
        point["busy_day_rank"] = 1 + sum(
            1 for other in points if other["event_count"] > point["event_count"]
        )
    return points
