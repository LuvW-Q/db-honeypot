# 原型差异闭环表（adjudication-checklist.md，T071）

- **范围**：`spec.md` 附录 B 第 1–20 条 + 实现期补充 21–28 条，共 28 条。
- **判定口径**：每条给出「落地位置 + 验证方式 + 状态」；`一致` 指实现与裁定终态一致，
  `差异` 保留原因，`不接受` 不允许存在（当前为 0）。
- **复核方式**：`make verify2` 的区域核对（`region-checklist.md`）、令牌审计、
  `interaction-check.mjs`、四页截图基线（深/浅两套）。
- **结论**：**28/28 已闭环**，无未决项。

## 1. 主裁定（附录 B 第 1–20 条）

| # | 原型现象 | 裁定落地位置 | 验证方式 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | DESIGN.md 画布色与截图令牌不一致 | `src/assets/main.css` 以 `#051424` 系为准；`ux/.../DESIGN.md` 数值段落标注"以截图令牌为准" | `token-audit.mjs` 0 违规；两主题 44 + 44 令牌对齐 | 一致 |
| 2 | 跨页严重度配色不一致 | `tailwind.config.js` `sev-critical/high/medium/low` 唯一映射；`RiskBadge`/`IntentTag`/图表统一引用 | 四页截图 + `token-sampling.md` 100/100 | 一致 |
| 3 | 侧栏第 4 项缺编号 | `App.vue` 四项导航 `01–04` 连续，告警徽标保留右侧 | `run-check` nav 断言 + 截图 | 一致 |
| 4 | 详情/概览缺一级标题 | 四页均有唯一 `<h1>`（详情页为动态 IP） | `interaction-check` `h1Count=1`；`run-check` 标题断言 | 一致 |
| 5 | 仅详情页有底部状态块 | `App.vue` `SHELL-STATUS` 四页共用（内核视图/权限/规格版本） | 区域清单壳层 5 项均 present | 一致 |
| 6 | 容器圆角混用 | 统一：容器 `rounded-lg`(8px)、控件/表格/徽标 `rounded`(4px)、状态点 `rounded-full` | `token-audit` 圆角类白名单；截图对照 | 一致 |
| 7 | `rounded-full` 被配置 12px 导致圆点不圆 | `tailwind.config.js` `borderRadius.full = 9999px`，状态点用 `rounded-full` | 截图状态点为正圆 | 一致 |
| 8 | 概览时间筛选只改样式 | `useOverview` 写 `range` 并重新取数；URL 同步 | `interaction-check` 7 天：请求 `range=7d`、KPI 214→5 | 一致 |
| 9 | 列表"实时重查"假动画 | 真实 `GET /api/attackers`，按钮 loading + 最近更新时间 | `interaction-check` 刷新请求列表；`OverviewPage` 刷新用例 | 一致 |
| 10 | 空态开关死代码 | `EmptyState.vue` 统一空态 + 重置入口；无不可达分支 | 交互脚本空态路径 + 代码无死链 | 一致 |
| 11 | 导出/DMZ 隔离/SQL 回放无后端 | 禁用态 + `title="演示未开放：…"`；不实现主动反制 | `interaction-check` 3 个禁用控件文案 | 一致 |
| 12 | 批量已读无批量接口 | 逐条 `PATCH` 并发 2，`BatchResult.failed` 部分失败提示 | `interaction-check` patches=2、未读 8→6 后还原 | 一致 |
| 13 | 处理完成率无依据 | `/api/alerts/summary` 返回 `resolution_rate`（已读/全部，分母 0 显示 `—`），页面标注口径 | `verify_views` 21 条核对；告警页统计卡 | 一致 |
| 14 | `LIVE UTC+8` 为静态文本 | `Clock.vue` 每秒刷新，UTC+8 时区 | 截图时间随系统变化；`run-check` 无异常 | 一致 |
| 15 | 依赖 Google Fonts/Tailwind CDN/外链 | `@fontsource*`、`material-symbols` 本地包；无外链 | `run-check` `external_requests=[]` 12 次运行 | 一致 |
| 16 | Material Symbols 重复引入 | 仅 `main.ts` 一次引入，按需图标子集 | 构建产物无重复字体请求 | 一致 |
| 17 | 示例数据自相矛盾 | 页面全部取接口/视图值；`—` 表示无数据 | `token-audit` 不适用；代码扫描无硬编码样例；`verify_views` 口径核对 | 一致 |
| 18 | 导航 `href="#"` 无路由 | hash 路由 `/`、`/attackers`、`/attackers/:ip`、`/alerts`，支持直达与刷新 | `run-check` 四页直达；`interaction-check` TOP5 下钻 | 一致 |
| 19 | 详情"关联会话 12 条"与列表 3 条不一致 | 关联会话数由 `/api/attackers/{ip}` 的 sessions 计算 | `verify_views` 页面-数据库核对组 4 | 一致 |
| 20 | 四页无 `<title>`/favicon | `router` 每页设置 `document.title` 与 `favicon-*.svg` | `run-check` 4 页 title/favicon 断言 | 一致 |

