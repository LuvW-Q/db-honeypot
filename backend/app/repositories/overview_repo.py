"""概览与趋势只读仓储（`v_session_risk_summary`、`v_attacker_profile_summary`、`v_daily_attack_trend`）。

概览四项指标全部来自两个核心视图（契约 3.2 口径说明），不在明细表上二次拼装，
保证页面数字与答辩时现场执行的视图 `SELECT` 完全一致（SC-009/SC-010）。
趋势接口同样只查 `v_daily_attack_trend`，连续日历补齐在 API 聚合层完成（契约 3.10）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.query_repo import fetch_all, fetch_one

#: 概览四项指标（会话数、查询数、告警数、高风险攻击者数）
OVERVIEW_SQL = """
SELECT
  (SELECT COUNT(*) FROM v_session_risk_summary)                       AS sessions,
  (SELECT COALESCE(SUM(query_count), 0) FROM v_session_risk_summary)  AS queries,
  (SELECT COALESCE(SUM(alert_count), 0) FROM v_session_risk_summary)  AS alerts,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE risk_level IN ('high', 'critical'))                         AS high_risk_attackers
"""

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


async def fetch_overview(session: AsyncSession) -> dict[str, int]:
    """查询首页四项指标（空库返回全 0，不报错）。"""
    row = await fetch_one(session, OVERVIEW_SQL) or {}
    return {
        "sessions": int(row.get("sessions") or 0),
        "queries": int(row.get("queries") or 0),
        "alerts": int(row.get("alerts") or 0),
        "high_risk_attackers": int(row.get("high_risk_attackers") or 0),
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


async def fetch_trend_rows(session: AsyncSession, days: int) -> list[dict[str, Any]]:
    """查询最近 `days` 个自然日（含今日）的趋势视图行。"""
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=days - 1)
    return await fetch_all(
        session,
        TREND_SQL,
        {"start_date": start_date, "end_date": end_date},
    )


def build_trend_series(
    rows: list[dict[str, Any]],
    days: int,
    *,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """按连续 UTC 日历补齐趋势点（契约 3.10 口径说明第 2 条）。

    - 空白日补 `0` 计数行，`prev_event_count`/`event_count_delta`/`event_change_pct`
      为 `null`；
    - `day_seq` 为返回序列内连续序号（1..days）；
    - `cumulative_event_count` 在补日后连续累加（空白日不变）；
    - `busy_day_rank` 在补日后的序列内按 `event_count DESC` 重算，空白日为末位。

    不修改数据库、不做跨视图聚合，只补齐视图本身“空白日不出行”的展示缺口。
    """
    end = end_date or datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)

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
