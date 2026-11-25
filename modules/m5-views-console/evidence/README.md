# M5 证据索引

本目录收录 M5「分析视图与控制台」的验收证据，分三类：

- `deploy/`：部署验收 13 步与浏览器检查汇总；
- `visual/`：双分辨率四页截图基线与令牌审计汇总；
- `sql-ui/`：T048/T049 的视图口径执行、只读核对 CLI、页面-数据库核对清单。

统一环境：仓库根运行、`PYTHONPATH` 含四个模块目录、解释器 `/tmp/dbh-venv/bin/python`、
MySQL 8 @ `127.0.0.1:3306/honeypot_dev`（只读账号 `honeypot_app_ro`）、
API `http://127.0.0.1:8000`（uvicorn，托管 `frontend/dist`）。

| 证据编号 | 对应用户故事 / FR | 复现命令 | 期望输出 | 产物路径 | 依赖 | 最近验证时间 |
| --- | --- | --- | --- | --- | --- | --- |
| M5-SQL-01 | US3 / T048 视图口径 | `PYTHONPATH=... /tmp/dbh-venv/bin/python -m m5_views_console.cli.run_queries` | 四条 SELECT 全部成功，含 MySQL 版本/行数/耗时/结果表 | [`sql-ui/queries-output.txt`](sql-ui/queries-output.txt) | dev 库、四个视图已迁移 | 2026-11-25 |
| M5-SQL-02 | US3 / T048 只读核对 CLI | `PYTHONPATH=... /tmp/dbh-venv/bin/python -m m5_views_console.cli.verify_views --check-pages --json` | 16 条视图断言 + 21 条 DB↔API 核对全 `ok=true`，退出码 0 | [`sql-ui/verify-views.json`](sql-ui/verify-views.json) | dev 库、API 8000 | 2026-11-25 |
| M5-SQL-03 | US3 / T049 页面-数据库核对 | 见 [`sql-ui/checklist.md`](sql-ui/checklist.md) 顶部「复现命令」 | 4 组核对：概览 KPI / 告警统计 / 攻击者列表 / 攻击者详情；逐层记录 SQL、SQL 结果、API、页面值 | [`sql-ui/checklist.md`](sql-ui/checklist.md) | M5-SQL-01/02、API 8000、Playwright | 2026-11-25 |
| M5-SQL-04 | US3 / T049 页面显示值 | `cd modules/m5-views-console/frontend && BASE_URL=http://127.0.0.1:8000 PLAYWRIGHT_CHROMIUM=<chromium 可执行文件> node --input-type=module -e "$(cat ../evidence/sql-ui/capture_pages.mjs)" > ../evidence/sql-ui/page-dom-capture.json` | 四页 KPI/统计卡/首行文本与 `/api/*` 请求状态（含告警页 422 记录） | [`sql-ui/page-dom-capture.json`](sql-ui/page-dom-capture.json) | 前端 `dist`、Playwright 浏览器 | 2026-11-25 |
| M5-SQL-05 | T048 口径说明书 | 直接阅读 [`../views/queries.sql`](../views/queries.sql) | 四视图各一节：视图名/用途/页面/API/口径/已知限制 + 可执行 SELECT + `SQL != UI` | [`../views/queries.sql`](../views/queries.sql) | 无（文档） | 2026-11-25 |
| M5-DEPLOY-01 | US1 / 部署验收 | `make verify` | 13 步部署验收与浏览器检查汇总（含失败步骤与复现命令） | [`deploy/summary.md`](deploy/summary.md)、`deploy/run-1/steps.tsv` | Docker、MySQL、Node、Playwright | 2026-11-25 |
| M5-VISUAL-01 | US2 / 视觉验收 | `make verify2` | 双分辨率四页截图基线、令牌审计、区域清单汇总 | [`visual/summary.md`](visual/summary.md) | 前端产物、Playwright | 2026-11-25 |
| M5-VISUAL-02 | FR-133/134 / T084 双主题 | `cd frontend && corepack pnpm exec node verify/run-check.mjs --base-url http://127.0.0.1:8000 --out ../evidence/deploy/theme-run` | `interactions.theme.ok=true`：默认 system、系统切换实时跟随、按钮 system→light→dark→system、刷新持久化；浅色四页 `console_errors=[]`/`overflow=false`/`missing_regions=[]` | [`deploy/theme-run/browser.json`](deploy/theme-run/browser.json)、[`visual/theme-evidence.md`](visual/theme-evidence.md) | 最新主题 `dist`、Playwright | 2026-11-25 |
| M5-VISUAL-03 | FR-134 / T084 区域清单 | `cd frontend && corepack pnpm exec node verify/region-audit.mjs --base-url http://127.0.0.1:8000 --out ../evidence/visual/region-checklist.md --json ../evidence/visual/region-audit.json` | 四页 × 两视口：覆盖率 100.0%（82/82），缺失/额外/页面区域重叠/横向溢出均为 0 | [`visual/region-checklist.md`](visual/region-checklist.md)、[`visual/region-audit.json`](visual/region-audit.json) | `dist`、Playwright | 2026-11-25 |
| M5-INTERACT-01 | US4 / T061 交互验收 | `cd frontend && corepack pnpm exec node verify/interaction-check.mjs --base-url http://127.0.0.1:8000 --out ../evidence/deploy/theme-run` | 18/18 PASS：范围/刷新/下钻/时间线/禁用文案/搜索/风险档/排序/告警筛选/单条与批量已读（真实 PATCH 后还原）/无障碍 | [`interactions.md`](interactions.md)、[`deploy/theme-run/interaction.json`](deploy/theme-run/interaction.json) | 固定种子、API 8000、Playwright | 2026-11-25 |
| M5-VISUAL-04 | US5 / T065 令牌抽样 | `cd frontend && corepack pnpm exec node verify/token-sampling.mjs --base-url http://127.0.0.1:8000` | 深/浅两主题 100/100 计算样式命中 `--c-*` 令牌（含 alpha 派生） | [`visual/token-sampling.md`](visual/token-sampling.md)、`visual/token-sampling.json` | `dist`、Playwright | 2026-11-25 |
| M5-VISUAL-05 | US6 / T066 复核指南 | 阅读 [`visual/review-guide.md`](visual/review-guide.md) | 10 分钟复核步骤、一键命令、差异登记规则 | [`visual/review-guide.md`](visual/review-guide.md) | 无 | 2026-11-25 |
| M5-VISUAL-06 | US6 / T071 差异闭环 | 阅读 [`visual/adjudication-checklist.md`](visual/adjudication-checklist.md) | 附录 B 20 条 + 补充 21–28 共 28/28 闭环，含落地位置与验证方式 | [`visual/adjudication-checklist.md`](visual/adjudication-checklist.md) | 区域/令牌/交互证据 | 2026-11-25 |
| M5-PERF-01 | T076 部署性能 | 见 [`deploy/performance.md`](deploy/performance.md) §1/§2 | API p95 ≤ 14ms（阈值 500ms）；JS gzip 合计 70.2KB（阈值 1.2MB） | [`deploy/performance.md`](deploy/performance.md) | 服务 8000 | 2026-11-25 |

