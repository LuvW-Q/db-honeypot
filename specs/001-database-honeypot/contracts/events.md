# 内部契约：标准事件、会话生命周期与写入/分析流水线（events.md）

**Feature**: `001-database-honeypot` | **版本**: 1.1.0 | **日期**: 2026-11-19

**适用范围**：本文档定义**捕获层 → 存储层 / 分析层**之间的标准事件内部契约（非 HTTP
接口）、会话生命周期、事件写入事务与分析流水线的执行顺序与派生口径，以及“只存不执行”
安全不变量。HTTP 契约见 `contracts/api.md`；诱饵协议与配置见
`contracts/honeypot-protocol.md`；表、列、约束与视图的最终定义见 `data-model.md`。

**与 `data-model.md` 的对齐**（本版已按其 v1.0 定稿校正）：

- `session_id` 为 **UUID v4 文本（36 字符）**，列类型 `CHAR(36) ascii_bin`，不使用自定义前缀；
- `rule_hits` 使用 `risk_weight`（命中时权重快照）与 `triggered_at`（命中时间），**没有**
  `score`、`risk_weight_snapshot`、`hit_at` 等别名；
- `attack_log` **没有** `source_port`、`target_service`、`client_info`、`error_code`、
  `statement_type` 独立列；这些捕获层字段分别落到 `sessions` 对应列、由 `normalized_sql`
  派生，或只进入运行日志（见 3.2 映射表）；
- `alerts` 使用 `dedup_key = <rule_code>:<source_ip>:<YYYY-MM-DD>`、`latest_hit_id`、
  `first_seen_at`/`last_seen_at`/`occurrence_count`；告警等级由规则**固定映射**（不按分数区间）；
- 风险分三档口径、`alerts` 更新语义、事务步骤、重试退避均以 `data-model.md` 第 8、9 章为准。

---

## 1. 分层与数据流

```text
客户端 ──TCP──► 诱饵层（mysql-mimic 3.0.5，默认端口 3307）
                    │  握手 / 认证 / SQL 路由 / 伪造响应
                    ▼
                捕获层：构造标准事件（生成 session_id、event_uuid、event_time）
                    │  标准事件对象（本文档第 3 章）
                    ▼
                存储层：事务 T1 写入 sessions / attack_log（唯一约束保证幂等）
                    │  事件已提交（含 event_id）
                    ▼
                分析层：读取启用规则 → rule_hits → attacker_profile → attacker_intent → alerts
                    │  派生结果与证据
                    ▼
                展示层：只读查询（四个核心视图 + 明细表），见 contracts/api.md
```

**职责边界（不得越界）**：

| 层 | 可以 | 不可以 |
| --- | --- | --- |
| 诱饵层 | 解析协议、返回伪造数据/受控错误、产生事件素材 | 执行任何客户端 SQL、访问真实业务库、写控制台逻辑 |
| 捕获层 | 生成事件字段、截断超长值、生成 UUID | 判断风险等级、生成告警、修改原始 SQL 语义 |
| 存储层 | 事务、约束、幂等、查询 | 解析协议、做规则判断 |
| 分析层 | 读事件与规则、写命中/画像/意图/告警、重算分数 | 修改或删除 attack_log 原始记录 |
| 展示层 | 只读查询、告警已读与规则配置两个写操作 | 写入事件或伪造证据 |

---

## 2. 事件类型与状态枚举

### 2.1 `event_type`（`attack_log.event_type`，`VARCHAR(16)` + `CHECK`）

| 值 | 触发时机 | 关键字段 | 说明 |
| --- | --- | --- | --- |
| `connect` | TCP 连接建立并完成 server greeting 后立即产生 | `session_id`、`source_ip`、`source_port`、`client_info` | 连接成功与认证成功**分别记录**（FR-013）；此事件 `status=success`，并创建 `sessions` 行 |
| `auth` | 客户端提交认证响应并经服务端判定后 | `username`、`status`、`credential_test_id` | 成功、失败、拒绝均记录；失败尝试计入认证尝试统计 |
| `query` | 收到 `COM_QUERY` 并完成路由与模拟响应后 | `sql_statement`、`normalized_sql`、`status`、`returned_rows`、`response_ms` | 一条 COM_QUERY 对应一条事件；无法识别的报文归入 `query` 且 `status=error` |
| `disconnect` | 客户端 `COM_QUIT`、套接字关闭、超时或服务端关闭会话 | `status` | 会话结束事件；同步更新 `sessions.session_status` 与 `ended_at` |

**扩展规则**：新增事件类型必须先修改本文档与数据库 `CHECK` 约束，两者集合必须完全一致。

### 2.2 `status`（`attack_log.status`，`VARCHAR(16)` + `CHECK`）

