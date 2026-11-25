"""规则种子数据：R01–R05（rule_version = 1，enabled = 1）。

修订号（Revision ID）: 0004_seed_rules
父修订（Revises）: 0003_indexes
创建时间（Create Date）: 2026-11-19

权威定义：`specs/001-database-honeypot/data-model.md` 第 10.1、10.2 章。

- 五条规则覆盖 scanning / bruteforce / recon / data_dump / destructive 五类意图；
- `parameters_json` 结构逐键对齐 10.2，阈值均为“达到即命中”（`>=`）；
- 可重复执行：`INSERT ... ON DUPLICATE KEY UPDATE`，唯一键
  `(rule_code, rule_version)` 保证重复执行不新增行、不改变行数；
- 使用 `op.execute` 执行带字面量的 SQL 文本（种子为仓库内静态受控数据），
  从而**同时支持在线迁移与 `--sql` 离线模式**；
- 不修改已存在的其他版本规则（规则改版必须走 10.3 的 T3 事务新建版本）。

`downgrade` 删除 R01–R05 的 v1 行；若已被 rule_hits/alerts 引用，外键 RESTRICT
会阻止删除并报错（data-model 12.5 的回滚纪律：显式报错而非关闭外键检查）。
"""

import json
from collections.abc import Sequence

from alembic import op

# Alembic 修订标识
revision: str = "0004_seed_rules"
down_revision: str | Sequence[str] | None = "0003_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULE_VERSION = 1

# data-model 10.2：五条种子规则的完整定义
RULES: list[dict[str, object]] = [
    {
        "rule_code": "R01",
        "rule_name": "短时高频连接扫描",
        "rule_type": "frequency",
        "intent_type": "scanning",
        "risk_weight": 10,
        "description": "60 秒内同一来源连接不少于 10 次且无有效 SQL，典型端口/服务扫描特征",
        "parameters_json": {
            "scope": "source_ip",
            "window_seconds": 60,
            "min_connect_count": 10,
            "max_valid_sql_count": 0,
            "boundary": "inclusive",
        },
    },
    {
        "rule_code": "R02",
        "rule_name": "短时多凭据认证爆破",
        "rule_type": "frequency",
        "intent_type": "bruteforce",
        "risk_weight": 25,
        "description": "5 分钟内同一来源认证尝试不少于 8 次，且不同用户名与测试标识组合不少于 5 组",
        "parameters_json": {
            "scope": "source_ip",
            "window_seconds": 300,
            "min_auth_attempts": 8,
            "min_distinct_credential_pairs": 5,
            "count_failed_only": False,
        },
    },
    {
        "rule_code": "R03",
        "rule_name": "元数据与结构探测",
        "rule_type": "keyword",
        "intent_type": "recon",
        "risk_weight": 15,
        "description": "出现 SHOW TABLES、SHOW DATABASES、SHOW COLUMNS、DESCRIBE、information_schema 查询",
        "parameters_json": {
            "scope": "event",
            "match_target": "normalized_sql",
            "case_sensitive": False,
            "keywords": [
                "SHOW TABLES",
                "SHOW DATABASES",
                "SHOW COLUMNS",
                "SHOW FIELDS",
                "DESCRIBE",
                "DESC ",
                "INFORMATION_SCHEMA",
            ],
            "max_hits_per_event": 1,
        },
    },
    {
        "rule_code": "R04",
        "rule_name": "会话级批量数据读取",
        "rule_type": "volume",
        "intent_type": "data_dump",
        "risk_weight": 25,
        "description": "同一会话连续 SELECT 不少于 5 次，或会话累计返回行数超过 1000 行",
        "parameters_json": {
            "scope": "session",
            "window_seconds": 300,
            "min_consecutive_select": 5,
            "session_returned_rows_threshold": 1000,
            "count_scope": "session_cumulative",
        },
    },
    {
        "rule_code": "R05",
        "rule_name": "破坏性写操作尝试",
        "rule_type": "keyword",
        "intent_type": "destructive",
        "risk_weight": 35,
        "description": "出现 DROP、TRUNCATE、DELETE、UPDATE、INSERT（诱饵层拒绝执行，仅记录并告警）",
        "parameters_json": {
            "scope": "event",
            "match_target": "normalized_sql",
            "case_sensitive": False,
            "word_boundary": True,
            "keywords": ["DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT"],
            "count_status": ["denied", "error", "success"],
        },
    },
]


def _sql_literal(value: object) -> str:
    """把种子值渲染为 SQL 字面量（仅用于仓库内静态种子，不接收外部输入）。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _upsert_sql(rule: dict[str, object]) -> str:
    """生成单条规则的幂等 upsert SQL（ON DUPLICATE KEY UPDATE）。"""
    # 注意：分隔符保留空格，避免 Alembic 把 JSON 中的 ":60"、":false" 误判为
    # `:param` 绑定参数（离线模式会渲染成 NULL），保证 --sql 输出可执行。
    params_json = json.dumps(
        rule["parameters_json"], ensure_ascii=False, separators=(", ", ": ")
    )
    columns = (
        "rule_code, rule_name, rule_type, intent_type, parameters_json, "
        "risk_weight, rule_version, enabled, description"
    )
    values = ", ".join(
        [
            _sql_literal(rule["rule_code"]),
            _sql_literal(rule["rule_name"]),
            _sql_literal(rule["rule_type"]),
            _sql_literal(rule["intent_type"]),
            _sql_literal(params_json),
            _sql_literal(rule["risk_weight"]),
            _sql_literal(RULE_VERSION),
            "1",
            _sql_literal(rule["description"]),
        ]
    )
    return (
        f"INSERT INTO detection_rules ({columns}) VALUES ({values})\n"
        "ON DUPLICATE KEY UPDATE\n"
        "    rule_name = VALUES(rule_name),\n"
        "    rule_type = VALUES(rule_type),\n"
        "    intent_type = VALUES(intent_type),\n"
        "    parameters_json = VALUES(parameters_json),\n"
        "    risk_weight = VALUES(risk_weight),\n"
        "    enabled = VALUES(enabled),\n"
        "    description = VALUES(description)"
    )


def upgrade() -> None:
    """写入（或刷新）R01–R05 的 v1 种子规则，可重复执行。"""
    for rule in RULES:
        op.execute(_upsert_sql(rule))


def downgrade() -> None:
    """删除 R01–R05 的 v1 种子规则（仅删除种子版本，不触碰其他版本）。"""
    op.execute(
        "DELETE FROM detection_rules "
        "WHERE rule_version = 1 "
        "AND rule_code IN ('R01','R02','R03','R04','R05')"
    )
