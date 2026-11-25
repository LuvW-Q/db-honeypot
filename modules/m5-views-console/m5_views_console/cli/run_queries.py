#!/usr/bin/env python3
"""执行 `views/queries.sql` 中的代表性查询并落盘（M5 证据脚本，只读）。

用法（仓库根）::

    PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console \
      /tmp/dbh-venv/bin/python -m m5_views_console.cli.run_queries

行为：

1. 从 `views/queries.sql` 抽取 `-- @query: <id>` 与 `-- @end` 之间的 SQL；
2. 用只读账号（`READONLY_DATABASE_URL`）连接并执行 `SET SESSION TRANSACTION READ ONLY`；
3. 把服务端版本、执行时间、SQL、行数与结果写入 `queries-output.txt`。

只执行 SELECT；不写库、不提交事务。退出码：0 全部成功，1 有查询失败，2 连接失败。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

try:  # 允许从仓库根或本目录直接运行
    from shared.config import settings
    from shared.db.session import get_ro_factory
except ModuleNotFoundError:  # pragma: no cover - 兜底提示
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from shared.config import settings
    from shared.db.session import get_ro_factory

QUERY_RE = re.compile(
    r"^--\s*@query:\s*(?P<id>\S+)\s*$\n(?P<sql>.*?)^--\s*@end\s*$",
    re.MULTILINE | re.DOTALL,
)

DEFAULT_SQL = Path(__file__).resolve().parents[2] / "views" / "queries.sql"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "evidence" / "sql-ui" / "queries-output.txt"


def parse_queries(path: Path) -> list[tuple[str, str]]:
    """抽取 `@query` 标记块，返回 [(id, sql)]。"""
    content = path.read_text(encoding="utf-8")
    queries = [
        (match.group("id").strip(), match.group("sql").strip())
        for match in QUERY_RE.finditer(content)
    ]
    if not queries:
        raise RuntimeError(f"{path} 中未找到任何 `-- @query:` 标记块")
    return queries


def mask_url(raw: str) -> str:
    """隐去连接串中的口令，仅保留账号/主机/库名。"""
    url = make_url(raw)
    return f"{url.drivername}://{url.username}@{url.host}:{url.port}/{url.database}"


def cell(value: Any) -> str:
    """把单元格值转成单行文本（NULL 显示为 NULL）。"""
    if value is None:
        return "NULL"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("\n", "\\n").replace("\t", "\\t")


def format_table(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    """把结果渲染成对齐的纯文本表格。"""
    if not rows:
        return ["(0 行)"]
    widths = [len(name) for name in columns]
    rendered: list[list[str]] = []
    for row in rows:
        cells = [cell(row.get(name)) for name in columns]
        rendered.append(cells)
        widths = [max(width, len(value)) for width, value in zip(widths, cells, strict=True)]
    lines = ["-+-".join(name.ljust(width) for name, width in zip(columns, widths, strict=True))]
    lines.append("-+-".join("-" * width for width in widths))
    lines.extend(
        " | ".join(value.ljust(width) for value, width in zip(cells, widths, strict=True))
        for cells in rendered
    )
    return lines


async def run(sql_path: Path, out_path: Path) -> int:
    """执行全部标记查询并写证据文件，返回退出码。"""
    queries = parse_queries(sql_path)
    started = datetime.now(UTC)
    try:
        sql_display = sql_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:  # 不在当前工作目录下时保留绝对路径
        sql_display = str(sql_path)
    lines: list[str] = [
        "# M5 四视图代表性查询真实执行输出",
        f"# 生成时间（UTC）：{started.isoformat(timespec='seconds')}",
        f"# SQL 文件：{sql_display}",
        f"# 连接：{mask_url(settings.readonly_database_url)}（只读账号，会话 READ ONLY）",
        "",
    ]

    try:
        factory = get_ro_factory()
        async with factory() as session:
            await session.execute(text("SET SESSION TRANSACTION READ ONLY"))
            version = (await session.execute(text("SELECT VERSION()"))).scalar_one()
            lines.insert(3, f"# MySQL 版本：{version}")
            for index, (query_id, sql) in enumerate(queries, start=1):
                one_line = " ".join(sql.split())
                begin = datetime.now(UTC)
                result = await session.execute(text(sql))
                rows = [dict(row) for row in result.mappings().all()]
                elapsed_ms = (datetime.now(UTC) - begin).total_seconds() * 1000
                lines.append(f"[{index}/{len(queries)}] {query_id} —— OK")
                lines.append(f"SQL: {one_line}")
                lines.append(f"行数: {len(rows)}　耗时: {elapsed_ms:.1f} ms")
                lines.append("结果:")
                lines.extend(format_table(list(rows[0].keys()) if rows else [], rows))
                lines.append("")
            await session.rollback()
    except Exception as exc:  # noqa: BLE001 - 连接/执行错误都要落盘并区分退出码
        lines.append(f"[FAIL] 数据库连接或查询失败：{type(exc).__name__}: {exc}")
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"数据库连接或查询失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {out_path}（{len(queries)} 条查询全部成功）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行 M5 四视图代表性查询并落盘（只读）")
    parser.add_argument("--sql", type=Path, default=DEFAULT_SQL, help="queries.sql 路径")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出文本路径")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.sql, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