| 值 | 含义 | 典型场景 |
| --- | --- | --- |
| `success` | 交互按预期完成 | 连接建立、认证通过、查询返回伪造结果 |
| `failure` | 交互正常结束但结果是否定 | 认证失败（MySQL 错误码 1045） |
| `denied` | 操作被安全策略拒绝 | 写操作返回权限不足（1142）、`LOAD DATA LOCAL` 被拒（1148） |
| `error` | 协议/解析/服务端异常 | 语法错误（1064）、畸形报文、内部错误 |

**约束**：`status` 只允许上述四值；`connect` 恒为 `success`。`disconnect` 事件取
`success`（正常 `COM_QUIT`、服务端主动关闭）或 `failure`（空闲超时、连接异常中断）；
`timeout` **不是** `status` 值，会话超时只体现在 `sessions.session_status='timeout'`。
MySQL 错误码不落 `attack_log`（无该列），由运行日志与 `evidence_summary` 承载（见 3.2）。

---

## 3. 标准事件字段

### 3.1 事件对象（JSON，捕获层产出）

```json
{
  "event_uuid": "3f2a9c1e-5b7d-4c8a-9e10-2d4f6a8b0c12",
  "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
  "event_type": "query",
  "source_ip": "198.51.100.23",
  "source_port": 51234,
  "target_service": "mysql-honeypot",
  "event_time": "2026-11-19T12:27:50Z",
  "username": "demo_app",
  "credential_test_id": "TEST-ONLY-ACC-01",
  "sql_statement": "SELECT id, email FROM users LIMIT 5",
  "normalized_sql": "select id, email from users limit ?",
  "statement_type": "SELECT",
  "returned_rows": 5,
  "response_ms": 2,
  "status": "success",
  "error_code": 0,
  "client_info": "mysql-cli/8.4.0 db=honeypot_shop charset=utf8mb4",
  "payload_truncated": false
}
```

### 3.2 字段约束与落库映射

| 字段 | 类型 | 可空 | 约束（长度/枚举/范围） | 落库位置 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `event_uuid` | string | 否 | 36 字符 UUIDv4 小写带连字符，全局唯一 | `attack_log.event_uuid`（`CHAR(36) ascii_bin`，`UNIQUE`） | 幂等键，生成规则见 3.3 |
| `session_id` | string | 否 | 36 字符 UUIDv4，`CHAR(36) ascii_bin` | `attack_log.session_id`（`FK`）、`sessions.session_id`（`PK`） | 一次连接共享；生成规则见 3.4 |
| `event_type` | string | 否 | 枚举 `connect/auth/query/disconnect` | `attack_log.event_type`（`CHECK`） | 见第 2 章 |
| `source_ip` | string | 否 | IPv4/IPv6 规范文本，≤ 45 字符，统一小写 | `attack_log.source_ip`、`sessions.source_ip`（事务内从会话行复制） | 取自套接字对端地址，不信任客户端声明 |
| `source_port` | integer | 是 | 1–65535 | `sessions.source_port`（`attack_log` 无该列） | 握手失败或 NAT 不可知时为 `null` |
| `target_service` | string | 否 | ≤ 64 字符，默认 `mysql-honeypot`；多端口演示可写 `mysql-honeypot:3307` | `sessions.target_service` | 标识被访问的诱饵服务实例 |
| `event_time` | string | 否 | ISO 8601 UTC 秒级 `...Z` | `attack_log.event_time`（`DATETIME(6)`，UTC，微秒位为 0） | 事件判定完成时间；会话内单调不减 |
| `username` | string | 是 | ≤ 128 字符；超长截断并置 `payload_truncated=true` | `attack_log.username` | 攻击者自填内容，按不可信数据对待 |
| `credential_test_id` | string | 是 | ≤ 64 字符，`^[A-Z0-9_-]+$` | `attack_log.credential_test_id` | 合成认证样本标识（`TEST-ONLY-...`）；**不存口令** |
| `credential_masked` | string | 是 | 派生字段，恒为 `"****"` | 不落库（API 层派生） | 接口只返回掩码，不返回口令明文、长度或哈希 |
| `sql_statement` | string | 是 | 协议层上限 4096 字符；存储列兜底 64 KB，超出置 `payload_truncated=true` | `attack_log.sql_statement`（`MEDIUMTEXT`） | 原始 SQL，只存储不执行 |
| `normalized_sql` | string | 是 | 与 `sql_statement` 同上限 | `attack_log.normalized_sql`（`MEDIUMTEXT`） | 小写关键字、空白折叠、字面量替换为 `?`、去注释；规则匹配只用该字段 |
| `statement_type` | string | 是 | 枚举 `SELECT/INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/SHOW/DESCRIBE/USE/SET/OTHER` | **不落库**（由 `normalized_sql` 首关键字派生，规则与展示共用同一派生函数） | 供 R03/R05 判定与页面展示 |
| `returned_rows` | integer | 否 | `>= 0`，默认 0 | `attack_log.returned_rows`（`INT UNSIGNED`） | 实际返回给客户端的行数（已应用行数上限） |
| `response_ms` | integer | 否 | `>= 0`，默认 0 | `attack_log.response_ms`（`INT UNSIGNED`） | 模拟响应耗时（毫秒） |
| `status` | string | 否 | 枚举 `success/failure/denied/error` | `attack_log.status`（`CHECK`） | 见 2.2 |
| `error_code` | integer | 是 | `0` 或 MySQL 协议错误码（`1040/1045/1049/1064/1065/1094/1142/1146/1148/1105/1295/2013`） | **不落库**：写运行日志，并进入 `rule_hits.evidence_summary` / `alerts.evidence_summary` 供解释 | 与客户端收到的错误码一致；`attack_log` 以 `status` 表达结果类别 |
| `client_info` | string | 是 | ≤ 256 字符 | `sessions.client_fingerprint`（`VARCHAR(255)`，会话级，非逐事件） | 客户端名称/版本、默认库、字符集摘要；不采集主机名、路径、进程号 |
| `payload_truncated` | boolean | 否 | 默认 `false` | `attack_log.payload_truncated`（`TINYINT(1)`） | SQL 或用户名是否被截断，用于审计“输入防线”是否生效 |

