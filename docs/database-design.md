# 数据库设计说明书（database-design.md）

| 项目 | 内容 |
| --- | --- |
| 文档用途 | 汇总数据库蜜罐系统的 ER 关系、11 表关系模式、关键约束、4 个分析视图、索引、事务与账号权限，作为建表评审与答辩“数据库技术”部分的说明材料 |
| 目标读者 | 数据库设计评审者、迁移编写者、后端实现者、答辩讲解人 |
| 权威上游 | `specs/001-database-honeypot/data-model.md`（完整数据字典、逐列注释、全部 SQL、需求映射） |
| 与其他文档的关系 | 本文是 data-model 的**摘要与导读**，不重复全部字段；系统分层与部署见 [architecture.md](architecture.md)，验证步骤见 [test-plan.md](test-plan.md)，索引实测见 [explain-indexes.md](explain-indexes.md) |
| 实测环境 | MySQL 8.0.46（Docker，`dbhoneypot-mysql`），库 `honeypot_dev`，字符集 `utf8mb4` / `utf8mb4_0900_ai_ci`，会话时区 `+00:00` |

> **口径说明**：数据模型最初按 MySQL 8.4 LTS 编写，实际运行镜像为 `mysql:8.0`（实测 8.0.46）。
> 本项目用到的 `CHECK`（≥8.0.16）、CTE、窗口函数、生成列、不可见索引语法在 8.0.46 均可用；
> 两者的差异不影响本设计，但答辩时应说明实际版本。本文出现的计数为 2026-11-19 实测快照。

---

## 1. 设计目标与原则

### 1.1 设计目标

1. **数据库是项目核心**：会话、事件、规则、命中、意图、画像、告警、诱饵与审计都有明确关系模型；
2. **判断可追溯**：每个意图和风险分都能沿 `画像 → 意图 → 命中 → 事件 → 会话` 回到原始证据；
3. **约束优先**：主键、外键、唯一、CHECK 在数据库层表达，不依赖应用“自觉”；
4. **可演示**：4 个视图承载 JOIN/CTE/窗口函数，复合索引支撑 EXPLAIN 对比，事务与幂等可现场验证；
5. **安全最小化**：诱饵数据与观测数据同库不同表；四类账号职责分离；审计表仅追加。

### 1.2 规范化（3NF）

| 关系 | 是否满足 3NF | 说明 |
| --- | --- | --- |
| `sessions` / `attack_log` | 是 | 每个非键列只依赖主键；`attack_log.source_ip` 是从会话复制的**受控反规范化快照**，动机是避免规则窗口查询反复 JOIN（见 data-model 7.4），并在写入事务内保持一致 |
| `attacker_profile` / `attacker_intent` | 是 | 画像不保存多值意图列表；意图一行一条，用 `(attacker_id,intent_type)` 唯一约束表达“每攻击者每意图一行” |
| `detection_rules` / `rule_hits` | 是 | 规则参数只描述单条规则内部阈值，不塞入多值业务实体；命中保存版本/权重/意图**快照**，属可解释性要求，不是重复存储业务实体 |
| `alerts` | 是 | 去重键、首末时间、次数、最新命中编号都是告警自身属性；证据通过 `latest_hit_id` 外键指向命中 |
| `fake_users` / `fake_orders` / `fake_config` | 是 | 诱饵展示数据独立建模，订单通过 `user_id` 引用用户，配置键唯一 |
| `audit_log` | 是 | 仅追加审计事实，不对业务表建外键，避免被 `RESTRICT` 阻塞 |

### 1.3 关键设计选择

