# 控制台截图索引（screenshots/README.md）

本目录保存**当前控制台**的页面截图（002 视觉重构 + 深/浅双主题），以及 001 期旧版图的
历史对照。当前权威基线同时存放在 `modules/m5-views-console/evidence/visual/`（含
`metadata.json` 与两视口）。

| 项目 | 内容 |
| --- | --- |
| 用途 | 说明哪张图对应哪一页、哪套主题，以及新版基线的命名/生成/归档约定 |
| 目标读者 | 答辩演示者、课程报告撰写人、视觉验收执行人 |
| 权威约定 | 命名与元数据字段见 `specs/002-ui-console-modularization/data-model.md` §6.2；区域契约见 `contracts/ui-contracts.md` §3；主题契约见同文件 §12 |
| 最近核对 | 2026-11-25（基线 14:54 重采，浅色 14:55 重采） |

---

## 1. 当前深色基线（002，默认主题）

页面：Vue 3 + Tailwind 3.4.19 语义令牌，固定侧栏 288px + 固定页头 64px，自研 SVG 图表。

| 页面 | 1440×900（本目录副本） | 1920×1080（权威证据） |
| --- | --- | --- |
| 首页概览 | [overview-1440x900.png](overview-1440x900.png) | [overview-1920x1080.png](../modules/m5-views-console/evidence/visual/baseline/overview-1920x1080.png) |
| 攻击者列表 | [attackers-1440x900.png](attackers-1440x900.png) | [attackers-1920x1080.png](../modules/m5-views-console/evidence/visual/baseline/attackers-1920x1080.png) |
| 攻击者详情与时间线 | [attacker-detail-1440x900.png](attacker-detail-1440x900.png) | [attacker-detail-1920x1080.png](../modules/m5-views-console/evidence/visual/baseline/attacker-detail-1920x1080.png) |
| 告警列表 | [alerts-1440x900.png](alerts-1440x900.png) | [alerts-1920x1080.png](../modules/m5-views-console/evidence/visual/baseline/alerts-1920x1080.png) |

> 当前主题默认为 **跟随系统**。上面 8 张图在系统深色外观下采集；页头右侧圆角矩形按钮
> 可在 `跟随系统 → 浅色 → 深色` 间循环，切换即时生效并持久化。

## 2. 当前浅色基线（002，跟随浅色方案）

浅色令牌来自 `ux/stitch_database_honeypot_analytics_console_light/`：画布 `#f8fafc`、
卡片 `#ffffff`、`primary #0284c7`、`secondary #0f766e`，严重度加深，不是简单反色。

| 页面 | 1440×900（本目录副本） | 1920×1080（权威证据） |
| --- | --- | --- |
| 首页概览 | [overview-1440x900-light.png](overview-1440x900-light.png) | [overview-1920x1080-light.png](../modules/m5-views-console/evidence/visual/baseline-light/overview-1920x1080-light.png) |
| 攻击者列表 | [attackers-1440x900-light.png](attackers-1440x900-light.png) | [attackers-1920x1080-light.png](../modules/m5-views-console/evidence/visual/baseline-light/attackers-1920x1080-light.png) |
| 攻击者详情与时间线 | [attacker-detail-1440x900-light.png](attacker-detail-1440x900-light.png) | [attacker-detail-1920x1080-light.png](../modules/m5-views-console/evidence/visual/baseline-light/attacker-detail-1920x1080-light.png) |
| 告警列表 | [alerts-1440x900-light.png](alerts-1440x900-light.png) | [alerts-1920x1080-light.png](../modules/m5-views-console/evidence/visual/baseline-light/alerts-1920x1080-light.png) |

采集命令（仓库根执行，需先构建 + 启动服务 + 固定种子数据）：

```bash
make db-up && make migrate && make seed     # 固定种子（保证截图可复现）
make frontend-build && make api             # 终端 A：构建产物 + 后端托管
make capture                                # 终端 B：深色 8 张 → evidence/visual/baseline/
cd modules/m5-views-console/frontend
corepack pnpm exec node verify/capture-baseline.mjs \
  --base-url http://127.0.0.1:8000 --out ../evidence/visual/baseline-light --theme light
```

`page ∈ {overview, attackers, attacker-detail, alerts}`，`viewport ∈ {1440x900, 1920x1080}`
（`deviceScaleFactor=1`、`locale=zh-CN`、`timezone=Asia/Shanghai`）。浅色文件名追加
`-light`，并在 `metadata.json` 记录 `theme.requested/resolved/classes/colorScheme/background`。
`attacker-detail` 由列表首个攻击者 IP 动态构造路由，列表为空时跳过——采集前必须有种子数据。

**元数据**（`data-model.md` §6.2）：固定数据指纹（`make verify` 的 `seed-digest.txt`）、
采集时间 UTC/UTC+8、视口/缩放、构建版本、链路核验（console 错误 0、失败请求 0、
外网请求 0、横向溢出 0）。

## 3. 001 期历史截图（重构前后对照）

| 文件 | 页面 | 说明 |
| --- | --- | --- |
| [01-overview.png](01-overview.png) | 概览 | 001 版浅色首页：Element Plus + ECharts，1600×1000 |
| [02-attackers.png](02-attackers.png) | 攻击者列表 | 001 版列表：风险等级/意图/排序筛选、分页 |
| [03-attacker-detail.png](03-attacker-detail.png) | 攻击者详情 | 001 版详情：来源画像、会话/告警摘要 |
| [04-alerts.png](04-alerts.png) | 告警列表 | 001 版告警：筛选、列表与已读处置 |

> ⚠️ 这 4 张图**不是当前界面**：002 已改为语义令牌 + 自研 SVG 图表 + 固定侧栏/页头，
> 页面标题、导航与区域 ID 均已变化；只用于“重构前后对比”，答辩请用 §1/§2。

## 4. 截图归档纪律

1. **只放控制台页面图**：ER 图、架构图、EXPLAIN 结果不放本目录（ER 图在
   `modules/m3-er-constraints/evidence/schema.png` / `schema.svg`）。
2. **一图一名**：深色 `{page}-{viewport}.png`；浅色 `{page}-{viewport}-light.png`；
   手工截图用 `<用例号>_<页面>_<时间戳>.png`。
3. **保留原始分辨率**：不要二次压缩或裁剪；需要局部放大时另存副本并标注 `-crop`。
4. **不提交大体积录屏**：视频留在本机，报告里写文件名与生成日期。
5. **截图与证据同源**：每张截图应能对上 `evidence/deploy/theme-run/browser.json`、
   `evidence/visual/{baseline,baseline-light}/metadata.json` 或 `evidence/visual/region-audit.json`
   中的同一轮数据。

## 5. 相关文档

- [../architecture.md](../architecture.md)：模块结构、部署模型与四页路由。
- [../demo-script.md](../demo-script.md)：四页演示步骤、主题切换讲解点与每步可见结果。
- [../test-plan.md](../test-plan.md)：视觉/部署/主题验收场景（A-09–A-11、A-16）与证据位置。
- [../modules/m5-views-console/evidence/visual/theme-evidence.md](../modules/m5-views-console/evidence/visual/theme-evidence.md)：主题交互与浅色渲染证据。
- [../modules/m5-views-console/evidence/visual/region-checklist.md](../modules/m5-views-console/evidence/visual/region-checklist.md)：区域覆盖率清单（100%）。
- `specs/002-ui-console-modularization/contracts/ui-contracts.md`：壳层尺寸、四页区域、令牌与主题契约。
- `specs/002-ui-console-modularization/data-model.md` §6.2：视觉基线记录字段。