## 2. 补充裁定（实现期 21–28 条）

| # | 原型现象 | 裁定落地位置 | 验证方式 | 状态 |
| --- | --- | --- | --- | --- |
| 21 | 告警类型 6 类 | 收敛为 `bruteforce`/`data_dump`/`destructive`；`AlertsPage` 筛选项与统计只渲染 3 类 | 告警接口 CHECK 约束 + 页面筛选项截图 | 一致 |
| 22 | 实体标签为业务库名 | 改为真实网络归属 `private/loopback/reserved/public`，`shared` 由 IP 派生；列头标"网络归属" | `v_attacker_profile_summary.network_scope`；`verify_views` 核对 | 一致 |
| 23 | 概览"94.2% 拦截" | `query_blocked_rate = denied/query`，窗口无查询显示 `—` | `/api/overview` 字段；页面 KPI；`test_api_extensions` | 一致 |
| 24 | 详情"平均时长 4m 12s" | `avg_session_seconds` 由会话起止真实计算，无会话 `—` | `verify_views` 组 4；详情页截图 | 一致 |
| 25 | 详情"高危操作" | `high_risk_op_count` = `data_dump`/`destructive` 规则命中数 | `/api/attackers/{ip}`；详情画像卡 | 一致 |
| 26 | KPI 副标假趋势 | `sessions_delta_pct`/`queries_delta_pct` 今日 vs 昨日，昨日为 0 显示 `—` | 概览页副标；`test_api_extensions` | 一致 |
| 27 | 详情"高风险会话"阈值 | 复用 `v_session_risk_summary.session_risk_score ≥ 60`，不新增 DDL | 详情页会话表；`verify_views` 视图断言 | 一致 |
| 28 | 时间线 4 类筛选 | 映射：认证=`login/login_success/login_failure`；查询 SQL=`query/query_denied`；规则命中=存在 `rule_hits`；全部=并集 | `interaction-check` 仅认证 16→8；`SessionTimeline` 计数 | 一致 |

## 3. 复核命令与证据

```bash
cd modules/m5-views-console/frontend
export PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers COREPACK_HOME=/tmp/corepack
corepack pnpm exec node verify/token-audit.mjs --out ../evidence/deploy/theme-run/token-audit.json
corepack pnpm exec node verify/run-check.mjs --base-url http://127.0.0.1:8000 --out ../evidence/deploy/theme-run
corepack pnpm exec node verify/interaction-check.mjs --base-url http://127.0.0.1:8000 --out ../evidence/deploy/theme-run
corepack pnpm exec node verify/region-audit.mjs --base-url http://127.0.0.1:8000 --out ../evidence/visual/region-checklist.md
```

- 区域一致性：[`region-checklist.md`](region-checklist.md)（100.0%，82/82）
- 令牌抽样：[`token-sampling.md`](token-sampling.md)（100/100）
- 交互：[`../interactions.md`](../interactions.md)（18/18）
- 主题：[`theme-evidence.md`](theme-evidence.md)
- 部署：[`../deploy/summary.md`](../deploy/summary.md)、[`../deploy/theme-run/browser.json`](../deploy/theme-run/browser.json)

## 4. 边界

- 本表是**差异裁定闭环**，不是逐像素比对；原型中的演示文案/数值与真实种子不同属于预期。
- 第 15 条“无外链”以浏览器网络请求为准，构建产物中的 sourcemap 注释不计入。
- 若后续改动触碰上述区域（导航、严重度、圆角、时间线映射），需同步更新本表并重跑对应脚本。
