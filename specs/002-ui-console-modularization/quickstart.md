# 快速验证指南：控制台视觉重构与模块解耦

**Feature**: `002-ui-console-modularization` | **Date**: 2026-11-25 | **Spec**: [spec.md](./spec.md)

本指南给出可执行的端到端验证场景（V00–V14），用于实现完成后逐条证明 FR-090–FR-132
与 SC-016–SC-028 达标。命令默认在仓库根执行；所有证据路径均相对仓库根。

> 实现细节（代码、迁移、测试体）不在本文件；接口字段见
> [contracts/api-extensions.md](./contracts/api-extensions.md)，模块边界见
> [contracts/module-boundaries.md](./contracts/module-boundaries.md)，UI 规则见
> [contracts/ui-contracts.md](./contracts/ui-contracts.md)，部署脚本见
> [contracts/deployment-verify.md](./contracts/deployment-verify.md)。

---

## 0. 一次性准备

```bash
cp .env.example .env                 # 已存在则跳过；确认 DATABASE_URL 等为 TEST-ONLY 占位
make db-up                           # 启动 MySQL 8 容器并等待健康
uv sync                              # 安装 shared + 五个模块 + dev 依赖（可编辑安装）
corepack pnpm --dir modules/m5-views-console/frontend install
corepack pnpm --dir modules/m5-views-console/frontend exec playwright install chromium
```

网络仅在上述安装与浏览器下载时需要；验收运行本身是离线的（V10）。

常用命令：

| 命令 | 作用 |
| --- | --- |
| `make migrate` | `alembic upgrade head` |
| `make seed` | 固定种子数据（reset + 合成规模 + `demo_basic`） |
| `make demo` | 启动诱饵 + 后端（开发） |
| `make api` | 仅启动后端（托管 `dist`） |
| `make frontend-build` | 构建 M5 控制台 |
| `make test` | 全量 pytest（真实 MySQL） |
| `make lint` | ruff |
| `make boundary` | 依赖边界检查 |
| `make structure` | 模块目录结构检查 |
| `make verify` | 部署验收一轮 |
| `make verify3` | 部署验收三轮（SC-024） |

---

## V00 环境自检

```bash
uv run python -c "import shared, m1_transaction_integration, m2_decoy_capture, m4_rules_derived, m5_views_console; print('imports ok')"
make structure
make boundary
```

**期望**：三条命令退出码 0；`make structure` 输出 5 个模块 + `shared` 的检查结果；
`make boundary` 输出 `violations: []`、`result: pass`、扫描文件数 ≥ 80。

**证据**：`modules/m5-views-console/evidence/deploy/run-*/` 之外，保存到
`modules/m5-views-console/evidence/visual/precheck.txt`（或 CI 日志）。

---

## V01 迁移与数据库可重建

```bash
make db-reset           # 删除并重建 honeypot_dev（或按 README 的等价命令）
make migrate
uv run alembic downgrade base && uv run alembic upgrade head
uv run pytest modules/m1-transaction-integration/tests/integration/test_migrations.py -q
```

**期望**：`upgrade`/`downgrade` 往返成功；11 张表、4 个视图、R01–R05 五条规则存在；
测试通过。**对应**：001 门禁 2、FR-121、SC-023。

---

## V02 固定种子数据

```bash
uv run python -m m1_transaction_integration.cli.reset_demo --yes
uv run python -m m2_decoy_capture.cli.gen_demo_data --sessions 200 --events 2400
uv run python -m m2_decoy_capture.cli.import_samples --group demo_basic
```

**期望**：输出行数摘要——会话 ≥ 207、事件 ≥ 3000、攻击者 ≥ 10、告警 ≥ 3
（覆盖 `bruteforce`/`data_dump`/`destructive` 三类）、规则命中覆盖 R01–R05。
重复执行同序列两次，行数摘要一致（幂等/确定性）。**对应**：R-12、SC-024。

---

## V03 部署验收（一条命令）

```bash
make verify
```

**期望**：退出码 0；控制台输出 13 个步骤全部 `ok`；生成
`evidence/deploy/run-1/deploy-record.json`，其中：

- `pages[*].console_errors == 0`、`failed_requests == 0`、`http_errors == 0`、
  `external_requests == 0`、`horizontal_overflow == false`、`fonts_ready == true`；
- `token_audit.violations == 0`；
- `result == "pass"`；8 张截图存在（4 页 × 2 视口）。

**对应**：SC-016、SC-017、SC-026、FR-107/108/109。

---

## V04 视觉一致性（自动 + 人工）

