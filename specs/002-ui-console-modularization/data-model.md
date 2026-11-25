# Phase 1 数据模型：控制台视觉重构与模块解耦

**Feature**: `002-ui-console-modularization` | **Date**: 2026-11-25 | **Spec**: [spec.md](./spec.md)

本文件定义本 feature 的**结构实体、前端领域模型、接口增量字段、设计令牌与证据模型**。
数据库实体（11 张表、4 个视图、10 个外键、12 个唯一约束）沿用 001，本 feature
**不新增、不修改任何 DDL**；ER 图与约束的权威源仍为
`specs/001-database-honeypot/data-model.md`，M3 在实现阶段将其 ER 源文件与约束用例
迁入模块目录并保持与 DDL 一致（FR-126）。

---

## 1. 范围与不变声明

| 项 | 本 feature 的处理 | 依据 |
| --- | --- | --- |
| 数据库表 / 列 / 约束 / 索引 | **不变**；不新增迁移 | 宪法二、FR-119 |
| 视图 `v_session_risk_summary` 等 4 个 | **不变**；M5 只引用并文档化口径 | FR-119、FR-128 |
| 种子规则 R01–R05 | **不变**；M4 证据复用既有版本与命中 | FR-127 |
| HTTP 接口既有字段 | **不变**；只做加法（可选新字段 + 新端点） | FR-123、SC-023 |
| 唯一写接口 | 仍为 `PATCH /api/alerts/{alert_id}` | FR-103、001 契约 3.7 |
| 事件写入事务与幂等 | **不变**；搬迁后入口保持单一事务 | 宪法四、FR-118 |

> 任何实现期发现必须改 DDL 的诉求，按 FR-120 回到 M3 设计 → M1 迁移 → 再实施；
> 本计划不包含此类变更。

---

## 2. 结构实体：模块、包与依赖

### 2.1 模块实体

| 实体 | 目录 | Python 导入名 | 职责（唯一所有权） | 对外公开面 |
| --- | --- | --- | --- | --- |
| M1 事务写入与接口集成 | `modules/m1-transaction-integration/` | `m1_transaction_integration` | 迁移、账号权限、事务入口（事件写入/重置）、REST 接口与查询仓储、审计写入 | `public.ingest_event()`、`public.write_audit()`、FastAPI `create_app()`、CLI `verify_transaction`/`reset_demo`、Alembic 迁移目录 |
| M2 诱饵交互与事件采集 | `modules/m2-decoy-capture/` | `m2_decoy_capture` | MySQL 协议模拟、会话与伪造目录、事件采集与发射、索引验证（EXPLAIN）、合成样本与流量模拟 | `public.run_server()`、CLI `simulate_traffic`/`import_samples`/`gen_demo_data`/`explain_diff`、`samples.catalog` 数据文件 |
| M3 ER 模型与完整性约束 | `modules/m3-er-constraints/` | 无运行时包 | ER 源文件（Mermaid）、约束目录与校验 SQL、约束用例 | `er/schema.mmd`、`constraints/verify_constraints.sql`、`tools/introspect_constraints.py`、测试 |
| M4 规则配置与派生数据 | `modules/m4-rules-derived/` | `m4_rules_derived` | R01–R05 判定、风险评分、派生数据更新（意图/画像）、告警去重与生成、规则版本与配置读写 | `public.analyze_and_derive()`、`public.list_rules()`/`update_rule()`、规则仓储 |
| M5 分析视图与控制台 | `modules/m5-views-console/` | `m5_views_console`（CLI） | 视图口径对照与核对查询、Vue 控制台（四页）、视觉基线与 SQL-界面核对、部署验收证据 | `views/queries.sql`、CLI `verify_views`、`frontend/` 构建产物、`verify/` 浏览器检查 |
| 共享平台 | `shared/` | `shared` | 配置、日志、数据库连接、SQLAlchemy 模型（schema 契约）、标准事件契约、脱敏与 SQL 归一化、通用查询工具、构建/部署与边界检查脚本 | `shared.config`、`shared.db`、`shared.models`、`shared.events`、`shared.utils`、`shared.data`、`shared.deploy` |

### 2.2 依赖矩阵（无环，方向固定）

