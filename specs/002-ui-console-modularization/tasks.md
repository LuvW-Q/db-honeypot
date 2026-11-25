# Tasks: 控制台视觉重构与模块解耦

**Input**: Design documents from `specs/002-ui-console-modularization/`

**Prerequisites**: [plan.md](plan.md)（必需）、[spec.md](spec.md)（用户故事与 FR）、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md)

**Tests**: 本 feature 的宪法原则五与 SC-016–028 明确要求可验证证据，且 001 回归是硬门禁，
因此测试任务已纳入（契约测试、结构/边界测试、Playwright 真实浏览器检查、三轮部署）。

**Organization**: 任务按用户故事分组。P1 故事（US1 视觉、US2 真实部署、US3 五模块）是
本 feature 的核心交付；US4/US5 把视觉与交互转为可复核证据；US6 收敛原型缺陷。由于
模块目录搬迁是所有故事的文件路径前提，搬迁工作集中在 Foundational 阶段完成，US3 阶段
交付模块证据与所有权校验（对应 spec US3 的独立验收标准）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 不同文件、无未完成依赖，可并行
- **[Story]**: 所属用户故事（US1–US6）；Setup/Foundational/Polish 不带故事标签
- 每个任务给出精确文件路径；字段约束引用 `data-model.md` 的 `实体.字段`

## Path Conventions

本仓库为"单发行版 + 五模块目录 + 共享平台"结构（见 [plan.md](plan.md) "Project Structure"）：

- `shared/`、`modules/<module>/`、`modules/m5-views-console/frontend/`
- 根级：`pyproject.toml`、`alembic.ini`、`conftest.py`、`tests/`、`Makefile`

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 建立新仓库布局的根级骨架、依赖与迁移前基线；本阶段不改变运行时行为。

- [X] T001 在 `specs/002-ui-console-modularization/spec.md` 附录 B 追加第 21–28 条原型差异裁定（告警类型 3 类、实体标签→网络归属、拦截率口径、平均时长/高危操作、KPI 趋势、高风险会话字段、时间线 4 类事件），并在附录 C 对应区域标注
- [X] T002 创建根 `pyproject.toml`：hatchling 多包映射（`shared`、五个模块内包）、锁定依赖与 dev 依赖（pytest/ruff）、添加 `[tool.uv] package = true`
- [X] T003 [P] 创建根 `alembic.ini` 并把 `modules/m1-transaction-integration/migrations/env.py` 的 `script_location`/`target_metadata` 适配到 `shared.shared.models`
- [X] T004 [P] 创建根 `conftest.py` 与 `tests/support.py`：测试库连接改用 `shared.shared.config/settings`、事务回滚 fixture、通用断言工具；删除 `backend/tests/` 下旧副本
- [X] T005 [P] 重写 `Makefile`：`UV` 改为 `command -v uv` 可覆盖变量，新增 `boundary`、`structure`、`verify`、`verify3`、`verify-offline` 目标，路径指向 `modules/m5-views-console/frontend`
- [X] T006 [P] 更新 `.env.example`（`WEB_DIST_DIR=modules/m5-views-console/frontend/dist`）、`compose.yaml` 注释与 `README.md` 部署说明为"容器 MySQL + 宿主 uvicorn 单地址"模型
- [X] T007 [P] 创建 `shared/` 与五个 `modules/<module>/` 目录骨架、五份模块 `README.md` 和 `evidence/README.md` 模板（证据编号/FR/命令/期望输出/路径/依赖/最近验证时间，见 data-model.md §6.1）
- [X] T008 [P] 调整 `modules/m5-views-console/frontend/package.json`：加入 `tailwindcss@3.4.19`、`postcss`、`autoprefixer`、`@fontsource-variable/inter@5.3.0`、`@fontsource-variable/jetbrains-mono@5.3.0`、`material-symbols@0.49.0`、`@playwright/test@1.65.1`；移除 `element-plus`、`echarts`；生成锁文件
- [X] T009 采集搬迁前接口基线到 `tests/fixtures/api_baseline.json`（overview/trend/attackers/alerts 的字段与示例值，固定种子），供 US3 回归对比

---

## Phase 2: Foundational（阻塞性前置）

**Purpose**: 完成模块目录搬迁、公开门面与边界检查；**所有用户故事都依赖本阶段**。

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事。

