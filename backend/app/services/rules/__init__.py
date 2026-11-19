"""规则包：导出注册表并触发各规则模块的注册副作用。

分析层只依赖 `from app.services.rules import RULES`，不直接依赖具体规则文件；
新增规则时在 `RULES` 注册后由 `detection_rules.rule_code` 自动关联，
未实现的编码会被分析层跳过并记录告警日志（不静默）。
"""

from __future__ import annotations

from app.services.rules.base import RULES, RuleContext, RuleHitCandidate, register
from app.services.rules.r01_scanning import evaluate as r01_scanning
from app.services.rules.r02_bruteforce import evaluate as r02_bruteforce
from app.services.rules.r03_recon import evaluate as r03_recon
from app.services.rules.r04_data_dump import evaluate as r04_data_dump
from app.services.rules.r05_destructive import evaluate as r05_destructive

# 显式引用一次，避免静态检查误删导入（导入即完成注册）
_RULE_IMPLEMENTATIONS = (
    r01_scanning,
    r02_bruteforce,
    r03_recon,
    r04_data_dump,
    r05_destructive,
)

__all__ = [
    "RULES",
    "RuleContext",
    "RuleHitCandidate",
    "register",
    "r01_scanning",
    "r02_bruteforce",
    "r03_recon",
    "r04_data_dump",
    "r05_destructive",
]