### 3.3 字段生成规则

| 字段 | 规则 |
| --- | --- |
| `event_uuid` | **捕获层**在事件构造时生成 `uuid.uuid4()` 的小写字符串；生成不依赖数据库与时间，重试不得重新生成；同一事件从捕获到入库必须复用同一 UUID |
| `event_time` | 捕获层在**交互判定完成时**取 `datetime.now(timezone.utc)`，截断到秒；同一会话内单调不减（同秒允许相等，用 `event_id` 破并列）；落库为 `DATETIME(6)`，微秒位固定为 0 |
| `session_id` | 见 3.4，由捕获层在 `connect` 事件前生成一次，后续事件复用 |
| `source_ip` | 取自套接字 `peername` 并规范化为小写文本；不接受客户端在 `client_info` 中声明的地址 |
| `normalized_sql` | 只做确定性归一：去首尾空白、折叠连续空白、关键字转**小写**、字符串/数字字面量替换为 `?`、去 `--`/`#`/`/* */` 注释；结果必须可复现 |
| `statement_type` | 取归一后 SQL 的首个关键字（大写）；无法识别为 `OTHER` |
| `returned_rows` | 诱饵层返回给客户端的**实际**行数（已应用行数上限），不是伪造表总行数 |
| `response_ms` | `int((monotonic_end - monotonic_start) * 1000)`，四舍五入到整数毫秒 |

### 3.4 `session_id` 生成规则

- 格式：**UUID v4 文本**，36 字符小写带连字符，例如
  `9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b`；列类型 `CHAR(36) CHARACTER SET ascii COLLATE ascii_bin`。
- 生成时机：TCP 连接接受后、写入 `connect` 事件与 `sessions` 行前，一次连接只生成一次。
- 唯一性：插入 `sessions` 命中主键冲突时**重新生成**（最多 3 次）；仍冲突则拒绝该连接并写运行
  日志（`stage=session_insert`），**不得覆盖或复用已有会话**（spec.md 边界情况）。
- 客户端输入不影响 `session_id`；`session_id` 只作为主键与外键值，不承载业务含义。

---

## 4. 幂等语义（`event_uuid`）

### 4.1 数据库保证

- `attack_log.event_uuid` 的 `UNIQUE` 约束（`uk_attack_log_event_uuid`）是幂等的**唯一权威**；
  应用层不做“先查后插”。
- 事务内直接 `INSERT attack_log`；捕获 `errno 1062` 且键名为 `uk_attack_log_event_uuid` 后，
  **立即回滚整个事务**（撤销本次已产生的会话计数、命中、画像与告警更新），再
  `SELECT event_id FROM attack_log WHERE event_uuid = ?` 取回已有事件编号。

### 4.2 处理语义

| 情形 | 存储层行为 | 返回值/副作用 |
| --- | --- | --- |
| 首次提交 | 插入事件、会话计数 +1、执行分析流水线、生成派生结果 | `is_new=true`，返回新 `event_id` |
| 重复提交（内容一致） | 回滚后读取已有事件；不更新计数、不重复累计风险与证据、不新增命中或告警 | `is_new=false, deduped=true`，返回**已有** `event_id` |
| 重复提交（内容不一致） | 同上，且以 `normalized_sql/status/returned_rows` 摘要比对，不一致时写运行日志（含 `event_uuid` 与两侧摘要），**不覆盖**已有记录 | `is_new=false, deduped=true, conflict=true`；内部/CLI 场景对应 `409 IDEMPOTENCY_CONFLICT` |

**内容摘要**只用于运行日志对比，不落库（`attack_log` 不设摘要列）；摘要口径：
`sha256(event_type + "\n" + event_time + "\n" + normalized_sql + "\n" + status + "\n" + returned_rows)`。

### 4.3 幂等覆盖范围

同一 `event_uuid` 重复提交时，以下副作用**全部不得重复发生**：

