"""事务回滚集成测试：分析阶段注入异常后五类数据无残留（SC-012）。

边界约束（contracts/module-boundaries.md §2）：M1 只允许依赖 M4 的 `public` 门面，
因此故障注入替换 `m4_rules_derived.public.analyze_and_derive`（`IngestService`
的调用点），不触达 M4 的 `analysis` 内部模块。
"""

from __future__ import annotations

import m4_rules_derived.public as m4_public
import pytest
from sqlalchemy import text

from shared.events.schema import EventType
from tests.support import count_rows


async def test_analysis_failure_rolls_back_whole_ingest(
    db_session, event_factory, ingest_event, monkeypatch
):
    """analyze_event 抛异常 → 会话/日志/命中/告警/画像全部回滚。"""
    event = event_factory(
        event_type=EventType.QUERY,
        source_ip="198.51.100.110",
        session_id="33333333-3333-4333-8333-333333333333",
        sql_statement="DROP TABLE users",
    )

    async def _explode(*args, **kwargs):  # noqa: ANN002, ANN003 - 注入点替身
        raise RuntimeError("注入的分析失败（事务回滚测试）")

    monkeypatch.setattr(m4_public, "analyze_and_derive", _explode)

    with pytest.raises(RuntimeError, match="注入的分析失败"):
        await ingest_event(event)

    for table in (
        "sessions",
        "attack_log",
        "rule_hits",
        "alerts",
        "attacker_profile",
        "attacker_intent",
    ):
        assert await count_rows(db_session, table) == 0, f"{table} 应无残留"


async def test_event_retry_succeeds_after_rollback(
    db_session, event_factory, ingest_event, monkeypatch
):
    """回滚后同一事件可重试成功（事务前状态与事务后一致）。"""
    event = event_factory(
        event_type=EventType.QUERY,
        source_ip="198.51.100.111",
        session_id="44444444-4444-4444-8444-444444444444",
        sql_statement="DROP TABLE users",
    )

    async def _explode(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("注入的分析失败（重试测试）")

    monkeypatch.setattr(m4_public, "analyze_and_derive", _explode)
    with pytest.raises(RuntimeError):
        await ingest_event(event)

    # 取消注入后重试同一 event_uuid（回滚不应留下幂等占用）
    monkeypatch.undo()
    result = await ingest_event(event)

    assert result.duplicate is False
    assert result.event_id > 0
    assert await count_rows(db_session, "sessions") == 1
    assert await count_rows(db_session, "attack_log") == 1
    assert await count_rows(db_session, "rule_hits") == 1
    assert await count_rows(db_session, "alerts") == 1
    assert await count_rows(db_session, "attacker_profile") == 1

    alert = (
        await db_session.execute(
            text("SELECT severity, alert_type FROM alerts")
        )
    ).mappings().one()
    assert alert["severity"] == "critical"
    assert alert["alert_type"] == "destructive"
