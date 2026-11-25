# Phase 0 研究：控制台视觉重构与模块解耦

**Feature**: `002-ui-console-modularization` | **Date**: 2026-11-25 | **Spec**: [spec.md](./spec.md)

本文件记录 `/speckit-plan` 阶段的技术决策。每条决策给出**决策 / 理由 / 备选方案 /
影响**；截至本文件完成，Technical Context 中不存在 `NEEDS CLARIFICATION`。

调研依据：`specs/002-ui-console-modularization/spec.md`（FR-090 至 FR-132、SC-016 至
SC-028、附录 A/B/C）、`specs/001-database-honeypot/`（既有契约与实现）、
`ux/stitch_database_honeypot_analytics_console/`（四页原型、`DESIGN.md`）、现有
`backend/`、`frontend/`、`Makefile`、`compose.yaml`、`docs/` 的实际内容。

---

## R-01 前端技术路线：Vue 3 + Tailwind CSS 3.4 自研组件，移除 Element Plus 与 ECharts

- **决策**：保留 Vue 3.5 + Vite 8 + TypeScript 5.9 与 hash 路由；引入 Tailwind CSS
  3.4.19（PostCSS 构建，非 CDN），按原型 `tailwind.config` 逐项复刻设计令牌；
  以 SFC 自研组件替换 Element Plus 的布局、表格、分页、时间线、徽标等全部控件；
  删除 `element-plus` 与 `echarts` 依赖。原型页面结构与类名可直接迁移。
- **理由**：
  1. 原型是 Tailwind utility + 自定义 token 的静态页，class-for-class 迁移是达到
     SC-018（区域一致 ≥95%、令牌取值 100% 来自令牌）最可控的路径；
  2. Element Plus 的暗色主题通过 CSS 变量覆盖，卡片、表格、时间线、空态的外观
     无法逐区域对齐附录 C，且会与 Tailwind 令牌形成两套取值来源；
  3. 原型图表为手写 SVG（渐变面积图 + `stroke-dasharray` 环图），ECharts 的主题
     体系难以逐像素对齐，且引入约 300KB 运行时，与"构建产物本地自托管"目标冲突；
  4. 移除两个大依赖后依赖面收敛到 Vue 生态 + 验证工具，令牌审计脚本可直接扫描
     `class` 与配置，SC-018 的"令牌 100%"要求可自动化。
- **备选方案**：
  - *Element Plus 暗色覆盖*：开发量小，但组件外观不可控，区域一致性与 token 审计
    很难达标，且两套语义色板并存；
  - *Tailwind CSS 4.x*：更新，但 v4 的 CSS-first `@theme` 与裸 `rounded` 等取值
    行为与原型 v3 配置存在差异，class-for-class 迁移需逐条验证，风险高于收益；
    若实现期确认 v3 与 Vite 8 构建冲突，再按变更记录升级 v4（见风险表）；
  - *纯 CSS 手写*：无构建期 token 校验，样式分散，4000+ 行原型样式维护成本更高。
- **影响**：前端需新增约 20 个自研组件与 2 个 SVG 图表组件；`frontend/package.json`
  依赖显著收敛；样式类名即令牌名，令牌审计可脚本化。

## R-02 设计令牌：`tailwind.config.cjs` 为唯一数值源，DESIGN.md 同步重写

- **决策**：颜色（M3 深色语义色板）、字号字阶、间距、圆角、字体族全部定义在
  `modules/m5-views-console/frontend/tailwind.config.cjs`（CommonJS，便于 Node 脚本
  `require` 读取）；`ux/.../DESIGN.md` 重写为深色版本并作为人类可读镜像（附录 B
  裁定截图色板优先，见 spec 假设）；令牌审计脚本从配置文件导出允许值表，扫描
  `src/**/*.{vue,ts,css}` 中的颜色/字体/圆角/间距类名与裸 `#hex`。
- **理由**：单一数值源避免"文档一套、实现一套"；CommonJS 配置可被验证脚本直接
  加载，无需额外解析器；DESIGN.md 仍是命名与语义的权威说明（FR-092 语义要求），
  实现值以配置为准并在文档中标注同步方式。
- **备选方案**：*CSS 自定义属性为源、Tailwind 映射变量*（透明度修饰符需拆 RGB
  通道，配置复杂）；*JSON token 文件 + 生成配置*（多一层生成物，课程规模不划算）。