| 选择 | 取值 | 理由 |
| --- | --- | --- |
| 数据库/引擎 | MySQL 8.0.46 / InnoDB | 事务、行锁、外键、窗口函数、CHECK 全部可用；课程环境统一 |
| 主键 | `sessions` 用业务主键 `CHAR(36)`；其余用 `BIGINT UNSIGNED AUTO_INCREMENT` | UUID 会话编号贯穿事件；日志表自增主键顺序写入且用于同时间戳稳定排序 |
| 字符集 | 库/文本列 `utf8mb4`；UUID/IP/规则编码用 `ascii` | 攻击载荷需支持任意 Unicode；标识列用 ascii 显著缩小索引 |
| 时间 | `DATETIME(6)`，全部存 UTC | 避免 `TIMESTAMP` 的 2038 上限与隐式时区转换；连接统一 `time_zone='+00:00'` |
| 外键动作 | 全部 `ON UPDATE RESTRICT ON DELETE RESTRICT` | 证据不可重建，禁止级联删除；重置按依赖顺序显式删除 |
| 枚举 | `VARCHAR(16) + CHECK IN (...)` | 比 ENUM 更直观、可迁移、可读 |
| 生成列 | `risk_level`（VIRTUAL）、`enabled_rule_code`（STORED） | 分数—等级不漂移；同一规则至多一个启用版本 |
| 视图 | 4 个 `SQL SECURITY DEFINER` 实时聚合视图 | 控制台直接复用；不引入汇总表双写一致性问题 |

命名规范、逐列类型与 38 条 CHECK 的完整清单见 data-model 第 2、4、5 章。本文不重复抄录。

---

## 2. ER 图（11 张表）

> **权威源**：ER 模型与约束规范归 M3，图源为
> [`modules/m3-er-constraints/er/schema.mmd`](../../modules/m3-er-constraints/er/schema.mmd)
> （Mermaid，可版本管理），导出图见
> [`modules/m3-er-constraints/evidence/schema.svg`](../../modules/m3-er-constraints/evidence/schema.svg)
> 与同目录 `schema.png`。本文不再重复维护第二份 ER 图，避免与 DDL 漂移（FR-120）。
>
> 阅读约定：`||--o{` 为数据库外键保证的强制一对多；`}o..o{` 为按 `source_ip` 归集的
> **逻辑聚合**（不建外键，画像由 M4 派生）；`audit_log` 为独立仅追加表，不与业务表建外键。
> 实体清单与关系基数、约束目录见
> [`modules/m3-er-constraints/constraints/catalog.md`](../../modules/m3-er-constraints/constraints/catalog.md)。

## 3. 关系模式摘要（11 张表）

完整字段、类型、可空性、默认值、逐列中文注释见 data-model 第 4 章；这里只列用途与关键键。

| # | 表 | 用途 | 主键 | 关键外键/唯一约束 |
| --- | --- | --- | --- | --- |
| 1 | `sessions` | 会话主表：一次诱饵连接一行 | `session_id CHAR(36)` | 被 `attack_log/rule_hits/alerts` 引用 |
| 2 | `attack_log` | 标准事件表：connect/auth/query/disconnect | `event_id BIGINT` | `event_uuid` UK；`fk_log_session` |
| 3 | `attacker_profile` | 按 `source_ip` 聚合的画像（一行一来源） | `attacker_id BIGINT` | `source_ip` UK；`risk_level` 生成列 |
| 4 | `attacker_intent` | 一行一条攻击意图 | `intent_id BIGINT` | `fk_intent_profile`；`(attacker_id,intent_type)` UK |
| 5 | `detection_rules` | 规则配置：一行一条规则的一个版本 | `rule_id BIGINT` | `(rule_code,rule_version)` UK；`enabled_rule_code` UK |
| 6 | `rule_hits` | 一次规则命中，保存版本/权重/意图快照 | `hit_id BIGINT` | `fk_hit_log`（复合）、`fk_hit_session`、`fk_hit_rule`；`(event_id,rule_id,rule_version)` UK |
| 7 | `alerts` | 爆破/拖库/破坏性操作告警，按去重键收敛 | `alert_id BIGINT` | `dedup_key` UK；4 个外键（会话/画像/规则/最新命中） |
| 8 | `fake_users` | 诱饵用户（30 条种子） | `id BIGINT` | `username`、`email` UK；`password_hash` CHECK `TEST-ONLY$` |
| 9 | `fake_orders` | 诱饵订单（120 条种子，30×4） | `order_id BIGINT` | `order_no` UK；`fk_fake_orders_user` |
| 10 | `fake_config` | 看似敏感但无效的配置（5 条种子） | `config_id BIGINT` | `config_key` UK；`config_value` CHECK `TEST-ONLY` |
| 11 | `audit_log` | 关键写操作审计（仅追加） | `audit_id BIGINT` | 无业务外键；`operation/result` CHECK |

