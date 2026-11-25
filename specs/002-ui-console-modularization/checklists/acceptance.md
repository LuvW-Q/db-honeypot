# 验收场景记录（acceptance.md，T078）

- **Feature**：`002-ui-console-modularization`｜**日期**：2026-11-25
- **环境**：macOS，Docker MySQL 8.0.46，宿主 uvicorn（`http://127.0.0.1:8000`），
  最新主题构建 `dist`（14:53），固定种子（214 会话 / 2525 事件 / 8 告警 / R01–R05）。
- **口径**：逐条执行 [quickstart.md](../quickstart.md) V00–V14，记录命令、结果与证据路径。
- **总结**：**14/14 场景均有可复现证据**；其中 V13（三轮连续 `verify3`）的单轮已通过，
  三轮汇总以 `modules/m5-views-console/evidence/deploy/summary.md` 的 `run-1..3` 为准
  （若该文件尚未生成三轮记录，V13 标记为"单轮通过、三轮待归档"，不伪造）。

## 场景总表

| 场景 | 结果 | 关键证据 |
| --- | --- | --- |
| V00 环境自检 | PASS | `make structure` 39/0/0；导入五包成功；边界检查（V11）通过 |
| V01 迁移与重建 | PASS | `checklists/migration-regression.md`（alembic head `0004_seed_rules`、292 tests） |
| V02 固定种子 | PASS | `make seed` 输出 214 会话 / 2525 事件 / 8 告警；重复执行行数一致 |
| V03 部署验收 | PASS（单轮 13/13） | `evidence/deploy/run-1/`（2026-11-25 15:27–15:37 实测，主题版 dist） |
| V04 视觉一致性 | PASS | `visual/summary.md`（verify2 run-1 pass，区域 82/82）+ `token-sampling.md` 100/100 |
| V05 严重度一致性 | PASS | `token-audit.json` 四色仅配置定义；四页截图一致 |
| V06 页面数字与 SQL | PASS | `verify-views.json` 16 条视图 + 21 条页面核对全 ok；`sql-ui/checklist.md` |
| V07 真实交互 | PASS | `interaction.json` 18/18（含单条/批量已读真实 PATCH 并还原） |
| V08 四态 | PASS | 降级 503→恢复 200（`deploy/summary.md` 步骤 11）；空/加载态由组件与测试覆盖 |
| V09 断网 | PASS | `browser.json` `external_requests=[]`；字体本地加载 |
| V10 五模块独立证据 | PASS | 五份 `modules/*/evidence/README.md` 索引与命令 |
| V11 边界反向验证 | PASS | `shared/deploy/tests/test_check_boundaries.py` 30 passed；`make boundary` pass（144 文件） |
| V12 001 无回归 | PASS | 默认套件 **270 passed**（8:27）+ `shared/deploy/tests` 30 passed；`ruff` 通过 |
| V13 三次连续验收 | 第 1 轮 PASS；第 2 轮被端口占用阻断（环境） | `run-1` 13/13；`verify3` 第 2 轮 `[0/13] 端口 8001 不可用` |
| V14 文档与裁定闭环 | PASS | `adjudication-checklist.md` 28/28；`screenshots/README.md` 已刷新 |

---

## V00 环境自检

```bash
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console
/tmp/dbh-venv/bin/python -c "import shared, m1_transaction_integration, m2_decoy_capture, m4_rules_derived, m5_views_console; print('imports ok')"
make structure PY=/tmp/dbh-venv/bin/python
```

- 结果：导入成功；`make structure` **PASS（39 项，FAIL 0，WARN 0）**，覆盖五模块目录/
  README/证据目录、旧目录残留、旧导入前缀、`element-plus/echarts` 移除、绝对路径等。
- 证据：本文件下方"最近门禁"；`evidence/deploy/summary.md` 步骤 1–2。

## V01 迁移与数据库可重建

- 结果：`alembic upgrade head` → `0004_seed_rules`；`downgrade base → upgrade head` 往返成功；
  11 表 + 4 视图 + R01–R05 存在；迁移测试通过。
- 证据：[`checklists/migration-regression.md`](../checklists/migration-regression.md)、
  `modules/m1-transaction-integration/evidence/`。

## V02 固定种子数据

```bash
make seed PY=/tmp/dbh-venv/bin/python
```

- 实测输出：`reset_demo` → `{alerts:8, rule_hits:10, attack_log:121, sessions:13}`；
  `gen_demo_data 200/2400`；`import_samples demo_basic` → 新增 14 会话 / 125 事件 /
  11 规则命中 / 8 告警；最终 **214 会话 / 2525 事件 / 8 告警**，覆盖 R01–R05 与三类告警。
- 幂等：同序列重跑行数摘要一致（`import_samples` 显示 `deduped` 计数）。
- 证据：本轮终端输出；`make verify` 的 `seed-digest.txt`。

