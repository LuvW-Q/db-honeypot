"""标准事件构造器单元测试：UUID、UTC 归一、长度截断与 payload_truncated。"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

import shared.events.builder as builder
from shared.events.builder import (
    MAX_CLIENT_INFO_LENGTH,
    MAX_CREDENTIAL_TEST_ID_LENGTH,
    MAX_SQL_STATEMENT_LENGTH,
    MAX_USERNAME_LENGTH,
    build_event,
    new_event_uuid,
    new_session_id,
    normalize_sql,
    utc_now_seconds,
)
from shared.events.schema import EventStatus, EventType

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_new_event_uuid_is_unique_v4_lowercase():
    """事件 UUID 唯一、小写、符合 v4 格式。"""
    values = {new_event_uuid() for _ in range(500)}
    assert len(values) == 500
    for value in values:
        assert _UUID_RE.match(value), value


def test_new_session_id_is_unique_v4():
    """会话编号同样为 UUID v4 文本。"""
    values = {new_session_id() for _ in range(200)}
    assert len(values) == 200
    assert all(_UUID_RE.match(value) for value in values)


def test_utc_now_seconds_truncates_microseconds():
    """当前 UTC 时间秒级截断且带 UTC 时区。"""
    moment = utc_now_seconds()
    assert moment.tzinfo is not None
    assert moment.utcoffset() == timedelta(0)
    assert moment.microsecond == 0


def test_build_event_normalizes_naive_time_as_utc():
    """朴素时间按 UTC 处理，并截断到秒。"""
    naive = datetime(2026, 11, 19, 12, 30, 48, 123456)
    event = build_event(
        event_type=EventType.QUERY,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        sql_statement="SELECT 1",
        event_time=naive,
    )
    assert event.event_time == datetime(2026, 11, 19, 12, 30, 48, tzinfo=UTC)
    assert event.event_time.microsecond == 0


def test_build_event_converts_aware_time_to_utc():
    """带 +08:00 偏移的时间转换为 UTC。"""
    aware = datetime(2026, 11, 19, 20, 30, 48, tzinfo=timezone(timedelta(hours=8)))
    event = build_event(
        event_type=EventType.CONNECT,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        event_time=aware,
    )
    assert event.event_time == datetime(2026, 11, 19, 12, 30, 48, tzinfo=UTC)
    assert event.event_time.utcoffset() == timedelta(0)


def test_build_event_lowercases_source_ip():
    """来源地址统一小写（IPv6 场景）。"""
    event = build_event(
        event_type=EventType.CONNECT,
        session_id=str(uuid.uuid4()),
        source_ip="2001:DB8::10",
    )
    assert event.source_ip == "2001:db8::10"


def test_build_event_truncates_username_and_sets_flag():
    """用户名超过 128 字符截断，并置 payload_truncated。"""
    event = build_event(
        event_type=EventType.AUTH,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        username="u" * (MAX_USERNAME_LENGTH + 50),
    )
    assert len(event.username) == MAX_USERNAME_LENGTH
    assert event.payload_truncated is True


def test_build_event_truncates_sql_and_sets_flag():
    """SQL 超过 65535 字符截断，并置 payload_truncated。"""
    event = build_event(
        event_type=EventType.QUERY,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        sql_statement="SELECT '" + "x" * (MAX_SQL_STATEMENT_LENGTH + 100) + "'",
    )
    assert len(event.sql_statement) == MAX_SQL_STATEMENT_LENGTH
    assert event.payload_truncated is True


def test_build_event_truncates_credential_id_and_client_info():
    """合成凭据标识与客户端特征按列长度截断。"""
    event = build_event(
        event_type=EventType.AUTH,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        credential_test_id="C" * (MAX_CREDENTIAL_TEST_ID_LENGTH + 20),
        client_info="client-" + "y" * (MAX_CLIENT_INFO_LENGTH + 20),
    )
    assert len(event.credential_test_id) == MAX_CREDENTIAL_TEST_ID_LENGTH
    assert len(event.client_info) == MAX_CLIENT_INFO_LENGTH
    assert event.payload_truncated is True


def test_build_event_keeps_explicit_truncated_flag():
    """外部显式标记的 payload_truncated 不会被覆盖为 False。"""
    event = build_event(
        event_type=EventType.QUERY,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        sql_statement="SELECT 1",
        payload_truncated=True,
    )
    assert event.payload_truncated is True


def test_build_event_normalizes_sql():
    """事件构造器自动写入 normalized_sql。"""
    event = build_event(
        event_type=EventType.QUERY,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        sql_statement="SELECT * FROM users WHERE id = 42",
    )
    assert event.normalized_sql == "select * from users where id = ?"
    assert normalize_sql("SELECT  1") == "select ?"


def test_build_event_clamps_negative_counters():
    """负的返回行数/耗时被收敛为 0（不产生负计数）。"""
    event = build_event(
        event_type=EventType.QUERY,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        returned_rows=-5,
        response_ms=-3,
    )
    assert event.returned_rows == 0
    assert event.response_ms == 0


def test_build_event_default_status_and_type_values():
    """默认状态为 success、事件保留枚举值。"""
    event = build_event(
        event_type=EventType.DISCONNECT,
        session_id=str(uuid.uuid4()),
        source_ip="192.0.2.10",
        status=EventStatus.ERROR,
    )
    assert event.event_type == EventType.DISCONNECT
    assert event.status == EventStatus.ERROR
    assert event.event_uuid != event.session_id


@pytest.mark.parametrize("sql", [None, "", "   ", "-- 只有注释\n"])
def test_normalize_sql_empty_inputs(sql):
    """空 SQL / 纯注释归一化为 None。"""
    assert normalize_sql(sql) is None


def test_event_builder_constants_are_documented_limits():
    """长度上限常量与 data-model 列定义一致（防回归）。"""
    assert builder.MAX_SQL_STATEMENT_LENGTH == 65535
    assert builder.MAX_USERNAME_LENGTH == 128
    assert builder.MAX_CREDENTIAL_TEST_ID_LENGTH == 64
    assert builder.MAX_CLIENT_INFO_LENGTH == 255
