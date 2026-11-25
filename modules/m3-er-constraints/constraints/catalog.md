# M3 完整性约束目录（catalog.md）

| 项目 | 内容 |
| --- | --- |
| 用途 | 逐表列出 `honeypot_dev` 的 PK/FK/UNIQUE/CHECK/索引与可空性，并与迁移文件逐条对账；T013/T046 的 M3 交付物 |
| 权威来源 | 迁移 `modules/m1-transaction-integration/migrations/versions/0001_initial_schema.py`（表/约束/生成列）与 `0003_indexes.py`（纯查询索引）；设计意图见 `docs/database-design.md` 第 3/4 章 |
| 实测来源 | `modules/m3-er-constraints/tools/introspect_constraints.py`（只读查询 `information_schema`），原始 JSON 见 [`evidence/constraints.json`](../evidence/constraints.json) |
| 实测环境 | MySQL **8.0.46**（容器 `dbhoneypot-mysql`），库 `honeypot_dev`，会话时区 `+00:00`，连接账号 `honeypot_app_rw`（只读元数据） |
| 采集时间 | 2026-11-25T05:22:50+00:00（UTC，JSON `meta.collected_at`；对应北京时间同日 13:22） |
| 采集命令 | `PYTHONPATH=. /tmp/dbh-venv/bin/python modules/m3-er-constraints/tools/introspect_constraints.py --out modules/m3-er-constraints/evidence/constraints.json` |
| 最近验证 | 2026-11-25（见第 7 节） |

> 本文件是 `evidence/constraints.json` 的人读版本：列类型、可空性、默认值、额外属性、约束名与子句全部来自实查，不含手抄；迁移行号来自对 0001/0003 的 `grep -n` 定位，两者一致即为“迁移与运行库未漂移”。

## 1. 事实来源与复现

1. **迁移是唯一事实来源**：`0001_initial_schema.py`（1288 行）建 11 张表、10 个外键、12 个 UNIQUE、38 个 CHECK、2 个生成列与 11 条随建表创建的索引；`0003_indexes.py`（104 行）补 10 条纯查询索引；`0002_analysis_views.py` 建 4 视图（不在本目录范围）；`0004_seed_rules.py` 只灌 R01–R05 种子，不改结构。
2. **运行库反查**：用 `tools/introspect_constraints.py` 从 `information_schema` 读取同一批元数据，与迁移声明逐条比对；差异即“漂移”，本次为 0。
3. **复现命令**（仓库根执行，`PYTHONPATH` 需含仓库根以导入 `shared`）：

```bash
PYTHONPATH=. /tmp/dbh-venv/bin/python \
  modules/m3-er-constraints/tools/introspect_constraints.py --json   # JSON 到 stdout
PYTHONPATH=. /tmp/dbh-venv/bin/python \
  modules/m3-er-constraints/tools/introspect_constraints.py \
  --out modules/m3-er-constraints/evidence/constraints.json         # 落盘证据
```

4. **直查口径**（脚本内部执行的 SQL，可手工复核）：

```sql
-- 当前库与版本
SELECT DATABASE(), VERSION(), @@session.time_zone, @@sql_mode;
-- 表/视图清单
SELECT table_name, table_type FROM information_schema.tables
 WHERE table_schema='honeypot_dev' ORDER BY table_name;
-- 约束（PK/UNIQUE/FK/CHECK 统一在此）
SELECT table_name, constraint_name, constraint_type
  FROM information_schema.table_constraints
 WHERE table_schema='honeypot_dev' ORDER BY table_name, constraint_type, constraint_name;
-- 外键动作（全 RESTRICT 的实测依据）
SELECT constraint_name, table_name, referenced_table_name, update_rule, delete_rule
  FROM information_schema.referential_constraints
 WHERE constraint_schema='honeypot_dev';
-- CHECK 子句原文
SELECT tc.table_name, cc.constraint_name, cc.check_clause
  FROM information_schema.table_constraints tc
  JOIN information_schema.check_constraints cc
    ON cc.constraint_schema=tc.constraint_schema AND cc.constraint_name=tc.constraint_name
 WHERE tc.table_schema='honeypot_dev' AND tc.constraint_type='CHECK';
```

## 2. 全库对账总表（实测 vs 设计期望）

| 对象 | 实测 | `docs/database-design.md` 4.1 期望 | 结论 |
| --- | --- | --- | --- |
| 业务表（BASE TABLE） | 11（另有迁移版本表 `alembic_version`） | 11 | 一致 |
| 视图 | 4 | 4 | 一致 |
| 外键 | 10 | 10 | 一致 |
| 外键动作 | 10/10 全 `RESTRICT` + `RESTRICT` | 全 RESTRICT | 一致 |
| CHECK 约束 | 38 | 38 | 一致 |
| UNIQUE 约束（不含主键） | 12 | 12 | 一致 |
| 索引（含主键/唯一支撑索引） | 45（PK 12 + UK 12 + 普通 21） | 未给总数，仅列关键索引 | 补充口径 |
| 生成列 | 2（`risk_level` VIRTUAL、`enabled_rule_code` STORED） | 2 | 一致 |
| `ascii` 字符集列 | 业务表列 18；含视图列 24 | 24 | 口径一致（文档按含视图列统计） |
| 数据行数快照 | `sessions` 214、`attack_log` 2525、`attacker_profile` 14、`attacker_intent` 11、`detection_rules` 5、`rule_hits` 11、`alerts` 8、`fake_users` 30、`fake_orders` 120、`fake_config` 5、`audit_log` 20、`alembic_version` 1（合计 2964） | 演示数据（非结构指标） | 与确定性 demo 数据基本一致（dev 库被多模块共用，时为时点快照） |

> 行数是 2026-11-25 采集时点的快照，用于证明证据来自真实库；结构断言不看行数。

## 3. 逐表目录（11 张业务表）

每表给出：列清单（类型/可空/默认值/额外属性，来自 `information_schema.columns`）、PK/UK/FK/CHECK（含迁移行号）、索引清单。`alembic_version` 是 Alembic 自带的版本表（单列 `version_num varchar(32) PK`），不计入业务表，本节不展开。

### 3.1 `sessions`

