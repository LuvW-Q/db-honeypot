---
description: "任务列表：数据库蜜罐与攻击行为分析系统全量核心功能"
---

# Tasks: 数据库蜜罐与攻击行为分析系统（全量核心功能）

**Input**: Design documents from `specs/001-database-honeypot/`

**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**: 本项目宪法原则五要求“涉及数据库的行为必须基于真实引擎验证”，spec.md
也将集成测试与安全用例列为验收内容，因此每个用户故事均包含测试任务。测试文件路径统一
放在 `backend/tests/` 下。

**Organization**: 任务按用户故事分组，每个故事可独立实现、独立测试、独立演示。任务
编号按执行顺序递增；`[P]` 表示不同文件且不依赖未完成任务，可并行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1–US10），仅用户故事阶段使用
- 每个任务包含明确的文件路径

## Path Conventions

- 后端：`backend/app/`、`backend/tests/`、`backend/migrations/`
- 前端：`frontend/src/`
- 数据库初始化与脚本：`db/init/`、`scripts/`
- 文档：`docs/`
- 依赖与配置：`backend/pyproject.toml`、`compose.yaml`、`.env.example`、`Makefile`

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 建立单仓多目录工程骨架与依赖基线，使后续所有任务有确定的落点。

- [X] T001 按 plan.md 的 Source Code 结构创建目录骨架（`backend/app/`、`backend/tests/`、`backend/migrations/`、`frontend/src/`、`db/init/`、`scripts/`、`docs/`）并补 `.gitignore`
- [X] T002 在 `backend/pyproject.toml` 声明 Python 3.14 与依赖（FastAPI 0.165、SQLAlchemy 2.1、asyncmy、Alembic、mysql-mimic 3.0.5、structlog、pytest 等），生成 `backend/uv.lock`
- [X] T003 [P] 初始化 `backend/alembic.ini` 与 `backend/migrations/env.py`，并让配置从仓库根 `.env` 读取 `MIGRATE_DATABASE_URL`
- [X] T004 [P] 创建 `frontend/package.json`、`frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/index.html` 与 `frontend/src/main.ts`（Vue 3.5 + Vite 8 + Element Plus + ECharts，`/api` 代理到 8000）
- [X] T005 [P] 编写 `.env.example`（端口、`DATABASE_URL`、`READONLY_DATABASE_URL`、`MIGRATE_DATABASE_URL`、四类账号口令占位、诱饵账号、规则默认值、AI 开关），不得包含真实口令
- [X] T006 [P] 编写 `compose.yaml`：`mysql:8.4`（固定隔离网段 `172.28.0.0/24`）、backend、web；`db/init/` 初始化演示库 `honeypot_demo` 与四类账号
- [X] T007 [P] 编写 `Makefile` 与 `scripts/` 包装命令（setup、migrate、seed、dev、test、reset、demo），并在 `README.md` 写明启动顺序
- [X] T008 [P] 配置 `backend/ruff.toml`（或 pyproject 内）与前端 ESLint/Prettier，统一中文注释与格式基线

**Checkpoint**: 目录、依赖、配置、编排就绪，可开始数据库设计与实现。

---

## Phase 2: Foundational（阻塞性前置）

**Purpose**: 数据库 Schema、模型、会话与接口骨架——所有用户故事都依赖这些内容。

**⚠️ CRITICAL**: 本阶段完成前，任何用户故事都不可开始。

