"""事件发射器：把捕获层事件安全写入存储层。

按 `impl-contract.md` 第 2 章实现：每次事件使用独立的读写会话与事务；
任何异常只写运行日志，**不影响**诱饵协议响应（events.md 6.2 / 8.10）。

死锁（1213）/锁等待超时（1205）按 `events.md` 6.2 做有限重试：
退避 50ms → 200ms → 800ms（±20% 抖动），每次重试复用同一 `event_uuid`，
因此重复写入由唯一约束幂等裁决，不会重复计数或重复分析。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Iterable

from app.db.session import get_rw_factory
from app.schemas.events import CapturedEvent, IngestResult
from app.services.ingest import IngestService, mysql_errno

logger = logging.getLogger(__name__)

# MySQL 锁冲突错误码：可整体重试事务
_RETRYABLE_ERRNOS = frozenset({1205, 1213})
# 退避序列（秒），与 data-model 8.5 / events.md 6.2 一致
_RETRY_DELAYS = (0.05, 0.2, 0.8)


def _retry_delay(attempt: int) -> float:
    """第 attempt 次重试的退避时间，带 ±20% 抖动。"""
    base = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
    return base * random.uniform(0.8, 1.2)


class EventEmitter:
    """把标准事件写入数据库；失败降级为运行日志。"""

    def __init__(
        self,
        factory: object | None = None,
        *,
        max_retries: int = 3,
    ) -> None:
        # 允许注入会话工厂（测试用）；默认使用应用读写会话工厂
        self._factory = factory or get_rw_factory
        self._max_retries = max(0, int(max_retries))

    async def emit(self, event: CapturedEvent) -> IngestResult | None:
        """发射一条事件；成功返回入库结果，失败返回 None（只记日志）。"""
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            try:
                session_factory = self._factory()  # type: ignore[operator]
                async with session_factory() as db:  # type: ignore[misc]
                    async with db.begin():
                        service = IngestService(db)
                        result = await service.ingest(event)
                    return result
            except Exception as exc:  # noqa: BLE001 - 协议层不得因入库失败而中断
                errno = mysql_errno(exc)
                if errno in _RETRYABLE_ERRNOS and attempt < attempts - 1:
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "事件写入锁冲突（errno=%s），第 %s/%s 次重试，%.0fms 后继续："
                        "event_uuid=%s session_id=%s",
                        errno,
                        attempt + 1,
                        self._max_retries,
                        delay * 1000,
                        getattr(event, "event_uuid", None),
                        getattr(event, "session_id", None),
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.exception(
                    "事件发射失败（仅记录运行日志，不影响协议响应）：event_uuid=%s "
                    "session_id=%s event_type=%s errno=%s",
                    getattr(event, "event_uuid", None),
                    getattr(event, "session_id", None),
                    getattr(event, "event_type", None),
                    errno,
                )
                return None
        return None

    async def emit_many(self, events: Iterable[CapturedEvent]) -> list[IngestResult | None]:
        """按顺序发射多条事件（保持同一会话内的事件顺序）。"""
        results: list[IngestResult | None] = []
        for event in events:
            results.append(await self.emit(event))
        return results
