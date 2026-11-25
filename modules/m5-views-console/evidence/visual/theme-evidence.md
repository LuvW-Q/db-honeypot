# 主题证据：跟随系统的深浅色切换（T084/T085）

- **任务**：T080–T085（FR-133、FR-134、`contracts/ui-contracts.md` §12）
- **日期**：2026-11-25｜**环境**：`http://127.0.0.1:8000`（最新主题构建 14:53），Playwright Chromium
- **结论**：**通过**。默认 `system`；系统外观变化实时跟随；页头圆角矩形按钮按
  `system → light → dark → system` 循环；刷新后保持选择；首屏无闪烁；四页在浅色下
  无 console 错误、无横向溢出、无缺失区域。

---

## 1. 实现方式（单一口径）

| 层 | 实现 | 位置 |
| --- | --- | --- |
| 令牌 | 30 个语义色以 RGB 三元组定义在 `:root`（深色）与 `html.light`（浅色）；`tailwind.config.js` 只做 `rgb(var(--c-*))` 映射，组件禁止裸色值 | `src/assets/main.css`、`tailwind.config.js` |
| 图表 | `--chart-1..5`、`--chart-grid/axis/track/tooltip-*/center-*/peak-ring` 均为**完整颜色值**（`rgb(...)`），SVG `stroke`/`fill` 用 `var()` 生效 | `main.css` §主题变量、`TrendChart.vue`、`IntentDonut.vue` |
| 状态 | `ThemeMode = system \| light \| dark`，`localStorage["dbh-theme"]`，`matchMedia('(prefers-color-scheme: dark)')` 监听实时切换 | `src/composables/theme.ts` |
| 首屏 | `index.html` 内联脚本在 CSS/JS 前读取存储或系统偏好，设置 `html.dark/html.light`、`color-scheme`、`dataset.theme`，**避免首帧闪白/闪黑** | `index.html` |
| 控件 | 页头圆角矩形按钮（`rounded border border-outline-variant bg-surface-container-low`），显示 `跟随系统/浅色/深色` 与对应图标，`aria-label`/`title` 同步 | `src/App.vue`（`data-theme-toggle`） |
| 过渡 | `body` 颜色/背景 200ms 过渡；图表颜色随 CSS 变量即时变化 | `main.css` |

**浅色口径**来自 `ux/stitch_database_honeypot_analytics_console_light/`：画布 `#f8fafc`、
卡片 `#ffffff`、`surface-container-high #f1f5f9`、`on-surface #0f172a`、
`on-surface-variant #64748b`、`primary #0284c7`、`secondary #0f766e`；严重度在浅色下
加深（critical `#e11d48`、high `#ea580c`、medium `#d97706`、low `#059669`），**不是简单反色**。

## 2. 交互验证（真实浏览器，`verify/run-check.mjs`）

`browser.json` → `interactions.theme`（`result: pass`，`failures: []`）：

| 步骤 | 操作 | `resolved` | `html class` | `color-scheme` | 按钮模式/标签 | `localStorage` | `body` 背景 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| system-dark | 系统深色 + 默认 system | dark | `dark` | dark | system · 主题：跟随系统（深色） | `system` | `rgb(5, 20, 36)` |
| system-follows-light | **不刷新**，系统切浅色 | light | `light` | light | system · 主题：跟随系统（浅色） | `system` | `rgb(248, 250, 252)` |
| override-light | 点击按钮一次 | light | `light` | light | light · 主题：浅色（浅色） | `light` | `rgb(248, 250, 252)` |
| override-dark | 再点一次 | dark | `dark` | dark | dark · 主题：深色（深色） | `dark` | `rgb(5, 20, 36)` |
| override-system | 再点一次 | light | `light` | light | system · 主题：跟随系统（浅色） | `system` | `rgb(248, 250, 252)` |
| persisted-after-reload | 刷新页面 | light | `light` | light | system · 主题：跟随系统（浅色） | `system` | `rgb(248, 250, 252)` |

要点：

- **实时跟随**：步骤 2 在 `emulateMedia({colorScheme:'light'})` 后未刷新即切换，
  `resolved/class/color-scheme/背景` 全部变为浅色（采样前等待 350ms 过渡完成）；
- **手动覆盖优先**：覆盖后 `localStorage` 为 `light/dark`，系统变化不再影响；回到 system
  后恢复跟随；
- **持久化**：刷新后按钮仍显示“跟随系统”，说明 `localStorage` 与首屏内联脚本一致；
- 按钮每步的 `data-theme-mode`、`aria-label`、`title` 与当前模式匹配（`aria` 检查见同轮
  `interactions.a11y`）。

