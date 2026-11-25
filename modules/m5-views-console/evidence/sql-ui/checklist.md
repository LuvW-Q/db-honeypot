# M5 页面-数据库核对清单（T049）

本清单把「视图/SQL → 页面 API → 页面显示」三层逐项对齐，所有数字均为 2026-11-25
在真实 dev 库（`honeypot_dev`）与运行中的控制台（`http://127.0.0.1:8000`）实测得到。

| 项 | 值 |
| --- | --- |
| 取样时间 | 2026-11-25 13:19–13:22（UTC+8） |
| 数据库 | MySQL 8.0.46 @ `127.0.0.1:3306/honeypot_dev`，只读账号 `honeypot_app_ro` |
| API 服务 | `http://127.0.0.1:8000`（uvicorn，托管 `frontend/dist`） |
| 数据规模 | `sessions` 214 行 / `attack_log` 2525 行 / `attacker_profile` 14 行 / `rule_hits` 11 行 / `alerts` 8 行 |
| 页面抓取方式 | Playwright Chromium（headless）打开 `#/`、`#/alerts`、`#/attackers`、`#/attackers/198.51.100.17`，按 `data-region` 抓 DOM 文本 |

## 原始证据

| 证据 | 路径 | 说明 |
| --- | --- | --- |
| CLI 全量 JSON | [verify-views.json](verify-views.json) | 16 条视图口径断言 + 21 条 DB↔API 核对，全部 `ok=true` |
| 四视图代表性查询输出 | [queries-output.txt](queries-output.txt) | 4 条 SELECT 真实执行结果（MySQL 版本/行数/耗时/表格） |
| 页面 DOM 抓取 | [page-dom-capture.json](page-dom-capture.json) | 四页 KPI/统计卡/首行文本 + `/api/*` 请求状态 |
| 查询口径说明 | [../../views/queries.sql](../../views/queries.sql) | 四视图用途/页面/口径/已知限制 + `SQL != UI` |
| 原始脚本 | [run_queries.py](../../m5_views_console/cli/run_queries.py)、[capture_pages.mjs](capture_pages.mjs) | 可重复执行，只读 |

## 复现命令（仓库根）

```bash
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console
PY=/tmp/dbh-venv/bin/python

# 1) 四视图代表性查询 → queries-output.txt
"$PY" -m m5_views_console.cli.run_queries

# 2) 视图断言 + DB↔API 核对 → verify-views.json（本文件结论即来自该输出）
"$PY" -m m5_views_console.cli.verify_views --check-pages --json \
  > modules/m5-views-console/evidence/sql-ui/verify-views.json

# 3) 页面 DOM 抓取 → page-dom-capture.json
cd modules/m5-views-console/frontend
BASE_URL=http://127.0.0.1:8000 \
PLAYWRIGHT_CHROMIUM="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-mac-arm64/chrome-headless-shell" \
  node --input-type=module -e "$(cat ../evidence/sql-ui/capture_pages.mjs)" \
  > ../evidence/sql-ui/page-dom-capture.json
```

## 结论速览

| # | 核对组 | SQL ↔ API | 页面 ↔ API | 说明 |
| --- | --- | --- | --- | --- |
| 1 | 概览 KPI（#/） | ✅ | ✅ | sessions/queries/alerts_unread/high_risk_attackers/total 全一致 |
| 2 | 告警统计（#/alerts） | ✅ | ❌ | 数据层一致；当前部署的 `dist` 构建产物只传 `from` 导致 422，统计卡显示 `—`（根因见组 2） |
| 3 | 攻击者列表（#/attackers） | ✅ | ✅ | total=14、high_risk_count=1、首行 85/1/6 全一致 |
| 4 | 攻击者详情（#/attackers/:ip） | ✅ | ✅ | connections=1、queries=6、session_count=1、risk_score=85 全一致 |

---

## 组 1：概览 KPI（页面 `#/`）

**页面绑定（源码）**：`frontend/src/pages/OverviewPage.vue:185/196/207/218/222`