| 从 → 到 | shared | M1 | M2 | M3 | M4 | M5 |
| --- | --- | --- | --- | --- | --- | --- |
| **shared** | — | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| **M1** | 允许 | — | 禁止 | 禁止 | 允许（仅 `public`） | 禁止 |
| **M2** | 允许 | 允许（仅 `public.ingest_event`） | — | 禁止 | 禁止 | 禁止 |
| **M3** | 允许（仅测试/工具） | 禁止 | 禁止 | — | 禁止 | 禁止 |
| **M4** | 允许 | 禁止 | 禁止 | 禁止 | — | 禁止 |
| **M5** | 允许 | 经 HTTP 与 CLI（不导入内部） | 禁止 | 禁止 | 禁止 | — |

约束说明：

- "仅 public"指只允许 `import m4_rules_derived.public` / `m1_transaction_integration.public`，
  禁止导入对方的 `api`、`services`、`repositories`、`models`（对方模型经 `shared.models`
  协作）；
- M5 前端只通过 `/api` HTTP 契约访问 M1，不产生 Python 导入关系；M5 的
  `verify_views` CLI 使用 `shared.db` 只读会话执行视图查询；
- 边界检查脚本的允许矩阵与本表逐行一致（见
  [contracts/module-boundaries.md](./contracts/module-boundaries.md)）。

### 2.3 搬迁映射实体（文件 → 目标模块）

完整映射见 [contracts/module-boundaries.md](./contracts/module-boundaries.md) 第 4 章；
搬迁的验收事实是：`git log --follow` 可追溯、旧导入 `app.`/`backend.` 残留为 0、
`make boundary` 通过、001 测试全绿（FR-121/123、SC-023）。

---

## 3. 前端领域模型

### 3.1 路由与页面

| 路由（hash） | 页面组件 | 页面标题 | favicon | 说明 |
| --- | --- | --- | --- | --- |
| `#/` | `pages/OverviewPage.vue` | 首页概览 | 概览图形 | 4 个 KPI + 趋势面积图 + 意图环图 + TOP5 攻击者 |
| `#/attackers` | `pages/AttackersPage.vue` | 攻击者列表 | 列表图形 | 摘要卡 + 4 项筛选/搜索 + 分页表格 |
| `#/attackers/:ip` | `pages/AttackerDetailPage.vue` | 攻击者详情与时间线 | 详情图形 | 画像 + 3 证据链 + 快捷指标 + 会话表 + 时间线 + 威胁等级 |
| `#/alerts` | `pages/AlertsPage.vue` | 告警列表 | 告警图形 | 统计行 + 筛选 + 批量已读 + 告警卡片 + 分页 |

`AppShell.vue` 在所有路由之上提供：固定侧栏（品牌、诱饵监听状态条、四项导航、安全
提示）、顶部工具栏（面包屑/标题、当前时间、刷新、通知）、页脚、全局 Toast。

### 3.2 页面区域与数据源（与附录 C 对齐）

| 区域 ID | 页面 | 数据来源 | 空态/降级 |
| --- | --- | --- | --- |
| `OV-HEAD` / `OV-KPI` / `OV-TREND` / `OV-DONUT` / `OV-TOP5` | 概览 | `/api/overview`、`/api/trend`、`/api/rules/effectiveness`、`/api/attackers` | 无数据 → 占位文本 + 重置入口；接口失败 → 区域级错误条 + 重试 |
| `AT-HEAD` / `AT-FILTER` / `AT-TABLE` / `AT-EMPTY` / `AT-PAGER` | 列表 | `/api/attackers`、`/api/attackers/summary` | 空结果 → "无匹配攻击者" + 清除筛选 |
| `AD-HEAD` / `AD-BANNER` / `AD-PROFILE` / `AD-CHAIN` / `AD-SESSIONS` / `AD-TIMELINE` / `AD-FOOTER` | 详情 | `/api/attackers/{ip}`、`/api/sessions/{id}/timeline` | 无会话/无命中 → 分块空态 |
| `AL-HEAD` / `AL-FILTER` / `AL-CARDS` / `AL-EMPTY` / `AL-BATCH` / `AL-FOOTER` | 告警 | `/api/alerts`、`/api/alerts/summary` | 空列表 → 空态插画/文本 + 重置筛选 |

> 区域 ID 的权威定义与逐区域核对点见
> [contracts/ui-contracts.md](./contracts/ui-contracts.md) §3；本表只列数据来源与状态。

### 3.3 前端类型（`types/`）