- [X] T010 迁移共享平台代码到 `shared/`（`config.py`、`logging.py`、`db/`、`models/`、`events/`、`schemas/common.py`、`utils/`、`data/query.py`），改用新包名导入并保留中文注释
- [X] T011 迁移 M1 到 `modules/m1-transaction-integration/`：`api/app.py`（原 `main.py`）、`api/{deps,errors,routes}`、`schemas/api.py`、`repositories/`、`services/`、`cli/`、`migrations/`、`db/init|grants` 与 `tests/api|integration`
- [X] T012 [P] 迁移 M2 到 `modules/m2-decoy-capture/`：诱饵服务（server/session/auth/emitter/fake_catalog）、`cli/{simulate_traffic,import_samples,gen_demo_data,explain_diff}`、`samples/catalog.py`、`docs/explain-indexes.md`、`tests/unit/test_fake_catalog.py`
- [X] T013 [P] 迁移 M3 到 `modules/m3-er-constraints/`：`er/schema.mmd`（自 `docs/database-design.md` 抽出）、`constraints/{catalog.md,verify_constraints.sql}`、`tools/introspect_constraints.py`、`tests/integration/test_constraints_fk.py`
- [X] T014 [P] 迁移 M4 到 `modules/m4-rules-derived/`：规则引擎（`rules/`、`analysis.py`、`risk.py`、`alerts.py`）、`repositories/rule_repo.py` 与 `tests/unit|integration|api`
- [X] T015 [P] 迁移 M5 前端与视图测试到 `modules/m5-views-console/`（`frontend/` 全量、`tests/integration/test_views.py`），更新 `vite.config.ts`（proxy/dist 路径）与 `tsconfig`
- [X] T016 实现并接入公开门面：`m1_transaction_integration/public.py`（`ingest_event`/`reset_demo`）、`m2_decoy_capture/public.py`（`serve`）、`m4_rules_derived/public.py`（`analyze_and_derive`/`list_rules`/`update_rule`）；M1 事件写入改调 M4 门面、M2 事件写入改调 M1 门面
- [X] T017 [P] 实现 `shared/deploy/boundary_check.py`（允许矩阵、旧前缀扫描、循环检测、JSON 输出）与 `shared/deploy/check_structure.py`（五模块目录/README/证据目录），并添加 `tests/test_boundary_check.py` 的 8 类违规自测
- [X] T018 搬迁回归门禁：`uv sync` → `make migrate` → `pytest` 全量 → `ruff` → `uvicorn m1_transaction_integration.api.app:create_app --factory` 启动 → 四页冒烟；修复所有导入/路径回归，结果记录到 `specs/002-ui-console-modularization/checklists/migration-regression.md`

**Checkpoint**: 搬迁后功能零变化、测试全绿、`make boundary` 与 `make structure` 通过。

---

## Phase 3: User Story 1 - 四页控制台按新原型呈现（Priority: P1）🎯 MVP

**Goal**: 按原型完成深色控制台壳层与四页视觉，数据来自真实接口；提供页面所需的聚合接口增量。

**Independent Test**: 固定种子数据与 1440×900/1920×1080 视口下打开四页，按附录 C 区域
顺序核对结构，抽查令牌取值，确认无横向滚动、无重叠；`pytest` 中新增接口契约测试通过。

### Tests for User Story 1

- [X] T019 [P] [US1] 编写接口增量契约测试 `modules/m1-transaction-integration/tests/api/test_api_extensions.py`：`range` 枚举（data-model.md `OverviewData.range`）、五个趋势命中字段（data-model.md `TrendSeries.points[]`）、分母 0 的解决率（data-model.md `AlertSummary.resolution_rate`）、高风险计数（data-model.md `AttackerSummary.high_risk_count`）、网络归属（data-model.md `AttackerRow.network_scope`）与 `q` 1–64 转义（data-model.md `FilterState`）；先失败后实现

### Implementation for User Story 1

