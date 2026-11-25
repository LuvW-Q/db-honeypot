# 视觉复核指南（review-guide.md，T066）

- **用途**：评审者 10 分钟独立复核四页视觉、双主题与证据一致性。
- **前置**：仓库根；Docker MySQL 可用；`/tmp/dbh-venv` 已建；端口 8000 空闲。
- **证据根**：`modules/m5-views-console/evidence/`。

## 1. 十分钟步骤

| 分钟 | 动作 | 期望看到 |
| --- | --- | --- |
| 0–2 | `make db-up && make migrate && make seed`；`make api`（终端 A） | 健康检查 200；214 会话 / 2525 事件 / 8 告警 |
| 2–4 | 浏览器打开 `http://127.0.0.1:8000/`，依次点四页导航 | 概览/攻击者列表/详情/告警；无 console 报错；页头时钟走秒 |
| 4–6 | 点页头右侧圆角按钮：跟随系统 → 浅色 → 深色 → 跟随系统；再切系统外观 | 即时变化、无刷新闪烁；按钮文字/图标/`title` 与模式一致；刷新后保持 |
| 6–8 | 概览切 24H/7天/全部；列表搜索 + 风险档 + 排序；告警页签/等级/类型/时间；单条已读 | 数据真实变化、URL 同步、统计与徽标更新；禁用控件有"演示未开放"提示 |
| 8–10 | 对照 `evidence/visual/baseline/`（深色）与 `baseline-light/`（浅色）截图 | 布局/层级/令牌一致；差异只允许数据值与时间戳 |

## 2. 一键证据复核

```bash
cd modules/m5-views-console/frontend
export PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers COREPACK_HOME=/tmp/corepack

# 1) 源码令牌审计（0 违规）
corepack pnpm exec node verify/token-audit.mjs --out ../evidence/deploy/theme-run/token-audit.json

# 2) 浏览器回归 + 主题交互 + 浅色四页（result=pass）
corepack pnpm exec node verify/run-check.mjs --base-url http://127.0.0.1:8000 \
  --out ../evidence/deploy/theme-run

# 3) 交互 18 项（result=pass）
corepack pnpm exec node verify/interaction-check.mjs --base-url http://127.0.0.1:8000 \
  --out ../evidence/deploy/theme-run

# 4) 区域覆盖 + 令牌计算值抽样（100% / 100%）
corepack pnpm exec node verify/region-audit.mjs --base-url http://127.0.0.1:8000 \
  --out ../evidence/visual/region-checklist.md
corepack pnpm exec node verify/token-sampling.mjs --base-url http://127.0.0.1:8000
```

## 3. 差异登记规则（引用 `ui-contracts.md` §10）

| 级别 | 定义 | 处理 |
| --- | --- | --- |
| 一致 | 区域结构、层级、令牌、交互与裁定终态相同 | 记录"一致" |
| 差异（可接受） | 数据值/时间戳/演示数据不同，或原型不可实现处的等价替代（如业务库标签→网络归属） | 记录理由 + 对应附录 B 编号，不改代码 |
| 差异（待修） | 令牌外颜色、圆角/间距越界、区域缺失、交互无反馈 | 开修复项，修完重跑 §2 |
| 不接受 | 死链、白屏、console 报错、外网请求、假成功、硬编码样例值 | 阻断验收，必须修复 |

**判定证据**必须能对上同一轮脚本产物（`browser.json` / `interaction.json` / `region-audit.json` /
`token-audit.json`），不接受"手工看过"的口头结论。

## 4. 常见问题

1. **页面全黑/全白**：确认 `index.html` 内联脚本未被 CSP 拦截；`localStorage["dbh-theme"]`
   可清空后刷新。
2. **图表线条不可见**：图表变量必须是完整颜色值（`--chart-*: rgb(...)`），不能是三元组；
   用 `token-audit` 与 `token-sampling` 双查。
3. **区域 overlap 报警**：壳层与页面区域嵌套属正常，脚本只统计同页业务区域；页面区域之间
   相交 >1px² 才是缺陷。
4. **截图与当前不一致**：截图是固定种子 + 固定视口产物；数据变化后需重采（`capture-baseline.mjs`）。
5. **Playwright 浏览器缺失**：设置 `PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers`，不要重装。

## 5. 相关文档

- [`region-checklist.md`](region-checklist.md)：21 区域 × 8 组合覆盖率
- [`token-sampling.md`](token-sampling.md)：100 处计算样式抽样
- [`theme-evidence.md`](theme-evidence.md)：双主题交互与浅色渲染
- [`adjudication-checklist.md`](adjudication-checklist.md)：28 条差异闭环
- `specs/002-ui-console-modularization/contracts/ui-contracts.md` §10–§12
