"""R01–R05 规则判定单元测试（真实测试库 + RuleContext）。

覆盖正例、反例与阈值边界；窗口统计类规则使用真实 ``attack_log`` 数据，
逐事件类规则使用真实事件行。规则参数默认取自迁移种子 ``detection_rules`` v1，
参数边界用 ``RuleStub`` 替换规则配置对象（判定逻辑仍在真实数据库上运行）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from m4_rules_derived.rules import RULES, RuleContext
from sqlalchemy import text

from tests.support import (
    RuleStub,
    get_enabled_rule,
    insert_attack_log,
    insert_session,
    utc_now,
)


async def _context(db, *, rule_code: str, rule_row, session, event):
    """构造规则判定上下文。"""
    return RuleContext(db=db, event_row=event, session_row=session, rule_row=rule_row)


def test_rules_registry_contains_all_codes():
    """五条规则判定函数均已注册。"""
    assert set(RULES) >= {"R01", "R02", "R03", "R04", "R05"}


# ---------------------------------------------------------------------------
# R01 短时高频连接扫描（60 秒内 >= 10 次 connect 且无有效 SQL）
# ---------------------------------------------------------------------------


async def test_r01_positive_ten_connects_within_window(db_session):
    """10 次 connect 落在 60 秒窗口内 → 命中 scanning/10。"""
    source_ip = "198.51.100.11"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=60))
    for offset in range(9, 0, -1):
        await insert_attack_log(
            db_session,
            session=session,
            event_type="connect",
            event_time=base - timedelta(seconds=offset),
            status="success",
        )
    current = await insert_attack_log(
        db_session, session=session, event_type="connect", event_time=base, status="success"
    )
    rule = await get_enabled_rule(db_session, "R01")
    ctx = await _context(db_session, rule_code="R01", rule_row=rule, session=session, event=current)

    candidate = await RULES["R01"](ctx)

    assert candidate is not None
    assert candidate.rule_code == "R01"
    assert candidate.intent_type == "scanning"
    assert candidate.risk_weight == 10
    assert candidate.details["connect_count"] == 10
    assert "扫描" in candidate.evidence_summary


async def test_r01_boundary_nine_connects_not_hit(db_session):
    """9 次 connect（差 1 次）→ 不命中。"""
    source_ip = "198.51.100.12"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=60))
    for offset in range(8, 0, -1):
        await insert_attack_log(
            db_session, session=session, event_type="connect",
            event_time=base - timedelta(seconds=offset),
        )
    current = await insert_attack_log(
        db_session, session=session, event_type="connect", event_time=base
    )
    rule = await get_enabled_rule(db_session, "R01")
    ctx = await _context(db_session, rule_code="R01", rule_row=rule, session=session, event=current)

    assert await RULES["R01"](ctx) is None


async def test_r01_window_start_is_inclusive(db_session):
    """窗口起点（恰好 60 秒前）的事件计入；61 秒前的排除。"""
    source_ip = "198.51.100.13"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=120))
    # 9 条历史：其中 1 条恰好位于窗口起点，其余在窗口内
    await insert_attack_log(
        db_session, session=session, event_type="connect",
        event_time=base - timedelta(seconds=60),
    )
    for offset in range(1, 9):
        await insert_attack_log(
            db_session, session=session, event_type="connect",
            event_time=base - timedelta(seconds=offset),
        )
    current = await insert_attack_log(
        db_session, session=session, event_type="connect", event_time=base
    )
    rule = await get_enabled_rule(db_session, "R01")
    ctx = await _context(db_session, rule_code="R01", rule_row=rule, session=session, event=current)
    candidate = await RULES["R01"](ctx)
    assert candidate is not None
    assert candidate.details["connect_count"] == 10

    # 把最早一条推到 61 秒前 → 窗口内只剩 9 条，不命中
    await db_session.execute(
        text(
            "UPDATE attack_log SET event_time = :t WHERE event_id = "
            "(SELECT event_id FROM (SELECT MIN(event_id) AS event_id FROM attack_log "
            " WHERE source_ip = :ip) AS x)"
        ),
        {"t": base - timedelta(seconds=61), "ip": source_ip},
    )
    await db_session.flush()
    assert await RULES["R01"](ctx) is None


async def test_r01_not_hit_when_valid_sql_exists(db_session):
    """窗口内出现有效 SQL（query/success）→ 不判为扫描。"""
    source_ip = "198.51.100.14"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=60))
    for offset in range(9, 0, -1):
        await insert_attack_log(
            db_session, session=session, event_type="connect",
            event_time=base - timedelta(seconds=offset),
        )
    await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base - timedelta(seconds=5),
        sql_statement="SELECT 1", status="success",
    )
    current = await insert_attack_log(
        db_session, session=session, event_type="connect", event_time=base
    )
    rule = await get_enabled_rule(db_session, "R01")
    ctx = await _context(db_session, rule_code="R01", rule_row=rule, session=session, event=current)

    assert await RULES["R01"](ctx) is None


async def test_r01_only_evaluates_connect_events(db_session):
    """非 connect 事件不参与 R01 判定（避免同一批扫描重复刷命中）。"""
    source_ip = "198.51.100.15"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=60))
    for offset in range(10, 0, -1):
        await insert_attack_log(
            db_session, session=session, event_type="connect",
            event_time=base - timedelta(seconds=offset),
        )
    current = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="SELECT 1", status="success",
    )
    rule = await get_enabled_rule(db_session, "R01")
    ctx = await _context(db_session, rule_code="R01", rule_row=rule, session=session, event=current)

    assert await RULES["R01"](ctx) is None


# ---------------------------------------------------------------------------
# R02 短时多凭据认证爆破（300 秒内 >= 8 次 auth 且 >= 5 组不同凭据）
# ---------------------------------------------------------------------------


async def _insert_auth_attempts(
    db, session, *, base, count: int, usernames: list[str] | None = None,
    status: str = "failure", start_offset: int = 0,
):
    """辅助：插入若干认证事件（同一来源、窗口内）。"""
    usernames = usernames or [f"user{i:02d}" for i in range(count)]
    for index in range(count):
        await insert_attack_log(
            db,
            session=session,
            event_type="auth",
            event_time=base - timedelta(seconds=start_offset + (count - index)),
            username=usernames[index % len(usernames)],
            credential_test_id=f"TEST-ONLY-{index:03d}",
            status=status,
        )


async def test_r02_positive_eight_attempts_five_pairs(db_session):
    """8 次认证 + 5 组不同凭据 → 命中 bruteforce/25。"""
    source_ip = "198.51.100.21"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    await _insert_auth_attempts(db_session, session, base=base, count=7)
    current = await insert_attack_log(
        db_session, session=session, event_type="auth", event_time=base,
        username="user97", credential_test_id="TEST-ONLY-097", status="failure",
    )
    rule = await get_enabled_rule(db_session, "R02")
    ctx = await _context(db_session, rule_code="R02", rule_row=rule, session=session, event=current)

    candidate = await RULES["R02"](ctx)

    assert candidate is not None
    assert candidate.intent_type == "bruteforce"
    assert candidate.risk_weight == 25
    assert candidate.details["auth_attempts"] == 8
    assert candidate.details["distinct_credential_pairs"] == 8


async def test_r02_boundary_seven_attempts_not_hit(db_session):
    """7 次认证（差 1 次）→ 不命中。"""
    source_ip = "198.51.100.22"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    await _insert_auth_attempts(db_session, session, base=base, count=6)
    current = await insert_attack_log(
        db_session, session=session, event_type="auth", event_time=base,
        username="user96", credential_test_id="TEST-ONLY-096", status="failure",
    )
    rule = await get_enabled_rule(db_session, "R02")
    ctx = await _context(db_session, rule_code="R02", rule_row=rule, session=session, event=current)

    assert await RULES["R02"](ctx) is None


async def test_r02_boundary_four_distinct_pairs_not_hit(db_session):
    """尝试次数达标但仅 4 组不同凭据 → 不命中。"""
    source_ip = "198.51.100.23"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    # 仅 4 组凭据组合：每个用户名固定绑定同一个 credential_test_id
    for index in range(7):
        username = f"user0{index % 4 + 1}"
        await insert_attack_log(
            db_session, session=session, event_type="auth",
            event_time=base - timedelta(seconds=7 - index),
            username=username, credential_test_id=f"TEST-ONLY-{username}",
            status="failure",
        )
    current = await insert_attack_log(
        db_session, session=session, event_type="auth", event_time=base,
        username="user01", credential_test_id="TEST-ONLY-user01", status="failure",
    )
    rule = await get_enabled_rule(db_session, "R02")
    ctx = await _context(db_session, rule_code="R02", rule_row=rule, session=session, event=current)

    assert await RULES["R02"](ctx) is None


async def test_r02_count_failed_only_parameter(db_session):
    """``count_failed_only=true`` 时仅统计失败认证；成功认证不计数。"""
    source_ip = "198.51.100.24"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    # 5 次成功 + 3 次失败 → 失败口径只有 3 次，不命中
    for index in range(8):
        await insert_attack_log(
            db_session, session=session, event_type="auth",
            event_time=base - timedelta(seconds=10 - index),
            username=f"credo{index}", credential_test_id=f"TEST-ONLY-C{index:02d}",
            status="failure" if index >= 5 else "success",
        )
    current = await insert_attack_log(
        db_session, session=session, event_type="auth", event_time=base,
        username="credo7", credential_test_id="TEST-ONLY-C07", status="failure",
    )
    stub = RuleStub(
        "R02",
        {
            "scope": "source_ip",
            "window_seconds": 300,
            "min_auth_attempts": 8,
            "min_distinct_credential_pairs": 5,
            "count_failed_only": True,
        },
    )
    ctx = await _context(db_session, rule_code="R02", rule_row=stub, session=session, event=current)

    assert await RULES["R02"](ctx) is None


async def test_r02_only_evaluates_auth_events(db_session):
    """非 auth 事件不参与 R02 判定。"""
    source_ip = "198.51.100.25"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    await _insert_auth_attempts(db_session, session, base=base, count=8)
    current = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="SELECT 1",
    )
    rule = await get_enabled_rule(db_session, "R02")
    ctx = await _context(db_session, rule_code="R02", rule_row=rule, session=session, event=current)

    assert await RULES["R02"](ctx) is None


# ---------------------------------------------------------------------------
# R03 元数据与结构探测（逐事件关键词）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "keyword"),
    [
        ("SHOW TABLES", "SHOW TABLES"),
        ("show databases;", "SHOW"),
        ("DESCRIBE honeypot_shop.users", "DESCRIBE"),
        ("SELECT * FROM information_schema.tables", "INFORMATION_SCHEMA"),
    ],
)
async def test_r03_positive_keywords(db_session, sql, keyword):
    """命中元数据探测关键词 → recon/15。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.31", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement=sql, status="success",
    )
    rule = await get_enabled_rule(db_session, "R03")
    ctx = await _context(db_session, rule_code="R03", rule_row=rule, session=session, event=event)

    candidate = await RULES["R03"](ctx)

    assert candidate is not None
    assert candidate.rule_code == "R03"
    assert candidate.intent_type == "recon"
    assert candidate.risk_weight == 15
    assert keyword.upper() in candidate.evidence_summary.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, username FROM users WHERE id = 1",
        "SELECT 'SHOW TABLES' AS note",
        "SELECT * FROM orders ORDER BY order_id DESC",
        "UPDATE_TIME > 100",
    ],
)
async def test_r03_negative_statements(db_session, sql):
    """普通 SELECT / 字符串字面量中的关键词 / ORDER BY DESC → 不命中。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.32", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement=sql, status="success",
    )
    rule = await get_enabled_rule(db_session, "R03")
    ctx = await _context(db_session, rule_code="R03", rule_row=rule, session=session, event=event)

    assert await RULES["R03"](ctx) is None


async def test_r03_only_evaluates_query_events(db_session):
    """非 query 事件（如 connect）即使携带 SQL 也不参与 R03。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.33", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="connect", event_time=base,
        sql_statement="SHOW TABLES", status="success",
    )
    rule = await get_enabled_rule(db_session, "R03")
    ctx = await _context(db_session, rule_code="R03", rule_row=rule, session=session, event=event)

    assert await RULES["R03"](ctx) is None


