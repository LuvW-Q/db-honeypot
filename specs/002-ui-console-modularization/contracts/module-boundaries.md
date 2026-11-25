# 模块边界与公开契约

**Feature**: `002-ui-console-modularization` | **Date**: 2026-11-25

本文件是 FR-114 至 FR-123 的实施契约：模块目录、Python 包、公开入口、允许依赖矩阵、
文件搬迁映射与自动化边界检查规则。**文档与检查脚本必须逐条一致**，修改本文件时必须
同步修改 `shared/deploy/boundary_check.py` 的允许表并更新检查用例。

---

## 1. 目录与包命名

| 目录（仓库根） | Python 包 | 入口 |
| --- | --- | --- |
| `shared/` | `shared`（`shared/shared/`） | `shared.deploy.*`、`shared.config`、`shared.db`、`shared.models`、`shared.events`、`shared.utils`、`shared.data` |
| `modules/m1-transaction-integration/` | `m1_transaction_integration` | `uvicorn m1_transaction_integration.api.app:create_app --factory`；`python -m m1_transaction_integration.cli.*` |
| `modules/m2-decoy-capture/` | `m2_decoy_capture` | `python -m m2_decoy_capture.server`；`python -m m2_decoy_capture.cli.*` |
| `modules/m3-er-constraints/` | 无（文档/SQL/测试） | `python -m m3_er_constraints` 不存在；入口为脚本与测试 |
| `modules/m4-rules-derived/` | `m4_rules_derived` | 由 M1 调用 `m4_rules_derived.public`；独立测试运行 |
| `modules/m5-views-console/` | `m5_views_console` | `python -m m5_views_console.cli.verify_views`；前端 `frontend/` |

命名规则：目录名严格使用 spec 附录 A 的连字符形式；Python 包名在连字符位置改为
下划线，**不额外加前缀或后缀**。

---

## 2. 公开入口契约

### 2.1 `shared`（平台能力，对所有模块公开）

| 模块 | 公开符号 | 说明 |
| --- | --- | --- |
| `shared.config` | `settings`、`Settings` | 环境变量与 `.env` 加载；`REPO_ROOT`/`WEB_DIST_DIR` 解析 |
| `shared.db` | `get_rw_session`、`get_ro_session`、`get_rw_engine`、`get_ro_engine`、`ping` | 读写/只读会话工厂；事务边界由调用方提交 |
| `shared.models` | 全部表模型与 `Base` | schema 契约；其他模块禁止自行定义映射 |
| `shared.events` | `StandardEvent`、`build_event`、`normalize_sql` | 标准事件契约与归一化 |
| `shared.utils` | `mask_username`、`truncate_text`、`derive_statement_type`、`network_scope` | 脱敏、截断、语句类型、IP 归属派生 |
| `shared.data` | `fetch_one`、`fetch_all`、`fetch_page`、`build_in_clause`、`parse_time_range`、`validate_*` | 通用只读查询与参数校验工具 |
| `shared.deploy` | `verify_deploy`、`boundary_check`、`check_structure`、`demo` | 构建/部署/边界/结构检查脚本 |

### 2.2 M1 对外公开面（`m1_transaction_integration.public`）

```python
async def ingest_event(event: StandardEvent) -> IngestResult:
    """唯一事件写入入口：单事务内写会话/事件/审计并调用 M4 分析。

    幂等键为 event.event_uuid（唯一约束兜底）；重试安全。
    M2 只调用本函数，不直接使用数据库会话。
    """

async def reset_demo(operator: str) -> ResetResult: ...
```

- FastAPI 应用工厂：`m1_transaction_integration.api.app:create_app`（供 uvicorn）。
- CLI：`m1_transaction_integration.cli.verify_transaction`、
  `m1_transaction_integration.cli.reset_demo`。
- 迁移：`modules/m1-transaction-integration/migrations/`（由根 `alembic.ini` 指向）。
- **禁止** M2/M4/M5 导入 M1 的 `api`、`repositories`、`services`、`schemas` 子模块。

### 2.3 M4 对外公开面（`m4_rules_derived.public`）

