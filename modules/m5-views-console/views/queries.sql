-- ============================================================================
-- M5 分析视图查询口径（Spec Kit T048）
-- ============================================================================
-- 本文件是四个核心分析视图的「口径说明书 + 可执行代表查询」：
--   1. v_session_risk_summary   —— 会话维度汇总与重算风险分
--   2. v_attacker_profile_summary —— 来源画像、主要意图与风险等级
--   3. v_daily_attack_trend     —— 按 UTC 自然日的趋势/环比/累计/繁忙排名
--   4. v_rule_effectiveness     —— 规则命中覆盖与效果排名
--
-- 视图权威定义：docs/database-design.md §5 与迁移
--   modules/m1-transaction-integration/migrations/versions/0002_analysis_views.py
-- 视图全部为 `SQL SECURITY DEFINER`、只读、无 ORDER BY（排序由查询侧决定）。
--
-- 复现（仓库根，只读账号 honeypot_app_ro，绝不写库）：
--   PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
--     modules/m4-rules-derived:modules/m5-views-console \
--     /tmp/dbh-venv/bin/python -m m5_views_console.cli.run_queries
-- 输出（真实执行结果）见 evidence/sql-ui/queries-output.txt。
--
-- 标记说明：`-- @query: <id>` 与 `-- @end` 之间为一条会被 run_queries.py
-- 抽取并实跑的代表性 SELECT；手工在 mysql 客户端里选中同样可执行。
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. v_session_risk_summary
-- ----------------------------------------------------------------------------
-- 视图名：v_session_risk_summary
-- 用途：每个会话一行，汇总事件/认证失败/查询/拒绝、规则命中编码、告警数，
--       并重算风险分与写入侧存储的 max_risk_score 并列对账。
-- 对应页面/API：
--   - 页面 #/（首页，会话 KPI 数量口径来自 sessions 表，不是本视图）
--   - 页面 #/attackers/:ip（会话摘要表 sessions[]，字段 event_count/query_count/
--     hit_rule_codes/risk_score/risk_level/alert_count 全部取自本视图）
--   - API GET /api/attackers/{ip} → `sessions[]`
--   - 趋势页头部（时间线会话计数）亦复用本视图
-- 口径：
--   - 时间窗：视图本身无时间过滤（全历史实时聚合）；页面/API 侧对
--     `started_at >= window_start` 的会话做窗口过滤（range=7d/24h 时）。
--   - 去重：rule_hits 先按 (session_id, rule_code) 取 MAX(risk_weight)，
--     同一规则多次命中只计一次权重，避免重复加分；命中编码用 GROUP_CONCAT
--     去重（GROUP BY rule_code 后拼接）。
--   - 聚合：日志/命中/告警各自按 session_id 预聚合再 LEFT JOIN，防止多明细表
--     JOIN 放大计数；`LEAST(100, SUM(权重))` 为风险分，等级阈值
--     critical ≥80 / high ≥60 / medium ≥30 / low <30。
--   - 已知限制：
--       * 视图不排序，页面分页/排序由 API 侧 ORDER BY 决定；
--       * 风险分是「会话内规则权重和」的实时重算，与写入侧存储分在正常数据下
--         一致（CLI 断言 stored_max_risk_score = calculated_risk_score）；
--       * 汇总为实时聚合、不物化，演示规模（千至万级事件）可接受。
-- @query: v_session_risk_summary
SELECT session_id,
       source_ip,
       event_count,
       connect_count,
       auth_attempt_count,
       auth_failure_count,
       query_count,
       denied_count,
       hit_rule_codes,
       calculated_risk_score,
       risk_level,
       stored_max_risk_score,
       alert_count,
       unread_alert_count,
       highest_alert_severity,
       started_at,
       last_event_at
FROM v_session_risk_summary
ORDER BY calculated_risk_score DESC, started_at DESC
LIMIT 20;
-- @end