> 另有 Alembic 自带的 `alembic_version` 表，不计入 11 张业务表。实测
> `information_schema.tables` 中 `BASE TABLE` 为 12（11 + `alembic_version`），视图 4 个。

---

## 4. 关键约束

### 4.1 实测约束规模（`honeypot_dev`，2026-11-19）

| 对象 | 实测值 | 期望 | 校验 SQL |
| --- | --- | --- | --- |
| 业务表 | 11（+`alembic_version`） | 11 | `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='honeypot_dev' AND table_type='BASE TABLE'` |
| 视图 | 4 | 4 | `information_schema.views` |
| 外键 | 10 | 10 | `information_schema.referential_constraints` |
| 外键动作 | 全部 `RESTRICT/RESTRICT` | 全部 RESTRICT | 同上的 `update_rule/delete_rule` |
| CHECK 约束 | 38 | 38 | `information_schema.table_constraints WHERE constraint_type='CHECK'` |
| 唯一约束（不含主键） | 12 | 12 | 同上 `constraint_type='UNIQUE'` |
| `ascii` 列 | 24 | 按设计 | `information_schema.columns WHERE character_set_name='ascii'` |
| 会话时区 | `+00:00` | `+00:00` | `SELECT @@session.time_zone` |
| 数据库版本 | `8.0.46` | ≥8.0.16 | `SELECT VERSION()` |

### 4.2 外键清单（全部 RESTRICT）

| 子表 | 约束名 | 子列 | 父表 |
| --- | --- | --- | --- |
| `attack_log` | `fk_log_session` | `session_id` | `sessions` |
| `attacker_intent` | `fk_intent_profile` | `attacker_id` | `attacker_profile` |
| `rule_hits` | `fk_hit_log` | `event_id, session_id` | `attack_log`（复合） |
| `rule_hits` | `fk_hit_session` | `session_id` | `sessions` |
| `rule_hits` | `fk_hit_rule` | `rule_id` | `detection_rules` |
| `alerts` | `fk_alert_session` | `session_id` | `sessions` |
| `alerts` | `fk_alert_attacker` | `attacker_id` | `attacker_profile` |
| `alerts` | `fk_alert_rule` | `rule_id` | `detection_rules` |
| `alerts` | `fk_alert_latest_hit` | `latest_hit_id` | `rule_hits` |
| `fake_orders` | `fk_fake_orders_user` | `user_id` | `fake_users` |

### 4.3 唯一约束与幂等/去重

| 表 | 唯一键 | 作用 |
| --- | --- | --- |
| `attack_log` | `uk_attack_log_event_uuid(event_uuid)` | **事件幂等**：重复投递 1062，返回已有 `event_id` |
| `attack_log` | `uk_attack_log_event_session(event_id,session_id)` | 复合外键父索引，保证命中同源 |
| `attacker_profile` | `uk_attacker_profile_source_ip(source_ip)` | 一来源一画像 |
| `attacker_intent` | `uk_attacker_intent_attacker_type(attacker_id,intent_type)` | 一攻击者一意图一行 |
| `detection_rules` | `uk_detection_rules_code_version(rule_code,rule_version)` | 规则版本不可覆盖 |
| `detection_rules` | `uk_detection_rules_enabled_code(enabled_rule_code)` | 同一编码至多一个启用版本 |
| `rule_hits` | `uk_rule_hits_event_rule_version(event_id,rule_id,rule_version)` | 同一事件同版本规则不重复命中 |
| `alerts` | `uk_alerts_dedup_key(dedup_key)` | **告警去重**：`<rule_code>:<source_ip>:<UTC 日期>` |
| `fake_users` / `fake_orders` / `fake_config` | 业务唯一键 | 诱饵种子幂等导入 |

### 4.4 CHECK 约束分类（38 条）

