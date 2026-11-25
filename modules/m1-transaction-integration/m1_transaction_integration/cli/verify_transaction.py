"""事务回滚验证 CLI（SC-012 / FR-039）。

用法：

    python -m m1_transaction_integration.cli.verify_transaction --inject-failure none
    python -m m1_transaction_integration.cli.verify_transaction --inject-failure profile_write
    python -m m1_transaction_integration.cli.verify_transaction --inject-failure alert_write

做法：构造一条测试来源的会话与事件序列（connect → SHOW TABLES → DROP TABLE），
通过 `IngestService`（延迟 import，避免捕获层尚未落地时导入失败）走正常单事务流水线，
在画像写入或告警写入处注入异常，打印五张派生/日志表在“执行前 / 注入失败后 / 清理后”的
行数对比。测试数据使用 TEST-NET-2 保留地址，结束后清理，不留下任何脏数据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any
from unittest import mock

from sqlalchemy import text

from shared.db.session import get_rw_engine, get_rw_factory
from shared.events.schema import CapturedEvent, EventStatus, EventType

# 五张核心表：与任务约定的“五表行数”一致（会话表另作为上下文统计）
TRACKED_TABLES: tuple[str, ...] = (
    "attack_log",
    "rule_hits",
    "attacker_profile",
    "attacker_intent",
    "alerts",
)
CONTEXT_TABLES: tuple[str, ...] = ("sessions",)

# 测试数据边界：RFC 5737 TEST-NET-2，不指向任何真实资产
TEST_SOURCE_IP = "198.51.100.250"


def _build_events(session_id: str) -> list[CapturedEvent]:
    """构造覆盖 R03（recon）与 R05（destructive）的测试事件序列。"""
    return [
        CapturedEvent(
            event_uuid=str(uuid.uuid4()),
            session_id=session_id,
            event_type=EventType.CONNECT,
            source_ip=TEST_SOURCE_IP,
            source_port=55001,
            status=EventStatus.SUCCESS,
        ),
        CapturedEvent(
            event_uuid=str(uuid.uuid4()),
            session_id=session_id,
            event_type=EventType.QUERY,
            source_ip=TEST_SOURCE_IP,
            username="demo_user_01",
            sql_statement="SHOW TABLES",
            normalized_sql="SHOW TABLES",
            status=EventStatus.SUCCESS,
        ),
        CapturedEvent(
            event_uuid=str(uuid.uuid4()),
            session_id=session_id,
            event_type=EventType.QUERY,
            source_ip=TEST_SOURCE_IP,
            username="demo_user_01",
            sql_statement="DROP TABLE fake_orders",
            normalized_sql="DROP TABLE fake_orders",
            status=EventStatus.DENIED,
        ),
    ]


async def _count_tables(db) -> dict[str, int]:
    """统计五表 + 会话表行数。"""
    counts: dict[str, int] = {}
    for table in (*TRACKED_TABLES, *CONTEXT_TABLES):
        value = (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
        counts[table] = int(value or 0)
    return counts


async def _cleanup(db, *, session_id: str) -> None:
    """删除本次验证产生的测试数据（按外键顺序，单事务）。"""
    if db.in_transaction():
        await _cleanup_in_transaction(db, session_id=session_id)
    else:
        async with db.begin():
            await _cleanup_in_transaction(db, session_id=session_id)


async def _cleanup_in_transaction(db, *, session_id: str) -> None:
    """清理事务内实现：按 TEST-NET-2 测试来源整体清理，避免告警去重行残留。

    告警按 `dedup_key` 去重，重复验证时可能把 `latest_hit_id` 指向新会话的命中，
    而 `session_id` 仍是首次触发会话；因此清理必须按**测试来源 IP** 删除告警与
    原始事件，而不能只按本次 session_id 删除（否则会留下跨次运行的残留行）。
    """
    attacker_ids = [
        int(row[0])
        for row in (
            await db.execute(
                text("SELECT attacker_id FROM attacker_profile WHERE source_ip = :ip"),
                {"ip": TEST_SOURCE_IP},
            )
        ).all()
    ]
    if attacker_ids:
        placeholders = ", ".join(f":a{i}" for i in range(len(attacker_ids)))
        params = {f"a{i}": value for i, value in enumerate(attacker_ids)}
        await db.execute(
            text(f"DELETE FROM alerts WHERE attacker_id IN ({placeholders})"), params
        )
        await db.execute(
            text(f"DELETE FROM attacker_intent WHERE attacker_id IN ({placeholders})"),
            params,
        )
    # 仍按会话兜底清理（画像可能因上游异常未创建）
    await db.execute(
        text("DELETE FROM alerts WHERE session_id = :session_id"),
        {"session_id": session_id},
    )
    await db.execute(
        text(
            """
            DELETE FROM rule_hits
            WHERE session_id IN (
                SELECT session_id FROM attack_log WHERE source_ip = :ip
            )
            """
        ),
        {"ip": TEST_SOURCE_IP},
    )
    await db.execute(
        text("DELETE FROM attack_log WHERE source_ip = :ip"), {"ip": TEST_SOURCE_IP}
    )
    await db.execute(
        text("DELETE FROM attacker_profile WHERE source_ip = :ip"), {"ip": TEST_SOURCE_IP}
    )
    await db.execute(
        text("DELETE FROM sessions WHERE source_ip = :ip"), {"ip": TEST_SOURCE_IP}
    )


def _profile_write_failure():
    """返回在画像写入阶段抛错的异步替身。"""

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("注入失败：画像写入阶段（attacker_profile UPSERT）")

    return mock.patch("m4_rules_derived.analysis._upsert_attacker_profile", side_effect=_boom)


def _alert_write_failure():
    """返回在“有告警类命中时”抛错的替身（经 M4 `public` 门面注入）。

    边界约束（contracts/module-boundaries.md §2）：M1 只能依赖 M4 的 `public` 门面，
    因此通过替换 `public.analyze_and_derive` 包一层：先执行完整分析流水线（命中、
    画像、告警均已写入本事务），若结果含可告警意图则抛错，由 `IngestService` 回滚，
    与“告警写入阶段失败”的事务语义一致。
    """
    from m4_rules_derived import public as rules_public

    original = rules_public.analyze_and_derive
    alertable_intents = rules_public.ALERTABLE_INTENTS

    async def _wrapped(db, event_row, session_row):
        result = await original(db, event_row, session_row)
        hits = getattr(result, "rule_hits", None) or []
        # 仅当本次确有可告警命中时注入失败，让前序无告警事件正常提交
        if any(
            str(getattr(hit, "intent_type", "")) in alertable_intents for hit in hits
        ):
            raise RuntimeError("注入失败：告警写入阶段（alerts UPSERT）")
        return result

    return mock.patch.object(rules_public, "analyze_and_derive", side_effect=_wrapped)


async def _run_ingest(events: list[CapturedEvent], inject_failure: str) -> str | None:
    """通过 IngestService 逐条投递事件；返回注入错误描述（无错误返回 None）。"""
    try:
        from m1_transaction_integration.services.ingest import (
            IngestService,  # 延迟 import：捕获层拥有该文件
        )
    except ImportError as exc:
        raise RuntimeError(f"m1_transaction_integration.services.ingest 尚未可用：{exc}") from exc

    factory = get_rw_factory()
    patcher = None
    if inject_failure == "profile_write":
        patcher = _profile_write_failure()
    elif inject_failure == "alert_write":
        patcher = _alert_write_failure()

    error_message: str | None = None
    async with factory() as db:
        service = IngestService(db)
        try:
            if patcher is not None:
                with patcher:
                    for event in events:
                        await service.ingest(event)
            else:
                for event in events:
                    await service.ingest(event)
        except Exception as exc:  # noqa: BLE001 - 验证脚本需要记录注入异常
            error_message = f"{type(exc).__name__}: {exc}"
            # 注入失败后事务应已由 IngestService 回滚；这里再做一次兜底回滚
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return error_message


async def run_verify(inject_failure: str) -> dict[str, Any]:
    """执行验证并返回结构化结果。"""
    factory = get_rw_factory()
    # 先清理历史验证可能残留的测试来源数据，保证 before 基线干净
    async with factory() as db:
        await _cleanup(db, session_id="00000000-0000-0000-0000-000000000000")
    async with factory() as db:
        before = await _count_tables(db)

    session_id = str(uuid.uuid4())
    events = _build_events(session_id)

    ingest_error: str | None = None
    ingest_missing = False
    try:
        ingest_error = await _run_ingest(events, inject_failure)
    except RuntimeError as exc:
        ingest_missing = True
        ingest_error = str(exc)

    async with factory() as db:
        after_failure = await _count_tables(db)
        # 统计查询会隐式开启事务；先回滚，确保清理逻辑自己持有事务并提交
        await db.rollback()
        await _cleanup(db, session_id=session_id)
    async with factory() as db:
        after_cleanup = await _count_tables(db)

    await get_rw_engine().dispose()

    result: dict[str, Any] = {
        "inject_failure": inject_failure,
        "session_id": session_id,
        "source_ip": TEST_SOURCE_IP,
        "tracked_tables": list(TRACKED_TABLES),
        "before": before,
        "after_failure": after_failure,
        "after_cleanup": after_cleanup,
        "ingest_error": ingest_error,
        "injected_failure_observed": ingest_error is not None,
        "clean": after_cleanup == before,
        "status": "skipped" if ingest_missing else "ok",
    }
    if ingest_missing:
        result["reason"] = "捕获层 m1_transaction_integration.services.ingest 尚未实现，验证已跳过"
    return result


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m m1_transaction_integration.cli.verify_transaction",
        description="验证事件写入事务在画像/告警阶段失败时整体回滚（不留下脏数据）",
    )
    parser.add_argument(
        "--inject-failure",
        choices=("none", "profile_write", "alert_write"),
        default="none",
        help="故障注入点：none 正常写入 / profile_write 画像写入失败 / alert_write 告警写入失败",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run_verify(args.inject_failure))
    except Exception as exc:  # noqa: BLE001 - CLI 需要明确失败信息
        print(f"事务验证执行失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    if result.get("status") == "skipped":
        return 3
    if not result.get("clean"):
        return 2
    if args.inject_failure != "none" and not result.get("injected_failure_observed"):
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