-- ----------------------------------------------------------------------------
-- 2. v_attacker_profile_summary
-- ----------------------------------------------------------------------------
-- 视图名：v_attacker_profile_summary
-- 用途：每个来源 IP 一行，输出画像计数、主要意图（窗口函数稳定排序）、
--       意图标签串、触发规则串、重算风险分与风险等级。
-- 对应页面/API：
--   - 页面 #/ 首页：高风险攻击者 KPI（risk_level IN high/critical）、TOP5 榜单；
--   - 页面 #/attackers 攻击者列表：total / high_risk_count / 列表行；
--   - 页面 #/attackers/:ip 攻击者详情：画像卡（total_connections/total_queries/
--     session_count/risk_score/risk_level/intent_labels/triggered_rule_codes）；
--   - API GET /api/overview（high_risk_attackers、attackers_total）、
--     GET /api/attackers/summary（total、high_risk_count）、
--     GET /api/attackers、GET /api/attackers/{ip}。
-- 口径：
--   - 时间窗：视图无时间过滤；API `range` 窗口用 `last_seen >= window_start` 过滤。
--   - 去重：命中来源按 (source_ip, rule_code) 取 MAX(risk_weight) 后求和；规则串
--     与意图串均由 GROUP BY 后的 GROUP_CONCAT 生成，天然去重。
--   - 聚合：主要意图用 ROW_NUMBER() 按 intent_score DESC、last_detected_at DESC、
--     危害等级 DESC 排序取第 1 行，分数/时间相同也能得到确定结果；
--     high_risk_session_count 以会话重算分 ≥60 计。
--   - 已知限制：
--       * `intent_labels`/`triggered_rule_codes` 是逗号串，API 层负责 split；
--       * 画像计数（total_queries 等）来自写入事务对 attacker_profile 的原子自增，
--         视图不做二次重算；风险分则实时重算（stored vs calculated 并列对账）；
--       * `risk_level` 由 calculated_risk_score 派生，与 attacker_profile 的
--         生成列 risk_level 语义一致。
-- @query: v_attacker_profile_summary
SELECT source_ip,
       calculated_risk_score,
       risk_level,
       primary_intent_type,
       primary_intent_score,
       session_count,
       high_risk_session_count,
       total_connections,
       total_auth_attempts,
       total_queries,
       alert_count,
       unread_alert_count,
       intent_labels,
       triggered_rule_codes,
       first_seen,
       last_seen
FROM v_attacker_profile_summary
ORDER BY calculated_risk_score DESC, last_seen DESC
LIMIT 20;
-- @end


-- ----------------------------------------------------------------------------
-- 3. v_daily_attack_trend
-- ----------------------------------------------------------------------------
-- 视图名：v_daily_attack_trend
-- 用途：按 UTC 自然日汇总事件/会话/来源/查询/拒绝/告警与高等级告警，
--       并给出前一日环比、累计事件数、繁忙日 RANK。
-- 对应页面/API：
--   - 页面 #/ 首页「每日攻击趋势」图（数据来自 API GET /api/trend，
--     并非直接读本视图）；
--   - API GET /api/trend（取本视图再补齐连续日期 + 意图族命中）。
-- 口径：
--   - 时间窗：按 `DATE(attack_log.event_time)` / `DATE(alerts.created_at)` 的
--     UTC 自然日分组，无窗口下界；API 侧按 start_date/end_date 截取。
--   - 去重：事件/会话/来源分别 COUNT/COUNT(DISTINCT)，日志与告警先各自按日
--     聚合再 LEFT JOIN，避免告警 JOIN 放大事件计数。
--   - 聚合：`LAG(event_count)` 是「上一个有事件的日期」的差值，不是严格日历日；
--     `SUM() OVER (ORDER BY stat_date)` 为累计；`RANK() OVER (ORDER BY
--     event_count DESC)` 为繁忙排名（并列同名次）。
--   - 已知限制：
--       * 没有事件的日期不会出现行，因此 event_change_pct 是相对「上一个有
--         事件日」的变化；GET /api/trend 在 API 层补齐连续日期并补 0，
--         页面以接口序列为准（见下方「SQL != UI」）；
--       * stat_date 为 UTC 日期，页面日期标签按 UTC+8 渲染，跨日边界需注意。
-- @query: v_daily_attack_trend
SELECT stat_date,
       event_count,
       session_count,
       source_count,
       query_count,
       denied_count,
       prev_event_count,
       event_count_delta,
       event_change_pct,
       cumulative_event_count,
       busy_day_rank,
       alert_count,
       high_level_alert_count
FROM v_daily_attack_trend
ORDER BY stat_date DESC
LIMIT 14;
-- @end


