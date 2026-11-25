"""四个核心分析视图（只读聚合，SQL SECURITY DEFINER）。

修订号（Revision ID）: 0002_analysis_views
父修订（Revises）: 0001_initial_schema
创建时间（Create Date）: 2026-11-19

权威定义：`specs/001-database-honeypot/data-model.md` 第 6 章，SQL 与文档逐字一致：

- `v_session_risk_summary`：会话维度事件/命中/告警汇总 + 重算风险分；
- `v_attacker_profile_summary`：来源画像汇总 + 窗口函数稳定选主要意图；
- `v_daily_attack_trend`：按 UTC 自然日的趋势、LAG 环比、累计与繁忙排名；
- `v_rule_effectiveness`：规则命中覆盖与效果排名。

实现约定（data-model 6.1）：
- 统一 `CREATE OR REPLACE SQL SECURITY DEFINER VIEW`，不显式写 DEFINER；
- 所有表达式列显式别名且 ≤64 字符；
- 视图内不写 ORDER BY，不写索引提示；
- 多明细表先各自按自身粒度聚合再 LEFT JOIN，避免 JOIN 放大计数；
- MySQL 8.0.46 实测支持视图内 CTE 与窗口函数，未使用降级派生表写法。

`downgrade` 按创建逆序 `DROP VIEW IF EXISTS`。
"""

from collections.abc import Sequence

from alembic import op

# Alembic 修订标识
revision: str = "0002_analysis_views"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# data-model 6.2 会话风险汇总
V_SESSION_RISK_SUMMARY = """
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_session_risk_summary AS
WITH log_agg AS (
  SELECT
    al.session_id                                                 AS session_id,
    COUNT(*)                                                      AS event_count,
    SUM(CASE WHEN al.event_type = 'connect' THEN 1 ELSE 0 END)    AS connect_count,
    SUM(CASE WHEN al.event_type = 'auth' THEN 1 ELSE 0 END)       AS auth_attempt_count,
    SUM(CASE WHEN al.event_type = 'auth'
              AND al.status IN ('failure', 'denied') THEN 1 ELSE 0 END) AS auth_failure_count,
    SUM(CASE WHEN al.event_type = 'query' THEN 1 ELSE 0 END)      AS query_count,
    SUM(CASE WHEN al.status = 'denied' THEN 1 ELSE 0 END)         AS denied_count,
    CAST(SUM(al.returned_rows) AS UNSIGNED)                       AS returned_rows_total,
    MAX(al.event_time)                                            AS last_event_at
  FROM attack_log AS al
  GROUP BY al.session_id
),
hit_agg AS (
  SELECT
    rh.session_id                                                 AS session_id,
    COUNT(*)                                                      AS hit_count,
    COUNT(DISTINCT rh.rule_code)                                  AS hit_rule_count,
    MAX(rh.triggered_at)                                          AS last_hit_at
  FROM rule_hits AS rh
  GROUP BY rh.session_id
),
rule_max AS (
  SELECT
    rh.session_id                                                 AS session_id,
    rh.rule_code                                                  AS rule_code,
    MAX(rh.risk_weight)                                           AS rule_weight
  FROM rule_hits AS rh
  GROUP BY rh.session_id, rh.rule_code
),
risk_agg AS (
  SELECT
    rm.session_id                                                 AS session_id,
    LEAST(100, SUM(rm.rule_weight))                               AS calculated_risk_score,
    GROUP_CONCAT(rm.rule_code ORDER BY rm.rule_code SEPARATOR ',') AS hit_rule_codes
  FROM rule_max AS rm
  GROUP BY rm.session_id
),
alert_agg AS (
  SELECT
    a.session_id                                                  AS session_id,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.is_read = 0 THEN 1 ELSE 0 END)                AS unread_alert_count,
    MAX(CASE a.severity WHEN 'critical' THEN 4
                        WHEN 'high'     THEN 3
                        WHEN 'medium'   THEN 2
                        WHEN 'low'      THEN 1
                        ELSE 0 END)                               AS severity_rank
  FROM alerts AS a
  GROUP BY a.session_id
)
SELECT
  s.session_id                                                    AS session_id,
  s.source_ip                                                     AS source_ip,
  s.source_port                                                   AS source_port,
  s.target_service                                                AS target_service,
  s.started_at                                                    AS started_at,
  s.ended_at                                                      AS ended_at,
  s.session_status                                                AS session_status,
  s.request_count                                                 AS stored_request_count,
  COALESCE(la.event_count, 0)                                     AS event_count,
  COALESCE(la.connect_count, 0)                                   AS connect_count,
  COALESCE(la.auth_attempt_count, 0)                              AS auth_attempt_count,
  COALESCE(la.auth_failure_count, 0)                              AS auth_failure_count,
  COALESCE(la.query_count, 0)                                     AS query_count,
  COALESCE(la.denied_count, 0)                                    AS denied_count,
  COALESCE(la.returned_rows_total, 0)                             AS returned_rows_total,
  la.last_event_at                                                AS last_event_at,
  COALESCE(ha.hit_count, 0)                                       AS hit_count,
  COALESCE(ha.hit_rule_count, 0)                                  AS hit_rule_count,
  ha.last_hit_at                                                  AS last_hit_at,
  ra.hit_rule_codes                                               AS hit_rule_codes,
  COALESCE(ra.calculated_risk_score, 0)                           AS calculated_risk_score,
  CASE
    WHEN COALESCE(ra.calculated_risk_score, 0) >= 80 THEN 'critical'
    WHEN COALESCE(ra.calculated_risk_score, 0) >= 60 THEN 'high'
    WHEN COALESCE(ra.calculated_risk_score, 0) >= 30 THEN 'medium'
    ELSE 'low'
  END                                                             AS risk_level,
  s.max_risk_score                                                AS stored_max_risk_score,
  COALESCE(aa.alert_count, 0)                                     AS alert_count,
  COALESCE(aa.unread_alert_count, 0)                              AS unread_alert_count,
  CASE aa.severity_rank
    WHEN 4 THEN 'critical'
    WHEN 3 THEN 'high'
    WHEN 2 THEN 'medium'
    WHEN 1 THEN 'low'
    ELSE NULL
  END                                                             AS highest_alert_severity
FROM sessions AS s
LEFT JOIN log_agg    AS la ON la.session_id = s.session_id
LEFT JOIN hit_agg    AS ha ON ha.session_id = s.session_id
LEFT JOIN risk_agg   AS ra ON ra.session_id = s.session_id
LEFT JOIN alert_agg  AS aa ON aa.session_id = s.session_id
"""


