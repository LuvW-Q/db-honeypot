# Implementation Plan: 控制台视觉重构与模块解耦

**Branch**: `002-ui-console-modularization` | **Date**: 2026-11-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-ui-console-modularization/spec.md`

## Summary

本计划同时交付两件事：

1. **控制台视觉重构**：按 `ux/stitch_database_honeypot_analytics_console/` 的深色
   "cyber terminal" M3 原型，把现有 Vue 3 控制台从 Element Plus 浅色主题改造为
   Tailwind 令牌驱动的深色控制台：固定侧栏、固定页头、四页（概览、攻击者列表、
   攻击者详情与时间线、告警列表）逐区域对齐原型；字体、图标、Logo 全部本地自托管；
   图表改为自研 SVG；所有交互接真实接口（时间范围、筛选、排序、分页、刷新、
   告警已读与批量已读），无数据支撑的控件置灰并说明，禁止假反馈与硬编码演示数字。
2. **五模块解耦**：把现有 `backend/`、`frontend/`、`db/`、`scripts/` 迁移为
   `modules/m1-transaction-integration`、`m2-decoy-capture`、`m3-er-constraints`、
   `m4-rules-derived`、`m5-views-console` 五个自包含目录 + `shared/` 共享平台，
   以单发行版多包（根 `pyproject.toml`）运行，依赖方向固定且无环，并提供自动化
   边界检查；每模块自带 README 与可独立复现的验收证据。

验收以**真实部署路径**（生产构建产物由后端统一托管、单地址）为准：`make verify`
一条命令完成数据库准备 → 迁移 → 固定种子数据 → 前端构建 → 启动 → Playwright
四页两视口检查 → 令牌审计 → 页面-数据库核对 → 降级验证 → 截图与报告；
连续三次运行稳定（SC-024）。视觉证据采用"自动检查 + 令牌审计 + 人工区域核对表"
三层，区域一致率目标 ≥95%，差异全部登记（附录 B，含实现期补充 21–28）。

技术路线（Phase 0 结论）：保留 Vue 3.5 + Vite 8 + TypeScript + hash 路由，引入
Tailwind CSS 3.4 按原型配置复刻令牌，移除 Element Plus 与 ECharts，自研组件与
SVG 图表；后端接口只做加法（2 个新聚合端点 + 若干可选字段），数据库 DDL 与视图
不变；模块以根 `pyproject.toml`（hatchling）统一安装，入口改为
`uvicorn m1_transaction_integration.api.app:create_app --factory`。

## Technical Context

**Language/Version**: Python 3.14.4（`requires-python >= 3.11`，沿用 001 已核实依赖
wheel）；TypeScript 5.9；Node 24 LTS；pnpm 12（经 corepack 调用）

**Primary Dependencies**:
- 后端（不变，版本锁定）：FastAPI 0.165、Uvicorn 0.54、Pydantic 2.14、
  pydantic-settings 2.16、SQLAlchemy 2.1.9（async）、asyncmy 0.2.18、Alembic 1.20.1、
  mysql-mimic 3.0.5、structlog 26.1、cryptography ≥45
- 前端（调整）：Vue 3.5、Vite 8、TypeScript 5.9、Tailwind CSS 3.4.19 + PostCSS 8 +
  autoprefixer 10、`@fontsource-variable/inter` 5.3.0、
  `@fontsource-variable/jetbrains-mono` 5.3.0、`material-symbols` 0.49.0；
  **移除** `element-plus` 2.14、`echarts` 6
- 验证工具（新增 devDependency）：`@playwright/test` 1.65.1（Chromium，或本机 Chrome）
- 构建/打包：hatchling（根 `pyproject.toml`，多包路径映射）；uv 管理虚拟环境与锁文件

**Storage**: MySQL 8.0.46（本机）/ 8.4 LTS（目标），InnoDB、utf8mb4、UTC、
`DATETIME(6)`；**11 张表、10 个外键、12 个唯一约束、4 个分析视图、5 条规则
全部不变**（本 feature 无 DDL 变更）；账号仍为 migrate / app_rw / app_ro / backup
四类，控制台经只读账号访问

**Testing**:
- 后端：pytest 9.2 + pytest-asyncio 1.5 + httpx 0.28，真实 MySQL 集成测试（禁止
  数据库 Mock）；覆盖约束、事务回滚、幂等、迁移往返、视图、规则与新增接口
- 前端验收：Playwright 1.65.1 真实浏览器（四页 × 1440×900/1920×1080），断言
  console 错误、失败请求、404、外网请求、横向溢出、字体就绪、标题/favicon、
  交互与降级
- 静态检查：ruff 0.17.5、`vue-tsc`（构建期类型检查）、令牌审计（Node 脚本）、
  依赖边界检查（AST，`shared/deploy/boundary_check.py`）、结构检查
- 证据：每模块 `evidence/README.md` 含可运行命令与期望输出；部署三轮 + 截图

**Target Platform**: macOS / Linux 单机或虚拟机；Docker Compose v2 运行 MySQL 8，
后端以宿主进程（uvicorn）托管前端 `dist` 并以单一地址对外；仅在授权隔离实验网络运行

**Project Type**: Web application（FastAPI 后端 + Vue SPA）+ 独立 TCP 诱饵服务，
仓库采用"单发行版 + 五模块目录 + 共享平台"结构

**Performance Goals**:
- 控制台只读接口本机 p95 ≤ 500 ms；新增聚合端点同等要求
- 页面间切换 ≤ 1 s；首屏可用 ≤ 2 s（固定种子数据、本机）
- 部署验收全流程（含前端构建，不含依赖下载）≤ 10 min；浏览器检查 ≤ 3 min
- 前端首屏 JS（不含字体/图标字体）gzip ≤ 1.2 MB；运行期外网请求 0

**Constraints**:
- 断网可运行：无 CDN、无公网字体/图标/Logo/脚本（FR-106、SC-026）
- 单地址部署：后端托管生产构建产物；不引入 nginx/额外容器（R-10）
- 控制台只读为主：唯一写操作为告警已读（单条 PATCH 复用，批量逐条）
- 数据库 DDL 不变；接口只做加法；001 测试与行为不回归（FR-123）
- 中文文档与代码注释；敏感信息不入库/不入日志/不展示
- 课程规模：固定种子数据 < 1 万事件；不设高并发目标
- 模块边界：五目录自包含、依赖无环、只经公开契约协作（FR-114–123）

**Scale/Scope**: 5 个业务模块 + `shared/`；约 70 个文件搬迁；4 个控制台页面、
约 20 个自研组件、2 个 SVG 图表；2 个新端点 + 4 个扩展端点；8 张基线截图；
5 份模块证据索引；1 个部署验收脚本与 1 套浏览器/令牌检查工具

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法条款 | 计划中的落地方式 | 状态 |
| --- | --- | --- |
| 一、文档与注释完备（中文优先） | 本计划、research、data-model、contracts、quickstart 全部中文；模块 README、证据索引、区域核对表、令牌说明均为中文；新增代码中文注释并标注安全假设；DESIGN.md 重写为深色语义镜像 | PASS |
| 二、数据库设计优先（Schema 即契约） | **本 feature 明示不修改 DDL**（11 表/4 视图/约束/索引不变）；接口扩展只读既有表与视图；M3 将 ER 源文件与约束目录迁入模块并保持与 DDL 一致；新增聚合 SQL 记录 EXPLAIN | PASS |
| 三、安全与最小权限 | 控制台仍用 `app_ro` 只读连接；唯一写路径沿用 `app_rw` 单事务 + 审计；脱敏横幅、口令掩码、用户名掩码保留；查询全部参数化并设时间窗口/`LIMIT` 上界；账号矩阵不变（FR-132） | PASS |
| 四、事务完整性与鲁棒性 | 事件写入事务与幂等键不变（搬迁不改语义）；告警已读单事务 `FOR UPDATE`；批量已读逐条写、部分失败可见；聚合查询有界；迁移可往返；降级路径有明确提示 | PASS |
| 五、测试先行与可验证性 | 搬迁阶段以 001 全量测试为回归门禁；新增接口先补契约/兼容性测试；前端以真实浏览器验收（非 Mock）；每模块证据可独立复现；三轮部署稳定 | PASS |
| 技术栈与工程约束 | 所有新依赖（Tailwind、字体、图标、Playwright）记录于本计划与 research 并锁定版本；协议层/持久化层解耦保持；不再引入未记录依赖；性能基线已定义 | PASS |
| 开发工作流与质量门禁 | 六阶段推进，每阶段过 `pytest + ruff + build + make boundary`；ER/DDL 一致性、迁移往返、安全用例、中文注释、无明文密钥五项合并门禁；设计变更回到对应阶段 | PASS |

**结论**：Phase 0 前检查通过，无违反项，无需在 Complexity Tracking 中申请豁免。

## Project Structure

### Documentation (this feature)

```text
specs/002-ui-console-modularization/
├── spec.md              # 功能规格（已完成）
├── plan.md              # 本文件
├── research.md          # Phase 0 技术决策（R-01 – R-15）
├── data-model.md        # Phase 1 结构/前端/接口增量/令牌/证据模型
├── quickstart.md        # Phase 1 验证指南（V00 – V14）
├── contracts/
│   ├── api-extensions.md    # 接口增量契约
│   ├── module-boundaries.md # 模块目录/公开入口/依赖矩阵/搬迁映射/检查脚本
│   ├── ui-contracts.md      # 壳层/路由/区域/组件/交互/禁用/格式化/离线
│   └── deployment-verify.md # 部署验收脚本契约
├── checklists/
│   └── requirements.md  # 规格质量清单（已完成）
└── tasks.md             # Phase 2 由 /speckit-tasks 生成
```

### Source Code (repository root)

```text
pyproject.toml                 # 单发行版：shared + 5 模块多包映射，uv/hatchling
alembic.ini                    # script_location = modules/m1-transaction-integration/migrations
Makefile                       # env/db/migrate/seed/api/honeypot/build/test/lint/boundary/structure/verify
compose.yaml                   # 仅 MySQL 8（部署模型修正为"容器数据库 + 宿主后端"）
.env.example                   # WEB_DIST_DIR 等更新为模块路径
README.md
conftest.py                    # 全局 pytest fixtures（真实 MySQL、测试库）
tests/                         # 跨模块契约/结构/边界检查测试
└── support.py

