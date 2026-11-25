"""风险等级映射（唯一实现口径）：0–29 low / 30–59 medium / 60–79 high / 80–100 critical。"""

from __future__ import annotations


def risk_level(score: int) -> str:
    """风险分映射为四档等级；非法输入按 0 处理。"""
    try:
        value = int(score)
    except (TypeError, ValueError):
        value = 0
    if value >= 80:
        return "critical"
    if value >= 60:
        return "high"
    if value >= 30:
        return "medium"
    return "low"


__all__ = ["risk_level"]
