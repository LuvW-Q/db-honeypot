# 部署与验收脚本契约

**Feature**: `002-ui-console-modularization` | **Date**: 2026-11-25

对应 FR-107 至 FR-113、SC-016/017/024/026/027：验收必须在**真实部署路径**（生产构建
产物 + 后端统一托管 + 单地址）下完成，由一条命令可重复执行并产出证据。本文件定义
脚本接口、步骤、检查项、产物格式与退出码；实现细节（脚本内部代码）不属于本契约。

---

## 1. 前置条件

| 条件 | 检查方式 | 缺失时 |
| --- | --- | --- |
| 仓库根 `.env`（由 `.env.example` 复制） | 文件存在且含 `DATABASE_URL` | 退出码 2，提示 `cp .env.example .env` |
| Docker + Compose v2，MySQL 8 可用 | `docker compose version` + `docker compose ps` | 退出码 2 |
| Python 3.11+ 与 `uv`，项目可编辑安装（`uv sync`） | `uv run python -c "import shared"` | 退出码 2 |
| Node 24 + pnpm（`corepack pnpm`）与前端依赖 | `pnpm -v`、`node_modules` 存在 | 退出码 2 |
| Playwright 1.65.1 及 Chromium（或本机 Chrome） | `pnpm exec playwright --version`；浏览器缺失时用 `channel: "chrome"` | 退出码 2，提示 `pnpm exec playwright install chromium` |
| 端口 8000 可用 | 绑定尝试 | 退出码 2 |
| 网络（仅首次安装依赖/浏览器需要） | 不检查 | 文档说明；运行期断网是验收项 |

一次性准备命令（quickstart V00）：

```bash
cp .env.example .env          # 已存在则跳过
make db-up                    # docker compose up -d mysql
uv sync                       # 安装 shared + 5 模块与 dev 依赖
corepack pnpm --dir modules/m5-views-console/frontend install
corepack pnpm --dir modules/m5-views-console/frontend exec playwright install chromium
```

---

## 2. 脚本接口

```text
bash shared/deploy/verify_deploy.sh [选项]

选项:
  --base-url URL      验收地址，默认 http://127.0.0.1:8000
  --port PORT         未指定 --base-url 时用于启动后端，默认 8000
  --repeat N          连续执行 N 轮（SC-024 要求 3），默认 1
  --skip-build        复用已有 dist（调试用；正式验收禁用）
  --offline           断网验证：断网由脚本无法切换，需外部断网后加此参数；
                      仅执行页面加载与外网请求断言，跳过需要下载的步骤
  --keep              结束后保留后端进程与容器（调试）
  --json              额外输出机器可读摘要到 stdout 末尾
  --evidence-dir DIR  证据根目录，默认 modules/m5-views-console/evidence/deploy
```

等价入口：`make verify`（`--repeat 1`）、`make verify3`（`--repeat 3`）。

---

## 3. 执行步骤（单轮）

