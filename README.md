# 数据库蜜罐与攻击行为分析系统

基于 MySQL 协议模拟的诱饵数据库、结构化行为日志、可解释规则、攻击者画像与可视化控制台。
本项目是网络空间安全学院数据库课程项目，设计基线与验收口径见
[项目总纲](docs/数据库蜜罐系统项目总纲_1.1_扩充版.md)，规格与设计见
[specs/001-database-honeypot](specs/001-database-honeypot/)。

> **安全边界**：系统仅允许在授权的本机、虚拟机或隔离实验网络运行，严禁暴露到公共互联网；
> 不得连接真实业务数据库或使用真实敏感数据。所有诱饵数据均为人工伪造。

## 功能概览

- **诱饵服务**：模拟 MySQL 8 握手、认证与元数据查询，返回完全虚构的库表数据；写操作只记录不执行。
- **行为捕获**：连接、认证、查询、断开转换为标准事件，按 `session_id` 归集为时间线。
- **数据库设计**：11 张表、正式主外键、CHECK/UNIQUE 约束、4 个核心分析视图、复合索引与 EXPLAIN 对比。
- **规则与画像**：R01–R05 确定性规则（扫描/爆破/踩点/拖库/破坏）生成意图、0–100 风险分与可追溯证据。
- **告警与控制台**：告警去重与已读处置；Vue 3 四页控制台（概览/攻击者/详情/告警）。

## 技术栈

| 部分 | 选型 |
| --- | --- |
| 数据库 | MySQL 8（本地实验使用 8.0.x；CHECK/CTE/窗口函数均支持） |
| 后端 | Python 3.14、FastAPI、SQLAlchemy 2.1 async、asyncmy、Alembic |
| 协议模拟 | mysql-mimic |
| 前端 | Vue 3.5、Vite 8、TypeScript、Element Plus、ECharts |
| 测试 | pytest + 真实 MySQL（不使用数据库 Mock） |
| 部署 | Docker Compose（MySQL 固定隔离网段 172.28.0.0/24） |

## 快速开始

```bash
# 1. 配置环境（口令均为 TEST-ONLY 占位，仅用于隔离实验）
cp .env.example .env

# 2. 启动 MySQL 并安装后端依赖
make setup

# 3. 数据库迁移（建表、视图、索引、规则种子）
make migrate
make seed

# 4. 启动后端 API（另一个终端）
make api

# 5. 启动诱饵服务（另一个终端）
make honeypot

# 6. 构建并访问控制台
make frontend-build        # 产物由后端托管：http://127.0.0.1:8000
# 或开发模式：make dev     # http://127.0.0.1:5173
```

## 演示路径

1. 用 MySQL 客户端连接诱饵：`mysql -h127.0.0.1 -P3307 -udemo_reader -p --default-auth=mysql_native_password`
2. 执行 `SHOW DATABASES; SHOW TABLES; DESCRIBE users; SELECT * FROM users LIMIT 5;` 观察伪造数据与踩点标签。
3. 执行 `DROP TABLE users;` 观察权限不足与破坏性操作记录。
4. 打开控制台查看概览、攻击者详情、会话时间线与告警。
5. `make demo` 导入固定合成样本，复现 R04/R05 与告警；`make reset` 重置演示数据。

完整演示脚本见 [docs/demo-script.md](docs/demo-script.md)，测试矩阵见 [docs/test-plan.md](docs/test-plan.md)。

## 目录结构

```text
backend/       FastAPI 应用、诱饵服务、迁移、测试
frontend/      Vue 3 控制台
db/init/       MySQL 容器初始化（库与四类账号）
db/explain/    EXPLAIN 对比记录
docs/          中文项目文档
specs/         Spec Kit 规格、计划、数据模型、契约与任务
scripts/       授权模拟器与运维脚本
compose.yaml   MySQL 8 编排
Makefile       常用命令
```

## 数据库账号与安全

四类账号职责分离、最小权限：`honeypot_migrate`（DDL）、`honeypot_app_rw`（DML）、
`honeypot_app_ro`（只读）、`honeypot_backup`（备份）。业务账号无 DDL 权限；审计表仅追加。
迁移完成后可执行 `./scripts/apply_table_grants.sh honeypot_dev` 收紧表级权限。

## 测试

```bash
make test          # 后端单元/集成/接口测试（需要 db-up）
make lint          # ruff 静态检查
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 连接 3307 报 1045 | 确认 `.env` 中诱饵账号口令；客户端加 `--default-auth=mysql_native_password` |
| 控制台无数据 | 先产生诱饵流量或 `make demo`；确认 API 已启动 |
| 迁移报 Can't locate revision | 检查 `backend/migrations/versions` 是否完整；重装依赖后重试 |
| 权限不足 1142/1044 | 执行 `scripts/apply_table_grants.sh` 或检查账号 |

## 许可与声明

课程项目，仅用于授权教学与演示。规则阈值为演示口径，不代表生产安全基线。