1. `sessions.request_count` 不增加；
2. `sessions.max_risk_score` 不重新抬升；
3. `rule_hits` 不新增行；
4. `attacker_intent.intent_score`、`evidence_count` 不增加；
5. `attacker_profile` 计数与风险分不变；
6. `alerts` 不新增，`occurrence_count` 不增加（告警去重键另行保证）。

**并发重复提交**：两个事务同时插入同一 `event_uuid`，后提交方等待唯一索引后收到 `1062`，
回滚并读取已有事件；两个请求返回同一 `event_id`，只产生一条日志（SC-011 的“重复 10 次
等价于 1 次”）。

---

## 5. 会话生命周期

### 5.1 状态机

```text
        TCP accept + server greeting
                  │
                  ▼
              ┌────────┐  客户端 COM_QUIT / 套接字关闭   ┌────────┐
              │ active │ ─────────────────────────────► │ closed │
              └────────┘                                 └────────┘
                  │  空闲超过 session_idle_timeout_s        ▲
                  ├───────────────────────────────────────►│ timeout
                  │  协议异常 / 处理异常 / 服务端强制关闭    │
                  └───────────────────────────────────────►│ error
```

| `session_status` | 进入条件 | `ended_at` | 说明 |
| --- | --- | --- | --- |
| `active` | 会话创建后至结束前（`sessions` 默认值） | `NULL` | 允许持续写入事件 |
| `closed` | 客户端 `COM_QUIT` 或 TCP FIN/RST 后正常收尾 | 关闭时刻（UTC） | 正常演示路径 |
| `timeout` | 空闲超过 `session_idle_timeout_s`（默认 600 秒） | 超时判定时刻 | 由空闲计时器触发，写 `disconnect` 事件 |
| `error` | 协议解析失败、诱饵层未捕获异常、存储层致命失败 | 异常发生时刻 | 必须写运行日志含 `session_id` 与失败阶段 |

**约束**：

- `ended_at >= started_at`（数据库 `CHECK`，FR-017）；时钟回拨导致小于 `started_at` 时，
  取 `started_at` 并写运行日志。
- 状态只能从 `active` 迁移到其他三种之一，不允许回到 `active`；重复关闭为幂等操作
  （只更新一次 `ended_at`，再关闭不覆盖）。
- 会话结束后收到迟到事件：允许写入 `attack_log`（不改变 `session_status`），并写运行日志
  标注迟到。

### 5.2 字段维护口径

| 字段 | 维护规则 |
| --- | --- |
| `started_at` | 创建会话时的 UTC 时间，等于 `connect` 事件的 `event_time`（两者必须一致） |
| `ended_at` | `disconnect` 事件写入时设置；`active` 时为 `NULL` |
| `session_status` | 见 5.1；由 `disconnect` 事件处理或超时/异常处理器更新 |
| `client_fingerprint` | `connect` 事件时写入（来自 `client_info`，截断 255 字符），后续不覆盖 |
| `request_count` | **成功写入一条事件 +1**（`connect` 计入）；幂等去重**不增加**；`v_session_risk_summary.event_count` 为重算值，`stored_request_count` 为存储值，二者应一致 |
| `max_risk_score` | 写入事件时 `GREATEST(max_risk_score, 本次按 6.4 计算的会话分)`；**只增不减**，规则停用或改版不回溯降低历史会话分数；`v_session_risk_summary.calculated_risk_score` 为重算值，用于比对存储值是否漂移 |

**一致性校验查询（验收用）**：

```sql
SELECT s.session_id, s.request_count, COUNT(l.event_id) AS actual_events,
       s.max_risk_score, v.calculated_risk_score, s.started_at, s.ended_at
FROM sessions s
LEFT JOIN attack_log l ON l.session_id = s.session_id
LEFT JOIN v_session_risk_summary v ON v.session_id = s.session_id
GROUP BY s.session_id, s.request_count, s.max_risk_score, v.calculated_risk_score,
         s.started_at, s.ended_at
HAVING s.request_count <> COUNT(l.event_id)
    OR (s.ended_at IS NOT NULL AND s.ended_at < s.started_at)
    OR s.max_risk_score <> v.calculated_risk_score;
```

预期：**返回 0 行**。

---

## 6. 事件写入事务与规则分析流水线

### 6.1 单事务基线（T1，对应 FR-039）

一条事件从“存储层接收”到“派生结果落库”在**同一个数据库事务**内完成；隔离级别固定
`READ COMMITTED`，连接初始化 `time_zone='+00:00'`、`autocommit=0`、
`innodb_lock_wait_timeout=5`。锁顺序固定为
`sessions → attack_log → rule_hits → attacker_profile → attacker_intent → alerts`。