| 类型 | 字段（摘要） | 来源 |
| --- | --- | --- |
| `RangeKey` | `'24h' \| '7d' \| 'all'` | FR-101 时间范围 |
| `RiskLevel` | `'low' \| 'medium' \| 'high' \| 'critical'` | 001 枚举不变 |
| `IntentType` | `'scanning' \| 'bruteforce' \| 'recon' \| 'data_dump' \| 'destructive'` | 001 枚举不变 |
| `AlertType` | `'bruteforce' \| 'data_dump' \| 'destructive'` | 001 枚举不变（附录 B 补充第 21 条） |
| `NetworkScope` | `'private' \| 'loopback' \| 'reserved' \| 'public'` | 由 IP 派生（附录 B 补充第 22 条） |
| `OverviewData` | 001 字段 + `attackers_total`、`high_risk_ratio`、`alerts_unread`、`alerts_by_severity`、`sessions_today`、`queries_today`、`sessions_delta_pct`、`queries_delta_pct`、`query_blocked_rate`、`range`、`window_start` | 契约 §2 |
| `TrendSeries` | `points[]`（含 001 字段 + 5 个意图族命中数） | 契约 §3 |
| `AlertSummary` | `total`、`unread`、`read`、`unread_by_severity`、`by_alert_type`、`today_new`、`yesterday_new`、`today_delta_pct`、`peak_window`、`resolution_rate`、`today_window`、`generated_at` | 契约 §4 |
| `AttackerSummary` | `total`、`high_risk_count`、`latest_intent`、`generated_at` | 契约 §5 |
| `AttackerRow` | 001 字段 + `intent_labels: string[]`、`triggered_rule_codes: string[]`、`network_scope` | 契约 §6 |
| `AttackerProfileView` | 001 画像 + `avg_session_seconds`、`auth_success_count`、`high_risk_op_count`、`network_scope` | 契约 §7 |
| `FilterState` | 各页筛选条件的可序列化对象（写入 URL query 便于刷新恢复） | FR-101 |
| `BatchResult` | `total`、`succeeded`、`failed: {alert_id, message}[]` | FR-102、附录 B 第 12 条 |

### 3.4 交互状态模型

**页面加载状态机**（所有页面一致）：
`idle → loading → (ready | empty | error | degraded)`；`degraded` 由 `/api/health`
的 `status=degraded` 或 503 触发，页面显示全宽降级条且保留上次成功数据（若有）。

**筛选状态**：每次筛选/翻页/排序变更写入 hash query（如
`#/alerts?severity=high&is_read=false&page=1`），刷新可恢复；非法值回退默认并提示。

**告警已读状态**：`unread → pending → read`；失败回滚为 `unread` 并显示错误原因；
批量操作逐条迁移，部分失败时列表明细保持服务端真实状态并高亮失败行。

**侧栏详情导航**：`no_recent_attacker`（禁用 + 提示）→ `has_recent_attacker`
（可点击，会话内记忆）；详情页加载成功后写入记忆，IP 非法或 404 时清除记忆并回列表。

**时间范围**：`24h`、`7d`、`all` 只改变查询参数与 KPI/趋势数据，不改变布局；切换
期间保留旧数据并显示加载指示（无假动画）。

**刷新**：顶部刷新按钮重新请求当前页全部所需接口，显示最近更新时间。

### 3.5 严重度与意图展示映射（跨页统一）

| 等级 | 中文 | 主色（附录 B 裁定） | 圆点/徽标 |
| --- | --- | --- | --- |
| `critical` | 严重 | `#EF4444` | 实心圆点 + 4px 圆角徽标 |
| `high` | 高 | `#F97316` | 同上 |
| `medium` | 中 | `#F59E0B` | 同上 |
| `low` | 低 | `#10B981` | 同上 |

意图 → 中文标签：`scanning` 扫描探测、`bruteforce` 暴力破解、`recon` 信息侦察、
`data_dump` 数据拖取、`destructive` 破坏性操作；均带括号英文/等宽副标（FR-097）。

---

## 4. 接口增量数据模型

全部为**加法**：既有字段与状态码不变；新字段为可选或有默认值，001 测试不受影响。
逐字段契约、校验与错误码见 [contracts/api-extensions.md](./contracts/api-extensions.md)。

