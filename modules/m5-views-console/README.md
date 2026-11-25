# M5 分析视图与控制台

## 职责

M5 负责「**四个核心分析视图的查询口径**」与「**四页分析控制台**」两件事：

1. `views/queries.sql`：`v_session_risk_summary`、`v_attacker_profile_summary`、
   `v_daily_attack_trend`、`v_rule_effectiveness` 的用途、对应页面/API、时间窗与聚合口径、
   已知限制，附可执行代表性 SELECT；
2. `frontend/`：Vue 3.5 + Vite 8 + Tailwind CSS 的控制台（四页 + 组件 + API 客户端），
   深/浅双主题、默认跟随系统外观（页头圆角矩形按钮三态切换），构建产物由 FastAPI 静态托管；
3. `m5_views_console/cli/verify_views.py`：只读核对 CLI（视图口径断言 + 数据库 ↔ 页面 API 对比）；
4. `evidence/sql-ui/`：页面-数据库核对清单与真实执行输出。

视图 DDL 与迁移不在此模块：权威定义在
[`docs/database-design.md`](../../docs/database-design.md) 第 5 章与
[`0002_analysis_views.py`](../m1-transaction-integration/migrations/versions/0002_analysis_views.py)。

## 目录

```
modules/m5-views-console/
├── README.md
├── views/queries.sql              # 四视图口径 + 可执行 SELECT + SQL != UI
├── m5_views_console/
│   └── cli/verify_views.py        # 只读核对 CLI（python -m m5_views_console.cli.verify_views）
├── cli/verify_views.py            # 兼容入口（结构门禁约定路径，转发到包内实现）
├── frontend/                      # Vue 3.5 + Vite 8 + Tailwind 3.4 控制台
│   ├── src/pages/                 # 四个页面
│   ├── src/components/            # KPI/趋势/意图/风险等组件
│   ├── src/api/                   # /api/* 客户端
│   ├── dist/                      # 构建产物（后端 WEB_DIST_DIR 托管）
│   └── verify/                    # 部署/令牌/交互检查脚本
├── tests/integration/test_views.py# 四视图集成测试（真实 MySQL 测试库）
└── evidence/                      # deploy / visual / sql-ui 证据
```

## 对外契约

### 页面路由（hash 模式，`frontend/src/router/index.ts`）

| 路由 | 页面 | 关键数据来源 |
| --- | --- | --- |
| `#/` | 首页概览 | `/api/overview?range=all`、`/api/trend`、`/api/rules/effectiveness`、`/api/attackers` |
| `#/attackers` | 攻击者列表 | `/api/attackers`、`/api/attackers/summary` |
| `#/attackers/:ip` | 攻击者详情与时间线 | `/api/attackers/{ip}`、`/api/sessions/{id}/timeline` |
| `#/alerts` | 告警列表 | `/api/alerts`、`/api/alerts/summary` |

路由为 `createWebHashHistory`，深层路径刷新不会 404；`/` 下其余路径重定向到 `#/`。

### 主题（深色 / 浅色）

- 令牌：`frontend/src/assets/main.css` 的 `:root`（深色）与 `html.light`（浅色）各定义一组
  `--c-*`（RGB 三元组）、`--chart-*`、`--shadow-panel`；`tailwind.config.js` 颜色全部映射到
  `rgb(var(--c-*) / <alpha-value>)`。浅色取值来自 `ux/stitch_database_honeypot_analytics_console_light/`。
- 切换：`frontend/src/composables/theme.ts`，模式 `system|light|dark`，持久化键
  `localStorage["dbh-theme"]`；`system` 模式监听 `prefers-color-scheme` 实时跟随，
  `system → 浅色 → 深色 → system` 循环。`index.html` 内联脚本在首屏前应用主题，避免闪烁。
- 验收：`verify/token-audit.mjs`（双主题令牌齐全 + 0 裸色值）、`verify/run-check.mjs`
  （实时跟随/三态/持久化 + 四页浅色渲染）、`verify/capture-baseline.mjs --theme light`
  （浅色基线截图）。见 `evidence/visual/theme-evidence.md`。