| 步骤 | 操作 | 锁 / 约束要点 |
| --- | --- | --- |
| 0 | **事务外校验**：字段类型、长度、枚举、IPv4/IPv6、UTF-8 编码；超长截断并置 `payload_truncated` | 校验失败直接拒绝，不开启事务，写运行日志 |
| 1 | `START TRANSACTION` | — |
| 2 | 会话定位：`connect` 执行 `INSERT sessions(...)`；其他事件 `SELECT ... WHERE session_id=? FOR UPDATE` | `connect` 主键冲突 → 重新生成 `session_id`（≤3 次），仍冲突回滚；其他事件无行 → 回滚返回“未知会话”（外键保护） |
| 3 | `INSERT attack_log(...)`，`source_ip` 从会话行复制 | `uk_attack_log_event_uuid` 是幂等裁决点（第 4 章） |
| 4 | 规则判定：读取 `detection_rules WHERE enabled=1`（`CURRENT` 版本），按 6.3–6.5 口径计算本事件命中；窗口统计只读本来源/本会话窗口 | 只读不加锁；读到的 `(rule_version, risk_weight)` 即本事件采用版本 |
| 5 | `INSERT rule_hits(...)`（`rule_id/rule_code/intent_type/rule_version/risk_weight/evidence_summary/triggered_at`） | `uk_rule_hits_event_rule_version` 防重复分析；冲突时用 `ON DUPLICATE KEY UPDATE hit_id=hit_id` 空更新 |
| 6 | 画像 Upsert：`INSERT attacker_profile ... ON DUPLICATE KEY UPDATE attacker_id=LAST_INSERT_ID(attacker_id), last_seen=GREATEST(...), total_*=total_*+1 ...` | 同来源行是唯一热点行；事务必须短（目标 <100 ms） |
| 7 | 按 6.4 公式**重算**画像分与证据摘要：`UPDATE attacker_profile SET risk_score=?, evidence_summary=?, last_calculated_at=?` | 重算而非累加，避免漂移；`risk_level` 由生成列维护，禁止写入 |
| 8 | 意图 Upsert：按 `(attacker_id, intent_type)` 更新 `intent_score`、`evidence_count`、`last_detected_at=GREATEST(...)` | `uk_attacker_intent_attacker_type` 定位；分数按 6.4 重算 |
| 9 | 告警 Upsert：符合 6.5 条件的首次命中插入告警；重复触发更新 `last_seen_at/occurrence_count/latest_hit_id/evidence_summary` | `uk_alerts_dedup_key` 去重 |
| 10 | 会话计数与最高分：`UPDATE sessions SET request_count=request_count+1, max_risk_score=GREATEST(max_risk_score, ?), ended_at=?, session_status=? WHERE session_id=?` | 与步骤 2 同一行锁，事务内串行；`disconnect` 置 `closed` 并写 `ended_at` |
| 11 | `COMMIT`；返回 `(event_id, is_new, hit_count, alert_ids, session_risk_score)` | — |
| E | 任一步异常：`ROLLBACK`，写应用日志（`event_uuid`、阶段、`errno`、`sqlstate`、重试次数），按 6.2 判定是否重试 | 不得吞异常、不得部分提交（FR-039/FR-042） |

**为什么是单事务**：会话计数、原始事件、规则命中、意图、画像与告警必须同时可见，否则
页面会出现“有告警但没有对应事件”的不可解释状态；同时满足答辩“事务回滚”演示（SC-012）。

**性能取舍**：课程演示规模（几千至几万条）下单事务足够；若后续拆分“分析”为独立可重放
阶段，必须保留 `rule_hits` 唯一键与 `alerts` 去重键，并在 `plan.md` 记录复杂度理由。
本版**不**默认拆分。

### 6.2 失败、回滚与重试

| 情形 | 处理 |
| --- | --- |
| 任意步骤抛异常 | `ROLLBACK`；不留下任何部分结果；捕获层对外仍按诱饵协议返回预设响应（客户端无感），运行日志必须含 `event_uuid`、`session_id`、失败阶段、数据库错误码 |
| 死锁 `1213` / 锁等待超时 `1205` | 整体重试事务，最多 **3 次**；退避 `50ms → 200ms → 800ms`（±20% 抖动）；每次重试复用同一 `event_uuid` |
| 唯一键冲突 `1062`（`uk_attack_log_event_uuid`） | 非失败：回滚当前事务，读取已有事件与派生结果，返回 `deduped=true`（4.1） |
| 其他 `1062`（如 `uk_alerts_dedup_key`） | 正常并发/重复触发，走 `ON DUPLICATE KEY UPDATE`，事务继续 |
| 外键失败 `1452` | 回滚，返回明确错误（`FK_*`），运行日志记录被引用值；**不重试** |
| 检查约束失败 `3819` | 回滚，返回字段级错误（字段名 + 约束名）；**不重试** |
| 重试耗尽 / 数据库不可达 | 运行日志记录事件编号与阶段；接口返回明确错误；事件进入本地待重投队列（持久化文件），后台限速重投，**禁止静默丢弃** |
| 会话已结束仍收到事件 | 允许写入（迟到事件），不改 `session_status`，写运行日志 |

**事务后不可逆**：`COMMIT` 后的派生结果不得因“事件重试”而重新计算覆盖；重算走 6.6 的
独立脚本。