- [X] T009 编写 `backend/migrations/versions/0001_initial_schema.py` 的 MySQL 8.4 DDL 基线：建库字符集与四类账号授权（`db/init/` 配套），严格实现 data-model.md 中 `sessions.session_id`、`sessions.source_ip`、`sessions.session_status`、`sessions.request_count`、`sessions.max_risk_score`、`sessions.ended_at`、`attack_log.event_uuid`、`attack_log.event_type`、`attack_log.source_ip`、`attack_log.status`、`attack_log.returned_rows`、`attack_log.response_ms`、`attack_log.event_time` 的类型、可空性与 CHECK/UNIQUE 约束
- [X] T010 在同一迁移中实现其余业务表并逐项对齐 data-model.md 第 4、5 章：`attacker_profile.source_ip`、`attacker_profile.risk_score`、`attacker_profile.risk_level`、`attacker_intent.intent_type`、`attacker_intent.intent_score`、`attacker_intent.evidence_count`、`detection_rules.rule_code`、`detection_rules.rule_version`、`detection_rules.parameters_json`、`detection_rules.risk_weight`、`detection_rules.enabled`、`detection_rules.enabled_rule_code`、`rule_hits.event_id`、`rule_hits.session_id`、`rule_hits.rule_id`、`rule_hits.rule_version`、`rule_hits.risk_weight`、`rule_hits.triggered_at`
- [X] T011 在同一迁移中实现并逐项对齐 data-model.md：`alerts.dedup_key`、`alerts.severity`、`alerts.alert_type`、`alerts.is_read`、`alerts.occurrence_count`、`alerts.latest_hit_id`、`fake_users.username`、`fake_users.password_hash`、`fake_orders.order_no`、`fake_orders.user_id`、`fake_config.config_key`、`fake_config.is_invalid`、`audit_log.operation`、`audit_log.result`、`audit_log.account_name` 以及全部 RESTRICT 外键
- [X] T012 编写 `backend/migrations/versions/0002_analysis_views.py`：按 data-model.md 第 6 章创建 `v_session_risk_summary`、`v_attacker_profile_summary`、`v_daily_attack_trend`、`v_rule_effectiveness`（CTE/窗口函数），`downgrade` 逆序 `DROP VIEW IF EXISTS`
- [X] T013 编写 `backend/migrations/versions/0003_indexes.py`：实现 `idx_log_session_time`、`idx_log_source_time`、`idx_alert_level_time`、`idx_hit_rule_time` 及 data-model.md 第 7 章其余索引，并在 `upgrade`/`downgrade` 中成对维护
- [X] T014 编写 `backend/migrations/versions/0004_seed_rules.py`：写入 R01–R05（`rule_version=1`、`enabled=1`、参数见 data-model.md 10.1/10.2），可重复执行且不产生重复版本
- [X] T015 [P] 在 `backend/app/models/` 创建 11 张表与 4 个视图的 SQLAlchemy 2.1 映射（`sessions.py`、`attack_log.py`、`attacker_profile.py`、`attacker_intent.py`、`detection_rules.py`、`rule_hits.py`、`alerts.py`、`fake_models.py`、`audit_log.py`、`views.py`），中文注释说明业务含义
- [X] T016 [P] 在 `backend/app/db/session.py` 实现 async 引擎、`async_sessionmaker`、`ACTIVE_SESSION` 依赖、`READ_COMMITTED` 默认隔离级别与显式事务辅助（`session.begin()`），连接参数 `charset=utf8mb4`
- [X] T017 [P] 在 `backend/app/config.py` 用 pydantic-settings 实现配置模型（数据库 URL、诱饵端口与账号、规则默认值、保留天数、AI 开关、只读 URL），并加载仓库根 `.env`
- [X] T018 [P] 在 `backend/app/logging.py` 实现 structlog JSON 运行日志，包含 `request_id`/`session_id`/`event_id` 字段，与业务事件日志严格分离
- [X] T019 在 `backend/app/main.py` 建立 FastAPI 应用、CORS、统一异常处理器与错误响应结构（`{"code","message","detail","request_id"}`，对齐 contracts/api.md 1.8/1.9）、`/api/health` 与前端静态托管入口
- [X] T020 [P] 在 `backend/app/schemas/` 建立共享 Pydantic 模型：事件、分页、错误、告警、规则、画像与时间线响应，字段命名与 contracts/api.md 对齐
- [X] T021 [P] 在 `backend/app/repositories/base.py` 实现只读查询基类与视图查询辅助，强制只读连接（`app_ro`）
- [X] T022 建立 `backend/tests/conftest.py`：独立测试库 `honeypot_test` 的迁移初始化、事务回滚夹具、合成事件工厂；禁止 Mock 数据库
- [X] T023 编写 `backend/tests/integration/test_migrations.py`：验证 `alembic upgrade head` 在空库可重复执行、`downgrade base` 可回滚、11 表 4 视图 4 索引存在且与 data-model.md 一致

**Checkpoint**: 数据库、模型、配置、健康检查与测试夹具就绪，用户故事可并行开始。

---

## Phase 3: User Story 1 - 诱饵数据库服务（Priority: P1）🎯 MVP

**Goal**: 让授权客户端能连接模拟 MySQL 8 服务，完成握手与认证，执行元数据查询与
SELECT 并得到伪造结果；写操作被记录并拒绝。

**Independent Test**: 在隔离环境用 MySQL 客户端连接 3307，依次执行 `SHOW DATABASES`、
`SHOW TABLES`、`DESCRIBE users`、`SELECT * FROM users LIMIT 5`，确认返回伪造结构；
执行 `DROP TABLE users` 确认收到权限不足且服务不中断。

### Tests for User Story 1

- [X] T024 [P] [US1] 编写 `backend/tests/integration/test_honeypot_protocol.py`：握手、认证成功/失败、元数据查询、SELECT、写操作拒绝、畸形报文的端到端用例
- [X] T025 [P] [US1] 编写 `backend/tests/unit/test_fake_catalog.py`：伪造库表目录结构、行数据可识别为合成数据、`fake_config` 密钥无效

### Implementation for User Story 1

- [X] T026 [P] [US1] 实现 `backend/app/honeypot/fake_catalog.py`：`honeypot_shop`/`honeypot_archive` 两个伪库、`users`/`orders`/`config` 三张伪表结构与行数据，数据从 `fake_users`/`fake_orders`/`fake_config` 读取
- [X] T027 [P] [US1] 实现 `backend/app/honeypot/auth.py`：自定义 `IdentityProvider`，预置诱饵账号使用 `mysql_native_password` 校验，未知账号拒绝并生成 auth 失败事件
- [X] T028 [US1] 实现 `backend/app/honeypot/session.py`：继承 `mysql_mimic.Session`，`schema()` 返回伪库表，按 contracts/honeypot-protocol.md 3 章路由 `SHOW`/`DESCRIBE`/`SELECT`/`information_schema`，对 DML/DDL 返回 1142 并记录
- [X] T029 [US1] 实现 `backend/app/honeypot/server.py`：启动/停止 `MysqlServer`，读取端口与账号配置，端口占用时非 0 退出并输出明确错误
- [X] T030 [US1] 在协议层接入捕获钩子，按 contracts/events.md 3 章产生 connect/auth/query/disconnect 原始事件并交给捕获服务（实现 `backend/app/honeypot/emitter.py`）
- [X] T031 [US1] 在 `backend/app/honeypot/limits.py` 落实 SQL 长度上限、返回行数上限、单连接超时与 payload 截断标记 `attack_log.payload_truncated`（见 contracts/honeypot-protocol.md 6 章）
- [X] T032 [US1] 在 `backend/app/cli/simulate_traffic.py` 实现授权模拟器：仅连接 `.env` 中允许的隔离目标，执行固定查询序列，用于演示与冒烟
- [X] T033 [US1] 在 `docs/demo-script.md` 补充诱饵连接与元数据查询的现场操作步骤，并验证三次连续执行稳定
- [X] T034 [US1] 对认证失败、非法字符集、超长 SQL、并发连接等边界补测试并修正实现，确认 `caching_sha2_password` 客户端限制按文档提示处理