- [X] T020 [US1] 实现 M1 聚合查询 `modules/m1-transaction-integration/m1_transaction_integration/repositories/{overview,alert,attacker}_repo.py`：范围过滤与今日窗口（data-model.md `OverviewData.window_start`、`OverviewData.queries_delta_pct`、`OverviewData.query_blocked_rate`）、趋势意图命中、告警汇总、攻击者汇总与 `sort=total_connections`
- [X] T021 [US1] 扩展 M1 路由与 schema `modules/m1-transaction-integration/m1_transaction_integration/api/routes/{overview,alerts,attackers}.py` 与 `schemas/api.py`：`GET /api/overview?range`、`GET /api/alerts/summary`、`GET /api/attackers/summary`、trend/attackers/detail 新字段（约束见 [contracts/api-extensions.md](contracts/api-extensions.md) §2–§7）
- [X] T022 [US1] 建立令牌唯一数值源 `modules/m5-views-console/frontend/tailwind.config.cjs` 与 `postcss.config.cjs`，重写 `src/styles/base.css` 与 `ux/.../DESIGN.md`（语义说明 + "数值以配置为准"，令牌组见 data-model.md §5 `颜色-表面`/`字体族`/`圆角`）
- [X] T023 [US1] 本地化资源：`modules/m5-views-console/frontend/index.html`、`src/main.ts` 引入 @fontsource Inter/JetBrains Mono、material-symbols outlined、内联 SVG Logo 与四个 `public/favicons/*.svg`
- [X] T024 [US1] 扩展前端类型与 API 客户端 `modules/m5-views-console/frontend/src/types/index.ts`、`src/api/{client,index}.ts`：映射 data-model.md §3.3 的 `OverviewData`/`TrendSeries`/`AlertSummary`/`AttackerSummary`/`AttackerRow`/`AttackerProfileView`
- [X] T025 [US1] 实现全局壳层 `src/App.vue`、`src/components/{AppShell,StatusBlock,Clock,IconButton,RefreshButton}.vue`、`src/router/index.ts`：固定侧栏 288px/页头 64px、四项导航 01–04、未读徽标、UTC+8 时钟、底部状态块、每页 title/favicon/激活项
- [X] T026 [P] [US1] 实现基础展示组件 `src/components/{PageHeader,KpiCard,SectionCard,RiskBadge,IntentTag,RiskBar,RiskLevelLegend,StateBanner,EmptyState,Pagination,FilterSelect,FilterPills,SearchInput,ToastHost}.vue`（严重度映射见 data-model.md §3.5）
- [X] T027 [P] [US1] 实现 SVG 图表 `src/components/{TrendChart,IntentDonut,Sparkline}.vue`：三序列 + 渐变 + 峰值标注、环图中心文案与五类图例、全零/单点空态（数据来自 T021）
- [X] T028 [US1] 实现首页概览 `src/pages/OverviewPage.vue` + `src/composables/useOverview.ts`：`OV-HEAD/OV-KPI/OV-TREND/OV-DONUT/OV-TOP5` 五区域，KPI 文案与 `SRC:` 视图标注，`queries_delta_pct` 为 null 时显示 `—`
- [X] T029 [US1] 实现攻击者列表 `src/pages/AttackersPage.vue` + `src/composables/useAttackers.ts`：汇总卡、搜索/风险档/意图/排序控件、八列表格（双行 IP + `network_scope` 徽标、`intent_labels`、风险分条）、空态与分页；筛选逻辑待 US4 完整接线
- [X] T030 [US1] 实现攻击者详情与时间线 `src/pages/AttackerDetailPage.vue` + `src/components/{ProfileCard,EvidenceCard,SessionTable,SessionTimeline}.vue`：画像六行（data-model.md `AttackerProfileView.avg_session_seconds`、`AttackerProfileView.high_risk_op_count`、`AttackerProfileView.network_scope`）、证据链三卡、关联会话表、时间线筛选 Tabs 与 SQL 三层结构
- [X] T031 [US1] 实现告警列表 `src/pages/AlertsPage.vue` + `src/components/AlertCard.vue`：四张统计卡（data-model.md `AlertSummary.resolution_rate`、`AlertSummary.unread`）、状态页签/等级/类型/时间筛选条、告警卡与已读态、空态
- [X] T032 [US1] 构建冒烟：`corepack pnpm --dir modules/m5-views-console/frontend build`（含 `vue-tsc`）通过；`make api` 启动后四页加载无 console 错误，修复所有构建/渲染错误并记录到 `modules/m5-views-console/README.md`

**Checkpoint**: US1 可独立演示——四页视觉可对照原型；新增接口契约测试通过。

---

## Phase 4: User Story 2 - 真实部署路径可用并通过部署测试（Priority: P1）

**Goal**: 用一条命令在生产构建路径下完成部署验收：单地址、四页可访问、无报错/外链、
断网可用、异常降级、三轮稳定，并产出截图与报告。

**Independent Test**: 干净环境执行 `make verify` 得到退出码 0 与 `run-1/deploy-record.json`；
断网后重开四页无塌陷；`make verify3` 三轮 `stable: true`。