### 6.3 规则分析流水线（事务内步骤 4–9 展开）

1. **读取规则快照**：`SELECT ... FROM detection_rules WHERE enabled=1`（借助生成列
   `enabled_rule_code` 的唯一约束，同一 `rule_code` 至多一个启用版本），一次性固定本次
   分析使用的 `(rule_id, rule_code, rule_version, risk_weight)`。
2. **逐条匹配**：输入只用 `normalized_sql`、派生 `statement_type`、`status`、`username`、
   `event_time`、会话内统计（累计返回行数、连续 SELECT 次数）与来源窗口统计（60 秒连接数、
   5 分钟认证次数/凭据组合数）；**不执行**原始 SQL、不访问诱饵数据、不做字符串拼接。
3. **写命中**：每条命中一行 `rule_hits`，唯一键 `(event_id, rule_id, rule_version)`；
   `evidence_summary` 必须说明“为什么命中”，≤ 1024 字符。
4. **画像与意图**：见 6.1 步骤 6–8 与 6.4 公式。
5. **生成告警**：按 6.5 条件与去重键 Upsert。
6. **更新会话**：`request_count +1`、`max_risk_score=GREATEST(...)`，必要时写 `ended_at`
   与 `session_status`。

### 6.4 派生口径（确定性、可追溯、带版本快照）

计分单元是 **`rule_code`**：同一规则在同一统计范围内重复命中只计一次，取命中快照的最大
权重 `MAX(risk_weight)`；一律 `LEAST(100, ...)`；AI 不参与任何分数计算。

| 派生结果 | 公式/口径 |
| --- | --- |
| 会话风险分 | `LEAST(100, Σ_{c∈rule_codes(session)} MAX_{h∈hits(session,c)} h.risk_weight)`；写回 `sessions.max_risk_score = GREATEST(旧值, 新值)` |
| 意图风险分 | `LEAST(100, Σ_{c∈rules(intent)} MAX_{h∈hits(ip,c,intent_snapshot)} h.risk_weight)`；写入 `attacker_intent.intent_score` |
| 画像风险分 | `LEAST(100, Σ_{c∈rule_codes(ip)} MAX_{h∈hits(ip,c)} h.risk_weight)`；**全量命中，不设时间窗口**；写入 `attacker_profile.risk_score` |
| 风险等级 | 0–29 `low`、30–59 `medium`、60–79 `high`、80–100 `critical`（`attacker_profile.risk_level` 生成列与四个视图共用同一 CASE，不得各自维护） |
| 意图 `evidence_count` | 该 `(attacker_id, intent_type)` 下的规则命中行数（重复分析被唯一键挡住，不重复计） |
| 意图 `first/last_detected_at` | 该意图下 `MIN/MAX(triggered_at)` |
| 主要意图 | 不在表中存多值；由 `v_attacker_profile_summary` 的 `ROW_NUMBER()` 按 `intent_score DESC, last_detected_at DESC, 危害等级 DESC` 稳定取第一名（FR-050） |
| 告警等级 `severity` | **按规则固定映射**（见 6.5），不按会话分数区间计算 |
| 证据摘要 | 模板如 `规则 R05（破坏性操作）：语句类型 DROP，对象 orders，会话累计返回行数 120（阈值 100）`；≤ 1024 字符，不含明文口令 |

**口径说明（答辩必须讲清）**：画像分按“规则维度”直接聚合，**不是**把各意图分相加再封顶；
意图分只用于排序与展示，不参与画像分合成。单意图已封顶 100 时两者会不同，本设计以画像公式
为准（`data-model.md` 9.2）。

**可追溯性**：任一分数必须能沿
`attacker_profile.risk_score → rule_hits(rule_code, risk_weight, rule_version) →
attack_log.event_id → attack_log.sql_statement` 逐级回溯（SC-004/SC-005）。

### 6.5 告警生成条件与去重

**生成条件**：规则命中且 `intent_type ∈ {bruteforce, data_dump, destructive}`（对应
R02/R04/R05），**首次命中即生成**；R01（scanning）与 R03（recon）只进入画像/意图/证据。

| 触发规则 | `intent_type` | `alert_type` | `severity`（固定） | 中文等级 |
| --- | --- | --- | --- | --- |
| R02 | bruteforce | `bruteforce` | `medium` | 中 |
| R04 | data_dump | `data_dump` | `high` | 高 |
| R05 | destructive | `destructive` | `critical` | 严重 |

- **去重键**：`dedup_key = "<rule_code>:<source_ip>:<YYYY-MM-DD>"`，日期取 `triggered_at`
  的 UTC 日期，`source_ip` 为小写文本；示例 `R05:198.51.100.23:2026-11-19`；
  数据库 `uk_alerts_dedup_key` 唯一。
- **首次触发插入**：`session_id`（首次告警会话）、`attacker_id`、`rule_id`/`rule_code`、
  `latest_hit_id`（本次命中）、`alert_type`、`severity`（固定映射）、`title`、
  `evidence_summary`、`first_seen_at = last_seen_at = triggered_at`、`occurrence_count=1`、
  `is_read=0`。