**视图 SQL 与 SQL 实际结果**（`:upper = overview.generated_at = 2026-11-25 05:21:56` UTC）：

| KPI | SQL | SQL 结果 |
| --- | --- | --- |
| 连接数 sessions | `SELECT COUNT(*) FROM sessions WHERE started_at <= :upper` | **214** |
| 查询数 queries | `SELECT COUNT(*) FROM attack_log WHERE event_type='query' AND event_time <= :upper` | **1222** |
| 未处理告警（页面第三卡） | `SELECT COALESCE(SUM(is_read=0),0) FROM alerts WHERE created_at <= :upper` | **8** |
| 告警总数 alerts（API 字段） | `SELECT COUNT(*) FROM alerts WHERE created_at <= :upper` | **8** |
| 高风险攻击者（≥60） | `SELECT COUNT(*) FROM v_attacker_profile_summary WHERE risk_level IN ('high','critical') AND last_seen <= :upper` | **1** |
| 攻击者总量 attackers_total | `SELECT COUNT(*) FROM v_attacker_profile_summary WHERE last_seen <= :upper` | **14** |

**API 实际返回**（`GET /api/overview?range=all`，2026-11-25T05:21:56Z）：

```json
{"sessions":214,"queries":1222,"alerts":8,"high_risk_attackers":1,"attackers_total":14,
 "high_risk_ratio":0.0714,"alerts_unread":8,"range":"all","window_start":null}
```

**页面显示值**（`page-dom-capture.json`，DOM `[data-region="OV-KPI"]`）：

| KPI 卡 | 页面文本 |
| --- | --- |
| 连接数 · SESSIONS | `214`；备注「今日新增 +0 会话」；`SRC: sessions` |
| 查询数 · QUERIES | `1,222`；「19.8% 拦截」；`SRC: attack_log` |
| 未处理告警 · ALERTS | `8`；「严重 2 · 高危 3」；`SRC: alerts 未读` |
| 高风险攻击者 · RISK >= 60 | `1`；「/ 14 总量」「占比 7.1%」；`SRC: v_attacker_profile` |

**是否一致**：✅ 一致。
- 数值层：SQL = API = 页面（214 / 1222 / 8 / 1 / 14）。
- 展示层差异是格式而非数据：`1222` → 页面 `1,222`（zh-CN 千分位）；`0.0714` → 页面 `7.1%`；
  页面第三卡绑定的是 `alerts_unread`（`OverviewPage.vue:207`），不是 `alerts`，本次两者同为 8。
- 时区：页面右上角时钟/「今日」按 UTC+8；API `today_window` 为 `16:00Z→16:00Z` 的 UTC+8 自然日边界。

---

## 组 2：告警统计（页面 `#/alerts`）

**页面绑定（源码）**：`frontend/src/pages/AlertsPage.vue:314/321/328/335`（`summary.total / unread / resolution_rate / peak_window.count`）

**视图 SQL 与 SQL 实际结果**（`:upper = alerts/summary.generated_at = 2026-11-25 05:21:56` UTC）：

| 指标 | SQL | SQL 结果 |
| --- | --- | --- |
| total | `SELECT COUNT(*) FROM alerts WHERE created_at < :upper` | **8** |
| unread | `SELECT COALESCE(SUM(is_read=0),0) FROM alerts WHERE created_at < :upper` | **8** |
| read | `SELECT COUNT(*) - COALESCE(SUM(is_read=0),0) FROM alerts WHERE created_at < :upper` | **0** |
| resolution_rate | `SELECT CASE WHEN COUNT(*)=0 THEN 0.0000 ELSE ROUND((COUNT(*)-COALESCE(SUM(is_read=0),0))/COUNT(*),4) END FROM alerts WHERE created_at < :upper` | **0.0000** |

**API 实际返回**（`GET /api/alerts/summary`，2026-11-25T05:21:56Z）：