## V03 部署验收（一条命令）

```bash
make verify VENV=/tmp/dbh-venv VERIFY_ARGS="--skip-build --port 8001"
```

- 结果（2026-11-25 15:37 实测）：13 步全部 `ok`，`result=pass`；step5 复用主题版 `dist`
  （`--skip-build`，`/tmp/dbh-build2.log` BUILD OK）；四页 × 两视口 console 错误/失败请求/
  404/外网请求/横向溢出均 0，字体就绪；令牌审计 0 违规/28 文件；视图 16/16 + 页面核对
  21/21；降级 `health 503 → SPA 可开 → 恢复 200`；固定种子 digest `53a2be97…` 两轮一致。
- 证据：`modules/m5-views-console/evidence/deploy/run-*/`（`deploy-record.json`、
  `browser.json`、`token-audit.json`、`sql-ui.json`、8 张截图）、`deploy/summary.md`。

## V04 视觉一致性

- `make verify2`（2026-11-25 15:27–15:41，主题版 dist，`--skip-build --port 8001`）：
  13 步全 PASS（step 10/11 按 verify2 模式跳过），区域覆盖率 **100%（82/82）**，
  浏览器 8 条页面×视口异常 0，截图 12 张（深色 8 + 浅色 1440 四张）。→
  [`visual/summary.md`](../../../modules/m5-views-console/evidence/visual/summary.md)
- 说明：区域断言在首次运行曾因异步渲染时序早于数据刷新失败一次（attempt1 证据保留
  `browser-attempt1.*`），脚本自动完整重跑一次后 PASS；连续两次失败仍会 FAIL，不掩盖问题。


- 区域：`region-audit.mjs` 实测四页 × 两视口 **82/82（100.0%）**，缺失/额外/页面区域重叠/
  横向溢出均 0；主题按钮每页存在。→ [`region-checklist.md`](../../../modules/m5-views-console/evidence/visual/region-checklist.md)
- 令牌：`token-sampling.mjs` 深/浅两主题共 **100/100（100.0%）** 计算值命中令牌。→
  [`token-sampling.md`](../../../modules/m5-views-console/evidence/visual/token-sampling.md)
- 差异：28 条裁定全部闭环。→ [`adjudication-checklist.md`](../../../modules/m5-views-console/evidence/visual/adjudication-checklist.md)

## V05 跨页严重度一致性

- `token-audit.mjs` 0 违规：`sev-critical #EF4444`、`sev-high #F97316`、`sev-medium #F59E0B`、
  `sev-low #10B981` 只在 `main.css` 定义，组件全部走令牌类；四页截图（深/浅各 4 张）同级
  元素颜色/文案/徽标一致。

## V06 页面数字与 SQL 核对

```bash
/tmp/dbh-venv/bin/python -m m5_views_console.cli.verify_views --check-pages --json
```

- 结果：16 条视图断言 + 21 条 DB↔API 核对全 `ok=true`，`mismatches=0`。
- 证据：[`sql-ui/verify-views.json`](../../../modules/m5-views-console/evidence/sql-ui/verify-views.json)、
  [`sql-ui/checklist.md`](../../../modules/m5-views-console/evidence/sql-ui/checklist.md)。

## V07 真实交互

- 脚本：`interaction-check.mjs` → **18/18 PASS**（`result: pass`）。
- 覆盖：范围切换、刷新、TOP5 下钻、时间线筛选、禁用控件文案、搜索/风险档/排序/导出禁用、
  告警页签/等级/类型/时间、单条与批量已读（真实 PATCH + 还原）、无障碍基础、页面异常。
- 证据：[`interactions.md`](../../../modules/m5-views-console/evidence/interactions.md)、
  [`deploy/theme-run/interaction.json`](../../../modules/m5-views-console/evidence/deploy/theme-run/interaction.json)。

## V08 四态（空/加载/失败/降级）

- 降级：停止 MySQL 后四页显示全宽降级条与重试，非白屏；恢复后重试成功（`verify` 步骤 11
  实测 `degraded 503 → recovered 200`）。
- 空态：`EmptyState` 统一组件，清空数据源时显示空态与重置入口（集成测试覆盖）。
- 加载态：各页 `loading` 骨架/文案，请求期间按钮 loading。
- 证据：`deploy/summary.md` 步骤 11；`src/components/OfflineBanner.vue`、`EmptyState.vue`。

## V09 断网验证

```bash
bash shared/deploy/verify_deploy.sh --offline --skip-build --port 8002
```

- 结果：`browser.json` `external_requests` 全 0；`@fontsource` 字体、`material-symbols`、
  favicon 全部本地加载；无布局塌陷。
- 证据：`deploy/run-*/browser.json`；`verify_deploy.sh --offline` 步骤。

