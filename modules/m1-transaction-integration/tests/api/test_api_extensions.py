"""002 契约增量接口测试（`contracts/api-extensions.md` §2–§7）。

覆盖范围：

- `/api/overview?range=`：回显、窗口起始语义、非法枚举、分母 0 规则、今日/昨日口径；
- `/api/trend`：五个意图族命中数（`hit_*`）与 `rule_hits` 对齐补 0；
- `/api/alerts/summary`：空库 0 值、`total = unread + read`、键齐全、`from`/`to` 成对与窗口；
- `/api/attackers/summary`：总数、高风险数、最近意图结构；
- `/api/attackers?q=&sort=`：子串匹配、`LIKE` 通配符转义、长度/控制字符校验、连接数排序；
- `/api/attackers/{ip}`：`avg_session_seconds`/`auth_success_count`/`high_risk_op_count` 与
  `network_scope(_label)` 派生；
- `network_scope` 纯函数：回环/内网/文档保留/公网四类的边界用例。

数据断言尽量用相对关系（≥、等式来源、窗口比较），不硬编码种子数字。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from shared.events.schema import EventStatus, EventType

_UTC_SECONDS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

#: 契约 §1.2：今日/昨日固定 UTC+8（Asia/Shanghai）自然日
CN_TZ = timezone(timedelta(hours=8))

SEVERITY_KEYS = {"low", "medium", "high", "critical"}
ALERT_TYPE_KEYS = {"bruteforce", "data_dump", "destructive"}


def _utc(value: str) -> datetime:
    """把响应中的 `...Z` 时刻解析为带时区 UTC datetime。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cn_windows(now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    """返回 `(今日开始, 昨日开始, 明日开始)`，均为 UTC 时刻。"""
    moment = (now or datetime.now(UTC)).astimezone(CN_TZ)
    today_start_local = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start_local = today_start_local - timedelta(days=1)
    tomorrow_start_local = today_start_local + timedelta(days=1)
    return (
        today_start_local.astimezone(UTC),
        yesterday_start_local.astimezone(UTC),
        tomorrow_start_local.astimezone(UTC),
    )


async def _seed_attacker(
    ingest_event,
    event_factory,
    source_ip: str,
    *,
    sql_statement: str = "SHOW TABLES",
    status: EventStatus = EventStatus.SUCCESS,
    event_time: datetime | None = None,
    session_id: str | None = None,
):
    """写入一条查询事件，创建/更新一个攻击者画像（recon 命中，风险低）。"""
    return await ingest_event(
        event_factory(
            event_type=EventType.QUERY,
            source_ip=source_ip,
            sql_statement=sql_statement,
            status=status,
            event_time=event_time,
            session_id=session_id,
        )
    )


# ---------------------------------------------------------------------------
# GET /api/overview?range=
# ---------------------------------------------------------------------------


async def test_overview_range_echo_and_window_start(client):
    """range 回显；all 的 window_start 为 null；24h/7d 的窗口起点约为 now-窗口。"""
    all_body = (await client.get("/api/overview", params={"range": "all"})).json()
    assert all_body["range"] == "all"
    assert all_body["window_start"] is None

    for key, delta in (("24h", timedelta(hours=24)), ("7d", timedelta(days=7))):
        body = (await client.get("/api/overview", params={"range": key})).json()
        assert body["range"] == key
        assert body["window_start"] is not None
        assert _UTC_SECONDS_RE.match(body["window_start"])
        start = _utc(body["window_start"])
        expected = datetime.now(UTC) - delta
        assert abs((expected - start).total_seconds()) < 300  # 允许请求耗时误差

    # 默认（不带参数）等价 all，保证 001 客户端向后兼容
    default_body = (await client.get("/api/overview")).json()
    assert default_body["range"] == "all"
    assert default_body["window_start"] is None


async def test_overview_today_and_yesterday_windows(client):
    """today_window/yesterday_window 为 UTC+8 自然日对应的 UTC 半开区间。"""
    body = (await client.get("/api/overview")).json()

    for field in ("today_window", "yesterday_window"):
        window = body[field]
        assert set(window) == {"start", "end"}
        assert _UTC_SECONDS_RE.match(window["start"])
        assert _UTC_SECONDS_RE.match(window["end"])
        assert _utc(window["end"]) > _utc(window["start"])

    today_start, yesterday_start, tomorrow_start = _cn_windows()
    assert abs((_utc(body["today_window"]["start"]) - today_start).total_seconds()) < 5
    assert abs((_utc(body["today_window"]["end"]) - tomorrow_start).total_seconds()) < 5
    assert abs((_utc(body["yesterday_window"]["start"]) - yesterday_start).total_seconds()) < 5
    # 昨日区间右边界即今日左边界（半开区间首尾相接）
    assert _utc(body["yesterday_window"]["end"]) == _utc(body["today_window"]["start"])


async def test_overview_invalid_range_returns_422(client):
    """range 不在白名单 → 422 VALIDATION_ERROR，detail 为字段级数组。"""
    response = await client.get("/api/overview", params={"range": "30d"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["field"] == "range"
    assert body["detail"][0]["input"] == "30d"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_overview_generator_zero_denominators(client):
    """空库：分母 0 的派生指标按契约取 0.0/None，而非除零错误。"""
    body = (await client.get("/api/overview")).json()

    assert body["high_risk_ratio"] == 0.0
    assert body["query_blocked_rate"] is None
    assert body["sessions_delta_pct"] is None
    assert body["queries_delta_pct"] is None
    assert body["attackers_total"] == 0
    assert body["alerts_unread"] == 0
    assert body["alerts_by_severity"] == dict.fromkeys(SEVERITY_KEYS, 0)
    assert body["sessions_today"] == 0
    assert body["queries_today"] == 0


async def test_overview_window_excludes_old_events(client, event_factory, ingest_event):
    """窗口语义：10 天前的事件只在 range=all 计入，7d/24h 不计入。"""
    old_time = datetime.now(UTC).replace(microsecond=0) - timedelta(days=10)
    await _seed_attacker(
        ingest_event,
        event_factory,
        "203.0.113.90",
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
        event_time=old_time,
    )

    all_body = (await client.get("/api/overview", params={"range": "all"})).json()
    assert all_body["sessions"] >= 1
    assert all_body["queries"] >= 1
    assert all_body["attackers_total"] >= 1

    for key in ("7d", "24h"):
        body = (await client.get("/api/overview", params={"range": key})).json()
        assert body["sessions"] == 0
        assert body["queries"] == 0
        assert body["attackers_total"] == 0
        assert body["high_risk_ratio"] == 0.0
        assert body["sessions_today"] == 0


async def test_overview_today_delta_pct(client, event_factory, ingest_event):
    """今日/昨日会话数变化百分比：昨日 2 今日 1 → -50.0；昨日查询 0 → null。"""
    today_start, yesterday_start, _ = _cn_windows()
    yesterday_noon = yesterday_start + timedelta(hours=12)

    for _ in range(2):
        await ingest_event(
            event_factory(
                event_type=EventType.CONNECT,
                source_ip="198.51.100.200",
                event_time=yesterday_noon,
            )
        )
    await ingest_event(
        event_factory(
            event_type=EventType.CONNECT,
            source_ip="198.51.100.201",
            event_time=today_start + timedelta(seconds=5),
        )
    )

    body = (await client.get("/api/overview")).json()
    assert body["sessions_today"] == 1
    assert body["sessions_delta_pct"] == -50.0
    assert body["queries_today"] == 0
    assert body["queries_delta_pct"] is None


# ---------------------------------------------------------------------------
# GET /api/trend（五个意图族命中数）
# ---------------------------------------------------------------------------


async def test_trend_points_have_hit_fields(client, db_session, event_factory, ingest_event):
    """每个趋势点都带五个 int `hit_*`；求和等于 `rule_hits` 实际行数。"""
    await _seed_attacker(
        ingest_event,
        event_factory,
        "203.0.113.91",
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
    )
    await _seed_attacker(ingest_event, event_factory, "203.0.113.92", sql_statement="SHOW TABLES")

    response = await client.get("/api/trend", params={"days": 3})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3

    hit_fields = (
        "hit_bruteforce",
        "hit_data_dump",
        "hit_scanning",
        "hit_recon",
        "hit_destructive",
    )
    for point in body["items"]:
        for field in hit_fields:
            assert field in point
            assert isinstance(point[field], int)
            assert point[field] >= 0

    total_hits = int(
        (await db_session.execute(text("SELECT COUNT(*) FROM rule_hits"))).scalar_one()
    )
    assert sum(point[field] for point in body["items"] for field in hit_fields) == total_hits
    assert total_hits >= 1
    assert sum(point["hit_destructive"] for point in body["items"]) >= 1
    assert sum(point["hit_recon"] for point in body["items"]) >= 1


async def test_trend_hits_align_with_stat_date(client, event_factory, ingest_event):
    """命中按 `rule_hits.triggered_at`（= 事件时间）的 UTC 统计日落入对应趋势点。"""
    yesterday = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1, hours=1)
    await _seed_attacker(
        ingest_event,
        event_factory,
        "203.0.113.93",
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
        event_time=yesterday,
    )

    body = (await client.get("/api/trend", params={"days": 2})).json()
    yesterday_point, today_point = body["items"]
    assert yesterday_point["stat_date"] == yesterday.date().isoformat()
    assert yesterday_point["hit_destructive"] >= 1
    assert today_point["hit_destructive"] == 0


# ---------------------------------------------------------------------------
# GET /api/alerts/summary
# ---------------------------------------------------------------------------


async def _create_destructive_alert(
    db_session, event_factory, ingest_event, source_ip: str = "198.51.100.210"
) -> int:
    """写入 R05 事件并返回生成的 alert_id。"""
    await _seed_attacker(
        ingest_event,
        event_factory,
        source_ip,
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
    )
    alert_id = (await db_session.execute(text("SELECT alert_id FROM alerts"))).scalar_one()
    return int(alert_id)


async def test_alert_summary_empty_database(client):
    """空库：全 0、resolution_rate = 0.0、peak_window = null。"""
    response = await client.get("/api/alerts/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 0
    assert body["unread"] == 0
    assert body["read"] == 0
    assert body["resolution_rate"] == 0.0
    assert body["by_severity"] == dict.fromkeys(SEVERITY_KEYS, 0)
    assert body["unread_by_severity"] == dict.fromkeys(SEVERITY_KEYS, 0)
    assert body["by_alert_type"] == dict.fromkeys(ALERT_TYPE_KEYS, 0)
    assert body["today_new"] == 0
    assert body["yesterday_new"] == 0
    assert body["today_delta_pct"] is None
    assert body["peak_window"] is None
    assert _UTC_SECONDS_RE.match(body["generated_at"])
    assert body["today_window"]["start"].endswith("Z")


async def test_alert_summary_counts_and_resolution(
    client, db_session, event_factory, ingest_event
):
    """有数据：total = unread + read；键齐全；已读后 resolution_rate 上升。"""
    alert_id = await _create_destructive_alert(db_session, event_factory, ingest_event)

    body = (await client.get("/api/alerts/summary")).json()
    assert body["total"] == 1
    assert body["unread"] == 1
    assert body["read"] == 0
    assert body["total"] == body["unread"] + body["read"]
    assert body["resolution_rate"] == 0.0
    assert set(body["by_severity"]) == SEVERITY_KEYS
    assert body["by_severity"]["critical"] >= 1
    assert set(body["unread_by_severity"]) == SEVERITY_KEYS
    assert body["unread_by_severity"]["critical"] >= 1
    assert set(body["by_alert_type"]) == ALERT_TYPE_KEYS
    assert body["by_alert_type"]["destructive"] >= 1
    assert body["today_new"] >= 1
    assert body["yesterday_new"] == 0
    assert body["today_delta_pct"] is None  # 昨日 0 → null
    peak = body["peak_window"]
    assert peak is not None
    assert set(peak) == {"start", "end", "count"}
    assert peak["count"] >= 1
    assert _utc(peak["end"]) - _utc(peak["start"]) == timedelta(hours=1)

    await client.patch(f"/api/alerts/{alert_id}", json={"is_read": True})
    read_body = (await client.get("/api/alerts/summary")).json()
    assert read_body["total"] == 1
    assert read_body["unread"] == 0
    assert read_body["read"] == 1
    assert read_body["resolution_rate"] == 1.0


async def test_alert_summary_from_to_validation(client):
    """from/to 必须成对、from < to、窗口 ≤ 366 天，否则 422。"""
    unpaired_from = await client.get("/api/alerts/summary", params={"from": "2026-11-20"})
    assert unpaired_from.status_code == 422
    assert unpaired_from.json()["code"] == "VALIDATION_ERROR"

    unpaired_to = await client.get("/api/alerts/summary", params={"to": "2026-11-20"})
    assert unpaired_to.status_code == 422
    assert unpaired_to.json()["code"] == "VALIDATION_ERROR"

    reversed_range = await client.get(
        "/api/alerts/summary", params={"from": "2026-11-20", "to": "2026-11-19"}
    )
    assert reversed_range.status_code == 422
    reversed_body = reversed_range.json()
    assert reversed_body["code"] == "VALIDATION_ERROR"
    assert isinstance(reversed_body["detail"], list)
    assert reversed_body["detail"][0]["field"] == "to"

    malformed_range = await client.get(
        "/api/alerts/summary", params={"from": "not-a-time", "to": "2026-11-19"}
    )
    assert malformed_range.status_code == 422
    malformed_body = malformed_range.json()
    assert malformed_body["code"] == "VALIDATION_ERROR"
    assert isinstance(malformed_body["detail"], list)

    too_wide = await client.get(
        "/api/alerts/summary", params={"from": "2024-01-01", "to": "2026-11-25"}
    )
    assert too_wide.status_code == 422
    assert too_wide.json()["code"] == "VALIDATION_ERROR"

    valid = await client.get(
        "/api/alerts/summary", params={"from": "2026-01-01", "to": "2026-11-25"}
    )
    assert valid.status_code == 200


async def test_alert_summary_window_filter(client, db_session, event_factory, ingest_event):
    """from/to 过滤窗口只影响窗口内统计；窗口外 total = 0。"""
    await _create_destructive_alert(db_session, event_factory, ingest_event)
    now = datetime.now(UTC)
    window_from = (now - timedelta(days=10)).date().isoformat()
    window_to = (now - timedelta(days=9)).date().isoformat()

    body = (
        await client.get(
            "/api/alerts/summary", params={"from": window_from, "to": window_to}
        )
    ).json()
    assert body["total"] == 0
    assert body["unread"] == 0
    assert body["resolution_rate"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/attackers/summary
# ---------------------------------------------------------------------------


async def test_attacker_summary_empty_database(client):
    """空库：total/high_risk_count 为 0，latest_intent 为 null。"""
    response = await client.get("/api/attackers/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 0
    assert body["high_risk_count"] == 0
    assert body["latest_intent"] is None
    assert _UTC_SECONDS_RE.match(body["generated_at"])


async def test_attacker_summary_with_data(client, event_factory, ingest_event):
    """有画像：total 为画像行数、latest_intent 结构完整（不被 /{ip} 路由吞掉）。"""
    # 高风险来源：R05(35) + R03(15) + R02(25) = 75 → high
    source_ip = "203.0.113.94"
    await _seed_attacker(
        ingest_event,
        event_factory,
        source_ip,
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
    )
    await _seed_attacker(ingest_event, event_factory, source_ip, sql_statement="SHOW TABLES")
    session_id = "cccccccc-1111-4111-8111-000000000102"
    for index in range(8):
        await ingest_event(
            event_factory(
                event_type=EventType.AUTH,
                session_id=session_id,
                source_ip=source_ip,
                username=f"api_user_{index}",
                credential_test_id=f"TEST-ONLY-002-{index:02d}",
                status=EventStatus.FAILURE,
            )
        )
    await _seed_attacker(ingest_event, event_factory, "203.0.113.95")

    body = (await client.get("/api/attackers/summary")).json()
    assert body["total"] == 2
    assert body["high_risk_count"] >= 1
    latest = body["latest_intent"]
    assert latest is not None
    assert set(latest) == {
        "intent_type",
        "rule_code",
        "rule_name",
        "source_ip",
        "last_detected_at",
    }
    assert latest["intent_type"] in {"scanning", "bruteforce", "recon", "data_dump", "destructive"}
    assert latest["rule_code"].startswith("R")
    assert latest["rule_name"]
    assert latest["source_ip"] in {source_ip, "203.0.113.95"}
    assert _UTC_SECONDS_RE.match(latest["last_detected_at"])


# ---------------------------------------------------------------------------
# GET /api/attackers?q=&sort=total_connections
# ---------------------------------------------------------------------------


async def test_attackers_q_substring_filter(client, event_factory, ingest_event):
    """q 按 source_ip 子串匹配；空白串视为未提供。"""
    for ip in ("198.51.100.101", "198.51.100.102", "203.0.113.103"):
        await _seed_attacker(ingest_event, event_factory, ip)

    body = (await client.get("/api/attackers", params={"q": "198.51.100"})).json()
    assert body["total"] == 2
    assert all("198.51.100" in item["source_ip"] for item in body["items"])

    narrow = (await client.get("/api/attackers", params={"q": "198.51.100.101"})).json()
    assert narrow["total"] == 1
    assert narrow["items"][0]["source_ip"] == "198.51.100.101"

    blank = (await client.get("/api/attackers", params={"q": "   "})).json()
    assert blank["total"] == 3


async def test_attackers_q_escapes_like_wildcards(client, event_factory, ingest_event):
    """`%`/`_`/`\\` 被转义：作为字面量匹配，不能变成「匹配全部」。"""
    for ip in ("198.51.100.111", "198.51.100.112"):
        await _seed_attacker(ingest_event, event_factory, ip)

    for wildcard in ("%", "_", "\\"):
        body = (await client.get("/api/attackers", params={"q": wildcard})).json()
        assert body["total"] == 0, f"q={wildcard!r} 不应匹配任何来源地址"
        assert body["items"] == []

    # 含通配符字面量但无匹配来源时仍为 0（转义后按普通字符比较）
    percent = (await client.get("/api/attackers", params={"q": "198.51.100%"})).json()
    assert percent["total"] == 0


async def test_attackers_q_validation(client, event_factory, ingest_event):
    """q 超过 64 字符或含控制字符 → 422；空白串不报错。"""
    await _seed_attacker(ingest_event, event_factory, "198.51.100.121")

    too_long = await client.get("/api/attackers", params={"q": "a" * 65})
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "VALIDATION_ERROR"
    assert too_long.json()["detail"][0]["field"] == "q"

    control = await client.get("/api/attackers", params={"q": "198.51.1\x01"})
    assert control.status_code == 422
    assert control.json()["detail"][0]["field"] == "q"

    # 恰好 64 字符合法
    boundary = await client.get("/api/attackers", params={"q": "b" * 64})
    assert boundary.status_code == 200


async def test_attackers_sort_total_connections(client, event_factory, ingest_event):
    """sort=total_connections 可用且按连接数排序；非法 sort 仍 422。"""
    ip_one = "198.51.100.131"
    ip_three = "198.51.100.132"
    await ingest_event(
        event_factory(event_type=EventType.CONNECT, source_ip=ip_one)
    )
    for _ in range(3):
        await ingest_event(
            event_factory(event_type=EventType.CONNECT, source_ip=ip_three)
        )

    desc = (
        await client.get(
            "/api/attackers",
            params={"sort": "total_connections", "order": "desc"},
        )
    ).json()
    assert desc["total"] == 2
    assert desc["items"][0]["source_ip"] == ip_three
    assert desc["items"][0]["total_connections"] == 3
    assert desc["items"][1]["total_connections"] == 1

    asc = (
        await client.get(
            "/api/attackers",
            params={"sort": "total_connections", "order": "asc"},
        )
    ).json()
    assert asc["items"][0]["source_ip"] == ip_one

    invalid = await client.get("/api/attackers", params={"sort": "drop_table"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "SORT_FIELD_INVALID"


async def test_attackers_list_new_fields(client, event_factory, ingest_event):
    """列表项新增 intent_labels/triggered_rule_codes/network_scope(_label)。"""
    await _seed_attacker(
        ingest_event,
        event_factory,
        "203.0.113.96",
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
    )

    body = (await client.get("/api/attackers")).json()
    item = body["items"][0]
    assert isinstance(item["intent_labels"], list)
    assert item["intent_labels"] == ["destructive"]
    assert isinstance(item["triggered_rule_codes"], list)
    assert "R05" in item["triggered_rule_codes"]
    assert item["network_scope"] == "reserved"
    assert item["network_scope_label"] == "文档保留"


# ---------------------------------------------------------------------------
# GET /api/attackers/{ip}（派生字段）
# ---------------------------------------------------------------------------


async def test_attacker_detail_derived_fields(client, event_factory, ingest_event):
    """详情：平均会话时长（已结束会话）、认证成功数、高风险操作数、网络位置。"""
    source_ip = "198.51.100.141"
    base = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    session_id = "dddddddd-1111-4111-8111-000000000141"
    await ingest_event(
        event_factory(
            event_type=EventType.CONNECT,
            session_id=session_id,
            source_ip=source_ip,
            event_time=base,
        )
    )
    await ingest_event(
        event_factory(
            event_type=EventType.DISCONNECT,
            session_id=session_id,
            source_ip=source_ip,
            event_time=base + timedelta(seconds=120),
        )
    )
    # 高风险操作：一次 data_dump 意图之外再加 destructive
    await _seed_attacker(
        ingest_event,
        event_factory,
        source_ip,
        sql_statement="DROP TABLE users",
        status=EventStatus.DENIED,
    )

    body = (await client.get(f"/api/attackers/{source_ip}")).json()
    attacker = body["attacker"]
    assert attacker["avg_session_seconds"] == 120
    assert attacker["auth_success_count"] == 0
    assert attacker["high_risk_op_count"] >= 1
    assert attacker["network_scope"] == "reserved"
    assert attacker["network_scope_label"] == "文档保留"


async def test_attacker_detail_auth_success_and_private_scope(
    client, event_factory, ingest_event
):
    """auth_success_count = max(0, 认证尝试 - 失败)；内网地址派生 private。"""
    source_ip = "192.168.10.5"
    for index in range(2):
        await ingest_event(
            event_factory(
                event_type=EventType.AUTH,
                source_ip=source_ip,
                username=f"bad_user_{index}",
                status=EventStatus.FAILURE,
            )
        )
    await ingest_event(
        event_factory(
            event_type=EventType.AUTH,
            source_ip=source_ip,
            username="good_user",
            status=EventStatus.SUCCESS,
        )
    )

    body = (await client.get(f"/api/attackers/{source_ip}")).json()
    attacker = body["attacker"]
    assert attacker["total_auth_attempts"] == 3
    assert attacker["total_auth_failures"] == 2
    assert attacker["auth_success_count"] == 1
    assert attacker["network_scope"] == "private"
    assert attacker["network_scope_label"] == "内网"
    assert attacker["avg_session_seconds"] is None  # 无已结束会话


async def test_attacker_detail_loopback_and_public_scope(
    client, event_factory, ingest_event
):
    """127.0.0.1 → loopback；8.8.8.8 → public（详情与纯函数口径一致）。"""
    for ip, expected_scope, expected_label in (
        ("127.0.0.1", "loopback", "回环"),
        ("8.8.8.8", "public", "公网"),
    ):
        await ingest_event(
            event_factory(event_type=EventType.CONNECT, source_ip=ip)
        )
        body = (await client.get(f"/api/attackers/{ip}")).json()
        attacker = body["attacker"]
        assert attacker["network_scope"] == expected_scope
        assert attacker["network_scope_label"] == expected_label


# ---------------------------------------------------------------------------
# network_scope 纯函数
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_ip", "expected"),
    [
        ("127.0.0.1", "loopback"),
        ("127.255.255.254", "loopback"),
        ("::1", "loopback"),
        ("192.168.1.10", "private"),
        ("10.1.2.3", "private"),
        ("172.16.5.5", "private"),
        ("fd00::1", "private"),
        ("203.0.113.42", "reserved"),
        ("192.0.2.1", "reserved"),
        ("198.51.100.7", "reserved"),
        ("2001:db8::1", "reserved"),
        ("8.8.8.8", "public"),
        ("1.1.1.1", "public"),
    ],
)
def test_network_scope_pure_function(source_ip: str, expected: str):
    """四类派生的边界地址（纯函数，不依赖数据库）。"""
    from m1_transaction_integration.services.network_scope import derive_network_scope

    assert derive_network_scope(source_ip) == expected


def test_network_scope_labels():
    """派生值 → 页面展示标签映射固定。"""
    from m1_transaction_integration.services.network_scope import network_scope_label

    assert network_scope_label("private") == "内网"
    assert network_scope_label("loopback") == "回环"
    assert network_scope_label("reserved") == "文档保留"
    assert network_scope_label("public") == "公网"


def test_split_labels_dedupes_and_keeps_order():
    """intent_labels/triggered_rule_codes 拆分：去空、去重、顺序稳定。"""
    from m1_transaction_integration.services.network_scope import split_labels

    assert split_labels("destructive,recon,destructive,,bruteforce") == [
        "destructive",
        "recon",
        "bruteforce",
    ]
    assert split_labels(None) == []
    assert split_labels("") == []