会话主表：一次诱饵连接一行。实测 **214** 行（2026-11-25），12 列，其中可空 3 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 130 起（`op.create_table`）
- 表注释：会话主表：一次诱饵连接一行，记录来源、起止时间、状态与事件计数；数据来源为捕获层的连接与断开事件

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `session_id` | `char(36)` | 否 | — | — |
| 2 | `source_ip` | `varchar(45)` | 否 | — | — |
| 3 | `source_port` | `smallint unsigned` | 是 | — | — |
| 4 | `target_service` | `varchar(64)` | 否 | `mysql-honeypot` | — |
| 5 | `client_fingerprint` | `varchar(255)` | 是 | — | — |
| 6 | `started_at` | `datetime(6)` | 否 | — | — |
| 7 | `ended_at` | `datetime(6)` | 是 | — | — |
| 8 | `session_status` | `varchar(16)` | 否 | `active` | — |
| 9 | `request_count` | `int unsigned` | 否 | `0` | — |
| 10 | `max_risk_score` | `tinyint unsigned` | 否 | `0` | — |
| 11 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 12 | `updated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6)` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`session_id`) — `0001_initial_schema.py` L210
- UK：无
- FK：无
- CHECK：`ck_sessions_ended_after_started` — ``((`ended_at` is null) or (`ended_at` >= `started_at`))`` — `0001_initial_schema.py` L218
- CHECK：`ck_sessions_max_risk_score` — ``(`max_risk_score` <= 100)`` — `0001_initial_schema.py` L220
- CHECK：`ck_sessions_source_port` — ``((`source_port` is null) or (`source_port` between 1 and 65535))`` — `0001_initial_schema.py` L217
- CHECK：`ck_sessions_status` — ``(`session_status` in ('active','closed','timeout','error'))`` — `0001_initial_schema.py` L219

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `session_id` | 是 | `0001_initial_schema.py` L210 |
| `idx_sessions_source_started` | `source_ip`, `started_at` | 否 | `0003_indexes.py` L34 |
| `idx_sessions_started` | `started_at` | 否 | `0003_indexes.py` L46 |
| `idx_sessions_status_started` | `session_status`, `started_at` | 否 | `0003_indexes.py` L40 |

### 3.2 `attack_log`

标准事件表：connect/auth/query/disconnect。实测 **2525** 行（2026-11-25），15 列，其中可空 4 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 225 起（`op.create_table`）
- 表注释：标准事件表：一次连接/认证/查询/断开一行；event_uuid 唯一约束实现采集幂等；SQL 与用户名为不可信数据，只存储不执行

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `event_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `event_uuid` | `char(36)` | 否 | — | — |
| 3 | `session_id` | `char(36)` | 否 | — | — |
| 4 | `event_type` | `varchar(16)` | 否 | — | — |
| 5 | `source_ip` | `varchar(45)` | 否 | — | — |
| 6 | `username` | `varchar(128)` | 是 | — | — |
| 7 | `credential_test_id` | `varchar(64)` | 是 | — | — |
| 8 | `sql_statement` | `mediumtext` | 是 | — | — |
| 9 | `normalized_sql` | `mediumtext` | 是 | — | — |
| 10 | `event_time` | `datetime(6)` | 否 | — | — |
| 11 | `returned_rows` | `int unsigned` | 否 | `0` | — |
| 12 | `response_ms` | `int unsigned` | 否 | `0` | — |
| 13 | `status` | `varchar(16)` | 否 | — | — |
| 14 | `payload_truncated` | `tinyint(1)` | 否 | `0` | — |
| 15 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`event_id`) — `0001_initial_schema.py` L228（`sa.Column(..., primary_key=True)`）
- UK：`uk_attack_log_event_session` (`event_id`, `session_id`) — `0001_initial_schema.py` L331-333
- UK：`uk_attack_log_event_uuid` (`event_uuid`) — `0001_initial_schema.py` L330
- FK：`fk_log_session` (`session_id`) → `sessions` (`session_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L323-328
- CHECK：`ck_attack_log_event_type` — ``(`event_type` in ('connect','auth','query','disconnect'))`` — `0001_initial_schema.py` L342
- CHECK：`ck_attack_log_normalized_length` — ``((`normalized_sql` is null) or (char_length(`normalized_sql`) <= 65535))`` — `0001_initial_schema.py` L349-351
- CHECK：`ck_attack_log_sql_length` — ``((`sql_statement` is null) or (char_length(`sql_statement`) <= 65535))`` — `0001_initial_schema.py` L345-348
- CHECK：`ck_attack_log_status` — ``(`status` in ('success','failure','denied','error'))`` — `0001_initial_schema.py` L343
- CHECK：`ck_attack_log_truncated_flag` — ``(`payload_truncated` in (0,1))`` — `0001_initial_schema.py` L352

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `event_id` | 是 | `0001_initial_schema.py` L228（`sa.Column(..., primary_key=True)`） |
| `idx_log_session_time` | `session_id`, `event_time` | 否 | `0001_initial_schema.py` L334 |
| `idx_log_source_time` | `source_ip`, `event_time` | 否 | `0001_initial_schema.py` L335 |
| `uk_attack_log_event_session` | `event_id`, `session_id` | 是 | `0001_initial_schema.py` L331-333（UNIQUE 约束的支撑索引） |
| `uk_attack_log_event_uuid` | `event_uuid` | 是 | `0001_initial_schema.py` L330（UNIQUE 约束的支撑索引） |

### 3.3 `attacker_profile`

按 source_ip 聚合的攻击者画像（一行一来源）。实测 **14** 行（2026-11-25），14 列，其中可空 1 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 357 起（`op.create_table`）
- 表注释：攻击者画像表：按来源地址聚合的画像，一行一个来源；不保存意图列表，主要意图由 v_attacker_profile_summary 计算

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `attacker_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `source_ip` | `varchar(45)` | 否 | — | — |
| 3 | `first_seen` | `datetime(6)` | 否 | — | — |
| 4 | `last_seen` | `datetime(6)` | 否 | — | — |
| 5 | `total_connections` | `int unsigned` | 否 | `0` | — |
| 6 | `total_auth_attempts` | `int unsigned` | 否 | `0` | — |
| 7 | `total_auth_failures` | `int unsigned` | 否 | `0` | — |
| 8 | `total_queries` | `int unsigned` | 否 | `0` | — |
| 9 | `risk_score` | `tinyint unsigned` | 否 | `0` | — |
| 10 | `risk_level` | `varchar(16)` | 否 | — | `VIRTUAL GENERATED` |
| 11 | `evidence_summary` | `varchar(1024)` | 是 | — | — |
| 12 | `last_calculated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 13 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 14 | `updated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6)` |