- **影响**：`DESIGN.md` 的旧浅色取值（附录 B 判定为原型遗留）在实现阶段重写；
  令牌审计脚本是 SC-018 的证据之一。

## R-03 字体、图标与 Logo 全部本地自托管

- **决策**：字体使用 `@fontsource-variable/inter@5.3.0` 与
  `@fontsource-variable/jetbrains-mono@5.3.0`；图标使用 `material-symbols@0.49.0`
  的 `outlined.css`（本地字体文件，无 CDN）；Logo 改为内联 SVG 图形标记（复用原型
  的盾牌/数据库意象，不下载外链图片）。
- **理由**：FR-106 与 SC-026 要求断网可用、外网请求为 0；npm 包自带 woff2 与 CSS，
  与 Vite 构建集成简单，无需手工维护字体文件；图标名与原型 HTML 中
  `<span class="material-symbols-outlined">` 一致，迁移成本最低。
- **备选方案**：*lucide-vue-next*（图标风格与原型差异大，区域一致性受损）；
  *手工下载 woff2 放 assets*（文件管理分散，版本不可锁定）；*系统字体回退*
  （排印差异明显，FR-092 字阶不可复现）。
- **影响**：Material Symbols 可变字体体积较大（约 3–4MB），仅本地演示可接受；
  bundle 体积不计入性能基线，构建时由 Vite 输出静态资源。

## R-04 图表：自研 SVG 组件（趋势面积图、意图环图）

- **决策**：`TrendChart.vue` 复刻原型的三序列折线 + 渐变面积 + 网格 + 峰值标注，
  数据来自扩展后的 `GET /api/trend`（按意图族补充分日命中数）；`IntentDonut.vue`
  复刻环图与图例，数据来自 `GET /api/rules/effectiveness`（R01–R05 命中占比）。
  两个组件只依赖传入的已排序数据，不自行取数。
- **理由**：原型图表是纯 SVG（路径、线性渐变、`stroke-dasharray`），自研可精确
  对齐线宽、颜色、圆点与图例排布；同时避免 Canvas 渲染在截图与缩放下的差异
  （SC-017 要求 125% 缩放不溢出、不重叠）。
- **备选方案**：*保留 ECharts*（主题映射成本高、体积大、截图差异不可控，R-01 已
  排除）；*纯 CSS 条形替代*（与原型形态不符，区域一致性不达标）。
- **影响**：图表组件需处理空数据、单点数据与超长标签；不做动画（原型无动画，
  FR-102 禁止假反馈）。

## R-05 接口扩展：只做加法，不改变 001 既有字段语义

- **决策**：新增 `GET /api/alerts/summary`、`GET /api/attackers/summary`；
  扩展现有端点参数与响应字段（全部带默认值的可选增量字段）：
  - `GET /api/overview?range=all|7d|24h`：补充 `attackers_total`、
    `high_risk_ratio`、`alerts_unread`、`alerts_by_severity`、`sessions_today`、
    `queries_today`、`sessions_delta_pct`、`queries_delta_pct`、`query_blocked_rate`、
    `range`、`window_start`；
  - `GET /api/trend`：`TrendPoint` 增加按意图族的分日命中数
    `hit_bruteforce`、`hit_data_dump`、`hit_scanning`、`hit_recon`、`hit_destructive`；
  - `GET /api/attackers`：新增 `q`（IP 子串，1–64 字符，转义 LIKE 通配符）、
    `sort=total_connections`；列表项增加 `intent_labels`、`triggered_rule_codes`；
  - `GET /api/attackers/{ip}`：画像增加 `avg_session_seconds`、
    `auth_success_count`、`high_risk_op_count`；
  - 数据库 DDL 与 11 张表、4 个视图全部不变（宪法"Schema 即契约"不触发迁移）。
- **理由**：原型中的统计（未读告警数、今日新增、解决率、高风险占比、平均会话
  时长、高危操作次数、按意图族的趋势）无法由现有列表接口在客户端正确汇总
  （分页截断、N+1 请求），必须由数据库聚合；全部增量字段可空/有默认值，001 的
  既有测试与接口返回保持向后兼容（FR-123、SC-023）。
- **备选方案**：*前端多请求拼装*（分页导致总数错误、10 次请求拖慢首屏）；
  *新增 `/api/v2`*（契约膨胀、001 文档与测试需大改）；*引入新表存统计*（无必要，
  违反"视图承载分析"的既有设计）。