# ---------------------------------------------------------------------------
# R04 会话级批量数据读取（连续 SELECT >= 5 或累计返回行数 >= 1000）
# ---------------------------------------------------------------------------


async def _insert_selects(db, session, *, base, count: int):
    """辅助：在同一会话窗口内插入连续 SELECT 查询。"""
    last = None
    for index in range(count):
        last = await insert_attack_log(
            db,
            session=session,
            event_type="query",
            event_time=base - timedelta(seconds=count - index),
            sql_statement=f"SELECT * FROM users WHERE id = {index + 1}",
            returned_rows=1,
            status="success",
        )
    return last


async def test_r04_positive_five_consecutive_selects(db_session):
    """连续 5 次 SELECT → 命中 data_dump/25。"""
    source_ip = "198.51.100.41"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    current = await _insert_selects(db_session, session, base=base, count=5)
    rule = await get_enabled_rule(db_session, "R04")
    ctx = await _context(db_session, rule_code="R04", rule_row=rule, session=session, event=current)

    candidate = await RULES["R04"](ctx)

    assert candidate is not None
    assert candidate.intent_type == "data_dump"
    assert candidate.risk_weight == 25
    assert candidate.details["hit_by_select"] is True
    assert candidate.details["consecutive_select"] == 5


async def test_r04_boundary_four_selects_not_hit(db_session):
    """连续 4 次 SELECT（差 1 次）→ 不命中。"""
    source_ip = "198.51.100.42"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    current = await _insert_selects(db_session, session, base=base, count=4)
    rule = await get_enabled_rule(db_session, "R04")
    ctx = await _context(db_session, rule_code="R04", rule_row=rule, session=session, event=current)

    assert await RULES["R04"](ctx) is None