### Tests for User Story 2

- [X] T033 [P] [US2] 编写浏览器检查脚本 `modules/m5-views-console/frontend/verify/run-check.mjs` 与 `verify/playwright.config.ts`：四页 × 两视口断言 console/pageerror/失败请求/404/外网请求/横向溢出/重叠/字体就绪/title/favicon/截图
- [X] T034 [P] [US2] 编写令牌审计脚本 `verify/token-audit.mjs`：从 `tailwind.config.cjs` 提取允许值，扫描 `src/**/*.{vue,ts,css}` 的令牌类与裸颜色字面量，输出违规 JSON；在 `package.json` 增加 `verify:token`/`verify:check` 脚本

### Implementation for User Story 2

- [X] T035 [US2] 实现部署验收脚本 `shared/deploy/verify_deploy.sh`：13 步（前置检查→db up→alembic→固定种子→build→uvicorn PID+trap→health→浏览器→令牌→SQL 核对→降级→证据→清理）、`--repeat/--keep/--json/--evidence-dir/--skip-build` 与退出码（见 [contracts/deployment-verify.md](contracts/deployment-verify.md) §2–§3）
- [X] T036 [US2] 接入 `Makefile` 目标 `verify`/`verify3`/`verify-offline` 并更新 `modules/m5-views-console/README.md` 的部署验收章节（依赖 T005、T035）
- [X] T037 [US2] 实现降级与错误路径 `src/composables/useHealth.ts` + `src/components/OfflineBanner.vue` + `src/App.vue`：`/api/health` degraded/503 时显示全宽提示与重试，保留最近成功数据；对应 data-model.md §3.4 状态机 `degraded`
- [X] T038 [US2] 离线资源与外链清理：核对 `index.html` 与构建产物无 `http(s)://` 外链（字体/图标/logo/favicon），修复遗漏并让 `token-audit`/`run-check` 的 `external_requests` 为 0
- [X] T039 [US2] 端到端跑通 `make verify`：修复所有失败步骤直至退出码 0，生成 `modules/m5-views-console/evidence/deploy/run-1/{deploy-record.json,browser.json,token-audit.json,sql-ui.json,backend.log,screenshots/*}`
- [ ] T040 [US2] 执行 `make verify3`：三轮均 `result=pass` 且 `stable=true`，生成 `evidence/deploy/summary.md`（耗时、失败步骤、种子指纹）— **第 1 轮 13/13 PASS；第 2 轮因 8001 端口被占用在 [0/13] 前置条件失败（环境问题），三轮未跑满，未勾选**
- [X] T041 [US2] 归档部署证据并更新 `docs/screenshots/` 演示图与 `modules/m5-views-console/evidence/README.md` 的"最近验证"时间

**Checkpoint**: US1 + US2 独立可验收——评审按 README 一条命令复现。

---

## Phase 5: User Story 3 - 五模块独立目录与自带验收证据（Priority: P1）

**Goal**: 每个模块目录自包含实现、README 与证据；所有权唯一、共享能力不复制、依赖边界 0 违规；
001 行为无回归。

**Independent Test**: 按任一模块 README 执行命令即可得到该模块证据；`make structure`、
`make boundary`、`tests/test_ownership.py` 全绿；`pytest` 全量通过且接口响应与
`tests/fixtures/api_baseline.json` 一致。

### Tests for User Story 3

- [X] T042 [P] [US3] 编写结构测试 `tests/test_module_structure.py`：五目录命名、README 与 evidence 存在、无 `backend/` 旧目录、无 `scripts/` 残留（结构约定见 [contracts/module-boundaries.md](contracts/module-boundaries.md) §1）
- [X] T043 [P] [US3] 编写所有权测试 `tests/test_ownership.py`：`shared` 只定义一次（脱敏/评分/配置/连接/日志）、迁移与账号矩阵仅在 M1、ER/约束仅在 M3、规则与去重仅在 M4、视图口径仅在 M5

### Implementation for User Story 3