```python
async def analyze_and_derive(
    session: AsyncSession, event: StandardEvent, event_id: int
) -> AnalysisResult:
    """在同一事务内执行 R01–R05 判定、派生更新、告警去重；不提交事务。"""

async def list_rules(session: AsyncSession, *, enabled: bool | None = None) -> list[RuleView]: ...
async def update_rule(session: AsyncSession, *, rule_code: str, payload: RuleUpdate) -> RuleView: ...
```

- M1 只能在既有事务内调用 `analyze_and_derive`，提交由 M1 负责（宪法四）。
- M1 的 `/api/rules` 路由通过 `list_rules`/`update_rule` 访问规则领域，禁止直接
  导入 `m4_rules_derived.repositories`。

### 2.4 M2 对外公开面（`m2_decoy_capture.public`）

```python
async def serve(settings: Settings) -> None:
    """启动 MySQL 协议诱饵服务（asyncio），事件经 M1.public.ingest_event 写入。"""
```

- CLI：`simulate_traffic`、`import_samples`、`gen_demo_data`、`explain_diff`、
  `seed_decoy`（模块路径 `m2_decoy_capture.cli.*`）。
- 数据文件：`m2_decoy_capture.samples.catalog`（固定样本组 `demo_basic`、
  `recon_only`）。

### 2.5 M5 对外公开面

- `views/queries.sql`：四个视图的"用途 → 页面 → 口径"对照与可执行查询（数据文件，
  非 DDL；DDL 仍由 M1 迁移 0002 持有）。
- CLI：`python -m m5_views_console.cli.verify_views`（只读）。
- 构建产物：`frontend/dist/`（由 M1 的静态托管按 `WEB_DIST_DIR` 提供）。
- 验证工具：`frontend/verify/*.mjs`（Node，不属于 Python 包）。

### 2.6 M3 对外公开面

- `er/schema.mmd`：ER 源文件（Mermaid），与 DDL 一致。
- `constraints/verify_constraints.sql`：主外键、CHECK、UNIQUE 的正反样例。
- `constraints/catalog.md`：约束目录（由 `tools/introspect_constraints.py` 从
  `information_schema` 生成/对账）。
- 测试：`tests/integration/test_constraints_fk.py`。

---

## 3. 依赖矩阵（自动化检查的允许表）

允许的跨模块导入边（其余一律违规）：

| 源 | 目标 | 允许的导入前缀 |
| --- | --- | --- |
| M1 | shared | `shared` |
| M1 | M4 | `m4_rules_derived.public` |
| M2 | shared | `shared` |
| M2 | M1 | `m1_transaction_integration.public` |
| M3 | shared | `shared`（仅 `tests/` 与 `tools/` 内） |
| M4 | shared | `shared` |
| M5 | shared | `shared`（仅 `cli/`、`tests/`） |
| 任意 | 自身 | 自身包内任意子模块 |

**硬性禁止**：

1. `shared` 导入任何 `m1_`…`m5_` 包；
2. 任意模块导入其他模块的 `api`/`repositories`/`services`/`schemas`/`migrations`
   子模块（只能经 §2 的公开入口）；
3. 反向依赖（M4 → M1、M1 → M2、M5 → M2/M3/M4 的 Python 导入）；
4. 旧包名残留：`app.`、`backend.`、`app.cli`、`frontend/` 源码引用 `../backend`；
5. 循环导入（含同包内环）。

M5 前端与 M1 的协作是 HTTP 契约（`/api`），不产生 Python 导入边；M5 的
`verify_views` 经 `shared.db` 只读连接执行视图查询，不导入 M1。

---

## 4. 文件搬迁映射（`git mv` 保留历史）

### 4.1 平台与共享

