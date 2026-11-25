"""事件写入流水线（存储层入口）。

单事务完成（`contracts/events.md` 6.1、`impl-contract.md` 第 2 章）：
1. 幂等预查 `event_uuid`（唯一约束仍是最终权威，1062 冲突回查返回 duplicate）；
2. `SessionManager.ensure_session` 定位/创建会话并更新 `request_count`；
3. `INSERT attack_log`；
4. 延迟导入并调用分析层 `analyze_event`（同一事务；模块缺失时降级跳过并记日志）；
5. 按分析结果以 GREATEST 抬升 `sessions.max_risk_score`；
6. `disconnect` 事件同时结束会话（`ended_at`/`session_status`）；
7. `COMMIT`；任一步异常 `ROLLBACK` 并抛出，不留下部分提交结果。

安全：采集到的 SQL 只作为字符串写入，绝不拼进任何查询执行。
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from m1_transaction_integration.services.session_manager import SessionManager, to_naive_utc
from shared.db.errors import mysql_errno
from shared.events.schema import EventStatus, EventType, IngestResult
from shared.models.attack_log import AttackLog

logger = logging.getLogger(__name__)

# 幂等冲突的约束名（data-model 5.3）
_EVENT_UUID_CONSTRAINT = "uk_attack_log_event_uuid"


class IngestService:
    """事件入库服务：接收捕获层标准事件，完成持久化与派生分析。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.session_manager = SessionManager(db)

    async def ingest(self, event) -> IngestResult:
        """写入一条标准事件；重复 `event_uuid` 返回已有 `event_id`（duplicate=True）。"""
        # 1) 幂等预查：已存在则直接返回，不重复计数、不重复分析
        existing_id = await self._find_event_id(event.event_uuid)
        if existing_id is not None:
            logger.info(
                "事件已存在，跳过写入：event_uuid=%s event_id=%s", event.event_uuid, existing_id
            )
            return IngestResult(
                event_id=existing_id,
                session_id=event.session_id,
                duplicate=True,
            )

        try:
            # 2) 会话定位/创建 + 计数
            session_row = await self.session_manager.ensure_session(event)

            # 3) 原始事件落库（唯一约束在此裁决幂等）
            log_row = AttackLog(
                event_uuid=event.event_uuid,
                session_id=event.session_id,
                # source_ip 在写入事务内从会话行复制（受控反规范化，events.md 3.2）
                event_type=str(event.event_type),
                source_ip=session_row.source_ip or (event.source_ip or "0.0.0.0").lower()[:45],
                username=event.username,
                credential_test_id=event.credential_test_id,
                sql_statement=event.sql_statement,
                normalized_sql=event.normalized_sql,
                event_time=to_naive_utc(event.event_time),
                returned_rows=max(0, int(event.returned_rows or 0)),
                response_ms=max(0, int(event.response_ms or 0)),
                status=str(event.status),
                payload_truncated=1 if event.payload_truncated else 0,
            )
            self.db.add(log_row)
            await self.db.flush()

            # 4) 分析流水线（延迟导入：分析层缺失时不影响捕获/存储）
            analysis = await self._analyze(log_row, session_row)

            # 5) 会话最高风险分（GREATEST 语义，只增不减）
            risk_score = getattr(analysis, "session_risk_score", 0) if analysis else 0
            self.session_manager.apply_risk_score(session_row, risk_score)

            # 6) 断开事件：结束会话（重复关闭在 SessionManager 内幂等处理）
            if event.event_type is EventType.DISCONNECT:
                await self.session_manager.finalize_session(
                    event.session_id,
                    self._final_session_status(event.status),
                    ended_at=event.event_time,
                )

            # 7) 提交
            await self.db.commit()
        except IntegrityError as exc:
            await self._rollback_quietly()
            if mysql_errno(exc) == 1062 and self._is_event_uuid_conflict(exc):
                # 并发重复提交：唯一键裁决后回查已有事件（events.md 4.1）
                existing_id = await self._find_event_id(event.event_uuid)
                if existing_id is not None:
                    logger.info(
                        "事件并发重复，回查已有记录：event_uuid=%s event_id=%s",
                        event.event_uuid,
                        existing_id,
                    )
                    return IngestResult(
                        event_id=existing_id,
                        session_id=event.session_id,
                        duplicate=True,
                    )
            logger.exception(
                "事件写入唯一约束/完整性冲突，已回滚：event_uuid=%s session_id=%s",
                event.event_uuid,
                event.session_id,
            )
            raise
        except Exception:
            await self._rollback_quietly()
            logger.exception(
                "事件写入失败，已回滚：event_uuid=%s session_id=%s event_type=%s",
                event.event_uuid,
                event.session_id,
                event.event_type,
            )
            raise

        rule_hits = list(getattr(analysis, "rule_hits", None) or []) if analysis else []
        alert_ids = list(getattr(analysis, "alert_ids", None) or []) if analysis else []
        logger.info(
            "事件写入成功：event_uuid=%s event_id=%s session_id=%s event_type=%s status=%s "
            "hits=%s alerts=%s session_risk=%s",
            event.event_uuid,
            log_row.event_id,
            event.session_id,
            event.event_type,
            event.status,
            len(rule_hits),
            len(alert_ids),
            risk_score,
        )
        return IngestResult(
            event_id=int(log_row.event_id),
            session_id=event.session_id,
            duplicate=False,
            rule_hits=rule_hits,
            alerts=alert_ids,
        )

    async def _find_event_id(self, event_uuid: str) -> int | None:
        """按幂等键查已有事件编号；不存在返回 None。"""
        from sqlalchemy import select

        return (
            await self.db.execute(
                select(AttackLog.event_id).where(AttackLog.event_uuid == event_uuid)
            )
        ).scalar_one_or_none()

    async def _analyze(self, log_row: AttackLog, session_row) -> object | None:
        """调用分析层（函数内延迟导入，模块缺失时降级为跳过分析）。

        分析层与事件写入在同一事务内执行；分析失败由调用方回滚（events.md 6.1）。
        """
        try:
            from m4_rules_derived import public as rules_derived
        except Exception:  # noqa: BLE001 - 分析层尚未就绪时不得阻断存储层
            logger.warning(
                "分析层模块不可用，事件仅入库不分析：event_uuid=%s event_id=%s",
                log_row.event_uuid,
                log_row.event_id,
            )
            return None
        return await rules_derived.analyze_and_derive(self.db, log_row, session_row)

    @staticmethod
    def _is_event_uuid_conflict(exc: IntegrityError) -> bool:
        message = str(getattr(exc, "orig", exc))
        return _EVENT_UUID_CONSTRAINT in message or "event_uuid" in message

    @staticmethod
    def _final_session_status(status: EventStatus) -> str:
        """把 disconnect 事件结果映射为 sessions.session_status（events.md 5.1）。"""
        if status is EventStatus.SUCCESS:
            return "closed"
        if status is EventStatus.FAILURE:
            return "timeout"
        return "error"

    async def _rollback_quietly(self) -> None:
        try:
            await self.db.rollback()
        except Exception:  # noqa: BLE001 - 回滚失败只记日志，不掩盖原始异常
            logger.exception("事务回滚失败")