| 端点 | 变更 | 关键校验 |
| --- | --- | --- |
| `GET /api/overview` | 新增 query `range`（枚举，默认 `all`）；响应 11 个新字段 | `range` 非法 → 422 `VALIDATION_ERROR`；`window_start` 为 UTC |
| `GET /api/trend` | 响应点新增 5 个整数命中数 | 负值不可能；缺列补 0；`days` 上限 90 不变 |
| `GET /api/alerts/summary` | **新端点** | `from < to`，窗口 ≤ 366 天；空库返回 0 值 |
| `GET /api/attackers/summary` | **新端点** | 无参数；空库 `latest_intent=null` |
| `GET /api/attackers` | 新增 `q`（1–64，转义 `% _ \`）、`sort=total_connections`；行新增 3 字段 | `q` 超长/控制字符 → 422；排序白名单 |
| `GET /api/attackers/{ip}` | 画像新增 3 字段 + `network_scope` | IP 不存在仍 404 `ATTACKER_NOT_FOUND` |
| `PATCH /api/alerts/{id}` | **不变** | 批量由前端逐条调用（R-06） |

响应信封、错误体（`code/message/detail/request_id`）、时间格式（UTC ISO8601）、
分页参数（`page`/`page_size`/`total`/`total_pages`）全部沿用 001 契约 §1。

---

## 5. 设计令牌模型

| 令牌组 | 令牌（示例） | 取值来源 | 校验 |
| --- | --- | --- | --- |
| 颜色-表面 | `surface`、`surface-container-lowest/low/high/highest`、`surface-variant` | 附录 B 截图色板（M3 深色） | 令牌审计：类名必须命中配置；源码禁止裸 `#hex` |
| 颜色-前景 | `on-surface`、`on-surface-variant`、`outline`、`outline-variant` | 同上 | 同上 + 对比度抽检（WCAG AA） |
| 颜色-语义 | `primary`、`secondary`、`tertiary`、`error` | 同上 | 严重度四色固定映射（§3.5） |
| 字体族 | `font-sans`（Inter Variable）、`font-mono`（JetBrains Mono Variable）、`font-icon`（Material Symbols） | R-03 | FR-096：等宽仅技术标识 |
| 字号字阶 | `display-lg`、`headline-*`、`title-*`、`body-*`、`label-*`、`code-*` | DESIGN.md 字阶 | 令牌审计 |
| 间距 | `space-xs/sm/md/lg/xl`、`gutter-*`、`margin-*` | DESIGN.md | 令牌审计 |
| 圆角 | 容器 8px、控件/表格/徽标 4px、状态点圆形 | 附录 B 第 6/7 条 | 令牌审计 + 区域核对 |
| 描边/阴影 | `border`、`divider`、`glow`（仅限图表/状态点） | DESIGN.md | 区域核对 |

唯一数值源为 `frontend/tailwind.config.cjs`；`DESIGN.md` 同步重写并在文件头标注
"数值以配置为准，本文件为语义说明"（R-02）。

---

## 6. 证据与基线模型

### 6.1 模块证据索引（每个模块 `evidence/README.md`）

| 字段 | 含义 |
| --- | --- |
| 证据编号 | `M1-E01` … `M5-E0n` |
| 对应用户故事 / FR | 如 `US1 / FR-124` |
| 复现命令 | 可直接复制执行（含前置种子命令） |
| 期望输出 | 关键行/JSON 片段或断言 |
| 产物路径 | 原始输出、截图、SQL 结果文件 |
| 依赖 | 种子数据、运行中的服务、浏览器 |
| 最近验证时间 | ISO8601（UTC+8 展示） |

### 6.2 视觉基线记录（`evidence/visual/`）

| 字段 | 含义 |
| --- | --- |
| 页面 | `overview` / `attackers` / `attacker-detail` / `alerts` |
| 视口 | `1440x900`、`1920x1080`（`deviceScaleFactor=1`） |
| 截图文件 | `baseline/{page}-{viewport}.png` |
| 区域核对表 | `region-checklist.md`：区域 ID、判定（一致/差异）、理由、令牌、证据 |
| 令牌抽样 | 每页 20 处：元素选择器、属性、期望令牌、实际取值、判定 |
| 固定数据指纹 | 种子命令 + 行数摘要（会话/事件/告警/攻击者） |
| 链路核验 | `verify-report.json` 摘要（错误 0、失败请求 0、外网请求 0、溢出 0） |

### 6.3 部署验证记录（`evidence/deploy/`）

`deploy-record.json` 结构：

```json
{
  "started_at": "2026-11-25T10:00:00+08:00",
  "finished_at": "2026-11-25T10:03:12+08:00",
  "base_url": "http://127.0.0.1:8000",
  "steps": [{"name": "db_up", "status": "ok", "detail": "..."}],
  "pages": [{"route": "#/", "status": "ok", "console_errors": 0,
             "failed_requests": 0, "http_errors": 0, "external_requests": 0,
             "horizontal_overflow": false, "fonts_ready": true,
             "screenshots": ["overview-1440x900.png"]}],
  "token_audit": {"violations": 0, "checked_files": 42},
  "result": "pass"
}
```