| 类别 | 代表约束 | 作用 |
| --- | --- | --- |
| 时间自洽 | `ck_sessions_ended_after_started`、`ck_profile_seen_order`、`ck_intent_detected_order`、`ck_alert_seen_order` | 结束不早于开始；首末时间有序 |
| 分数/权重 | `ck_sessions_max_risk_score`、`ck_profile_risk_score`、`ck_intent_score`、`ck_detection_rules_risk_weight`、`ck_hit_risk_weight` | 0–100（无符号保证下界），权重 1–100 |
| 枚举 | `event_type`、`status`、`session_status`、`rule_type`、`intent_type`、`alert_type`、`severity`、`order_status`、`category`、`audit operation/result` | 只允许契约中的值 |
| 输入上限 | `ck_attack_log_sql_length`、`ck_attack_log_normalized_length` | 单条 SQL ≤ 65535 字符 |
| 安全标记 | `ck_fake_users_password_hash`、`ck_fake_config_test_only`、`ck_*_synthetic` | 强制 `TEST-ONLY` 与合成标记 |
| 逻辑一致性 | `ck_alert_read_at`（`read_at IS NULL OR is_read=1`）、`ck_alert_occurrence_count` | 已读时间与状态一致 |

### 4.5 生成列与应用层保证

| 对象 | 表达式 | 说明 |
| --- | --- | --- |
| `attacker_profile.risk_level`（VIRTUAL） | `CASE WHEN risk_score>=80 THEN 'critical' ... END` | 分数—等级永不漂移 |
| `detection_rules.enabled_rule_code`（STORED） | `CASE WHEN enabled=1 THEN rule_code ELSE NULL END` | 参与唯一索引，保证每规则最多一个启用版本 |

跨表条件（如 `attack_log.source_ip` 与会话一致、画像计数与事件计数一致）不在数据库层用触发器
实现，由写入事务复制/原子自增 + 校验 SQL 保证；理由与替代方案见 data-model 5.6、7.4、15。

---

## 5. 四个核心分析视图

| 视图 | 用途 | 查询技术 | 消费位置 |
| --- | --- | --- | --- |
| `v_session_risk_summary` | 每会话汇总事件数、认证失败、命中、告警，重算风险分并与存储值对照 | 多个 CTE 先分表聚合 + `LEFT JOIN` + `GROUP BY`；`LEAST/SUM` 计算；`GROUP_CONCAT` 规则串 | 首页会话指标、攻击者详情会话摘要、时间线头部 |
| `v_attacker_profile_summary` | 每来源画像统计、主要意图、会话数、高风险会话数、告警数 | `JOIN` + 分源聚合 + 窗口函数 `ROW_NUMBER()`（意图分数/最近时间/危害等级稳定排序）+ `GROUP_CONCAT` | 首页高风险攻击者数、攻击者列表与详情 |
| `v_daily_attack_trend` | 按 UTC 自然日汇总事件/来源/告警，给出环比、累计、繁忙排名 | CTE 日期分组 + `LAG()` 前一日 + `SUM() OVER` 累计 + `RANK()` 排名 + 告警按日 `LEFT JOIN` | 首页趋势图、`GET /api/trend` |
| `v_rule_effectiveness` | 每条规则命中次数、覆盖会话/来源、告警数、首末命中、排名 | `COUNT(DISTINCT)` + 最新版本 `JOIN` + `RANK()` 排名 | `GET /api/rules/effectiveness`、答辩“哪条规则最有效” |

### 5.1 视图设计要点

1. **两阶段聚合防放大**：日志、命中、告警先各自按自身粒度聚合，再与主表 LEFT JOIN，
   避免“多明细表 JOIN 后 GROUP BY”导致计数虚高。
2. **全部表达式列显式别名**（≤64 字符），不写 `ORDER BY`，排序交给查询侧。
3. **风险口径统一**：视图重算分与写入侧都使用“按 `rule_code` 取 `MAX(risk_weight)` 后求和并
   `LEAST(100,...)`”；`stored_*` 与 `calculated_*` 并列，便于答辩对账。
4. **主要意图稳定排序**：`intent_score DESC, last_detected_at DESC, 危害等级 DESC`；
   分数/时间相同也能得到确定结果。
5. **实时聚合不物化**：演示规模（千至万级事件）可接受，避免汇总表双写不一致。

