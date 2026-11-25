"""固定合成样本导入 CLI：``python -m m2_decoy_capture.cli.import_samples``。

契约（`specs/001-database-honeypot/contracts/api.md` 4.2）：

- ``--sample S01`` 可重复；``--set demo_basic`` 一次导入核心样本；两者二选一；
- ``--repeat N`` 在同一次进程内重复导入，用于验证 ``event_uuid`` 幂等；
- ``--dry-run`` 只解析并打印计划，不连接数据库；
- ``--database-url`` 只允许指向本机数据库，否则拒绝并以退出码 3 退出；
- 默认向 stdout 输出机器可读 JSON，``--no-json`` 时输出人类可读表格。

实现要点：样本通过 ``IngestService`` 逐事件写入，走与真实捕获完全相同的事务、
规则分析、画像与告警流水线；本脚本**不执行**样本中的任何 SQL，也不访问诱饵端口。
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys
from datetime import UTC, datetime
from typing import Any

from m1_transaction_integration import public as transaction_api
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from m2_decoy_capture.samples import GROUPS, Sample, get_group, get_sample
from shared.db.session import get_rw_engine, get_rw_factory
from shared.utils.risk import risk_level

# 允许连接的本机主机名（契约：只允许 127.0.0.1 / localhost / ::1）
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# 重复导入次数上限（api.md 4.2：1..20）
_MIN_REPEAT = 1
_MAX_REPEAT = 20


# ---------------------------------------------------------------------------
# 参数解析与数据库地址校验
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m m2_decoy_capture.cli.import_samples",
        description="导入固定合成样本（S01–S07 / demo_basic），重复导入幂等",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--sample",
        action="append",
        metavar="S01",
        help="单个样本编号，可重复传入（如 --sample S03 --sample S04）",
    )
    source_group.add_argument(
        "--set",
        dest="sample_set",
        metavar="demo_basic",
        help=f"样本组名，可选：{', '.join(GROUPS)}",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help=f"单样本重复导入次数（{_MIN_REPEAT}..{_MAX_REPEAT}），用于验证幂等",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析样本并打印将产生的会话/事件/命中/告警，不写数据库",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="导入前先重置观测数据（调用 reset_demo_data，保留规则与诱饵种子）",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="覆盖 .env 的 DATABASE_URL；只允许指向本机数据库",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=True,
        help="输出机器可读 JSON（默认开启）",
    )
    parser.add_argument(
        "--no-json",
        dest="json_output",
        action="store_false",
        help="输出人类可读表格而非 JSON",
    )
    return parser


def _normalize_database_url(raw: str | None) -> URL | None:
    """规范化并校验数据库 URL；非本机地址返回 None（由调用方以退出码 3 拒绝）。"""
    if not raw:
        return None
    value = raw.strip()
    if value.startswith("mysql://"):
        value = "mysql+asyncmy://" + value[len("mysql://") :]
    try:
        url = make_url(value)
    except Exception:  # noqa: BLE001 - URL 解析失败按参数错误处理
        return None
    host = (url.host or "").strip().lower()
    if host not in _LOCAL_HOSTS:
        return None
    return url


def _is_local_host(host: str | None) -> bool:
    """判断主机是否为本机回环地址（localhost / 127.0.0.0/8 / ::1）。"""
    if not host:
        return True
    value = host.strip().lower().strip("[]")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _resolve_samples(args: argparse.Namespace) -> list[Sample]:
    """解析 --sample / --set，返回待导入样本列表。"""
    if args.sample_set:
        return list(get_group(args.sample_set))
    if args.sample:
        seen: list[Sample] = []
        for sample_id in args.sample:
            sample = get_sample(sample_id)
            if sample.sample_id not in {item.sample_id for item in seen}:
                seen.append(sample)
        return seen
    raise ValueError("必须提供 --sample 或 --set")


# ---------------------------------------------------------------------------
# 数据库会话工厂
# ---------------------------------------------------------------------------


class _Database:
    """管理默认/自定义数据库引擎的上下文对象。"""

    def __init__(self, database_url: URL | None) -> None:
        self.url = database_url
        self.engine: AsyncEngine | None = None
        self.factory: async_sessionmaker[AsyncSession] | None = None

    async def __aenter__(self) -> async_sessionmaker[AsyncSession]:
        if self.url is None:
            self.factory = get_rw_factory()
            return self.factory
        self.engine = create_async_engine(
            self.url.render_as_string(hide_password=False),
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        return self.factory

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - 上下文协议
        if self.engine is not None:
            await self.engine.dispose()
        else:
            await get_rw_engine().dispose()


def _database_description(database_url: URL | None) -> dict[str, Any]:
    """输出 JSON 中的 database 摘要（绝不包含口令）。"""
    from shared.config import settings

    url = database_url or make_url(settings.database_url)
    return {
        "host": url.host or "127.0.0.1",
        "port": url.port or 3306,
        "schema": url.database or "",
    }


# ---------------------------------------------------------------------------
# 导入逻辑
# ---------------------------------------------------------------------------


async def _existing_session_ids(db: AsyncSession, session_ids: list[str]) -> set[str]:
    """查询已经存在的会话编号集合。"""
    if not session_ids:
        return set()
    placeholders = ", ".join(f":sid_{index}" for index in range(len(session_ids)))
    params = {f"sid_{index}": value for index, value in enumerate(session_ids)}
    rows = (
        await db.execute(
            text(f"SELECT session_id FROM sessions WHERE session_id IN ({placeholders})"),
            params,
        )
    ).scalars()
    return {str(value) for value in rows}


async def _actual_rule_hits(db: AsyncSession, event_uuids: list[str]) -> list[str]:
    """按样本事件 UUID 查询库内实际命中（第二次幂等导入也能返回稳定结果）。"""
    if not event_uuids:
        return []
    placeholders = ", ".join(f":eid_{index}" for index in range(len(event_uuids)))
    params = {f"eid_{index}": value for index, value in enumerate(event_uuids)}
    rows = (
        await db.execute(
            text(
                f"""
                SELECT DISTINCT rh.rule_code
                FROM rule_hits AS rh
                JOIN attack_log AS al ON al.event_id = rh.event_id
                WHERE al.event_uuid IN ({placeholders})
                ORDER BY rh.rule_code
                """
            ),
            params,
        )
    ).scalars()
    return [str(value) for value in rows]


async def _actual_alerts(db: AsyncSession, session_ids: list[str]) -> list[int]:
    """按样本会话查询库内实际告警编号（稳定、可重复）。"""
    if not session_ids:
        return []
    placeholders = ", ".join(f":sid_{index}" for index in range(len(session_ids)))
    params = {f"sid_{index}": value for index, value in enumerate(session_ids)}
    rows = (
        await db.execute(
            text(
                f"SELECT alert_id FROM alerts WHERE session_id IN ({placeholders}) "
                "ORDER BY alert_id"
            ),
            params,
        )
    ).scalars()
    return [int(value) for value in rows]


async def _session_risk_scores(db: AsyncSession, session_ids: list[str]) -> dict[str, int]:
    """查询样本会话的最终风险分。"""
    if not session_ids:
        return {}
    placeholders = ", ".join(f":sid_{index}" for index in range(len(session_ids)))
    params = {f"sid_{index}": value for index, value in enumerate(session_ids)}
    rows = (
        await db.execute(
            text(
                "SELECT session_id, max_risk_score FROM sessions "
                f"WHERE session_id IN ({placeholders})"
            ),
            params,
        )
    ).all()
    return {str(row.session_id): int(row.max_risk_score or 0) for row in rows}


async def run_import(
    samples: list[Sample],
    *,
    repeat: int,
    database_url: URL | None,
    dry_run: bool,
    clean: bool,
) -> dict[str, Any]:
    """执行导入并返回输出契约所需的 JSON 负载。"""
    database_info = _database_description(database_url)
    payload: dict[str, Any] = {
        "set": None,
        "dry_run": dry_run,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "database": database_info,
        "samples": [],
        "imported": {"sessions": 0, "events": 0, "rule_hits": 0, "alerts": 0},
        "deduped": {"sessions": 0, "events": 0, "rule_hits": 0, "alerts": 0},
        "failed": [],
    }

    if dry_run:
        for sample in samples:
            summary = sample.expected_summary()
            payload["samples"].append(
                {
                    "sample_id": sample.sample_id,
                    "sample": sample.sample_id,
                    "session_id": sample.session_ids[0],
                    "session_ids": list(sample.session_ids),
                    "event_count": len(sample.events),
                    "rule_hits": list(sample.expected_hits),
                    "hits": list(sample.expected_hits),
                    "alerts": [],
                    "alert_count": len(sample.expected_alerts),
                    "expected": summary,
                    "matched": True,
                    "status": "planned",
                }
            )
        return payload

    async with _Database(database_url) as factory:
        # 连接与迁移就绪检查：失败以退出码 3 由上层处理
        async with factory() as db:
            try:
                await db.execute(text("SELECT 1"))
                rule_count = (
                    await db.execute(text("SELECT COUNT(*) FROM detection_rules"))
                ).scalar_one()
            except SQLAlchemyError as exc:
                raise RuntimeError(f"数据库不可达或迁移未执行：{exc}") from exc
            if int(rule_count or 0) < 5:
                raise RuntimeError(
                    "detection_rules 少于 5 条，请先执行 `make migrate && make seed`"
                )
            if clean:
                cleaned = await transaction_api.reset_demo(operator="import_samples")
                payload["cleaned"] = cleaned

        async with factory() as db:
            for sample in samples:
                sample_events = list(sample.events)
                event_uuids = [spec.event_uuid for spec in sample_events]
                session_ids = list(sample.session_ids)
                existing = await _existing_session_ids(db, session_ids)
                imported_events = 0
                deduped_events = 0
                new_hit_codes: list[str] = []
                new_alert_ids: list[int] = []

                try:
                    for _ in range(repeat):
                        for spec in sample_events:
                            result = await transaction_api.ingest_event(
                                spec.to_captured_event()
                            )
                            if result.duplicate:
                                deduped_events += 1
                                continue
                            imported_events += 1
                            for hit in result.rule_hits:
                                if hit.rule_code not in new_hit_codes:
                                    new_hit_codes.append(hit.rule_code)
                            for alert_id in result.alerts:
                                if alert_id not in new_alert_ids:
                                    new_alert_ids.append(alert_id)
                except Exception as exc:  # noqa: BLE001 - 单样本失败不影响其他样本
                    payload["failed"].append({"sample": sample.sample_id, "error": str(exc)})
                    continue

                # 以库内结果为准，保证重复导入（全部 dedupe）时输出仍稳定可核对。
                # ingest_event 使用独立事务，先结束本会话的只读事务再读最新提交。
                await db.rollback()
                actual_hits = await _actual_rule_hits(db, event_uuids)
                actual_alert_ids = await _actual_alerts(db, session_ids)
                risk_scores = await _session_risk_scores(db, session_ids)
                existing_after = await _existing_session_ids(db, session_ids)
                max_risk = max(risk_scores.values(), default=0)

                sample_payload = {
                    "sample_id": sample.sample_id,
                    "sample": sample.sample_id,
                    "title": sample.title,
                    "session_id": session_ids[0],
                    "session_ids": session_ids,
                    "event_count": len(sample_events),
                    "imported_events": imported_events,
                    "deduped_events": deduped_events,
                    "new_rule_hits": new_hit_codes,
                    "rule_hits": actual_hits,
                    "hits": actual_hits,
                    "alerts": actual_alert_ids,
                    "new_alerts": new_alert_ids,
                    "alert_count": len(actual_alert_ids),
                    "risk_scores": risk_scores,
                    "risk_score": max_risk,
                    "risk_level": risk_level(max_risk),
                    "expected": sample.expected_summary(),
                    "matched": set(actual_hits) == set(sample.expected_hits),
                    "status": "imported",
                }
                payload["samples"].append(sample_payload)

                payload["imported"]["events"] += imported_events
                payload["imported"]["rule_hits"] += len(new_hit_codes)
                payload["imported"]["alerts"] += len(new_alert_ids)
                payload["imported"]["sessions"] += len(existing_after - existing)
                payload["deduped"]["events"] += deduped_events

    payload["imported_total"] = payload["imported"]["events"]
    payload["deduped_total"] = payload["deduped"]["events"]
    return payload


# ---------------------------------------------------------------------------
# 输出与入口
# ---------------------------------------------------------------------------


def _print_human(payload: dict[str, Any]) -> None:
    """人类可读输出（--no-json）。"""
    print(f"样本导入结果：dry_run={payload['dry_run']} 数据库={payload['database']}")
    header = f"{'样本':6} {'事件':>4} {'导入':>4} {'去重':>4} {'命中':16} {'告警':>4} {'风险分':>6} {'匹配':>4}"
    print(header)
    for item in payload["samples"]:
        hits = ",".join(item.get("rule_hits") or []) or "-"
        print(
            f"{item['sample']:6} {item.get('event_count', 0):>4} "
            f"{item.get('imported_events', 0):>4} {item.get('deduped_events', 0):>4} "
            f"{hits:16} {item.get('alert_count', 0):>4} "
            f"{item.get('risk_score', 0):>6} {str(item.get('matched', '-')):>4}"
        )
    imported = payload["imported"]
    deduped = payload["deduped"]
    print(
        "合计：导入 sessions={sessions} events={events} rule_hits={rule_hits} "
        "alerts={alerts}；去重 events={deduped_events}".format(
            sessions=imported["sessions"],
            events=imported["events"],
            rule_hits=imported["rule_hits"],
            alerts=imported["alerts"],
            deduped_events=deduped["events"],
        )
    )
    if payload["failed"]:
        print(f"失败样本：{payload['failed']}")


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：返回 0/1/2/3（见 api.md 4.2 退出码表）。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not _MIN_REPEAT <= args.repeat <= _MAX_REPEAT:
        print(
            f"--repeat 必须在 {_MIN_REPEAT}..{_MAX_REPEAT} 之间，当前 {args.repeat}",
            file=sys.stderr,
        )
        return 2

    try:
        samples = _resolve_samples(args)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # --set 的组名通过 payload.set 回显（--sample 时为 null）
    explicit_set = args.sample_set.lower() if args.sample_set else None

    database_url: URL | None = None
    if args.database_url:
        database_url = _normalize_database_url(args.database_url)
        if database_url is None:
            print(
                "拒绝执行：--database-url 只允许指向本机数据库（127.0.0.1/localhost/::1）",
                file=sys.stderr,
            )
            return 3
    else:
        from shared.config import settings

        if not _is_local_host(make_url(settings.database_url).host):
            print(
                "拒绝执行：.env 中 DATABASE_URL 不是本机数据库；请使用 --database-url 指定本机地址",
                file=sys.stderr,
            )
            return 3

    try:
        payload = asyncio.run(
            run_import(
                samples,
                repeat=args.repeat,
                database_url=database_url,
                dry_run=args.dry_run,
                clean=args.clean,
            )
        )
    except RuntimeError as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI 需要明确失败信息
        print(f"导入异常：{exc}", file=sys.stderr)
        return 3

    payload["set"] = explicit_set
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        _print_human(payload)

    if payload["failed"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