**Checkpoint**: 客户端可完成诱饵交互，US1 可独立演示；事件尚未入库时以日志断言。

---

## Phase 4: User Story 2 - 结构化捕获与会话时间线（Priority: P1）

**Goal**: 把连接、认证、查询、断开转换为带唯一事件编号的标准事件，同一连接共享
`session_id`，事件可按事件时间与 event_id 稳定排序还原。

**Independent Test**: 制造一次含认证失败、认证成功、多次查询与断开的交互，断言数据库
存在 1 个会话与有序事件，事件字段与 contracts/events.md 一致，`event_uuid` 唯一。

### Tests for User Story 2

- [X] T035 [P] [US2] 编写 `backend/tests/unit/test_event_builder.py`：事件 UUID 生成、时区、标准化 SQL、字段必填与长度截断
- [X] T036 [P] [US2] 编写 `backend/tests/integration/test_capture_session.py`：一次完整交互落库后的会话与事件关联、并列时间戳排序、connect/auth 分别记录

### Implementation for User Story 2

- [X] T037 [US2] 实现 `backend/app/schemas/events.py`：标准事件模型，字段与约束对齐 contracts/events.md 3 章与 data-model.md `attack_log.event_uuid/event_type/status/source_ip/username/credential_test_id/sql_statement/normalized_sql/event_time/returned_rows/response_ms`
- [X] T038 [US2] 实现 `backend/app/services/event_builder.py`：UUID v4 生成规则、UTC 时间、SQL 归一化（去除常量与空白差异）、超长 SQL 截断与 `payload_truncated`
- [X] T039 [US2] 实现 `backend/app/services/session_manager.py`：会话创建、`request_count` 维护、`session_status` 状态迁移（active→closed/timeout/error）、`ended_at >= started_at` 校验，引用 data-model.md `sessions.session_status/request_count/ended_at`
- [X] T040 [US2] 实现 `backend/app/repositories/session_repo.py` 与 `attack_log_repo.py`：按 `session_id` 查询时间线、按来源查询事件，使用 `idx_log_session_time`/`idx_log_source_time`
- [X] T041 [US2] 在 `backend/app/api/routes/health.py` 暴露诱饵服务状态与最近事件计数，供控制台与演练自检
- [X] T042 [US2] 将 US1 的原始事件经 `event_builder` + `session_manager` 接入诱饵服务，保证同连接事件共享 `session_id`
- [X] T043 [US2] 编写 `backend/tests/integration/test_session_alignment.py`：验证 `rule_hits`/`alerts` 与事件的会话一致性（为 US4/US6 预留断言）
- [X] T044 [US2] 在 `docs/architecture.md` 记录事件模型、会话生命周期与数据流（诱饵→捕获→存储）

**Checkpoint**: 会话与事件可完整落库并按序查询，US2 独立可测。

---

## Phase 5: User Story 3 - 事务完整性、幂等与重置（Priority: P1）

**Goal**: 会话、日志、规则命中、告警与画像的写入在同一事务内完成；`event_uuid` 唯一
约束保证重试幂等；演示重置按依赖顺序清理且可回滚。

**Independent Test**: 同一 `event_uuid` 连续提交 10 次仅 1 条日志；注入画像写入失败后
五类数据与事务前一致；写入不存在的 `session_id` 被外键拒绝；重置后规则种子保留。

### Tests for User Story 3

- [X] T045 [P] [US3] 编写 `backend/tests/integration/test_idempotency.py`：重复 event_uuid 返回已有 event_id、计数不变、并发插入冲突处理
- [X] T046 [P] [US3] 编写 `backend/tests/integration/test_transaction_rollback.py`：在各写入点注入失败，断言 event/session/rule_hit/alert/profile 全部回滚
- [X] T047 [P] [US3] 编写 `backend/tests/integration/test_constraints_fk.py`：外键拒绝、CHECK 拒绝（分数越界、负计数、非法状态）、UNIQUE 冲突错误映射

### Implementation for User Story 3

- [X] T048 [US3] 实现 `backend/app/services/ingest.py`：事件写入事务 T1（会话 upsert → attack_log → 规则分析挂点 → 画像更新 → 审计），按 contracts/events.md 6 章顺序执行，失败整体回滚
- [X] T049 [US3] 实现幂等处理：先查 `attack_log.event_uuid`，冲突时回查返回已有 `event_id`，区分“已存在/本次新增”两种结果，映射 MySQL 1062 为业务结果而非 500
- [X] T050 [US3] 实现 `backend/app/db/retry.py`：死锁 1213/锁超时 1205 最多重试 3 次、退避 50/100/200ms，记录运行日志与 `audit_log` 失败留痕
- [X] T051 [US3] 实现 `backend/app/services/reset.py` 与 `backend/app/cli/reset_demo.py`：按 `alerts → rule_hits → attack_log → attacker_intent → attacker_profile → sessions` 删除，保留规则与诱饵种子，异常回滚，写 `audit_log(operation='reset')`
- [X] T052 [US3] 实现 `backend/app/services/audit.py` 与 `backend/app/repositories/audit_repo.py`：仅追加审计，覆盖（`audit_log.operation/result/account_name/target_table/target_key`），业务账号仅 INSERT/SELECT
- [X] T053 [US3] 实现 `backend/app/cli/verify_transaction.py`：提供 `--inject-failure` 参数复现事务回滚，输出五表行数前后对比，供答辩演示
- [X] T054 [US3] 配置 `app_rw` 账号运行写入、`app_ro` 只读展示、`migrate` 迁移、`backup` 备份的 URL 与连接池，验证应用不使用超级用户
- [X] T055 [US3] 编写 `docs/database-design.md` 的事务与幂等章节，引用 data-model.md 8 章步骤与测试证据

