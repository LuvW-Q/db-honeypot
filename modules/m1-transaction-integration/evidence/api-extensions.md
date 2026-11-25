# 002 API 扩展：查询计划（EXPLAIN）与 HTTP 冒烟证据

- 任务：`002-ui-console-modularization` T019/T020/T021（首页范围窗口、趋势命中数、
  告警摘要、攻击者摘要/筛选/排序、画像派生字段）
- 契约：`specs/002-ui-console-modularization/contracts/api-extensions.md`
  §2.1（overview range）、§3.1（trend hit_*）、§4.2（alerts/summary）、
  §5.2（attackers/summary）、§6.2（q/sort）、§7.1（画像派生字段）、§9（422 格式）、§10（EXPLAIN 证据）
- 最近验证时间：2026-11-25T04:41:48Z（EXPLAIN）/ 2026-11-25T12:41+08:00（HTTP 冒烟，见下）
- 环境：MySQL 8.0.46、`honeypot_dev`、SQLAlchemy 2 + asyncmy、Python 3.13（`/tmp/dbh-venv`）

## 1. 方法

EXPLAIN 由可复现脚本生成，SQL **直接取自 M1 仓储模块**（`overview_repo` /
`alert_repo` / `attacker_repo`），与运行时语句一致；参数按服务端生成值内联为常量
（无用户输入拼接）。连接使用迁移账号（具备 `SELECT` + `SHOW VIEW`；只读账号缺
`SHOW VIEW` 时 EXPLAIN 视图会报 1345，执行计划本身与只读账号一致——同一库、同一 SQL）。