### 5.2 可直接演示的查询

```sql
-- ① 会话风险排行
SELECT session_id, source_ip, event_count, query_count, hit_rule_codes,
       calculated_risk_score, risk_level, stored_max_risk_score, alert_count
FROM v_session_risk_summary
ORDER BY calculated_risk_score DESC, started_at DESC
LIMIT 20;

-- ② 攻击者画像
SELECT source_ip, calculated_risk_score, risk_level, primary_intent_type,
       primary_intent_score, session_count, total_queries, alert_count
FROM v_attacker_profile_summary
ORDER BY calculated_risk_score DESC, last_seen DESC
LIMIT 20;

-- ③ 每日趋势（近 14 天）
SELECT stat_date, event_count, prev_event_count, event_count_delta,
       event_change_pct, cumulative_event_count, alert_count, busy_day_rank
FROM v_daily_attack_trend
ORDER BY stat_date DESC
LIMIT 14;

-- ④ 规则效果排名
SELECT hit_rank, rule_code, rule_name, intent_type, is_enabled,
       hit_count, affected_attacker_count, alert_count, alert_per_hit_ratio
FROM v_rule_effectiveness
ORDER BY hit_rank;
```

**实测（2026-11-19 14:45 UTC）**：四条查询均成功返回。`v_session_risk_summary` 201 行、
`v_attacker_profile_summary` 1 行、`v_daily_attack_trend` 2 行、`v_rule_effectiveness` 5 行（采集时点；
随后导入 S01–S07 样本后行数会增长）。该结果与 `rule_hits` 明细一致。
完整视图 SQL 见 data-model 第 6 章与迁移 `0002_analysis_views.py`。

**视图口径限制**：`v_daily_attack_trend` 的 `LAG()` 只在“有事件的日期”之间比较，空白日不会
出现行，因此 `event_change_pct` 是“相对上一个有事件日”的变化，不是严格前一日历日；
`GET /api/trend` 在 API 层补齐连续日期并补 0 行，二者用途不同但页面以接口为准。

---

## 6. 索引、事务与幂等

### 6.1 索引

| 索引 | 列顺序 | 目标查询 | 状态 |
| --- | --- | --- | --- |
| `idx_log_session_time` | `attack_log(session_id,event_time)` | 会话时间线 | 已创建，EXPLAIN 已实测 |
| `idx_log_source_time` | `attack_log(source_ip,event_time)` | 按来源+时间窗口（R01/R02） | 已创建，EXPLAIN 已实测 |
| `idx_alert_level_time` | `alerts(severity,created_at)` | 近期高等级告警筛选 | 已创建；当前告警仅 1 行，计划为 `index` 反向扫描 |
| `idx_hit_rule_time` | `rule_hits(rule_id,created_at)` | 规则命中趋势 | 已创建 |

另有 10 条查询索引（`0003_indexes.py`）与主键/唯一/外键支撑索引，完整清单见 data-model 7.1。
索引建立前后的 `type/key/rows/耗时` 实测见 [explain-indexes.md](explain-indexes.md)。

### 6.2 事务

| 事务 | 涉及操作 | 隔离级别 | 失败处理 |
| --- | --- | --- | --- |
| T1 事件写入 | `sessions` 插入/更新 → `attack_log` 插入 → `rule_hits` → `attacker_profile` → `attacker_intent` → `alerts` → 会话计数/最高分 | `READ COMMITTED` | 整体 ROLLBACK；死锁 1213/锁超时 1205 最多重试 3 次，退避 50→200→800 ms |
| T2 告警已读 | `alerts` UPDATE + `audit_log` INSERT | `READ COMMITTED` | 单事务回滚，返回失败 |
| T3 规则版本变更 | 停用旧版本 + 插入新版本 + 审计 | `READ COMMITTED` | 回滚，旧版本保持可用 |
| T4 演示重置 | 按 `alerts → rule_hits → attack_log → attacker_intent → attacker_profile → sessions` 删除 + 审计 | `READ COMMITTED` | 整体回滚；保留规则/诱饵/审计 |

### 6.3 幂等

