"""告警只读与已读写仓储。

- 列表：按 `alert_type`/`severity`/`is_read`/`from`/`to` 过滤 + 分页 + 白名单排序
  （契约 3.6）；`source_ip` 与 `rule_name` 由画像与规则当前版本反查得到；
- 详情：按 `alert_id` 查询，供 PATCH 后返回更新后的完整对象（契约 3.7）；
- 已读更新：使用应用读写会话，单事务内 `SELECT ... FOR UPDATE` 后写入，返回数据库
  实际状态（幂等：已读再次置已读不刷新 `read_at`）。

只读函数不提交事务；写函数由路由层调用 `await session.commit()` 提交。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.query_repo import build_in_clause, fetch_one, fetch_page

#: 告警行查询（列表与单条详情共用）。`rule_name` 取规则编码当前版本名称。
ALERT_SELECT = """
SELECT a.alert_id,
       a.dedup_key,
       a.session_id,
       a.attacker_id,
       p.source_ip,
       a.rule_code,
       COALESCE(rc.rule_name, a.rule_code) AS rule_name,
       a.latest_hit_id,
       a.alert_type,
       a.severity,
       a.title,
       a.evidence_summary,
       a.first_seen_at,
       a.last_seen_at,
       a.occurrence_count,
       a.created_at,
       a.is_read,
       a.read_at
FROM alerts AS a
JOIN attacker_profile AS p ON p.attacker_id = a.attacker_id
LEFT JOIN (
    SELECT d.rule_code, d.rule_name
    FROM detection_rules AS d
    JOIN (
        SELECT rule_code, MAX(rule_version) AS max_version
        FROM detection_rules
        GROUP BY rule_code
    ) AS latest
      ON latest.rule_code = d.rule_code
     AND latest.max_version = d.rule_version
) AS rc ON rc.rule_code = a.rule_code
"""

#: 严重度排序表达式（契约 3.6：critical > high > medium > low，不用字典序）
SEVERITY_RANK_EXPR = """
CASE a.severity
    WHEN 'critical' THEN 4
    WHEN 'high'     THEN 3
    WHEN 'medium'   THEN 2
    WHEN 'low'      THEN 1
    ELSE 0
END
"""

#: 排序白名单（契约 3.6）
SORT_FIELDS = ("created_at", "severity")


def _build_filters(
    alert_types: list[str],
    severities: list[str],
    is_read: bool | None,
    from_time: Any,
    to_time: Any,
) -> tuple[str, dict[str, Any]]:
    """构造告警列表筛选 SQL 片段（时间区间左闭右开，契约 1.5）。"""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if alert_types:
        clause, values = build_in_clause("a.alert_type", alert_types, "alert_type_")
        clauses.append(clause)
        params.update(values)
    if severities:
        clause, values = build_in_clause("a.severity", severities, "severity_")
        clauses.append(clause)
        params.update(values)
    if is_read is not None:
        clauses.append("a.is_read = :is_read")
        params["is_read"] = 1 if is_read else 0
    if from_time is not None:
        clauses.append("a.created_at >= :from_time")
        params["from_time"] = from_time
    if to_time is not None:
        clauses.append("a.created_at < :to_time")
        params["to_time"] = to_time
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _order_by(sort: str, order: str) -> str:
    """返回稳定排序子句（次级键固定，翻页不重复不漏项）。"""
    direction = order.upper()
    if sort == "severity":
        return (
            f"ORDER BY {SEVERITY_RANK_EXPR} {direction}, "
            "a.created_at DESC, a.alert_id DESC"
        )
    return f"ORDER BY a.created_at {direction}, a.alert_id {direction}"


async def list_alerts(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    sort: str,
    order: str,
    alert_types: list[str] | None = None,
    severities: list[str] | None = None,
    is_read: bool | None = None,
    from_time: Any = None,
    to_time: Any = None,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询告警列表（返回当前页行与 total）。"""
    where, params = _build_filters(
        alert_types or [], severities or [], is_read, from_time, to_time
    )
    count_sql = f"SELECT COUNT(*) FROM alerts AS a\n{where}"
    items_sql = f"{ALERT_SELECT}\n{where}\n{_order_by(sort, order)}"
    return await fetch_page(
        session,
        count_sql=count_sql,
        items_sql=items_sql,
        params=params,
        page=page,
        page_size=page_size,
    )


async def get_alert_by_id(session: AsyncSession, alert_id: int) -> dict[str, Any] | None:
    """按告警编号取完整告警行（供 PATCH 返回更新后对象）。"""
    return await fetch_one(
        session,
        f"{ALERT_SELECT}\nWHERE a.alert_id = :alert_id",
        {"alert_id": alert_id},
    )


async def lock_alert_for_update(session: AsyncSession, alert_id: int) -> bool:
    """在写事务内锁定告警行；不存在返回 `False`（路由层转 404 ALERT_NOT_FOUND）。"""
    row = await fetch_one(
        session,
        "SELECT alert_id FROM alerts WHERE alert_id = :alert_id FOR UPDATE",
        {"alert_id": alert_id},
    )
    return row is not None


#: 置已读：已读时保留原 `read_at`（幂等，不刷新时间）
_MARK_READ = text(
    """
    UPDATE alerts
       SET is_read = 1,
           read_at = COALESCE(read_at, UTC_TIMESTAMP(6))
     WHERE alert_id = :alert_id
    """
)

#: 置未读：`read_at` 置 NULL（允许撤回误标）
_MARK_UNREAD = text(
    """
    UPDATE alerts
       SET is_read = 0,
           read_at = NULL
     WHERE alert_id = :alert_id
    """
)


async def set_alert_read(session: AsyncSession, alert_id: int, is_read: bool) -> None:
    """更新已读状态（不提交事务）。

    - 置 `true`：已读时保留原 `read_at`（幂等，不刷新时间）；
    - 置 `false`：`read_at` 置 `NULL`（允许撤回误标）。
    """
    statement = _MARK_READ if is_read else _MARK_UNREAD
    await session.execute(statement, {"alert_id": alert_id})
