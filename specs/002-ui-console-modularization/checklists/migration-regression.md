# 搬迁回归门禁记录（T018）

- **执行日期**：2026-11-25｜**执行环境**：仓库根 `db-honeypot`，macOS，MySQL 8.0.46 容器
  `dbhoneypot-mysql`（healthy），Python 3.11/3.12 虚拟环境，Node 24 + pnpm。
- **结论**：**通过**。搬迁后依赖锁定、迁移、全量测试、静态检查、模块门禁、应用启动与
  四页冒烟全部通过；未发现导入/路径回归。

---

## 1. 门禁结果

| 步骤 | 命令 | 结果 | 证据/备注 |
| --- | --- | --- | --- |
| 依赖锁定一致性 | `UV_CACHE_DIR=/tmp/uv-cache uv lock --check` | **PASS**（`Resolved 45 packages`，21ms） | 锁文件与 `pyproject.toml` 一致；缓存目录需可写（仓库外 `~/.cache/uv` 在本机受沙箱限制，改用 `/tmp/uv-cache`） |
| 数据库迁移 | `PYTHONPATH=.:modules/m1-transaction-integration /tmp/dbh-venv/bin/python -m alembic upgrade head` | **PASS**（无待执行迁移） | `alembic current` → `0004_seed_rules (head)` |
| 全量测试 | `PYTHONPATH=.:… /tmp/dbh-venv/bin/python -m pytest tests shared/tests modules shared/deploy/tests -q` | **PASS：292 passed**（34.56s） | 含根测试、shared、M1–M5 模块测试、部署工具链测试 |
| 静态检查 | `/tmp/dbh-venv/bin/python -m ruff check .` | **PASS**（All checks passed!） | 0 error / 0 warning |
| 目录结构门禁 | `python -m shared.deploy.check_structure` | **PASS**（PASS 39 / FAIL 0 / WARN 0） | 旧布局残留、命名、必需文件 |
| 模块边界门禁 | `python -m shared.deploy.check_boundaries` | **PASS**（144 个 Python 文件） | 依赖矩阵、公开门面、旧 `app.*` 前缀、循环依赖 |
| 应用启动 | `uvicorn --factory m1_transaction_integration.api.app:create_app --port 8000` | **PASS** | `/api/health` → `{"status":"ok","database":{"status":"ok","latency_ms":2}}` |
| 四页冒烟（浏览器） | `node verify/run-check.mjs --base-url http://127.0.0.1:8000` | **PASS**（`result: pass`，`failures: []`） | 四页 × 两视口区域/溢出/console 检查 + 主题交互；产物 `modules/m5-views-console/evidence/deploy/theme-run/browser.json` |

## 2. 搬迁相关的回归点与处理

| 回归点 | 现象 | 处理 |
| --- | --- | --- |
| 旧的 `app.*` 导入前缀 | 搬迁后 `shared`/各模块不再有 `from app…` | `check_boundaries` 的 `old_prefix` 规则通过（0 命中） |
| M5 证据脚本越界导入 `shared` | `evidence/sql-ui/run_queries.py` 被边界门禁判为 `shared_import_scope` 违规 | 脚本移入 `m5_views_console/cli/run_queries.py`（边界允许 `cli/` 导入 shared），同步更新 `views/queries.sql`、M5 README、证据索引与 `docs/test-plan.md` 中的路径 |
| 前端产物路径 | 后端按 `WEB_DIST_DIR=modules/m5-views-console/frontend/dist` 托管 | `check_structure` 与 `/api/health`/四页冒烟均通过；`dist` 由最新主题构建覆盖 |
| 测试库/迁移路径 | 迁移脚本仍在 `modules/m1-transaction-integration/migrations/` | `alembic upgrade head` 正常，`pytest` 全绿 |

> 备注：同一天曾在“构建/浏览器任务并行 + MySQL 冷启动”时出现过一轮 4 failed / 2 errors
> （概览计数断言、规则版本 PATCH、R04 阈值用例），单独复跑与随后串行全量复跑均通过
> （292 passed）。判定为并行负载导致的测试库/连接时序抖动，非代码回归；门禁以串行结果为准。
> 若后续复现，先确认没有并发任务占用 `honeypot_test`，再按模块单独复跑定位。

## 3. 复现命令

```bash
cd /path/to/db-honeypot
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console
PY=/tmp/dbh-venv/bin/python

UV_CACHE_DIR=/tmp/uv-cache uv lock --check
$PY -m alembic upgrade head && $PY -m alembic current
$PY -m pytest tests shared/tests modules shared/deploy/tests -q
$PY -m ruff check .
$PY -m shared.deploy.check_structure
$PY -m shared.deploy.check_boundaries

$PY -m uvicorn --factory m1_transaction_integration.api.app:create_app --port 8000 &
# 四页冒烟（浏览器检查，需 Playwright 浏览器已安装）
cd modules/m5-views-console/frontend
PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers node verify/run-check.mjs --base-url http://127.0.0.1:8000
```