- [X] T044 [US3] 产出 M1 证据：提交前后快照与故障注入回滚、四类账号 GRANT 矩阵、会话查询接口 curl 输出，写入 `modules/m1-transaction-integration/evidence/{transaction,grants,api}.md`
- [X] T045 [P] [US3] 产出 M2 证据：同一会话完整事件日志查询、`explain_diff` 时间线查询对比 JSON，归档到 `modules/m2-decoy-capture/evidence/`（源数据 `evidence/explain/`）
- [X] T046 [P] [US3] 产出 M3 证据：`er/schema.mmd` 渲染图、`tools/introspect_constraints.py` 生成的约束目录对账、主外键/CHECK/UNIQUE 正反样例执行记录，写入 `modules/m3-er-constraints/evidence/`
- [X] T047 [P] [US3] 产出 M4 证据：规则版本与命中记录、意图评分样例、告警去重前后对比（SQL + 输出），写入 `modules/m4-rules-derived/evidence/`
- [X] T048 [US3] 实现 M5 视图口径 `modules/m5-views-console/views/queries.sql`（四视图→用途→页面→口径 + 可执行查询）与只读核对 CLI `modules/m5-views-console/cli/verify_views.py`（支持 `--check-pages`，输出 JSON）
- [X] T049 [US3] 产出 M5 页面-数据库核对证据：概览 KPI、告警统计、攻击者总数/详情画像各 ≥1 组，记录 SQL、SQL 结果与页面值到 `modules/m5-views-console/evidence/sql-ui/checklist.md`
- [X] T050 [US3] 完成五份模块 README（职责/对外契约/依赖/复现命令/证据索引/最近验证）与 `evidence/README.md` 索引；更新 `docs/architecture.md` 的五模块结构图与目录映射
- [X] T051 [US3] 解耦回归：用 T009 基线对比 `/api/*` 响应（字段与语义允许新增、既有字段不变），跑 001 全量测试与四页手工验收，将对比结果写入 `specs/002-ui-console-modularization/checklists/decoupling-regression.md`

**Checkpoint**: 五模块均可独立验收，边界/所有权/回归全绿。

---

## Phase 6: User Story 4 - 页面交互对真实数据生效（Priority: P2）

**Goal**: 所有可交互控件接真实接口并写入 URL 状态；写操作真实落库；禁用控件有明确说明；
无假反馈、无假数字。

**Independent Test**: `verify/interaction-check.mjs` 对每个控件执行一次操作并断言请求与
数据变化；单条/批量已读后刷新保持且审计表新增；无后端能力的控件均为禁用态并带原因。

### Tests for User Story 4

- [X] T052 [P] [US4] 编写交互检查脚本 `modules/m5-views-console/frontend/verify/interaction-check.mjs`：范围切换、列表筛选/排序/分页、告警筛选/页签/时间、单条与批量已读（含 1 条并发已读）、时间线筛选、会话跳转、刷新、禁用控件文案

### Implementation for User Story 4

- [X] T053 [US4] 实现 URL 状态层 `src/router/index.ts` + `src/composables/useQueryState.ts`：筛选/排序/页码/范围双向同步、刷新恢复、非法值回退（状态模型见 data-model.md §3.4，`FilterState` 字段见 §3.3）
- [X] T054 [US4] 首页范围切换真实取数 `src/composables/useOverview.ts` + `src/pages/OverviewPage.vue`：24H/7天/全部写 `range` 并同步 KPI 与趋势、显示当前范围，失败保留旧数据
- [X] T055 [US4] 攻击者列表筛选/排序/分页接线 `src/composables/useAttackers.ts` + `src/pages/AttackersPage.vue`：`q`、风险档、意图、排序（含 `total_connections`）、分页重置与空态
- [X] T056 [US4] 告警筛选/页签/时间预设接线 `src/composables/useAlerts.ts` + `src/pages/AlertsPage.vue`：状态页签计数、4 等级、3 类型、今日/3 天/7 天真实窗口（data-model.md `AlertSummary.by_alert_type`、`AlertSummary.unread_by_severity`）
- [X] T057 [US4] 单条已读 `src/api/index.ts` + `src/components/AlertCard.vue`：真实 PATCH、失败回滚并提示、成功刷新统计与未读徽标，审计记录写入说明保持真实
- [X] T058 [US4] 批量已读 `src/composables/useBatchRead.ts` + `src/pages/AlertsPage.vue`：逐条 PATCH 并发 2、成功/部分失败 Toast（data-model.md `BatchResult.failed`）、失败项保持未读并高亮
- [X] T059 [US4] 时间线筛选与会话证据跳转 `src/components/SessionTimeline.vue` + `src/pages/AttackerDetailPage.vue`：四类筛选、计数一致、告警卡 `查看会话证据` → `/attackers/{ip}?session=` 高亮并过滤
- [X] T060 [US4] 刷新与禁用控件 `src/components/{RefreshButton,IconButton}.vue` + 四页：刷新后更新"最近更新时间"、请求期间 loading；导出/DMZ 隔离/SQL 回放/规则下发等禁用并给"演示未开放"原因
- [X] T061 [US4] 四态统一与交互验收记录 `src/composables/useRequestState.ts` + `modules/m5-views-console/evidence/interactions.md`：每控件记录操作→请求→结果→DB 状态，覆盖空/加载/失败/降级