- **生成列** `risk_level`（VIRTUAL）：``(case when (`risk_score` >= 80) then 'critical' when (`risk_score` >= 60) then 'high' when (`risk_score` >= 30) then 'medium' else 'low' end)``

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`attacker_id`) — `0001_initial_schema.py` L454
- UK：`uk_attacker_profile_source_ip` (`source_ip`) — `0001_initial_schema.py` L455
- FK：无
- CHECK：`ck_profile_risk_score` — ``(`risk_score` <= 100)`` — `0001_initial_schema.py` L463
- CHECK：`ck_profile_seen_order` — ``(`last_seen` >= `first_seen`)`` — `0001_initial_schema.py` L462

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `attacker_id` | 是 | `0001_initial_schema.py` L454 |
| `idx_profile_risk` | `risk_score`, `last_seen` | 否 | `0003_indexes.py` L52 |
| `uk_attacker_profile_source_ip` | `source_ip` | 是 | `0001_initial_schema.py` L455（UNIQUE 约束的支撑索引） |

### 3.4 `attacker_intent`

攻击意图聚合（一行一条意图）。实测 **11** 行（2026-11-25），9 列，其中可空 0 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 468 起（`op.create_table`）
- 表注释：攻击意图聚合表：一行一条攻击者意图，按画像编号与意图类型复合唯一；命中新证据时更新分数与首末识别时间

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `intent_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `attacker_id` | `bigint unsigned` | 否 | — | — |
| 3 | `intent_type` | `varchar(16)` | 否 | — | — |
| 4 | `intent_score` | `tinyint unsigned` | 否 | `0` | — |
| 5 | `evidence_count` | `int unsigned` | 否 | `0` | — |
| 6 | `first_detected_at` | `datetime(6)` | 否 | — | — |
| 7 | `last_detected_at` | `datetime(6)` | 否 | — | — |
| 8 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 9 | `updated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6)` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`intent_id`) — `0001_initial_schema.py` L530
- UK：`uk_attacker_intent_attacker_type` (`attacker_id`, `intent_type`) — `0001_initial_schema.py` L538-540
- FK：`fk_intent_profile` (`attacker_id`) → `attacker_profile` (`attacker_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L531-537
- CHECK：`ck_intent_detected_order` — ``(`last_detected_at` >= `first_detected_at`)`` — `0001_initial_schema.py` L552
- CHECK：`ck_intent_score` — ``(`intent_score` <= 100)`` — `0001_initial_schema.py` L551
- CHECK：`ck_intent_type` — ``(`intent_type` in ('scanning','bruteforce','recon','data_dump','destructive'))`` — `0001_initial_schema.py` L548-550

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `intent_id` | 是 | `0001_initial_schema.py` L530 |
| `idx_intent_type_score` | `intent_type`, `intent_score` | 否 | `0003_indexes.py` L58 |
| `uk_attacker_intent_attacker_type` | `attacker_id`, `intent_type` | 是 | `0001_initial_schema.py` L538-540（UNIQUE 约束的支撑索引） |

### 3.5 `detection_rules`