```bash
corepack pnpm --dir modules/m5-views-console/frontend run verify:token
open modules/m5-views-console/evidence/visual/baseline/   # 8 张基线截图
```

人工按 [contracts/ui-contracts.md](./contracts/ui-contracts.md) §10 与 spec 附录 C：

1. 逐页逐区域标记"一致 / 差异（理由）/ 不接受"；
2. 每页记录 20 处视觉取值（元素、属性、期望令牌、实际计算值）；
3. 填写 `modules/m5-views-console/evidence/visual/region-checklist.md`；
4. 差异项必须引用附录 B（含补充 21–28），否则待修。

**期望**：一致率 ≥95%；令牌抽样 100% 命中；差异 0 项未登记。**对应**：SC-018、
FR-110/111、FR-092。

---

## V05 跨页严重度一致性

```bash
# 令牌审计：确认四色映射未被源码中的任意值绕过
corepack pnpm --dir modules/m5-views-console/frontend run verify:token
# 浏览器打开四页，对 critical/high/medium/low 各抽样 1 个元素并截图
```

**期望**：四页中同一等级使用同一颜色/文案/徽标形态：严重 `#EF4444`、高 `#F97316`、
中 `#F59E0B`、低 `#10B981`；16 个组合（4 等级 × 4 页面）全部一致；`token-audit.json`
中四色定义只出现于配置；抽样记录写入核对表"跨页一致性"小节。
**对应**：SC-019、FR-093。

---

## V06 页面数字与 SQL 核对

```bash
uv run python -m m5_views_console.cli.verify_views --check-pages
```

**期望**：输出每页 ≥3 组 `{页面, 指标, 接口值, SQL 值, 一致}`，`mismatches == 0`；
另在 `evidence/sql-ui/` 手工记录至少 3 组查询原文与结果截图（可直接重跑）。
**对应**：SC-020、FR-112、FR-128。

---

## V07 真实交互（禁止假反馈）

在 `make verify` 启动后的页面（或 `make dev`）手工验证并记录：

| 操作 | 期望 |
| --- | --- |
| 概览切换 24H/7天/全部 | KPI 数字与趋势图变化，网络面板出现对应 `range` 请求 |
| 攻击者列表搜索/风险档/意图/排序/翻页 | 结果与 URL hash 同步；刷新后保持 |
| 告警状态页签/等级/类型/时间筛选 | 计数与列表变化；无结果时显示空态 |
| 单条标记已读 | 状态点、按钮、统计卡、未读徽标更新；`audit_log` 新增一行 |
| 批量标记已读（含 1 条被并发置为已读） | 成功/部分失败 Toast，失败项保持未读并高亮 |
| 现场刷新 | 数据与"最近更新"时间变化 |
| 告警"查看会话证据" | 跳转详情并高亮会话、时间线过滤 |
| 侧栏 03（无历史） | 禁用态并有说明，不产生死链 |

**证据**：录屏或截图 + `browser.json` 中的交互断言。**对应**：FR-101/102/103、SC-025。

---

## V08 四态（空/加载/失败/降级）

```bash
# 降级：停止数据库后加载四页
docker compose stop mysql
# 浏览器访问四页（后端保持运行）
docker compose start mysql
```

**期望**：四页均显示降级条与重试按钮，无白屏、无 0 值冒充；恢复数据库后重试成功。
空态：清空 `alerts` 与 `attack_log` 后（或测试库）显示空态与可执行重置按钮；加载态
出现在真实请求期间。**对应**：FR-100、FR-113。

---

## V09 断网验证

断开网络（或使用 `--offline`）后：

```bash
make verify-offline   # 等价：bash shared/deploy/verify_deploy.sh --offline --skip-build
```

**期望**：四页正常渲染；`browser.json` 中 `external_requests` 全为 0；字体/图标
加载成功；无布局塌陷。**对应**：FR-106、SC-026。

---

## V10 五模块证据独立复现（SC-021）

按各模块 README 的命令逐条执行，验收人只需仓库 + `.env`：

| 模块 | 命令（示例） | 期望证据 |
| --- | --- | --- |
| M1 | `uv run python -m m1_transaction_integration.cli.verify_transaction` | 提交前后快照、注入失败回滚、账号 GRANT 矩阵、会话查询接口 curl 输出 |
| M2 | `uv run python -m m2_decoy_capture.cli.explain_diff` + 会话事件日志查询 | 同一会话完整事件日志、时间线查询 EXPLAIN 对比（JSON） |
| M3 | `uv run pytest modules/m3-er-constraints/tests/integration -q` + 打开 `constraints/verify_constraints.sql` | ER 图源文件、主外键/CHECK/UNIQUE 正反样例输出 |
| M4 | `uv run pytest modules/m4-rules-derived/tests -q` + 规则版本/去重样例 SQL | 规则版本与命中记录、意图评分、告警去重样例 |
| M5 | `make verify` + `verify_views` 输出 | 视图用途对照、主要意图查询、SQL 与界面结果核对 |

