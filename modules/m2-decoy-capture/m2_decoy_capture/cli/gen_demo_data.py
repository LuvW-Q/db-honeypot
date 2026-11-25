"""批量合成演示数据 CLI：`python -m m2_decoy_capture.cli.gen_demo_data --sessions 2000 --events 20000`。

用途：为 EXPLAIN 对比与规模演示生成确定性的合成会话/事件（data-model 7.3 / 12.3）。
默认走**批量 INSERT + 分批 commit**（性能优先，不触发规则分析、不产生告警），
生成的数据全部为合成流量（来源使用 RFC 5737 TEST-NET-2 地址段），可被
`python -m m1_transaction_integration.cli.reset_demo` 清理。

生成口径：

- 会话：每次运行使用随机命名空间生成 UUID（重复执行是追加语义），
  来源 IP、起止时间与事件计数固定，状态 `closed`；
- 事件：每会话首条 `connect`、末条 `disconnect`，中间交替 `auth` / `query`；
  查询语句覆盖 SELECT / SHOW / UPDATE / DROP，状态以 success 为主并含少量 denied/failure；
- 时间：以 2026-11-01 00:00:00 UTC 为基准，会话间相隔 37 秒，会话内事件相隔 1 秒。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from shared.db.session import get_rw_engine, get_rw_factory

BASE_TIME = datetime(2026, 11, 1, 0, 0, 0)
TARGET_SERVICE = "mysql-honeypot:13306"

# 合成查询语句池（按全局序号循环，保证可重复且覆盖多种语句类型）
QUERY_TEMPLATES: tuple[str, ...] = (
    "SELECT id, order_no, amount FROM fake_orders WHERE user_id = 1 LIMIT 20",
    "SELECT COUNT(*) FROM fake_users",
    "SHOW TABLES",
    "SHOW COLUMNS FROM fake_orders",
    "SELECT email, phone FROM fake_users LIMIT 50",
    "SELECT * FROM fake_config",
    "DESCRIBE fake_users",
    "SELECT user_id, SUM(amount) FROM fake_orders GROUP BY user_id",
    "UPDATE fake_config SET config_value = 'TEST-ONLY' WHERE config_key = 'mail.smtp.password'",
    "DROP TABLE fake_orders",
)

AUTH_USERNAMES: tuple[str, ...] = (
    "demo_user_01",
    "demo_user_02",
    "root",
    "demo_admin",
    "demo_reader",
)


def _utc_naive(value: datetime) -> datetime:
    """统一成 naive UTC（DATETIME(6) 口径）。"""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


async def _insert_sessions(db, sessions: list[dict[str, Any]]) -> int:
    """批量插入会话行（单条 executemany）。"""
    if not sessions:
        return 0
    await db.execute(
        text(
            """
            INSERT INTO sessions (
                session_id, source_ip, source_port, target_service, client_fingerprint,
                started_at, ended_at, session_status, request_count, max_risk_score
            ) VALUES (
                :session_id, :source_ip, :source_port, :target_service, :client_fingerprint,
                :started_at, :ended_at, 'closed', :request_count, 0
            )
            """
        ),
        sessions,
    )
    return len(sessions)


async def _insert_events(db, events: list[dict[str, Any]]) -> int:
    """批量插入事件行（单条 executemany）。"""
    if not events:
        return 0
    await db.execute(
        text(
            """
            INSERT INTO attack_log (
                event_uuid, session_id, event_type, source_ip, username, credential_test_id,
                sql_statement, normalized_sql, event_time, returned_rows, response_ms,
                status, payload_truncated
            ) VALUES (
                :event_uuid, :session_id, :event_type, :source_ip, :username, :credential_test_id,
                :sql_statement, :normalized_sql, :event_time, :returned_rows, :response_ms,
                :status, 0
            )
            """
        ),
        events,
    )
    return len(events)


def _build_session(index: int, run_token: str) -> dict[str, Any]:
    """构造第 index 个合成会话行。

    `run_token` 为每次 CLI 运行的随机命名空间：重复执行本命令是“追加”语义，
    不会因固定 UUID 与既有会话主键冲突（幂等重建请先执行 reset_demo）。
    """
    session_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"dsh-demo-session-{run_token}-{index:06d}")
    )
    started_at = BASE_TIME + timedelta(seconds=index * 37)
    return {
        "session_id": session_id,
        "source_ip": f"203.0.113.{(index % 25) + 1}",
        "source_port": 30000 + (index * 7) % 30000,
        "target_service": TARGET_SERVICE,
        "client_fingerprint": f"mysql-native-8.0-client-{index % 7:02d}",
        "started_at": started_at,
        "ended_at": started_at + timedelta(seconds=40),
        "request_count": 0,  # 事件生成后回填
    }


def _build_events_for_session(
    session: dict[str, Any], *, count: int, global_offset: int, run_token: str
) -> list[dict[str, Any]]:
    """为单个会话构造 count 条事件（首 connect、末 disconnect，中间 auth/query）。"""
    events: list[dict[str, Any]] = []
    started_at: datetime = session["started_at"]
    source_ip = session["source_ip"]
    session_id = session["session_id"]
    if count <= 0:
        return events

    for position in range(count):
        event_time = started_at + timedelta(seconds=position)
        global_index = global_offset + position

        if position == 0:
            event_type = "connect"
            sql_statement = None
            normalized_sql = None
            status = "success"
            username = None
            credential_test_id = None
            returned_rows = 0
        elif position == count - 1 and count > 1:
            event_type = "disconnect"
            sql_statement = None
            normalized_sql = None
            status = "success"
            username = None
            credential_test_id = None
            returned_rows = 0
        elif position % 3 == 1:
            event_type = "auth"
            sql_statement = None
            normalized_sql = None
            username = AUTH_USERNAMES[global_index % len(AUTH_USERNAMES)]
            credential_test_id = f"TEST-ONLY-ACC-{(global_index % 12) + 1:02d}"
            # 约 1/4 认证失败，制造爆破/失败画像计数
            status = "failure" if global_index % 4 == 0 else "success"
            returned_rows = 0
        else:
            event_type = "query"
            template = QUERY_TEMPLATES[global_index % len(QUERY_TEMPLATES)]
            sql_statement = template
            normalized_sql = template.upper()
            username = AUTH_USERNAMES[global_index % len(AUTH_USERNAMES)]
            credential_test_id = None
            if template.startswith(("UPDATE", "DROP")):
                status = "denied"
            elif global_index % 17 == 0:
                status = "error"
            else:
                status = "success"
            returned_rows = (global_index * 37) % 900

        events.append(
            {
                "event_uuid": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"dsh-demo-event-{run_token}-{session_id}-{position:04d}",
                    )
                ),
                "session_id": session_id,
                "event_type": event_type,
                "source_ip": source_ip,
                "username": username,
                "credential_test_id": credential_test_id,
                "sql_statement": sql_statement,
                "normalized_sql": normalized_sql,
                "event_time": _utc_naive(event_time),
                "returned_rows": returned_rows,
                "response_ms": global_index % 50,
                "status": status,
            }
        )
    return events


async def run_generate(*, sessions: int, events: int, batch_size: int = 1000) -> dict[str, int]:
    """批量生成合成会话与事件，返回生成数量。"""
    if sessions <= 0 or events <= 0:
        raise ValueError("--sessions 与 --events 必须为正整数")
    batch_size = max(100, min(batch_size, 5000))

    factory = get_rw_factory()
    created_sessions = 0
    created_events = 0

    # 每条会话的事件数量尽量均分，保证总事件数精确等于 --events
    per_session_base = events // sessions
    remainder = events % sessions

    session_batch: list[dict[str, Any]] = []
    event_batch: list[dict[str, Any]] = []
    global_event_offset = 0
    run_token = uuid.uuid4().hex

    async with factory() as db:
        for index in range(sessions):
            session = _build_session(index, run_token)
            event_count = per_session_base + (1 if index < remainder else 0)
            session["request_count"] = event_count
            session_events = _build_events_for_session(
                session,
                count=event_count,
                global_offset=global_event_offset,
                run_token=run_token,
            )
            global_event_offset += event_count

            session_batch.append(session)
            event_batch.extend(session_events)

            # 会话必须先于事件写入（外键）；同一批里事件可能属尚未落库的会话，
            # 因此到达批阈值时必须先无条件写入 session_batch，再写 event_batch。
            if len(event_batch) >= batch_size or len(session_batch) >= batch_size:
                created_sessions += await _insert_sessions(db, session_batch)
                created_events += await _insert_events(db, event_batch)
                session_batch = []
                event_batch = []
                await db.commit()

        # 兜底提交（收尾批次）
        if session_batch:
            created_sessions += await _insert_sessions(db, session_batch)
        if event_batch:
            created_events += await _insert_events(db, event_batch)
        await db.commit()

    await get_rw_engine().dispose()
    return {"sessions": created_sessions, "events": created_events}


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m m2_decoy_capture.cli.gen_demo_data",
        description="批量生成合成会话/事件，用于 EXPLAIN 对比与规模演示（不含规则派生）",
    )
    parser.add_argument("--sessions", type=int, default=2000, help="生成会话数（默认 2000）")
    parser.add_argument("--events", type=int, default=20000, help="生成事件数（默认 20000）")
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="每批插入/提交的行数（默认 1000）"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(
            run_generate(
                sessions=args.sessions,
                events=args.events,
                batch_size=args.batch_size,
            )
        )
    except Exception as exc:  # noqa: BLE001 - CLI 需要明确失败信息
        print(f"合成数据生成失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
