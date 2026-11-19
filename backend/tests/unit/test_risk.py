"""风险评分纯函数单元测试（data-model 9.1–9.3 口径）。"""

from __future__ import annotations

import pytest

from app.services.risk import (
    INTENT_TYPES,
    build_evidence,
    compute_intent_scores,
    compute_profile_risk,
    compute_session_risk,
    risk_level,
)


def _hit(rule_code: str, weight: int, intent_type: str = "recon") -> dict:
    """构造一条最小命中记录（与 rule_hits 同名字段）。"""
    return {"rule_code": rule_code, "risk_weight": weight, "intent_type": intent_type}


def test_compute_session_risk_sums_max_weight_per_rule():
    """会话分 = 各 rule_code 最大权重之和。"""
    hits = [
        _hit("R03", 15, "recon"),
        _hit("R05", 35, "destructive"),
        _hit("R02", 25, "bruteforce"),
    ]
    assert compute_session_risk(hits) == 75


def test_same_rule_code_deduplicated_by_max_weight():
    """同一 rule_code 多次命中只计一次，并取最大权重快照。"""
    hits = [_hit("R05", 35), _hit("R05", 20), _hit("R05", 35)]
    assert compute_session_risk(hits) == 35
    assert compute_profile_risk(hits) == 35


def test_session_risk_capped_at_100():
    """权重之和超过 100 时封顶。"""
    hits = [
        _hit("R01", 10),
        _hit("R02", 25),
        _hit("R03", 15),
        _hit("R04", 25),
        _hit("R05", 35),
    ]
    assert compute_session_risk(hits) == 100
    assert compute_profile_risk(hits) == 100


def test_empty_hits_score_zero():
    """无命中 → 0 分。"""
    assert compute_session_risk([]) == 0
    assert compute_profile_risk([]) == 0
    assert compute_intent_scores([]) == {}


def test_profile_risk_is_rule_dimension_not_intent_sum():
    """画像分按规则维度聚合，不是“意图分相加”。"""
    # 两个不同规则各 60 分：意图分各自封顶 60，但画像分 = min(100, 60+60) = 100
    hits = [
        _hit("R04", 60, "data_dump"),
        _hit("R05", 60, "destructive"),
    ]
    intent_scores = compute_intent_scores(hits)
    assert intent_scores == {"data_dump": 60, "destructive": 60}
    assert compute_profile_risk(hits) == 100


def test_intent_scores_group_by_intent_and_dedupe_rule():
    """意图分按 intent_type 分组、组内按 rule_code 去重取最大权重。"""
    hits = [
        _hit("R01", 10, "scanning"),
        _hit("R01", 10, "scanning"),
        _hit("R03", 15, "recon"),
        _hit("R02", 25, "bruteforce"),
        _hit("R04", 25, "data_dump"),
        _hit("R05", 35, "destructive"),
    ]
    scores = compute_intent_scores(hits)
    assert scores == {
        "scanning": 10,
        "recon": 15,
        "bruteforce": 25,
        "data_dump": 25,
        "destructive": 35,
    }


def test_intent_scores_cap_each_intent_at_100():
    """单意图分数超过 100 时封顶。"""
    hits = [_hit(f"R9{i}", 60, "data_dump") for i in range(3)]
    assert compute_intent_scores(hits) == {"data_dump": 100}


def test_weights_are_normalized_and_out_of_range_ignored():
    """权重为字符串/负数/超 100 时按 0–100 归一（负权重按 0 处理）。"""
    hits = [
        {"rule_code": "R01", "risk_weight": "not-a-number", "intent_type": "scanning"},
        {"rule_code": "R02", "risk_weight": -5, "intent_type": "bruteforce"},
        {"rule_code": "R03", "risk_weight": 150, "intent_type": "recon"},
    ]
    assert compute_profile_risk(hits) == 100  # 0 + 0 + min(150,100)
    assert compute_session_risk(hits) == 100


def test_intent_types_constant_matches_schema():
    """意图枚举集合与 data-model 4.4 一致。"""
    assert set(INTENT_TYPES) == {
        "scanning",
        "bruteforce",
        "recon",
        "data_dump",
        "destructive",
    }


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, "low"),
        (1, "low"),
        (29, "low"),
        (30, "medium"),
        (59, "medium"),
        (60, "high"),
        (79, "high"),
        (80, "critical"),
        (99, "critical"),
        (100, "critical"),
    ],
)
def test_risk_level_boundaries(score, expected):
    """风险等级边界：0/29 low、30/59 medium、60/79 high、80/100 critical。"""
    assert risk_level(score) == expected


@pytest.mark.parametrize(("score", "expected"), [(-1, "low"), (101, "critical")])
def test_risk_level_out_of_range_is_clamped_by_thresholds(score, expected):
    """阈值映射对极端值仍保持单调（越界不抛异常）。"""
    assert risk_level(score) == expected


def test_build_evidence_dedupes_and_sorts():
    """证据摘要去重、按编码排序；空输入返回空串。"""
    assert build_evidence(["R05", "R03", "R05"]) == "命中规则：R03、R05"
    assert build_evidence([]) == ""
    assert build_evidence([""]) == ""
