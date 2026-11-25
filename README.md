# 数据库蜜罐与攻击行为分析系统

基于 MySQL 协议模拟的诱饵数据库、结构化行为日志、可解释规则、攻击者画像与可视化控制台。
本项目是网络空间安全学院数据库课程项目，设计基线与验收口径见
[项目总纲](docs/数据库蜜罐系统项目总纲_1.1_扩充版.md)，模块化重构规格见
[specs/002-ui-console-modularization](specs/002-ui-console-modularization/)。

> **安全边界**：系统仅允许在授权的本机、虚拟机或隔离实验网络运行，严禁暴露到公共互联网；
> 不得连接真实业务数据库或使用真实敏感数据。所有诱饵数据均为人工伪造。

## 功能概览

- **诱饵服务**：模拟 MySQL 8 握手、认证与元数据查询，返回完全虚构的库表数据；写操作只记录不执行。
- **行为捕获**：连接、认证、查询、断开转换为标准事件，按 `session_id` 归集为时间线。
- **数据库设计**：11 张表、正式主外键、CHECK/UNIQUE 约束、4 个核心分析视图、复合索引与 EXPLAIN 对比。
- **规则与画像**：R01–R05 确定性规则（扫描/爆破/踩点/拖库/破坏）生成意图、0–100 风险分与可追溯证据。
- **告警与控制台**：告警去重与已读处置；Vue 3 四页控制台（概览/攻击者/详情/告警），
  深/浅双主题，默认跟随系统外观，页头按钮可实时切换。

## 技术栈

| 部分 | 选型 |
| --- | --- |
| 数据库 | MySQL 8（容器固定 `mysql:8.0`，可用 `MYSQL_IMAGE` 覆盖；CHECK/CTE/窗口函数均支持） |
| 后端 | Python 3.11+、FastAPI、SQLAlchemy 2.1 async、asyncmy、Alembic、mysql-mimic |
| 前端 | Vue 3.5、Vite 8、TypeScript、Vue Router、Tailwind CSS 3；字体/图标全部本地打包 |
| 测试 | pytest + 真实 MySQL（不使用数据库 Mock）；部署验收用 Playwright |
| 部署 | 容器 MySQL（隔离网段 172.28.0.0/24）+ 宿主后端统一托管前端产物（单地址） |

## 目录结构（模块化重构后）

```text
shared/                             共享包（包根即 shared/，含部署工具链 shared/deploy/）
  config.py, db/, models/, events/, schemas/, utils/, data/
  deploy/                           结构/边界检查器、13 步部署验收脚本、演示脚本
modules/
  m1-transaction-integration/       事务写入与 API 集成（唯一 Alembic 迁移、唯一应用工厂）
  m2-decoy-capture/                 诱饵交互与事件采集（模拟器、样本导入）
  m3-er-constraints/                ER 与完整性约束（仅文档/SQL/测试，无运行时包）
  m4-rules-derived/                 规则、派生数据、攻击者画像
  m5-views-console/                 分析视图、CLI 核对与控制台（frontend/）
tests/                              跨模块共享夹具（根 conftest.py 准备 honeypot_test；用例在各模块内）
docs/                               中文项目文档（部署模型、演示脚本、测试矩阵等）
specs/                              Spec Kit 规格、计划、数据模型、契约与任务
compose.yaml                        MySQL 8 编排（数据卷 + 四类账号初始化）
Makefile                            统一命令入口（见 `make help`）
```

> 旧 `backend/`、根 `frontend/`、`scripts/` 已全部迁入 `shared/` 与 `modules/`；
> `make structure` 会检查并阻止旧布局残留、旧导入前缀（`app.`/`backend.`）与写死本机路径。

## 快速开始

```bash
# 1. 配置环境（口令均为 TEST-ONLY 占位，仅用于隔离实验）
cp .env.example .env

# 2. 安装依赖（Python .venv + 前端 pnpm 依赖）
make install            # 创建 .venv 并安装 dev 依赖；有 uv 时自动走 uv sync
make frontend-install   # corepack pnpm install（锁定 pnpm 版本）

# 3. 启动 MySQL 容器
make db-up              # 首次启动自动执行 modules/m1-transaction-integration/db/init 建库与四类账号

# 4. 数据库迁移与固定种子数据
make migrate            # alembic upgrade head（迁移脚本在 M1 模块内）
make seed               # reset → gen(200 会话/2400 事件) → 导入 demo_basic 样本

# 5. 启动后端 API（另一个终端）
make api                # uvicorn --factory m1_transaction_integration.api.app:create_app

# 6. 构建并访问控制台（产物由后端统一托管，单地址）
make frontend-build     # 输出到 modules/m5-views-console/frontend/dist
open http://127.0.0.1:8000

# 7. 启动诱饵服务（另一个终端，模拟 MySQL 3307）
make honeypot
```

四页控制台均使用 hash 路由（刷新/直接打开不依赖服务器 rewrite）：

| 页面 | 路由 |
| --- | --- |
| 首页概览 | `http://127.0.0.1:8000/#/` |
| 攻击者列表 | `http://127.0.0.1:8000/#/attackers` |
| 攻击者详情与时间线 | `http://127.0.0.1:8000/#/attackers/<ip>` |
| 告警列表 | `http://127.0.0.1:8000/#/alerts` |