## 3. 浅色渲染验收（四页 × 1440×900）

同轮 `browser.json` → `light_pages`（`colorScheme: light`、`localStorage=system`）：

| 页面 | `resolved` | 背景 | console 错误 | 缺失区域 | 横向溢出 |
| --- | --- | --- | --- | --- | --- |
| overview | light | `rgb(248, 250, 252)` | 0 | 0 | 否 |
| attackers | light | `rgb(248, 250, 252)` | 0 | 0 | 否 |
| attacker-detail | light | `rgb(248, 250, 252)` | 0 | 0 | 否 |
| alerts | light | `rgb(248, 250, 252)` | 0 | 0 | 否 |

深色主回归（四页 × 两视口）同轮 `result: pass`：console 错误 0、失败请求 0、外网请求 0、
横向溢出 0、`missing_regions=[]`。

## 4. 截图基线

- 深色：`evidence/visual/baseline/{page}-{viewport}.png`（8 张，2026-11-25 14:54 重采）
- 浅色：`evidence/visual/baseline-light/{page}-{viewport}-light.png`（8 张，同上）

| 页面 | 深色 1440×900 | 浅色 1440×900 |
| --- | --- | --- |
| 首页概览 | [overview-1440x900.png](baseline/overview-1440x900.png) | [overview-1440x900-light.png](baseline-light/overview-1440x900-light.png) |
| 攻击者列表 | [attackers-1440x900.png](baseline/attackers-1440x900.png) | [attackers-1440x900-light.png](baseline-light/attackers-1440x900-light.png) |
| 攻击者详情与时间线 | [attacker-detail-1440x900.png](baseline/attacker-detail-1440x900.png) | [attacker-detail-1440x900-light.png](baseline-light/attacker-detail-1440x900-light.png) |
| 告警列表 | [alerts-1440x900.png](baseline/alerts-1440x900.png) | [alerts-1440x900-light.png](baseline-light/alerts-1440x900-light.png) |

两套基线均含 `metadata.json`（请求主题、解析结果、`html class`、`color-scheme`、背景色）。

## 5. 修复记录（本主题实现期间的真实问题）

| 问题 | 现象 | 修复 |
| --- | --- | --- |
| 图表色变量为 RGB 三元组却被直接用于 SVG `style` | 浅色下折线、峰值点、tooltip、图例点变黑/透明 | 图表变量改为完整颜色 `rgb(...)`，组件 `stroke`/`fill` 用 `var(--chart-*)`；Minify 后为 `#4cd7f6/#0284c7` 等 |
| 侧栏激活项使用实心 `bg-primary-container` | 与浅色原型的浅蓝底 + 蓝字不一致 | 改为 `bg-primary/10 + border-primary/30 + text-primary`，深浅两套都更接近原型 |
| 发光阴影硬编码青色/红色 | 浅色下按钮与告警卡发光过重 | 抽出 `--shadow-glow/-error/-primary` 主题变量，浅色用低透明度 |

## 6. 复现命令

```bash
cd modules/m5-views-console/frontend
export PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers COREPACK_HOME=/tmp/corepack

# 交互 + 浅色四页回归（写 browser.json）
corepack pnpm exec node verify/run-check.mjs --base-url http://127.0.0.1:8000 \
  --out ../evidence/deploy/theme-run

# 两套截图基线
corepack pnpm exec node verify/capture-baseline.mjs --base-url http://127.0.0.1:8000 \
  --out ../evidence/visual/baseline --theme dark
corepack pnpm exec node verify/capture-baseline.mjs --base-url http://127.0.0.1:8000 \
  --out ../evidence/visual/baseline-light --theme light

# 手工体验：浏览器打开 http://127.0.0.1:8000/ ，点页头右侧圆角按钮循环三种模式
# 系统跟随：macOS 外观切换（或 DevTools ▸ Rendering ▸ Emulate CSS media prefers-color-scheme）
```

## 7. 边界

- 浏览器自动化用 `emulateMedia` 模拟系统外观；真实 OS 切换等价（监听同一 `matchMedia`）。
- 首屏“无闪烁”由内联脚本保证，`run-check` 未逐帧断言；截图基线在主题确定后采集。
- 浅色基线不替代原型逐像素比对，验收口径为“同语义、同层级、同布局、令牌一致”；
  原型中的演示数据与当前种子不同，数值不要求一致。
- 打印样式未适配双主题（课程范围为屏幕演示）。