| 既有路径 | 目标路径 |
| --- | --- |
| `backend/app/config.py` | `shared/shared/config.py` |
| `backend/app/logging.py` | `shared/shared/logging.py` |
| `backend/app/db/base.py`、`db/session.py` | `shared/shared/db/` |
| `backend/app/models/*` | `shared/shared/models/` |
| `backend/app/schemas/common.py` | `shared/shared/schemas/common.py` |
| `backend/app/schemas/events.py` | `shared/shared/events/schema.py` |
| `backend/app/services/event_builder.py` | `shared/shared/events/builder.py` |
| `backend/app/utils/*` | `shared/shared/utils/` |
| `backend/app/repositories/query_repo.py` | `shared/shared/data/query.py` |
| `backend/tests/conftest.py` | `conftest.py`（仓库根，全部测试共用） |
| `backend/tests/support.py` | `tests/support.py` |
| `backend/tests/unit/test_masking.py`、`test_sql_norm.py`、`test_event_builder.py` | `shared/tests/unit/` |
| `scripts/demo.sh` | `shared/deploy/demo.sh` |
| `backend/pyproject.toml`（依赖与工具配置） | `pyproject.toml`（仓库根；`tool.uv.package = true`） |
| `backend/alembic.ini` | `alembic.ini`（仓库根；`script_location = modules/m1-transaction-integration/migrations`） |

### 4.2 M1 事务写入与接口集成

| 既有路径 | 目标路径 |
| --- | --- |
| `backend/app/main.py` | `m1_transaction_integration/api/app.py` |
| `backend/app/api/deps.py`、`errors.py`、`routes/*` | `m1_transaction_integration/api/` |
| `backend/app/schemas/api.py` | `m1_transaction_integration/schemas/api.py` |
| `backend/app/repositories/{alert,attacker,audit,overview,session}_repo.py` | `m1_transaction_integration/repositories/` |
| `backend/app/services/{ingest,audit,reset,session_manager,ai_assistant}.py` | `m1_transaction_integration/services/` |
| `backend/app/cli/{verify_transaction,reset_demo}.py` | `m1_transaction_integration/cli/` |
| `backend/migrations/**` | `modules/m1-transaction-integration/migrations/` |
| `db/init/01-init-databases.sh` | `modules/m1-transaction-integration/db/init/01-init-databases.sh` |
| `scripts/apply_table_grants.sh` | `modules/m1-transaction-integration/db/grants/apply_table_grants.sh` |
| `backend/tests/api/*` | `modules/m1-transaction-integration/tests/api/` |
| `backend/tests/integration/{test_transaction_rollback,test_idempotency,test_migrations}.py` | `modules/m1-transaction-integration/tests/integration/` |

### 4.3 M2 诱饵交互与事件采集

| 既有路径 | 目标路径 |
| --- | --- |
| `backend/app/honeypot/*` | `m2_decoy_capture/`（`server/session/auth/emitter/fake_catalog`） |
| `backend/app/cli/{simulate_traffic,import_samples,gen_demo_data,explain_diff}.py` | `m2_decoy_capture/cli/` |
| `backend/app/cli/samples/catalog.py` | `m2_decoy_capture/samples/catalog.py` |
| `backend/app/cli/seed.py` | 拆分：诱饵数据部分 → `m2_decoy_capture/cli/seed_decoy.py`；规则种子仍由迁移 `0004_seed_rules.py`（M1）承担，原文件删除并在 M2 README 说明 |
| `db/explain/*.json` | `modules/m2-decoy-capture/evidence/explain/` |
| `docs/explain-indexes.md` | `modules/m2-decoy-capture/docs/explain-indexes.md`（`docs/` 保留跳转链接） |
| `backend/tests/unit/test_fake_catalog.py` | `modules/m2-decoy-capture/tests/unit/` |

### 4.4 M3 ER 与完整性约束

| 既有路径 | 目标路径 |
| --- | --- |
| `docs/database-design.md` 内的 Mermaid ER 源 | `modules/m3-er-constraints/er/schema.mmd`（文档改为引用该文件） |
| `specs/001-database-honeypot/data-model.md` 的约束清单 | `modules/m3-er-constraints/constraints/catalog.md`（以 `information_schema` 反查对账） |
| `backend/tests/integration/test_constraints_fk.py` | `modules/m3-er-constraints/tests/integration/` |
| 约束正反样例 SQL（新建） | `modules/m3-er-constraints/constraints/verify_constraints.sql` |