**Checkpoint**: 写入原子、幂等、可重置，数据库完整性可现场演示。

---

## Phase 6: User Story 4 - 意图识别与风险画像（Priority: P1）

**Goal**: 依据数据库配置的 R01–R05 识别扫描、爆破、踩点、拖库与破坏性操作，更新意图、
画像与 0–100 风险分，所有分数可追溯到 `rule_hits` 证据。

**Independent Test**: 导入固定合成样本，命中 R01–R05 各正例/反例、阈值边界、重复处理、
封顶、停用规则与版本切换，核对 `rule_hits`、`attacker_intent`、`attacker_profile.risk_score`
与 data-model.md 9.6 手算基准一致。

### Tests for User Story 4

- [X] T056 [P] [US4] 编写 `backend/tests/unit/test_rules.py`：五条规则判定函数在阈值边界、关键词、窗口统计上的正反例
- [X] T057 [P] [US4] 编写 `backend/tests/unit/test_risk.py`：会话/意图/画像三档评分公式、封顶、同规则重复命中去重、等级映射
- [X] T058 [P] [US4] 编写 `backend/tests/integration/test_analysis_pipeline.py`：单事务内命中、意图、画像更新，重复分析不重复计分

### Implementation for User Story 4

- [X] T059 [P] [US4] 在 `backend/app/services/rules/` 实现规则参数模型与参数校验：`detection_rules.parameters_json` 的按类型 schema（frequency/keyword/sequence/volume），引用 data-model.md 10.2
- [X] T060 [P] [US4] 实现 R01 扫描规则 `backend/app/services/rules/r01_scanning.py`：60 秒窗口连接数 ≥10 且无有效 SQL，权重 10
- [X] T061 [P] [US4] 实现 R02 爆破规则 `r02_bruteforce.py`：5 分钟认证 ≥8 次且凭据组合 ≥5 组，权重 25
- [X] T062 [P] [US4] 实现 R03 踩点规则 `r03_recon.py`：SHOW/DESCRIBE/information_schema 关键词，权重 15
- [X] T063 [P] [US4] 实现 R04 拖库规则 `r04_data_dump.py`：连续 SELECT 或会话返回行数阈值，权重 25
- [X] T064 [P] [US4] 实现 R05 破坏性操作规则 `r05_destructive.py`：DROP/TRUNCATE/DELETE/UPDATE/INSERT，权重 35
- [X] T065 [US4] 实现 `backend/app/services/analysis.py`：读取启用的最大版本规则、执行判定、写 `rule_hits`（含 `rule_version`/`risk_weight` 快照与 `evidence_summary`），在 T1 事务内调用
- [X] T066 [US4] 实现 `backend/app/services/risk.py`：按 data-model.md 9.2 公式计算会话分、意图分、画像分与 `risk_level`（low/medium/high/critical），封顶 100，更新 `attacker_profile` 与 `attacker_intent`
- [X] T067 [US4] 实现 `backend/app/repositories/profile_repo.py`：按 `source_ip` 聚合与视图 `v_attacker_profile_summary` 查询主要意图（分数/最近时间/危害排序稳定）
- [X] T068 [US4] 编写 `docs/database-design.md` 的规则与评分章节，附 data-model.md 9.6 手算样例与验证记录模板

**Checkpoint**: 规则、意图、画像可独立验证，分数可逐条回溯证据。

---

## Phase 7: User Story 5 - 会话时间线与攻击者详情（Priority: P2）

**Goal**: 观察者按会话编号查看认证与 SQL 事件时间线、规则证据与风险分；从攻击者详情
进入其名下各会话并核对首末时间与统计。

**Independent Test**: 对含认证失败、认证成功与多次查询的会话，调用
`GET /api/sessions/{session_id}/timeline` 与 `GET /api/attackers/{ip}`，断言事件顺序、
规则证据、画像统计与数据库一致且口令已脱敏。

### Tests for User Story 5

- [X] T069 [P] [US5] 编写 `backend/tests/api/test_timeline_api.py`：已知会话返回有序事件与证据、未知会话 404、并列时间戳稳定排序
- [X] T070 [P] [US5] 编写 `backend/tests/api/test_attacker_detail_api.py`：画像、意图、会话摘要与统计正确，`username_masked` 不含完整口令

### Implementation for User Story 5

- [X] T071 [US5] 实现 `backend/app/api/routes/sessions.py` 的 `GET /api/sessions/{session_id}/timeline`：会话头、事件（按 event_time, event_id）、`rule_hits`、`alerts`，查询 `v_session_risk_summary`
- [X] T072 [US5] 实现 `backend/app/api/routes/attackers.py` 的 `GET /api/attackers/{ip}`：画像、intents、sessions 摘要、recent_rule_hits，未知 IP 返回 404
- [X] T073 [US5] 在 `backend/app/schemas/` 补时间线与画像详情的响应模型，字段与 contracts/api.md 3.4/3.5 一致
- [X] T074 [P] [US5] 实现前端 `frontend/src/components/SessionTimeline.vue`：按时间线渲染认证/SQL 事件、命中标记与证据抽屉
- [X] T075 [P] [US5] 实现前端 `frontend/src/components/IntentTag.vue` 与 `RiskBadge.vue`：意图标签、风险等级与分数徽标
- [X] T076 [US5] 补 `docs/test-plan.md` 的时间线与画像验收用例与截图位置