# data-model 6.3 攻击者画像汇总
V_ATTACKER_PROFILE_SUMMARY = """
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_attacker_profile_summary AS
WITH session_agg AS (
  SELECT
    s.source_ip                                                   AS source_ip,
    COUNT(*)                                                      AS session_count,
    MIN(s.started_at)                                             AS first_session_at,
    MAX(s.started_at)                                             AS last_session_at
  FROM sessions AS s
  GROUP BY s.source_ip
),
intent_rank AS (
  SELECT
    ai.attacker_id                                                AS attacker_id,
    ai.intent_type                                                AS intent_type,
    ai.intent_score                                               AS intent_score,
    ai.evidence_count                                             AS evidence_count,
    ai.last_detected_at                                           AS last_detected_at,
    ROW_NUMBER() OVER (
      PARTITION BY ai.attacker_id
      ORDER BY ai.intent_score DESC,
               ai.last_detected_at DESC,
               CASE ai.intent_type
                 WHEN 'destructive' THEN 5
                 WHEN 'data_dump'   THEN 4
                 WHEN 'bruteforce'  THEN 3
                 WHEN 'recon'       THEN 2
                 ELSE 1
               END DESC
    )                                                             AS intent_rank_no
  FROM attacker_intent AS ai
),
intent_labels AS (
  SELECT
    ai.attacker_id                                                AS attacker_id,
    GROUP_CONCAT(ai.intent_type
                 ORDER BY ai.intent_score DESC, ai.last_detected_at DESC
                 SEPARATOR ',')                                   AS intent_labels
  FROM attacker_intent AS ai
  GROUP BY ai.attacker_id
),
hit_source AS (
  SELECT
    al.source_ip                                                  AS source_ip,
    rh.session_id                                                 AS session_id,
    rh.rule_code                                                  AS rule_code,
    rh.risk_weight                                                AS risk_weight
  FROM rule_hits AS rh
  JOIN attack_log AS al ON al.event_id = rh.event_id
),
source_rule_max AS (
  SELECT
    hs.source_ip                                                  AS source_ip,
    hs.rule_code                                                  AS rule_code,
    MAX(hs.risk_weight)                                           AS rule_weight
  FROM hit_source AS hs
  GROUP BY hs.source_ip, hs.rule_code
),
profile_risk AS (
  SELECT
    srm.source_ip                                                 AS source_ip,
    LEAST(100, SUM(srm.rule_weight))                              AS calculated_risk_score,
    GROUP_CONCAT(srm.rule_code ORDER BY srm.rule_code SEPARATOR ',') AS triggered_rule_codes
  FROM source_rule_max AS srm
  GROUP BY srm.source_ip
),
session_rule_max AS (
  SELECT
    hs.source_ip                                                  AS source_ip,
    hs.session_id                                                 AS session_id,
    hs.rule_code                                                  AS rule_code,
    MAX(hs.risk_weight)                                           AS rule_weight
  FROM hit_source AS hs
  GROUP BY hs.source_ip, hs.session_id, hs.rule_code
),
session_risk AS (
  SELECT
    srm.source_ip                                                 AS source_ip,
    srm.session_id                                                AS session_id,
    LEAST(100, SUM(srm.rule_weight))                              AS session_risk_score
  FROM session_rule_max AS srm
  GROUP BY srm.source_ip, srm.session_id
),
high_risk AS (
  SELECT
    sr.source_ip                                                  AS source_ip,
    SUM(CASE WHEN sr.session_risk_score >= 60 THEN 1 ELSE 0 END)  AS high_risk_session_count
  FROM session_risk AS sr
  GROUP BY sr.source_ip
),
alert_agg AS (
  SELECT
    a.attacker_id                                                 AS attacker_id,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.is_read = 0 THEN 1 ELSE 0 END)                AS unread_alert_count
  FROM alerts AS a
  GROUP BY a.attacker_id
)
SELECT
  p.attacker_id                                                   AS attacker_id,
  p.source_ip                                                     AS source_ip,
  p.first_seen                                                    AS first_seen,
  p.last_seen                                                     AS last_seen,
  p.total_connections                                             AS total_connections,
  p.total_auth_attempts                                           AS total_auth_attempts,
  p.total_auth_failures                                           AS total_auth_failures,
  p.total_queries                                                 AS total_queries,
  p.risk_score                                                    AS stored_risk_score,
  COALESCE(pr.calculated_risk_score, 0)                           AS calculated_risk_score,
  CASE
    WHEN COALESCE(pr.calculated_risk_score, 0) >= 80 THEN 'critical'
    WHEN COALESCE(pr.calculated_risk_score, 0) >= 60 THEN 'high'
    WHEN COALESCE(pr.calculated_risk_score, 0) >= 30 THEN 'medium'
    ELSE 'low'
  END                                                             AS risk_level,
  COALESCE(sa.session_count, 0)                                   AS session_count,
  COALESCE(hr.high_risk_session_count, 0)                         AS high_risk_session_count,
  COALESCE(aa.alert_count, 0)                                     AS alert_count,
  COALESCE(aa.unread_alert_count, 0)                              AS unread_alert_count,
  ir.intent_type                                                  AS primary_intent_type,
  ir.intent_score                                                 AS primary_intent_score,
  ir.last_detected_at                                             AS primary_intent_last_detected_at,
  COALESCE(il.intent_labels, '')                                  AS intent_labels,
  pr.triggered_rule_codes                                         AS triggered_rule_codes,
  p.evidence_summary                                              AS evidence_summary
FROM attacker_profile AS p
LEFT JOIN session_agg  AS sa ON sa.source_ip = p.source_ip
LEFT JOIN profile_risk AS pr ON pr.source_ip = p.source_ip
LEFT JOIN high_risk    AS hr ON hr.source_ip = p.source_ip
LEFT JOIN alert_agg    AS aa ON aa.attacker_id = p.attacker_id
LEFT JOIN intent_rank  AS ir ON ir.attacker_id = p.attacker_id
                             AND ir.intent_rank_no = 1
LEFT JOIN intent_labels AS il ON il.attacker_id = p.attacker_id
"""


