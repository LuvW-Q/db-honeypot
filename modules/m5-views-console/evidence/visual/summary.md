# 视觉验收汇总（verify2）

生成时间：2026-11-25T16:00:41

| 轮次 | 开始时间 | 结束时间 | 结果 | 失败步骤 |
| --- | --- | --- | --- | --- |
| verify-run-1 | 2026-11-25T15:27:07+0800 | 2026-11-25T15:37:46+0800 | pass | 无 |

固定种子数据确定性：stable（各轮摘要一致）

- verify-run-1: `53a2be97f12e1216cbe5d7e59d5ad2257a2af99da3a19c9cd39efd4fbbd7307c`

### verify-run-1 证据摘要

- 令牌审计：violations=0，checked_files=28
- 浏览器页面：8 条（页面×视口），异常 0 条；console/请求错误与横向溢出均为 0
- 区域覆盖率：100%（命中 82/82）
- 截图（verify-run-1）：12 张（深色 8 + 浅色 4）

## 各轮步骤

### verify-run-1
- [ok] 前置检查（docker/python/node/playwright/端口就绪）
- [ok] 启动数据库（MySQL 健康）
- [ok] 数据库迁移（alembic upgrade head）
- [ok] 固定种子数据（reset → gen(200/2400) → demo_basic；digest=53a2be97f12e…）
- [skip] 构建前端（复用已有 dist（--skip-build，调试模式））
- [ok] 启动后端（uvicorn factory（PID 45065））
- [ok] 健康检查与静态资源（health 200；SPA 入口 + 本地资源 200/content-type；四页 favicon 200）
- [ok] 浏览器检查（四页 × 两视口；browser.json result=pass）
- [ok] 令牌审计（violations=0）
- [skip] 页面-数据库抽样（verify2 模式跳过（由 make verify 执行））
- [skip] 降级验证（verify2 模式跳过（由 make verify 执行））
- [ok] 写证据（modules/m5-views-console/evidence/visual/verify-run-1）
- [ok] 清理（后端已停止；MySQL 保持运行）