### 静态资源挂载

- 构建入口 `frontend/index.html`，产物目录由 `WEB_DIST_DIR` 指定，默认
  `modules/m5-views-console/frontend/dist`；
- M1 的 FastAPI 在 [`api/app.py`](../m1-transaction-integration/m1_transaction_integration/api/app.py)
  中以 `StaticFiles(directory=WEB_DIST_DIR, html=True)` 挂载到 `/`，因此**页面与 `/api/*` 同源**，
  无需额外 CORS；
- 资源路径为 `/assets/*`（带内容哈希）、页面 favicon 为 `/favicon-*.svg`。

### 视图口径（详见 [`views/queries.sql`](views/queries.sql)）

| 视图 | 用途 | 页面/API |
| --- | --- | --- |
| `v_session_risk_summary` | 每会话事件/查询/命中/告警汇总，重算风险分与存储分对账 | 攻击者详情会话摘要与时间线开口 |
| `v_attacker_profile_summary` | 每来源画像、会话/告警计数、稳定排序的主要意图、风险等级 | 首页高风险 KPI/TOP5、攻击者列表、详情画像、`/api/overview` |
| `v_daily_attack_trend` | 按 UTC 自然日的趋势、`LAG` 环比、累计与繁忙排名 | 首页趋势图、`/api/trend` |
| `v_rule_effectiveness` | 每规则命中覆盖、告警数、命中率与排名 | 首页意图环图、`/api/rules/effectiveness` |

统一口径：视图实时聚合、不物化、不写 `ORDER BY`；风险分为
`LEAST(100, Σ 每 rule_code 的 MAX(risk_weight))`，等级阈值 ≥80/≥60/≥30；
`stored_*` 与 `calculated_*` 并列用于对账。`SQL != UI`（UTC+8 展示、分页/筛选、
补日补 0、千分位格式化）见 `views/queries.sql` 末尾说明。

## 依赖

- Python：`sqlalchemy[asyncio]`、`asyncmy`、`pydantic-settings`（经 `shared/` 读取
  `READONLY_DATABASE_URL`）；CLI 只用标准库 `urllib` 访问 API；
- 运行时：M1 API（uvicorn）提供 `/api/*` 并托管 `frontend/dist`；
- 数据库：MySQL 8（视图由 M1 Alembic 迁移创建）；核对使用只读账号 `honeypot_app_ro`；
- 前端构建：Node + pnpm 10（`corepack pnpm`），Vue 3.5、Vite 8、Tailwind 3.4；
- 证据脚本：Playwright（`@playwright/test`，已在 `frontend/devDependencies`）。

## 复现命令（仓库根）

```bash
# 环境（不要用仓库 .venv）
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console
PY=/tmp/dbh-venv/bin/python

# 数据库与演示数据（可选，已有数据时跳过）
make db-up && make migrate && make seed

# 前端构建 / 独立开发服务器（构建产物由后端统一托管）
make frontend-build              # 等价 cd modules/m5-views-console/frontend && pnpm build
make frontend-dev                # Vite dev server: http://127.0.0.1:5173
make api                         # uvicorn: http://127.0.0.1:8000

# 四视图代表性查询（真实执行 → evidence/sql-ui/queries-output.txt）
"$PY" -m m5_views_console.cli.run_queries

# 视图口径断言（只读，全部通过退出码 0）
"$PY" -m m5_views_console.cli.verify_views

# 视图断言 + 数据库 ↔ 页面 API 对比，JSON 输出
"$PY" -m m5_views_console.cli.verify_views --check-pages --json

# 可选参数：--base-url http://127.0.0.1:8000、--json
# 退出码：0 全通过；1 有断言失败；2 数据库/API 连接错误

# 页面 DOM 显示值抓取（Playwright，Linux/macOS 均可指定浏览器）
cd modules/m5-views-console/frontend
BASE_URL=http://127.0.0.1:8000 PLAYWRIGHT_CHROMIUM="<chromium 可执行文件>" \
  node --input-type=module -e "$(cat ../evidence/sql-ui/capture_pages.mjs)" \
  > ../evidence/sql-ui/page-dom-capture.json
```