**Checkpoint**: 每个控件都有真实请求或明确禁用理由；刷新后数据保持。

---

## Phase 7: User Story 5 - 视觉一致性可复核（Priority: P2）

**Goal**: 产出基线截图、区域核对表与令牌抽查记录，评审 10 分钟内复现一致性结论；
界面改动后可重跑。

**Independent Test**: 按 `evidence/visual/review-guide.md` 步骤，用提供的脚本重新采集
截图与抽样并得到同一结论；核对表每项有判定、理由与证据路径。

### Implementation for User Story 5

- [X] T062 [P] [US5] 编写基线采集脚本 `modules/m5-views-console/frontend/verify/capture-baseline.mjs`：固定种子、`document.fonts.ready`、网络空闲、两视口、`{page}-{viewport}.png` 命名与元数据 JSON
- [X] T063 [US5] 采集 8 张基线截图到 `modules/m5-views-console/evidence/visual/baseline/` 并复制到 `docs/screenshots/`，记录种子指纹/日期/视口/构建信息（格式见 data-model.md §6.2）
- [X] T064 [US5] 填写区域核对表 `modules/m5-views-console/evidence/visual/region-checklist.md`：按附录 C 全局壳层 + 四页区域逐项判定（一致/差异/不接受）、理由、令牌与证据链接；一致率 ≥95%
- [X] T065 [US5] 填写令牌抽样记录 `modules/m5-views-console/evidence/visual/token-sampling.md`：每页 20 处（选择器、属性、期望令牌、实际计算值、判定），命中率 100%
- [X] T066 [US5] 编写复核指南 `modules/m5-views-console/evidence/visual/review-guide.md`：10 分钟复核步骤、重跑命令、差异登记规则（引用 ui-contracts §10）

**Checkpoint**: 视觉结论可复现、可追溯到令牌与区域。

---

## Phase 8: User Story 6 - 原型缺陷裁定并统一（Priority: P3）

**Goal**: 跨页制品统一（严重度、编号、圆角、页头、状态块、标题/无障碍），清除死链、
死代码、硬编码数字，附录 B 全部闭环。

**Independent Test**: 按 `evidence/visual/adjudication-checklist.md` 逐条核对；四页壳层
一致、无死链/无硬编码示例值、每页唯一 h1 与正确 aria 标记。

### Implementation for User Story 6

- [X] T067 [US6] 跨页一致性收敛：严重度四色/文案（data-model.md §3.5）、导航 01–04、容器 8px/控件 4px/状态点圆形、页头控件与底部状态块四页统一；修正 `src/components/*` 与四页
- [X] T068 [US6] 无死链与无障碍：导航 `aria-current`、图标按钮 `aria-label`、每页唯一 `<h1>`、焦点可见、`prefers-reduced-motion` 关闭脉冲动画；修正 `src/App.vue`、`src/router/index.ts` 与全部组件
- [X] T069 [US6] 清除硬编码演示数字与自相矛盾数据：扫描 `src/**/*.vue|ts` 的示例数值/日期/编号，全部改为接口/视图值；`—` 表示无数据
- [X] T070 [US6] 每页 title/favicon/导航激活最终核对（4 路由 × 2 视口，断言见 ui-contracts §2），修正 `index.html`、`router/index.ts`、`public/favicons/*`
- [X] T071 [US6] 原型差异闭环表 `modules/m5-views-console/evidence/visual/adjudication-checklist.md`：附录 B 20 条 + 补充 21–28 逐条给出落地位置与验证方式；未闭环项修复
- [X] T072 [US6] 未支持控件与说明文案最终统一（导出 JSON/CSV、DMZ 隔离、证据链下发、SQL 回放、AI 标识）：禁用状态、`title`/可见说明一致，无"点击无反应"

**Checkpoint**: 四页作为一套系统；所有差异有登记、所有控件有反馈。

---

## Phase 10: 主题（浅色/深色，追加需求 FR-133、FR-134）