### 4.5 M4 规则与派生数据

| 既有路径 | 目标路径 |
| --- | --- |
| `backend/app/services/{analysis,risk,alerts}.py` | `m4_rules_derived/` |
| `backend/app/services/rules/*` | `m4_rules_derived/rules/` |
| `backend/app/repositories/rule_repo.py` | `m4_rules_derived/repositories/rule_repo.py` |
| `backend/tests/unit/{test_rules,test_risk}.py` | `modules/m4-rules-derived/tests/unit/` |
| `backend/tests/integration/test_analysis_pipeline.py` | `modules/m4-rules-derived/tests/integration/` |
| `backend/tests/api/test_rules.py` | `modules/m4-rules-derived/tests/api/`（经 M1 路由的集成测试） |

### 4.6 M5 分析视图与控制台

| 既有路径 | 目标路径 |
| --- | --- |
| `frontend/**` | `modules/m5-views-console/frontend/**` |
| `backend/tests/integration/test_views.py` | `modules/m5-views-console/tests/integration/` |
| 视图口径查询（新建） | `modules/m5-views-console/views/queries.sql` |
| 视图核对 CLI（新建） | `modules/m5-views-console/cli/verify_views.py` |
| 浏览器检查/令牌审计（新建） | `modules/m5-views-console/frontend/verify/` |
| 视觉基线/部署记录（新建） | `modules/m5-views-console/evidence/{visual,deploy,sql-ui}/` |

### 4.7 根级保留与新增

- 保留：`Makefile`、`compose.yaml`、`.env.example`、`README.md`、`docs/`、
  `ux/`（设计输入）、`specs/`。
- 新增：`pyproject.toml`、`alembic.ini`、`conftest.py`、`tests/`（跨模块契约测试）、
  `shared/`、`modules/`。
- 删除：`backend/`（搬迁完成后）、`scripts/`（内容并入 `shared/deploy/` 或 M1/M2）。

---

## 5. 数据模型变更流程（FR-120）

1. **M3** 更新 `er/schema.mmd` 与 `constraints/catalog.md`，并在证据目录记录评审结论；
2. **M1** 新增 Alembic 迁移 + `downgrade`，执行空库/存量库往返演练并留下快照；
3. **M2/M4/M5** 适配：M2 调整事件写入字段、M4 调整规则/派生、M5 更新视图口径与页面；
4. 宪法门禁：ER/关系模式/DDL 三者一致、迁移可往返、集成测试通过后合并。

本 feature **不包含**步骤 1–3 的 DDL 变更；本流程用于防止实现期私自改表。

---

## 6. 边界检查脚本契约

`shared/deploy/boundary_check.py`：

```text
用法: python -m shared.deploy.boundary_check [--json] [--paths modules shared]
退出码: 0 无违规；1 存在违规；2 扫描失败（语法错误等）
输出:
  {
    "scanned_files": 87,
    "violations": [
      {"file": "modules/m1-transaction-integration/.../x.py",
       "line": 12, "import": "m2_decoy_capture.server",
       "rule": "cross_module_internal", "message": "..."}
    ],
    "legacy_imports": [],
    "result": "pass"
  }
```

检查项：

1. 允许表（§3）逐行实现；未知目标包（如第三方）放行；
2. `import x` / `from x import y` / 相对导入统一解析为绝对模块名；
3. 扫描 `shared/`、`modules/**` 的 `.py` 文件；`tests/` 目录使用相同允许表，
   但允许导入自身包与 `shared`；
4. 旧导入扫描：`app`、`backend`、`app.cli`、`backend.app` 前缀出现即违规；
5. 循环依赖检测：模块级导入图做 DFS，报告环路径（同包内部允许）；
6. 自测：`tests/test_boundary_check.py` 构造 8 类违规样例（内外依赖、反向、
   旧前缀、环）断言 `exit 1`，并断言当前仓库 `exit 0`（SC-022）。

`make boundary` = `python -m shared.deploy.boundary_check --json`；合并门禁要求
`violations == []` 且 `result == "pass"`。
