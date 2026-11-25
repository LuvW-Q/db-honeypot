# M1 事务写入与接口集成

M1 是唯一拥有**写路径**与**对外 HTTP 契约**的模块：诱饵事件经事务写入、规则分析、
画像派生与告警去重；控制台只读查询全部由 M1 的 `/api/*` 提供，并由同一个 FastAPI 进程
托管前端构建产物（单地址部署）。

| 项目 | 内容 |
| --- | --- |
| 包名 | `m1_transaction_integration`（安装名 `db-honeypot`） |
| 对外门面 | [`m1_transaction_integration/public.py`](m1_transaction_integration/public.py) |
| 拥有产物 | Alembic 迁移、数据库账号权限、事务/幂等入口、`/api/*` 路由、演示重置 CLI |
| 依赖方向 | M1 → `shared`、M4 `public.py`（规则分析在同一事务内调用）；**不** import M2/M3/M5 内部模块 |
| 契约 | [`contracts/module-boundaries.md`](../../specs/002-ui-console-modularization/contracts/module-boundaries.md) §2、[`contracts/api.md`](../../specs/002-ui-console-modularization/contracts/api.md) |

---

## 1. 目录与职责

```text
m1-transaction-integration/
├── m1_transaction_integration/
│   ├── public.py              # 跨模块写入口：ingest_event / ingest_events_in_session / reset_demo
│   ├── api/
│   │   ├── app.py             # create_app()：CORS、异常、路由、StaticFiles 托管 dist
│   │   ├── deps.py            # 只读/读写会话依赖（honeypot_app_ro / honeypot_app_rw）
│   │   ├── errors.py          # 统一错误结构（含 422 校验错误）
│   │   └── routes/            # overview / attackers / sessions / alerts / rules / ai
│   ├── services/
│   │   ├── ingest.py          # 单事件事务：落库 → M4 分析 → 审计，失败整体回滚
│   │   ├── audit.py           # audit_log 仅追加写入
│   │   ├── reset.py           # 演示数据重置（显式按依赖删除，不用 TRUNCATE）
│   │   ├── session_manager.py # 会话生命周期与计数
│   │   ├── network_scope.py   # 来源网段标签派生（002 新增）
│   │   ├── time_windows.py    # overview/trend 时间窗（002 新增）
│   │   └── ai_assistant.py    # 可选的 AI 摘要（无外网时禁用）
│   ├── repositories/          # overview / attacker / alert / session / audit 只读查询
│   ├── schemas/api.py         # Pydantic 响应模型（含 002 扩展端点）
│   └── cli/                   # reset_demo / verify_transaction
├── migrations/versions/       # 0001 建表 → 0002 视图 → 0003 索引 → 0004 规则种子
├── db/
│   ├── init/01-init-databases.sh   # 初始化 dev/demo/test 库与四类账号
│   └── grants/apply_table_grants.sh # 表级最小权限（FR-068/082）
├── tests/{api,integration}/   # 接口契约、迁移、幂等、事务回滚
└── evidence/                  # 事务/权限/接口证据
```

## 2. 对外契约

### 2.1 跨模块 Python 门面（`public.py`）

| 函数 | 语义 |
| --- | --- |
| `ingest_event(event: CapturedEvent) -> IngestResult` | 写一条事件：独立事务内落库 → M4 规则分析/派生 → 审计；返回写入与会话摘要 |
| `ingest_events_in_session(session, events)` | 在一个已开启事务中批量写入（M2 模拟器/导入样本使用） |
| `reset_demo(operator)` | 单事务清理观测数据并写 `audit_log`，保留规则与诱饵种子 |

### 2.2 HTTP 接口（`/api/*`，只读为主）

| 接口 | 说明 |
| --- | --- |
| `GET /api/health` | 进程/数据库/诱饵监听状态；数据库不可用返回 503 `degraded` |
| `GET /api/overview?range=all\|7d\|24h` | KPI 卡与概览统计（002 新增 `range`） |
| `GET /api/trend?days=7` | 每日趋势；002 新增 `hit_*` 命中序列 |
| `GET /api/attackers` | 攻击者列表：分页、`q` 搜索、风险档/意图/排序（`sort=total_connections\|risk_score` 白名单） |
| `GET /api/attackers/summary` | 攻击者统计（002 新增） |
| `GET /api/attackers/{ip}` | 画像详情：`avg_session_seconds`、`auth_success_count`、`high_risk_op_count`、`network_scope` |
| `GET /api/sessions/{id}/timeline` | 会话事件时间线（支持类型过滤） |
| `GET/PATCH /api/alerts`、`/api/alerts/{id}` | 告警列表与**唯一写操作**：标记已读 |
| `GET /api/alerts/summary` | 未读/等级统计（002 新增；`from`/`to` 必须成对） |
| `GET/PUT /api/rules`、`/api/rules/effectiveness` | 规则列表/效果统计；PUT 生成新规则版本 |