> 用户追加需求：参考 `ux/stitch_database_honeypot_analytics_console_light/` 实现跟随系统的
> 浅色/深色主题，页头圆角矩形按钮实时切换。契约见 `contracts/ui-contracts.md` §12。

- [X] T080 将 `tailwind.config.js` 颜色令牌映射为 CSS 变量，在 `src/assets/main.css` 定义深色 `:root`
  与浅色 `html.light` 两套 `--c-*`、`--chart-*`、`--shadow-panel` 令牌（浅色取值来自 light 原型）
- [X] T081 新增 `src/composables/theme.ts`：三态（system/light/dark）、`matchMedia` 实时跟随、
  `localStorage["dbh-theme"]` 持久化、`initTheme()` 幂等初始化
- [X] T082 页头新增 `data-theme-toggle` 圆角矩形按钮（循环三态、aria-label/title 明示当前与下一步），
  `index.html` 内联引导脚本 + `main.ts` 挂载前初始化，消除首屏闪烁
- [X] T083 图表与内联样式主题化：`TrendChart`（渐变/网格/轴线/峰值提示）、`IntentDonut`（轨道/中心字/扇区）、
  概览意图配色、Logo 全部改用主题变量；`verify/token-audit.mjs` 增加双主题令牌对账并放行 `rgb(var(--*))`
- [X] T084 验证脚本支持主题：`verify/capture-baseline.mjs --theme` 产出深/浅基线截图，
  `verify/run-check.mjs` 新增系统实时跟随、三态循环、持久化/刷新保持与四页浅色渲染检查（`browser.json`）
- [X] T085 更新 `spec.md` FR-133/134、`contracts/ui-contracts.md` §12、demo/README 与
  `modules/m5-views-console/evidence/visual/` 主题证据，重跑 token-audit + 浏览器验收

## Phase 9: Polish & 跨故事收尾

**Purpose**: 文档漂移修正、性能/安全复核、全量验收。

- [X] T073 [P] 更新 `docs/architecture.md`（五模块图 + 目录映射）与 `docs/database-design.md`（ER 改为引用 M3 源文件，删除重复 Mermaid）
- [X] T074 [P] 更新 `docs/demo-script.md`（新截图/交互/证据路径）与 `docs/test-plan.md`（用例数改为实际统计，补充 002 验收场景），刷新 `docs/screenshots/README.md`
- [X] T075 [P] 最终核对 `README.md`、`compose.yaml` 注释、`.env.example`、`Makefile` 与新目录一致；`rg "backend/|frontend/" docs README.md` 仅剩历史说明
- [X] T076 性能基线验证并记录 `modules/m5-views-console/evidence/deploy/performance.md`：接口 p95 ≤500ms、页面切换 ≤1s、构建 JS gzip ≤1.2MB、`make verify` ≤10min（R-15）
- [X] T077 安全复核 `modules/m1-transaction-integration/evidence/security-review.md`：无明文密钥、查询参数化、控制台只读账号 GRANT、脱敏/掩码、禁用主动反制、审计写入；逐项给出证据
- [X] T078 执行 [quickstart.md](quickstart.md) V00–V14 全场景并填写 `specs/002-ui-console-modularization/checklists/acceptance.md`（场景、命令、结果、证据路径、SC 映射）
- [ ] T079 最终门禁：`uv sync`、`pytest`、`ruff`、`make structure`、`make boundary`、`make frontend-build`、`make verify3` 全部通过；清理临时产物，按中文 Conventional Commits 拆分提交建议 — **已通过 pytest 270+30、ruff、structure 39/0/0、boundary、frontend-build、`make verify` 13/13；仅 `verify3` 三轮未跑满（第 2 轮端口占用），未勾选**

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，可立即开始；T001–T009 内部多数可并行
- **Foundational (Phase 2)**: 依赖 Setup；**阻塞所有用户故事**。T010–T015 是文件搬迁，
  须按 T010 → T011/T012/T013/T014/T015 顺序（共享平台先行），T016–T018 依搬迁完成
- **User Stories (Phase 3–8)**: 均依赖 Foundational 完成
- **Polish (Phase 9)**: 依赖所需用户故事完成

### User Story Dependencies

- **US1 (P1)**: Foundational 后可开始；无其他故事依赖。**MVP 交付点**
- **US2 (P1)**: 依赖 US1（需要四页与构建产物）；其浏览器/令牌脚本可先写、后联调
- **US3 (P1)**: M1–M4 证据可在 Foundational 后立即进行；M5 视图口径/SQL-UI 核对依赖 US1
  页面；回归对比依赖 T009 基线。建议在 US1 完成后收尾