| # | 步骤 | 命令/动作 | 失败判定 | 预计耗时 |
| --- | --- | --- | --- | --- |
| 1 | 前置检查 | §1 全部检查 | 退出码 2 | <5s |
| 2 | 启动数据库 | `docker compose up -d mysql` + 轮询 `mysqladmin ping`（≤60s） | 超时退出 1 | ≤60s |
| 3 | 迁移 | `uv run alembic upgrade head`（空库/存量库均适用） | 非 0 退出 1 | ≤30s |
| 4 | 固定种子数据 | `uv run python -m m1_transaction_integration.cli.reset_demo --yes` → `uv run python -m m2_decoy_capture.cli.gen_demo_data --sessions 200 --events 2400` → `uv run python -m m2_decoy_capture.cli.import_samples --group demo_basic` | 任一非 0 退出 1；记录行数摘要 | ≤60s |
| 5 | 构建前端 | `corepack pnpm --dir modules/m5-views-console/frontend build` | 非 0 退出 1 | ≤60s |
| 6 | 启动后端 | `uv run uvicorn m1_transaction_integration.api.app:create_app --factory --host 127.0.0.1 --port $PORT`（PID + 日志文件；`trap` 清理） | 10s 内无监听退出 1 | ≤10s |
| 7 | 健康检查 | 轮询 `GET /api/health` 直到 200（≤30s） | 超时退出 1 | ≤30s |
| 8 | 浏览器检查 | `corepack pnpm --dir modules/m5-views-console/frontend exec node verify/run-check.mjs --base-url ... --out ...` | 报告 `result != pass` 退出 1 | ≤180s |
| 9 | 令牌审计 | 同上 `verify/token-audit.mjs` | 违规 >0 退出 1 | ≤10s |
| 10 | 页面-数据库抽样（可选自动） | `uv run python -m m5_views_console.cli.verify_views --check-pages`（读取接口与视图对比） | 差异 >0 退出 1 | ≤20s |
| 11 | 降级验证 | 停止 MySQL（`docker compose stop mysql`）→ 重新加载四页 → 断言无白屏且显示降级条 → 恢复 MySQL | 未显示降级或出现白屏退出 1 | ≤60s |
| 12 | 写证据 | `deploy-record.json` + 截图 + 日志 + 摘要；`--repeat` 时每轮独立 `run-N/` | 写失败退出 1 | <5s |
| 13 | 清理 | 停止后端、恢复容器（`--keep` 时跳过） | — | ≤10s |

总预算：≤10 分钟（SC-027）；超时打印各步骤耗时便于定位。

---

## 4. 浏览器检查项（`run-check.mjs`）

对 4 条路由 × 2 视口（1440×900、1920×1080）执行：

| 检查 | 断言 | 记录 |
| --- | --- | --- |
| 控制台错误 | `console` 的 `error` 数 = 0 | 全部消息文本（截断） |
| 页面异常 | `pageerror` 数 = 0 | 文本 |
| 失败请求 | `requestfailed` 数 = 0 | URL + 失败原因 |
| HTTP 错误 | 响应状态 ≥400 数 = 0（除有意探测的降级步骤） | URL + 状态 |
| 资源 404 | `/favicon.ico`、字体、脚本、样式 404 = 0 | URL |
| 外网请求 | 请求域不等于 `base_url` 主机 = 0（SC-026） | 外网 URL |
| 横向溢出 | `document.documentElement.scrollWidth <= innerWidth` | 实际值 |
| 元素重叠 | 抽检区域根节点不重叠（区域 rect 两两相交面积 0） | 相交对 |
| 字体就绪 | `document.fonts.check("14px Inter")` 等 3 项为 true | 各字体状态 |
| 标题/favicon | 每页 `<title>` 与 `<link rel=icon>` 符合 ui-contracts §2 | 实际值 |
| 导航 | 4 项可点击（03 无记忆时禁用），`aria-current` 正确 | 结果 |
| 已读交互 | 用测试账号（只读接口 + 已读写）执行 1 次 PATCH → 状态与统计变化 | 结果（写操作使用演示数据，可重置） |
| 截图 | 每页每视口 1 张 PNG（`fullPage: true`） | 文件路径 |

截图保存到 `run-N/screenshots/{page}-{viewport}.png`；检查结果写入 `run-N/browser.json`。

`--repeat N` 的跨轮一致性：对每轮记录的 20 个区域根节点 `getBoundingClientRect()`
（四舍五入到整数像素）与页面 `outerHTML` 文本骨架（数字/十六进制/ISO 时间替换为 `#`）
做比较；两轮完全一致 → `stable: true`，否则输出差异并对该轮判失败（SC-024 允许的
时间戳/随机 ID 已在骨架归一化中排除）。

---

## 5. 令牌审计（`token-audit.mjs`）

