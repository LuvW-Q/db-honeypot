"""会话生命周期管理（`sessions` 表）。

职责（`impl-contract.md` 第 2 章、`contracts/events.md` 第 5 章）：
- `ensure_session`：按 `session_id` 定位会话；`connect` 事件创建会话行，
  其他事件复用并原子自增 `request_count`；找不到会话且事件不是 `connect` 时
  用事件信息补建（迟到/重投场景）。
- `finalize_session`：`disconnect` 时写入 `ended_at` 与 `session_status`（幂等，
  不覆盖已有结束状态）。
- `refresh_counters`：按 `attack_log`/`rule_hits` 重算事件计数与会话风险分
  （校验/运维用途，写回 `max_risk_score` 时遵守"只增不减"）。

本模块只做持久化，不做协议解析与规则判定；事务由 `IngestService` 统一控制。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.events.schema import CapturedEvent, EventType
from shared.models.attack_log import AttackLog
from shared.models.rule_hits import RuleHit
from shared.models.sessions import Session as SessionRow

logger = logging.getLogger(__name__)

# sessions.session_status 的合法迁移目标（data-model 4.1 / events.md 5.1）
_FINAL_STATUSES: frozenset[str] = frozenset({"closed", "timeout", "error"})


def to_naive_utc(moment: datetime | None) -> datetime | None:
    """把带时区的 UTC 时间转为"无时区 UTC"，适配 MySQL `DATETIME(6)`。

    数据库列不带时区，统一存 UTC 墙上时间；传入 naive 时间视为已是 UTC。
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


class SessionManager:
    """会话行的定位、创建、结束与计数维护。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load(
        self, session_id: str, *, for_update: bool = False
    ) -> SessionRow | None:
        stmt = select(SessionRow).where(SessionRow.session_id == session_id)
        if for_update:
            # 会话行是同一来源下的热点行，事务内串行化计数更新（events.md 6.1）
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def ensure_session(self, event: CapturedEvent) -> SessionRow:
        """确保事件所属会话存在，并维护 `request_count`。

        - 会话已存在：`connect` 事件不重复计数（重投/重连语义），其他事件 +1；
        - 会话不存在且事件为 `connect`：插入会话行，`request_count = 1`；
        - 会话不存在且事件非 `connect`：用事件信息补建（`request_count = 1`），
          并记录运行日志（迟到事件 / 首事件丢失）。
        """
        row = await self._load(event.session_id, for_update=True)
        if row is not None:
            if event.event_type is not EventType.CONNECT:
                row.request_count = int(row.request_count or 0) + 1
            return row

        is_connect = event.event_type is EventType.CONNECT
        if not is_connect:
            logger.warning(
                "会话不存在，使用事件信息补建：session_id=%s event_type=%s event_uuid=%s",
                event.session_id,
                event.event_type,
                event.event_uuid,
            )
        started_at = to_naive_utc(event.event_time) or datetime.now(UTC).replace(
            tzinfo=None
        )
        client_fingerprint = None
        if event.client_info:
            client_fingerprint = event.client_info[:255]
        row = SessionRow(
            session_id=event.session_id,
            source_ip=(event.source_ip or "0.0.0.0").lower()[:45],
            source_port=event.source_port,
            target_service=(settings.honeypot_service_name or "mysql-honeypot")[:64],
            client_fingerprint=client_fingerprint,
            started_at=started_at,
            ended_at=None,
            session_status="active",
            request_count=1,
            max_risk_score=0,
        )
        self.db.add(row)
        await self.db.flush()
        logger.info(
            "新建会话：session_id=%s source_ip=%s source_port=%s event_type=%s",
            row.session_id,
            row.source_ip,
            row.source_port,
            event.event_type,
        )
        return row

    async def finalize_session(
        self,
        session_id: str,
        status: str,
        *,
        ended_at: datetime | None = None,
    ) -> None:
        """结束会话：写入 `ended_at` 与 `session_status`（幂等，只生效一次）。

        `status` 只能取 ``closed`` / ``timeout`` / ``error``；重复关闭不覆盖首次结果。
        `ended_at < started_at` 时取 `started_at` 并写运行日志（events.md 5.1）。
        """
        if status not in _FINAL_STATUSES:
            raise ValueError(f"非法会话结束状态：{status!r}")
        row = await self._load(session_id, for_update=True)
        if row is None:
            logger.warning("会话不存在，无法结束：session_id=%s status=%s", session_id, status)
            return
        if row.ended_at is not None or row.session_status != "active":
            # 重复关闭：不覆盖首次结束时间与状态（events.md 5.1）
            logger.info(
                "重复关闭会话，忽略：session_id=%s 当前状态=%s", session_id, row.session_status
            )
            return
        end = to_naive_utc(ended_at) or datetime.now(UTC).replace(tzinfo=None)
        if row.started_at is not None and end < row.started_at:
            logger.warning(
                "会话结束时间早于开始时间，取 started_at：session_id=%s", session_id
            )
            end = row.started_at
        row.ended_at = end
        row.session_status = status

    def apply_risk_score(self, session_row: SessionRow, score: int | None) -> None:
        """按 GREATEST 语义抬升会话最高风险分（只增不减，0–100）。"""
        try:
            value = int(score or 0)
        except (TypeError, ValueError):
            value = 0
        value = max(0, min(100, value))
        if value > int(session_row.max_risk_score or 0):
            session_row.max_risk_score = value

    async def refresh_counters(self, session_id: str) -> dict[str, int]:
        """按库内数据重算会话计数与风险分（返回重算结果，不提交事务）。

        - `request_count` 取 `attack_log` 实际条数（connect/auth/query/disconnect 均计 1）；
        - 风险分按 events.md 6.4 会话口径重算：同一 `rule_code` 取最大 `risk_weight`
          后求和并封顶 100；写回时仍遵守"只增不减"。
        """
        row = await self._load(session_id, for_update=True)
        if row is None:
            logger.warning("会话不存在，无法重算计数：session_id=%s", session_id)
            return {}

        event_count = (
            await self.db.execute(
                select(func.count())
                .select_from(AttackLog)
                .where(AttackLog.session_id == session_id)
            )
        ).scalar_one()

        hit_rows = (
            await self.db.execute(
                select(RuleHit.rule_code, func.max(RuleHit.risk_weight))
                .where(RuleHit.session_id == session_id)
                .group_by(RuleHit.rule_code)
            )
        ).all()
        risk_score = min(100, sum(int(weight or 0) for _, weight in hit_rows))

        row.request_count = int(event_count or 0)
        self.apply_risk_score(row, risk_score)
        return {"event_count": int(event_count or 0), "risk_score": risk_score}