-- ----------------------------------------------------------------------------
-- 4. v_rule_effectiveness
-- ----------------------------------------------------------------------------
-- 视图名：v_rule_effectiveness
-- 用途：每条规则（当前最高版本）一行，输出命中次数、覆盖会话/事件/来源数、
--       使用版本数、告警数与命中率、命中排名。
-- 对应页面/API：
--   - 页面 #/ 首页「规则命中与意图分布」环图（意图族命中量，来源
--     GET /api/rules/effectiveness）；
--   - 答辩「哪条规则最有效」问答；
--   - API GET /api/rules/effectiveness。
-- 口径：
--   - 时间窗：无窗口，统计全部历史命中/告警。
--   - 去重：`COUNT(DISTINCT session_id/event_id/source_ip/rule_version)`，
--     同一事件同版本规则的重叠命中只算一次（uk_rule_hits_event_rule_version 保证）。
--   - 聚合：规则全集取 detection_rules 每个 rule_code 的 MAX(rule_version)，
--     无命中的规则仍出现（hit_count=0）；`alert_per_hit_ratio = alert_count /
--     hit_count`（0 命中记 0.0000）；`RANK() OVER (ORDER BY hit_count DESC,
--     rule_code ASC)` 生成 hit_rank。
--   - 已知限制：
--       * 只统计「当前最高版本」规则的元数据，历史版本命中仍会计入 hit_count
--         与 used_version_count；
--       * 告警按 alerts.rule_code 关联，若告警来源规则编码不在 detection_rules
--         中则不会出现在本视图。
-- @query: v_rule_effectiveness
SELECT hit_rank,
       rule_code,
       rule_name,
       intent_type,
       is_enabled,
       current_version,
       hit_count,
       affected_session_count,
       affected_event_count,
       affected_attacker_count,
       used_version_count,
       alert_count,
       unread_alert_count,
       alert_per_hit_ratio
FROM v_rule_effectiveness
ORDER BY hit_rank;
-- @end


-- ============================================================================
-- SQL != UI：口径差异说明
-- ============================================================================
-- 数据对得上不等于页面显示同一个字符串。视图/表是「事实层」，页面是「展示层」，
-- 两者之间至少经过 API 口径、时区、格式化、分页/筛选四道转换：
--
-- 1) 时区：数据库全部保存 UTC（DATETIME，无时区）；页面统一按 UTC+8
--    (Asia/Shanghai) 展示（frontend/src/utils/format.ts）。因此同一时刻在 SQL 中
--    是 `2026-11-25 05:14:21`，页面上是 `2026-11-25 13:14:21`。
--    「今日/昨日」统计固定 UTC+8 自然日（API 契约 §1.2，窗口形如
--    16:00Z→16:00Z），不是 UTC 自然日；而 `v_daily_attack_trend.stat_date`
--    是按 UTC 自然日分组，二者不可直接互抄。
--
-- 2) 聚合口径：API `overview.queries` = `attack_log` 中 `event_type='query'`
--    的行数，不是 sessions.request_count，也不是 returned_rows 之和；
--    `overview.alerts` 是告警行数，页面第三张 KPI 卡显示的是
--    `alerts_unread`（未读数）而非 alerts 总数；`high_risk_attackers` 是
--    `risk_level IN ('high','critical')` 的来源数，阈值 ≥60，而非 ≥80。
--
-- 3) 分页/筛选：视图不写 ORDER BY、不分页，返回全集；API 侧才应用
--    `page/page_size`（page_size 上限 100）、`q/risk_level/intent/sort` 等
--    白名单参数；页面只渲染 API 返回的当前页 items，并展示 total/total_pages。
--    因此「列表有 14 个来源」与「当前页显示 1 个来源」并不矛盾。
--
-- 4) 补零/对齐：`v_daily_attack_trend` 只返回「有事件的日期」，而
--    GET /api/trend 会补齐请求区间内的连续日期并补 0 行；页面趋势图以接口
--    序列为准，直接对视图做「天数」断言会少行。
--
-- 5) 格式化：页面 `formatNumber` 用 zh-CN 千分位（1222 → `1,222`），
--    百分比 `formatPercent` 保留 1 位小数并把 0–1 比率乘 100；
--    比率字段（high_risk_ratio、resolution_rate、alert_per_hit_ratio）
--    在 SQL 里是 0–1 小数，页面上是 `7.1%` 之类的字符串。
--    核对数值时应比较 API 原始 JSON 与 SQL 原始标量，而不是比较页面文本。
--
-- 结论：清单（evidence/sql-ui/checklist.md）按「视图 SQL → SQL 结果 →
-- API JSON → 页面绑定字段/显示值」逐层记录，任一层的差异都可定位。
-- ============================================================================