- **US4 (P2)**: 依赖 US1；与 US2 可部分并行（文件不重叠：US2 改 `verify/` 与
  `shared/deploy/`，US4 改 `src/composables|pages`），但 US2 的交互断言需 US4 完成后补跑
- **US5 (P2)**: 依赖 US1、US2（截图工具链）与 US4（最终交互态）；US6 依赖 US5 的核对表
- **US6 (P3)**: 依赖 US1、US4、US5
- **Polish**: 依赖全部故事

### Within Each User Story

1. 测试先行（T019/T033–T034/T042–T043/T052 先写并确认失败）；
2. 后端/数据层 → 前端展示 → 交互接线 → 证据；
3. 同一文件中不并行（四页共享 `App.vue`、`router`、`api/client` 的任务串行）；
4. 每阶段结束跑门禁：`pytest` + `ruff` + `build` + `make boundary`。

### Parallel Opportunities

- Setup：T003/T004/T005/T006/T007/T008 可并行（不同文件）；T001/T002/T009 串行
- Foundational：T012/T013/T014/T015 可并行（不同模块目录）；T010 与 T011 串行、
  T016 依赖 T010–T015、T017 可与 T016 并行、T018 最后
- US1：T026/T027 可并行（组件/图表不同文件）；T019–T025 串行；T028–T031 四页可在
  T025/T026/T027 完成后并行（不同页面文件）
- US2：T033/T034 可并行
- US3：T045/T046/T047 可并行（不同模块证据）
- US4：T052 先写；T054/T055/T056/T057/T058/T059 可由不同人并行（不同页面/composable）
- US5：T062 完成后 T063–T066 串行（同一证据目录）
- Polish：T073/T074/T075 可并行

---

## Parallel Example: User Story 1

```bash
# 基础组件与图表（不同文件，可并行）
Task: "实现基础展示组件 src/components/{PageHeader,KpiCard,...}.vue"
Task: "实现 SVG 图表 src/components/{TrendChart,IntentDonut,Sparkline}.vue"

# 四页（在壳层/组件/图表完成后并行）
Task: "实现首页概览 src/pages/OverviewPage.vue"
Task: "实现攻击者列表 src/pages/AttackersPage.vue"
Task: "实现详情与时间线 src/pages/AttackerDetailPage.vue"
Task: "实现告警列表 src/pages/AlertsPage.vue"
```

## Parallel Example: Foundational

```bash
# 模块搬迁（不同目录，可并行）
Task: "迁移 M2 到 modules/m2-decoy-capture/"
Task: "迁移 M3 到 modules/m3-er-constraints/"
Task: "迁移 M4 到 modules/m4-rules-derived/"
Task: "迁移 M5 前端到 modules/m5-views-console/frontend/"
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. 完成 Phase 1 Setup 与 Phase 2 Foundational；
2. 完成 Phase 3 US1（含新增聚合接口）；
3. **STOP and VALIDATE**：四页对照原型与附录 C 区域清单、契约测试通过；
4. 可先演示视觉成果（P1 首要诉求），再继续部署测试。

### Incremental Delivery

1. Foundational → 结构可评审（US3 部分能力已具备）
2. + US1 → 视觉 MVP，可演示四页
3. + US2 → 一条命令部署验收 + 三轮截图证据
4. + US3 → 五模块证据与所有权闭环（SC-021/022/023）
5. + US4 → 交互真实化（SC-025）
6. + US5 → 视觉可复核（SC-018/019）
7. + US6 → 跨页统一与附录 B 闭环
8. Polish → 文档/性能/安全/quickstart 全量验收

### Notes

- [P] = 不同文件且无未完成依赖；同一文件（`App.vue`、`router`、`api/client`）不并行
- 每阶段结束执行：`uv run pytest -q`、`uv run ruff check .`、`corepack pnpm --dir modules/m5-views-console/frontend build`、`make boundary`
- 涉及数据库的测试一律使用真实 MySQL（宪法原则五），先置 `make db-up && make migrate`
- 证据文件随任务生成，不要最后补写；时间统一 UTC+8 展示、ISO8601 记录
- 提交按任务组小步进行，使用中文 Conventional Commits（如 `refactor(modules): 迁移 M2 至独立目录`）
