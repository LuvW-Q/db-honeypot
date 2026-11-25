"""ORM 模型统一导出。

共 11 张表（data-model 第 4 章），按域拆分为多个模块；本模块负责聚合导入，
使 `from shared.models import Session, AttackLog, ...` 与 `import shared.models` 都能
一次性注册全部映射（Alembic env.py 依赖该副作用取得完整 `Base.metadata`）。

视图（v_session_risk_summary 等 4 个）由迁移 0002 创建，属于只读分析对象，
不映射为 ORM 实体；控制台查询通过 `text()` 或只读仓储访问。
"""

from __future__ import annotations

from shared.models.alerts import Alert
from shared.models.attack_log import AttackLog
from shared.models.attacker_intent import AttackerIntent
from shared.models.attacker_profile import AttackerProfile
from shared.models.audit_log import AuditLog
from shared.models.detection_rules import DetectionRule
from shared.models.fake_models import FakeConfig, FakeOrder, FakeUser
from shared.models.rule_hits import RuleHit
from shared.models.sessions import Session

__all__ = [
    # 观测数据
    "Session",
    "AttackLog",
    "AttackerProfile",
    "AttackerIntent",
    "DetectionRule",
    "RuleHit",
    "Alert",
    # 诱饵数据
    "FakeUser",
    "FakeOrder",
    "FakeConfig",
    # 审计
    "AuditLog",
]