完整字段、状态码与真实响应样例见 [`contracts/api.md`](../../specs/002-ui-console-modularization/contracts/api.md)
与 [`evidence/api.md`](evidence/api.md)。

## 3. 事务、幂等与权限

- **单事务写入**：`IngestService.ingest` 在一个 `async with session.begin()` 内完成事件落库、
  规则命中、画像/意图更新、告警去重与审计；任一步异常整体回滚（证据
  [`evidence/transaction.md`](evidence/transaction.md) 的三组 before/after 快照）。
- **幂等**：`attack_log.event_uuid`、`rule_hits(event_id,rule_id,rule_version)`、
  `alerts.dedup_key` 三层唯一约束保证重复导入不新增；证据见 M2/M4 证据索引。
- **四类账号**：`honeypot_migrate`（DDL）、`honeypot_app_rw`（写 + 只读）、
  `honeypot_app_ro`（仅 SELECT 视图/表）、`honeypot_backup`（导出）；权限矩阵与越权被拒
  实测见 [`evidence/grants.md`](evidence/grants.md)。
- **表级授权**：`db/grants/apply_table_grants.sh <db>` 收紧到具体表/列（`app_rw` 不可
  DELETE `detection_rules`，`app_ro` 不可读 `password_hash`）。

## 4. 复现命令

仓库根执行，MySQL 用 `make db-up` 启动（容器 `dbhoneypot-mysql`）：

```bash
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console

# 建库/迁移/种子
make db-up && make migrate && make seed

# 事务提交与回滚（真实库，只增删本次测试数据）
/tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction

# 接口冒烟（需服务已在 :8000）
make api            # 终端 A：uvicorn --factory m1_transaction_integration.api.app:create_app
curl -s http://127.0.0.1:8000/api/health

# 接口契约测试（既有 82 例 + 002 扩展 37 例）
/tmp/dbh-venv/bin/python -m pytest modules/m1-transaction-integration/tests -q
```

**期望输出**：`verify_transaction` 退出码 0、`clean=true`；pytest 全绿；`/api/health` 返回
`status=ok`、`database.status=ok`。

## 5. 验收证据

索引见 [`evidence/README.md`](evidence/README.md)：

- [`evidence/transaction.md`](evidence/transaction.md)：正常提交/注入失败/清理三组快照，`clean=true`；
- [`evidence/grants.md`](evidence/grants.md)：四类账号 `SHOW GRANTS` 矩阵与 1142 实测；
- [`evidence/api.md`](evidence/api.md)：10 个接口状态码与真实响应（含 422/404 分支）；
- [`evidence/api-extensions.md`](evidence/api-extensions.md)：002 扩展端点的 EXPLAIN 与冒烟。

## 6. 边界与限制

- **不拥有协议**：诱饵监听与事件采集归 M2；M1 只接收已标准化的 `CapturedEvent`。
- **不拥有分析规则**：规则/评分/去重逻辑归 M4，M1 只调用 `m4_rules_derived.public`。
- **不拥有视图口径**：四个分析视图的用途与 SQL 归 M5（`views/queries.sql`），M1 只读消费。
- **唯一写操作**：控制台侧只允许 PATCH 告警已读；其余接口只读，404/422 分支有测试覆盖。
- **演示数据不伪装“今日”**：种子时间为固定日期，`overview` 的 24h/7d 窗口可能为 0，
  这是真实数据而不是缺陷（见 `docs/test-plan.md` 说明）。

## 7. 最近验证

| 项 | 结果 | 时间 |
| --- | --- | --- |
| `pytest modules/m1-transaction-integration/tests` | 通过（含 37 例 002 扩展） | 2026-11-25 |
| `verify_transaction` | 退出码 0，`clean=true` | 2026-11-25 |
| `ruff check modules/m1-transaction-integration` | All checks passed | 2026-11-25 |
| 接口冒烟 | `/api/health` 200；overview/trend/attackers/alerts/rules 均 200 | 2026-11-25 |
