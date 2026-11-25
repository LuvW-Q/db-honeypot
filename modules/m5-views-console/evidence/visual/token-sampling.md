# 令牌抽样记录（token-sampling.md，T065）

- 生成时间：2026-11-25T07:12:58.897Z｜目标：http://127.0.0.1:8000｜口径：`contracts/ui-contracts.md` §11 + `data-model.md` §5
- 方法：每页抽取 10 个元素 × 2 个属性（背景色/文字色）= 20 处计算样式，与 `src/assets/main.css` 的 `--c-*` 值反查；命中率 **100.0%（100/100）**
- 判定：命中任意已定义令牌即通过（同值多令牌时全部列出）；未命中视为裸色值违规。

| 主题 | 页面 | 选择器 | 属性 | 计算值 | 命中令牌 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| dark | overview | `body` | backgroundColor | `rgb(5, 20, 36)` | --c-background, --c-surface, --c-surface-dim | PASS |
| dark | overview | `body` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `aside` | backgroundColor | `rgb(13, 28, 45)` | --c-surface-container-low | PASS |
| dark | overview | `aside` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `header` | backgroundColor | `rgba(5, 20, 36, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-dim @85% | PASS |
| dark | overview | `header` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `main` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `footer` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | overview | `h1` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `h2` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `[data-region$="-HEAD"]` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `[data-region$="-KPI"]` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | overview | `table th` | backgroundColor | `rgb(1, 15, 31)` | --c-surface-container-lowest | PASS |
| dark | overview | `table th` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | attackers | `body` | backgroundColor | `rgb(5, 20, 36)` | --c-background, --c-surface, --c-surface-dim | PASS |
| dark | attackers | `body` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attackers | `aside` | backgroundColor | `rgb(13, 28, 45)` | --c-surface-container-low | PASS |
| dark | attackers | `aside` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attackers | `header` | backgroundColor | `rgba(5, 20, 36, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-dim @85% | PASS |
| dark | attackers | `header` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attackers | `main` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attackers | `footer` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | attackers | `h1` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attackers | `[data-region$="-HEAD"]` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attackers | `table th` | backgroundColor | `rgb(1, 15, 31)` | --c-surface-container-lowest | PASS |
| dark | attackers | `table th` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | attacker-detail | `body` | backgroundColor | `rgb(5, 20, 36)` | --c-background, --c-surface, --c-surface-dim | PASS |
| dark | attacker-detail | `body` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `aside` | backgroundColor | `rgb(13, 28, 45)` | --c-surface-container-low | PASS |
| dark | attacker-detail | `aside` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `header` | backgroundColor | `rgba(5, 20, 36, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-dim @85% | PASS |
| dark | attacker-detail | `header` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `main` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `footer` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | attacker-detail | `h1` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `h2` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `[data-region$="-HEAD"]` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | attacker-detail | `table th` | backgroundColor | `rgb(1, 15, 31)` | --c-surface-container-lowest | PASS |
| dark | attacker-detail | `table th` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | alerts | `body` | backgroundColor | `rgb(5, 20, 36)` | --c-background, --c-surface, --c-surface-dim | PASS |
| dark | alerts | `body` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | alerts | `aside` | backgroundColor | `rgb(13, 28, 45)` | --c-surface-container-low | PASS |
| dark | alerts | `aside` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | alerts | `header` | backgroundColor | `rgba(5, 20, 36, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-dim @85% | PASS |
| dark | alerts | `header` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | alerts | `main` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | alerts | `footer` | color | `rgb(134, 147, 151)` | --c-outline | PASS |
| dark | alerts | `h1` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | alerts | `h2` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| dark | alerts | `[data-region$="-HEAD"]` | color | `rgb(212, 228, 250)` | --c-on-surface | PASS |
| light | overview | `body` | backgroundColor | `rgb(248, 250, 252)` | --c-background, --c-surface, --c-surface-container | PASS |
| light | overview | `body` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `aside` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | overview | `aside` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `header` | backgroundColor | `rgba(248, 250, 252, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-container @85% | PASS |
| light | overview | `header` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `main` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `footer` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | overview | `h1` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `h2` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `[data-region$="-HEAD"]` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `[data-region$="-KPI"]` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | overview | `table th` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | overview | `table th` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | attackers | `body` | backgroundColor | `rgb(248, 250, 252)` | --c-background, --c-surface, --c-surface-container | PASS |
| light | attackers | `body` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attackers | `aside` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | attackers | `aside` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attackers | `header` | backgroundColor | `rgba(248, 250, 252, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-container @85% | PASS |
| light | attackers | `header` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attackers | `main` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attackers | `footer` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | attackers | `h1` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attackers | `[data-region$="-HEAD"]` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attackers | `table th` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | attackers | `table th` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | attacker-detail | `body` | backgroundColor | `rgb(248, 250, 252)` | --c-background, --c-surface, --c-surface-container | PASS |
| light | attacker-detail | `body` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `aside` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | attacker-detail | `aside` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `header` | backgroundColor | `rgba(248, 250, 252, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-container @85% | PASS |
| light | attacker-detail | `header` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `main` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `footer` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | attacker-detail | `h1` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `h2` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `[data-region$="-HEAD"]` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | attacker-detail | `table th` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | attacker-detail | `table th` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | alerts | `body` | backgroundColor | `rgb(248, 250, 252)` | --c-background, --c-surface, --c-surface-container | PASS |
| light | alerts | `body` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | alerts | `aside` | backgroundColor | `rgb(255, 255, 255)` | --c-surface-bright, --c-surface-container-lowest, --c-surface-container-low, --c-on-primary, --c-on-primary-container, --c-on-secondary | PASS |
| light | alerts | `aside` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | alerts | `header` | backgroundColor | `rgba(248, 250, 252, 0.85)` | --c-background @85%, --c-surface @85%, --c-surface-container @85% | PASS |
| light | alerts | `header` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | alerts | `main` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | alerts | `footer` | color | `rgb(148, 163, 184)` | --c-outline | PASS |
| light | alerts | `h1` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | alerts | `h2` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |
| light | alerts | `[data-region$="-HEAD"]` | color | `rgb(15, 23, 42)` | --c-on-surface | PASS |

## 结论

- 深色/浅色两轮共 100 处抽样，命中 100 处，**命中率 100.0%**；未命中 0 处。
- 未命中项若出现，应回到 `main.css` 补令牌或改组件为令牌类，而不是放行裸色值。
- 与 `token-audit.mjs` 互补：前者查源码字面量，本表查浏览器最终计算值。

