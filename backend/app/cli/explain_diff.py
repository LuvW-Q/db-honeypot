"""EXPLAIN 对比 CLI：``python -m app.cli.explain_diff``。

按 `data-model.md` 7.3 / quickstart V20 的口径，对两条目标查询各做一次
「索引不可用（before）/ 索引可用（after）」对比：

- 目标查询 A（Q1）：按会话时间线读取 `attack_log`；
- 目标查询 B（Q2）：按告警等级与时间读取 `alerts`。

实现方式：不修改任何表结构（避免 DDL 与统计信息污染），而是在 before 查询里用
MySQL 的 ``IGNORE INDEX (索引名)`` 显式禁用目标索引，等价模拟"索引不可用"；
after 查询使用正常语句。两组查询分别在同一个只读连接、同一份数据上执行，
记录 ``EXPLAIN FORMAT=JSON`` 关键字段、``SHOW INDEX`` 索引现状与实测耗时中位数。

结果写入 ``db/explain/explain_YYYYMMDDTHHMMSSZ.json``，并在 stdout 打印摘要。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import REPO_ROOT, settings
from app.db.session import get_ro_engine, get_ro_factory

# 输出目录（仓库根目录下 db/explain）
OUTPUT_DIR = REPO_ROOT / "db" / "explain"

# 实测耗时采样次数（取中位数，减少偶发抖动）
TIMING_RUNS = 5

# 目标查询定义：before 用 IGNORE INDEX 模拟索引不可用
QUERY_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "group": "G1",
        "query_id": "Q1",
        "name": "按会话时间线读取事件",
        "table": "attack_log",
        "expected_index": "idx_log_session_time",
        "sql_before": (
            "SELECT event_id, event_type, event_time, status "
            "FROM attack_log IGNORE INDEX (idx_log_session_time) "
            "WHERE session_id = :session_id "
            "ORDER BY event_time, event_id"
        ),
        "sql_after": (
            "SELECT event_id, event_type, event_time, status "
            "FROM attack_log "
            "WHERE session_id = :session_id "
            "ORDER BY event_time, event_id"
        ),
        "params": "session_id",
        "expected": "type 由 ALL 变为 ref，key 命中 idx_log_session_time，rows 显著下降",
    },
    {
        "group": "G2",
        "query_id": "Q2",
        "name": "筛选近期高等级告警",
        "table": "alerts",
        "expected_index": "idx_alert_level_time",
        "sql_before": (
            "SELECT alert_id, severity, created_at "
            "FROM alerts IGNORE INDEX (idx_alert_level_time) "
            "WHERE severity = 'critical' "
            "ORDER BY created_at DESC LIMIT 20"
        ),
        "sql_after": (
            "SELECT alert_id, severity, created_at "
            "FROM alerts "
            "WHERE severity = 'critical' "
            "ORDER BY created_at DESC LIMIT 20"
        ),
        "params": None,
        "expected": "type 由 ALL 变为 ref，key 命中 idx_alert_level_time，避免 filesort",
    },
)


# ---------------------------------------------------------------------------
# 查询计划解析与计时
# ---------------------------------------------------------------------------


def _find_table_plan(node: Any) -> dict[str, Any] | None:
    """在 EXPLAIN JSON 中递归寻找 `table_name` 节点（兼容 ordering/nested_loop）。"""
    if isinstance(node, dict):
        if "table_name" in node:
            return node
        for value in node.values():
            found = _find_table_plan(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_table_plan(item)
            if found is not None:
                return found
    return None


def _find_ordering(node: Any) -> dict[str, Any] | None:
    """递归寻找 `ordering_operation` 节点（用于判断 filesort）。"""
    if isinstance(node, dict):
        if "ordering_operation" in node and isinstance(node["ordering_operation"], dict):
            return node["ordering_operation"]
        for value in node.values():
            found = _find_ordering(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_ordering(item)
            if found is not None:
                return found
    return None


def _extract_plan_fields(plan: dict[str, Any]) -> dict[str, Any]:
    """从 EXPLAIN JSON 中提取 7.3 记录模板要求的关键字段。"""
    query_block = plan.get("query_block", {}) if isinstance(plan, dict) else {}
    table = _find_table_plan(query_block) or {}
    ordering = _find_ordering(query_block) or {}
    return {
        "table": table.get("table_name"),
        "type": table.get("access_type"),
        "possible_keys": table.get("possible_keys"),
        "key": table.get("key"),
        "key_len": table.get("key_length"),
        "rows": table.get("rows_examined_per_scan"),
        "rows_produced": table.get("rows_produced_per_join"),
        "filtered": table.get("filtered"),
        "using_filesort": ordering.get("using_filesort"),
        "using_temporary_table": ordering.get("using_temporary_table"),
        "using_index": table.get("using_index"),
        "backward_index_scan": table.get("backward_index_scan"),
        "query_cost": (query_block.get("cost_info") or {}).get("query_cost"),
        "attached_condition": table.get("attached_condition"),
    }


async def _explain_json(db: AsyncSession, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    """执行 EXPLAIN FORMAT=JSON 并解析为字典。"""
    raw = (await db.execute(text("EXPLAIN FORMAT=JSON " + sql), params)).scalar()
    if not raw:
        raise RuntimeError("EXPLAIN 返回空结果")
    return json.loads(str(raw))


async def _timed_query(
    db: AsyncSession, sql: str, params: dict[str, Any], *, runs: int = TIMING_RUNS
) -> dict[str, Any]:
    """预热后重复执行查询，返回行数与耗时中位数（毫秒）。"""
    # 预热一次：加载缓冲池，避免第一次执行的冷启动误差
    (await db.execute(text(sql), params)).all()
    samples: list[float] = []
    row_count = 0
    for _ in range(max(1, runs)):
        started = time.perf_counter()
        rows = (await db.execute(text(sql), params)).all()
        elapsed_ms = (time.perf_counter() - started) * 1000
        samples.append(elapsed_ms)
        row_count = len(rows)
    return {
        "runs": max(1, runs),
        "row_count": row_count,
        "median_ms": round(statistics.median(samples), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
    }


async def _show_index(db: AsyncSession, table: str) -> list[dict[str, Any]]:
    """读取表的索引现状（SHOW INDEX），按索引名分组。"""
    rows = (await db.execute(text(f"SHOW INDEX FROM {table}"))).all()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        mapping = row._mapping
        index_name = str(mapping["Key_name"])
        item = grouped.setdefault(
            index_name,
            {
                "index_name": index_name,
                "unique": int(mapping["Non_unique"]) == 0,
                "visible": str(mapping.get("Visible", "YES")).upper() == "YES",
                "columns": [],
            },
        )
        item["columns"].append(str(mapping["Column_name"]))
    return list(grouped.values())


async def _dataset_stats(db: AsyncSession) -> dict[str, Any]:
    """记录数据集规模与本次查询参数，保证 EXPLAIN 结论可复现。"""
    version = str((await db.execute(text("SELECT VERSION()"))).scalar())
    stats = {}
    for table in ("attack_log", "sessions", "alerts", "rule_hits", "attacker_profile"):
        stats[table] = int((await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one())
    session_id = (
        await db.execute(
            text(
                "SELECT session_id FROM attack_log "
                "GROUP BY session_id ORDER BY COUNT(*) DESC LIMIT 1"
            )
        )
    ).scalar()
    return {
        "mysql_version": version,
        "tables": stats,
        "session_id_used": str(session_id or ""),
    }


# ---------------------------------------------------------------------------
# 对比记录构造
# ---------------------------------------------------------------------------


def _build_conclusion(
    *,
    before_fields: dict[str, Any],
    after_fields: dict[str, Any],
    before_timing: dict[str, Any],
    after_timing: dict[str, Any],
    expected_index: str,
) -> str:
    """生成中文结论：计划是否变化、是否按预期命中索引、耗时变化。"""
    before_type = before_fields.get("type")
    after_type = after_fields.get("type")
    after_key = after_fields.get("key")
    before_rows = before_fields.get("rows")
    after_rows = after_fields.get("rows")
    filesort_before = bool(before_fields.get("using_filesort"))
    filesort_after = bool(after_fields.get("using_filesort"))

    parts = [
        f"访问类型 {before_type} → {after_type}",
        f"实际索引 {before_fields.get('key') or 'NULL'} → {after_key or 'NULL'}",
        f"估算扫描行数 {before_rows} → {after_rows}",
        f"实测耗时中位数 {before_timing['median_ms']} ms → {after_timing['median_ms']} ms",
        f"filesort {filesort_before} → {filesort_after}",
    ]
    if after_key == expected_index and str(after_type) in {"ref", "range", "eq_ref", "const"}:
        parts.append(f"结论：索引可用后按预期命中 {expected_index}，计划达标")
    else:
        parts.append("结论：计划未按预期命中目标索引，需要检查统计信息或索引定义")
    return "；".join(parts)


async def _build_group(
    db: AsyncSession, definition: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """构造单组（Q1/Q2）的 before/after 对比记录。"""
    before_plan = await _explain_json(db, definition["sql_before"], params)
    after_plan = await _explain_json(db, definition["sql_after"], params)
    before_fields = _extract_plan_fields(before_plan)
    after_fields = _extract_plan_fields(after_plan)
    before_timing = await _timed_query(db, definition["sql_before"], params)
    after_timing = await _timed_query(db, definition["sql_after"], params)

    return {
        "group": definition["group"],
        "query_id": definition["query_id"],
        "name": definition["name"],
        "table": definition["table"],
        "expected_index": definition["expected_index"],
        "sql": {
            "before": definition["sql_before"],
            "after": definition["sql_after"],
        },
        "query_params": params,
        "explain": {
            "format": "JSON",
            "before": before_plan,
            "after": after_plan,
        },
        "plan_fields": {
            "before": before_fields,
            "after": after_fields,
        },
        "timing_ms": {
            "before": before_timing,
            "after": after_timing,
        },
        "index_presence": {
            "index_name": definition["expected_index"],
            "before": (
                "索引已存在，但 before 查询通过 IGNORE INDEX 显式禁用，"
                "等价模拟索引不可用（不执行 DDL，避免污染统计信息）"
            ),
            "after": "索引存在且可见，优化器可选择并命中该索引",
        },
        "conclusion": _build_conclusion(
            before_fields=before_fields,
            after_fields=after_fields,
            before_timing=before_timing,
            after_timing=after_timing,
            expected_index=definition["expected_index"],
        ),
        "expected": definition["expected"],
    }


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def _output_path(now: datetime) -> Path:
    """生成输出文件路径；同一秒重复运行时追加序号避免覆盖。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUTPUT_DIR / f"explain_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    if not base.exists():
        return base
    for index in range(1, 100):
        candidate = base.with_name(f"{base.stem}_{index}{base.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("无法生成不重复的 EXPLAIN 记录文件名")


def _print_summary(payload: dict[str, Any], output_path: Path) -> None:
    """打印人类可读摘要。"""
    print("=== EXPLAIN 索引前后对比摘要 ===")
    print(
        f"数据库：{payload['database']['host']}:{payload['database']['port']}/"
        f"{payload['database']['schema']}（MySQL {payload['dataset']['mysql_version']}）"
    )
    print(
        "数据规模："
        + "，".join(f"{name}={count}" for name, count in payload["dataset"]["tables"].items())
    )
    for group in payload["groups"]:
        fields = group["plan_fields"]
        timing = group["timing_ms"]
        print(f"[{group['group']}/{group['query_id']}] {group['name']}（表 {group['table']}）")
        print(
            "  before：type={type} key={key} rows={rows} filesort={fs} 耗时={before_ms} ms".format(
                type=fields["before"].get("type"),
                key=fields["before"].get("key"),
                rows=fields["before"].get("rows"),
                fs=fields["before"].get("using_filesort"),
                before_ms=timing["before"]["median_ms"],
            )
        )
        print(
            "  after ：type={type} key={key} rows={rows} filesort={fs} 耗时={after_ms} ms".format(
                type=fields["after"].get("type"),
                key=fields["after"].get("key"),
                rows=fields["after"].get("rows"),
                fs=fields["after"].get("using_filesort"),
                after_ms=timing["after"]["median_ms"],
            )
        )
        print(f"  结论：{group['conclusion']}")
    print(f"记录已写入：{output_path}")


async def run_explain() -> tuple[dict[str, Any], Path]:
    """执行两组对比并写入 JSON 记录，返回负载与文件路径。"""
    try:
        async with get_ro_factory()() as db:
            dataset = await _dataset_stats(db)
            if not dataset["session_id_used"]:
                raise RuntimeError("attack_log 为空，无法生成按会话时间线的 EXPLAIN 记录")
            params = {"session_id": dataset["session_id_used"]}

            groups: list[dict[str, Any]] = []
            for definition in QUERY_DEFINITIONS:
                query_params = params if definition["params"] else {}
                groups.append(await _build_group(db, definition, query_params))

            indexes = {
                "attack_log": await _show_index(db, "attack_log"),
                "alerts": await _show_index(db, "alerts"),
            }
    finally:
        # 在同一个事件循环内释放只读引擎，避免跨事件循环 dispose
        await get_ro_engine().dispose()

    now = datetime.now(UTC)
    url = settings.readonly_database_url
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    payload: dict[str, Any] = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "database": {
            "host": parsed.host or "127.0.0.1",
            "port": parsed.port or 3306,
            "schema": parsed.database or "",
        },
        "dataset": dataset,
        "method": (
            "不执行任何 DDL：before 查询用 IGNORE INDEX 显式禁用目标索引模拟索引不可用，"
            "after 查询正常执行；两条查询在同一只读连接、同一份数据上对比，"
            "耗时取预热后多次执行的中位数。"
        ),
        "timing_runs": TIMING_RUNS,
        "indexes": indexes,
        "groups": groups,
    }
    output_path = _output_path(now)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload, output_path


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：0 成功；3 数据库不可达或数据不足。"""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.explain_diff",
        description="生成按会话时间线与按告警等级时间的 EXPLAIN 索引前后对比记录",
    )
    parser.parse_args(argv)

    try:
        payload, output_path = asyncio.run(run_explain())
    except (SQLAlchemyError, RuntimeError, OSError) as exc:
        print(f"EXPLAIN 对比失败：{exc}", file=sys.stderr)
        return 3
    _print_summary(payload, output_path)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