- **影响**：`specs/001-database-honeypot/contracts/api.md` 需在实现阶段追加"增量
  字段引用 002 契约"的说明；新增字段需补 API 测试；`attacker_repo`、`alert_repo`、
  `overview_repo`、`rule_repo` 增加只读聚合 SQL（参数化、有界）。

## R-06 告警批量已读：客户端顺序 PATCH，逐条反馈

- **决策**：批量置已读由前端对选中告警逐条调用既有 `PATCH /api/alerts/{id}`
  （最大并发 2），收集每条结果；全部成功、部分失败、全部失败分别给出中文提示，
  失败项保持原状态并高亮。后端不新增批量端点。
- **理由**：既有写接口已在单事务内 `SELECT ... FOR UPDATE` + 审计留痕 + 幂等，
  复用可保持 001 契约与审计完整性（宪法三/四）；spec 附录 B 第 12 条已裁定采用
  逐条写入并反馈部分失败。
- **备选方案**：*新增批量端点*（多写接口、部分失败语义与审计粒度需重新设计，
  超出本 feature 范围）。
- **影响**：前端需要并发控制与结果聚合逻辑；按钮在请求期间禁用并显示进度。

## R-07 侧栏"攻击者详情"导航：会话内记住最近访问的攻击者

- **决策**：导航第 03 项指向最近一次访问的 `/attackers/{ip}`，IP 存于
  `sessionStorage`；无记录时该导航项呈禁用态并附 `title`/`aria-label` 提示
  "请先从攻击者列表进入"，不产生死链。详情页激活时 03 高亮；刷新后仍可用。
- **理由**：FR-090/FR-091 要求四模块导航可用、点击有真实目标；详情页路由必须带
  IP，直接硬编码示例 IP 会展示不存在的数据（违反 FR-102）。
- **备选方案**：*导航 03 跳列表并自动选中第一行*（语义误导）；*删除 03*（违反原型
  四模块与附录 A）；*03 跳固定示例 IP*（断网/换库后 404）。
- **影响**：壳层需要一个轻量会话状态；空态提示文案需与附录 B 一致。

## R-08 模块物理结构：单发行版多包 + 五模块目录 + `shared/`

- **决策**：仓库根新增 `pyproject.toml`（hatchling），以
  `packages = ["shared/shared", "modules/m1-transaction-integration/m1_transaction_integration", ...]`
  将 `shared` 与 5 个模块内包纳入同一可编辑安装；导入名使用下划线
  （`m1_transaction_integration` … `m5_views_console`），目录名保持 spec 规定的
  连字符命名。`backend/` 目录移除，入口改为
  `uvicorn m1_transaction_integration.api.app:create_app --factory`；Alembic 位于
  `modules/m1-transaction-integration/migrations/`，根 `alembic.ini` 指向它；
  前端迁至 `modules/m5-views-console/frontend/`；`WEB_DIST_DIR` 默认改为
  `modules/m5-views-console/frontend/dist`。所有搬迁使用 `git mv` 保留历史（FR-121）。
- **理由**：FR-114/115 要求五模块目录自包含且可直接运行；单发行版避免 6 份
  `pyproject.toml` 与交叉 path 依赖，`uv sync` 一次安装即可同时跑 API、诱饵、
  CLI 与测试；目录名与导入名分离是 Python 包命名的标准做法。
- **备选方案**：*每模块独立发行版 + path 依赖*（6 个依赖图、版本对齐成本高，
  课程规模过重）；*仅移动部分文件、保留 `backend/app` 分层*（违反 FR-114/115
  自包含）；*PEP 420 命名空间包免安装*（依赖 PYTHONPATH，uvicorn/alembic/pytest
  三处路径易漂移）。
- **影响**：~70 个文件的 `git mv` 与导入重写；`Makefile`、`compose.yaml`（init 脚本
  挂载路径）、`alembic.ini`、`.env.example`、文档全部同步；建议单独一个提交完成
  搬迁且保持测试全绿。

## R-09 依赖边界检查：AST 静态扫描 + 允许矩阵

