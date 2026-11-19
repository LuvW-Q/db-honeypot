"""标准事件构造器（捕获层 → 存储层）。

字段与生成规则严格对齐 `contracts/events.md` 第 3 章与 `impl-contract.md` 第 2 章：
- `event_uuid` / `session_id` 均为 UUID v4 小写文本（36 字符）；
- `event_time` 取 UTC 并截断到秒（落库 `DATETIME(6)` 微秒位为 0）；
- 超长载荷按上限截断并置 `payload_truncated=True`；
- 口令永不进入事件，只保留合成标识 `credential_test_id`。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.schemas.events import CapturedEvent, EventStatus, EventType
from app.utils.sql import normalize_sql as _normalize_sql

# 字段长度上限（contracts/events.md 3.2 / 6.1）
MAX_SQL_STATEMENT_LENGTH = 65535
MAX_USERNAME_LENGTH = 128
MAX_CREDENTIAL_TEST_ID_LENGTH = 64
MAX_CLIENT_INFO_LENGTH = 255


def new_event_uuid() -> str:
    """生成事件幂等键：UUID v4 小写文本（36 字符）。"""
    return str(uuid.uuid4())


def new_session_id() -> str:
    """生成会话编号：UUID v4 小写文本（36 字符）。"""
    return str(uuid.uuid4())


def normalize_sql(sql: str | None) -> str | None:
    """事件字段 `normalized_sql` 的归一化（委托 utils.sql，保持单一事实来源）。"""
    return _normalize_sql(sql)


def utc_now_seconds() -> datetime:
    """当前 UTC 时间，截断到秒（events.md 3.3 `event_time` 规则）。"""
    return datetime.now(UTC).replace(microsecond=0)


def build_event(
    *,
    event_type: EventType,
    session_id: str,
    source_ip: str,
    source_port: int | None = None,
    username: str | None = None,
    credential_test_id: str | None = None,
    sql_statement: str | None = None,
    event_time: datetime | None = None,
    returned_rows: int = 0,
    response_ms: int = 0,
    status: EventStatus = EventStatus.SUCCESS,
    payload_truncated: bool = False,
    client_info: str | None = None,
) -> CapturedEvent:
    """构造一条标准事件（不落库）。

    超长字段在此处统一截断，并把截断事实写进 ``payload_truncated``，
    使"输入防线是否生效"可审计（events.md 3.2）。
    """
    truncated = bool(payload_truncated)

    if username is not None and len(username) > MAX_USERNAME_LENGTH:
        username = username[:MAX_USERNAME_LENGTH]
        truncated = True
    if (
        credential_test_id is not None
        and len(credential_test_id) > MAX_CREDENTIAL_TEST_ID_LENGTH
    ):
        credential_test_id = credential_test_id[:MAX_CREDENTIAL_TEST_ID_LENGTH]
        truncated = True
    if sql_statement is not None and len(sql_statement) > MAX_SQL_STATEMENT_LENGTH:
        sql_statement = sql_statement[:MAX_SQL_STATEMENT_LENGTH]
        truncated = True
    if client_info is not None and len(client_info) > MAX_CLIENT_INFO_LENGTH:
        client_info = client_info[:MAX_CLIENT_INFO_LENGTH]
        truncated = True

    # 事件时间：显式传入则归一为 UTC 秒级；否则取当前时间。
    if event_time is None:
        moment = utc_now_seconds()
    else:
        moment = event_time
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        moment = moment.astimezone(UTC).replace(microsecond=0)

    return CapturedEvent(
        event_uuid=new_event_uuid(),
        session_id=session_id,
        event_type=event_type,
        source_ip=(source_ip or "").lower()[:45] or "0.0.0.0",
        source_port=source_port,
        username=username,
        credential_test_id=credential_test_id,
        sql_statement=sql_statement,
        normalized_sql=normalize_sql(sql_statement),
        event_time=moment,
        returned_rows=max(0, int(returned_rows)),
        response_ms=max(0, int(response_ms)),
        status=status,
        payload_truncated=truncated,
        client_info=client_info,
    )
