#!/usr/bin/env python3
"""M3 只读约束反查工具：从 information_schema 导出真实库结构为 JSON。

用途
----
`constraints/catalog.md` 与 `er/schema.mmd` 都必须与真实库一致，本脚本是二者的
对账数据源：连接 `DATABASE_URL`（默认取 `shared.config.settings.database_url`，
即 dev 库 `honeypot_dev`），逐表收集 columns / PK / FK / UNIQUE / CHECK / 索引，
输出稳定排序的 JSON。

只读保证
--------
脚本仅执行 `SELECT` 与 `SHOW` 类元数据查询，不写任何业务表；每表 `COUNT(*)`
也只是读取，用于把"约束对账"与"演示数据快照"一起留证。

用法
----
    # 仓库根执行；PYTHONPATH 需包含仓库根（shared 包）
    PYTHONPATH=. /tmp/dbh-venv/bin/python \
        modules/m3-er-constraints/tools/introspect_constraints.py

    # 机器可读 JSON 输出到 stdout
    ... introspect_constraints.py --json

    # 落盘证据
    ... introspect_constraints.py --out modules/m3-er-constraints/evidence/constraints.json

    # 指向其他库（例如测试库）
    ... introspect_constraints.py --schema honeypot_test --out /tmp/test-constraints.json

退出码：0 成功；1 连接/查询/写文件失败（错误信息与堆栈摘要写 stderr）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 导入 shared：脚本位于 <仓库根>/modules/m3-er-constraints/tools/，parents[3] 为仓库根。
# 允许显式 PYTHONPATH=.，这里再兜底一次，保证单文件可直接运行。
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from shared.config import settings  # noqa: E402

# 工具自身版本，便于证据中标注"哪一版工具产出的 JSON"
TOOL_VERSION = "m3-introspect-constraints/1.0"

# 非业务表：Alembic 版本表不属于 11 张业务表（见 docs/database-design.md 3 节）
NON_BUSINESS_TABLES = frozenset({"alembic_version"})


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

SQL_TABLES = text(
    """
    SELECT table_name, table_type, engine, row_format, table_collation,
           table_comment, table_rows
    FROM information_schema.tables
    WHERE table_schema = :schema
    ORDER BY table_name
    """
)

SQL_COLUMNS = text(
    """
    SELECT table_name, column_name, ordinal_position, column_default, is_nullable,
           data_type, column_type, character_maximum_length, numeric_precision,
           numeric_scale, datetime_precision, character_set_name, collation_name,
           column_key, extra, generation_expression, column_comment
    FROM information_schema.columns
    WHERE table_schema = :schema
    ORDER BY table_name, ordinal_position
    """
)

SQL_CONSTRAINTS = text(
    """
    SELECT table_name, constraint_name, constraint_type
    FROM information_schema.table_constraints
    WHERE table_schema = :schema
    ORDER BY table_name, constraint_type, constraint_name
    """
)

SQL_KEY_COLUMNS = text(
    """
    SELECT table_name, constraint_name, column_name, ordinal_position,
           position_in_unique_constraint, referenced_table_schema,
           referenced_table_name, referenced_column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = :schema
    ORDER BY table_name, constraint_name, ordinal_position
    """
)

SQL_REFERENTIAL = text(
    """
    SELECT table_name, constraint_name, unique_constraint_schema,
           unique_constraint_name, match_option, update_rule, delete_rule,
           referenced_table_name
    FROM information_schema.referential_constraints
    WHERE constraint_schema = :schema
    ORDER BY table_name, constraint_name
    """
)

SQL_CHECKS = text(
    """
    SELECT tc.table_name, cc.constraint_name, cc.check_clause
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.check_constraints AS cc
      ON cc.constraint_schema = tc.constraint_schema
     AND cc.constraint_name = tc.constraint_name
    WHERE tc.table_schema = :schema
      AND tc.constraint_type = 'CHECK'
    ORDER BY tc.table_name, cc.constraint_name
    """
)

SQL_INDEXES = text(
    """
    SELECT table_name, index_name, non_unique, seq_in_index, column_name,
           collation, sub_part, index_type, cardinality, nullable,
           index_comment, is_visible
    FROM information_schema.statistics
    WHERE table_schema = :schema
    ORDER BY table_name, index_name, seq_in_index
    """
)

SQL_VIEWS = text(
    """
    SELECT table_name, view_definition, check_option, is_updatable,
           security_type, character_set_client, collation_connection
    FROM information_schema.views
    WHERE table_schema = :schema
    ORDER BY table_name
    """
)

SQL_SERVER = text(
    """
    SELECT DATABASE() AS database_name,
           VERSION() AS server_version,
           @@session.time_zone AS session_time_zone,
           @@character_set_connection AS connection_charset,
           @@collation_connection AS connection_collation,
           @@sql_mode AS sql_mode
    """
)


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------


async def _rows(conn, statement, schema: str) -> list[dict[str, Any]]:
    """执行元数据查询并返回 dict 列表。

    information_schema 的列标签由 MySQL 原样返回大写（如 ``TABLE_NAME``），
    而本项目 JSON 使用小写键，这里统一降键名、保留值。
    """
    result = await conn.execute(statement, {"schema": schema})
    return [{str(key).lower(): value for key, value in row._mapping.items()} for row in result]


def _group_by_table(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 table_name 分组；保持查询内的排序。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["table_name"], []).append(row)
    return grouped


def _build_table(
    info: dict[str, Any],
    columns: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    key_columns: list[dict[str, Any]],
    referential: dict[str, dict[str, Any]],
    checks: list[dict[str, Any]],
    indexes: list[dict[str, Any]],
) -> dict[str, Any]:
    """把单张表的元数据整理成结构化条目。"""
    pk_names = [c["constraint_name"] for c in constraints if c["constraint_type"] == "PRIMARY KEY"]
    unique_names = [c["constraint_name"] for c in constraints if c["constraint_type"] == "UNIQUE"]

    def _columns_of(constraint_name: str) -> list[str]:
        return [
            row["column_name"]
            for row in key_columns
            if row["constraint_name"] == constraint_name
        ]

    primary_key: dict[str, Any] | None = None
    if pk_names:
        primary_key = {"name": pk_names[0], "columns": _columns_of(pk_names[0])}

    unique_constraints = [
        {"name": constraint_name, "columns": _columns_of(constraint_name)}
        for constraint_name in unique_names
    ]

    foreign_keys: list[dict[str, Any]] = []
    fk_names = [c["constraint_name"] for c in constraints if c["constraint_type"] == "FOREIGN KEY"]
    for constraint_name in fk_names:
        child_rows = [row for row in key_columns if row["constraint_name"] == constraint_name]
        child_rows.sort(key=lambda row: row["ordinal_position"])
        if not child_rows:
            continue
        rule = referential.get(constraint_name, {})
        foreign_keys.append(
            {
                "name": constraint_name,
                "columns": [row["column_name"] for row in child_rows],
                "referenced_table": child_rows[0]["referenced_table_name"],
                "referenced_columns": [
                    row["referenced_column_name"] for row in child_rows
                ],
                "on_update": rule.get("update_rule"),
                "on_delete": rule.get("delete_rule"),
            }
        )

    check_constraints = [
        {"name": row["constraint_name"], "clause": row["check_clause"]} for row in checks
    ]

    index_map: dict[str, dict[str, Any]] = {}
    for row in indexes:
        index_name = row["index_name"]
        entry = index_map.setdefault(
            index_name,
            {
                "name": index_name,
                "unique": not row["non_unique"],
                "type": row["index_type"],
                "columns": [],
                "cardinality": row["cardinality"],
                "visible": row["is_visible"],
                "comment": row["index_comment"],
            },
        )
        entry["columns"].append(row["column_name"])

    return {
        "table_type": info["table_type"],
        "business_table": info["table_type"] == "BASE TABLE"
        and info["table_name"] not in NON_BUSINESS_TABLES,
        "engine": info["engine"],
        "row_format": info["row_format"],
        "table_collation": info["table_collation"],
        "table_comment": info["table_comment"],
        "row_count": info.get("row_count"),
        "columns": [
            {
                "name": row["column_name"],
                "position": row["ordinal_position"],
                "column_type": row["column_type"],
                "data_type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "default": row["column_default"],
                "extra": row["extra"],
                "key": row["column_key"],
                "character_set": row["character_set_name"],
                "collation": row["collation_name"],
                "generation_expression": row["generation_expression"],
                "comment": row["column_comment"],
            }
            for row in columns
        ],
        "primary_key": primary_key,
        "foreign_keys": foreign_keys,
        "unique_constraints": unique_constraints,
        "check_constraints": check_constraints,
        "indexes": sorted(index_map.values(), key=lambda item: item["name"]),
    }


async def collect(schema: str | None, database_url: str | None) -> dict[str, Any]:
    """连接数据库并收集全部元数据，返回可直接 json.dumps 的字典。"""
    url = database_url or settings.database_url
    engine = create_async_engine(url)
    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        async with engine.connect() as conn:
            server = {
                str(key).lower(): value
                for key, value in (await conn.execute(SQL_SERVER)).mappings().one().items()
            }
            effective_schema = schema or server["database_name"]
            if not effective_schema:
                raise RuntimeError(
                    "无法确定目标库：DATABASE_URL 未携带库名且未传 --schema"
                )

            tables = await _rows(conn, SQL_TABLES, effective_schema)
            columns = await _rows(conn, SQL_COLUMNS, effective_schema)
            constraints = await _rows(conn, SQL_CONSTRAINTS, effective_schema)
            key_columns = await _rows(conn, SQL_KEY_COLUMNS, effective_schema)
            referential_rows = await _rows(conn, SQL_REFERENTIAL, effective_schema)
            checks = await _rows(conn, SQL_CHECKS, effective_schema)
            indexes = await _rows(conn, SQL_INDEXES, effective_schema)
            views = await _rows(conn, SQL_VIEWS, effective_schema)

            referential = {row["constraint_name"]: row for row in referential_rows}
            grouped_columns = _group_by_table(columns)
            grouped_constraints = _group_by_table(constraints)
            grouped_keys = _group_by_table(key_columns)
            grouped_checks = _group_by_table(checks)
            grouped_indexes = _group_by_table(indexes)

            # 行数：只对 BASE TABLE 取精确 COUNT(*)，用于把约束对账与数据快照一起留证
            row_counts: dict[str, int] = {}
            for table in tables:
                if table["table_type"] != "BASE TABLE":
                    continue
                table_name = table["table_name"]
                quoted = table_name.replace("`", "``")
                count = (
                    await conn.execute(text(f"SELECT COUNT(*) FROM `{quoted}`"))
                ).scalar_one()
                row_counts[table_name] = int(count)

            table_payload: dict[str, Any] = {}
            for table in tables:
                table_name = table["table_name"]
                info = dict(table, row_count=row_counts.get(table_name))
                table_payload[table_name] = _build_table(
                    info=info,
                    columns=grouped_columns.get(table_name, []),
                    constraints=grouped_constraints.get(table_name, []),
                    key_columns=grouped_keys.get(table_name, []),
                    referential=referential,
                    checks=grouped_checks.get(table_name, []),
                    indexes=grouped_indexes.get(table_name, []),
                )

            business_tables = [
                name for name, item in table_payload.items() if item["business_table"]
            ]
            summary = {
                "schema": effective_schema,
                "base_tables": sum(
                    1 for item in table_payload.values() if item["table_type"] == "BASE TABLE"
                ),
                "business_tables": len(business_tables),
                "business_table_names": business_tables,
                "views": len(views),
                "view_names": [view["table_name"] for view in views],
                "foreign_keys": sum(
                    len(item["foreign_keys"]) for item in table_payload.values()
                ),
                "unique_constraints": sum(
                    len(item["unique_constraints"]) for item in table_payload.values()
                ),
                "check_constraints": sum(
                    len(item["check_constraints"]) for item in table_payload.values()
                ),
                "indexes": sum(len(item["indexes"]) for item in table_payload.values()),
                "generated_columns": sum(
                    1
                    for item in table_payload.values()
                    for column in item["columns"]
                    if column["generation_expression"]
                ),
                "rows_total": sum(row_counts.values()),
            }

            return {
                "meta": {
                    "tool": TOOL_VERSION,
                    "collected_at": collected_at,
                    "schema": effective_schema,
                    "database_url": make_url(url).render_as_string(hide_password=True),
                    "server_version": server["server_version"],
                    "session_time_zone": server["session_time_zone"],
                    "connection_charset": server["connection_charset"],
                    "connection_collation": server["connection_collation"],
                    "sql_mode": server["sql_mode"],
                },
                "summary": summary,
                "tables": table_payload,
                "views": [
                    {
                        "name": view["table_name"],
                        "security_type": view["security_type"],
                        "is_updatable": view["is_updatable"],
                        "check_option": view["check_option"],
                        "definition": view["view_definition"],
                    }
                    for view in views
                ],
            }
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def render_summary(payload: dict[str, Any]) -> str:
    """把 JSON 结果渲染成便于人工核对的表格摘要。"""
    meta = payload["meta"]
    summary = payload["summary"]
    lines = [
        f"库: {meta['schema']}    MySQL: {meta['server_version']}    "
        f"时区: {meta['session_time_zone']}",
        f"连接: {meta['database_url']}",
        f"业务表 {summary['business_tables']} / 基础表 {summary['base_tables']} / "
        f"视图 {summary['views']}",
        f"外键 {summary['foreign_keys']} / 唯一 {summary['unique_constraints']} / "
        f"CHECK {summary['check_constraints']} / 索引 {summary['indexes']} / "
        f"生成列 {summary['generated_columns']}",
        "",
        f"{'表名':<18}{'列':>4}{'PK':>4}{'FK':>4}{'UK':>4}{'CK':>4}{'IDX':>5}{'行数':>7}",
    ]
    for name, table in payload["tables"].items():
        lines.append(
            f"{name:<18}{len(table['columns']):>4}"
            f"{1 if table['primary_key'] else 0:>4}"
            f"{len(table['foreign_keys']):>4}"
            f"{len(table['unique_constraints']):>4}"
            f"{len(table['check_constraints']):>4}"
            f"{len(table['indexes']):>5}"
            f"{table['row_count'] if table['row_count'] is not None else '-':>7}"
        )
    lines.append("")
    lines.append("视图: " + ", ".join(summary["view_names"]))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="introspect_constraints.py",
        description="只读反查 MySQL information_schema，导出 M3 约束目录 JSON。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="把完整 JSON 打印到 stdout（默认打印人工核对用的摘要表）",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="把完整 JSON 写入指定文件（自动创建父目录）",
    )
    parser.add_argument(
        "--schema",
        metavar="DB",
        default=None,
        help="目标库名；默认取 DATABASE_URL 中的库（dev 库 honeypot_dev）",
    )
    parser.add_argument(
        "--database-url",
        metavar="URL",
        default=None,
        help="覆盖 DATABASE_URL（默认 shared.config.settings.database_url）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = asyncio.run(collect(schema=args.schema, database_url=args.database_url))
    except Exception as exc:  # noqa: BLE001 - 统一转为退出码 1，错误写 stderr
        print(f"[introspect] 失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[introspect] 写文件失败 {out_path}: {exc}", file=sys.stderr)
            return 1
        print(f"[introspect] 已写入 {out_path}", file=sys.stderr)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_summary(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