async def test_r04_positive_returned_rows_threshold(db_session):
    """单会话累计返回 1001 行 → 命中（行数条件，严格大于 1000）。"""
    source_ip = "198.51.100.43"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    current = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="SELECT * FROM fake_orders", returned_rows=1001, status="success",
    )
    rule = await get_enabled_rule(db_session, "R04")
    ctx = await _context(db_session, rule_code="R04", rule_row=rule, session=session, event=current)

    candidate = await RULES["R04"](ctx)

    assert candidate is not None
    assert candidate.details["hit_by_rows"] is True
    assert candidate.details["total_returned_rows"] == 1001


async def test_r04_boundary_rows_999_not_hit(db_session):
    """累计返回 999 行（差 1 行）→ 不命中。"""
    source_ip = "198.51.100.44"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    current = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="SELECT * FROM fake_orders", returned_rows=999, status="success",
    )
    rule = await get_enabled_rule(db_session, "R04")
    ctx = await _context(db_session, rule_code="R04", rule_row=rule, session=session, event=current)

    assert await RULES["R04"](ctx) is None


async def test_r04_non_select_not_hit_even_with_many_rows(db_session):
    """非 SELECT 查询即使返回行数很大也不判定为拖库。"""
    source_ip = "198.51.100.45"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    current = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="SHOW TABLES", returned_rows=2000, status="success",
    )
    rule = await get_enabled_rule(db_session, "R04")
    ctx = await _context(db_session, rule_code="R04", rule_row=rule, session=session, event=current)

    assert await RULES["R04"](ctx) is None