1. `event_uuid` 在事件生成时一次性生成，重试复用同一值；
2. 事务内直接 `INSERT attack_log`，由 `uk_attack_log_event_uuid` 唯一键裁决；冲突则回滚并
   回查已有 `event_id`，返回 `duplicate=true`；
3. 同一事件重复分析时，`uk_rule_hits_event_rule_version` 阻止重复命中，
   `ON DUPLICATE KEY UPDATE hit_id=hit_id` 空更新；
4. 告警重复触发由 `uk_alerts_dedup_key` 收敛：累加 `occurrence_count`、更新 `last_seen_at` /
   `latest_hit_id`，不新增行。

### 6.4 演示重置顺序（RESTRICT 兼容）

```sql
START TRANSACTION;
DELETE FROM alerts;
DELETE FROM rule_hits;
DELETE FROM attack_log;
DELETE FROM attacker_intent;
DELETE FROM attacker_profile;
DELETE FROM sessions;
-- 断言 detection_rules 与 fake_* 行数不变
COMMIT;
```

不使用 `TRUNCATE`（DDL 隐式提交、无法回滚）；重置实现见
[`modules/m1-transaction-integration/m1_transaction_integration/cli/reset_demo.py`](../../modules/m1-transaction-integration/m1_transaction_integration/cli/reset_demo.py)，
CLI 为 `python -m m1_transaction_integration.cli.reset_demo --yes`。

---

## 7. 账号权限矩阵（摘要）

| 对象 | `honeypot_migrate` | `honeypot_app_rw` | `honeypot_app_ro` | `honeypot_backup` |
| --- | --- | --- | --- | --- |
| 业务表（`sessions/attack_log/rule_hits/alerts/...`） | 读写 + DDL | 读写 | 只读 | 只读 |
| `detection_rules` | 读写 + DDL | S/I/U（不可删） | 只读 | 只读 |
| `audit_log` | 读写 + DDL | **仅 S/I** | 只读 | 只读 |
| `fake_users` | 读写 + DDL | 只读 | 列级 SELECT（排除 `password_hash`） | 只读 |
| 4 个视图 | S + 建视图 | 只读 | 只读 | 只读 |
| 全局特权 | 无 | 无 | 无 | 库级 `LOCK TABLES` |

完整 GRANT 语句见 data-model 11.3，实际收紧脚本为 `scripts/apply_table_grants.sh`。

**当前实例实测差异（必须如实说明）**：`db/init/01-init-databases.sh` 授予的是库级权限，
`apply_table_grants.sh` 在本实例**尚未执行**。因此 `audit_log` 仅追加、`detection_rules`
不可删除、`fake_users.password_hash` 列级隐藏这三项属于“设计已定义、实例待收紧”，
在 [test-plan.md](test-plan.md) 的权限用例中标记为待验证。

---

## 8. 迁移与回滚

| 修订 | 内容 | 关键点 |
| --- | --- | --- |
| `0001_initial_schema` | 11 张表、10 个外键、12 个唯一键、38 个 CHECK、四条规定复合索引 | 建表顺序：`sessions → attack_log → attacker_profile → attacker_intent → detection_rules → rule_hits → alerts → fake_* → audit_log` |
| `0002_analysis_views` | 4 个 `CREATE OR REPLACE SQL SECURITY DEFINER VIEW` | `downgrade` 逆序 `DROP VIEW IF EXISTS` |
| `0003_indexes` | 10 条纯查询索引 | `downgrade` 逆序 `DROP INDEX` |
| `0004_seed_rules` | R01–R05 规则种子（v1、启用） | 按 `(rule_code,rule_version)` 幂等；不参与演示重置 |

### 8.1 命令

```bash
# 仓库根执行（迁移脚本位于 M1 模块）
PYTHONPATH=.:modules/m1-transaction-integration .venv/bin/alembic upgrade head       # 建表、视图、索引、规则种子
.venv/bin/alembic current            # 查看当前修订
.venv/bin/alembic downgrade -1       # 回退一个修订（演示环境慎用；先备份）
```

### 8.2 回滚顺序

