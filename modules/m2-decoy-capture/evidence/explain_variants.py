"""补充 EXPLAIN 变体证据：同一时间线的不同写法（只读，无 DDL）。

`m2_decoy_capture.cli.explain_diff` 固定产出两组（Q1 会话时间线 / Q2 告警等级时间）。
本脚本追加两组**同一时间线的不同写法**对比，方法与 CLI 完全一致：

- before 用 ``IGNORE INDEX`` 显式禁用目标索引，等价“索引不可用”，不执行任何 DDL；
- after 正常执行；
- 同一只读连接、同一份数据，预热后取 5 次中位耗时。

产出写入 ``modules/m2-decoy-capture/evidence/explain/explain_variants_<UTC>.json``。

用法（仓库根执行）::

    PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console \
        /tmp/dbh-venv/bin/python modules/m2-decoy-capture/evidence/explain_variants.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from m2_decoy_capture.cli.explain_diff import (
    _explain_json,
    _extract_plan_fields,
    _timed_query,
)
from sqlalchemy import text

from shared.config import REPO_ROOT
from shared.db.session import get_ro_engine, get_ro_factory

OUTPUT_DIR = REPO_ROOT / "modules/m2-decoy-capture/evidence/explain"
SID = "5a060001-0000-4000-8000-000000000001"
SOURCE_IP = "198.51.100.17"
TIMING_RUNS = 5

VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "group": "G3",
        "query_id": "Q3",
        "name": "同一会话时间线 + event_time 下界（增量拉取写法）",
        "table": "attack_log",
        "expected_index": "idx_log_session_time",
        "sql_before": (
            "SELECT event_id, event_type, event_time, status FROM attack_log "
            "IGNORE INDEX (idx_log_session_time) "
            "WHERE session_id = :sid AND event_time >= :t0 ORDER BY event_time, event_id"
        ),
        "sql_after": (
            "SELECT event_id, event_type, event_time, status FROM attack_log "
            "WHERE session_id = :sid AND event_time >= :t0 ORDER BY event_time, event_id"
        ),
        "params": {"sid": SID, "t0": "2026-11-18 06:00:09"},
        "expected": (
            "type=ALL + filesort → type=range，key 命中 idx_log_session_time，"
            "key_len 由 36 增至 44（session_id 36 + event_time 8）"
        ),
    },
    {
        "group": "G4",
        "query_id": "Q4",
        "name": "按来源 IP 倒序取最近事件（告警溯源写法）",
        "table": "attack_log",
        "expected_index": "idx_log_source_time",
        "sql_before": (
            "SELECT event_id, event_type, event_time, session_id FROM attack_log "
            "IGNORE INDEX (idx_log_source_time) "
            "WHERE source_ip = :ip ORDER BY event_time DESC LIMIT 20"
        ),
        "sql_after": (
            "SELECT event_id, event_type, event_time, session_id FROM attack_log "
            "WHERE source_ip = :ip ORDER BY event_time DESC LIMIT 20"
        ),
        "params": {"ip": SOURCE_IP},
        "expected": ("type=ALL + filesort → type=ref + 反向索引扫描，key 命中 idx_log_source_time"),
    },
)


async def _build(db, definition: dict[str, Any]) -> dict[str, Any]:
    """构造单组 before/after 对比记录。"""
    params = definition["params"]
    before_plan = await _explain_json(db, definition["sql_before"], params)
    after_plan = await _explain_json(db, definition["sql_after"], params)
    return {
        "group": definition["group"],
        "query_id": definition["query_id"],
        "name": definition["name"],
        "table": definition["table"],
        "expected_index": definition["expected_index"],
        "sql": {"before": definition["sql_before"], "after": definition["sql_after"]},
        "query_params": {key: str(value) for key, value in params.items()},
        "explain": {"format": "JSON", "before": before_plan, "after": after_plan},
        "plan_fields": {
            "before": _extract_plan_fields(before_plan),
            "after": _extract_plan_fields(after_plan),
        },
        "timing_ms": {
            "before": await _timed_query(db, definition["sql_before"], params),
            "after": await _timed_query(db, definition["sql_after"], params),
        },
        "expected": definition["expected"],
    }


async def run_variants() -> tuple[dict[str, Any], Path]:
    """执行两组变体对比并写入 JSON，返回负载与文件路径。"""
    groups: list[dict[str, Any]] = []
    async with get_ro_factory()() as db:
        version = str((await db.execute(text("SELECT VERSION()"))).scalar())
        stats = {
            table: int((await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one())
            for table in ("attack_log", "sessions", "alerts")
        }
        for definition in VARIANTS:
            groups.append(await _build(db, definition))
    await get_ro_engine().dispose()

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_date": "2026-11-25",
        "kind": "supplementary-variants",
        "note": (
            "explain_diff CLI 固定两组（Q1/Q2）；本文件补充『同一时间线的不同写法』两组，"
            "方法一致（IGNORE INDEX，无 DDL，只读）。"
        ),
        "database": {"host": "127.0.0.1", "port": 3306, "schema": "honeypot_dev"},
        "dataset": {"mysql_version": version, "tables": stats},
        "method": (
            "before 用 IGNORE INDEX 显式禁用目标索引模拟索引不可用；after 正常执行；"
            "同一只读连接，预热后 5 次中位耗时。"
        ),
        "timing_runs": TIMING_RUNS,
        "groups": groups,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUTPUT_DIR / f"explain_variants_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path = base
    for index in range(1, 100):
        if not path.exists():
            break
        path = base.with_name(f"{base.stem}_{index}{base.suffix}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload, path


def main() -> int:
    """CLI 入口：打印摘要并返回 0。"""
    payload, path = asyncio.run(run_variants())
    print("=== EXPLAIN 同时间线不同写法对比（补充） ===")
    print(
        f"数据库：{payload['database']['host']}:{payload['database']['port']}/"
        f"{payload['database']['schema']}（MySQL {payload['dataset']['mysql_version']}）"
    )
    for group in payload["groups"]:
        fields = group["plan_fields"]
        timing = group["timing_ms"]
        print(f"[{group['group']}/{group['query_id']}] {group['name']}（表 {group['table']}）")
        print(
            "  before：type={} key={} rows={} filesort={} 耗时={} ms".format(
                fields["before"].get("type"),
                fields["before"].get("key"),
                fields["before"].get("rows"),
                fields["before"].get("using_filesort"),
                timing["before"]["median_ms"],
            )
        )
        print(
            "  after ：type={} key={} key_len={} rows={} filesort={} 耗时={} ms".format(
                fields["after"].get("type"),
                fields["after"].get("key"),
                fields["after"].get("key_len"),
                fields["after"].get("rows"),
                fields["after"].get("using_filesort"),
                timing["after"]["median_ms"],
            )
        )
    print(f"记录已写入：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