async def test_r04_select_chain_broken_by_non_select(db_session):
    """连续 SELECT 被中间的非 SELECT 查询打断 → 不命中。"""
    source_ip = "198.51.100.46"
    base = utc_now()
    session = await insert_session(db_session, source_ip=source_ip, started_at=base - timedelta(seconds=300))
    for index in range(2):
        await insert_attack_log(
            db_session, session=session, event_type="query",
            event_time=base - timedelta(seconds=10 + index),
            sql_statement=f"SELECT * FROM users WHERE id = {index}", returned_rows=1,
        )
    await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base - timedelta(seconds=8),
        sql_statement="SHOW TABLES", returned_rows=1,
    )
    current = await _insert_selects(db_session, session, base=base, count=3)
    rule = await get_enabled_rule(db_session, "R04")
    ctx = await _context(db_session, rule_code="R04", rule_row=rule, session=session, event=current)

    assert await RULES["R04"](ctx) is None


# ---------------------------------------------------------------------------
# R05 破坏性写操作尝试（首关键词 + 状态口径）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "status"),
    [
        ("DROP TABLE users", "denied"),
        ("TRUNCATE TABLE fake_orders", "denied"),
        ("DELETE FROM users WHERE id = 1", "success"),
        ("UPDATE users SET role = 'admin'", "error"),
        ("INSERT INTO users (id) VALUES (1)", "success"),
    ],
)
async def test_r05_positive_write_attempts(db_session, sql, status):
    """首关键词为写操作且状态在口径内 → destructive/35。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.51", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement=sql, status=status,
    )
    rule = await get_enabled_rule(db_session, "R05")
    ctx = await _context(db_session, rule_code="R05", rule_row=rule, session=session, event=event)

    candidate = await RULES["R05"](ctx)

    assert candidate is not None
    assert candidate.rule_code == "R05"
    assert candidate.intent_type == "destructive"
    assert candidate.risk_weight == 35
    assert "破坏性" in candidate.evidence_summary


@pytest.mark.parametrize(
    ("sql", "status"),
    [
        ("SELECT * FROM users", "success"),
        ("SHOW TABLES", "success"),
        ("UPDATE_TIME > 100", "success"),
        ("SELECT * FROM t WHERE note = 'DROP TABLE x'", "success"),
    ],
)
async def test_r05_negative_statements(db_session, sql, status):
    """普通查询 / 字符串字面量中的写关键词 → 不命中。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.52", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement=sql, status=status,
    )
    rule = await get_enabled_rule(db_session, "R05")
    ctx = await _context(db_session, rule_code="R05", rule_row=rule, session=session, event=event)

    assert await RULES["R05"](ctx) is None


async def test_r05_failure_status_not_counted(db_session):
    """种子参数 count_status 不含 failure → 认证失败类状态不命中。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.53", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="DROP TABLE users", status="failure",
    )
    rule = await get_enabled_rule(db_session, "R05")
    ctx = await _context(db_session, rule_code="R05", rule_row=rule, session=session, event=event)

    assert await RULES["R05"](ctx) is None


async def test_r05_word_boundary_avoids_false_positive(db_session):
    """``status=denied`` 时按词边界匹配，``UPDATE_TIME`` 等标识符不误报。"""
    base = utc_now()
    session = await insert_session(db_session, source_ip="198.51.100.54", started_at=base)
    event = await insert_attack_log(
        db_session, session=session, event_type="query", event_time=base,
        sql_statement="SELECT UPDATE_TIME FROM some_table", status="denied",
    )
    rule = await get_enabled_rule(db_session, "R05")
    ctx = await _context(db_session, rule_code="R05", rule_row=rule, session=session, event=event)

    assert await RULES["R05"](ctx) is None