```json
{"total":8,"unread":8,"read":0,"resolution_rate":0.0,
 "by_severity":{"low":0,"medium":3,"high":3,"critical":2},
 "by_alert_type":{"bruteforce":3,"data_dump":3,"destructive":2},
 "today_new":8,"today_delta_pct":null,
 "peak_window":{"start":"2026-11-25T05:00:00Z","end":"2026-11-25T06:00:00Z","count":8}}
```

**页面显示值**（`page-dom-capture.json`，DOM `[data-region="AL-STATS"]`）：

| 统计卡 | 页面文本 |
| --- | --- |
| 告警总数 | `—`（今日 +0） |
| 未读告警 | `—` |
| 处置完成率 | `—`（已读 0 / 共 0） |
| 今日告警峰值 | `0`（暂无今日高峰） |

页面同时出现错误横幅：`请求参数校验失败（错误码 VALIDATION_ERROR，请求编号 …）`。

**是否一致**：
- SQL ↔ API：✅ 一致（8 / 8 / 0 / 0.0）。
- 页面 ↔ API：❌ 本次部署的页面统计卡未显示数值。

**根因（可复现，非视图/数据问题）**：
1. 页面 DOM 抓取记录到 `GET /api/alerts/summary?from=2026-11-18T16:00:00.000Z` → **422**；
   API 契约 §4.1 要求 `from`/`to` 成对出现，只传 `from` 即 `VALIDATION_ERROR`。
2. 当前服务托管的是旧构建产物：`frontend/dist/assets/AlertsPage-Cs_tmRds.js` 中调用为
   `getAlertsSummary({from:e})`（只传 `from`）。
3. 前端源码已正确传成对参数：`frontend/src/pages/AlertsPage.vue:195`
   `getAlertsSummary({ from, to: toParam() })`。
4. 因此这是 **`dist` 构建产物滞后**，不属于 M5 `views/`、CLI 或 `evidence/sql-ui/` 的修改范围；
   重新执行前端 `pnpm build` 生成 dist 即可修复。数据层无需改动：直接 `curl /api/alerts/summary`
   与数据库完全一致，且首页「未处理告警」KPI（绑定 `alerts_unread`）显示 `8` 正常。

---

## 组 3：攻击者列表（页面 `#/attackers`）

**页面绑定（源码）**：`AttackersPage.vue:202/203`（`summary.high_risk_count / summary.total`）、
列表行 `AttackersPage.vue:354/355/358`（`item.total_connections / total_queries / risk_score`）。

**视图 SQL 与 SQL 实际结果**：

| 指标 | SQL | SQL 结果 |
| --- | --- | --- |
| 攻击者总数 | `SELECT COUNT(*) FROM v_attacker_profile_summary` | **14** |
| 高危及严重数 | `SELECT COALESCE(SUM(risk_level IN ('high','critical')),0) FROM v_attacker_profile_summary` | **1** |
| 首行 risk_score | `SELECT stored_risk_score FROM v_attacker_profile_summary WHERE source_ip='198.51.100.17'` | **85**（calculated 亦 85） |
| 首行 total_connections | `SELECT total_connections FROM v_attacker_profile_summary WHERE source_ip='198.51.100.17'` | **1** |
| 首行 total_queries | `SELECT total_queries FROM v_attacker_profile_summary WHERE source_ip='198.51.100.17'` | **6** |

**API 实际返回**：

```json
// GET /api/attackers/summary
{"total":14,"high_risk_count":1,"latest_intent":{"intent_type":"data_dump","rule_code":"R04","source_ip":"198.51.100.23"}}
// GET /api/attackers?page_size=1
{"items":[{"source_ip":"198.51.100.17","total_connections":1,"total_queries":6,"risk_score":85,"risk_level":"critical"}],
 "page":1,"page_size":1,"total":14,"total_pages":14}
```

**页面显示值**（DOM `[data-region="AT-HEAD"]` 与 `AT-TABLE` 首行）：

