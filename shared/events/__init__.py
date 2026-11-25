"""标准事件契约：类型/状态枚举、事件构造与校验。"""

from shared.events.builder import build_event
from shared.events.schema import (  # noqa: F401
    AnalysisResult,
    CapturedEvent,
    EventStatus,
    EventType,
    RuleHitSummary,
)

__all__ = ["AnalysisResult", "CapturedEvent", "EventStatus", "EventType", "RuleHitSummary", "build_event"]
