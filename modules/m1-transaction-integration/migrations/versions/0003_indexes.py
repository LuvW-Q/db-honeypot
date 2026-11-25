"""补充索引：data-model 7.1 索引总表中不随建表创建的部分（成对 downgrade）。

修订号（Revision ID）: 0003_indexes
父修订（Revises）: 0002_analysis_views
创建时间（Create Date）: 2026-11-19

索引分工（保证 0001 + 0003 合并后与 data-model 7.1 索引总表完全一致）：

- 0001 创建：唯一键、主键、外键支撑索引，以及**四条规定复合索引**
  （idx_log_session_time、idx_log_source_time、idx_alert_level_time、
  idx_hit_rule_time，名称与列顺序不得变更）；
- 0003 创建（本文件）：不承担外键约束的纯查询索引 ——
  会话按来源/状态/时间检索、画像风险排序、意图分布、规则列表、
  告警类型/已读筛选、审计时间与操作检索。

MySQL 8 的 `CREATE INDEX` 不支持 `IF NOT EXISTS`，因此每个索引只在本迁移中创建一次；
`downgrade` 按创建逆序 `DROP INDEX`，重复执行由 Alembic 版本表保证不会发生。
"""

from collections.abc import Sequence

from alembic import op

# Alembic 修订标识
revision: str = "0003_indexes"
down_revision: str | Sequence[str] | None = "0002_analysis_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (表名, 索引名, 列列表, 中文说明)
INDEXES: list[tuple[str, str, list[str], str]] = [
    (
        "sessions",
        "idx_sessions_source_started",
        ["source_ip", "started_at"],
        "攻击者详情页按来源列出会话；画像关联统计的检索入口（FR-064）",
    ),
    (
        "sessions",
        "idx_sessions_status_started",
        ["session_status", "started_at"],
        "巡检未关闭会话（active/timeout）并按时序扫描，供超时回收任务使用（FR-017）",
    ),
    (
        "sessions",
        "idx_sessions_started",
        ["started_at"],
        "首页近 N 天连接数/会话数按时间范围聚合（FR-062）",
    ),
    (
        "attacker_profile",
        "idx_profile_risk",
        ["risk_score", "last_seen"],
        "攻击者列表按风险分降序、最近时间降序分页；MySQL 8 可反向扫描升序索引",
    ),
    (
        "attacker_intent",
        "idx_intent_type_score",
        ["intent_type", "intent_score"],
        "意图分布统计与按意图查看攻击者（FR-064）",
    ),
    (
        "detection_rules",
        "idx_detection_rules_intent",
        ["intent_type", "enabled", "rule_code"],
        "按意图列出可用规则，供分析层与规则管理页使用（FR-054）",
    ),
    (
        "alerts",
        "idx_alert_type_time",
        ["alert_type", "created_at"],
        "按告警类型 + 时间筛选（FR-056/FR-066）",
    ),
    (
        "alerts",
        "idx_alert_read_time",
        ["is_read", "created_at"],
        "未读告警筛选与最近未读默认排序（FR-058/FR-066）",
    ),
    (
        "audit_log",
        "idx_audit_time",
        ["occurred_at"],
        "审计日志按时间范围检索（宪法原则三）",
    ),
    (
        "audit_log",
        "idx_audit_operation_time",
        ["operation", "occurred_at"],
        "审计日志按操作类型 + 时间检索（宪法原则三）",
    ),
]


def upgrade() -> None:
    """创建 10 条纯查询索引。"""
    for table, name, columns, _comment in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    """按创建逆序删除本迁移创建的索引。"""
    for table, name, _columns, _comment in reversed(INDEXES):
        op.drop_index(name, table_name=table)