- 头部统计：`高危及严重攻击源 1 / 14 IP`
- 列表计数：`筛选结果：14 个实`
- 首行：`198.51.100.17 … 1 会话 6 次查询 85 严重`
- 时间格式：DB/API `2026-11-18T06:00:00Z` → 页面 `2026-11-18 14:00:00`（UTC+8）

**是否一致**：✅ 一致（total 14、high_risk_count 1、首行 85 / 1 / 6）。
补充：列表页 `page_size=1` 只返回首行，页面仍显示 `total=14`，这是分页与全量的差别，不是数据不一致。

---

## 组 4：攻击者详情（页面 `#/attackers/198.51.100.17`）

**页面绑定（源码）**：`AttackerDetailPage.vue:187/191/195`（`attacker.risk_score / session_count / total_queries`）
以及 `:238`（`total_connections`）、`:242`（`total_queries`）。

**视图 SQL 与 SQL 实际结果**：

```sql
SELECT total_connections, total_queries, session_count, stored_risk_score,
       calculated_risk_score, risk_level, alert_count
FROM v_attacker_profile_summary WHERE source_ip = '198.51.100.17';
-- 1 | 6 | 1 | 85 | 85 | critical | 3

SELECT COUNT(*) FROM v_session_risk_summary WHERE source_ip = '198.51.100.17';
-- 1（会话摘要 1 行）
```

**API 实际返回**（`GET /api/attackers/198.51.100.17`）：

```json
{"attacker":{"source_ip":"198.51.100.17","total_connections":1,"total_auth_attempts":8,
 "total_auth_failures":8,"total_queries":6,"risk_score":85,"calculated_risk_score":85,
 "risk_level":"critical","session_count":1,"high_risk_session_count":1,"alert_count":3,
 "intent_labels":"destructive,data_dump,bruteforce","triggered_rule_codes":"R02,R04,R05",
 "avg_session_seconds":15,"auth_success_count":0,"high_risk_op_count":2},
 "sessions":[{"session_id":"5a060001-0000-4000-8000-000000000001","event_count":16,
 "query_count":6,"risk_score":85,"risk_level":"critical","alert_count":3}]}
```

**页面显示值**（DOM `[data-region="AD-HEAD"]` / `AD-PROFILE`）：

- 头部：`综合风险分85 累计会话1 执行查询6 认证尝试8(失败 8 / 成功 0)`
- 画像：`累计连接与会话 1 次 (平均时长 15 秒)`、`敏感查询捕获量 6 条 (高危操作 2 次)`、
  `风险评分: 85（严重威胁）`、`THREAT LEVEL: CRITICAL`
- 会话摘要：`共 1 条关联记录`、`16 个事件`、`6 条`、`85 严重`
- 时间转换：`first_seen 2026-11-18T06:00:00Z` → 页面 `2026-11-18 14:00:00`

**是否一致**：✅ 一致（total_connections=1、total_queries=6、session_count=1、risk_score=85、alert_count=3）。

---

## 附：SQL 与页面口径差异备忘

| 页面元素 | SQL/视图口径 | 差异说明 |
| --- | --- | --- |
| 首页「未处理告警」 | `alerts.is_read=0` 计数 | 页面绑定 `alerts_unread`，不是 `alerts` 总数 |
| 首页「高风险攻击者」 | 视图 `risk_level IN ('high','critical')`，阈值 ≥60 | 与页面标签 `RISK >= 60` 一致；不是 ≥80 |
| 首页「查询数」 | `attack_log.event_type='query'` 行数 | 不是 `sessions.request_count`，也不是 `returned_rows` 之和 |
| 趋势图日期 | `v_daily_attack_trend` 仅有事件日 | `GET /api/trend` 补连续日期/补 0，页面以接口为准 |
| 列表分页 | 视图返回全量 | API `page/page_size` 分页，页面只渲染当前页 |
| 时间显示 | DB 存 UTC | 页面统一 UTC+8；「今日/昨日」为 UTC+8 自然日窗口 |
| 数字格式 | SQL 原始数值 | 页面 `formatNumber` 千分位、`formatPercent` 乘 100 保留 1 位 |