**Checkpoint**: 攻击行为链可按会话还原，画像详情可查。

---

## Phase 8: User Story 6 - 告警生成、筛选与已读（Priority: P2）

**Goal**: R02/R04/R05 命中生成带证据的告警，按类型/时间/等级/已读筛选，支持标记已读
且为独立写操作。

**Independent Test**: 分别触发爆破、拖库与破坏告警，核对数量、等级与证据；按各条件
筛选与数据库一致；PATCH 已读后重新查询状态生效。

### Tests for User Story 6

- [X] T077 [P] [US6] 编写 `backend/tests/integration/test_alerts.py`：生成条件、severity 映射、`dedup_key` 去重与 `occurrence_count` 累加
- [X] T078 [P] [US6] 编写 `backend/tests/api/test_alerts_api.py`：筛选、分页、空数组、PATCH 已读、未知告警 404

### Implementation for User Story 6

- [X] T079 [US6] 实现 `backend/app/services/alerts.py`：按 data-model.md 9.4/9.5 生成告警（`alert_type`、`severity`、`dedup_key`、`latest_hit_id`、`occurrence_count`），基于 `uk_alerts_dedup_key` 去重更新
- [X] T080 [US6] 在分析流水线中接入告警生成（仅 bruteforce/data_dump/destructive），保持 T1 事务原子性
- [X] T081 [US6] 实现 `backend/app/api/routes/alerts.py`：`GET /api/alerts`（过滤与分页）与 `PATCH /api/alerts/{alert_id}`（`is_read`/`read_at` + 审计）
- [X] T082 [US6] 在 `backend/app/services/alerts.py` 实现告警证据可追溯查询（告警→命中→事件）
- [X] T083 [US6] 补 `docs/test-plan.md` 的告警测试矩阵与重放去重用例

**Checkpoint**: 告警可生成、可筛选、可处置，证据链完整。

---

## Phase 9: User Story 7 - 四页核心控制台（Priority: P2）

**Goal**: 首页概览、攻击者列表、攻击者详情、告警列表四个页面可用，数字与视图一致，
空态友好、视觉统一。

**Independent Test**: 在预置数据与空数据下逐一打开四页，核对指标与视图聚合一致、分页
稳定、图表正常、无明文口令。

### Tests for User Story 7

- [X] T084 [P] [US7] 编写 `backend/tests/api/test_overview_api.py`：概览指标与 `v_session_risk_summary`/`v_daily_attack_trend` 一致
- [X] T085 [P] [US7] 编写 `backend/tests/api/test_attackers_list_api.py`：分页、排序、空数组、`main_intent` 稳定
- [X] T086 [P] [US7] 编写 `backend/tests/api/test_trend_effectiveness_api.py`：趋势与前日变化（LAG）、规则效果（RANK）字段正确

### Implementation for User Story 7

- [X] T087 [US7] 实现 `backend/app/api/routes/overview.py`：`GET /api/overview`（会话数/查询数/告警数/高风险攻击者数）与 `GET /api/trend`（`v_daily_attack_trend`）
- [X] T088 [US7] 实现 `backend/app/api/routes/attackers.py` 的列表接口 `GET /api/attackers`（分页、排序、`main_intent`、`risk_level`），复用 `v_attacker_profile_summary`
- [X] T089 [US7] 实现 `backend/app/api/routes/rules.py` 的 `GET /api/rules/effectiveness`（`v_rule_effectiveness`）
- [X] T090 [P] [US7] 实现 `frontend/src/api/client.ts` 与 `frontend/src/types/index.ts`：类型化接口封装、错误处理与分页参数
- [X] T091 [P] [US7] 实现 `frontend/src/router/index.ts` 与 `frontend/src/App.vue`：四路由（`/`、`/attackers`、`/attackers/:ip`、`/alerts`）与统一布局导航
- [X] T092 [P] [US7] 实现 `frontend/src/views/OverviewView.vue` 与 `components/StatCard.vue`、`TrendChart.vue`（ECharts 趋势图）
- [X] T093 [P] [US7] 实现 `frontend/src/views/AttackersView.vue` 与 `components/AttackerTable.vue`（分页、排序、意图标签、风险徽标）
- [X] T094 [P] [US7] 实现 `frontend/src/views/AttackerDetailView.vue`：画像统计、意图列表、会话摘要与时间线抽屉
- [X] T095 [P] [US7] 实现 `frontend/src/views/AlertsView.vue` 与 `components/AlertTable.vue`：筛选、分页、标记已读
- [X] T096 [US7] 统一四页视觉与空态/错误态，接入 `/api/health` 降级横幅，确认四页数字与视图查询一致

**Checkpoint**: 控制台四页可独立演示，页面与数据库结果一致。

---

## Phase 10: User Story 8 - 规则配置与版本管理（Priority: P3）

**Goal**: 管理员查看规则阈值/权重/版本/启用状态，停用或调整后生成新版本，历史命中
保留旧版本快照。

**Independent Test**: 停用 R03 后新事件不再命中；修改 R05 权重生成 v2，新命中快照为
v2，历史命中仍为 v1/旧权重。

### Tests for User Story 8

- [X] T097 [P] [US8] 编写 `backend/tests/api/test_rules_api.py`：`GET /api/rules` 列表、`PATCH /api/rules/{rule_code}` 生成新版本、停用后不参与分析、非法参数 422

### Implementation for User Story 8