- **决策**：`shared/deploy/boundary_check.py` 用 `ast` 解析 `modules/**/*.py` 与
  `shared/**/*.py` 的 import，按允许矩阵判定；违规（跨模块内部子模块、反向依赖、
  循环）输出 JSON 明细并 `exit 1`；`make boundary` 纳入合并门禁与 CI。允许矩阵与
  公开契约定稿于 [contracts/module-boundaries.md](./contracts/module-boundaries.md)。
- **理由**：FR-122 要求自动化检查且违规为 0（SC-022）；AST 方案零新依赖、可解释、
  可给出文件与行号；同时检查 `backend.`、`app.` 等旧导入残留，防止搬迁遗漏。
- **备选方案**：*人工评审*（不可重复）；*import-linter 第三方依赖*（新增依赖，
  配置表达力对五模块矩阵过剩）。
- **影响**：每个模块需提供 `public.py`（或 `public/` 包）作为唯一对外入口；边界
  检查本身需要自测（构造违规样例 → 断言 exit 1）。

## R-10 部署形态：MySQL 容器 + 宿主 uvicorn 托管生产构建，单地址验收

- **决策**：`docker compose` 仅保留 MySQL 8（与仓库现状一致，修正 001 plan 中
  "compose 含 backend + web"的漂移描述）；后端在本机以 uvicorn 启动并由
  `StaticFiles` 托管前端 `dist`，四页与 `/api` 同源单地址；`make verify` 调用
  `shared/deploy/verify_deploy.sh`：
  1) 检查 `.env` 与依赖 → 2) `docker compose up -d` + 等待健康 →
  3) `alembic upgrade head` → 4) 重置并导入固定种子数据 →
  5) `pnpm build` → 6) 启动 uvicorn（PID 文件 + trap 清理）→ 7) 等待
  `GET /api/health` 为 200 → 8) 运行浏览器检查与截图 → 9) 运行 token 审计 →
  10) 写 `deploy-record.json` 与截图 → 11) 停止服务并输出摘要。
  浏览器检查使用 `@playwright/test@1.65.1`（console 页 devDependency），浏览器
  缺失时优先使用本机 Chrome（`channel: "chrome"`），否则明确报错并提示安装命令；
  断网验收（SC-026）通过请求拦截列表断言外网请求为 0。
- **理由**：SC-027 要求干净环境 10 分钟内可部署（不含依赖下载），宿主进程 +
  容器数据库最短路径；不额外引入 nginx/容器镜像构建；单地址与 001 的部署模型
  一致，改动面最小。
- **备选方案**：*后端也进容器*（需新增 Dockerfile 与镜像构建，冷启动超时）；
  *nginx + 静态站点 + 反向代理*（新增进程与配置，无收益）。
- **影响**：修正 `Makefile` 的 `UV` 绝对路径（改为 `command -v uv` 并支持
  `UV` 覆盖）；`compose.yaml` 注释、`README.md`、`docs/architecture.md` 的部署
  视图同步修正；`.env.example` 的 `WEB_DIST_DIR` 更新。

## R-11 视觉验收：自动化检查 + 令牌审计 + 人工区域核对表

- **决策**：三层证据：
  1. **浏览器自动检查**（Playwright，两视口 × 四页）：控制台 error 数、失败请求数、
     ≥400 响应数、外网请求数、`documentElement.scrollWidth` 溢出、字体就绪
     （`document.fonts.check`）、页面标题/favicon 切换；输出 JSON；
  2. **令牌审计**：从 `tailwind.config.cjs` 导出允许值，扫描源码中的颜色/字体/
     圆角/间距类名与裸 `#hex`，违规为 0；
  3. **人工区域核对表**：按附录 C 每页逐区域记录"一致/差异 + 理由 + 证据"，每页
     20 处视觉取值填"页面/令牌/核对方式"，差异全部登记；基线截图 4 页 × 2 视口
     存 `evidence/visual/baseline/`，演示用图同步到 `docs/screenshots/`。
- **理由**：SC-016/017/018/024/026 分别要求自动化与人工证据；原型与实现的数据、
  尺寸不同，像素 diff 不可行也不必要（SC-024 允许时间戳与随机 ID 差异）。
- **备选方案**：*像素级 diff*（原型截图 913×1600 等与目标视口不同，数据不同，
  误报率高）；*仅人工核对*（不可重复、无法覆盖控制台错误与溢出）。
- **影响**：新增 Node 验证脚本与 Playwright 依赖；证据目录结构见
  [data-model.md](./data-model.md) 第 7 章。

