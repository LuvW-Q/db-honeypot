"""风险评分纯函数（data-model 9.2 / 9.3 的唯一实现口径）。

评分三档统一规则（9.1）：

1. 计分单元是 `rule_code`，同一规则在同一统计范围内重复命中只计一次；
2. 同一规则取命中快照中的**最大权重** `MAX(risk_weight)`；
3. 三档结果一律 `LEAST(100, Σ 各规则最大权重)`；
4. 画像分按“规则维度”直接聚合，**不是**把各意图分相加再封顶（9.2 口径说明）。

本模块不访问数据库、不做 I/O，便于单元测试；输入既可以是 ORM `RuleHit` 行，
也可以是 `dict`/`RowMapping`/`RuleHitSummary` 等带同名字段的对象。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# 意图类型全集（data-model 4.4）
INTENT_TYPES: tuple[str, ...] = (
    "scanning",
    "bruteforce",
    "recon",
    "data_dump",
    "destructive",
)


def _field(hit: Any, name: str, default: Any = None) -> Any:
    """从 ORM 行 / 映射 / 普通对象中读取字段，缺失时返回默认值。"""
    if isinstance(hit, Mapping):
        return hit.get(name, default)
    return getattr(hit, name, default)


def _normalize_weight(value: Any) -> int:
    """把驱动可能返回的 Decimal/str 权重安全转成 0–100 的整数。"""
    try:
        weight = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(weight, 100))


def _max_weight_by_rule(hits: Iterable[Any]) -> dict[str, int]:
    """按 rule_code 聚合最大权重快照。"""
    weights: dict[str, int] = {}
    for hit in hits:
        rule_code = _field(hit, "rule_code")
        if not rule_code:
            continue
        weight = _normalize_weight(_field(hit, "risk_weight", 0))
        code = str(rule_code)
        if weight > weights.get(code, 0):
            weights[code] = weight
    return weights


def _cap(score: int) -> int:
    """分数封顶 100，且不允许负数。"""
    return max(0, min(int(score), 100))


def risk_level(score: int) -> str:
    """风险等级映射（data-model 9.3）：0–29 low / 30–59 medium / 60–79 high / 80–100 critical。"""
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


def compute_session_risk(hits: list[Any]) -> int:
    """会话风险分：该会话全部命中按 rule_code 去重取最大权重后求和并封顶。"""
    return _cap(sum(_max_weight_by_rule(hits).values()))


def compute_intent_scores(hits: list[Any]) -> dict[str, int]:
    """意图风险分：按 `intent_type` 快照分组，再按 rule_code 去重取最大权重求和并封顶。"""
    grouped: dict[str, list[Any]] = {}
    for hit in hits:
        intent_type = _field(hit, "intent_type")
        if not intent_type:
            continue
        grouped.setdefault(str(intent_type), []).append(hit)
    return {
        intent_type: _cap(sum(_max_weight_by_rule(group_hits).values()))
        for intent_type, group_hits in grouped.items()
    }


def compute_profile_risk(hits: list[Any]) -> int:
    """画像风险分：该来源全部命中按 rule_code 去重取最大权重后求和并封顶。"""
    return _cap(sum(_max_weight_by_rule(hits).values()))


def build_evidence(rule_codes: list[str]) -> str:
    """构造画像/会话的证据摘要（规则编码去重、按编码排序，长度受限）。"""
    unique_codes = sorted({str(code) for code in rule_codes if code})
    if not unique_codes:
        return ""
    return f"命中规则：{'、'.join(unique_codes)}"


__all__ = [
    "INTENT_TYPES",
    "risk_level",
    "compute_session_risk",
    "compute_intent_scores",
    "compute_profile_risk",
    "build_evidence",
]