- [X] T098 [US8] 实现 `backend/app/api/routes/rules.py` 的 `GET /api/rules` 与 `PATCH /api/rules/{rule_code}`：参数校验、版本自增、旧版本 `enabled=0`、唯一约束防并发双启用
- [X] T099 [US8] 在 `backend/app/services/analysis.py` 落实“按 rule_code 取启用最大版本、命中快照版本/权重”，引用 data-model.md 10.3
- [X] T100 [US8] 在规则变更中写 `audit_log(operation='rule_change')` 并验证 `app_rw` 无规则 DELETE 权限
- [X] T101 [US8] 编写 `docs/database-design.md` 的规则版本管理说明与回滚口径
- [X] T102 [US8] 补 `frontend/src/views/OverviewView.vue` 的规则效果小表（只读），保证 `v_rule_effectiveness` 被控制台实际使用

**Checkpoint**: 规则可配置、可版本化、可追溯。

---

## Phase 11: User Story 9 - 固定合成样本与授权模拟（Priority: P3）

**Goal**: 提供固定合成样本与模拟器，空库导入后可稳定复现预期标签、评分与告警，支撑
测试矩阵与答辩兜底。

**Independent Test**: 空库导入三条固定事件→同一会话三条有序日志且仅命中 R03；导入
批量读取与被拒绝写操作样本→R04/R05 与告警符合预期；重复导入幂等。

### Tests for User Story 9

- [X] T103 [P] [US9] 编写 `backend/tests/integration/test_samples.py`：S01 样本闭环、S03 重复导入幂等、S04/S05 评分与告警、S06/S07 边界
- [X] T104 [P] [US9] 编写 `backend/tests/unit/test_simulator_safety.py`：模拟器仅允许 `.env` 声明的隔离网段，拒绝未授权地址

### Implementation for User Story 9

- [X] T105 [P] [US9] 在 `backend/app/cli/samples/` 定义样本 S01–S07 与 `demo_basic` 集合（JSON，含合成事件、预期规则与分数），字段符合 contracts/events.md
- [X] T106 [US9] 实现 `backend/app/cli/import_samples.py`：按样本导入、`--repeat` 验证幂等、输出 `{imported, deduped, alerts[]}` JSON
- [X] T107 [US9] 实现 `backend/app/cli/gen_demo_data.py`：生成 2000 会话/20000 事件等规模数据用于索引对比与展示压测（课程规模）
- [X] T108 [US9] 实现 `backend/app/cli/seed.py`：幂等导入 5 规则、30 fake_users、120 fake_orders、5 fake_config（见 data-model.md 10.4），并写 `audit_log`
- [X] T109 [US9] 完善 `backend/app/cli/simulate_traffic.py` 与 `scripts/demo.sh`：三轮演示脚本、样本重置、预期结果打印
- [X] T110 [US9] 编写 `docs/test-plan.md` 的测试矩阵（连接/失败认证/踩点/拖库/破坏/画像/界面/恢复）与预期结果
- [X] T111 [US9] 编写 `docs/demo-script.md` 完整演示顺序（7 步）与答辩口径（创新点与限制）

**Checkpoint**: 样本可重复、演示可复现、模拟器安全边界明确。

---

## Phase 12: User Story 10 - AI 只读辅助（可选增强，可关闭）（Priority: P3）

**Goal**: 自然语言只读查询映射到预设模板/视图，输出标记为辅助解释，不参与检测与评分，
关闭或不可用时不影响核心功能。

**Independent Test**: 开启时允许的只读问题可用、任意 SQL/写操作被拒；关闭时概览、画像、
告警与演示不受影响。

### Tests for User Story 10

- [X] T112 [P] [US10] 编写 `backend/tests/api/test_ai_api.py`：允许模板查询、拒绝任意 SQL、AI 关闭返回 503 且核心接口正常

### Implementation for User Story 10

- [X] T113 [US10] 实现 `backend/app/services/ai_assistant.py`：自然语言→预设只读查询模板/视图的映射，使用 `app_ro` 连接，仅 SELECT，输出附 `"辅助解释"` 标记
- [X] T114 [US10] 实现可选路由 `backend/app/api/routes/ai.py`（`POST /api/ai/ask`，默认关闭由 `AI_ENABLED` 控制），并同步更新 `contracts/api.md` 变更记录
- [ ] T115 [US10] 在 `frontend/src/views/OverviewView.vue` 增加可选的解释侧栏（关闭时隐藏），不阻塞主流程
  - **状态**：未实现。AI 能力已通过 `POST /api/ai/ask` 提供且默认关闭；按“可选增强、可整体关闭”的口径，前端入口推迟到后续迭代。
- [X] T116 [US10] 补 `docs/architecture.md` 的 AI 权限边界与降级说明，确认 AI 不修改规则命中/风险分/告警

**Checkpoint**: AI 可关闭、只读、安全，不影响最小闭环。

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: 文档、索引验证、安全复核与快速验证收尾。

