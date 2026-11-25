# 交互验收记录（interactions.md，T061）

- **日期**：2026-11-25 15:12（UTC+8）｜**环境**：`http://127.0.0.1:8000`，最新主题构建（14:53），
  固定种子（`make seed` 后 214 会话 / 2525 事件 / 8 告警）
- **脚本**：`frontend/verify/interaction-check.mjs`｜**证据**：[`deploy/theme-run/interaction.json`](../deploy/theme-run/interaction.json)
- **结论**：**18/18 通过**（`result: pass`，`failures: []`）。覆盖范围切换、刷新、TOP5 下钻、
  时间线筛选、禁用控件文案、攻击者搜索/风险档/排序、告警页签/等级/类型/时间、
  单条与批量已读（真实 PATCH 并还原）、无障碍基础断言；无页面异常。

| # | 检查项 | 结果 | 实测摘要 |
| --- | --- | --- | --- |
| 1 | 概览 7 天范围 | PASS | URL `?range=7d`；请求 `/api/overview?range=7d`；KPI 由 214 → 5 |
| 2 | 概览全部历史 | PASS | URL 回到 `?range=all`，KPI/趋势同步刷新 |
| 3 | 现场刷新 | PASS | 触发 overview/trend/rules/attackers 四个请求，状态条更新时间 |
| 4 | TOP5 下钻 | PASS | 跳转 `#/attackers/198.51.100.17`，详情页渲染 |
| 5 | 时间线筛选 | PASS | 全部 16 条 → 仅认证 8 条，计数与页签一致 |
| 6 | 禁用控件文案 | PASS | DMZ 隔离 / 导出报告 / 同步证据链均 `disabled` 且有"演示未开放：…"`title` |
| 7 | 攻击者搜索 | PASS | `?q=198.51.100.17` → 1 行结果 |
| 8 | 风险档筛选 | PASS | `?q=…&risk_level=critical`，URL 双向同步 |
| 9 | 排序（会话数） | PASS | `?sort=total_connections`，首行随排序变化 |
| 10 | 导出 CSV 禁用 | PASS | 按钮禁用 + 原因 `title` |
| 11 | 告警未读页签 | PASS | `?is_read=false`，列表仅未读 |
| 12 | 告警等级筛选 | PASS | `?severity=high`，卡片等级一致 |
| 13 | 告警类型筛选 | PASS | `?alert_type=bruteforce` |
| 14 | 告警时间预设 | PASS | `?days=3`，统计卡随窗口变化 |
| 15 | 单条已读 | PASS | `PATCH /api/alerts/109` → 200，Toast「告警 #109 已标记已读」，统计/未读徽标刷新后还原现场 |
| 16 | 批量已读 | PASS | 2 条 PATCH，未读数 8 → 6，随后还原 |
| 17 | 无障碍基础 | PASS | 每页唯一 `h1`、`nav aria-current` 1 个、3 个图标按钮均有 `aria-label` |
| 18 | 页面异常 | PASS | `pageerror` 0 |

## 写操作与现场还原

- 单条/批量已读是**真实写操作**（`PATCH /api/alerts/{id}`），脚本在断言后把被标记的告警
  恢复为未读（`restored_alerts: 1`），避免污染演示数据；失败项会保留未读并由脚本报告。
- 其余交互只读或只改 URL 状态，不改数据库。
- 运行前应保证种子数据完整；已读状态累积会让"未读"断言失效，重跑前执行 `make seed` 即可。

## 复现命令

```bash
cd modules/m5-views-console/frontend
export PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers COREPACK_HOME=/tmp/corepack
corepack pnpm exec node verify/interaction-check.mjs \
  --base-url http://127.0.0.1:8000 --out ../evidence/deploy/theme-run
cat ../evidence/deploy/theme-run/interaction.json | head -20
```

## 已知边界

1. 交互脚本以默认深色主题运行；浅色主题下的交互一致性由 `run-check.mjs` 的浅色四页回归覆盖
   （console 0、区域齐全、无溢出），主题切换本身见 [`theme-evidence.md`](theme-evidence.md)。
2. 批量已读只抽 2 条验证并发 PATCH 与统计刷新，未做 100+ 条的压测。
3. 时间线筛选只校验"仅认证"一类（其余页签同组件同一逻辑），计数由 `filterCounts` 实时计算。
4. 搜索/筛选/排序只验证 URL 与首行结果，未穷举所有组合；组合逻辑由 `tests/integration/test_api_*.py`
   与 `verify_views` 的 21 条页面-数据库核对兜底。