退出码：`0` 全通过；`1` 任一步骤失败；`2` 前置条件缺失（无 `.env`、无浏览器等）。
三次连续运行（SC-024）分别保存 `run-1/`、`run-2/`、`run-3/`。

### 6.4 页面-数据库核对记录（`evidence/sql-ui/`）

每页至少 3 组：`{页面, 区域, 页面显示值, SQL, SQL 结果, 一致?}`；SQL 可直接重跑，
统一使用只读账号与视图口径（SC-020）。核对样例覆盖：概览 KPI、告警统计、攻击者
总数、详情画像指标、规则命中占比。

---

## 7. 校验规则汇总（可执行断言）

| 编号 | 规则 | 校验方式 | 失败处理 |
| --- | --- | --- | --- |
| V-01 | 五个模块目录 + `shared/` 齐全且命名固定 | `tools/check_structure`（make structure） | 阻断 |
| V-02 | 依赖矩阵内无违规、无循环 | `shared/deploy/boundary_check.py` | 阻断 |
| V-03 | 无旧导入残留（`app.`、`backend.`） | 边界检查附带扫描 | 阻断 |
| V-04 | 模板/源码中的设计令牌全部命中配置 | `frontend/verify/token-audit.mjs` | 阻断 |
| V-05 | 四页无 console error / 失败请求 / 404 / 外网请求 / 横向溢出 | `frontend/verify/run-check.mjs` | 阻断 |
| V-06 | 页面数字与 SQL 一致（每页 ≥3 组） | `verify/sql-ui-check.md` + 人工执行 + 记录 | 阻断 |
| V-07 | 区域核对一致率 ≥95%，差异均有理由 | `region-checklist.md` 统计 | 阻断 |
| V-08 | 严重度映射跨页一致（4×4 抽样） | 自动截图 + 核对表 + 令牌审计 | 阻断 |
| V-09 | 001 全量测试通过、接口字段向后兼容 | `pytest` + 兼容性用例 | 阻断 |
| V-10 | 迁移在空库/存量库往返成功 | `tests/integration/test_migrations.py` | 阻断 |
| V-11 | 部署脚本三次连续成功、截图关键区域一致 | `verify_deploy.sh --repeat 3` | 阻断 |
| V-12 | 空态/加载/失败/降级四态可复现 | 浏览器脚本注入（阻断 API/DB） | 阻断 |
| V-13 | 禁用控件语义正确（`aria-disabled`、说明文案） | 区域核对 + 浏览器断言 | 阻断 |
| V-14 | 附录 B（含补充 21–28）闭环率 100% | 核对表逐条勾选 | 阻断 |

---

## 8. 与 001 数据库实体的关系

- **读取的实体**：`sessions`、`attack_log`、`rule_hits`、`attacker_profile`、
  `attacker_intent`、`alerts`、`detection_rules`、`audit_log`（写审计时由 M1 追加），
  以及 4 个分析视图；全部经既有仓储与视图读取，不新增列。
- **写入的实体**：仅 `alerts.is_read`/`read_at` 与 `audit_log`（001 既有写路径），
  由 M1 在单事务内完成；批量已读只是多次单条写。
- **不涉及的实体**：`fake_users`、`fake_orders`、`credential_test`、`session_event`
  等采集侧表不改结构；M2 搬迁后写入路径与幂等键不变。
- **约束与完整性**：外键、CHECK、UNIQUE 全部保持 001 定义；M3 证据从
  `information_schema` 反查并与 001 data-model 对账（FR-126、宪法门禁 1）。

---

## 9. 需求映射（摘要）

| 需求组 | 覆盖方式 | 主要证据 |
| --- | --- | --- |
| FR-090–099（视觉/版式/令牌/语义） | 令牌配置 + 壳层 + 四页组件 | 基线截图、区域核对表、令牌审计 |
| FR-100–106（状态/真实交互/禁用/可访问/离线） | 状态机 + 真实接口 + 禁用语义 + 本地资源 | 浏览器检查、断网运行、核对表 |
| FR-107–113（部署/证据/降级） | verify_deploy.sh + 证据目录 + 降级注入 | deploy-record、截图、核对记录 |
| FR-114–123（五模块/边界/无回归） | 模块目录 + 边界检查 + 阶段门禁 | 结构检查、boundary 报告、pytest |
| FR-124–129（五类证据） | 每模块 evidence/README + 原始产物 | 五份证据索引 |
| FR-130–132（安全/红线/权限） | 只读接口 + 脱敏 + 账号矩阵不变 | 安全用例、账号检查 |
| SC-016–028 | 见 §7 校验矩阵 | quickstart 场景 V01–V14 |