# data-model 6.4 每日攻击趋势
V_DAILY_ATTACK_TREND = """
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_daily_attack_trend AS
WITH daily AS (
  SELECT
    DATE(al.event_time)                                           AS stat_date,
    COUNT(*)                                                      AS event_count,
    COUNT(DISTINCT al.session_id)                                 AS session_count,
    COUNT(DISTINCT al.source_ip)                                  AS source_count,
    SUM(CASE WHEN al.event_type = 'connect' THEN 1 ELSE 0 END)    AS connect_count,
    SUM(CASE WHEN al.event_type = 'auth' THEN 1 ELSE 0 END)       AS auth_attempt_count,
    SUM(CASE WHEN al.event_type = 'auth'
              AND al.status IN ('failure', 'denied') THEN 1 ELSE 0 END) AS auth_failure_count,
    SUM(CASE WHEN al.event_type = 'query' THEN 1 ELSE 0 END)      AS query_count,
    SUM(CASE WHEN al.status = 'denied' THEN 1 ELSE 0 END)         AS denied_count,
    CAST(SUM(al.returned_rows) AS UNSIGNED)                       AS returned_rows_total
  FROM attack_log AS al
  GROUP BY DATE(al.event_time)
),
daily_alert AS (
  SELECT
    DATE(a.created_at)                                            AS stat_date,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.severity IN ('high', 'critical') THEN 1 ELSE 0 END) AS high_level_alert_count
  FROM alerts AS a
  GROUP BY DATE(a.created_at)
),
daily_lag AS (
  SELECT
    d.stat_date                                                   AS stat_date,
    d.event_count                                                 AS event_count,
    d.session_count                                               AS session_count,
    d.source_count                                                AS source_count,
    d.connect_count                                               AS connect_count,
    d.auth_attempt_count                                          AS auth_attempt_count,
    d.auth_failure_count                                          AS auth_failure_count,
    d.query_count                                                 AS query_count,
    d.denied_count                                                AS denied_count,
    d.returned_rows_total                                         AS returned_rows_total,
    LAG(d.event_count) OVER (ORDER BY d.stat_date)                AS prev_event_count,
    LAG(d.session_count) OVER (ORDER BY d.stat_date)              AS prev_session_count,
    SUM(d.event_count) OVER (
      ORDER BY d.stat_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                             AS cumulative_event_count,
    ROW_NUMBER() OVER (ORDER BY d.stat_date)                      AS day_seq,
    RANK() OVER (ORDER BY d.event_count DESC)                     AS busy_day_rank
  FROM daily AS d
)
SELECT
  dl.stat_date                                                    AS stat_date,
  dl.day_seq                                                      AS day_seq,
  dl.event_count                                                  AS event_count,
  dl.session_count                                                AS session_count,
  dl.source_count                                                 AS source_count,
  dl.connect_count                                                AS connect_count,
  dl.auth_attempt_count                                           AS auth_attempt_count,
  dl.auth_failure_count                                           AS auth_failure_count,
  dl.query_count                                                  AS query_count,
  dl.denied_count                                                 AS denied_count,
  dl.returned_rows_total                                          AS returned_rows_total,
  dl.prev_event_count                                             AS prev_event_count,
  dl.event_count - dl.prev_event_count                            AS event_count_delta,
  CASE
    WHEN dl.prev_event_count IS NULL OR dl.prev_event_count = 0 THEN NULL
    ELSE ROUND((dl.event_count - dl.prev_event_count) * 100.0 / dl.prev_event_count, 2)
  END                                                             AS event_change_pct,
  dl.prev_session_count                                           AS prev_session_count,
  dl.cumulative_event_count                                       AS cumulative_event_count,
  dl.busy_day_rank                                                AS busy_day_rank,
  COALESCE(da.alert_count, 0)                                     AS alert_count,
  COALESCE(da.high_level_alert_count, 0)                          AS high_level_alert_count
FROM daily_lag AS dl
LEFT JOIN daily_alert AS da ON da.stat_date = dl.stat_date
"""