## R-12 固定种子数据：重置 + 合成规模数据 + 样本组，保证可重跑

- **决策**：视觉基线与页面-数据库核对统一使用以下幂等序列：
  `python -m m1_transaction_integration.cli.reset_demo --yes` →
  `python -m m2_decoy_capture.cli.gen_demo_data --sessions 200 --events 2400`（合成
  规模数据，RFC 5737 地址，固定基准时间）→
  `python -m m2_decoy_capture.cli.import_samples --group demo_basic`（覆盖 R01–R05
  的固定样本，产生全部三类告警与多等级严重度）。命令写入 quickstart 与
  verify_deploy.sh；数据规模保持演示级（<1 万事件）。
- **理由**：四页需要"长列表 + 多等级 + 多意图 + 有告警"的稳定数据；合成数据
  确定（固定 IP/时间/语句池），样本组确定（S01–S07），重复执行结果一致（SC-024）；
  数量控制在 001 的性能基线与截图耗时内。
- **备选方案**：*随机生成数据*（截图不可复现）；*直接使用生产/演示库快照*
  （版本不可控、含敏感数据风险）。
- **影响**：`gen_demo_data` 与 `import_samples` 随 M2 搬迁；`reset_demo` 随 M1
  搬迁；verify_deploy.sh 固化为脚本步骤，quickstart 给出等价命令。

## R-13 原型差异补充登记：实现前回写 spec 附录 B（第 21–28 条）

- **决策**：以下 8 项"原型有、数据/接口无"的差异在实现前追加到 spec.md 附录 B
  并同步附录 C 区域清单；实现按"真实计算 > 派生标签 > 禁用/省略"的顺序处理：
  1. 告警类型筛选 6 类 → 实际 3 类（`bruteforce`/`data_dump`/`destructive`），
     R01/R03 不产生告警（001 数据口径），筛选项由真实枚举生成；
  2. 攻击者实体标签（DMZ-Segment-A 等）→ 改为按 IP 归属派生标签（内网 / 回环 /
     文档保留 / 公网），不虚构资产归属；
  3. 概览"查询拦截率 94.2%"→ 由 `attack_log.status IN ('denied','failure')`
     真实计算，无数据时显示"—"；
  4. 详情"高危操作 12 次"→ `rule_hits` 中 `data_dump`/`destructive` 命中数；
  5. 详情"平均时长 6分12秒"→ 视图会话真实均值（接口新增字段）；
  6. KPI 趋势副标"较昨日 +27.5%"→ 真实昨日对比，无昨日数据不显示百分比；
  7. 快捷指标"高危会话"→ `high_risk_session_count`（既有字段）；
  8. 时间线事件图标四类（连接/认证/查询/断开）→ 未知类型归 `query`+`error`，
     不新增虚构类型。
- **理由**：FR-102/FR-131 禁止假数据与暗示能力；spec 自身要求差异有登记理由
  （SC-018/SC-025）。附录 B 是既有裁定清单，本清单属于"实现阶段新发现的差异"，
  按宪法"设计变更回到对应阶段更新产物"补充登记。
- **备选方案**：*扩展 001 数据模型生成 R01/R03 告警*（改变 001 业务口径，超出本
  feature 范围且需重跑迁移与规则评审）；*界面保留原样但置灰*（信息虚假）。
- **影响**：spec.md 附录 B 增补 8 条、附录 C 对应区域标注"差异已登记"；
  tasks.md 需含文档同步任务；区域核对表使用补充后的清单。

## R-14 实施顺序与回归门禁

- **决策**：6 个阶段顺序推进，每阶段结束运行 `pytest` + `ruff` +
  `pnpm build` + `make boundary` 全绿后再进入下一阶段：
  1. **结构搬迁**（纯移动 + 导入重写 + 打包/入口/配置 + 边界检查 + 测试迁移，
     功能零变化）；
  2. **M1 接口扩展**（聚合 SQL + 新端点 + 契约测试）；
  3. **M5 前端重写**（令牌 → 壳层 → 四页 → 图表 → 交互状态）；
  4. **验证工具链**（浏览器检查、令牌审计、截图、deploy 脚本）；
  5. **证据与文档**（模块 README/证据索引、ER 与约束样例、EXPLAIN 归档、
     管线图、spec 附录 B 补充、001 文档与 Makefile/README 漂移修正）；
  6. **回归与验收**（001 全量测试、四页流程、SC-016–028 逐条核对、quickstart
     三连跑）。
