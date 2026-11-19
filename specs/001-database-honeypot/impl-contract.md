# 实现接口契约（后端并行开发用）

**用途**：规定各后端工作流之间的模块边界与函数签名，避免并行开发时接口漂移。
**权威来源**：spec.md、plan.md、data-model.md、contracts/；本文件只约定“谁调用谁”。

## 1. 模块边界

| 模块 | 负责目录 | 不得承担 |
| --- | --- | --- |
| 数据层 | `backend/migrations/`、`backend/app/models/` | 业务规则、HTTP 协议 |
| 捕获层 | `backend/app/honeypot/` | 风险评分、告警判定 |
| 存储层 | `backend/app/services/ingest.py`、`session_manager.py`、`audit.py` | 协议解析 |
| 分析层 | `backend/app/services/rules/`、`analysis.py`、`risk.py`、`alerts.py` | 修改原始日志 |
| 查询层 | `backend/app/repositories/`、`backend/app/api/routes/` | 绕过 ORM 直接改文件 |
| 前端 | `frontend/src/` | 保存完整明文口令 |

## 2. 关键函数签名（必须保持稳定）

```python
# backend/app/services/event_builder.py
def new_event_uuid() -> str: ...
def new_session_id() -> str: ...
def normalize_sql(sql: str | None) -> str | None: ...
def build_event(
    *,
    event_type: EventType,
    session_id: str,
    source_ip: str,
    source_port: int | None = None,
    username: str | None = None,
    credential_test_id: str | None = None,
    sql_statement: str | None = None,
    event_time: datetime | None = None,
    returned_rows: int = 0,
    response_ms: int = 0,
    status: EventStatus = EventStatus.SUCCESS,
    payload_truncated: bool = False,
    client_info: str | None = None,
) -> CapturedEvent: ...

# backend/app/services/session_manager.py
class SessionManager:
    def __init__(self, db: AsyncSession) -> None: ...
    async def ensure_session(self, event: CapturedEvent) -> object:  # 返回 sessions ORM 行
        ...
    async def finalize_session(self, session_id: str, status: str) -> None: ...
    async def refresh_counters(self, session_id: str) -> None: ...

# backend/app/services/audit.py
async def write_audit(
    db: AsyncSession,
    *,
    operation: str,
    result: str,
    account_name: str | None = None,
    target_table: str | None = None,
    target_key: str | None = None,
    detail: str | None = None,
    request_id: str | None = None,
) -> None: ...

# backend/app/services/analysis.py
async def analyze_event(db: AsyncSession, event_row: object, session_row: object) -> object:
    """返回 schemas.events.AnalysisResult。

    职责：读取启用的最大版本规则 → 写 rule_hits → 更新 attacker_intent →
    更新 attacker_profile（含 risk_score/risk_level）→ 调用 alerts.generate_alerts。
    在 ingest 的同一事务内执行，失败由调用方回滚。
    """

# backend/app/services/risk.py
def risk_level(score: int) -> str: ...  # low/medium/high/critical
def compute_session_risk(hits: list) -> int: ...
def compute_intent_scores(hits: list) -> dict[str, int]: ...
def compute_profile_risk(hits: list) -> int: ...

# backend/app/services/alerts.py
async def generate_alerts(
    db: AsyncSession,
    *,
    session_row: object,
    attacker_id: int,
    event_row: object,
    hits: list,               # 本次新写入的 rule_hits 行（含 rule_code/intent_type/risk_weight/evidence_summary/hit_id）
) -> list[int]: ...           # 返回受影响的 alert_id 列表

# backend/app/services/ingest.py
class IngestService:
    def __init__(self, db: AsyncSession) -> None: ...
    async def ingest(self, event: CapturedEvent) -> IngestResult:
        """单事务：会话 ensure/更新 → attack_log 幂等插入 → analyze_event → 提交。

        重复 event_uuid 返回已有 event_id，duplicate=True，不重复计数。
        """

# backend/app/services/reset.py
async def reset_demo_data(db: AsyncSession, *, operator: str = "cli") -> dict[str, int]:
    """按外键顺序删除业务数据，保留规则与诱饵种子，返回各表删除行数。"""

# backend/app/honeypot/emitter.py
class EventEmitter:
    """把协议层事件写入数据库；每次事件使用独立 rw 会话与事务。"""
    async def emit(self, event: CapturedEvent) -> IngestResult: ...
```

## 3. 数据契约

- 标准事件字段以 `backend/app/schemas/events.py` 为准（已完成）。
- API 响应字段以 `specs/001-database-honeypot/contracts/api.md` 为准；JSON 使用 snake_case。
- 时间统一 ISO 8601 UTC（`...Z`）；分页参数 `page`（1 起）、`page_size`（≤100）。
- 错误结构：`{"code","message","detail","request_id"}`，实现见 `app/api/errors.py`。

## 4. 工作流与文件所有权

| 工作流 | 可写文件 |
| --- | --- |
| 数据层 | `backend/alembic.ini`、`backend/migrations/**`、`backend/app/models/**` |
| 捕获层 | `backend/app/honeypot/**`、`backend/app/services/event_builder.py`、`session_manager.py`、`ingest.py`、`audit.py`、`backend/app/utils/sql.py` |
| 分析层 | `backend/app/services/rules/**`、`analysis.py`、`risk.py`、`alerts.py`、`reset.py`、`backend/app/cli/{seed,reset_demo,verify_transaction,gen_demo_data}.py` |
| 查询/API 层 | `backend/app/api/routes/**`、`backend/app/schemas/api.py`、`backend/app/repositories/**` |
| 样本/模拟器 | `backend/app/cli/{samples/**,import_samples.py,simulate_traffic.py}`、`backend/tests/**`、`scripts/demo.sh` |

跨工作流文件由 lead 统一集成；`app/main.py`、`app/config.py`、`app/db/**`、`app/api/errors.py`、
`app/schemas/common.py`、`app/schemas/events.py`、`app/utils/masking.py` 已由 lead 完成，勿改动。
