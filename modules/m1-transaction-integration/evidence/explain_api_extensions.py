"""生成 002 API 扩展查询的 EXPLAIN 证据（可复现脚本，输出 Markdown 表格）。

用法（仓库根目录）：

    /tmp/dbh-venv/bin/python modules/m1-transaction-integration/evidence/explain_api_extensions.py

说明：

- SQL 直接取自 M1 仓储模块（`overview_repo` / `alert_repo` / `attacker_repo`），
  与运行时完全一致；参数按服务端生成值内联为常量（无用户输入）；
- 连接 `honeypot_dev`，使用迁移账号（具备 SELECT + SHOW VIEW；只读账号缺
  SHOW VIEW 时 EXPLAIN 视图会报 1345，执行计划本身与只读账号一致）；
- 仅执行 EXPLAIN，不写入任何数据，也不新增索引/视图/DDL（宪法三、契约 §10）。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO_ROOT),
    str(REPO_ROOT / "modules/m1-transaction-integration"),
    str(REPO_ROOT / "modules/m2-decoy-capture"),
    str(REPO_ROOT / "modules/m4-rules-derived"),
    str(REPO_ROOT / "modules/m5-views-console"),
]

from m1_transaction_integration.repositories import (  # noqa: E402
    alert_repo,
    attacker_repo,
    overview_repo,
)
from m1_transaction_integration.services.time_windows import (  # noqa: E402
    today_window,
    yesterday_window,
)
from sqlalchemy import text  # noqa: E402

from shared.db.session import get_migrate_engine  # noqa: E402

NOW = datetime.now(UTC).replace(microsecond=0)
TODAY_START, TODAY_END = today_window(NOW)
YESTERDAY_START, YESTERDAY_END = yesterday_window(NOW)

BASE_VALUES: dict[str, object] = {
    "upper": NOW,
    "window_start": NOW - timedelta(days=7),
    "today_start": TODAY_START,
    "today_end": TODAY_END,
    "yesterday_start": YESTERDAY_START,
    "yesterday_end": YESTERDAY_END,
    "from_time": NOW - timedelta(days=7),
    "to_time": NOW,
    "start_date": (NOW - timedelta(days=13)).date(),
    "end_date": NOW.date(),
    "start_time": NOW - timedelta(days=13),
    "end_time": NOW + timedelta(days=1),
    "source_ip": "192.0.2.10",
    "q_pattern": "%192.168%",
}

QUERIES: list[tuple[str, str, dict[str, object]]] = [
    (
        "overview·range=7d（带窗口下界）",
        overview_repo.build_overview_sql(NOW - timedelta(days=7)),
        {},
    ),
    ("overview·range=all（无下界）", overview_repo.build_overview_sql(None), {}),
    ("trend·v_daily_attack_trend", overview_repo.TREND_SQL, {}),
    ("trend·rule_hits 意图族聚合", overview_repo.TREND_HITS_SQL, {}),
    ("alerts·summary（无 from/to）", alert_repo._build_summary_sql(None, None), {}),
    (
        "alerts·summary（from/to 窗口）",
        alert_repo._build_summary_sql(NOW - timedelta(days=7), NOW),
        {},
    ),
    ("alerts·peak_window 小时分桶", alert_repo.PEAK_WINDOW_SQL, {}),
    ("attackers·summary", attacker_repo.ATTACKER_SUMMARY_SQL, {}),
    ("attackers·latest_intent", attacker_repo.LATEST_INTENT_SQL, {}),
    ("attackers·派生统计", attacker_repo.DERIVED_STATS_SQL, {}),
    (
        "attackers·list（q + total_connections 排序）",
        attacker_repo.LIST_COLUMNS
        + "\nWHERE v.source_ip LIKE :q_pattern ESCAPE '\\\\'\n"
        + "ORDER BY v.total_connections DESC, v.source_ip ASC",
        {},
    ),
]

SCALARS: list[tuple[str, str, dict[str, object]]] = [
    (
        "overview·sessions 标量子查询（7d）",
        "SELECT COUNT(*) FROM sessions WHERE started_at <= :upper AND started_at >= :window_start",
        {},
    ),
    (
        "overview·queries 标量子查询（7d）",
        "SELECT COUNT(*) FROM attack_log WHERE event_type = 'query'"
        " AND event_time <= :upper AND event_time >= :window_start",
        {},
    ),
    (
        "overview·alerts 标量子查询（7d）",
        "SELECT COUNT(*) FROM alerts WHERE created_at <= :upper AND created_at >= :window_start",
        {},
    ),
    (
        "overview·高风险攻击者（视图 + IN）",
        "SELECT COUNT(*) FROM v_attacker_profile_summary"
        " WHERE risk_level IN ('high', 'critical') AND last_seen <= :upper",
        {},
    ),
    (
        "overview·今日会话（UTC+8 半开区间）",
        "SELECT COUNT(*) FROM sessions WHERE started_at >= :today_start AND started_at < :today_end",
        {},
    ),
    (
        "overview·告警时间上界（all 时唯一谓词）",
        "SELECT COUNT(*) FROM alerts WHERE created_at <= :upper",
        {},
    ),
]


def substitute(sql: str, extra: dict[str, object]) -> str:
    """把命名参数替换为 SQL 常量字面量（值均来自服务端或脚本常量）。"""
    values = dict(BASE_VALUES)
    values.update(extra)
    for key, value in values.items():
        if isinstance(value, datetime):
            rendered = f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
        elif isinstance(value, date):
            rendered = f"'{value.isoformat()}'"
        else:
            escaped = str(value).replace("\\", "\\\\").replace("'", "''")
            rendered = f"'{escaped}'"
        sql = sql.replace(f":{key}", rendered)
    return sql


def markdown_table(rows: list[tuple[object, ...]]) -> list[str]:
    """把 EXPLAIN 行渲染为 Markdown 表格（列：id/select_type/table/type/key/rows/Extra）。"""
    lines = ["| id | select_type | table | type | key | rows | Extra |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        rid, select_type, table_name, join_type = row[0], row[1], row[2], row[4]
        key = row[6]
        est_rows = row[9]
        extra = row[11]
        lines.append(
            f"| {rid} | {select_type} | {table_name or ''} | {join_type or ''} | "
            f"{key or ''} | {est_rows if est_rows is not None else ''} | {extra or ''} |"
        )
    return lines


async def main() -> None:
    engine = get_migrate_engine()
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT VERSION()"))).scalar()
        dbname = (await conn.execute(text("SELECT DATABASE()"))).scalar()
        charset, collation = (
            await conn.execute(text("SELECT @@character_set_connection, @@collation_connection"))
        ).one()

        print(f"验证时间：{NOW.isoformat()}")
        print(f"MySQL：{version}")
        print(f"数据库：{dbname}")
        print(f"连接字符集：{charset} / {collation}")
        print()
        print("EXPLAIN 时点各表行数：")
        print()
        print("| 表 | 行数 |")
        print("| --- | --- |")
        for table in ("sessions", "attack_log", "alerts", "rule_hits", "attacker_profile"):
            count = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
            print(f"| {table} | {count} |")

        for title, queries in (
            ("新查询整体 EXPLAIN", QUERIES),
            ("overview 标量子查询拆解", SCALARS),
        ):
            print()
            print(f"### {title}")
            for name, sql, extra in queries:
                rendered = substitute(sql.strip(), extra)
                rows = (await conn.execute(text("EXPLAIN " + rendered))).fetchall()
                print()
                print(f"**{name}**")
                print()
                print("```sql")
                print(rendered)
                print("```")
                print()
                print("\n".join(markdown_table(list(rows))))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