健康检查：`curl -s http://127.0.0.1:8000/api/health`（数据库不可用时返回 503 与降级状态）。

前端独立开发模式：`make frontend-dev`（Vite 5173，通过 `/api` 代理到 8000）。

## 演示与验收

```bash
make demo          # 一键演示：固定样本导入 → 诱饵服务 → 授权模拟器 → 概览摘要
make reset-demo    # 仅重置演示数据（清空观测数据）

make structure     # 结构门禁：旧布局残留/包命名/必需文件/Makefile 变量一致性
make boundary      # 边界门禁：依赖矩阵、公开门面、旧前缀、跨包循环
make test          # 全仓 pytest（根 tests/ + 各模块 tests/ + shared/deploy/tests）
make lint          # ruff 静态检查

make verify        # 13 步部署验收（真实构建产物 + 真实浏览器 + 降级；失败即停）
make verify2       # 视觉验收：两分辨率四页截图 + 令牌审计 + 区域清单
make verify3       # 确定性验收：固定种子 3 轮重建 + 跨轮摘要比对
make evidence      # 从已有证据重建 summary.md
```

验收证据写入 `modules/m5-views-console/evidence/deploy/run-N/`（`deploy-record.json`、
`browser.json`、`token-audit.json`、`backend.log`、截图与 `summary.md`）。

## 部署模型（T006）

- **拓扑**：MySQL 跑在 Docker 容器（隔离网段 `172.28.0.0/24`，仅绑定 `127.0.0.1:3306`）；
  后端 uvicorn 跑在宿主，统一托管前端产物，**只暴露一个地址** `http://127.0.0.1:8000`。
- **数据卷**：`dbhoneypot_mysql_data`（命名卷）保存 MySQL 数据；`make db-down` 保留卷，
  `docker compose down -v` 才会清空，重启后数据仍在。
- **账号隔离**：初始化脚本创建四类最小权限账号（见下一节），业务运行只用 `app_rw`/`app_ro`。
- **库隔离**：开发库 `honeypot_dev`、测试库 `honeypot_test`、演示库 `honeypot_demo` 相互独立；
  `TEST_DATABASE_URL` 固定指向 `honeypot_test`，根 `conftest.py` 只在该库建/清表，
  不影响开发库与演示数据（SC-028）。
- **离线/首次运行**：`corepack` 拉取 pnpm、Playwright 首次下载浏览器需要网络；之后
  `make verify` 的离线资源检查会断言构建产物不含任何外部 `http(s)` 资源引用（字体/图标/Logo 全本地）。

完整说明（端口、环境变量、数据卷生命周期、备份与排障）见
[docs/deployment.md](docs/deployment.md)。

## 演示路径

1. 用授权模拟器连接诱饵（真实 MySQL 协议，来源 127.0.0.1）：
   `PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console .venv/bin/python -m m2_decoy_capture.cli.simulate_traffic --target 127.0.0.1:3307 --rounds 3`
   （若本机已装 mysql 客户端：`mysql -h127.0.0.1 -P3307 -udemo_reader -p --default-auth=mysql_native_password`）
2. 模拟器在每轮会话内依次执行 `SHOW DATABASES; SHOW TABLES; DESCRIBE users; SELECT ...`
   等读操作，再执行 `UPDATE/DELETE/INSERT/DROP/TRUNCATE`——观察伪造数据、踩点标签与
   写操作被拒的 `1142`（诱饵层拒绝，数据库无真实变更）。
3. 打开控制台查看概览、攻击者详情、会话时间线与告警。
4. `make demo` 导入固定合成样本，复现 R04/R05 与告警。

完整演示脚本见 [docs/demo-script.md](docs/demo-script.md)，测试矩阵见 [docs/test-plan.md](docs/test-plan.md)。

## 数据库账号与安全

四类账号职责分离、最小权限：`honeypot_migrate`（DDL）、`honeypot_app_rw`（DML）、
`honeypot_app_ro`（只读）、`honeypot_backup`（备份）。业务账号无 DDL 权限；审计表仅追加。
迁移完成后可执行 `bash modules/m1-transaction-integration/db/grants/apply_table_grants.sh honeypot_dev`
收紧表级权限。

## 测试

```bash
make db-up && make migrate && make seed   # 测试库由根 conftest 自动准备
make test                                 # pytest（真实 MySQL，不使用 Mock）
make lint                                 # ruff
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 连接 3307 报 1045 | 确认 `.env` 中诱饵账号口令；客户端加 `--default-auth=mysql_native_password` |
| 控制台无数据 | 先产生诱饵流量或 `make demo`；确认 API 已启动且 `make seed` 已执行 |
| 迁移报 Can't locate revision | 检查 `modules/m1-transaction-integration/migrations/versions` 是否完整 |
| 权限不足 1142/1044 | 执行 `modules/m1-transaction-integration/db/grants/apply_table_grants.sh` 或检查账号 |
| `make verify` 在浏览器步骤失败 | 先 `make frontend-build` 并确认 Playwright 浏览器已安装（`/tmp/pw-browsers`） |
| 端口 8000 被占用 | `make api API_PORT=8001`，或关闭占用进程后重跑 `make verify` |

## 许可与声明

课程项目，仅用于授权教学与演示。规则阈值为演示口径，不代表生产安全基线。