**期望**：5/5 模块命令可独立运行；每份 `evidence/README.md` 含 ≥1 条可运行命令、
期望输出与最近验证时间。**对应**：FR-114–129、SC-021、SC-028。

---

## V11 边界检查的反向验证

```bash
uv run pytest tests/test_boundary_check.py -q
```

**期望**：测试构造的 8 类违规样例（跨模块内部导入、反向依赖、旧前缀、循环等）
全部被判定为失败；当前仓库检查通过。**对应**：FR-122、SC-022。

---

## V12 001 无回归

```bash
make test        # pytest 全量（真实 MySQL，不用 Mock）
make lint
uv run pytest modules/m1-transaction-integration/tests modules/m4-rules-derived/tests -q
```

**期望**：001 既有测试全部通过（含新增接口兼容性用例）；ruff 无告警；四页主要流程与
解耦前行为一致（对照 `docs/screenshots/` 旧图与 V03 验证）。**对应**：FR-123、SC-023。

---

## V13 三次连续部署验收

```bash
make verify3
```

**期望**：`run-1/`、`run-2/`、`run-3/` 均 `result == "pass"`；`summary.md` 记录
`stable: true`（区域几何与文本骨架一致，时间戳/随机 ID 已归一化）。**对应**：SC-024。

---

## V14 文档与裁定闭环

检查清单：

- [ ] spec 附录 B 已补 8 条（21–28）且每条在核对表中有对应位置；
- [ ] 每页 title/favicon/导航/禁用控件符合 ui-contracts；
- [ ] `docs/architecture.md` 更新为五模块结构图与目录映射；
- [ ] `docs/demo-script.md` 更新截图路径与新交互；
- [ ] `docs/test-plan.md` 的用例数量与实际测试一致（修正 225 → 实际值）；
- [ ] `README.md` 启动命令、`Makefile`（无绝对路径）、`compose.yaml` 说明与实际一致；
- [ ] `docs/database-design.md` 的 ER 改为引用 M3 源文件；
- [ ] 五个 `evidence/README.md` 的"最近验证时间"为本次验收时间。

**期望**：全部勾选；`docs/`、`specs/`、模块 README 无遗留"backend/frontend"旧路径
引用（`rg "backend/|frontend/" docs README.md` 仅剩历史说明）。**对应**：FR-121、
SC-025、宪法门禁 4。

---

## 故障排查

| 现象 | 排查 |
| --- | --- |
| `uv sync` 失败 | 检查 Python ≥3.11；`uv` 版本；删除 `.venv` 后重试 |
| MySQL 不通 | `docker compose ps`；`.env` 端口/口令；`docker compose logs mysql` |
| 页面 404 或白屏 | 确认已 `make frontend-build` 且 `WEB_DIST_DIR` 指向 `modules/m5-views-console/frontend/dist` |
| Playwright 启动失败 | `pnpm exec playwright install chromium`；或设置 `PLAYWRIGHT_CHANNEL=chrome` |
| 截图字体不对 | 等待 `document.fonts.ready`；确认 @fontsource 包已安装并被引入 |
| 令牌审计误报 | 检查是否使用了任意值语法（`text-[13px]`）或裸颜色；改用令牌类 |
| 边界检查报错 | 按 `module-boundaries.md` §3 改为公开入口；不要直接改允许表绕过 |
| 三次运行不稳定 | 检查种子命令是否按顺序执行；确认数据未在轮间被手工修改 |

---

## 成功标准映射

| 场景 | 覆盖 SC/FR |
| --- | --- |
| V00/V01/V02 | SC-023、FR-121 |
| V03 | SC-016、SC-017、SC-026、FR-107–109 |
| V04/V05 | SC-018、SC-019、FR-092/093/110/111 |
| V06 | SC-020、FR-112、FR-128 |
| V07/V08 | FR-100–103、FR-113、SC-025 |
| V09 | SC-026、FR-106 |
| V10/V11 | SC-021、SC-022、SC-028、FR-114–129 |
| V12 | SC-023、FR-123 |
| V13 | SC-024 |
| V14 | SC-025、FR-121、宪法门禁 |