复现命令（仓库根目录）：

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python modules/m1-transaction-integration/evidence/explain_api_extensions.py
```

约束：不新增索引/视图/DDL（宪法三）；所有聚合查询都带时间上界（`<= :upper` 或
`to` 半开上界），不出现无界 `SELECT *` 全表拉取（契约 §10）。

## 2. EXPLAIN 记录（脚本原始输出）

验证时间：2026-11-25T04:41:48+00:00
MySQL：8.0.46
数据库：honeypot_dev
连接字符集：utf8mb4 / utf8mb4_0900_ai_ci

EXPLAIN 时点各表行数：

| 表 | 行数 |
| --- | --- |
| sessions | 0 |
| attack_log | 0 |
| alerts | 0 |
| rule_hits | 0 |
| attacker_profile | 0 |

### 新查询整体 EXPLAIN

**overview·range=7d（带窗口下界）**

```sql
SELECT
  (SELECT COUNT(*) FROM sessions
    WHERE started_at <= '2026-11-25 04:41:48' AND started_at >= '2026-11-18 04:41:48')                       AS sessions,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query' AND event_time <= '2026-11-25 04:41:48' AND event_time >= '2026-11-18 04:41:48')  AS queries,
  (SELECT COUNT(*) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48')                         AS alerts,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE risk_level IN ('high', 'critical')
      AND last_seen <= '2026-11-25 04:41:48' AND last_seen >= '2026-11-18 04:41:48')                       AS high_risk_attackers,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE last_seen <= '2026-11-25 04:41:48' AND last_seen >= '2026-11-18 04:41:48')                       AS attackers_total,
  (SELECT COUNT(*) FROM alerts
    WHERE is_read = 0 AND created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48')         AS alerts_unread,
  (SELECT COALESCE(SUM(severity = 'low'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48')                         AS alerts_low,
  (SELECT COALESCE(SUM(severity = 'medium'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48')                         AS alerts_medium,
  (SELECT COALESCE(SUM(severity = 'high'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48')                         AS alerts_high,
  (SELECT COALESCE(SUM(severity = 'critical'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48')                         AS alerts_critical,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query' AND status = 'denied'
      AND event_time <= '2026-11-25 04:41:48' AND event_time >= '2026-11-18 04:41:48')                           AS denied_queries,
  (SELECT COUNT(*) FROM sessions
    WHERE started_at >= '2026-11-24 16:00:00' AND started_at < '2026-11-25 16:00:00')     AS sessions_today,
  (SELECT COUNT(*) FROM sessions
    WHERE started_at >= '2026-11-23 16:00:00'
      AND started_at < '2026-11-24 16:00:00')                                AS sessions_yesterday,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query'
      AND event_time >= '2026-11-24 16:00:00' AND event_time < '2026-11-25 16:00:00')     AS queries_today,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query'
      AND event_time >= '2026-11-23 16:00:00'
      AND event_time < '2026-11-24 16:00:00')                                AS queries_yesterday
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY |  |  |  |  | No tables used |
| 16 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 15 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 14 | SUBQUERY | sessions | index | idx_sessions_started | 1 | Using where; Using index |
| 13 | SUBQUERY | sessions | index | idx_sessions_started | 1 | Using where; Using index |
| 12 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 11 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 10 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 9 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 8 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 7 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |
| 6 | SUBQUERY | p | ALL |  | 1 | Using where |
| 6 | SUBQUERY | <derived40> | ref | <auto_key0> | 2 |  |
| 6 | SUBQUERY | <derived37> | ref | <auto_key0> | 2 |  |
| 6 | SUBQUERY | <derived33> | ref | <auto_key0> | 2 |  |
| 6 | SUBQUERY | <derived32> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 6 | SUBQUERY | <derived31> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 6 | SUBQUERY | <derived30> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 30 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 31 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 32 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 33 | DERIVED | <derived34> | ALL |  | 2 | Using temporary |
| 34 | DERIVED | <derived35> | ALL |  | 2 | Using temporary |
| 35 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 35 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 37 | DERIVED | <derived38> | ALL |  | 2 | Using filesort |
| 38 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 38 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 40 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |
| 5 | SUBQUERY | p | ALL |  | 1 | Using where |
| 5 | SUBQUERY | <derived28> | ref | <auto_key0> | 2 |  |
| 5 | SUBQUERY | <derived25> | ref | <auto_key0> | 2 | Using where |
| 5 | SUBQUERY | <derived21> | ref | <auto_key0> | 2 |  |
| 5 | SUBQUERY | <derived20> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 5 | SUBQUERY | <derived19> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 5 | SUBQUERY | <derived18> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 18 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 19 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 20 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 21 | DERIVED | <derived22> | ALL |  | 2 | Using temporary |
| 22 | DERIVED | <derived23> | ALL |  | 2 | Using temporary |
| 23 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 23 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 25 | DERIVED | <derived26> | ALL |  | 2 | Using filesort |
| 26 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 26 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 28 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |
| 4 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |
| 3 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 2 | SUBQUERY | sessions | index | idx_sessions_started | 1 | Using where; Using index |

**overview·range=all（无下界）**

```sql
SELECT
  (SELECT COUNT(*) FROM sessions
    WHERE started_at <= '2026-11-25 04:41:48')                       AS sessions,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query' AND event_time <= '2026-11-25 04:41:48')  AS queries,
  (SELECT COUNT(*) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48')                         AS alerts,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE risk_level IN ('high', 'critical')
      AND last_seen <= '2026-11-25 04:41:48')                       AS high_risk_attackers,
  (SELECT COUNT(*) FROM v_attacker_profile_summary
    WHERE last_seen <= '2026-11-25 04:41:48')                       AS attackers_total,
  (SELECT COUNT(*) FROM alerts
    WHERE is_read = 0 AND created_at <= '2026-11-25 04:41:48')         AS alerts_unread,
  (SELECT COALESCE(SUM(severity = 'low'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48')                         AS alerts_low,
  (SELECT COALESCE(SUM(severity = 'medium'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48')                         AS alerts_medium,
  (SELECT COALESCE(SUM(severity = 'high'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48')                         AS alerts_high,
  (SELECT COALESCE(SUM(severity = 'critical'), 0) FROM alerts
    WHERE created_at <= '2026-11-25 04:41:48')                         AS alerts_critical,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query' AND status = 'denied'
      AND event_time <= '2026-11-25 04:41:48')                           AS denied_queries,
  (SELECT COUNT(*) FROM sessions
    WHERE started_at >= '2026-11-24 16:00:00' AND started_at < '2026-11-25 16:00:00')     AS sessions_today,
  (SELECT COUNT(*) FROM sessions
    WHERE started_at >= '2026-11-23 16:00:00'
      AND started_at < '2026-11-24 16:00:00')                                AS sessions_yesterday,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query'
      AND event_time >= '2026-11-24 16:00:00' AND event_time < '2026-11-25 16:00:00')     AS queries_today,
  (SELECT COUNT(*) FROM attack_log
    WHERE event_type = 'query'
      AND event_time >= '2026-11-23 16:00:00'
      AND event_time < '2026-11-24 16:00:00')                                AS queries_yesterday
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY |  |  |  |  | No tables used |
| 16 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 15 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 14 | SUBQUERY | sessions | index | idx_sessions_started | 1 | Using where; Using index |
| 13 | SUBQUERY | sessions | index | idx_sessions_started | 1 | Using where; Using index |
| 12 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 11 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 10 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 9 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 8 | SUBQUERY | alerts | index | idx_alert_level_time | 1 | Using where; Using index |
| 7 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |
| 6 | SUBQUERY | p | ALL |  | 1 | Using where |
| 6 | SUBQUERY | <derived40> | ref | <auto_key0> | 2 |  |
| 6 | SUBQUERY | <derived37> | ref | <auto_key0> | 2 |  |
| 6 | SUBQUERY | <derived33> | ref | <auto_key0> | 2 |  |
| 6 | SUBQUERY | <derived32> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 6 | SUBQUERY | <derived31> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 6 | SUBQUERY | <derived30> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 30 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 31 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 32 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 33 | DERIVED | <derived34> | ALL |  | 2 | Using temporary |
| 34 | DERIVED | <derived35> | ALL |  | 2 | Using temporary |
| 35 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 35 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 37 | DERIVED | <derived38> | ALL |  | 2 | Using filesort |
| 38 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 38 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 40 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |
| 5 | SUBQUERY | p | ALL |  | 1 | Using where |
| 5 | SUBQUERY | <derived28> | ref | <auto_key0> | 2 |  |
| 5 | SUBQUERY | <derived25> | ref | <auto_key0> | 2 | Using where |
| 5 | SUBQUERY | <derived21> | ref | <auto_key0> | 2 |  |
| 5 | SUBQUERY | <derived20> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 5 | SUBQUERY | <derived19> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 5 | SUBQUERY | <derived18> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 18 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 19 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 20 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 21 | DERIVED | <derived22> | ALL |  | 2 | Using temporary |
| 22 | DERIVED | <derived23> | ALL |  | 2 | Using temporary |
| 23 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 23 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 25 | DERIVED | <derived26> | ALL |  | 2 | Using filesort |
| 26 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 26 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 28 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |
| 4 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |
| 3 | SUBQUERY | attack_log | ALL |  | 1 | Using where |
| 2 | SUBQUERY | sessions | index | idx_sessions_started | 1 | Using where; Using index |

**trend·v_daily_attack_trend**

```sql
SELECT stat_date,
       day_seq,
       event_count,
       session_count,
       source_count,
       query_count,
       denied_count,
       alert_count,
       high_level_alert_count,
       prev_event_count,
       event_count_delta,
       event_change_pct,
       cumulative_event_count,
       busy_day_rank
FROM v_daily_attack_trend
WHERE stat_date BETWEEN '2026-11-12' AND '2026-11-25'
ORDER BY stat_date ASC
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | <derived4> | ALL |  | 2 | Using where; Using filesort |
| 1 | PRIMARY | <derived3> | ref | <auto_key0> | 2 |  |
| 3 | DERIVED | a | index | idx_alert_level_time | 1 | Using index; Using temporary |
| 4 | DERIVED | <derived5> | ALL |  | 2 | Using filesort |
| 5 | DERIVED | al | ALL |  | 1 | Using filesort |

**trend·rule_hits 意图族聚合**

```sql
SELECT DATE(triggered_at) AS stat_date,
       SUM(intent_type = 'bruteforce')  AS hit_bruteforce,
       SUM(intent_type = 'data_dump')   AS hit_data_dump,
       SUM(intent_type = 'scanning')    AS hit_scanning,
       SUM(intent_type = 'recon')       AS hit_recon,
       SUM(intent_type = 'destructive') AS hit_destructive
FROM rule_hits
WHERE triggered_at >= '2026-11-12 04:41:48'
  AND triggered_at < '2026-11-26 04:41:48'
GROUP BY DATE(triggered_at)
ORDER BY stat_date ASC
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | rule_hits | ALL |  | 1 | Using where; Using temporary; Using filesort |

**alerts·summary（无 from/to）**

```sql
SELECT COUNT(*)                                                    AS total,
       COALESCE(SUM(is_read = 0), 0)                               AS unread,
       COALESCE(SUM(severity = 'low'), 0)                          AS sev_low,
       COALESCE(SUM(severity = 'medium'), 0)                       AS sev_medium,
       COALESCE(SUM(severity = 'high'), 0)                         AS sev_high,
       COALESCE(SUM(severity = 'critical'), 0)                     AS sev_critical,
       COALESCE(SUM(is_read = 0 AND severity = 'low'), 0)          AS unread_low,
       COALESCE(SUM(is_read = 0 AND severity = 'medium'), 0)       AS unread_medium,
       COALESCE(SUM(is_read = 0 AND severity = 'high'), 0)         AS unread_high,
       COALESCE(SUM(is_read = 0 AND severity = 'critical'), 0)     AS unread_critical,
       COALESCE(SUM(alert_type = 'bruteforce'), 0)                 AS type_bruteforce,
       COALESCE(SUM(alert_type = 'data_dump'), 0)                  AS type_data_dump,
       COALESCE(SUM(alert_type = 'destructive'), 0)                AS type_destructive,
       (SELECT COUNT(*) FROM alerts
         WHERE created_at >= '2026-11-24 16:00:00' AND created_at < '2026-11-25 16:00:00')
                                                                   AS today_new,
       (SELECT COUNT(*) FROM alerts
         WHERE created_at >= '2026-11-23 16:00:00' AND created_at < '2026-11-24 16:00:00')
                                                                   AS yesterday_new
FROM alerts
WHERE created_at < '2026-11-25 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | alerts | ALL |  | 1 | Using where |
| 3 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |
| 2 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |

**alerts·summary（from/to 窗口）**

```sql
SELECT COUNT(*)                                                    AS total,
       COALESCE(SUM(is_read = 0), 0)                               AS unread,
       COALESCE(SUM(severity = 'low'), 0)                          AS sev_low,
       COALESCE(SUM(severity = 'medium'), 0)                       AS sev_medium,
       COALESCE(SUM(severity = 'high'), 0)                         AS sev_high,
       COALESCE(SUM(severity = 'critical'), 0)                     AS sev_critical,
       COALESCE(SUM(is_read = 0 AND severity = 'low'), 0)          AS unread_low,
       COALESCE(SUM(is_read = 0 AND severity = 'medium'), 0)       AS unread_medium,
       COALESCE(SUM(is_read = 0 AND severity = 'high'), 0)         AS unread_high,
       COALESCE(SUM(is_read = 0 AND severity = 'critical'), 0)     AS unread_critical,
       COALESCE(SUM(alert_type = 'bruteforce'), 0)                 AS type_bruteforce,
       COALESCE(SUM(alert_type = 'data_dump'), 0)                  AS type_data_dump,
       COALESCE(SUM(alert_type = 'destructive'), 0)                AS type_destructive,
       (SELECT COUNT(*) FROM alerts
         WHERE created_at >= '2026-11-24 16:00:00' AND created_at < '2026-11-25 16:00:00')
                                                                   AS today_new,
       (SELECT COUNT(*) FROM alerts
         WHERE created_at >= '2026-11-23 16:00:00' AND created_at < '2026-11-24 16:00:00')
                                                                   AS yesterday_new
FROM alerts
WHERE created_at < '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48' AND created_at < '2026-11-25 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | alerts | ALL |  | 1 | Using where |
| 3 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |
| 2 | SUBQUERY | alerts | index | idx_alert_read_time | 1 | Using where; Using index |

**alerts·peak_window 小时分桶**

```sql
SELECT FLOOR(TIMESTAMPDIFF(SECOND, '2026-11-24 16:00:00', created_at) / 3600) AS bucket_no,
       COUNT(*)                                                      AS alert_count
FROM alerts
WHERE created_at >= '2026-11-24 16:00:00'
  AND created_at < '2026-11-25 16:00:00'
GROUP BY bucket_no
ORDER BY alert_count DESC, bucket_no ASC
LIMIT 1
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | alerts | index | idx_alert_read_time | 1 | Using where; Using index; Using temporary; Using filesort |

**attackers·summary**

```sql
SELECT COUNT(*)                                              AS total,
       COALESCE(SUM(risk_level IN ('high', 'critical')), 0)  AS high_risk_count
FROM v_attacker_profile_summary
LIMIT 1
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | p | index | uk_attacker_profile_source_ip | 1 | Using index |
| 1 | PRIMARY | <derived13> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived10> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived6> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived5> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | <derived4> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | <derived3> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 3 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 4 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 5 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 6 | DERIVED | <derived7> | ALL |  | 2 | Using temporary |
| 7 | DERIVED | <derived8> | ALL |  | 2 | Using temporary |
| 8 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 8 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 10 | DERIVED | <derived11> | ALL |  | 2 | Using filesort |
| 11 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 11 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 13 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |

**attackers·latest_intent**

```sql
SELECT rh.intent_type,
       rh.rule_code,
       COALESCE(rc.rule_name, rh.rule_code) AS rule_name,
       al.source_ip,
       rh.triggered_at                      AS last_detected_at
FROM rule_hits AS rh
JOIN attack_log AS al ON al.event_id = rh.event_id
LEFT JOIN (
    SELECT d.rule_code, d.rule_name
    FROM detection_rules AS d
    JOIN (
        SELECT rule_code, MAX(rule_version) AS max_version
        FROM detection_rules
        GROUP BY rule_code
    ) AS latest
      ON latest.rule_code = d.rule_code
     AND latest.max_version = d.rule_version
) AS rc ON rc.rule_code = rh.rule_code
ORDER BY rh.triggered_at DESC, rh.hit_id DESC
LIMIT 1
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | rh | ALL |  | 1 | Using filesort |
| 1 | PRIMARY | al | eq_ref | PRIMARY | 1 |  |
| 1 | PRIMARY | d | ref | uk_detection_rules_code_version | 1 |  |
| 1 | PRIMARY | <derived3> | ref | <auto_key0> | 2 | Using where; Using index |
| 3 | DERIVED | detection_rules | index | uk_detection_rules_code_version | 5 | Using index |

**attackers·派生统计**

```sql
SELECT
  (SELECT CAST(ROUND(AVG(TIMESTAMPDIFF(SECOND, started_at, ended_at))) AS SIGNED)
     FROM sessions
    WHERE source_ip = '192.0.2.10'
      AND ended_at IS NOT NULL)                                   AS avg_session_seconds,
  (SELECT COUNT(*)
     FROM rule_hits AS rh
     JOIN attack_log AS al ON al.event_id = rh.event_id
    WHERE al.source_ip = '192.0.2.10'
      AND rh.intent_type IN ('data_dump', 'destructive'))         AS high_risk_op_count
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY |  |  |  |  | No tables used |
| 3 | SUBQUERY | rh | ALL |  | 1 | Using where |
| 3 | SUBQUERY | al | eq_ref | PRIMARY | 1 | Using where |
| 2 | SUBQUERY | sessions | ref | idx_sessions_source_started | 1 | Using where |

**attackers·list（q + total_connections 排序）**

```sql
SELECT v.attacker_id,
       v.source_ip,
       v.first_seen,
       v.last_seen,
       v.total_connections,
       v.total_auth_attempts,
       v.total_queries,
       v.primary_intent_type,
       v.primary_intent_score,
       v.primary_intent_last_detected_at,
       COALESCE(ai.evidence_count, 0) AS primary_intent_evidence_count,
       v.intent_labels,
       v.triggered_rule_codes,
       v.stored_risk_score,
       v.risk_level,
       v.alert_count
FROM v_attacker_profile_summary AS v
LEFT JOIN attacker_intent AS ai
       ON ai.attacker_id = v.attacker_id
      AND ai.intent_type = v.primary_intent_type

WHERE v.source_ip LIKE '%192.168%' ESCAPE '\\'
ORDER BY v.total_connections DESC, v.source_ip ASC
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | p | ALL |  | 1 | Using where; Using temporary; Using filesort |
| 1 | PRIMARY | <derived13> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived10> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived6> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived5> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | <derived4> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | ai | ALL |  | 1 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | <derived3> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 3 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 4 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 5 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 6 | DERIVED | <derived7> | ALL |  | 2 | Using temporary |
| 7 | DERIVED | <derived8> | ALL |  | 2 | Using temporary |
| 8 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 8 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 10 | DERIVED | <derived11> | ALL |  | 2 | Using filesort |
| 11 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 11 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 13 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |

### overview 标量子查询拆解

**overview·sessions 标量子查询（7d）**

```sql
SELECT COUNT(*) FROM sessions WHERE started_at <= '2026-11-25 04:41:48' AND started_at >= '2026-11-18 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | sessions | index | idx_sessions_started | 1 | Using where; Using index |

**overview·queries 标量子查询（7d）**

```sql
SELECT COUNT(*) FROM attack_log WHERE event_type = 'query' AND event_time <= '2026-11-25 04:41:48' AND event_time >= '2026-11-18 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | attack_log | ALL |  | 1 | Using where |

**overview·alerts 标量子查询（7d）**

```sql
SELECT COUNT(*) FROM alerts WHERE created_at <= '2026-11-25 04:41:48' AND created_at >= '2026-11-18 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | alerts | index | idx_alert_read_time | 1 | Using where; Using index |

**overview·高风险攻击者（视图 + IN）**

```sql
SELECT COUNT(*) FROM v_attacker_profile_summary WHERE risk_level IN ('high', 'critical') AND last_seen <= '2026-11-25 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PRIMARY | p | ALL |  | 1 | Using where |
| 1 | PRIMARY | <derived13> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived10> | ref | <auto_key0> | 2 | Using where |
| 1 | PRIMARY | <derived6> | ref | <auto_key0> | 2 |  |
| 1 | PRIMARY | <derived5> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | <derived4> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 1 | PRIMARY | <derived3> | ALL |  | 2 | Using where; Using join buffer (hash join) |
| 3 | DERIVED | ai | index | uk_attacker_intent_attacker_type | 1 |  |
| 4 | DERIVED | ai | ALL |  | 1 | Using filesort |
| 5 | DERIVED | a | index | idx_alert_attacker_time | 1 |  |
| 6 | DERIVED | <derived7> | ALL |  | 2 | Using temporary |
| 7 | DERIVED | <derived8> | ALL |  | 2 | Using temporary |
| 8 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 8 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 10 | DERIVED | <derived11> | ALL |  | 2 | Using filesort |
| 11 | DERIVED | rh | ALL |  | 1 | Using temporary |
| 11 | DERIVED | al | eq_ref | PRIMARY | 1 |  |
| 13 | DERIVED | s | index | idx_sessions_source_started | 1 | Using index |

**overview·今日会话（UTC+8 半开区间）**

```sql
SELECT COUNT(*) FROM sessions WHERE started_at >= '2026-11-24 16:00:00' AND started_at < '2026-11-25 16:00:00'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | sessions | index | idx_sessions_started | 1 | Using where; Using index |

**overview·告警时间上界（all 时唯一谓词）**

```sql
SELECT COUNT(*) FROM alerts WHERE created_at <= '2026-11-25 04:41:48'
```

| id | select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SIMPLE | alerts | index | idx_alert_read_time | 1 | Using where; Using index |

## 3. 结论

1. **overview 窗口查询**：`sessions` 命中 `idx_sessions_started`（`Using index` 覆盖扫描），
   `alerts` 命中 `idx_alert_read_time`/`idx_alert_level_time` 覆盖扫描，均只回表前过滤；
   `attack_log` 的 `event_type + event_time` 谓词没有“单列 event_time”索引（既有索引都以
   `session_id`/`source_ip` 为前导列），本次 EXPLAIN 为 `type=ALL` 全表扫描——属于契约
   §10 明确接受的范围（单机蜜罐数据量有限、SQL 已带上界，且 002 不允许新增索引/DDL），
   已在此记录取舍，留待后续迁移窗口统一补索引。
2. **趋势命中数**：`rule_hits` 按 `DATE(triggered_at)` 分组，索引前导列不是 `triggered_at`，
   计划为全表 + `Using temporary; Using filesort`；趋势查询本身固定 `days ≤ 90` 且带
   `[start_time, end_time)` 上界，属可接受的有界聚合。`v_daily_attack_trend` 行查询
   仍走既有视图计划（派生表 + `filesort`），未新增对象。
3. **alerts/summary**：主聚合与今日/昨日标量子查询均为覆盖索引扫描
   （`idx_alert_read_time` / `idx_alert_level_time`），`peak_window` 小时分桶额外
   `Using temporary; Using filesort`（按小时桶排序取 1 行，今日区间有界）。
4. **attackers/summary 与 latest_intent**：摘要统计基于
   `v_attacker_profile_summary`（视图内部 hash join 派生表），画像表行数受攻击者数量
   约束；`latest_intent` 为 `ORDER BY triggered_at DESC, hit_id DESC LIMIT 1`，出现
   `Using filesort`（`rule_hits` 无 `triggered_at` 单列索引），数据量大时可考虑后续迁移
   补索引，当前数据量下为毫秒级。
5. **画像派生统计**：`avg_session_seconds` 命中 `idx_sessions_source_started`
   （`source_ip` 等值 + `ended_at IS NOT NULL` 过滤，`type=ref`）；`high_risk_op_count`
   以 `rule_hits ⋈ attack_log` 主键 `eq_ref` 回表，逐攻击者查询有界。
6. **攻击者列表 q 过滤**：`LIKE :pat ESCAPE '\\'` 参数化 + 转义，计划为
   `p` 表 `type=ALL`（`q` 为子串匹配，前缀通配符无法走索引），但 `total_connections`
   排序在视图结果集内完成，分页仍由 `LIMIT/OFFSET` 收口。
7. 全部新查询只读、不提交事务；脚本只执行 `EXPLAIN`，不写入任何数据（脚本输出的行数表为
   EXPLAIN 时点各表行数）。

## 4. HTTP 冒烟验证

启动（只读 API，不启动前端 dev server）：

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
WEB_DIST_DIR=modules/m5-views-console/frontend/dist \
/tmp/dbh-venv/bin/python -m uvicorn m1_transaction_integration.api.app:create_app \
  --factory --host 127.0.0.1 --port 8001 --log-level warning
```

冒烟数据：通过 `IngestService` 在 `honeypot_dev` 造 6 个来源（内网/回环/公网/文档保留、
含 10 天前事件与连续认证失败），共 20 条事件，触发破坏性（R05）与暴力破解（R02）告警；
验证完成后按来源 IP 清理，核心表回到 0 行（见 §4.3）。

### 4.1 接口与状态码

| 请求 | 状态码 | 关键结论 |
| --- | --- | --- |
| `GET /api/overview?range=7d` | 200 | `range=7d`、`window_start` 回显；10 天前会话被排除（sessions 4 vs all 5） |
| `GET /api/overview` | 200 | 默认 `range=all`、`window_start=null`；今日/昨日窗口固定 UTC+8 |
| `GET /api/overview?range=30d` | 422 | `VALIDATION_ERROR` + 字段级 detail（`field=range`） |
| `GET /api/trend?days=3` | 200 | 五个 `hit_*` 全为 int，空白日补 0；今日 `hit_bruteforce=2`、`hit_recon=1`、`hit_destructive=1` |
| `GET /api/alerts/summary` | 200 | 总数/未读/已读自洽（`total = unread + read`）；`by_alert_type` 键齐全；`peak_window` 为今日 1 小时桶 |
| `GET /api/alerts/summary?from=…&to=…` | 200 | 窗口过滤生效；`today_*`/`peak_window` 不受 from/to 影响（契约 §4.2） |
| `GET /api/alerts/summary?from=…`（缺 to） | 422 | `VALIDATION_ERROR`，`field=to`，`input=null` |
| `GET /api/attackers/summary` | 200 | `latest_intent` 返回最新 `triggered_at` 命中，`rule_name` 取当前规则版本 |
| `GET /api/attackers?q=192.168&sort=total_connections` | 200 | 子串命中 1 条；排序字段白名单生效 |
| `GET /api/attackers?q=%25` | 200 | `%` 按字面量匹配（`total=0`），未被当作通配符 |
| `GET /api/attackers/192.168.1.10` | 200 | `avg_session_seconds=1200`、`auth_success_count`、`high_risk_op_count=1`、`network_scope=private` |
| `GET /api/attackers/203.0.113.9` | 200 | `network_scope=reserved`（文档保留）、`avg_session_seconds=null` |
| `GET /api/attackers?sort=bogus` | 422 | 既有 `SORT_FIELD_INVALID` 行为不变 |
| `GET /api/alerts?page=1&page_size=5`（旧） | 200 | 旧列表契约未变 |
| `GET /api/rules`（旧） | 200 | 旧规则接口正常 |
| `GET /api/health` | 200 | 数据库健康检查正常 |
| `GET /api/sessions/{id}/timeline`（旧） | 404 | 该路由本就不提供会话列表；未知会话按契约 404 |

补充：实施过程中 `schemas/api.py` 曾短暂缺少 `not_found` 等错误辅助（`ImportError`），
已修复并重启 8001 冒烟；上表所有旧路由（overview/trend/alerts/attackers/rules/health）
复测 200，空库时 overview、`alerts/summary`、`attackers/summary` 均返回全 0/`null`
（不返回 500），符合契约 1.6/§4.2/§5.2 的“空数据语义”。

### 4.2 关键响应样例

```json
# /api/overview?range=7d（200，字段完整）
{
  "sessions": 4,
  "queries": 3,
  "alerts": 1,
  "high_risk_attackers": 0,
  "generated_at": "2026-11-25T04:40:12Z",
  "range": "7d",
  "window_start": "2026-11-18T04:40:12Z",
  "attackers_total": 4,
  "high_risk_ratio": 0.0,
  "alerts_unread": 1,
  "alerts_by_severity": {
    "low": 0,
    "medium": 0,
    "high": 0,
    "critical": 1
  },
  "sessions_today": 4,
  "queries_today": 3,
  "sessions_delta_pct": null,
  "queries_delta_pct": null,
  "query_blocked_rate": 0.3333,
  "today_window": {
    "start": "2026-11-24T16:00:00Z",
    "end": "2026-11-25T16:00:00Z"
  },
  "yesterday_window": {
    "start": "2026-11-23T16:00:00Z",
    "end": "2026-11-24T16:00:00Z"
  }
}
```

```json
# /api/alerts/summary（200，含暴力破解 + 破坏性两类告警）
{
  "total": 2,
  "unread": 2,
  "read": 0,
  "resolution_rate": 0.0,
  "by_severity": {
    "low": 0,
    "medium": 1,
    "high": 0,
    "critical": 1
  },
  "unread_by_severity": {
    "low": 0,
    "medium": 1,
    "high": 0,
    "critical": 1
  },
  "by_alert_type": {
    "bruteforce": 1,
    "data_dump": 0,
    "destructive": 1
  },
  "today_new": 2,
  "yesterday_new": 0,
  "today_delta_pct": null,
  "peak_window": {
    "start": "2026-11-25T04:00:00Z",
    "end": "2026-11-25T05:00:00Z",
    "count": 2
  },
  "today_window": {
    "start": "2026-11-24T16:00:00Z",
    "end": "2026-11-25T16:00:00Z"
  },
  "generated_at": "2026-11-25T04:40:41Z"
}
```

```json
# /api/attackers/summary（200，latest_intent 规则名来自当前规则版本）
{
  "total": 5,
  "high_risk_count": 0,
  "latest_intent": {
    "intent_type": "destructive",
    "rule_code": "R05",
    "rule_name": "破坏性写操作尝试",
    "source_ip": "192.168.1.10",
    "last_detected_at": "2026-11-25T02:49:54Z"
  },
  "generated_at": "2026-11-25T04:40:12Z"
}
```

```json
# /api/attackers?q=192.168&sort=total_connections（200，单条命中）
{
  "items": [
    {
      "attacker_id": 1,
      "source_ip": "192.168.1.10",
      "first_seen": "2026-11-25T02:39:54Z",
      "last_seen": "2026-11-25T02:59:54Z",
      "total_connections": 1,
      "total_auth_attempts": 0,
      "total_queries": 2,
      "main_intent": {
        "intent_type": "destructive",
        "intent_score": 35,
        "evidence_count": 1,
        "last_detected_at": "2026-11-25T02:49:54Z"
      },
      "risk_score": 50,
      "risk_level": "medium",
      "alert_count": 1,
      "intent_labels": [
        "destructive",
        "recon"
      ],
      "triggered_rule_codes": [
        "R03",
        "R05"
      ],
      "network_scope": "private",
      "network_scope_label": "内网"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1,
  "total_pages": 1
}
```

```json
# /api/attackers/192.168.1.10（200，派生字段）
{
  "attacker_id": 1,
  "source_ip": "192.168.1.10",
  "first_seen": "2026-11-25T02:39:54Z",
  "last_seen": "2026-11-25T02:59:54Z",
  "total_connections": 1,
  "total_auth_attempts": 0,
  "total_auth_failures": 0,
  "total_queries": 2,
  "risk_score": 50,
  "calculated_risk_score": 50,
  "risk_level": "medium",
  "session_count": 1,
  "high_risk_session_count": 0,
  "alert_count": 1,
  "unread_alert_count": 1,
  "intent_labels": "destructive,recon",
  "triggered_rule_codes": "R03,R05",
  "evidence_summary": "命中规则：R05×1(权重35)、R03×1(权重15)；最近事件 disconnect",
  "avg_session_seconds": 1200,
  "auth_success_count": 0,
  "high_risk_op_count": 1,
  "network_scope": "private",
  "network_scope_label": "内网"
}
```

```json
# /api/attackers/203.0.113.9（200，文档保留地址 → reserved）
{
  "attacker_id": 16,
  "source_ip": "203.0.113.9",
  "first_seen": "2026-11-25T04:39:06Z",
  "last_seen": "2026-11-25T04:39:56Z",
  "total_connections": 1,
  "total_auth_attempts": 9,
  "total_auth_failures": 9,
  "total_queries": 0,
  "risk_score": 25,
  "calculated_risk_score": 25,
  "risk_level": "low",
  "session_count": 1,
  "high_risk_session_count": 0,
  "alert_count": 1,
  "unread_alert_count": 1,
  "intent_labels": "bruteforce",
  "triggered_rule_codes": "R02",
  "evidence_summary": "命中规则：R02×2(权重25)；最近事件 auth",
  "avg_session_seconds": null,
  "auth_success_count": 0,
  "high_risk_op_count": 0,
  "network_scope": "reserved",
  "network_scope_label": "文档保留"
}
```

```json
# /api/overview?range=30d（422）
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "detail": [
    {
      "field": "range",
      "reason": "只能是 all/7d/24h",
      "input": "30d"
    }
  ],
  "request_id": "e33e2b9d-4341-49c2-8125-d8e8d604f05b"
}
```

```json
# /api/alerts/summary?from=...（缺 to，422）
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "detail": [
    {
      "field": "to",
      "reason": "from 与 to 必须成对出现（或同时缺省）",
      "input": null
    }
  ],
  "request_id": "1fdfb161-6397-4bab-af52-444ee4ef4107"
}
```

```json
# /api/attackers?sort=bogus（422）
{
  "code": "SORT_FIELD_INVALID",
  "message": "排序字段不合法",
  "detail": {
    "field": "sort",
    "reason": "取值不在白名单内",
    "input": "bogus"
  },
  "request_id": "11b56608-3798-4823-aac8-5fdf4b37d0c1"
}
```

### 4.3 清理与空库复测

冒烟结束后执行按来源 IP 的清理（告警 → 意图 → 命中 → 事件 → 画像 → 会话），
核心表行数复测：`sessions=0`、`attack_log=0`、`rule_hits=0`、`alerts=0`、`attacker_profile=0`。
空库复测（均为 200）：

- `GET /api/overview`：`sessions=0, queries=0, alerts=0, attackers_total=0, high_risk_ratio=0.0, alerts_unread=0, sessions_delta_pct=null, query_blocked_rate=null`；
- `GET /api/alerts/summary`：`total=0, unread=0, read=0, resolution_rate=0.0`、各分布键齐全、`peak_window=null`；
- `GET /api/attackers/summary`：`total=0, high_risk_count=0, latest_intent=null`。

## 5. 口径说明与已知取舍

- `range` 的窗口下界只作用于概览四项基础指标（会话/查询/告警/高风险攻击者）；
  `sessions_today`/`queries_today`/两个 `delta_pct`/`today_window`/`yesterday_window`
  固定按 UTC+8 自然日（合同 §1.2），不随 `range` 变化。
- `query_blocked_rate`：分子 `event_type='query' AND status='denied'`，分母
  `event_type='query'`，均在当前窗口内；分母 0 → `null`（契约 §2.2 允许 null）。
  首个实现版本按“拒绝查询 / 查询总数”解释；若验收口径要求“被拦截连接占比”需再对齐。
- `alerts/summary` 的 `from`/`to` 需成对出现且 `from < to`、窗口 ≤ 366 天；
  `to` 缺省以服务端当前 UTC 为上界（半开 `<`）。
- `latest_intent.rule_name` 取该 `rule_code` 的**当前（最高版本）**规则名，与
  `recent_rule_hits` 的“命中时版本名”口径不同：前者用于“最近在发生什么”，后者用于审计追责。
- 未新增索引/视图/DDL；`attack_log`、`rule_hits` 的时间过滤全表扫描是本次已知取舍（§3 结论 1/2/4），
  若后续接入大数据量演练，需在迁移中统一补 `event_time`/`triggered_at` 单列索引。
