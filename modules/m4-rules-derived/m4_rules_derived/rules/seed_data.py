"""检测规则 R01–R05 v1 种子定义（与迁移 0004_seed_rules 完全一致）。

规则定义归 M4 所有：M1 的历史迁移保留 SQL 副本，测试与规则工具从本模块读取，
保证同一口径只有一个可导入事实来源。
"""

from __future__ import annotations

from typing import Any

RULE_SEEDS: list[dict[str, Any]] = [
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

__all__ = ["RULE_SEEDS"]