- **理由**：搬迁与改功能混在一个提交会掩盖回归来源；宪法要求"小提交、单一逻辑
  变更"，且 SC-023 需要"解耦前后行为一致"的可证明基线。
- **备选方案**：*一次性大重构*（不可回归、评审困难）；*先改 UI 再搬结构*
  （前端路径二次搬迁，返工）。
- **影响**：tasks.md 按阶段生成依赖顺序；迁移阶段建议独立 PR/提交。

## R-15 性能与规模基线

- **决策**：沿用 001 基线并补充本 feature 指标：
  - 四页在固定种子数据下切换 ≤1s（SC-027）；`/api/overview`、
    `/api/alerts/summary`、`/api/attackers/summary` 本机 p95 ≤500ms；
  - 合成数据 200 会话 / 2400 事件，固定样本组 7 个会话；查询全部参数化、
    带 `LIMIT` 与时间窗口上界；
  - 前端首屏 JS（不含字体/图标字体）gzip ≤ 1.2MB，无远程请求；
  - 部署脚本全流程（含构建，不含依赖安装）≤10 分钟；浏览器检查 ≤3 分钟。
- **理由**：与 001 的课程规模基线一致，避免为原型视觉效果引入无界查询；新聚合
  接口需在 001 的四个视图与既有索引范围内完成（不新增 DDL）。
- **备选方案**：*新增物化统计表*（违反"Schema 不变"与视图优先设计）。
- **影响**：新增聚合 SQL 需 EXPLAIN 记录（沿用 M1/M2 的 EXPLAIN 证据方法），
  慢查询回退为视图内聚合。

---

## 依赖版本锁定

| 依赖 | 版本 | 用途 | 来源确认 |
| --- | --- | --- | --- |
| tailwindcss | 3.4.19 | 设计令牌与原子样式 | npm registry 已确认 3.4.x 最新 |
| postcss / autoprefixer | 8.x / 10.x | Tailwind 构建管线 | 随 Tailwind 3 生态锁定 |
| @fontsource-variable/inter | 5.3.0 | 正文/标题字体（本地） | npm registry 已确认 |
| @fontsource-variable/jetbrains-mono | 5.3.0 | 等宽技术字体（本地） | npm registry 已确认 |
| material-symbols | 0.49.0 | 图标字体（本地） | npm registry 已确认 |
| @playwright/test | 1.65.1 | 浏览器部署验收 | npm registry 已确认 |
| vue / vite / typescript | 3.5 / 8.x / 5.9 | 沿用 001 既有版本 | `frontend/package.json` |
| FastAPI / SQLAlchemy / asyncmy / Alembic | 0.165 / 2.1.9 / 0.2.18 / 1.20.1 | 沿用 001 | `backend/pyproject.toml` |

新增依赖均评估：维护活跃、MIT/Apache-2.0 许可证、无已知高危漏洞；`pnpm-lock.yaml`
与 `uv.lock` 必须提交锁定结果（宪法"依赖锁定版本"）。

## 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 依赖安装需网络（npm registry / Playwright 浏览器） | 离线机器无法首次安装 | 文档写明前置步骤；Playwright 支持系统 Chrome 作为回退 |
| 大面积文件搬迁导致导入断裂 | 测试与启动失败 | 阶段 1 单独完成并以测试全绿为门禁；边界检查拦截旧导入 |
| Tailwind 3 与 Vite 8/PostCSS 8 构建冲突 | 构建失败 | 锁版本；冲突时升级 Tailwind 4 并记录变更 |
| 原型数据与真实数据差异导致区域不一致 | SC-018 不达标 | 附录 B 补充登记 + 禁用/派生策略；核对表按"数据差异"分类登记 |
| Material Symbols 体积大 | 首包资源较大 | 仅本地演示；构建产物指纹缓存；不纳入 JS 体积基线 |
| 新增聚合 SQL 拖慢接口 | p95 超基线 | 复用视图 + 索引；上限窗口与 `LIMIT`；EXPLAIN 记录 |
| Playwright 截图受字体/滚动条影响 | 基线不可重复 | 固定视口、`deviceScaleFactor=1`、等待 `document.fonts.ready` 与网络空闲 |
