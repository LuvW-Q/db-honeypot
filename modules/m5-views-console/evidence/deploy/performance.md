# 部署性能与体积（T076）

- **测量日期**：2026-11-25｜**环境**：macOS，Docker MySQL 8.0.46（`dbhoneypot-mysql`），
  宿主机 uvicorn（单 worker）`http://127.0.0.1:8000`，前端为 `modules/m5-views-console/frontend/dist`
  最新主题构建（2026-11-25 14:53）。
- **结论**：接口 p95 全部 **≤ 14 ms**（目标 ≤ 500 ms），页面 JS gzip 合计 **≈ 70 KB**
  （目标 ≤ 1.2 MB），无外网依赖、无 CDN 字体；远优于验收阈值。

---

## 1. 接口延迟（warm，20 次采样/端点）

方法：对每个端点先请求 1 次预热，丢弃首次，再串行采样 20 次取中位数/p95；同一进程、
无并发压测。种子数据为确定性 demo（`attack_log=2525`、`sessions=214`、`alerts=8`）。

| 端点 | 状态 | 中位 (ms) | **p95 (ms)** | 最大 (ms) |
| --- | --- | --- | --- | --- |
| `GET /api/health` | 200 | 2.6 | **4.1** | 4.2 |
| `GET /api/overview?range=all` | 200 | 5.9 | **14.0** | 14.2 |
| `GET /api/overview?range=7d` | 200 | 5.1 | **5.8** | 6.0 |
| `GET /api/trend?days=7` | 200 | 4.3 | **5.5** | 5.7 |
| `GET /api/attackers?page=1&page_size=10` | 200 | 3.3 | **4.2** | 4.8 |
| `GET /api/attackers/summary` | 200 | 2.6 | **3.0** | 3.1 |
| `GET /api/attackers/198.51.100.17` | 200 | 7.3 | **8.4** | 8.6 |
| `GET /api/alerts?page=1&page_size=10` | 200 | 2.8 | **4.1** | 4.1 |
| `GET /api/alerts/summary` | 200 | 2.6 | **3.3** | 3.4 |
| `GET /api/rules` | 200 | 2.1 | **3.0** | 3.2 |
| `GET /api/rules/effectiveness` | 200 | 2.5 | **2.9** | 3.2 |

**判定**：最慢端点 `overview?range=all` p95 = 14.0 ms，为阈值 500 ms 的 **2.8%**；
本机 dev 库规模下不存在慢查询路径（索引口径见 M2 `evidence/explain-diff.md`）。

复现（仓库根，服务已启动）：

```bash
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console
/tmp/dbh-venv/bin/python - <<'PY'
import statistics, time, urllib.request
base = 'http://127.0.0.1:8000'
eps = ['/api/health', '/api/overview?range=all', '/api/overview?range=7d',
       '/api/trend?days=7', '/api/attackers?page=1&page_size=10',
       '/api/attackers/summary', '/api/attackers/198.51.100.17',
       '/api/alerts?page=1&page_size=10', '/api/alerts/summary',
       '/api/rules', '/api/rules/effectiveness']
for ep in eps:
    vals = []
    for i in range(21):
        t = time.perf_counter()
        with urllib.request.urlopen(base + ep, timeout=10) as r:
            r.read()
        if i: vals.append((time.perf_counter() - t) * 1000)
    vals.sort()
    print(f"{ep:44s} median={statistics.median(vals):5.1f}ms p95={vals[18]:5.1f}ms")
PY
```

> 首次请求（冷启动、连接池建立）会略慢，验收口径为 warm p95；`/api/health` 含一次
> `SELECT 1`，其余端点走只读连接池（`honeypot_app_ro`）。

## 2. 前端体积（`dist`，gzip 后）

构建：`cd modules/m5-views-console/frontend && corepack pnpm exec vite build`（2026-11-25 14:53）。
gzip 为单文件 `gzip -c` 后字节数；`dist` 目录 4.2 MB 主要来自本地字体与 Material Symbols。

| 产物 | 原始 | gzip |
| --- | --- | --- |
| `index-*.js`（入口，含 Vue/Router/API/主题 composable） | 116.5 KB | **43.9 KB** |
| `OverviewPage-*.js`（懒加载） | 19.6 KB | 7.2 KB |
| `AttackerDetailPage-*.js` | 20.6 KB | 6.5 KB |
| `AlertsPage-*.js` | 15.8 KB | 5.5 KB |
| `AttackersPage-*.js` | 12.3 KB | 4.7 KB |
| 其他共享 chunk（SectionCard/PaginationBar/RiskBadge/PageHeader） | 9.5 KB | 4.3 KB |
| `index-*.css`（Tailwind 产物 + 主题变量） | 37.8 KB | **9.5 KB** |
| **JS 合计** | **≈ 194 KB** | **≈ 70.2 KB** |
| **JS + CSS 合计** | **≈ 232 KB** | **≈ 81.4 KB** |

**判定**：JS gzip 合计 70.2 KB，为阈值 1.2 MB 的 **5.7%**；CSS gzip 9.5 KB。
页面按路由懒加载，四页各自 chunk ≤ 7.2 KB(gzip)，首屏只加载入口 + 概览 chunk。

复现：

```bash
cd modules/m5-views-console/frontend
for f in dist/assets/*.js dist/assets/*.css; do
  printf '%8s  %s\n' "$(gzip -c "$f" | wc -c)" "$f"
done
du -sh dist
```

## 3. 部署形态与资源

| 项 | 当前值 | 说明 |
| --- | --- | --- |
| 前端托管 | FastAPI `StaticFiles`（`WEB_DIST_DIR=modules/m5-views-console/frontend/dist`） | 与 `/api/*` 同源，无 CORS、无 CDN、无外网请求 |
| 后端 | 宿主机 `uvicorn --factory m1_transaction_integration.api.app:create_app`，单 worker | 课程演示规模足够；生产可加 worker/反向代理 |
| 数据库 | Docker `mysql:8.0`（healthy），`honeypot_dev` 16 张表/视图 | 初始化脚本 + Alembic 迁移，种子确定性 |
| 诱饵 | `m2_decoy_capture`，默认 `127.0.0.1:3307` | 与 MySQL 3306 分离；非回环绑定会被拒绝 |
| 静态资源 | 本地字体（Inter Variable / JetBrains Mono / Material Symbols） | 浏览器检查 `external_requests=[]`，离线可用 |
| 冷启动 | `uvicorn` 启动到 `/api/health` 可用 < 2 s；MySQL 容器 healthy 依赖 compose healthcheck | `make verify` 第 1–2 步覆盖 |

## 4. 限制与说明

1. 数据量为课程演示规模（约 2.5k 事件 / 214 会话 / 8 告警），未做百万级压测；
   查询路径已用 EXPLAIN 验证走索引（M2 证据），但容量规划需按真实规模另测。
2. 未做并发压测（如 `wrk`/`k6`）；本表是串行 warm 延迟，用于验收“页面不等待”的体验底线。
3. 浏览器端渲染耗时由 `verify/run-check.mjs` 的 `networkidle` + 字体就绪判定间接覆盖，
   未单独采集 LCP/INP 等 Web Vitals。
4. 前端构建在本机 iCloud 卷上 `vue-tsc` 偶发极慢（10+ 分钟），属文件系统 IO 现象，
   不影响产物；验收记录使用已生成的最新 `dist`。
