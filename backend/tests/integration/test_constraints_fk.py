"""数据库约束集成测试：CHECK、外键、唯一约束与生成列边界。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.support import insert_attack_log, insert_session, utc_now


async def _insert_profile(db, *, source_ip: str) -> int:
    """插入一条最小画像行并返回 attacker_id。"""
    now = utc_now()
    await db.execute(
        text(
            """
            INSERT INTO attacker_profile (source_ip, first_seen, last_seen)
            VALUES (:source_ip, :now, :now)
            """
        ),
        {"source_ip": source_ip, "now": now},
    )
    return int(
        (await db.execute(text("SELECT LAST_INSERT_ID()"))).scalar_one()
    )


async def _insert_intent(db, *, attacker_id: int, intent_type: str = "recon") -> None:
    """插入一条意图行。"""
    now = utc_now()
    await db.execute(
        text(
            """
            INSERT INTO attacker_intent
                (attacker_id, intent_type, intent_score, evidence_count,
                 first_detected_at, last_detected_at)
            VALUES (:attacker_id, :intent_type, 15, 1, :now, :now)
            """
        ),
        {"attacker_id": attacker_id, "intent_type": intent_type, "now": now},
    )


# ---------------------------------------------------------------------------
# CHECK 约束
# ---------------------------------------------------------------------------


async def test_check_rejects_risk_score_over_100(db_session):
    """attacker_profile.risk_score > 100 被 CHECK 拒绝。"""
    attacker_id = await _insert_profile(db_session, source_ip="198.51.100.201")
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE attacker_profile SET risk_score = 101 WHERE attacker_id = :id"),
            {"id": attacker_id},
        )
    assert "ck_profile_risk_score" in str(excinfo.value) or "3819" in str(excinfo.value)
    await db_session.rollback()


async def test_check_rejects_session_max_risk_score_over_100(db_session):
    """sessions.max_risk_score > 100 被 CHECK 拒绝。"""
    session = await insert_session(db_session, source_ip="198.51.100.202")
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE sessions SET max_risk_score = 101 WHERE session_id = :sid"),
            {"sid": session.session_id},
        )
    assert "ck_sessions_max_risk_score" in str(excinfo.value) or "3819" in str(excinfo.value)
    await db_session.rollback()


async def test_unsigned_column_rejects_negative_counter(db_session):
    """无符号计数列拒绝负值（total_connections = -1）。"""
    attacker_id = await _insert_profile(db_session, source_ip="198.51.100.203")
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "UPDATE attacker_profile SET total_connections = -1 "
                "WHERE attacker_id = :id"
            ),
            {"id": attacker_id},
        )
    await db_session.rollback()


async def test_check_rejects_illegal_session_status(db_session):
    """sessions.session_status 非法枚举值被 CHECK 拒绝。"""
    session = await insert_session(db_session, source_ip="198.51.100.204")
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE sessions SET session_status = 'hacked' WHERE session_id = :sid"),
            {"sid": session.session_id},
        )
    assert "ck_sessions_status" in str(excinfo.value) or "3819" in str(excinfo.value)
    await db_session.rollback()


async def test_check_rejects_illegal_alert_severity(db_session):
    """alerts.severity 非法枚举值被 CHECK 拒绝（构造完整告警依赖链）。"""
    session = await insert_session(db_session, source_ip="198.51.100.205")
    event = await insert_attack_log(
        db_session, session=session, sql_statement="DROP TABLE users", status="denied"
    )
    attacker_id = await _insert_profile(db_session, source_ip="198.51.100.205")
    rule_id = int(
        (
            await db_session.execute(
                text("SELECT rule_id FROM detection_rules WHERE rule_code = 'R05'")
            )
        ).scalar_one()
    )
    now = utc_now()
    await db_session.execute(
        text(
            """
            INSERT INTO rule_hits
                (event_id, session_id, rule_id, rule_code, intent_type, rule_version,
                 risk_weight, evidence_summary, triggered_at)
            VALUES (:event_id, :session_id, :rule_id, 'R05', 'destructive', 1, 35,
                    '测试证据：DROP TABLE', :now)
            """
        ),
        {
            "event_id": event.event_id,
            "session_id": session.session_id,
            "rule_id": rule_id,
            "now": now,
        },
    )
    hit_id = int((await db_session.execute(text("SELECT LAST_INSERT_ID()"))).scalar_one())
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(
                """
                INSERT INTO alerts
                    (dedup_key, session_id, attacker_id, rule_id, rule_code,
                     latest_hit_id, alert_type, severity, title, evidence_summary,
                     first_seen_at, last_seen_at)
                VALUES (:dedup, :session_id, :attacker_id, :rule_id, 'R05',
                        :hit_id, 'destructive', 'fatal', '非法等级', '证据',
                        :now, :now)
                """
            ),
            {
                "dedup": f"R05:198.51.100.205:{now.date().isoformat()}",
                "session_id": session.session_id,
                "attacker_id": attacker_id,
                "rule_id": rule_id,
                "hit_id": hit_id,
                "now": now,
            },
        )
    assert "ck_alert_severity" in str(excinfo.value) or "3819" in str(excinfo.value)
    await db_session.rollback()


async def test_check_rejects_read_at_without_is_read(db_session):
    """alerts.read_at 非空但 is_read=0 被 CHECK 拒绝。"""
    session = await insert_session(db_session, source_ip="198.51.100.206")
    event = await insert_attack_log(
        db_session, session=session, sql_statement="DROP TABLE users", status="denied"
    )
    attacker_id = await _insert_profile(db_session, source_ip="198.51.100.206")
    rule_id = int(
        (
            await db_session.execute(
                text("SELECT rule_id FROM detection_rules WHERE rule_code = 'R05'")
            )
        ).scalar_one()
    )
    now = utc_now()
    await db_session.execute(
        text(
            """
            INSERT INTO rule_hits
                (event_id, session_id, rule_id, rule_code, intent_type, rule_version,
                 risk_weight, evidence_summary, triggered_at)
            VALUES (:event_id, :session_id, :rule_id, 'R05', 'destructive', 1, 35,
                    '测试证据：DROP TABLE', :now)
            """
        ),
        {
            "event_id": event.event_id,
            "session_id": session.session_id,
            "rule_id": rule_id,
            "now": now,
        },
    )
    hit_id = int((await db_session.execute(text("SELECT LAST_INSERT_ID()"))).scalar_one())
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(
                """
                INSERT INTO alerts
                    (dedup_key, session_id, attacker_id, rule_id, rule_code,
                     latest_hit_id, alert_type, severity, title, evidence_summary,
                     first_seen_at, last_seen_at, is_read, read_at)
                VALUES (:dedup, :session_id, :attacker_id, :rule_id, 'R05',
                        :hit_id, 'destructive', 'critical', '未读却带已读时间', '证据',
                        :now, :now, 0, :now)
                """
            ),
            {
                "dedup": f"R05:198.51.100.206:{now.date().isoformat()}",
                "session_id": session.session_id,
                "attacker_id": attacker_id,
                "rule_id": rule_id,
                "hit_id": hit_id,
                "now": now,
            },
        )
    assert "ck_alert_read_at" in str(excinfo.value) or "3819" in str(excinfo.value)
    await db_session.rollback()


# ---------------------------------------------------------------------------
# 外键约束
# ---------------------------------------------------------------------------


async def test_fk_rejects_orphan_attack_log(db_session):
    """attack_log.session_id 引用不存在的会话 → 外键拒绝。"""
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(
                """
                INSERT INTO attack_log
                    (event_uuid, session_id, event_type, source_ip, event_time, status)
                VALUES (:event_uuid, :session_id, 'connect', '198.51.100.210', :now, 'success')
                """
            ),
            {
                "event_uuid": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "now": utc_now(),
            },
        )
    # MySQL 8.4 线上报 1216（通用子行外键错误），旧版本报 1452；均属外键拒绝
    message = str(excinfo.value)
    assert "fk_log_session" in message or "1216" in message or "1452" in message
    await db_session.rollback()


async def test_fk_restrict_prevents_deleting_referenced_session(db_session):
    """删除仍被 attack_log 引用的会话 → RESTRICT 外键拒绝。"""
    session = await insert_session(db_session, source_ip="198.51.100.211")
    await insert_attack_log(db_session, session=session, event_type="connect")
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("DELETE FROM sessions WHERE session_id = :sid"),
            {"sid": session.session_id},
        )
    message = str(excinfo.value)
    assert "fk_log_session" in message or "1217" in message or "1451" in message
    await db_session.rollback()


async def test_fk_rejects_rule_hit_with_mismatched_session(db_session):
    """rule_hits 复合外键要求事件与会话同源：跨会话事件被拒绝。"""
    session_a = await insert_session(db_session, source_ip="198.51.100.212")
    session_b = await insert_session(db_session, source_ip="198.51.100.213")
    event = await insert_attack_log(db_session, session=session_a, event_type="connect")
    rule_id = int(
        (
            await db_session.execute(
                text("SELECT rule_id FROM detection_rules WHERE rule_code = 'R01'")
            )
        ).scalar_one()
    )
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                """
                INSERT INTO rule_hits
                    (event_id, session_id, rule_id, rule_code, intent_type,
                     rule_version, risk_weight, evidence_summary, triggered_at)
                VALUES (:event_id, :session_b, :rule_id, 'R01', 'scanning',
                        1, 10, '跨会话构造', :now)
                """
            ),
            {
                "event_id": event.event_id,
                "session_b": session_b.session_id,
                "rule_id": rule_id,
                "now": utc_now(),
            },
        )
    await db_session.rollback()


# ---------------------------------------------------------------------------
# UNIQUE 约束
# ---------------------------------------------------------------------------


async def test_unique_event_uuid_rejected(db_session):
    """attack_log.event_uuid 重复 → 唯一约束拒绝。"""
    session = await insert_session(db_session, source_ip="198.51.100.220")
    event_uuid = str(uuid.uuid4())
    await insert_attack_log(
        db_session, session=session, event_type="connect", event_uuid=event_uuid
    )
    with pytest.raises(DBAPIError) as excinfo:
        await insert_attack_log(
            db_session, session=session, event_type="connect", event_uuid=event_uuid
        )
    assert "uk_attack_log_event_uuid" in str(excinfo.value) or "1062" in str(
        excinfo.value
    )
    await db_session.rollback()


async def test_unique_attacker_intent_rejected(db_session):
    """同一画像 + 同一意图类型只能有一行。"""
    attacker_id = await _insert_profile(db_session, source_ip="198.51.100.221")
    await _insert_intent(db_session, attacker_id=attacker_id, intent_type="recon")
    with pytest.raises(DBAPIError) as excinfo:
        await _insert_intent(db_session, attacker_id=attacker_id, intent_type="recon")
    assert "uk_attacker_intent_attacker_type" in str(excinfo.value) or "1062" in str(
        excinfo.value
    )
    await db_session.rollback()


async def test_unique_rule_code_version_rejected(db_session):
    """detection_rules(rule_code, rule_version) 复合唯一。"""
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(
                """
                INSERT INTO detection_rules
                    (rule_code, rule_name, rule_type, intent_type, parameters_json,
                     risk_weight, rule_version, enabled, description)
                VALUES ('R01', '重复版本', 'frequency', 'scanning', '{}', 10, 1, 1, '重复')
                """
            )
        )
    assert "uk_detection_rules_code_version" in str(excinfo.value) or "1062" in str(
        excinfo.value
    )
    await db_session.rollback()


async def test_unique_enabled_rule_code_rejected(db_session):
    """同一 rule_code 至多一个启用版本（生成列唯一约束）。"""
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(
                """
                INSERT INTO detection_rules
                    (rule_code, rule_name, rule_type, intent_type, parameters_json,
                     risk_weight, rule_version, enabled, description)
                VALUES ('R01', '重复启用版本', 'frequency', 'scanning', '{}', 10, 99, 1, '重复')
                """
            )
        )
    assert "uk_detection_rules_enabled_code" in str(excinfo.value) or "1062" in str(
        excinfo.value
    )
    await db_session.rollback()