1. 先备份：`mysqldump --single-transaction --routines --triggers --events honeypot_dev > backup.sql`；
2. `0004` 回退：删除规则种子（若已被 `rule_hits` 引用，`RESTRICT` 会阻止，须先清业务数据）；
3. `0003` 回退：按创建逆序删 10 条索引；
4. `0002` 回退：逆序删 4 个视图；
5. `0001` 回退：按外键逆序删表 `audit_log → fake_config → fake_orders → fake_users →
   alerts → rule_hits → detection_rules → attacker_intent → attacker_profile → attack_log → sessions`。

演示环境优先“整库重建”而不是逐版本回滚：`DROP DATABASE` 后重新 `alembic upgrade head`，
可保证与迁移脚本一致；回滚/重建后必须重跑验证断言。

### 8.3 迁移后验证（V1–V15 摘要）

| 编号 | 断言 | 期望 |
| --- | --- | --- |
| V1–V2 | 业务表 11、视图 4 | 通过（实测 11 + alembic_version，视图 4） |
| V3 | 外键 10，动作全 RESTRICT | 通过 |
| V4 | CHECK 38 | 通过 |
| V5 | UUID/IP/规则编码列字符集/排序规则 | 通过（24 个 ascii 列） |
| V6 | `@@session.time_zone='+00:00'` | 通过 |
| V7 | 四视图可 `SELECT COUNT(*)` | 通过 |
| V8 | 规则 5、fake_users 30、fake_orders 120、fake_config 5 | 通过（实测一致） |
| V9–V15 | 非法写入被拒、外键拦截、幂等、快照一致、权限 | 见 [test-plan.md](test-plan.md)，部分待验证 |

运行验证的完整 SQL 见 data-model 12.6 与 `specs/001-database-honeypot/quickstart.md` 第 6 章。

---

## 9. 已知限制与权衡

| 限制 | 影响 | 当前处理 |
| --- | --- | --- |
| 实际版本为 MySQL 8.0.46，非设计文档写的 8.4 LTS | 少数字符集/插件默认行为不同 | 项目只用两者共有能力；答辩说明实际版本 |
| 画像与 `sessions` 无外键（按 IP 逻辑聚合） | 应用漏更新时可能短暂不一致 | 事务内更新 + 视图重算 + 校验 SQL；当前实测 `127.0.0.1` 画像计数与事件计数一致 |
| 视图实时聚合、不物化 | 数据量增大后变慢 | 课程演示规模（千至万级）可接受；页面查询带 LIMIT |
| 告警去重键含 UTC 日期 | 跨日持续攻击会产生“每日一条”告警 | 有意的业务取舍，便于按日统计 |
| `risk_level` 与视图 CASE 双处维护 | 阈值变更需同步 | 当前阈值固定为 0-29/30-59/60-79/80-100，迁移与视图均按同一口径 |
| 表级最小权限尚未在实例执行 | `audit_log`/规则删除限制未在权限层生效 | 执行 `scripts/apply_table_grants.sh honeypot_dev` 后复验 |
| 无分区/无归档/无软删除 | 日志增长后清理成本上升 | 课程范围不做；备份 + 重建 |

更完整的 18 条设计权衡见 data-model 第 15 章。

---

## 10. 相关文档

- [system architecture](architecture.md)：五层架构、数据流、部署与安全边界。
- [test-plan.md](test-plan.md)：测试矩阵、SC 映射、约束/事务/权限验证。
- [demo-script.md](demo-script.md)：数据库专项演示（外键、幂等、回滚、四视图、EXPLAIN）。
- [explain-indexes.md](explain-indexes.md)：复合索引实测记录。
- `specs/001-database-honeypot/data-model.md`：完整数据字典、全部 DDL/视图 SQL、约束矩阵、需求映射。
- `specs/001-database-honeypot/contracts/events.md`：事件字段、状态机、事务与幂等契约。
- [`modules/m1-transaction-integration/migrations/versions/`](../../modules/m1-transaction-integration/migrations/versions)：迁移唯一事实来源（`0001_initial_schema.py` … `0004_seed_rules.py`）。
- [`modules/m3-er-constraints/`](../../modules/m3-er-constraints)：ER 模型、约束目录与实测证据。