1. 读取 `frontend/tailwind.config.cjs`，导出颜色/字号/间距/圆角/字体允许值；
2. 扫描 `src/**/*.{vue,ts,css}`：
   - `class`/`class:` 中的 `bg-*`、`text-*`、`border-*`、`ring-*`、`fill-*`、`stroke-*`、
     `font-*`、`text-{size}`、`p-*`/`m-*`/`gap-*`/`rounded-*`/`space-*` 必须命中允许值
     （允许的语义类：`bg-[var(--…)]` 白名单为空，禁止任意值语法）；
   - CSS 文件与内联 `style` 中不得出现裸颜色字面量（`#hex`、`rgb()`、`hsl()`）；
     例外：`tailwind.config.cjs` 与内联 SVG 的渐变/滤镜定义（色值仍须取自配置）；
3. 输出 `{"violations": [{file,line,match,reason}], "checked_files": N, "result": "pass"}`；
4. 违规 >0 → 退出 1；统计每类令牌使用次数供核对表引用。

---

## 6. 页面-数据库核对（自动部分）

`verify_views --check-pages` 执行：

| 页面 | 抽样组（≥3） | SQL 口径 |
| --- | --- | --- |
| 概览 | 会话总数、查询总数、未读告警数、高风险攻击者 | `v_session_risk_summary` / `v_attacker_profile_summary` / `alerts` 聚合 |
| 攻击者列表 | 攻击者总数、高风险数、首行风险分 | `v_attacker_profile_summary` |
| 详情 | 某 IP 画像分、会话数、命中数 | 视图 + `rule_hits` |
| 告警列表 | 总数、未读数、等级分布 | `alerts` 聚合 |

输出 `{"checks": [{page, metric, api_value, sql_value, match}], "mismatches": 0}`；
写入 `run-N/sql-ui.json`；人工核对记录补充到 `evidence/sql-ui/`（含 SQL 文本与结果）。

---

## 7. 产物结构

```text
modules/m5-views-console/evidence/deploy/
├── run-1/
│   ├── deploy-record.json
│   ├── browser.json
│   ├── sql-ui.json
│   ├── token-audit.json
│   ├── backend.log
│   └── screenshots/{overview,attackers,attacker-detail,alerts}-{1440x900,1920x1080}.png
├── run-2/ …
├── run-3/ …
└── summary.md          # 三次运行结论、耗时、失败步骤（若有）
```

`deploy-record.json` 字段见 [data-model.md](../data-model.md) §6.3；`browser.json`
结构：

```json
{
  "base_url": "http://127.0.0.1:8000",
  "viewports": [{"width": 1440, "height": 900}, {"width": 1920, "height": 1080}],
  "pages": [{"route": "#/alerts", "page": "alerts", "viewport": "1440x900",
             "console_errors": [], "page_errors": [], "failed_requests": [],
             "http_errors": [], "external_requests": [], "overflow": false,
             "overlaps": [], "fonts_ready": true, "title": "告警列表 · DB Honeypot",
             "favicon": "/favicon-alerts.svg", "screenshot": "run-1/screenshots/alerts-1440x900.png"}],
  "stable": true,
  "result": "pass"
}
```

---

## 8. 退出码与失败处理

| 退出码 | 含义 | 处理 |
| --- | --- | --- |
| 0 | 全部检查通过 | 报告路径与耗时 |
| 1 | 检查/步骤失败 | 保留失败轮证据；打印失败步骤、日志尾部与修复建议 |
| 2 | 前置条件缺失 | 打印缺失项与准备命令；不修改仓库 |

无论成功失败：停止后端进程（`--keep` 除外）、恢复 MySQL 容器、清理临时 PID/日志
（证据文件保留）。

---

## 9. 证据与文档联动

- `verify_deploy.sh` 通过后，将关键截图复制/链接到 `docs/screenshots/`（演示图，
  命名 `{page}.png`）并在 `docs/demo-script.md` 引用；
- 三次运行的 `summary.md` 摘要写入 `modules/m5-views-console/evidence/README.md`
  的"最近验证"字段（ISO8601 时间、耗时、结果）；
- 区域核对表（人工）与自动报告互相引用：核对表"证据"列指向 `run-N/browser.json`
  或截图路径；自动报告不替代人工区域判定（SC-018）。
