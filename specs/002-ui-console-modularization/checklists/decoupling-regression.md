# 解耦回归核对（T051 / US3）

- **日期**：2026-11-25｜**环境**：容器 MySQL 8.0.46 `honeypot_dev` + 宿主 uvicorn `http://127.0.0.1:8000`
- **对照基线**：[`tests/fixtures/api_baseline.json`](../../../tests/fixtures/api_baseline.json)（T009）
- **回归工具**：[`tools/compare_api_baseline.py`](../../../tools/compare_api_baseline.py)
- **本轮 JSON**：[`tests/fixtures/api_regression.json`](../../../tests/fixtures/api_regression.json)

## 1. 契约回归结论

规则：002 为 **additive** 契约——允许新增字段/新增端点；既有字段名缺失或类型变化判失败；状态类示例值（`is_read`、计数）允许随演示数据变化，只比形状。

```bash
/tmp/dbh-venv/bin/python tools/compare_api_baseline.py --json tests/fixtures/api_regression.json
```

| 端点 | 结果 | 缺失字段 | 新增字段 | 类型变化 |
| --- | --- | --- | --- | --- |
| `/api/health` | PASS | 0 | 0 | 0 |
| `/api/overview?range=all` | PASS | 0 | 0 | 0 |
| `/api/trend?days=7` | PASS | 0 | 0 | 0 |
| `/api/attackers?page=1&page_size=5` | PASS | 0 | 0 | 0 |
| `/api/attackers/summary` | PASS | 0 | 0 | 0 |
| `/api/attackers/198.51.100.17` | PASS | 0 | 0 | 0 |
| `/api/alerts?page=1&page_size=5` | PASS | 0 | 0 | 0 |
| `/api/alerts/summary` | PASS | 0 | 0 | 0 |
| `/api/rules` | PASS | 0 | 0 | 0 |
| `/api/sessions/{id}/timeline` | PASS | 0 | 0 | 0 |

汇总：10/10 端点 PASS，`ok=true`，退出码 0。

**口径说明（诚实记录）**：002 的接口增量（`range`、趋势 `hit_*`、`/alerts/summary`、`/attackers/summary`、`network_scope`、详情指标）是在**迁移完成后**实现的，仓库内不存在搬迁前的独立基线快照。因此本基线的语义是「002 完成时的 001 契约字段快照 + 后续回归门禁」：它保证已交付的 001 字段不再被后续改动破坏，但无法证明 001→002 期间没有字段被改名（该部分由 001 原有的 API 测试 + 本文第 2 节的 262 条测试兜底）。

## 2. 全量测试回归（001 + 002）

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m pytest -q
```

```text
262 passed in 127.60s (0:02:07)
```

## 3. 静态与结构门禁

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 边界矩阵 | `make boundary`（`python -m shared.deploy.boundary_check`） | PASS（133 py 文件，0 违规；详见 `migration-regression.md`） |
| 五模块结构 | `python -m shared.deploy.check_structure` | PASS 39 / FAIL 0 / WARN 0（2026-11-25 M5 交付后复跑） |
| Ruff | `ruff check .` | 待最终门禁复跑（`shared/deploy/**` 由 infra 收口） |

## 4. 四页手工验收（对照 001 行为）

| 页面 | 001 行为 | 002 结果 | 证据 |
| --- | --- | --- | --- |
| 首页概览 | KPI/趋势/环图/TOP5 全量加载，无 4xx/5xx | 保持一致；范围切换新增 `range` 参数 | `evidence/visual/baseline/overview-*.png`、`evidence/deploy/run-*/browser.json` |
| 攻击者列表 | 分页/搜索/排序可用 | 保持一致；新增 `sort=total_connections`、网络归属列 | 同上 |
| 攻击者详情 | 画像/证据链/会话/时间线 | 保持一致；新增平均时长、高危操作、认证成功数 | 同上 |
| 告警列表 | 筛选/分页/已读 | 保持一致；新增统计摘要、未读页签、批量已读 | 同上 |

（四页浏览器断言以最终 `make verify` 的 `browser.json` 为准，见第 5 节。）

## 5. 结论

- 接口契约：10/10 PASS（additive 兼容）。
- 测试：262 passed，无回归。
- 结构/边界：PASS，五模块导入未回退旧前缀。
- UI：四页与 001 既有功能一致，新增能力均有真实接口支撑。