## 说明

1. 所有证据均为**只读**产生：SQL 侧仅 `SELECT`，CLI 会话执行
   `SET SESSION TRANSACTION READ ONLY`，Playwright 只打开页面与 `GET /api/*`。
2. `queries-output.txt` / `verify-views.json` / `page-dom-capture.json` 含生成时间戳，
   重新执行会更新文件内容；数值应保持一致（演示数据为固定种子）。
3. 旧构建遗留问题已修复：此前 `frontend/dist` 为旧产物，告警页统计卡因
   `/api/alerts/summary` 只传 `from` 返回 422 而显示 `—`；当前前端同时传 `from`/`to`，
   最新构建（2026-11-25 14:53）下四页统计卡正常，`run-check` 的 HTTP 错误为 0。
   历史记录见 [`sql-ui/checklist.md` 组 2](sql-ui/checklist.md#组-2告警统计页面-alerts)。
4. 双主题截图基线：深色 `visual/baseline/`、浅色 `visual/baseline-light/`（各 8 张，
   含 `metadata.json` 的 theme 字段）；索引见 [`../../docs/screenshots/README.md`](../../docs/screenshots/README.md)。
5. 验收场景逐条记录见 `specs/002-ui-console-modularization/checklists/acceptance.md`（V00–V14）；
   部署 13 步与三轮稳定性见 `deploy/summary.md`。
5. 更详细的模块职责、路由/静态挂载契约与复现命令见 [`../README.md`](../README.md)。