# data-model 6.5 规则效果统计
V_RULE_EFFECTIVENESS = """
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_rule_effectiveness AS
WITH latest_rule AS (
  SELECT
    d.rule_code                                                   AS rule_code,
    MAX(d.rule_version)                                           AS latest_version
  FROM detection_rules AS d
  GROUP BY d.rule_code
),
rule_current AS (
  SELECT
    d.rule_code                                                   AS rule_code,
    d.rule_id                                                     AS rule_id,
    d.rule_name                                                   AS rule_name,
    d.rule_type                                                   AS rule_type,
    d.intent_type                                                 AS intent_type,
    d.risk_weight                                                 AS risk_weight,
    d.rule_version                                                AS current_version,
    d.enabled                                                     AS is_enabled
  FROM detection_rules AS d
  JOIN latest_rule AS lr
    ON lr.rule_code = d.rule_code
   AND lr.latest_version = d.rule_version
),
hit_stats AS (
  SELECT
    rh.rule_code                                                  AS rule_code,
    COUNT(*)                                                      AS hit_count,
    COUNT(DISTINCT rh.session_id)                                 AS affected_session_count,
    COUNT(DISTINCT rh.event_id)                                   AS affected_event_count,
    COUNT(DISTINCT al.source_ip)                                  AS affected_attacker_count,
    COUNT(DISTINCT rh.rule_version)                               AS used_version_count,
    MIN(rh.triggered_at)                                          AS first_hit_at,
    MAX(rh.triggered_at)                                          AS last_hit_at
  FROM rule_hits AS rh
  JOIN attack_log AS al ON al.event_id = rh.event_id
  GROUP BY rh.rule_code
),
alert_stats AS (
  SELECT
    a.rule_code                                                   AS rule_code,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.is_read = 0 THEN 1 ELSE 0 END)                AS unread_alert_count
  FROM alerts AS a
  GROUP BY a.rule_code
),
combined AS (
  SELECT
    rc.rule_code                                                  AS rule_code,
    rc.rule_name                                                  AS rule_name,
    rc.rule_type                                                  AS rule_type,
    rc.intent_type                                                AS intent_type,
    rc.risk_weight                                                AS risk_weight,
    rc.current_version                                            AS current_version,
    rc.is_enabled                                                 AS is_enabled,
    COALESCE(hs.hit_count, 0)                                     AS hit_count,
    COALESCE(hs.affected_session_count, 0)                        AS affected_session_count,
    COALESCE(hs.affected_event_count, 0)                          AS affected_event_count,
    COALESCE(hs.affected_attacker_count, 0)                       AS affected_attacker_count,
    COALESCE(hs.used_version_count, 0)                            AS used_version_count,
    hs.first_hit_at                                               AS first_hit_at,
    hs.last_hit_at                                                AS last_hit_at,
    COALESCE(aa.alert_count, 0)                                   AS alert_count,
    COALESCE(aa.unread_alert_count, 0)                            AS unread_alert_count
  FROM rule_current AS rc
  LEFT JOIN hit_stats   AS hs ON hs.rule_code = rc.rule_code
  LEFT JOIN alert_stats AS aa ON aa.rule_code = rc.rule_code
)
SELECT
  cb.rule_code                                                    AS rule_code,
  cb.rule_name                                                    AS rule_name,
  cb.rule_type                                                    AS rule_type,
  cb.intent_type                                                  AS intent_type,
  cb.risk_weight                                                  AS risk_weight,
  cb.current_version                                              AS current_version,
  cb.is_enabled                                                   AS is_enabled,
  cb.hit_count                                                    AS hit_count,
  cb.affected_session_count                                       AS affected_session_count,
  cb.affected_event_count                                         AS affected_event_count,
  cb.affected_attacker_count                                      AS affected_attacker_count,
  cb.used_version_count                                           AS used_version_count,
  cb.first_hit_at                                                 AS first_hit_at,
  cb.last_hit_at                                                  AS last_hit_at,
  cb.alert_count                                                  AS alert_count,
  cb.unread_alert_count                                           AS unread_alert_count,
  CASE WHEN cb.hit_count = 0 THEN 0.0000
       ELSE ROUND(cb.alert_count / cb.hit_count, 4) END            AS alert_per_hit_ratio,
  RANK() OVER (ORDER BY cb.hit_count DESC, cb.rule_code ASC)       AS hit_rank
FROM combined AS cb
"""


# 视图创建顺序（无相互依赖，按 data-model 章节顺序）
VIEWS: list[tuple[str, str]] = [
    ("v_session_risk_summary", V_SESSION_RISK_SUMMARY),
    ("v_attacker_profile_summary", V_ATTACKER_PROFILE_SUMMARY),
    ("v_daily_attack_trend", V_DAILY_ATTACK_TREND),
    ("v_rule_effectiveness", V_RULE_EFFECTIVENESS),
]


def upgrade() -> None:
    """创建四个分析视图（CREATE OR REPLACE，可重复执行）。"""
    for _name, sql in VIEWS:
        op.execute(sql)


def downgrade() -> None:
    """按创建逆序删除四个视图。"""
    for name, _sql in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {name}")