- **重复触发更新**：`last_seen_at=GREATEST(...)`、`occurrence_count+1`、`latest_hit_id`、
  `evidence_summary`、`updated_at`；**不**更新 `first_seen_at`、`created_at`、`severity`、
  `alert_type`、`rule_id`、`session_id`（保留“首次”语义，避免告警漂移）。
- **跨日行为**：同一攻击跨 UTC 日界会产生两条告警（去重键含日期），属于有意取舍，需在
  演示说明中写明。
- 告警到证据的追溯路径：`alerts.latest_hit_id → rule_hits → attack_log.event_id`
  （FR-057/SC-006）。

### 6.6 重算（可选运维动作，不属于默认流水线）

若按新规则版本重算历史，必须：① 独立脚本执行并默认 `--dry-run`；② 显式声明时间范围与规则
版本；③ 先写 `audit_log`（范围、版本、结果统计）；④ 只重算派生表（新增 `rule_hits` 并保留
旧快照、重算 `attacker_intent`/`attacker_profile`/`alerts`），**禁止修改或删除 `attack_log`
原始事件**；⑤ 记录重算后 `sessions.max_risk_score` 的变化。

---

## 7. JSON 示例

### 7.1 `connect` 事件

```json
{
  "event_uuid": "8c1d5e70-2a4b-4c6d-8e9f-0a1b2c3d4e5f",
  "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
  "event_type": "connect",
  "source_ip": "198.51.100.23",
  "source_port": 51234,
  "target_service": "mysql-honeypot",
  "event_time": "2026-11-19T12:27:10Z",
  "username": null,
  "credential_test_id": null,
  "sql_statement": null,
  "normalized_sql": null,
  "statement_type": null,
  "returned_rows": 0,
  "response_ms": 0,
  "status": "success",
  "error_code": null,
  "client_info": "mysql-cli/8.4.0 db=honeypot_shop charset=utf8mb4",
  "payload_truncated": false
}
```

**预期落库结果**：新建 `sessions` 行（`session_status='active'`、`request_count=1`、
`max_risk_score=0`、`client_fingerprint` 取自 `client_info`），`attack_log` 新增 1 行；
无规则命中、无告警。

### 7.2 `auth` 失败事件

```json
{
  "event_uuid": "b2e4f6a8-1c3d-4e5f-9a0b-2c4d6e8f0a1b",
  "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
  "event_type": "auth",
  "source_ip": "198.51.100.23",
  "source_port": 51234,
  "target_service": "mysql-honeypot",
  "event_time": "2026-11-19T12:27:14Z",
  "username": "admin_test",
  "credential_test_id": "TEST-ONLY-UNKNOWN-001",
  "sql_statement": null,
  "normalized_sql": null,
  "statement_type": null,
  "returned_rows": 0,
  "response_ms": 1,
  "status": "failure",
  "error_code": 1045,
  "client_info": "mysql-cli/8.4.0 auth=mysql_native_password",
  "payload_truncated": false
}
```

**预期落库结果**：`attack_log` 新增 1 行（`status='failure'`）；`sessions.request_count +1`；
`attacker_profile.total_auth_attempts +1`、`total_auth_failures +1`；口令不落库（只保留
`credential_test_id`）；若 5 分钟内认证尝试与凭据组合达到阈值则命中 R02 并生成
`bruteforce`（severity=`medium`）告警。

### 7.3 `query` 被拒绝的写操作事件

```json
{
  "event_uuid": "d4f6a8b0-3c5e-4f7a-8b9c-0d1e2f3a4b5c",
  "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
  "event_type": "query",
  "source_ip": "198.51.100.23",
  "source_port": 51234,
  "target_service": "mysql-honeypot",
  "event_time": "2026-11-19T12:27:50Z",
  "username": "demo_app",
  "credential_test_id": null,
  "sql_statement": "DROP TABLE orders",
  "normalized_sql": "drop table orders",
  "statement_type": "DROP",
  "returned_rows": 0,
  "response_ms": 2,
  "status": "denied",
  "error_code": 1142,
  "client_info": "mysql-cli/8.4.0 db=honeypot_shop charset=utf8mb4",
  "payload_truncated": false
}
```

**预期落库结果**：`attack_log` 新增 1 行（`status='denied'`）；命中 R05（权重 35）；
`destructive` 意图更新；会话 `max_risk_score` 抬升至 35（若同会话另有 R03 命中则为 50）；
生成 `destructive` 告警（severity=`critical`，`dedup_key=R05:198.51.100.23:2026-11-19`）；
**诱饵数据未被修改**（`fake_orders` 行数不变）。

---

## 8. 安全不变量：只存不执行

以下不变量是**不可协商**的实现红线（FR-004/FR-007/FR-083、宪法原则三）：