也可用 Makefile：`make structure`、`make lint`、`make test`、`make frontend-build`、
`make verify`（13 步部署验收）。

## 证据索引

| 证据 | 路径 | 内容 |
| --- | --- | --- |
| 页面-数据库核对清单 | [`evidence/sql-ui/checklist.md`](evidence/sql-ui/checklist.md) | 4 组（概览 KPI / 告警统计 / 攻击者列表 / 攻击者详情）逐层核对 |
| CLI JSON | [`evidence/sql-ui/verify-views.json`](evidence/sql-ui/verify-views.json) | 16 条视图断言 + 21 条 DB↔API 核对，含 `db_value/api_value/ok` |
| SQL 执行输出 | [`evidence/sql-ui/queries-output.txt`](evidence/sql-ui/queries-output.txt) | 四条代表性 SELECT 真实结果（行数/耗时/表格） |
| 页面 DOM | [`evidence/sql-ui/page-dom-capture.json`](evidence/sql-ui/page-dom-capture.json) | 四页 KPI/统计卡/首行文本与 `/api/*` 请求状态 |
| 部署验收 | [`evidence/deploy/summary.md`](evidence/deploy/summary.md) | 部署 13 步与浏览器检查汇总 |
| 视觉验收 | [`evidence/visual/summary.md`](evidence/visual/summary.md) | verify2 汇总：区域 82/82、令牌 0/28、截图 12 张 |
| 区域清单 | [`evidence/visual/region-checklist.md`](evidence/visual/region-checklist.md) | 四页 × 两视口 21 区域覆盖率 100%，0 缺失/重叠/溢出 |
| 令牌抽样 | [`evidence/visual/token-sampling.md`](evidence/visual/token-sampling.md) | 深/浅两主题 100/100 计算值命中 `--c-*` |
| 主题证据 | [`evidence/visual/theme-evidence.md`](evidence/visual/theme-evidence.md) | 实时跟随/三态循环/持久化/浅色四页/截图基线 |
| 差异闭环 | [`evidence/visual/adjudication-checklist.md`](evidence/visual/adjudication-checklist.md) | 附录 B 20 + 补充 8 共 28/28 闭环 |
| 复核指南 | [`evidence/visual/review-guide.md`](evidence/visual/review-guide.md) | 10 分钟复核步骤与差异登记规则 |
| 交互验收 | [`evidence/interactions.md`](evidence/interactions.md) | 18/18 交互（真实 PATCH 后还原） |
| 性能基线 | [`evidence/deploy/performance.md`](evidence/deploy/performance.md) | API p95 ≤14ms；JS gzip 70.2KB |
| 证据总索引 | [`evidence/README.md`](evidence/README.md) | 全部证据的复现命令与产物 |

## 最近验证（2026-11-25）

- 数据库：MySQL 8.0.46 `honeypot_dev`；数据 214 sessions / 2525 attack_log /
  14 attacker_profile / 11 rule_hits / 8 alerts。
- `views/queries.sql` 四条 SELECT 全部实跑成功（见 `queries-output.txt`）。
- `verify_views.py`：视图断言 **16/16 PASS**；`--check-pages --json`
  DB↔API 核对 **21/21 PASS**，退出码 **0**（见 `verify-views.json`）。
- 页面 DOM（Playwright）：首页 KPI `214 / 1,222 / 8 / 1`、攻击者列表 `1 / 14 IP`、
  详情 `85 / 1 / 6` 与 SQL/API 一致。
- 已知问题（不在本模块视图/CLI 范围）：当前部署的 `frontend/dist` 为旧构建，
  告警页统计卡因 `/api/alerts/summary` 只传 `from` 返回 422 而显示 `—`；
  前端源码 `AlertsPage.vue:195` 已传 `from`+`to`，重新构建 dist 即可修复。
  详见 [`checklist.md` 组 2](evidence/sql-ui/checklist.md#组-2告警统计页面-alerts)。
- 结构门禁 `check_structure` 中 M5 待交付项已清零；`ruff check modules/m5-views-console` 干净；
  `pytest modules/m5-views-console/tests` 通过。