规则配置：一行一条规则的一个版本。实测 **5** 行（2026-11-25），13 列，其中可空 2 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 557 起（`op.create_table`）
- 表注释：检测规则配置表：一行一条规则的一个版本；分析层只执行 enabled=1 的版本，历史命中保留命中时的版本与权重快照

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `rule_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `rule_code` | `varchar(16)` | 否 | — | — |
| 3 | `rule_name` | `varchar(100)` | 否 | — | — |
| 4 | `rule_type` | `varchar(16)` | 否 | — | — |
| 5 | `intent_type` | `varchar(16)` | 否 | — | — |
| 6 | `parameters_json` | `json` | 否 | — | — |
| 7 | `risk_weight` | `tinyint unsigned` | 否 | — | — |
| 8 | `rule_version` | `smallint unsigned` | 否 | `1` | — |
| 9 | `enabled` | `tinyint(1)` | 否 | `1` | — |
| 10 | `enabled_rule_code` | `varchar(16)` | 是 | — | `STORED GENERATED` |
| 11 | `description` | `varchar(500)` | 是 | — | — |
| 12 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 13 | `updated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6)` |

- **生成列** `enabled_rule_code`（STORED）：``(case when (`enabled` = 1) then `rule_code` else NULL end)``

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`rule_id`) — `0001_initial_schema.py` L644
- UK：`uk_detection_rules_code_version` (`rule_code`, `rule_version`) — `0001_initial_schema.py` L645-647
- UK：`uk_detection_rules_enabled_code` (`enabled_rule_code`) — `0001_initial_schema.py` L648-650
- FK：无
- CHECK：`ck_detection_rules_enabled` — ``(`enabled` in (0,1))`` — `0001_initial_schema.py` L667
- CHECK：`ck_detection_rules_intent_type` — ``(`intent_type` in ('scanning','bruteforce','recon','data_dump','destructive'))`` — `0001_initial_schema.py` L662-664
- CHECK：`ck_detection_rules_risk_weight` — ``(`risk_weight` between 1 and 100)`` — `0001_initial_schema.py` L665
- CHECK：`ck_detection_rules_rule_type` — ``(`rule_type` in ('frequency','keyword','sequence','volume'))`` — `0001_initial_schema.py` L658-661
- CHECK：`ck_detection_rules_rule_version` — ``(`rule_version` >= 1)`` — `0001_initial_schema.py` L666

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `rule_id` | 是 | `0001_initial_schema.py` L644 |
| `idx_detection_rules_intent` | `intent_type`, `enabled`, `rule_code` | 否 | `0003_indexes.py` L64 |
| `uk_detection_rules_code_version` | `rule_code`, `rule_version` | 是 | `0001_initial_schema.py` L645-647（UNIQUE 约束的支撑索引） |
| `uk_detection_rules_enabled_code` | `enabled_rule_code` | 是 | `0001_initial_schema.py` L648-650（UNIQUE 约束的支撑索引） |

### 3.6 `rule_hits`

规则命中：保存命中时的版本/权重/意图快照。实测 **11** 行（2026-11-25），11 列，其中可空 0 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 672 起（`op.create_table`）
- 表注释：规则命中表：一次命中一行，保存命中时的规则版本、权重与意图快照；与攻击日志、会话、规则构成可回溯证据链

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `hit_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `event_id` | `bigint unsigned` | 否 | — | — |
| 3 | `session_id` | `char(36)` | 否 | — | — |
| 4 | `rule_id` | `bigint unsigned` | 否 | — | — |
| 5 | `rule_code` | `varchar(16)` | 否 | — | — |
| 6 | `intent_type` | `varchar(16)` | 否 | — | — |
| 7 | `rule_version` | `smallint unsigned` | 否 | — | — |
| 8 | `risk_weight` | `tinyint unsigned` | 否 | — | — |
| 9 | `evidence_summary` | `varchar(1024)` | 否 | — | — |
| 10 | `triggered_at` | `datetime(6)` | 否 | — | — |
| 11 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`hit_id`) — `0001_initial_schema.py` L743
- UK：`uk_rule_hits_event_rule_version` (`event_id`, `rule_id`, `rule_version`) — `0001_initial_schema.py` L766-768
- FK：`fk_hit_log` (`event_id`, `session_id`) → `attack_log` (`event_id`, `session_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L745-751
- FK：`fk_hit_rule` (`rule_id`) → `detection_rules` (`rule_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L759-765
- FK：`fk_hit_session` (`session_id`) → `sessions` (`session_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L752-758
- CHECK：`ck_hit_intent_type` — ``(`intent_type` in ('scanning','bruteforce','recon','data_dump','destructive'))`` — `0001_initial_schema.py` L779-781
- CHECK：`ck_hit_risk_weight` — ``(`risk_weight` between 1 and 100)`` — `0001_initial_schema.py` L782
- CHECK：`ck_hit_rule_version` — ``(`rule_version` >= 1)`` — `0001_initial_schema.py` L783

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `hit_id` | 是 | `0001_initial_schema.py` L743 |
| `idx_hit_event_session` | `event_id`, `session_id` | 否 | `0001_initial_schema.py` L769 |
| `idx_hit_rule_time` | `rule_id`, `created_at` | 否 | `0001_initial_schema.py` L770 |
| `idx_hit_session_time` | `session_id`, `triggered_at` | 否 | `0001_initial_schema.py` L771 |
| `uk_rule_hits_event_rule_version` | `event_id`, `rule_id`, `rule_version` | 是 | `0001_initial_schema.py` L766-768（UNIQUE 约束的支撑索引） |

### 3.7 `alerts`

告警：按 dedup_key 收敛，重复触发累加次数。实测 **8** 行（2026-11-25），18 列，其中可空 1 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 788 起（`op.create_table`）
- 表注释：告警表：爆破/拖库/破坏性操作首次命中生成，dedup_key 唯一约束实现同日同规则同来源去重；重复触发更新次数与最近时间

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `alert_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `dedup_key` | `varchar(160)` | 否 | — | — |
| 3 | `session_id` | `char(36)` | 否 | — | — |
| 4 | `attacker_id` | `bigint unsigned` | 否 | — | — |
| 5 | `rule_id` | `bigint unsigned` | 否 | — | — |
| 6 | `rule_code` | `varchar(16)` | 否 | — | — |
| 7 | `latest_hit_id` | `bigint unsigned` | 否 | — | — |
| 8 | `alert_type` | `varchar(16)` | 否 | — | — |
| 9 | `severity` | `varchar(8)` | 否 | — | — |
| 10 | `title` | `varchar(200)` | 否 | — | — |
| 11 | `evidence_summary` | `varchar(1024)` | 否 | — | — |
| 12 | `first_seen_at` | `datetime(6)` | 否 | — | — |
| 13 | `last_seen_at` | `datetime(6)` | 否 | — | — |
| 14 | `occurrence_count` | `int unsigned` | 否 | `1` | — |
| 15 | `is_read` | `tinyint(1)` | 否 | `0` | — |
| 16 | `read_at` | `datetime(6)` | 是 | — | — |
| 17 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 18 | `updated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6)` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`alert_id`) — `0001_initial_schema.py` L904
- UK：`uk_alerts_dedup_key` (`dedup_key`) — `0001_initial_schema.py` L933
- FK：`fk_alert_attacker` (`attacker_id`) → `attacker_profile` (`attacker_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L912-918
- FK：`fk_alert_latest_hit` (`latest_hit_id`) → `rule_hits` (`hit_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L926-932
- FK：`fk_alert_rule` (`rule_id`) → `detection_rules` (`rule_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L919-925
- FK：`fk_alert_session` (`session_id`) → `sessions` (`session_id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L905-911
- CHECK：`ck_alert_is_read` — ``(`is_read` in (0,1))`` — `0001_initial_schema.py` L957
- CHECK：`ck_alert_occurrence_count` — ``(`occurrence_count` >= 1)`` — `0001_initial_schema.py` L956
- CHECK：`ck_alert_read_at` — ``((`read_at` is null) or (`is_read` = 1))`` — `0001_initial_schema.py` L958
- CHECK：`ck_alert_seen_order` — ``(`last_seen_at` >= `first_seen_at`)`` — `0001_initial_schema.py` L955
- CHECK：`ck_alert_severity` — ``(`severity` in ('low','medium','high','critical'))`` — `0001_initial_schema.py` L952-954
- CHECK：`ck_alert_type` — ``(`alert_type` in ('bruteforce','data_dump','destructive'))`` — `0001_initial_schema.py` L948-951

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `alert_id` | 是 | `0001_initial_schema.py` L904 |
| `idx_alert_attacker_time` | `attacker_id`, `created_at` | 否 | `0001_initial_schema.py` L936 |
| `idx_alert_latest_hit` | `latest_hit_id` | 否 | `0001_initial_schema.py` L937 |
| `idx_alert_level_time` | `severity`, `created_at` | 否 | `0001_initial_schema.py` L934 |
| `idx_alert_read_time` | `is_read`, `created_at` | 否 | `0003_indexes.py` L76 |
| `idx_alert_rule` | `rule_id` | 否 | `0001_initial_schema.py` L940 |
| `idx_alert_session_time` | `session_id`, `created_at` | 否 | `0001_initial_schema.py` L935 |
| `idx_alert_type_time` | `alert_type`, `created_at` | 否 | `0003_indexes.py` L70 |
| `uk_alerts_dedup_key` | `dedup_key` | 是 | `0001_initial_schema.py` L933（UNIQUE 约束的支撑索引） |

### 3.8 `fake_users`

诱饵用户（30 条种子）。实测 **30** 行（2026-11-25），8 列，其中可空 0 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 963 起（`op.create_table`）
- 表注释：诱饵用户表：完全虚构的展示数据，仅用于诱饵层返回；password_hash 为不可用伪哈希，检查约束强制 TEST-ONLY$ 前缀

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `username` | `varchar(64)` | 否 | — | — |
| 3 | `email` | `varchar(120)` | 否 | — | — |
| 4 | `phone` | `varchar(32)` | 否 | — | — |
| 5 | `password_hash` | `varchar(120)` | 否 | — | — |
| 6 | `display_name` | `varchar(64)` | 否 | — | — |
| 7 | `is_synthetic` | `tinyint(1)` | 否 | `1` | — |
| 8 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`id`) — `0001_initial_schema.py` L1017
- UK：`uk_fake_users_email` (`email`) — `0001_initial_schema.py` L1019
- UK：`uk_fake_users_username` (`username`) — `0001_initial_schema.py` L1018
- FK：无
- CHECK：`ck_fake_users_password_hash` — ``(`password_hash` like 'TEST-ONLY$%')`` — `0001_initial_schema.py` L1026
- CHECK：`ck_fake_users_synthetic` — ``(`is_synthetic` = 1)`` — `0001_initial_schema.py` L1027

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `id` | 是 | `0001_initial_schema.py` L1017 |
| `uk_fake_users_email` | `email` | 是 | `0001_initial_schema.py` L1019（UNIQUE 约束的支撑索引） |
| `uk_fake_users_username` | `username` | 是 | `0001_initial_schema.py` L1018（UNIQUE 约束的支撑索引） |

### 3.9 `fake_orders`

诱饵订单（120 条种子）。实测 **120** 行（2026-11-25），9 列，其中可空 1 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 1032 起（`op.create_table`）
- 表注释：诱饵订单表：完全虚构的业务数据，含 120 条种子记录用于构造大结果集；仅用于诱饵层展示，不参与检测

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `order_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `order_no` | `varchar(32)` | 否 | — | — |
| 3 | `user_id` | `bigint unsigned` | 否 | — | — |
| 4 | `amount` | `decimal(12,2)` | 否 | — | — |
| 5 | `currency` | `char(3)` | 否 | `CNY` | — |
| 6 | `order_status` | `varchar(16)` | 否 | `paid` | — |
| 7 | `remark` | `varchar(200)` | 是 | — | — |
| 8 | `is_synthetic` | `tinyint(1)` | 否 | `1` | — |
| 9 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`order_id`) — `0001_initial_schema.py` L1094
- UK：`uk_fake_orders_order_no` (`order_no`) — `0001_initial_schema.py` L1102
- FK：`fk_fake_orders_user` (`user_id`) → `fake_users` (`id`)；ON UPDATE RESTRICT / ON DELETE RESTRICT — `0001_initial_schema.py` L1095-1101
- CHECK：`ck_fake_orders_amount` — ``(`amount` >= 0)`` — `0001_initial_schema.py` L1110
- CHECK：`ck_fake_orders_status` — ``(`order_status` in ('pending','paid','shipped','cancelled','refunded'))`` — `0001_initial_schema.py` L1112-1114
- CHECK：`ck_fake_orders_synthetic` — ``(`is_synthetic` = 1)`` — `0001_initial_schema.py` L1115

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `order_id` | 是 | `0001_initial_schema.py` L1094 |
| `idx_fake_orders_user` | `user_id`, `created_at` | 否 | `0001_initial_schema.py` L1103 |
| `uk_fake_orders_order_no` | `order_no` | 是 | `0001_initial_schema.py` L1102（UNIQUE 约束的支撑索引） |

### 3.10 `fake_config`

诱饵配置（5 条种子）。实测 **5** 行（2026-11-25），8 列，其中可空 1 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 1120 起（`op.create_table`）
- 表注释：诱饵配置表：看似敏感但完全无效的配置项；检查约束强制 config_value 以 TEST-ONLY 开头，禁止真实凭据入库

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `config_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `config_key` | `varchar(64)` | 否 | — | — |
| 3 | `config_value` | `varchar(512)` | 否 | — | — |
| 4 | `category` | `varchar(32)` | 否 | — | — |
| 5 | `description` | `varchar(200)` | 是 | — | — |
| 6 | `is_invalid` | `tinyint(1)` | 否 | `1` | — |
| 7 | `created_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 8 | `updated_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6)` |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`config_id`) — `0001_initial_schema.py` L1175
- UK：`uk_fake_config_config_key` (`config_key`) — `0001_initial_schema.py` L1176
- FK：无
- CHECK：`ck_fake_config_category` — ``(`category` in ('database','mail','api','storage'))`` — `0001_initial_schema.py` L1185-1187
- CHECK：`ck_fake_config_invalid` — ``(`is_invalid` = 1)`` — `0001_initial_schema.py` L1188
- CHECK：`ck_fake_config_test_only` — ``(`config_value` like 'TEST-ONLY%')`` — `0001_initial_schema.py` L1183

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `config_id` | 是 | `0001_initial_schema.py` L1175 |
| `uk_fake_config_config_key` | `config_key` | 是 | `0001_initial_schema.py` L1176（UNIQUE 约束的支撑索引） |

### 3.11 `audit_log`

关键写操作审计（仅追加，无业务外键）。实测 **20** 行（2026-11-25），9 列，其中可空 4 列；引擎 `InnoDB`，行格式 `Dynamic`。

- 建表语句：`0001_initial_schema.py` 1193 起（`op.create_table`）
- 表注释：审计日志表：仅追加重放记录关键写操作（重置、规则变更、告警已读、导出、迁移）；业务账号仅可插入与查询，不可修改删除

| # | 列 | 类型 | 可空 | 默认值 | 额外 |
| --- | --- | --- | --- | --- | --- |
| 1 | `audit_id` | `bigint unsigned` | 否 | — | `auto_increment` |
| 2 | `occurred_at` | `datetime(6)` | 否 | `CURRENT_TIMESTAMP(6)` | `DEFAULT_GENERATED` |
| 3 | `account_name` | `varchar(64)` | 否 | — | — |
| 4 | `operation` | `varchar(32)` | 否 | — | — |
| 5 | `target_table` | `varchar(64)` | 是 | — | — |
| 6 | `target_key` | `varchar(128)` | 是 | — | — |
| 7 | `result` | `varchar(16)` | 否 | — | — |
| 8 | `detail` | `varchar(1000)` | 是 | — | — |
| 9 | `request_id` | `char(36)` | 是 | — | — |

**键与约束**（来源均为迁移文件；`information_schema` 实查结果见 `evidence/constraints.json`）

- PK：`PRIMARY` (`audit_id`) — `0001_initial_schema.py` L1252
- UK：无
- FK：无
- CHECK：`ck_audit_operation` — ``(`operation` in ('reset','rule_change','alert_ack','export','migration','manual_query','login_failed'))`` — `0001_initial_schema.py` L1260-1262
- CHECK：`ck_audit_result` — ``(`result` in ('success','failure'))`` — `0001_initial_schema.py` L1263

| 索引 | 列 | 唯一 | 来源 |
| --- | --- | --- | --- |
| `PRIMARY` | `audit_id` | 是 | `0001_initial_schema.py` L1252 |
| `idx_audit_operation_time` | `operation`, `occurred_at` | 否 | `0003_indexes.py` L88 |
| `idx_audit_time` | `occurred_at` | 否 | `0003_indexes.py` L82 |

## 4. 全局约束清单（跨表汇总）

### 4.1 外键 10 条（全部 `ON UPDATE RESTRICT ON DELETE RESTRICT`）

| # | 子表 | 约束 | 子列 | 父表 | 父列 | 父列索引（子表用于校验的外键支撑索引） | 迁移来源 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `attack_log` | `fk_log_session` | `session_id` | `sessions` | `session_id` | `idx_log_session_time` | `0001_initial_schema.py` L323-328 |
| 2 | `attacker_intent` | `fk_intent_profile` | `attacker_id` | `attacker_profile` | `attacker_id` | `uk_attacker_intent_attacker_type` | `0001_initial_schema.py` L531-537 |
| 3 | `rule_hits` | `fk_hit_log` | `event_id`, `session_id` | `attack_log` | `event_id`, `session_id` | `idx_hit_event_session` | `0001_initial_schema.py` L745-751 |
| 4 | `rule_hits` | `fk_hit_rule` | `rule_id` | `detection_rules` | `rule_id` | `idx_hit_rule_time` | `0001_initial_schema.py` L759-765 |
| 5 | `rule_hits` | `fk_hit_session` | `session_id` | `sessions` | `session_id` | `idx_hit_session_time` | `0001_initial_schema.py` L752-758 |
| 6 | `alerts` | `fk_alert_attacker` | `attacker_id` | `attacker_profile` | `attacker_id` | `idx_alert_attacker_time` | `0001_initial_schema.py` L912-918 |
| 7 | `alerts` | `fk_alert_latest_hit` | `latest_hit_id` | `rule_hits` | `hit_id` | `idx_alert_latest_hit` | `0001_initial_schema.py` L926-932 |
| 8 | `alerts` | `fk_alert_rule` | `rule_id` | `detection_rules` | `rule_id` | `idx_alert_rule` | `0001_initial_schema.py` L919-925 |
| 9 | `alerts` | `fk_alert_session` | `session_id` | `sessions` | `session_id` | `idx_alert_session_time` | `0001_initial_schema.py` L905-911 |
| 10 | `fake_orders` | `fk_fake_orders_user` | `user_id` | `fake_users` | `id` | `idx_fake_orders_user` | `0001_initial_schema.py` L1095-1101 |

### 4.2 唯一约束 12 条

| # | 表 | 约束 | 列 | 迁移来源 |
| --- | --- | --- | --- | --- |
| 1 | `attack_log` | `uk_attack_log_event_session` | `event_id`, `session_id` | `0001_initial_schema.py` L331-333 |
| 2 | `attack_log` | `uk_attack_log_event_uuid` | `event_uuid` | `0001_initial_schema.py` L330 |
| 3 | `attacker_profile` | `uk_attacker_profile_source_ip` | `source_ip` | `0001_initial_schema.py` L455 |
| 4 | `attacker_intent` | `uk_attacker_intent_attacker_type` | `attacker_id`, `intent_type` | `0001_initial_schema.py` L538-540 |
| 5 | `detection_rules` | `uk_detection_rules_code_version` | `rule_code`, `rule_version` | `0001_initial_schema.py` L645-647 |
| 6 | `detection_rules` | `uk_detection_rules_enabled_code` | `enabled_rule_code` | `0001_initial_schema.py` L648-650 |
| 7 | `rule_hits` | `uk_rule_hits_event_rule_version` | `event_id`, `rule_id`, `rule_version` | `0001_initial_schema.py` L766-768 |
| 8 | `alerts` | `uk_alerts_dedup_key` | `dedup_key` | `0001_initial_schema.py` L933 |
| 9 | `fake_users` | `uk_fake_users_email` | `email` | `0001_initial_schema.py` L1019 |
| 10 | `fake_users` | `uk_fake_users_username` | `username` | `0001_initial_schema.py` L1018 |
| 11 | `fake_orders` | `uk_fake_orders_order_no` | `order_no` | `0001_initial_schema.py` L1102 |
| 12 | `fake_config` | `uk_fake_config_config_key` | `config_key` | `0001_initial_schema.py` L1176 |

### 4.3 CHECK 约束 38 条（按表）

| # | 表 | 约束 | 子句（`information_schema.check_constraints` 原文） | 迁移来源 |
| --- | --- | --- | --- | --- |
| 1 | `sessions` | `ck_sessions_ended_after_started` | ``((`ended_at` is null) or (`ended_at` >= `started_at`))`` | `0001_initial_schema.py` L218 |
| 2 | `sessions` | `ck_sessions_max_risk_score` | ``(`max_risk_score` <= 100)`` | `0001_initial_schema.py` L220 |
| 3 | `sessions` | `ck_sessions_source_port` | ``((`source_port` is null) or (`source_port` between 1 and 65535))`` | `0001_initial_schema.py` L217 |
| 4 | `sessions` | `ck_sessions_status` | ``(`session_status` in ('active','closed','timeout','error'))`` | `0001_initial_schema.py` L219 |
| 5 | `attack_log` | `ck_attack_log_event_type` | ``(`event_type` in ('connect','auth','query','disconnect'))`` | `0001_initial_schema.py` L342 |
| 6 | `attack_log` | `ck_attack_log_normalized_length` | ``((`normalized_sql` is null) or (char_length(`normalized_sql`) <= 65535))`` | `0001_initial_schema.py` L349-351 |
| 7 | `attack_log` | `ck_attack_log_sql_length` | ``((`sql_statement` is null) or (char_length(`sql_statement`) <= 65535))`` | `0001_initial_schema.py` L345-348 |
| 8 | `attack_log` | `ck_attack_log_status` | ``(`status` in ('success','failure','denied','error'))`` | `0001_initial_schema.py` L343 |
| 9 | `attack_log` | `ck_attack_log_truncated_flag` | ``(`payload_truncated` in (0,1))`` | `0001_initial_schema.py` L352 |
| 10 | `attacker_profile` | `ck_profile_risk_score` | ``(`risk_score` <= 100)`` | `0001_initial_schema.py` L463 |
| 11 | `attacker_profile` | `ck_profile_seen_order` | ``(`last_seen` >= `first_seen`)`` | `0001_initial_schema.py` L462 |
| 12 | `attacker_intent` | `ck_intent_detected_order` | ``(`last_detected_at` >= `first_detected_at`)`` | `0001_initial_schema.py` L552 |
| 13 | `attacker_intent` | `ck_intent_score` | ``(`intent_score` <= 100)`` | `0001_initial_schema.py` L551 |
| 14 | `attacker_intent` | `ck_intent_type` | ``(`intent_type` in ('scanning','bruteforce','recon','data_dump','destructive'))`` | `0001_initial_schema.py` L548-550 |
| 15 | `detection_rules` | `ck_detection_rules_enabled` | ``(`enabled` in (0,1))`` | `0001_initial_schema.py` L667 |
| 16 | `detection_rules` | `ck_detection_rules_intent_type` | ``(`intent_type` in ('scanning','bruteforce','recon','data_dump','destructive'))`` | `0001_initial_schema.py` L662-664 |
| 17 | `detection_rules` | `ck_detection_rules_risk_weight` | ``(`risk_weight` between 1 and 100)`` | `0001_initial_schema.py` L665 |
| 18 | `detection_rules` | `ck_detection_rules_rule_type` | ``(`rule_type` in ('frequency','keyword','sequence','volume'))`` | `0001_initial_schema.py` L658-661 |
| 19 | `detection_rules` | `ck_detection_rules_rule_version` | ``(`rule_version` >= 1)`` | `0001_initial_schema.py` L666 |
| 20 | `rule_hits` | `ck_hit_intent_type` | ``(`intent_type` in ('scanning','bruteforce','recon','data_dump','destructive'))`` | `0001_initial_schema.py` L779-781 |
| 21 | `rule_hits` | `ck_hit_risk_weight` | ``(`risk_weight` between 1 and 100)`` | `0001_initial_schema.py` L782 |
| 22 | `rule_hits` | `ck_hit_rule_version` | ``(`rule_version` >= 1)`` | `0001_initial_schema.py` L783 |
| 23 | `alerts` | `ck_alert_is_read` | ``(`is_read` in (0,1))`` | `0001_initial_schema.py` L957 |
| 24 | `alerts` | `ck_alert_occurrence_count` | ``(`occurrence_count` >= 1)`` | `0001_initial_schema.py` L956 |
| 25 | `alerts` | `ck_alert_read_at` | ``((`read_at` is null) or (`is_read` = 1))`` | `0001_initial_schema.py` L958 |
| 26 | `alerts` | `ck_alert_seen_order` | ``(`last_seen_at` >= `first_seen_at`)`` | `0001_initial_schema.py` L955 |
| 27 | `alerts` | `ck_alert_severity` | ``(`severity` in ('low','medium','high','critical'))`` | `0001_initial_schema.py` L952-954 |
| 28 | `alerts` | `ck_alert_type` | ``(`alert_type` in ('bruteforce','data_dump','destructive'))`` | `0001_initial_schema.py` L948-951 |
| 29 | `fake_users` | `ck_fake_users_password_hash` | ``(`password_hash` like 'TEST-ONLY$%')`` | `0001_initial_schema.py` L1026 |
| 30 | `fake_users` | `ck_fake_users_synthetic` | ``(`is_synthetic` = 1)`` | `0001_initial_schema.py` L1027 |
| 31 | `fake_orders` | `ck_fake_orders_amount` | ``(`amount` >= 0)`` | `0001_initial_schema.py` L1110 |
| 32 | `fake_orders` | `ck_fake_orders_status` | ``(`order_status` in ('pending','paid','shipped','cancelled','refunded'))`` | `0001_initial_schema.py` L1112-1114 |
| 33 | `fake_orders` | `ck_fake_orders_synthetic` | ``(`is_synthetic` = 1)`` | `0001_initial_schema.py` L1115 |
| 34 | `fake_config` | `ck_fake_config_category` | ``(`category` in ('database','mail','api','storage'))`` | `0001_initial_schema.py` L1185-1187 |
| 35 | `fake_config` | `ck_fake_config_invalid` | ``(`is_invalid` = 1)`` | `0001_initial_schema.py` L1188 |
| 36 | `fake_config` | `ck_fake_config_test_only` | ``(`config_value` like 'TEST-ONLY%')`` | `0001_initial_schema.py` L1183 |
| 37 | `audit_log` | `ck_audit_operation` | ``(`operation` in ('reset','rule_change','alert_ack','export','migration','manual_query','login_failed'))`` | `0001_initial_schema.py` L1260-1262 |
| 38 | `audit_log` | `ck_audit_result` | ``(`result` in ('success','failure'))`` | `0001_initial_schema.py` L1263 |

### 4.4 索引 45 条（构成与口径）

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 主键索引 | 12 | 11 张业务表 + `alembic_version` 各 1 |
| UNIQUE 支撑索引 | 12 | 与 4.2 的 12 条唯一约束一一对应（含生成列 `enabled_rule_code` 上的唯一索引） |
| 普通索引 | 21 | 0001 随建表创建 11 条（含 4 条规定复合索引、7 条外键/唯一支撑索引），0003 补 10 条纯查询索引 |
| **合计** | **45** | `information_schema.statistics` 中 `DISTINCT (table_name, index_name)` 实测 45 |

10 个外键的子表列全部有前缀索引支撑：9 条由普通索引承担（`idx_log_session_time`、`idx_hit_event_session`、`idx_hit_session_time`、`idx_hit_rule_time`、`idx_alert_session_time`、`idx_alert_attacker_time`、`idx_alert_rule`、`idx_alert_latest_hit`、`idx_fake_orders_user`），1 条由 `uk_attacker_intent_attacker_type`（`fk_intent_profile`）承担。

### 4.5 生成列 2 个

| 表.列 | 类型 | 表达式（实查） | 作用 | 迁移来源 |
| --- | --- | --- | --- | --- |
| `attacker_profile.risk_level` | VIRTUAL | ``(case when (`risk_score` >= 80) then 'critical' when (`risk_score` >= 60) then 'high' when (`risk_score` >= 30) then 'medium' else 'low' end)`` | 分数—等级永不漂移，视图与写入侧同口径 | `0001` L104-109（表达式常量）、L421-423（列定义） |
| `detection_rules.enabled_rule_code` | STORED | ``(case when (`enabled` = 1) then `rule_code` else NULL end)`` | 参与 `uk_detection_rules_enabled_code`，保证同一 `rule_code` 至多一个启用版本 | `0001` L112（表达式常量）、L618-620（列定义） |

### 4.6 可空性分布

| 表 | 列数 | 可空列数 | 可空列 |
| --- | --- | --- | --- |
| `sessions` | 12 | 3 | `source_port`, `client_fingerprint`, `ended_at` |
| `attack_log` | 15 | 4 | `username`, `credential_test_id`, `sql_statement`, `normalized_sql` |
| `attacker_profile` | 14 | 1 | `evidence_summary` |
| `attacker_intent` | 9 | 0 | 无 |
| `detection_rules` | 13 | 2 | `enabled_rule_code`, `description` |
| `rule_hits` | 11 | 0 | 无 |
| `alerts` | 18 | 1 | `read_at` |
| `fake_users` | 8 | 0 | 无 |
| `fake_orders` | 9 | 1 | `remark` |
| `fake_config` | 8 | 1 | `description` |
| `audit_log` | 9 | 4 | `target_table`, `target_key`, `detail`, `request_id` |

### 4.7 字符集与排序规则口径

库/文本列默认 `utf8mb4` / `utf8mb4_0900_ai_ci`；UUID、IP、规则编码等机器可读列在迁移中用 `ascii_bin`（UUID/编码）或 `ascii_general_ci`（IP）显式声明：`char(36)` 会话/事件编号、`varchar(45)` 来源地址、`varchar(16)` 规则编码、`char(3)` 币种。业务表实测 18 个 `ascii` 列；四个视图列合计再贡献 6 个，共 24，与 `docs/database-design.md` 4.1 的“24 个 ascii 列”统计口径一致。

## 5. 与 `docs/database-design.md` 的对账结论

设计文档第 2 节的 ER 图是**导读级子集**（只画业务关键列），本目录按真实库列全量展开，因此“列更多”不构成差异。以下四类需要显式说明：

1. **规则表是单表多版本**：规则配置实现在单表 `detection_rules`（一行 = 一条规则的一个版本），版本维度由 `rule_version` 列 + `uk_detection_rules_code_version` 表达，启用版本由生成列 `enabled_rule_code` + `uk_detection_rules_enabled_code` 收口；不存在独立的规则定义表或规则版本表。
2. **文档未展开的列**：多数表有 `created_at` + `updated_at` 运维列，`attack_log`/`rule_hits`/`fake_orders`/`fake_users` 只有 `created_at`，`audit_log` 用 `occurred_at` 记录操作时间；`attack_log` 另有 `normalized_sql`、`payload_truncated`、`response_ms`、`credential_test_id`，`alerts` 另有 `title`、`description`、`rule_code` 快照。均以本目录为准。
3. **`audit_log` 无外键**：设计目标是“仅追加、不被 RESTRICT 阻塞”，实测 0 个外键、0 个 UNIQUE，一致。
4. **`ascii` 列 24 vs 业务表 18**：文档统计包含视图列；业务表本体为 18，两者不矛盾（见 4.7）。

**结论：迁移声明 = 运行库实测，未发现结构漂移。** 若后续有人手工 `ALTER TABLE`，重跑第 1 节命令即可从 JSON 与本目录的差异中发现。

## 6. 约束正反样例（执行记录）

可执行 SQL 见 [`verify_constraints.sql`](verify_constraints.sql)，实跑记录与错误码见 [`../evidence/constraints-check.md`](../evidence/constraints-check.md)。覆盖：

| 样例 | 类型 | 语句 | 预期/实测错误码 |
| --- | --- | --- | --- |
| S1 | FK 反例 | `attack_log` 插入不存在的 `session_id` | 1452（8.4：1216）`fk_log_session` |
| S2 | FK 正例 | 先插合法会话再插事件 | 成功，`1/1` 行 |
| S3 | CHECK/ENUM 反例 | `sessions.session_status='hacked'` | 3819 `ck_sessions_status` |
| S4 | CHECK 反例 | `attacker_profile.risk_score=101` | 3819 `ck_profile_risk_score` |
| S5 | CHECK 正例 + 生成列 | `risk_score=80` → `risk_level='critical'` | 成功 |
| S6 | UNIQUE 反例 | 同一 `event_uuid` 重复投递 | 1062 `uk_attack_log_event_uuid` |
| S7 | UNIQUE 反例 | 同一 `source_ip` 两行画像 | 1062 `uk_attacker_profile_source_ip` |
| S8 | 无符号反例 | `total_connections=-1` | 1264 |
| S9 | FK RESTRICT 反例 | 删除仍被 `attack_log` 引用的会话 | 1451（8.4：1217）`fk_log_session` |
| — | 收尾 | 事务 `ROLLBACK` 后行数与基线一致 | `all_unchanged=1` |

## 7. 最近验证

| 日期 | 内容 | 结果 |
| --- | --- | --- |
| 2026-11-25 | `introspect_constraints.py --out evidence/constraints.json` 实跑 | 退出码 0；业务表 11、视图 4、FK 10、UK 12、CHECK 38、索引 45、生成列 2 |
| 2026-11-25 | `verify_constraints.sql` 在 `honeypot_dev` 实跑（`mysql --force`） | 7 个预期约束拒绝 + 2 个正例通过；最终 `all_unchanged=1` |
| 2026-11-25 | `schema.mmd` 由 `@mermaid-js/mermaid-cli@11` 渲染 | `evidence/schema.svg`（402 KB）生成成功 |
| 2026-11-25 | `pytest modules/m3-er-constraints/tests -q` | 见 `README.md` 最近验证 |