1. **采集的 SQL 永不执行**：`sql_statement` 与 `normalized_sql` 只作为字符串存储、展示与
   规则匹配；任何代码路径不得把采集内容交给数据库驱动、`exec`、`subprocess`、模板引擎或
   ORM 的 `text()` 拼接执行。
2. **规则匹配不使用 SQL 求值**：规则只基于派生的 `statement_type`、关键字与统计值判断，
   禁止把攻击者 SQL 拼进规则查询。
3. **口令不可逆**：诱饵账号口令只以环境变量注入并做常量时间比较，**不落库、不返回**；
   认证事件只保存 `username` 与 `credential_test_id`，API 只返回 `credential_masked="****"`。
4. **无命令/文件能力**：诱饵进程不得调用 shell、不得读写客户端指定路径、不支持
   `LOAD DATA LOCAL INFILE`（1148）、`SELECT ... INTO OUTFILE`（拒绝）、UDF、`GRANT`、
   复制与插件安装。
5. **长度与规模上限**：协议层 SQL 4096 字符、用户名 128 字符、`client_info` 256 字符、
   单次返回 100 行、连接数 200；存储层 `sql_statement` 列兜底 64 KB 并以
   `payload_truncated` 标记截断。超限本身不导致进程退出（FR-008/边界情况）。
6. **编码安全**：输入按 UTF-8 严格解码，非法字节序列拒绝并记 `status=error`；连接字符集
   统一 `utf8mb4`，不使用 `latin1` 等会改变字节语义的字符集。
7. **不主动出站**：事件流水线与诱饵层不得向攻击者地址发起反向连接、DNS 查询或探测；
   任何重放/复现只在隔离环境由人工执行。
8. **展示与导出最小化**：展示层只读取允许字段；导出前删除或遮盖口令相关字段（FR-020/FR-082）。
9. **审计只追加**：`attack_log` 不因“修正”而删除；`audit_log` 仅追加，业务账号禁止修改
   或删除审计记录。
10. **失败不静默**：任何写入失败必须在运行日志中保留 `event_uuid`、`session_id`、失败
    阶段与数据库错误码；不得以“客户端没发现”为由忽略（FR-019/FR-042）。

---

## 9. 验收对照

| 编号 | 验收点 | 对应标准 | 验证方式 |
| --- | --- | --- | --- |
| EV-01 | 同一事件提交 10 次，日志数、计数、风险贡献与 1 次相同 | SC-011 | CLI `--sample S03 --repeat 10`，比对 `COUNT(*)` 与 `max_risk_score` |
| EV-02 | 会话内事件按 `event_time, event_id` 稳定排序，重复查询一致 | SC-003 | `api.md` 3.5 + 两次执行同一查询比对 |
| EV-03 | `request_count` 等于该会话事件条数，且与视图 `event_count` 一致 | FR-017 | 第 5.2 节校验 SQL 返回 0 行 |
| EV-04 | 事务注入失败后五类数据与事务前一致 | SC-012 | 受控失败脚本 + 前后计数快照比对 |
| EV-05 | 引用不存在 `session_id` 被外键拦截并返回明确错误 | FR-022/边界情况 | 直接 SQL `INSERT` 触发 1452 |
| EV-06 | 规则版本切换后新命中带新版本，历史命中保留旧快照 | FR-052/SC-004 | PATCH 规则后导入样本，查 `rule_hits` |
| EV-07 | 告警去重键匹配 `<rule_code>:<source_ip>:<date>`，重复触发只增 `occurrence_count` | FR-059 | 重复导入 S05，比对 `alerts` 行数与 `occurrence_count` |
| EV-08 | 采集 SQL 全文只存不执行，诱饵数据行数不变 | FR-004/FR-083 | `DROP/UPDATE` 后查 `fake_orders` 行数 |
| EV-09 | 超长 SQL 被截断入库且 `payload_truncated=1` | 边界情况/FR-008 | 发送 > 4096 字符语句并核对 |
| EV-10 | 会话状态与结束时间满足 `ended_at >= started_at`，存储分与重算分一致 | FR-017 | `CHECK` 约束 + 第 5.2 节校验 SQL |

---

## 10. 变更记录

| 版本 | 日期 | 变更 | 动机 |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-19 | 首次建立标准事件字段、UUID 与幂等语义、会话生命周期、单事务流水线与派生口径、只存不执行不变量 | 落实 spec.md 用户故事 2/3/4 与 FR-011 至 FR-052 |
| 1.1.0 | 2026-11-19 | 按 `data-model.md` 对齐：`session_id` 改为 UUID v4；字段落库映射（`source_port`/`client_info`/`error_code`/`statement_type`）；`payload_truncated` 取代 `sql_truncated`；`rule_hits` 改用 `risk_weight`/`triggered_at`；告警等级固定映射与 `<rule_code>:<source_ip>:<date>` 去重键；计分公式与重试退避对齐 data-model 第 8、9 章 | 避免契约与数据模型双轨，保证实现与验收只有一个事实来源 |