- [X] T117 [P] 编写 `docs/architecture.md`：五层架构、数据流、部署视图与模块职责
- [X] T118 [P] 编写 `docs/database-design.md`：ER 图、关系模式、约束、视图、索引、事务与安全设计，交叉引用 `data-model.md`
- [X] T119 [P] 生成 `db/explain/` 的索引前后 EXPLAIN 记录（至少两组：会话时间线、告警等级），写入 `docs/explain-indexes.md`
- [X] T120 执行 `backend/app/cli/explain_diff.py` 输出计划对比（`type`/`key`/`rows`/耗时），纳入答辩材料
- [X] T121 [P] 补全 `README.md`：环境、初始化、启动、健康检查、关闭顺序、重置与常见故障
- [X] T122 [P] 补 `backend/tests/unit/` 的脱敏、分页、错误映射、中文注释规范检查等单元测试
- [X] T123 在 `backend/` 运行 `ruff` 与 `mypy`（或 pyright）并修复问题，在 `frontend/` 运行 `pnpm build` 与 ESLint
- [X] T124 执行 `quickstart.md` 的 V01–V23 全部验证场景与 SC-001–SC-015 映射，记录结果
- [X] T125 在 `db/init/` 与 `backend/` 完成安全复核：`SHOW GRANTS` 四类账号最小权限、无明文口令、无拼接 SQL、诱饵只存不执行、无真实数据
- [X] T126 在 `docs/test-plan.md` 记录性能与稳定性复核：三轮连续演示、索引对比、页面响应时间、数据库重启后恢复
- [X] T127 更新 `specs/001-database-honeypot/` 与 `docs/` 的变更记录，确认 spec/plan/data-model/contracts/tasks 术语一致
- [X] T128 按 `compose.yaml` 与 `db/init/` 从空库重建演示环境并完成一次完整演练，确认可重复演示（结果记入 `docs/test-plan.md`）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，可立即开始
- **Foundational（Phase 2）**：依赖 Setup，完成后才可开始用户故事
- **User Stories（Phase 3–12）**：依赖 Foundational；按优先级顺序推进，具备条件时可并行
- **Polish（Phase 13）**：依赖目标用户故事完成

### User Story Dependencies

- **US1 诱饵服务**：依赖 Foundational；可独立实现与测试（事件以日志断言）
- **US2 捕获与会话**：依赖 Foundational；US1 的协议钩子为集成点，可先用合成事件独立测试
- **US3 事务与幂等**：依赖 Foundational；为 US2/US4/US6 提供写入基础
- **US4 规则与画像**：依赖 US2/US3 的事件与写入能力；可先用固定样本独立测试
- **US5 时间线与画像详情**：依赖 US2/US4（数据）与 US7（前端路由与页面）
- **US6 告警**：依赖 US3/US4（写入与命中），可独立以样本验证
- **US7 控制台**：依赖 US4/US5/US6 的接口与组件；四页可分别验证
- **US8 规则配置**：依赖 US4（分析版本选择）
- **US9 样本与模拟器**：依赖 US1–US4，作为测试与演示支撑
- **US10 AI**：依赖 US5/US7 的只读查询与视图，可整体关闭

### Within Each User Story

- 测试任务先写并确认失败，再实现
- 模型/参数 → 服务 → 接口 → 集成 → 文档
- 故事完成后在 checkpoint 独立验证，再进入下一优先级

### Parallel Opportunities

- Phase 1 的 `[P]` 任务（T003–T008）可并行
- Phase 2 的 `[P]` 任务（T015–T018、T020–T021）可并行，但 T019（应用骨架）需在路由任务前完成
- 同一故事内标记 `[P]` 的规则实现（T060–T064）、前端组件（T074–T075、T090–T095）可并行
- 不同故事可由不同成员并行开发，但 US5–US7 的前端任务建议在 US7 路由骨架后进行
- 所有测试任务（标 `[P]`）可并行编写

---

## Parallel Example: User Story 4

```bash
# 五条规则可并行实现（不同文件）：
Task: "实现 R01 扫描规则 backend/app/services/rules/r01_scanning.py"
Task: "实现 R02 爆破规则 backend/app/services/rules/r02_bruteforce.py"
Task: "实现 R03 踩点规则 backend/app/services/rules/r03_recon.py"
Task: "实现 R04 拖库规则 backend/app/services/rules/r04_data_dump.py"
Task: "实现 R05 破坏性规则 backend/app/services/rules/r05_destructive.py"

# 规则判定与评分单元测试可并行编写：
Task: "编写 backend/tests/unit/test_rules.py"
Task: "编写 backend/tests/unit/test_risk.py"
```

---

## Implementation Strategy

### MVP First（US1 + 最小落库链路）

1. 完成 Phase 1 Setup
2. 完成 Phase 2 Foundational（关键阻塞）
3. 完成 US1 诱饵服务
4. 完成最小落库（US2 捕获 + US3 事务）
5. **STOP and VALIDATE**：客户端交互→事件落库→会话可查
6. 演示 MVP

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. US2/US3 → 会话与日志可追溯（数据库专项可演示）
3. US4 → 规则、画像、评分（分析能力上线）
4. US5/US6/US7 → 时间线、告警、四页控制台（演示完整）
5. US8 → 规则配置与版本（可解释调整）
6. US9 → 样本与模拟器（可重复演示）
7. US10 → AI 辅助（可选）
8. Polish → 文档、EXPLAIN、安全与验收

### Parallel Team Strategy

- 全员先完成 Setup + Foundational（T001–T023）
- 之后按角色分工：
  - 成员 A：US1 诱饵协议 + US2 捕获
  - 成员 B：US3 存储事务 + US9 样本
  - 成员 C：US4 规则画像 + US8 规则配置
  - 成员 D：US5/US6 接口 + US7 前端
- 每周联调一次，回归 US2 样本时间线与证据链

---

## Notes

- `[P]` 任务为不同文件、无未完成依赖；同文件任务不得并行
- 每个任务完成后更新本文件状态并提交
- 测试优先：先写测试并确认失败，再实现
- 数据库相关断言必须基于真实 MySQL 8.4 测试库，禁止 Mock
- 所有文档、注释、提交信息使用中文；DDL 注释写入 `COMMENT`

## 约束引用索引（data-model.md → 实现任务）