shared/                        # 共享平台（不承载业务）
├── shared/
│   ├── config.py              # 配置与仓库根/静态目录解析
│   ├── logging.py
│   ├── db/{base,session}.py
│   ├── models/                # 11 张表 + 4 视图的 SQLAlchemy 映射（schema 契约）
│   ├── events/{schema,builder}.py   # 标准事件契约与构造
│   ├── schemas/common.py
│   ├── data/query.py          # 通用只读查询/参数校验工具
│   ├── utils/{masking,sql}.py
│   └── deploy/                # verify_deploy.sh、boundary_check.py、check_structure.py、demo.sh
└── tests/unit/                # masking / sql 归一化 / event_builder

modules/
├── m1-transaction-integration/
│   ├── README.md              # 职责、公开入口、复现命令、证据索引
│   ├── m1_transaction_integration/
│   │   ├── public.py          # ingest_event / reset_demo（唯一对外入口）
│   │   ├── api/{app,deps,errors,routes/*}.py
│   │   ├── schemas/api.py
│   │   ├── repositories/{alert,attacker,audit,overview,session}_repo.py
│   │   ├── services/{ingest,audit,reset,session_manager,ai_assistant}.py
│   │   └── cli/{verify_transaction,reset_demo}.py
│   ├── migrations/{env.py,script.py.mako,versions/0001–0004}
│   ├── db/init/01-init-databases.sh + db/grants/apply_table_grants.sh
│   ├── tests/{api/*,integration/{transaction_rollback,idempotency,migrations}}
│   └── evidence/              # 提交/回滚、账号职责、会话查询接口证据
├── m2-decoy-capture/
│   ├── m2_decoy_capture/{server,session,auth,emitter,fake_catalog}.py + public.py
│   ├── cli/{simulate_traffic,import_samples,gen_demo_data,explain_diff,seed_decoy}.py
│   ├── samples/catalog.py     # S01–S07 与 demo_basic/recon_only
│   ├── docs/explain-indexes.md
│   ├── tests/unit/test_fake_catalog.py
│   └── evidence/              # 会话事件日志、EXPLAIN 对比
├── m3-er-constraints/
│   ├── er/schema.mmd          # ER 源文件（与 DDL 一致）
│   ├── constraints/{catalog.md,verify_constraints.sql}
│   ├── tools/introspect_constraints.py
│   ├── tests/integration/test_constraints_fk.py
│   └── evidence/              # ER、主外键/CHECK/UNIQUE 正反样例
├── m4-rules-derived/
│   ├── m4_rules_derived/{public,rules/*,analysis,risk,alerts}.py
│   ├── repositories/rule_repo.py
│   ├── tests/{unit/{rules,risk},integration/analysis_pipeline,api/test_rules}
│   └── evidence/              # 规则版本与命中、意图评分、告警去重
└── m5-views-console/
    ├── views/queries.sql      # 视图→用途→页面→口径 与可执行查询
    ├── cli/verify_views.py    # 只读核对（含 --check-pages）
    ├── frontend/
    │   ├── package.json / vite.config.ts / tailwind.config.cjs / postcss.config.cjs
    │   ├── index.html + public/favicons/*
    │   ├── verify/{run-check.mjs,token-audit.mjs,playwright.config.ts}
    │   └── src/
    │       ├── main.ts / App.vue / router/index.ts / types/
    │       ├── styles/base.css
    │       ├── api/{client,index}.ts
    │       ├── composables/{useOverview,useAttackers,useAlerts,useHealth}.ts
    │       ├── components/    # PageHeader/KpiCard/RiskBadge/TrendChart/…（约 20 个）
    │       └── pages/{Overview,Attackers,AttackerDetail,Alerts}Page.vue
    ├── tests/integration/test_views.py
    ├── evidence/{visual,deploy,sql-ui}/
    └── README.md

ux/                            # 原型输入（只读，不参与构建）
docs/                          # 架构、数据库设计、演示脚本、测试计划、索引验证、截图
db/                            # 仅保留容器初始化与 EXPLAIN 说明的跳转（实际脚本在 M1/M2）
```

**Structure Decision**：采用"单发行版 + 五模块目录 + 共享平台"的 monorepo。根
`pyproject.toml`（hatchling）把 `shared` 与五个模块内包（`m1_transaction_integration`
… `m5_views_console`）纳入同一可编辑安装，避免六份依赖图；目录名使用 spec 规定的
连字符命名，Python 包名改为下划线。`shared/` 只承载 FR-116 所列公共能力；M3 不提供
运行时包，以 ER/SQL/测试作为交付物。前端位于 M5，由 M1 的 FastAPI 按
`WEB_DIST_DIR` 托管静态产物，形成单地址部署。该结构直接对应 FR-114–123 的所有权与
依赖约定，并让每模块 README 能独立复现证据（SC-021）。

## Phase 0：研究与决策

已完成，输出 [research.md](./research.md)，15 条决策全部落定，无 `NEEDS CLARIFICATION`：

| 编号 | 决策要点 |
| --- | --- |
| R-01 | Vue 3 + Vite 8 + Tailwind 3.4 自研组件；移除 Element Plus 与 ECharts |
| R-02 | `tailwind.config.cjs` 为令牌唯一数值源，DESIGN.md 重写为深色语义镜像 |
| R-03 | 字体/图标/Logo 全部本地自托管（@fontsource + material-symbols） |
| R-04 | SVG 自研趋势与环图，数据来自扩展后的趋势/规则效果接口 |
| R-05 | 接口只做加法：2 个新端点 + 4 个扩展端点，DDL 不变 |
| R-06 | 批量已读 = 客户端逐条 PATCH（并发 2）+ 部分失败反馈 |
| R-07 | 侧栏 03 记忆最近访问 IP，无记录时禁用并提示 |
| R-08 | 单发行版多包 + 五模块目录 + shared；根 pyproject/alembic.ini |
| R-09 | AST 依赖边界检查 + 允许矩阵，违规即失败（make boundary） |
| R-10 | MySQL 容器 + 宿主 uvicorn 托管 dist；`make verify` 一条命令 |
| R-11 | 视觉验收三层：浏览器自动检查 + 令牌审计 + 人工区域核对表 |
| R-12 | 固定种子数据序列（reset → 合成规模 → demo_basic） |
| R-13 | 原型差异补充登记 8 条，写入 spec 附录 B（21–28） |
| R-14 | 六阶段推进，每阶段全绿门禁；搬迁单独提交 |
| R-15 | 性能/规模基线：接口 p95 ≤500ms、切换 ≤1s、部署 ≤10min |

依赖版本锁定表与风险缓解见 research.md 末尾。

## Phase 1：设计与契约

1. **数据模型** → [data-model.md](./data-model.md)：范围与不变声明、模块/依赖矩阵、
   前端路由/区域/类型/交互状态、接口增量字段、令牌模型、证据与基线模型、
   14 条可执行校验规则、与 001 数据库实体关系、FR 映射。
2. **接口契约** → [contracts/api-extensions.md](./contracts/api-extensions.md)：
   时间范围与今日口径、"今日"UTC+8 语义、派生字段、新端点与扩展字段的完整校验、
   示例、兼容性规则、错误码、查询边界。
3. **模块边界契约** → [contracts/module-boundaries.md](./contracts/module-boundaries.md)：
   目录/包命名、公开入口签名、依赖矩阵、`git mv` 映射（7 组）、数据模型变更流程、
   边界检查脚本的输入输出与 6 类检查项、自测要求。
4. **UI 契约** → [contracts/ui-contracts.md](./contracts/ui-contracts.md)：壳层尺寸、
   路由元数据（title/favicon/激活导航/hash query）、四页区域清单与核对点、
   组件契约、禁用控件清单、交互语义（含批量已读部分失败）、格式化、可访问性、
   离线要求、区域判定与 95% 计算方式、附录 B 落地映射。
5. **部署验收契约** → [contracts/deployment-verify.md](./contracts/deployment-verify.md)：
   前置条件、脚本选项、13 个步骤与耗时预算、浏览器检查项、三轮一致性方法、
   令牌审计规则、产物结构与 JSON schema、退出码、证据联动。
6. **验证指南** → [quickstart.md](./quickstart.md)：V00–V14 场景（环境、迁移往返、
   固定种子、部署、视觉、跨页一致、SQL 核对、真实交互、四态、断网、五模块证据、
   边界反向验证、001 回归、三轮、文档闭环）与 SC/FR 映射。

### 设计后宪法复核

| 宪法条款 | Phase 1 设计证据 | 状态 |
| --- | --- | --- |
| 一、文档与注释 | 五份设计产出全中文；UI 契约含中文文案与说明；模块 README/证据索引模板明确中文要求 | PASS |
| 二、Schema 即契约 | data-model §1 明确无 DDL 变更；接口增量只读既有表/视图；M3 ER 与约束目录要求与 DDL 对账；新增聚合 SQL 要求 EXPLAIN | PASS |
| 三、安全与最小权限 | 只读账号、脱敏横幅/掩码、参数化与有界查询、禁用主动反制控件、账号矩阵不变 | PASS |
| 四、事务与鲁棒性 | 写路径不变；批量已读逐条事务 + 部分失败；聚合窗口上界；降级与空态契约 | PASS |
| 五、测试与可验证性 | V00–V14 覆盖全部 SC；浏览器真实验收；模块证据独立复现；三轮稳定；边界/令牌/结构自动检查 | PASS |
| 技术栈与工程约束 | 版本锁定表；无未记录依赖；协议层/持久化层保持解耦；性能基线定义 | PASS |
| 工作流与门禁 | 六阶段门禁；文档漂移修正清单（见"实施阶段"§6）；合并五项门禁 | PASS |

**结论**：设计后复核通过，无违反项。

## 实施阶段与顺序（供 `/speckit-tasks` 生成依赖）

| 阶段 | 内容 | 门禁/产出 |
| --- | --- | --- |
| 1. 结构搬迁 | 根 `pyproject.toml`/`alembic.ini`/`conftest.py`；`git mv` 五模块 + shared；导入重写；入口/配置/Makefile/compose 路径；边界/结构检查脚本与自测 | `pytest` 全绿、`ruff`、`make boundary`、`make structure`；功能零变化 |
| 2. M1 接口扩展 | 聚合 SQL 与仓储；`/api/alerts/summary`、`/api/attackers/summary`；overview/trend/attackers/detail 字段扩展；兼容性测试与 EXPLAIN 记录 | 001 全部接口测试通过 + 新契约测试通过；p95 达标 |
| 3. M5 前端重写 | 令牌配置与基础样式；壳层；四页；约 20 组件；SVG 图表；交互与四态；路由元数据 | `vue-tsc` + build 通过；手工冒烟四页 |
| 4. 验证工具链 | Playwright 检查脚本、令牌审计、截图、`verify_deploy.sh`、`make verify/verify3` | `make verify` 通过、三轮稳定 |
| 5. 证据与文档 | 五模块 README/证据；ER 源与约束样例；EXPLAIN 归档；管线图；spec 附录 B 补充；001 文档/Makefile/README/compose 漂移修正 | V10/V14 清单全勾选；`rg` 无旧路径残留 |
| 6. 回归与验收 | 001 全量测试；四页流程；SC-016–028 逐条核对；quickstart 三连跑；演示脚本更新 | quickstart 全通过；验收报告 |

**实现期必须修正的既有漂移**（来自 001 实际状态）：`Makefile` 的 `UV` 绝对路径
（改为 `command -v uv` + 可覆盖变量）；`compose.yaml` 与 001 plan/README 描述不一致
（统一为"容器 MySQL + 宿主后端"）；`docs/test-plan.md` 声称 225 用例而实际 156
个测试函数（按实际统计修正）；视图证据只覆盖 2 条查询（补齐 4 个视图到 M5 证据）；
R06–R08 未实现（界面对应能力禁用/不展示，附录 B 已覆盖）；无规则配置页面（不新增
导航，规则能力经 API 演示）；`backend/.venv`、`frontend/node_modules`、`dist` 缺失
（按 quickstart V00 安装后构建）。

## Complexity Tracking

无宪法违反项，不需要豁免。以下复杂度为满足 spec 所必需，已在 research.md 说明取舍：

| 复杂度 | 必要性 | 更简方案未采用的原因 |
| --- | --- | --- |
| 单发行版多包（6 个包路径映射） | FR-114/115 要求五模块自包含且可运行，同时保持一次安装 | 六份 `pyproject.toml` + path 依赖会形成 6 个依赖图，课程规模维护成本过高；仅移动部分文件则违反自包含 |
| 约 70 个文件 `git mv` 与导入重写 | 解耦是本 feature 的核心目标（SC-021/022） | 保留 `backend/app` 分层再"镜像"目录会形成双份代码与所有权混乱 |
| 新增 2 个聚合端点 + 4 个端点字段扩展 | 原型统计（未读数、今日新增、解决率、高风险占比、平均时长、意图族趋势）无法由分页列表在客户端正确汇总 | 前端多请求拼装会因分页截断产生错误数字，且首屏请求数不可控 |
| Playwright + Node 验证工具链 | FR-109/SC-016/017/026 要求可自动化真实浏览器验收与断网证据 | 纯手工检查不可重复、无法自动发现 console 错误/溢出/外网请求；SC-024 要求三轮稳定 |
| 自研 SVG 图表替代 ECharts | 原型为手写 SVG，区域一致性与截图/缩放稳定性要求高 | ECharts 主题映射成本高、体积大，Canvas 渲染与原型差异难以逐区域对齐 |
| Tailwind 静态构建 + 自托管字体/图标 | 原型为 Tailwind utility + 自定义 token，且必须离线（FR-106） | Element Plus 暗色覆盖无法逐区域对齐且形成两套取值来源；CDN 字体违反断网要求 |
| 五模块证据目录与独立复现命令 | SC-021/028 要求评审可在 10 分钟内独立复现每个模块 | 仅保留全仓测试无法证明"模块自包含"与所有权唯一 |
| 三轮部署 + 区域几何/骨架一致性 | SC-024 明确要求重复执行稳定 | 单次运行无法证明可重复；像素 diff 因数据/尺寸差异不可行 |

## 风险与缓解（摘要）

| 风险 | 缓解 |
| --- | --- |
| 依赖安装需网络（npm/Playwright 浏览器） | 写入前置条件；Playwright 支持本机 Chrome 回退 |
| 大规模搬迁导致导入断裂 | 阶段 1 单独提交、测试全绿门禁、旧前缀扫描 |
| Tailwind 3 与 Vite 8 构建冲突 | 锁版本；冲突时升级 Tailwind 4 并记录变更 |
| 原型数据/控件与真实口径冲突 | 附录 B 补充 21–28 + 禁用/派生策略；区域核对表登记差异 |
| 新增聚合 SQL 拖慢接口 | 复用视图与既有索引、窗口上界、EXPLAIN 记录、p95 验证 |
| 截图受字体/滚动条影响 | 固定视口/缩放、等待字体与网络空闲、三轮骨架比对 |
| HB 体积（Material Symbols） | 仅本地演示；不纳入 JS 体积基线 |

## 后续阶段

- **Phase 2**：运行 `/speckit-tasks`，依据本计划、data-model、四份契约与 quickstart
  生成依赖有序的 `tasks.md`（按上述六阶段组织，含文档同步与证据任务）。
- **实现顺序**：结构搬迁 → M1 接口扩展 → M5 前端重写 → 验证工具链 → 证据与文档 →
  回归验收；每阶段以门禁全绿为进入下一阶段的条件。
- **验收**：以 spec.md 的 SC-016 至 SC-028 与 quickstart V00–V14 为准；部署验收证据
  留存于各模块 `evidence/` 与 `docs/`。