## V10 五模块证据独立复现

| 模块 | 命令（README） | 证据 |
| --- | --- | --- |
| M1 | `verify_transaction` / `pytest modules/m1.../tests` | `m1.../evidence/{transaction,grants,api,security-review}.md` |
| M2 | `explain_diff` / `import_samples` | `m2.../evidence/{session-events,explain-diff}.md` + JSON/输出 |
| M3 | `introspect_constraints.py` / pytest | `m3.../evidence/{constraints-check.md,constraints.json,schema.png}` |
| M4 | 规则/风险/告警 SQL 与 pytest | `m4.../evidence/README.md`（E-M4-001..004） |
| M5 | `verify_views` + `make verify` | `m5.../evidence/{sql-ui,deploy,visual}/` |

五份 README 均含职责、对外契约、复现命令、证据索引、最近验证时间。

## V11 边界检查反向验证

```bash
/tmp/dbh-venv/bin/python -m pytest shared/deploy/tests -q
make boundary PY=/tmp/dbh-venv/bin/python
```

- 结果：`shared/deploy/tests` **30 passed**（含 8 类违规样例：跨模块内部导入、反向依赖、
  旧前缀、循环等）；当前仓库 `violations: []`、`result: pass`，扫描 144 文件。
- 证据：本轮终端输出；`shared/deploy/boundary_check.py` 自测。

## V12 001 无回归

```bash
make test PY=/tmp/dbh-venv/bin/python     # 或 pytest -q
make lint PY=/tmp/dbh-venv/bin/python
```

- 结果：默认 `pytest -q` **270 passed**（真实 MySQL，507.34s，含结构/所有权门禁 8 个新测试）；
  `shared/deploy/tests` 30 passed；`ruff check .` 通过。iCloud 卷上真实仓库扫描较慢，耗时以每次终端输出为准。
- 证据：[`checklists/migration-regression.md`](../checklists/migration-regression.md)、
  [`checklists/decoupling-regression.md`](../checklists/decoupling-regression.md)。

## V13 三次连续部署验收

- **实测（2026-11-25 17:0x）**：`make verify3` 第 1 轮 **13/13 PASS**（run-1：令牌 0/28、
  视图 16/16、页面核对 21/21、降级 503→200），第 2 轮在 `[0/13] 前置条件` 失败：
  `端口 8001 不可用`（上一轮/并行检查残留占用），`make` 退出 2。
- **判定**：第 1 轮全绿；第 2 轮为**端口占用环境问题**，不是验收断言失败；因未跑满三轮，
  **V13 不标记全绿**，`stable: true` 暂不宣称（单轮 digest 已稳定）。
- 复跑建议：确认 `lsof -i :8001` 无残留后执行 `make verify3 ... --skip-build --port 8002`
  （三轮约 30 分钟）。

## V14 文档与裁定闭环

- [x] spec 附录 B 21–28 已补，核对表逐条落地（`adjudication-checklist.md`）
- [x] 每页 title/favicon/导航/禁用控件符合 `ui-contracts.md`（`run-check` + `interaction`）
- [x] `docs/architecture.md` 五模块图与目录映射
- [x] `docs/demo-script.md` 新截图/交互/证据路径（含主题切换讲解点）
- [x] `docs/test-plan.md` 用例数按实际 270/300 + 002 场景（A-01–A-16）
- [x] `README.md` / `Makefile` / `compose.yaml` 与实际目录一致（`make structure` 覆盖）
- [x] `docs/database-design.md` ER 引用 M3 源文件
- [x] 五份 `evidence/README.md` 最近验证时间 = 2026-11-25

---

## 最近门禁（2026-11-25 15:12 本地实测）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 结构 | `make structure` | PASS 39 / FAIL 0 / WARN 0 |
| 边界 | `make boundary` | PASS（见 V11） |
| 测试 | `pytest -q` | 270 passed（+ shared/deploy 30） |
| 静态 | `ruff check .` | 通过 |
| 部署 | `make verify` | 13/13 PASS（run-1） |
| 主题 | `run-check`（theme-run） | PASS，failures [] |
| 交互 | `interaction-check` | 18/18 PASS |
| 区域 | `region-audit` | 100.0%（82/82） |
| 令牌 | `token-sampling` | 100/100（100%） |

## 边界与未决项

1. **V13 三轮**：本轮只保留单轮 `verify` 结果；三轮稳定性以 `verify3` 产物为准，未生成前
   不宣称 `stable: true`。
2. 视觉核对按语义/区域/令牌判定，不做逐像素 diff；原型演示数据与真实种子不同属预期。
3. 交互脚本需在固定种子下运行（已读状态会累积），重跑前 `make seed`。
4. 性能为串行 warm 测量，非并发压测；详见 `evidence/deploy/performance.md`。
