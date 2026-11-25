# 部署模型与部署验收说明（T006）

本文描述模块化重构后的部署形态：容器 MySQL + 宿主后端统一托管前端产物（单地址），
以及固定数据卷、四类最小权限账号、`honeypot_test` 测试库隔离与 13 步验收流程。
规格来源：`specs/002-ui-console-modularization/contracts/deployment-verify.md`、
`contracts/module-boundaries.md`、`quickstart.md`。

> **安全边界**：只允许在授权的本机、虚拟机或隔离实验网络运行；容器网络为隔离网段
> `172.28.0.0/24`，MySQL 仅绑定 `127.0.0.1:3306`，后端仅监听回环地址，禁止暴露公网。

## 1. 部署拓扑

```text
┌──────────────────────────── 宿主（127.0.0.1） ────────────────────────────┐
│                                                                          │
│  浏览器 ──HTTP──▶ uvicorn :8000（唯一对外地址）                           │
│                     │  m1_transaction_integration.api.app:create_app      │
│                     │  托管 modules/m5-views-console/frontend/dist        │
│                     │  /api/* 业务接口 + /api/health 健康检查              │
│                     │                                                      │
│                     ├── asyncmy :3306 ──▶ ┌──────────── Docker ────────┐  │
│  诱饵客户端 ──MySQL 协议──▶ :3307        │ MySQL 8.0 容器             │  │
│                  m2_decoy_capture.server  │ dbhoneypot-mysql          │  │
│                                           │ 网段 172.28.0.0/24        │  │
│                                           │ 卷 dbhoneypot_mysql_data  │  │
│                                           └───────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

- 前端**不再**单独启动 Web 服务器：`make frontend-build` 生成 `dist/`，由后端按
  `WEB_DIST_DIR` 挂载；四页使用 hash 路由，无需服务器 rewrite。
- 诱饵服务（M2）是独立进程，监听 `HONEYPOT_HOST:HONEYPOT_PORT`（默认 `127.0.0.1:3307`），
  与真实 MySQL 的 3306 分离，避免误连。

## 2. 端口

| 端口 | 进程 | 说明 |
| --- | --- | --- |
| 8000 | uvicorn（宿主） | 唯一控制台/API 地址；健康检查 `/api/health` |
| 3306 | MySQL 容器 | 仅绑定 `127.0.0.1`，供后端与迁移使用 |
| 3307 | M2 诱饵服务 | 模拟 MySQL，供授权客户端/模拟器连接 |
| 5173 | Vite（可选） | 仅前端独立开发模式，生产部署不使用 |

## 3. 数据卷与生命周期

| 对象 | 名称 | 说明 |
| --- | --- | --- |
| 命名卷 | `dbhoneypot_mysql_data` | MySQL 数据目录；`make db-down` 不删除 |
| 网络 | `dbhoneypot_net`（`172.28.0.0/24`） | 容器隔离网段 |
| 初始化 | `modules/m1-transaction-integration/db/init/` | 首次启动建库、建四类账号 |

常用命令：

```bash
make db-up      # 启动容器并等待健康（首次自动执行 init 脚本）
make db-down    # 停止并删除容器，保留数据卷
make migrate    # alembic upgrade head（迁移脚本在 M1 模块）
make seed       # 固定种子数据：reset → gen(200/2400) → demo_basic
docker compose down -v   # 危险：连数据卷一起清空，仅用于彻底重置实验环境
```

数据保留策略：`.env` 的 `DATA_RETENTION_DAYS` 供业务清理任务使用；验收与演示请用
`make reset-demo` 或 `make seed` 重建，不要手工 `DROP DATABASE`。

## 4. 账号与最小权限

初始化脚本 `01-init-databases.sh` 创建四类账号（口令来自 `.env`，均为 TEST-ONLY 占位）：

| 账号 | 用途 | 权限 |
| --- | --- | --- |
| `honeypot_migrate` | Alembic 迁移、建表/视图/索引/种子 | 目标库 DDL + DML |
| `honeypot_app_rw` | 后端运行期写入（事件、告警、画像） | 目标库 DML，无 DDL |
| `honeypot_app_ro` | 控制台只读查询 | 目标库 SELECT |
| `honeypot_backup` | 备份导出 | 目标库 SELECT + LOCK TABLES 等备份所需权限 |

- 后端只使用 `DATABASE_URL`（`app_rw`）与 `READONLY_DATABASE_URL`（`app_ro`）；
- 迁移只使用 `MIGRATE_DATABASE_URL`（`migrate`）；
- 迁移完成后可执行
  `bash modules/m1-transaction-integration/db/grants/apply_table_grants.sh honeypot_dev`
  收紧表级权限（业务账号仅能访问白名单表）。

## 5. 数据库隔离（SC-028）

| 库 | 用途 | 连接变量 |
| --- | --- | --- |
| `honeypot_dev` | 本地开发/演示 | `DATABASE_URL`、`READONLY_DATABASE_URL`、`MIGRATE_DATABASE_URL` |
| `honeypot_test` | pytest 专用 | `TEST_DATABASE_URL`（根 `conftest.py` 只在此库建/清表） |
| `honeypot_demo` | 可选演示快照库 | 手工迁移/导入，不参与自动化验收 |

根 `conftest.py` 的 `prepare_test_database` 在会话开始时对 `honeypot_test` 执行迁移与清理，
`database_isolation` 在每个用例后清空业务表；因此 `make test` **不会**破坏开发数据。
部署验收（`make verify`）使用 `honeypot_dev` 的固定种子数据，通过 `reset → gen → import`
三步重建，保证每轮一致。

## 6. 环境变量（.env）

| 变量 | 默认/示例 | 说明 |
| --- | --- | --- |
| `MYSQL_IMAGE` | `mysql:8.0` | 容器镜像，可离线环境替换为本地镜像 |
| `MYSQL_HOST` / `MYSQL_PORT` | `127.0.0.1` / `3306` | 容器 MySQL 地址 |
| `MYSQL_ROOT_PASSWORD` | TEST-ONLY | 容器 root（仅初始化与管理用） |
| `HONEYPOT_*_PASSWORD` | TEST-ONLY | 四类业务账号口令 |
| `MIGRATE_DATABASE_URL` | `.../honeypot_dev` | 迁移连接（migrate 账号） |
| `DATABASE_URL` | `.../honeypot_dev` | 应用读写（app_rw） |
| `READONLY_DATABASE_URL` | `.../honeypot_dev` | 应用只读（app_ro） |
| `TEST_DATABASE_URL` | `.../honeypot_test` | pytest 专用 |
| `HONEYPOT_HOST` / `HONEYPOT_PORT` | `127.0.0.1` / `3307` | 诱饵服务监听 |
| `HONEYPOT_ACCOUNTS` | `demo_reader:...` | 诱饵账号（用户名:口令，逗号分隔） |
| `HONEYPOT_ALLOWED_CLIENT_CIDRS` | `127.0.0.1/32,172.28.0.0/24` | 允许连接诱饵的网段 |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | 后端监听 |
| `WEB_DIST_DIR` | `modules/m5-views-console/frontend/dist` | 前端产物目录（后端托管） |
| `DATA_RETENTION_DAYS` / `AI_ENABLED` / `LOG_LEVEL` | `30` / `false` / `INFO` | 运行参数 |

`.env` 不入库（`.gitignore` 忽略）；`.env.example` 只放占位口令，禁止填真实凭据。

## 7. 首次部署步骤

```bash
cp .env.example .env          # 按注释确认占位口令
make db-up                    # 容器 MySQL（首次执行 init 建库/账号）
make install                  # .venv + dev 依赖（有 uv 时 uv sync）
make frontend-install         # corepack pnpm install
make migrate                  # 建表/视图/索引/规则种子
make seed                     # 固定种子数据（200 会话 / 2400 事件 / demo_basic）
make frontend-build           # 构建 dist，由后端托管
make verify                   # 13 步验收（见下）
```

首次运行需要网络：corepack 拉取 pnpm、Playwright 下载 Chromium（缓存到
`/tmp/pw-browsers`，可用同名环境变量覆盖）。之后可断网重复验收。

## 8. 13 步部署验收（make verify）

`shared/deploy/verify_deploy.sh` 在真实部署路径上执行，失败即停并打印
`[k/13] FAIL 名称` 与复现命令：

| 步骤 | 内容 | 失败含义 |
| --- | --- | --- |
| 1 | 前置检查（.env/Docker/Python 包/Node/corepack/Playwright/端口） | 环境未就绪，退出码 2 |
| 2 | 启动 MySQL 并等待健康 | 容器/端口问题 |
| 3 | `alembic upgrade head` | 迁移脚本或账号权限问题 |
| 4 | 固定种子数据（reset → gen 200/2400 → demo_basic） | 种子 CLI 或数据一致性 |
| 5 | `vite build` + 离线资源检查（dist 无外部 http(s) 引用） | 前端构建失败/引用了外部 CDN |
| 6 | 启动 uvicorn 工厂入口（PID+日志+trap 清理） | 应用工厂/依赖导入失败 |
| 7 | `/api/health` 200、SPA 入口与本地资源 200/content-type、四页 favicon | 静态托管或健康检查异常 |
| 8 | 浏览器检查（四页 × 两视口，console/请求/溢出/字体） | 页面运行时报错或布局溢出 |
| 9 | 令牌审计（0 违规） | 硬编码颜色/尺寸等设计令牌问题 |
| 10 | 页面-数据库抽样（`verify_views --check-pages`） | 页面数据与数据库不一致 |
| 11 | 降级：停 MySQL → health 503、SPA 可打开 → 恢复 → 200 | 降级条/错误处理缺失 |
| 12 | 写证据 `evidence/deploy/run-N/`（deploy-record/browser/token-audit/summary） | 证据缺失 |
| 13 | 清理（停止后端、恢复 MySQL；`--keep` 保留） | 清理失败 |

变体：

```bash
make verify2   # 视觉验收：两分辨率四页截图 + 令牌审计 + 区域清单（evidence/visual/）
make verify3   # 确定性验收：固定种子 3 轮重建 + 跨轮摘要比对
make evidence  # 从已有 run-N/ 重建 summary.md
```

退出码：`0` 全通过；`1` 检查失败；`2` 前置条件缺失。

## 9. 手动验收命令（不经脚本）

```bash
make migrate && make seed && make frontend-build
make api                      # 终端 A
curl -s http://127.0.0.1:8000/api/health
curl -sI http://127.0.0.1:8000/ | head -1         # SPA 入口 200
python -m shared.deploy.offline_assets --dist modules/m5-views-console/frontend/dist
make structure && make boundary && make test
```

## 10. 排障

| 现象 | 排查 |
| --- | --- |
| `make db-up` 超时 | `docker compose ps`、`docker compose logs mysql`，确认 3306 未被占用 |
| 迁移报权限错误 | 使用 `MIGRATE_DATABASE_URL`（`honeypot_migrate`），不要用 app 账号 |
| 页面 404 / 空白 | 确认 `make frontend-build` 已生成 `index.html`，且 uvicorn 工作目录为仓库根 |
| 端口 8000 被占用 | `make api API_PORT=8001`，或 `lsof -i :8000` 后关闭占用进程 |
| Playwright 安装 EPERM | 设置 `PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers`（脚本已默认） |
| corepack EPERM | 设置 `COREPACK_HOME=/tmp/dbh-corepack`（Makefile/验收脚本已默认） |
| `make verify` 在步骤 8/9 失败 | 前端 `verify/*.mjs` 由前端任务交付；失败日志在 `evidence/deploy/run-N/*.log` |