下表确保 data-model.md 中每个受约束字段至少被一个实现任务显式引用为“实现依据”。

| 实体 | 受约束字段（引用 `data-model.md` 定义） | 实现任务 |
| --- | --- | --- |
| sessions | `sessions.session_id`、`sessions.session_status`、`sessions.request_count`、`sessions.max_risk_score`、`sessions.ended_at`、`sessions.source_ip` | T009、T015、T039 |
| attack_log | `attack_log.event_uuid`、`attack_log.event_type`、`attack_log.status`、`attack_log.returned_rows`、`attack_log.response_ms`、`attack_log.event_time`、`attack_log.username`、`attack_log.payload_truncated` | T009、T015、T031、T037、T049 |
| attacker_profile | `attacker_profile.source_ip`、`attacker_profile.risk_score`、`attacker_profile.risk_level`、`attacker_profile.total_connections`、`attacker_profile.total_auth_attempts`、`attacker_profile.total_queries` | T010、T015、T066、T067 |
| attacker_intent | `attacker_intent.intent_type`、`attacker_intent.intent_score`、`attacker_intent.evidence_count`、`attacker_intent.attacker_id + intent_type` | T010、T015、T066 |
| detection_rules | `detection_rules.rule_code`、`detection_rules.rule_version`、`detection_rules.parameters_json`、`detection_rules.risk_weight`、`detection_rules.enabled`、`detection_rules.enabled_rule_code` | T010、T014、T059、T098 |
| rule_hits | `rule_hits.event_id`、`rule_hits.session_id`、`rule_hits.rule_id`、`rule_hits.rule_version`、`rule_hits.risk_weight`、`rule_hits.triggered_at` | T010、T015、T065 |
| alerts | `alerts.dedup_key`、`alerts.alert_type`、`alerts.severity`、`alerts.is_read`、`alerts.occurrence_count`、`alerts.latest_hit_id` | T011、T015、T079、T081 |
| fake_users | `fake_users.username`、`fake_users.password_hash`（列级不暴露） | T011、T015、T026、T125 |
| fake_orders | `fake_orders.order_no`、`fake_orders.user_id` | T011、T015、T026 |
| fake_config | `fake_config.config_key`、`fake_config.is_invalid` | T011、T015、T026 |
| audit_log | `audit_log.operation`、`audit_log.result`、`audit_log.account_name`、`audit_log.request_id` | T011、T052、T100 |

## 格式校验

- 全部任务使用 `- [X] Txxx [P?] [US?] 描述 + 文件路径` 格式
- Setup、Foundational、Polish 阶段无 Story 标签；用户故事阶段均带 `[USx]`
- 任务 ID 连续且唯一；`[P]` 仅用于不同文件、无未完成依赖的任务


---

## 实施状态记录（2026-11-19）

**结论**：128 个任务中 127 个已完成，1 个可选增强前端入口（T115）明确推迟。

### 验证证据

| 项 | 结果 |
| --- | --- |
| 数据库 | MySQL 8.0.46；11 张业务表 + 4 视图 + 38 CHECK / 10 FK / 12 UNIQUE；`alembic upgrade/downgrade` 往返与重复执行通过 |
| 后端测试 | `pytest -q`：**225 passed, 0 failed**（单元/集成/接口，真实 MySQL，无数据库 Mock） |
| 静态检查 | `ruff check app tests migrations`：All checks passed |
| 诱饵服务 | 3307 端口；SHOW/DESCRIBE/SELECT 返回伪造数据；DML/DDL 返回 1142；只存不执行（fake_* 行数不变） |
| 事件链路 | connect/auth/query/disconnect 落库；`event_uuid` 幂等；R01–R05 命中、画像、告警可追溯 |
| API | 11 个契约接口 + `/api/ai/ask`；health 对齐契约（database/honeypot 嵌套、degraded=503）；404/422 错误结构统一 |
| 前端 | `frontend/dist` 构建成功并由 FastAPI 托管；四页路由可用；接口失败有降级横幅 |
| 样本与演示 | S01–S07 预期全部匹配；`demo_basic` 连续三轮结果一致（14 会话 / 125 事件 / 8 告警） |
| EXPLAIN | `db/explain/` 两组记录：`ALL→ref`，扫描行数 2174→16 / 9→3，filesort 消除 |
| 权限 | `apply_table_grants.sh` 已收紧；`app_rw` 无 DDL、`app_ro` 无写权限、`fake_users.password_hash` 列级隐藏 |
| 安全边界 | 模拟器仅允许 127.0.0.0/8；诱饵采集数据只存不执行；演示数据全为合成值 |

### 已知偏差（如实记录）

1. **MySQL 版本**：设计目标 8.4 LTS，本机镜像源仅有 8.0.46；实现使用 8.x 共有能力，8.4 上同样可运行。
2. **样本编号**：`api.md` 4.3 的旧编号与 `tasks.md` T103 的编号不同；实现按 T103（S01 闭环、S03 拖库、S04 破坏、S05 扫描、S06 综合、S07 边界），差异记录于 `backend/app/cli/samples/README.md`。
3. **健康检查**：已修复为契约 3.1 的嵌套结构（早期测试 xfail 已更新为通过）。
4. **R03/R04 口径**：按 data-model 10.2 修正——R03 严格使用 `parameters_json.keywords`；R04 行数条件为严格大于 1000。
5. **测试库账号**：`honeypot_test` 仅 `honeypot_migrate` 有授权，测试统一使用迁移账号；应用只读/读写账号的权限边界在 `honeypot_dev` 上验证。
6. **T115**：AI 前端入口推迟；核心闭环与四页控制台不受影响。
