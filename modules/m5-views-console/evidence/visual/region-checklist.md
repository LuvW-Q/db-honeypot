# 区域清单（region-checklist.md）

- 生成时间：2026-11-25T06:40:24.489Z（UTC+8 2026-11-25T14:40:24.492+08:00）
- 目标地址：http://127.0.0.1:8000｜口径：`contracts/ui-contracts.md` §3 + `data-model.md` §6.2
- 期望区域：壳层 5 个（SHELL-SIDEBAR/HEADER/MAIN/FOOTER/STATUS）+ 页面区域 21 个
- **覆盖率：100.0%（82/82）**；重叠 0 视为通过（本表 overlaps 列）

## 1. 汇总

| 页面 | 路由 | 视口 | 期望 | 命中 | 缺失 | 额外 | 页面区域重叠 | 横向溢出 | 主题按钮 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overview | / | 1440x900 | 10 | 10 | 0 | 0 | 0 | 否 | 存在 |
| attackers | /attackers | 1440x900 | 9 | 9 | 0 | 0 | 0 | 否 | 存在 |
| attacker-detail | /attackers/198.51.100.17 | 1440x900 | 12 | 12 | 0 | 0 | 0 | 否 | 存在 |
| alerts | /alerts | 1440x900 | 10 | 10 | 0 | 0 | 0 | 否 | 存在 |
| overview | / | 1920x1080 | 10 | 10 | 0 | 0 | 0 | 否 | 存在 |
| attackers | /attackers | 1920x1080 | 9 | 9 | 0 | 0 | 0 | 否 | 存在 |
| attacker-detail | /attackers/198.51.100.17 | 1920x1080 | 12 | 12 | 0 | 0 | 0 | 否 | 存在 |
| alerts | /alerts | 1920x1080 | 10 | 10 | 0 | 0 | 0 | 否 | 存在 |

## 2. 页面区域明细

### overview（5 个区域）

| 区域 | 1440×900 | 1920×1080 |
| --- | --- | --- |
| `OV-HEAD` | present | present |
| `OV-KPI` | present | present |
| `OV-TREND` | present | present |
| `OV-DONUT` | present | present |
| `OV-TOP5` | present | present |

结论：两视口均命中全部页面区域。

### attackers（4 个区域）

| 区域 | 1440×900 | 1920×1080 |
| --- | --- | --- |
| `AT-HEAD` | present | present |
| `AT-FILTER` | present | present |
| `AT-TABLE` | present | present |
| `AT-PAGER` | present | present |

结论：两视口均命中全部页面区域。

### attacker-detail（7 个区域）

| 区域 | 1440×900 | 1920×1080 |
| --- | --- | --- |
| `AD-HEAD` | present | present |
| `AD-BANNER` | present | present |
| `AD-PROFILE` | present | present |
| `AD-CHAIN` | present | present |
| `AD-SESSIONS` | present | present |
| `AD-TIMELINE` | present | present |
| `AD-FOOTER` | present | present |

结论：两视口均命中全部页面区域。

### alerts（5 个区域）

| 区域 | 1440×900 | 1920×1080 |
| --- | --- | --- |
| `AL-HEAD` | present | present |
| `AL-STATS` | present | present |
| `AL-FILTER` | present | present |
| `AL-CARDS` | present | present |
| `AL-FOOTER` | present | present |

结论：两视口均命中全部页面区域。

## 3. 说明

- 壳层区域在四个页面共享，两视口均实测存在（见 §1 期望/命中数）。
- `extra` 为未在契约清单中登记的区域；当前为 0，说明页面未私自新增区域 ID。
- 重叠只统计同页业务区域之间的相交面积 >1px²；壳层与页面区域天然嵌套，不计入。
- 横向溢出、console 错误、失败请求、外网请求由 `verify/run-check.mjs` 同轮检查；本清单只记录区域与溢出。
- 主题按钮 `data-theme-toggle` 每页均存在（主题交互与浅色渲染见 `theme-evidence.md`）。

