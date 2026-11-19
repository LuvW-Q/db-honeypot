# 接口契约：控制台只读查询与受限配置接口（api.md）

**Feature**: `001-database-honeypot` | **版本**: 1.1.0 | **日期**: 2026-11-19

**适用范围**：本文档定义控制台（Vue 3.5 + Vite 8 + Element Plus 2.14 + ECharts 6）与后端
（Python 3.14 + FastAPI 0.165 + Uvicorn 0.54 + Pydantic 2.14）之间的 HTTP 契约，以及
`/api` 路由的通用约定、字段、错误、分页、脱敏与页面映射规则。

**关联文档**：

| 文档 | 作用 |
| --- | --- |
| `specs/001-database-honeypot/spec.md` | 功能规格；本契约实现其 FR-055 至 FR-070、FR-078 与 SC-009/SC-010 |
| `docs/数据库蜜罐系统项目总纲_1.1_扩充版.md` 第七章“建议接口”、第九章“演示方案” | 接口清单与演示口径基线 |
| `.specify/memory/constitution.md` | 安全、中文文档、事务与只读边界约束 |
| `specs/001-database-honeypot/data-model.md` | 表、列、视图与约束的最终定义（v1.0 定稿；字段口径以其为准，本契约已对齐） |
| `specs/001-database-honeypot/contracts/events.md` | 标准事件内部契约（捕获层→存储层/分析层） |
| `specs/001-database-honeypot/contracts/honeypot-protocol.md` | 诱饵协议、错误码与配置项契约 |

**字段名一致性约定**：本契约的 JSON 字段一律 `snake_case`，并与数据库列名保持一致。
若 `data-model.md` 最终确定的列名或视图列名与本文档不同，以 `data-model.md` 为准，并
在同一次提交中修订本文档与前端类型定义；不得出现“接口字段一套、数据库列一套”的双轨命名。

---

## 1. 通用约定

### 1.1 基础路径与传输

| 项目 | 约定 |
| --- | --- |
| Base path | `/api`（无版本前缀；本课程项目不做多版本共存） |
| 传输 | HTTP/1.1，JSON 请求与响应体，`Content-Type: application/json; charset=utf-8` |
| 字符编码 | UTF-8；响应不得返回非 UTF-8 字节 |
| 监听地址 | 开发与演示默认 `127.0.0.1:8000`，只绑定回环地址，不暴露到公网 |
| 前端开发代理 | Vite dev server（`127.0.0.1:5173`）把 `/api` 代理到 `http://127.0.0.1:8000` |
| 生产托管 | 由 FastAPI `StaticFiles` 托管前端构建产物（`/`），`/api` 仍为同一进程；或由 nginx 托管静态文件并把 `/api` 反代到 8000 |
| CORS | 仅允许 `http://127.0.0.1:5173` 与 `http://localhost:5173` 的开发来源；生产同源部署时关闭 CORS |
| 请求标识 | 每个响应都带 `X-Request-ID` 响应头，值等于错误体中的 `request_id`（UUIDv4） |
| 超时 | 单接口数据库查询超时 3 秒，超时返回 `503` 与 `DB_TIMEOUT`；不提供长轮询与 WebSocket |
| 缓存 | 只读接口响应带 `Cache-Control: no-store`（演示环境数据实时变化，禁止前端或代理缓存） |

### 1.2 权限边界（隔离环境不做登录，但读写分离）

本系统为隔离实验环境中的课程演示系统，**不实现账号登录、会话令牌与 RBAC**；权限边界由
“接口分类 + 数据库账号 + 网络暴露面”三层共同保证：

1. **读接口（GET）**：全部为只读查询。后端以分析只读数据库账号（`honeypot_app_ro`，
   `data-model.md` 中称 `app_ro`）执行，该账号仅有 `SELECT` 权限，且仅授权核心视图与少数
   明细表，不具备任何写权限。
2. **写接口（PATCH）**：整个系统只有两类写接口——告警已读状态更新、检测规则配置。
   写接口使用应用读写账号（`honeypot_app_rw`，`data-model.md` 中称 `app_rw`），不授予 DDL
   权限，不使用超级用户；迁移/种子使用独立 `migrate` 账号。
3. **无写接口的领域**：会话、事件、规则命中、画像、意图、诱饵数据、样本导入均**不提供**
   HTTP 写入入口。原因是这些数据只能由诱饵捕获层、存储层与分析流水线产生；若允许 HTTP
   写入，演示环境可被任意脚本伪造“攻击证据”，破坏审计可信度（对应 FR-068、FR-082）。
4. **网络边界**：API 默认只监听 `127.0.0.1`；演示机若需同机浏览器以外的访问，必须显式
   修改配置并记录在演示记录中，且仍限制在隔离实验网内（对应 FR-079）。
5. **写接口的幂等与乐观并发**：写接口不要求登录，但要求请求体严格校验（多余字段返回
   `422`）、规则变更带可选 `expected_version`（版本不符返回 `409`），并且全部写入落在
   数据库事务中，失败整体回滚。

> **答辩说明口径**：本项目不做权限系统（FR-067/FR-068），读写分离体现在“只有告警已读与
> 规则配置两条写路径，其余全部只读，且只读路径使用只读数据库账号”。

### 1.3 请求与响应格式

- 请求体（仅两个 PATCH 接口使用）必须为 JSON 对象；空体、数组、非 JSON 一律 `422`。
- 成功响应统一为 JSON 对象；列表接口统一使用分页信封（见 1.4）。
- **不使用 `204 No Content`**：即使更新成功也返回更新后的完整对象，便于前端就地刷新并让
  “更新是否成功”在返回值中可见（FR-058）。`204` 仅作为未来接口的保留状态码。
- 服务端不再返回超出契约的字段（禁止把数据库整行 ORM 对象直接序列化）；新增字段属于
  契约变更，需同步更新本文档与前端 TypeScript 类型。
- 数值字段：计数为非负整数；分数为 0 至 100 的整数；比例字段为 0 至 1 的浮点数，保留
  4 位小数。

### 1.4 分页约定

| 参数 | 类型 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | integer | `1` | `>= 1` | 页码从 1 开始；`page=0`、负数、非整数 → `422 VALIDATION_ERROR` |
| `page_size` | integer | `20` | `1 <= page_size <= 100` | 超过 100 返回 `422 VALIDATION_ERROR`，**不做静默截断** |
| `sort` | string | 见各接口 | 白名单枚举 | 非白名单值 → `422 SORT_FIELD_INVALID` |
| `order` | string | `desc` | `asc` / `desc` | 大小写不敏感；其他值 → `422 VALIDATION_ERROR` |

**分页信封**（所有列表接口一致）：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0,
  "total_pages": 0
}
```

- `total_pages = ceil(total / page_size)`；`total = 0` 时 `total_pages = 0`。
- `page` 超出范围（例如 `page=99` 但只有 2 页）**不返回 404**，返回 `items: []` 与真实
  `total`，前端显示“暂无更多数据”。
- **稳定分页**：每个列表接口必须追加确定性次级排序键（见各接口），保证相同数据在翻页与
  刷新之间顺序一致（对应 SC-009“排序稳定”）。

### 1.5 排序与时间约定

- 排序参数只接受白名单字段；`sort` 与 `order` 同时生效，未提供 `sort` 时使用接口默认排序。
- 所有时间字段统一为 **ISO 8601 UTC**，秒级精度，以 `Z` 结尾，格式固定为
  `2026-11-19T12:30:48Z`（不返回 `+00:00`、不返回毫秒、不返回本地时区）。
- 输入时间参数（`from`、`to`）必须符合上述格式或 `YYYY-MM-DD`（按 UTC 当日 00:00:00 解释）；
  其他格式 → `422 TIME_RANGE_INVALID`。
- 时间区间语义统一为**左闭右开** `[from, to)`；`from > to` → `422 TIME_RANGE_INVALID`；
  两者都不传表示不限制时间。
- 日期字段（趋势、统计日）使用 `YYYY-MM-DD`（UTC 日期）。
- 数据库存储为 UTC（连接参数 `time_zone='+00:00'`），转换与格式化只在 API 序列化层完成。

### 1.6 空数组与空态约定

- 数据库无数据时，列表接口返回 `items: []`（**不是** `null`、不是 404、不是 500）。
- 概览、攻击者详情、会话时间线等对象型接口，在没有关联数据时对应数组字段返回 `[]`，
  可空标量返回 `null`（例如 `main_intent: null`），不得省略字段。
- 前端空态文案由页面负责，接口只保证结构完整；不允许页面因空数组进入错误分支。

### 1.7 脱敏字段约定

| 数据 | 约定 |
| --- | --- |
| 口令与凭据明文 | **任何接口在任何情况下都不返回**，包括认证失败事件中的输入口令 |
| 凭据标识 | 只返回 `credential_test_id`（合成样本测试标识，如 `S02-AUTH-FAIL-01`）与固定掩码 `credential_masked: "****"`；不返回长度、哈希、前后缀 |
| 用户名 | 可返回（攻击者自填内容），但长度截断至 128 字符，且由前端以纯文本渲染（不做 HTML 注入） |
| 客户端特征 | `client_info` 截断至 256 字符；不返回客户端文件路径、进程号、主机名等采集侧信息 |
| 伪造敏感配置 | 若接口暴露诱饵配置项，值必须含 `TEST-ONLY` 标识且不可用；本版 API 不提供诱饵数据查询接口 |
| 错误详情 | `detail` 中禁止回显完整请求体、SQL、口令与环境变量；只返回字段名、约束类型与请求编号 |
| 导出 | 本版不提供 HTTP 导出接口；如后续增加，必须复用本节规则并在导出前做字段审查（FR-082） |

### 1.8 错误响应统一结构

所有非 2xx 响应均为：

```json
{
  "code": "SESSION_NOT_FOUND",
  "message": "未找到会话",
  "detail": {"session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b"},
  "request_id": "6f1c2f4e-8a3b-4f5d-9c1e-2b7d0a9e5c11"
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 否 | 稳定机器可读错误码，大写蛇形，见 1.9 错误码清单 |
| `message` | string | 否 | 面向操作者的中文短描述（可展示在页面提示条） |
| `detail` | object \| array \| null | 是 | 结构化细节；字段校验错误时为逐字段错误数组 |
| `request_id` | string | 否 | 本次请求 UUIDv4，与 `X-Request-ID` 响应头一致，便于在运行日志中定位 |

字段校验错误（`422`）的 `detail` 结构固定为：

```json
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "detail": [
    {"field": "page_size", "reason": "必须小于或等于 100", "input": "500"}
  ],
  "request_id": "6f1c2f4e-8a3b-4f5d-9c1e-2b7d0a9e5c11"
}
```

约束：

- `detail.input` 只回显被校验的标量参数（截断至 64 字符），**不回显** SQL、口令、请求体全文。
- 生产模式下不返回 Python 异常栈；异常栈只写运行日志（与应用日志分离，FR-073/FR-074）。

### 1.9 状态码与错误码清单

| HTTP | `code` | 触发条件 | 前端处理 |
| --- | --- | --- | --- |
| `200` | — | 查询成功、更新成功、幂等重复更新成功 | 正常渲染 |
| `201` | — | 预留（本版无“创建资源”型接口；若后续新增则用于创建成功） | — |
| `204` | — | 预留（本版更新接口均返回更新后对象） | — |
| `400` | `BAD_REQUEST` | 请求无法解析：非法 JSON、非法 Content-Type、重复查询参数 | 提示“请求格式错误”并记录 request_id |
| `404` | `SESSION_NOT_FOUND` | 时间线接口的 `session_id` 不存在 | 页面显示“会话不存在”，回退列表 |
| `404` | `ATTACKER_NOT_FOUND` | 详情接口的 `source_ip` 无画像记录 | 页面显示“暂无该来源画像” |
| `404` | `ALERT_NOT_FOUND` | `alert_id` 不存在 | 刷新列表并提示已被移除 |
| `404` | `RULE_NOT_FOUND` | `rule_code` 不存在 | 刷新规则列表 |
| `404` | `NOT_FOUND` | 未注册的路径（兜底） | 提示接口不存在（前端发版不一致时排查） |
| `409` | `RULE_VERSION_CONFLICT` | 规则更新时 `expected_version` 与当前版本不一致（并发或过期页面） | 提示“规则已被修改”，重新拉取后再提交 |
| `409` | `IDEMPOTENCY_CONFLICT` | 同一 `event_uuid` 重复提交但内容摘要不一致（内部/CLI 场景） | 不在页面出现；运行日志记录 |
| `422` | `VALIDATION_ERROR` | 分页、排序、枚举、请求体字段、长度、类型不合法 | 定位到具体字段并提示 |
| `422` | `SORT_FIELD_INVALID` | `sort` 不在白名单 | 回落到默认排序并提示 |
| `422` | `TIME_RANGE_INVALID` | `from`/`to` 格式错误或 `from > to` | 重置筛选条件提示 |
| `422` | `IP_FORMAT_INVALID` | 路径参数 `source_ip` 不是合法 IPv4/IPv6 | 提示地址格式错误 |
| `500` | `INTERNAL_ERROR` | 未预期异常 | 显示“服务异常”，记录 request_id |
| `500` | `DATA_INCONSISTENT` | 视图/明细数据违反契约（例如计数为负、分数越界） | 显示异常并提供 request_id |
| `503` | `DB_UNAVAILABLE` | 数据库连接失败/不可用 | 顶部横幅“数据库不可用”，轮询健康检查 |
| `503` | `DB_TIMEOUT` | 查询超过 3 秒超时 | 显示“查询超时，请缩小筛选范围” |
| `503` | `HONEYPOT_UNAVAILABLE` | 健康检查场景下诱饵服务不可达（仅 `/api/health` 返回降级信息） | 概览页显示诱饵状态为降级 |
| `503` | `SERVICE_UNAVAILABLE` | 服务启动未完成/优雅停机中 | 自动重试 |

**错误码与 HTTP 状态码的映射在实现中必须是单一映射表**（不允许同一 `code` 在不同接口
返回不同状态码），便于前端集中处理与测试断言。

---

## 2. 接口总览

| 序号 | 方法 | 路径 | 分类 | 用途 | 数据来源 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/health` | 只读 | 健康检查与依赖状态 | `SELECT 1`、服务内部状态 |
| 2 | GET | `/api/overview` | 只读 | 首页四项指标 | `v_session_risk_summary`、`v_attacker_profile_summary` |
| 3 | GET | `/api/attackers` | 只读 | 攻击者列表（分页） | `v_attacker_profile_summary` |
| 4 | GET | `/api/attackers/{ip}` | 只读 | 攻击者详情与意图、会话摘要 | `attacker_profile`、`attacker_intent`、`v_session_risk_summary`、`rule_hits` |
| 5 | GET | `/api/sessions/{session_id}/timeline` | 只读 | 会话时间线与证据 | `sessions`、`attack_log`、`rule_hits`、`alerts` |
| 6 | GET | `/api/alerts` | 只读 | 告警列表（筛选+分页） | `alerts`（JOIN `rule_hits`/`detection_rules` 取证据摘要） |
| 7 | PATCH | `/api/alerts/{alert_id}` | **写** | 告警已读状态 | `alerts` |
| 8 | GET | `/api/rules` | 只读 | 规则配置列表 | `detection_rules` |
| 9 | PATCH | `/api/rules/{rule_code}` | **写** | 规则变更并生成新版本 | `detection_rules`（事务内版本自增） |
| 10 | GET | `/api/trend` | 只读 | 每日攻击趋势 | `v_daily_attack_trend` |
| 11 | GET | `/api/rules/effectiveness` | 只读 | 规则效果统计 | `v_rule_effectiveness` |

**合成样本导入不提供 HTTP 接口**，改用命令行脚本（见第 4 章，含脚本契约与明确理由）。

---

## 3. 接口详情

### 3.1 GET /api/health

**用途**：启动自检、演示前检查、前端降级横幅。

**请求参数**：无。

**成功响应 `200`**：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": {"status": "ok", "latency_ms": 3},
  "honeypot": {"status": "ok", "listen": "127.0.0.1:3307", "accepted_connections": 12},
  "generated_at": "2026-11-19T12:30:48Z"
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 否 | `ok` / `degraded`；`degraded` 时 HTTP 为 `503` |
| `version` | string | 否 | 后端版本（与 `pyproject.toml` 一致） |
| `database.status` | string | 否 | `ok` / `down`；通过 `SELECT 1` 探测，超时 1 秒 |
| `database.latency_ms` | integer | 是 | 探测耗时；`database.status=down` 时为 `null` |
| `honeypot.status` | string | 否 | `ok` / `down` / `disabled`（降级为真实 MySQL 方案时为 `disabled`） |
| `honeypot.listen` | string | 是 | `host:port`；`disabled` 时为 `null` |
| `honeypot.accepted_connections` | integer | 否 | 进程启动以来的累计接受连接数（仅内存计数，不代表入库条数） |
| `generated_at` | string | 否 | 响应生成时间（UTC） |

**错误**：数据库不可用时返回 `503`：

```json
{
  "status": "degraded",
  "version": "0.1.0",
  "database": {"status": "down", "latency_ms": null},
  "honeypot": {"status": "ok", "listen": "127.0.0.1:3307", "accepted_connections": 0},
  "generated_at": "2026-11-19T12:31:05Z",
  "code": "DB_UNAVAILABLE",
  "message": "数据库连接不可用",
  "detail": {"stage": "connect"},
  "request_id": "6f1c2f4e-8a3b-4f5d-9c1e-2b7d0a9e5c11"
}
```

**安全**：不返回数据库连接串、主机名、账号、环境变量；`detail.stage` 只说明失败阶段。

---

### 3.2 GET /api/overview

**用途**：首页概览四项指标（FR-062）。

**请求参数**：无（本版统计范围为演示库全量累计数据，不做时间窗口筛选；趋势另见 `/api/trend`）。

**成功响应 `200`**：

```json
{
  "sessions": 3,
  "queries": 12,
  "alerts": 2,
  "high_risk_attackers": 1,
  "generated_at": "2026-11-19T12:30:48Z"
}
```

| 字段 | 类型 | 说明 | 数据来源视图与口径 |
| --- | --- | --- | --- |
| `sessions` | integer | 连接数（会话总数） | `v_session_risk_summary` 的行数（每个 `session_id` 一行） |
| `queries` | integer | 查询数（查询类事件总数） | `SUM(v_session_risk_summary.query_count)`（只计 `event_type='query'`） |
| `alerts` | integer | 告警总数 | `SUM(v_session_risk_summary.alert_count)`，应与 `alerts` 表 `COUNT(*)` 一致 |
| `high_risk_attackers` | integer | 高风险攻击者数 | `v_attacker_profile_summary` 中 `risk_level IN ('high','critical')` 的来源地址数量 |
| `generated_at` | string | 响应生成时间（UTC） | 数据库 `UTC_TIMESTAMP()` 或应用时钟 |

**口径说明（答辩必须能讲清）**：

1. 四个数字**全部来自两个核心视图**，不直接拼装明细表，保证页面数字与“现场执行的视图
   `SELECT` 语句”完全一致（SC-009/SC-010）。
2. `sessions` 是累计值，不因会话关闭而减少；`queries` 只统计 `event_type='query'` 的事件，
   认证与连接事件不计入。
3. 高风险攻击者按**画像风险等级**判断（`high` 60–79、`critical` 80–100），不是“有高危告警
   的来源数”；两者口径不同，页面文案必须写“高风险攻击者”。
4. 空库时返回 `{"sessions":0,"queries":0,"alerts":0,"high_risk_attackers":0}`，不报错
   （FR-069/SC-009）。

**错误**：`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

---

### 3.3 GET /api/attackers

**用途**：攻击者列表（FR-063），分页、排序、可选筛选。

**请求参数**：

| 参数 | 位置 | 类型 | 必填 | 默认 | 约束/说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | query | integer | 否 | 1 | `>= 1` |
| `page_size` | query | integer | 否 | 20 | `1..100` |
| `sort` | query | string | 否 | `risk_score` | 白名单：`risk_score`、`last_seen`、`first_seen`、`total_queries` |
| `order` | query | string | 否 | `desc` | `asc`/`desc` |
| `risk_level` | query | string | 否 | — | 可重复或逗号分隔：`low,medium,high,critical` |
| `intent_type` | query | string | 否 | — | 可重复或逗号分隔：`scanning,bruteforce,recon,data_dump,destructive` |

**默认排序**：`risk_score DESC, last_seen DESC, source_ip ASC`（第三键保证稳定分页）。
**指定 `sort=last_seen` 时**：`last_seen DESC, source_ip ASC`；`sort=risk_score` 时同上默认。

**成功响应 `200`**：

```json
{
  "items": [
    {
      "attacker_id": 1,
      "source_ip": "198.51.100.23",
      "first_seen": "2026-11-19T10:02:11Z",
      "last_seen": "2026-11-19T12:28:03Z",
      "total_connections": 12,
      "total_auth_attempts": 9,
      "total_queries": 34,
      "main_intent": {
        "intent_type": "destructive",
        "intent_score": 35,
        "evidence_count": 1,
        "last_detected_at": "2026-11-19T12:27:50Z"
      },
      "risk_score": 85,
      "risk_level": "critical",
      "alert_count": 2
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1,
  "total_pages": 1
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `attacker_id` | integer | 否 | 画像主键，用于前端缓存与跳转 |
| `source_ip` | string | 否 | 攻击者聚合键（IPv4/IPv6），同时是详情接口路径参数 |
| `first_seen` | string | 否 | 该来源最早会话开始时间 |
| `last_seen` | string | 否 | 该来源最近事件时间 |
| `total_connections` | integer | 否 | 累计会话数 |
| `total_auth_attempts` | integer | 否 | 累计认证尝试数（成功与失败都计，FR-014/边界情况） |
| `total_queries` | integer | 否 | 累计查询事件数 |
| `main_intent` | object \| null | 是 | 主要意图；无意图命中时为 `null` |
| `main_intent.intent_type` | string | 否 | `scanning`/`bruteforce`/`recon`/`data_dump`/`destructive` |
| `main_intent.intent_score` | integer | 否 | 该意图累计可信分 0–100 |
| `main_intent.evidence_count` | integer | 否 | 支持该意图的规则命中次数 |
| `main_intent.last_detected_at` | string | 否 | 最近识别时间 |
| `risk_score` | integer | 否 | 来源画像风险分 0–100（封顶） |
| `risk_level` | string | 否 | `low`/`medium`/`high`/`critical`，由 `risk_score` 按 0–29/30–59/60–79/80–100 映射 |
| `alert_count` | integer | 否 | 该来源关联告警数（按 `attacker_id` 统计） |

**字段来源**：`v_attacker_profile_summary`（`risk_score` 取画像存储值，`risk_level` 为
生成列；`main_intent` 由视图的 `primary_intent_type/primary_intent_score/...` 映射而来，
主要意图按分数、最近时间、危害程度排序得出，不在画像表存多值列表，FR-025/FR-050）；
`alert_count` 由视图聚合提供。

**错误**：`422 VALIDATION_ERROR`（分页越界、枚举非法）、`422 SORT_FIELD_INVALID`、
`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

**排序稳定性要求**：同一 `risk_score` 与 `last_seen` 的多条记录必须由 `source_ip` 决定顺序，
否则翻页会重复或漏项（SC-009）。

---

### 3.4 GET /api/attackers/{ip}

**用途**：攻击者详情页（FR-064）：画像统计、意图列表、会话摘要、最近规则证据。

**路径参数**：`ip`（string，必填）：IPv4 或 IPv6 字面量（与会话/画像中的规范化文本一致）。
格式非法 → `422 IP_FORMAT_INVALID`；合法但无画像 → `404 ATTACKER_NOT_FOUND`。

**查询参数**：

| 参数 | 类型 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `session_limit` | integer | 50 | `1..200` | 会话摘要条数上限（按 `started_at DESC, session_id ASC`） |
| `hit_limit` | integer | 20 | `1..100` | 最近规则命中条数上限 |

**成功响应 `200`**：

```json
{
  "attacker": {
    "attacker_id": 1,
    "source_ip": "198.51.100.23",
    "first_seen": "2026-11-19T10:02:11Z",
    "last_seen": "2026-11-19T12:28:03Z",
    "total_connections": 12,
    "total_auth_attempts": 9,
    "total_auth_failures": 6,
    "total_queries": 34,
    "risk_score": 85,
    "calculated_risk_score": 85,
    "risk_level": "critical",
    "session_count": 12,
    "high_risk_session_count": 0,
    "alert_count": 2,
    "unread_alert_count": 1,
    "intent_labels": "destructive,bruteforce,recon,scanning",
    "triggered_rule_codes": "R01,R02,R03,R05",
    "evidence_summary": "命中 R02 爆破（认证尝试 9 次/凭据 6 组）与 R05 破坏性操作（DROP TABLE orders）"
  },
  "intents": [
    {
      "intent_type": "scanning",
      "intent_score": 10,
      "evidence_count": 1,
      "first_detected_at": "2026-11-19T10:02:30Z",
      "last_detected_at": "2026-11-19T10:02:30Z"
    },
    {
      "intent_type": "bruteforce",
      "intent_score": 25,
      "evidence_count": 1,
      "first_detected_at": "2026-11-19T10:05:02Z",
      "last_detected_at": "2026-11-19T10:05:02Z"
    },
    {
      "intent_type": "recon",
      "intent_score": 15,
      "evidence_count": 1,
      "first_detected_at": "2026-11-19T10:06:40Z",
      "last_detected_at": "2026-11-19T10:06:40Z"
    },
    {
      "intent_type": "destructive",
      "intent_score": 35,
      "evidence_count": 1,
      "first_detected_at": "2026-11-19T12:27:50Z",
      "last_detected_at": "2026-11-19T12:27:50Z"
    }
  ],
  "sessions": [
    {
      "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
      "source_port": 51234,
      "target_service": "mysql-honeypot",
      "started_at": "2026-11-19T12:27:10Z",
      "ended_at": "2026-11-19T12:28:03Z",
      "session_status": "closed",
      "event_count": 7,
      "query_count": 4,
      "hit_rule_count": 2,
      "hit_rule_codes": "R03,R05",
      "risk_score": 50,
      "risk_level": "medium",
      "stored_max_risk_score": 50,
      "alert_count": 1
    }
  ],
  "recent_rule_hits": [
    {
      "hit_id": 42,
      "event_id": 118,
      "rule_code": "R05",
      "rule_name": "破坏性操作检测",
      "intent_type": "destructive",
      "rule_version": 1,
      "risk_weight": 35,
      "triggered_at": "2026-11-19T12:27:50Z",
      "evidence_summary": "规则 R05：语句类型 DROP，对象 orders，已按权限不足拒绝"
    }
  ]
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `attacker` | object | 否 | 画像统计；字段取自 `attacker_profile` 与 `v_attacker_profile_summary`（重算值） |
| `attacker.risk_score` | integer | 否 | `attacker_profile.risk_score`（存储值） |
| `attacker.calculated_risk_score` | integer | 否 | 视图重算值；与 `risk_score` 不一致说明数据漂移，必须记录运行日志并在测试中断言相等 |
| `attacker.risk_level` | string | 否 | 生成列，严格按 0–29/30–59/60–79/80–100 映射 |
| `attacker.total_auth_failures` | integer | 否 | 认证失败次数（成功与失败都计入 `total_auth_attempts`） |
| `attacker.session_count` | integer | 否 | 该来源会话总数（视图聚合） |
| `attacker.high_risk_session_count` | integer | 否 | 该来源 `calculated_risk_score >= 60` 的会话数 |
| `attacker.unread_alert_count` | integer | 否 | 未读告警数 |
| `attacker.triggered_rule_codes` | string \| null | 是 | 触发过的规则编码串（视图 `GROUP_CONCAT`，仅展示用） |
| `attacker.intent_labels` | string \| null | 是 | 意图标签串（视图 `GROUP_CONCAT`，仅展示用；**不落库**，FR-025） |
| `intents` | array | 否 | 按 `intent_score DESC, last_detected_at DESC, intent_type ASC` 排序；无意图为 `[]` |
| `sessions` | array | 否 | 会话摘要，按 `started_at DESC, session_id ASC`，最多 `session_limit` 条；字段取自 `v_session_risk_summary` |
| `sessions[].risk_score` | integer | 否 | 该会话重算风险分（视图 `calculated_risk_score`） |
| `sessions[].stored_max_risk_score` | integer | 否 | `sessions.max_risk_score` 存储值，用于与重算值对照 |
| `sessions[].hit_rule_codes` | string \| null | 是 | 该会话命中的规则编码串；无命中为 `null` |
| `recent_rule_hits` | array | 否 | 按 `triggered_at DESC, hit_id DESC` 排序，最多 `hit_limit` 条 |
| `recent_rule_hits[].risk_weight` | integer | 否 | 命中时的权重快照（历史证据在规则调整后仍可解释，FR-052） |
| `recent_rule_hits[].rule_version` | integer | 否 | 命中时实际采用的规则版本快照 |

**说明**：示例为控制篇幅只截取了 1 条 `sessions` 与 1 条 `recent_rule_hits`。示例中画像分
85 = R01(10) + R02(25) + R03(15) + R05(35) 按规则去重求和，故 `risk_level=critical`；所示会话
只命中 R03+R05=50，故会话分为 50、`risk_level=medium`、`high_risk_session_count=0`。
`recent_rule_hits.evidence_summary` 必须说明“为什么命中”，禁止只给标签（FR-051）。

**错误**：`422 IP_FORMAT_INVALID`、`422 VALIDATION_ERROR`、`404 ATTACKER_NOT_FOUND`、
`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

---

### 3.5 GET /api/sessions/{session_id}/timeline

**用途**：会话时间线（FR-065、SC-003）：会话头 + 按时间排序的事件 + 规则命中 + 告警。

**路径参数**：`session_id`（string，必填，UUID v4 文本，36 字符）。不存在 →
`404 SESSION_NOT_FOUND`。

**成功响应 `200`**：

```json
{
  "session": {
    "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
    "source_ip": "198.51.100.23",
    "source_port": 51234,
    "target_service": "mysql-honeypot",
    "client_fingerprint": "mysql-cli/8.4.0 db=honeypot_shop charset=utf8mb4",
    "started_at": "2026-11-19T12:27:10Z",
    "ended_at": "2026-11-19T12:28:03Z",
    "session_status": "closed",
    "request_count": 7,
    "event_count": 7,
    "query_count": 4,
    "max_risk_score": 50,
    "calculated_risk_score": 50,
    "risk_level": "medium",
    "alert_count": 1
  },
  "events": [
    {
      "event_id": 111,
      "event_uuid": "3f2a9c1e-5b7d-4c8a-9e10-2d4f6a8b0c12",
      "event_type": "connect",
      "event_time": "2026-11-19T12:27:10Z",
      "source_ip": "198.51.100.23",
      "username": null,
      "credential_test_id": null,
      "credential_masked": null,
      "sql_statement": null,
      "normalized_sql": null,
      "statement_type": null,
      "returned_rows": 0,
      "response_ms": 0,
      "status": "success",
      "payload_truncated": false
    }
  ],
  "rule_hits": [
    {
      "hit_id": 42,
      "event_id": 118,
      "rule_code": "R05",
      "rule_name": "破坏性操作检测",
      "intent_type": "destructive",
      "rule_version": 1,
      "risk_weight": 35,
      "triggered_at": "2026-11-19T12:27:50Z",
      "evidence_summary": "规则 R05：语句类型 DROP，对象 orders，已按权限不足拒绝"
    }
  ],
  "alerts": [
    {
      "alert_id": 7,
      "alert_type": "destructive",
      "severity": "critical",
      "title": "检测到破坏性操作",
      "occurrence_count": 1,
      "created_at": "2026-11-19T12:27:51Z",
      "is_read": false
    }
  ],
  "events_truncated": false
}
```

**字段与排序规则**：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session` | object | 会话头；`ended_at` 在 `session_status='active'` 时为 `null` |
| `session.request_count` | integer | `sessions.request_count` 存储值；与 `event_count`（视图重算值）必须一致 |
| `session.event_count` | integer | `v_session_risk_summary.event_count` 重算值 |
| `session.max_risk_score` | integer | `sessions.max_risk_score` 存储值 |
| `session.calculated_risk_score` | integer | 视图重算值，与存储值对照；不一致说明数据漂移 |
| `session.risk_level` | string | 由重算分按 0–29/30–59/60–79/80–100 映射 |
| `events` | array | **按 `event_time ASC, event_id ASC` 稳定排序**；`event_id` 是自增主键，作为并列时间戳的确定性次级键（FR-018/SC-003） |
| `events[].event_id` | integer | 持久化事件序号，同时作为前端列表 `key` 与稳定排序键 |
| `events[].event_uuid` | string | 幂等键（UUIDv4 小写带连字符），用于演示“重复提交不重复计数” |
| `events[].event_type` | string | `connect`/`auth`/`query`/`disconnect` |
| `events[].status` | string | `success`/`failure`/`denied`/`error` |
| `events[].sql_statement` | string \| null | 原始 SQL，超长按 `payload_truncated` 标记；展示时只渲染为纯文本 |
| `events[].normalized_sql` | string \| null | 标准化 SQL（字面量替换、空白折叠、小写），用于规则归因展示 |
| `events[].statement_type` | string \| null | 由 `normalized_sql` 派生的语句类型（不落库） |
| `events[].returned_rows` | integer | 返回行数；非查询事件为 `0` |
| `events[].response_ms` | integer | 模拟响应耗时（毫秒） |
| `events[].credential_masked` | string \| null | 认证事件固定为 `"****"`；其他事件为 `null`；**永不返回明文口令** |
| `events[].payload_truncated` | boolean | SQL 或用户名是否被截断 |
| `rule_hits` | array | 按 `triggered_at ASC, hit_id ASC` 排序，便于与事件时间线对齐 |
| `alerts` | array | 按 `created_at ASC, alert_id ASC` 排序 |
| `events_truncated` | boolean | 事件数超过单会话返回上限（默认 1000）时为 `true`，此时 `events` 只含前 1000 条（仍按上述顺序） |

**错误**：`404 SESSION_NOT_FOUND`、`422 VALIDATION_ERROR`、`503 DB_UNAVAILABLE`、
`500 INTERNAL_ERROR`。

**空数据**：会话存在但无规则命中或告警时，`rule_hits` 与 `alerts` 返回 `[]`。

---

### 3.6 GET /api/alerts

**用途**：告警列表与筛选（FR-056/FR-066）。

**请求参数**：

| 参数 | 类型 | 默认 | 约束/说明 |
| --- | --- | --- | --- |
| `page` | integer | 1 | `>= 1` |
| `page_size` | integer | 20 | `1..100` |
| `alert_type` | string | — | 可重复或逗号分隔：`bruteforce`/`data_dump`/`destructive` |
| `severity` | string | — | 可重复或逗号分隔：`low`/`medium`/`high`/`critical` |
| `is_read` | boolean | — | `true`/`false`；传 `1/0` 视为非法 → `422` |
| `from` | string | — | 起始时间（含），ISO 8601 UTC 或 `YYYY-MM-DD` |
| `to` | string | — | 结束时间（不含）；`from > to` → `422 TIME_RANGE_INVALID` |
| `sort` | string | `created_at` | 白名单：`created_at`、`severity` |
| `order` | string | `desc` | `asc`/`desc` |

**默认排序**：`created_at DESC, alert_id DESC`（`alert_id` 为稳定次级键）。
`sort=severity` 时：`severity_rank DESC, created_at DESC, alert_id DESC`（严重度排序按
`critical > high > medium > low`，不使用字符串字典序）。

**成功响应 `200`**：

```json
{
  "items": [
    {
      "alert_id": 7,
      "dedup_key": "R05:198.51.100.23:2026-11-19",
      "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
      "attacker_id": 1,
      "source_ip": "198.51.100.23",
      "rule_code": "R05",
      "rule_name": "破坏性操作检测",
      "latest_hit_id": 42,
      "alert_type": "destructive",
      "severity": "critical",
      "title": "检测到破坏性操作",
      "evidence_summary": "规则 R05：会话内出现 DROP TABLE orders，已按权限不足拒绝",
      "first_seen_at": "2026-11-19T12:27:51Z",
      "last_seen_at": "2026-11-19T12:27:51Z",
      "occurrence_count": 1,
      "created_at": "2026-11-19T12:27:51Z",
      "is_read": false,
      "read_at": null
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1,
  "total_pages": 1
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `alert_id` | integer | 否 | 告警主键，用于 PATCH 路径参数 |
| `dedup_key` | string | 否 | 去重键 `<rule_code>:<source_ip>:<YYYY-MM-DD>`（UTC 日期），只读；用于答辩说明“同日同规则同来源只一条告警”（FR-059） |
| `session_id` | string | 否 | 首次触发告警的会话（外键保证存在） |
| `attacker_id` | integer | 否 | 关联画像 |
| `source_ip` | string | 否 | 反查画像得到的来源地址，便于列表直接展示 |
| `rule_code` | string | 否 | 触发规则编码快照（如 `R05`） |
| `rule_name` | string | 否 | 触发规则当前名称（JOIN `detection_rules` 得到，仅展示用） |
| `latest_hit_id` | integer | 否 | 最近一次触发该告警的 `rule_hits.hit_id`，证据可定位（FR-057/SC-006） |
| `alert_type` | string | 否 | `bruteforce`/`data_dump`/`destructive`（仅这三类意图生成告警） |
| `severity` | string | 否 | `low`/`medium`/`high`/`critical`；**按规则固定映射**：R02→medium、R04→high、R05→critical（不随分数变化） |
| `title` | string | 否 | 中文短标题，≤ 200 字符 |
| `evidence_summary` | string | 否 | 证据摘要，≤ 1024 字符，说明规则编码、语句类型/统计值 |
| `first_seen_at` | string | 否 | 首次触发时间（UTC）；重复触发不改变 |
| `last_seen_at` | string | 否 | 最近触发时间（UTC）；重复触发取 GREATEST |
| `occurrence_count` | integer | 否 | 触发次数；首次为 1，重复触发 +1 |
| `created_at` | string | 否 | 行创建（首次告警）时间（UTC） |
| `is_read` | boolean | 否 | 已读状态 |
| `read_at` | string \| null | 是 | 首次置为已读的时间；`is_read=false` 时为 `null` |

**错误**：`422 VALIDATION_ERROR`（分页、枚举、`is_read` 非布尔）、`422 SORT_FIELD_INVALID`、
`422 TIME_RANGE_INVALID`、`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

**空数据**：无匹配返回 `items: []` 与 `total: 0`（FR-056/FR-069），不返回 404。

---

### 3.7 PATCH /api/alerts/{alert_id}

**用途**：更新告警已读状态（FR-058，系统仅有的两个写接口之一）。

**路径参数**：`alert_id`（integer，正整数）。不存在 → `404 ALERT_NOT_FOUND`。

**请求体**（严格模式，多余字段 → `422`）：

```json
{"is_read": true}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `is_read` | boolean | 是 | 只能是 JSON 布尔 `true`/`false`；缺字段、`null`、字符串 `"true"` → `422 VALIDATION_ERROR` |

**成功响应 `200`**：返回更新后的完整告警对象（结构同 3.6 的 `items[]` 元素）。

```json
{
  "alert_id": 7,
  "dedup_key": "R05:198.51.100.23:2026-11-19",
  "session_id": "9f2c7a1b-4d5e-4f70-8a9b-0c1d2e3f4a5b",
  "attacker_id": 1,
  "source_ip": "198.51.100.23",
  "rule_code": "R05",
  "rule_name": "破坏性操作检测",
  "latest_hit_id": 42,
  "alert_type": "destructive",
  "severity": "critical",
  "title": "检测到破坏性操作",
  "evidence_summary": "规则 R05：会话内出现 DROP TABLE orders，已按权限不足拒绝",
  "first_seen_at": "2026-11-19T12:27:51Z",
  "last_seen_at": "2026-11-19T12:27:51Z",
  "occurrence_count": 1,
  "created_at": "2026-11-19T12:27:51Z",
  "is_read": true,
  "read_at": "2026-11-19T12:31:20Z"
}
```

**语义**：

- 置 `true`：若原本为 `false`，写 `is_read=1`、`read_at=UTC_TIMESTAMP(6)`；若原本已为
  `true`，**幂等成功**（`200`，`read_at` 保持不变，不刷新时间）。
- 置 `false`：`is_read=0`、`read_at=NULL`（允许撤回误标，演示可重复）。
- 每次成功更新写一条 `audit_log`（操作类型 `alert_read`，含 `alert_id` 与结果），审计记录
  独立提交，不随业务事务回滚（宪法“审计留痕”）。
- 并发：以数据库最后一次提交为准；接口在单事务内 `SELECT ... FOR UPDATE` 后写入，返回
  数据库实际状态，不返回“预期状态”。
- 本接口不做批量更新；`PATCH /api/alerts`（无 id）→ `404 NOT_FOUND`。

**错误**：`404 ALERT_NOT_FOUND`、`422 VALIDATION_ERROR`、`400 BAD_REQUEST`（非法 JSON）、
`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

---

### 3.8 GET /api/rules

**用途**：规则配置列表（FR-054、用户故事 8）。

**请求参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `include_history` | boolean | `false` | `true` 时返回该 `rule_code` 的全部历史版本，按 `rule_code ASC, rule_version DESC`；`false` 时每个 `rule_code` 只返回当前生效版本 |
| `enabled` | boolean | — | 可选筛选当前版本启用状态 |

**成功响应 `200`**（`include_history=false`）：

```json
{
  "items": [
    {
      "rule_id": 5,
      "rule_code": "R03",
      "rule_name": "结构探测（踩点）检测",
      "rule_type": "keyword",
      "intent_type": "recon",
      "parameters": {"keywords": ["SHOW", "DESCRIBE", "INFORMATION_SCHEMA"], "min_matches": 1},
      "risk_weight": 15,
      "rule_version": 2,
      "enabled": true,
      "description": "出现 SHOW / DESCRIBE / information_schema 查询时命中，证据摘要记录触发语句类型",
      "created_at": "2026-11-19T11:40:02Z",
      "updated_at": "2026-11-19T11:40:02Z"
    }
  ],
  "total": 5
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `rule_id` | integer | 当前版本行主键 |
| `rule_code` | string | 稳定编码 `R01`…`R08`；**不可修改**，是 PATCH 的路径参数 |
| `rule_name` | string | 中文名称 |
| `rule_type` | string | `frequency`/`keyword`/`sequence`/`volume`（对应总纲“规则类型”） |
| `intent_type` | string | `scanning`/`bruteforce`/`recon`/`data_dump`/`destructive` |
| `parameters` | object | 从 `parameters_json` 解析后的 JSON 对象；只保存单条规则内部阈值与窗口，不保存多实体 |
| `risk_weight` | integer | 0–100 命中权重 |
| `rule_version` | integer | 当前版本号（从 1 开始，每次 PATCH +1） |
| `enabled` | boolean | 是否参与检测 |
| `description` | string | 规则说明（可读解释，供答辩使用） |
| `created_at` | string | 该版本创建时间（UTC） |
| `updated_at` | string | 该版本最近更新时间（UTC）；PATCH 生成新版本后由数据库 `ON UPDATE` 维护 |

**版本语义（必须与 PATCH 一致）**：

- `detection_rules` 采用“同一 `rule_code` 多行版本”存储，`rule_code + rule_version` 复合唯一。
- **当前生效版本** = 该 `rule_code` 下 `rule_version` 最大的一行；`enabled` 以当前行为准。
- 历史版本行冻结保留（`enabled=false`），用于解释历史命中；`rule_hits` 另存
  `rule_version` 与 `risk_weight` 快照，即使规则行被清理也不影响证据展示。

**错误**：`422 VALIDATION_ERROR`、`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

---

### 3.9 PATCH /api/rules/{rule_code}

**用途**：规则变更并生成新版本（FR-054、FR-052、用户故事 8）。

**路径参数**：`rule_code`（string，`^R0[1-8]$`）。不存在 → `404 RULE_NOT_FOUND`。

**请求体**（严格模式；以下三项至少提供一项）：

```json
{
  "enabled": false,
  "parameters": {"window_seconds": 60, "min_connections": 10, "require_no_valid_sql": true},
  "risk_weight": 12,
  "expected_version": 2,
  "change_reason": "演示前把扫描阈值从 10 次调整为 8 次"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `enabled` | boolean | 否 | 启用/停用 |
| `parameters` | object | 否 | 必须满足该 `rule_code` 的参数模式（服务端按规则类型做结构化校验）；未知键 → `422` |
| `risk_weight` | integer | 否 | 0–100 |
| `expected_version` | integer | 否 | 乐观并发校验；与当前版本不一致 → `409 RULE_VERSION_CONFLICT` |
| `change_reason` | string | 否 | ≤ 200 字符，写入运行日志与审计记录，中文 |

**行为（事务 T3，事务内完成）**：

1. `SELECT ... FOR UPDATE` 读取该 `rule_code` 当前最大版本行（当前启用版本）。
2. 校验 `expected_version`（如提供）；不一致立即返回 `409`。
3. 计算 `new_version = current.rule_version + 1`；`rule_id` 由数据库自增生成。
4. **先将旧版本行 `enabled=0`**（冻结历史版本、腾出唯一启用位；生成列
   `enabled_rule_code` 的唯一约束要求同一 `rule_code` 至多一个启用版本，顺序不可颠倒）。
5. 插入新版本行：未提供的字段从当前版本复制；`parameters_json` 序列化后写入；
   `enabled` 取请求值（未提供时继承旧版本）；`created_at/updated_at` 取事务内 UTC 时间。
6. 写一条 `audit_log`（操作类型 `rule_update`，记录 `rule_code`、旧/新版本、变更字段摘要）。
7. 提交；任一步失败整体回滚，不产生半成品版本，旧版本仍保持原启用状态。

**成功响应 `200`**：返回新版本对象（结构同 3.8），并附加 `previous_version`：

```json
{
  "rule_id": 6,
  "rule_code": "R01",
  "rule_name": "扫描行为检测",
  "rule_type": "frequency",
  "intent_type": "scanning",
  "parameters": {"window_seconds": 60, "min_connections": 10, "require_no_valid_sql": true},
  "risk_weight": 12,
  "rule_version": 3,
  "enabled": true,
  "description": "60 秒内同一来源连接不少于 10 次且无有效 SQL",
  "created_at": "2026-11-19T12:35:10Z",
  "updated_at": "2026-11-19T12:35:10Z",
  "previous_version": 2
}
```

**版本自增与历史命中说明（答辩口径）**：

- 任何一次成功的 PATCH 都产生一个新版本号；**停用规则也算一次版本变更**（便于审计）。
- 新事件按“分析开始时读取到的当前生效版本”判定；已经存在的 `rule_hits` **不重算、不覆盖**，
  继续保存当时实际使用的 `rule_version` 与 `risk_weight` 快照（FR-052/SC-004）。
- 若需要按新版本重算历史，必须走独立的重算脚本并记录“重算范围、规则版本、结果口径”，
  不在本接口内隐式重算。
- 版本号只增不减；不提供删除版本或回滚接口（可通过再次 PATCH 生成“回滚版本”）。

**错误**：`404 RULE_NOT_FOUND`、`409 RULE_VERSION_CONFLICT`、`422 VALIDATION_ERROR`
（三项都未提供、权重越界、参数模式不匹配）、`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

---

### 3.10 GET /api/trend

**用途**：每日攻击趋势图（ECharts），数据来自 `v_daily_attack_trend`（CTE + 窗口函数
`LAG` 计算前一日变化）。

**请求参数**：

| 参数 | 类型 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `days` | integer | 14 | `1..90` | 以 UTC 今日为终点，向前取 `days` 个自然日（含今日） |

**成功响应 `200`**：

```json
{
  "days": 3,
  "items": [
    {
      "stat_date": "2026-11-17",
      "day_seq": 1,
      "event_count": 8,
      "session_count": 2,
      "source_count": 1,
      "query_count": 8,
      "denied_count": 0,
      "alert_count": 0,
      "high_level_alert_count": 0,
      "prev_event_count": null,
      "event_count_delta": null,
      "event_change_pct": null,
      "cumulative_event_count": 8,
      "busy_day_rank": 3
    },
    {
      "stat_date": "2026-11-18",
      "day_seq": 2,
      "event_count": 9,
      "session_count": 2,
      "source_count": 2,
      "query_count": 9,
      "denied_count": 1,
      "alert_count": 1,
      "high_level_alert_count": 1,
      "prev_event_count": 8,
      "event_count_delta": 1,
      "event_change_pct": 12.5,
      "cumulative_event_count": 17,
      "busy_day_rank": 2
    },
    {
      "stat_date": "2026-11-19",
      "day_seq": 3,
      "event_count": 12,
      "session_count": 3,
      "source_count": 2,
      "query_count": 12,
      "denied_count": 2,
      "alert_count": 2,
      "high_level_alert_count": 2,
      "prev_event_count": 9,
      "event_count_delta": 3,
      "event_change_pct": 33.33,
      "cumulative_event_count": 29,
      "busy_day_rank": 1
    }
  ]
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `days` | integer | 否 | 回显实际生效的天数 |
| `items[].stat_date` | string | 否 | UTC 日期 `YYYY-MM-DD` |
| `items[].day_seq` | integer | 否 | 返回序列内序号（从 1 开始，连续） |
| `items[].event_count` | integer | 否 | 当日事件数（含 connect/auth/query/disconnect） |
| `items[].session_count` | integer | 否 | 当日新建会话数 |
| `items[].source_count` | integer | 否 | 当日来源地址数 |
| `items[].query_count` | integer | 否 | 当日查询事件数 |
| `items[].denied_count` | integer | 否 | 当日被拒绝事件数 |
| `items[].alert_count` | integer | 否 | 当日新建告警数 |
| `items[].high_level_alert_count` | integer | 否 | 当日高等级（`high`/`critical`）告警数 |
| `items[].prev_event_count` | integer | 是 | 上一个有事件日的事件数；序列首行或补日行可能为 `null` |
| `items[].event_count_delta` | integer | 是 | 相对上一个有事件日的变化量，`null` 语义同 `prev_event_count` |
| `items[].event_change_pct` | number | 是 | 变化率（百分数，2 位小数）；前值为 0 或 `null` 时为 `null` |
| `items[].cumulative_event_count` | integer | 否 | 截至当日（含）的累计事件数 |
| `items[].busy_day_rank` | integer | 否 | 按 `event_count DESC` 的繁忙日排名（并列名次相同） |

**口径说明**：

1. 数据全部来自 `v_daily_attack_trend`，接口不做二次聚合，保证页面与视图查询一致。
2. 视图的 `LAG` 只在“有事件的日期”之间比较，**空白日不出现在视图中**；为保证折线连续，
   API 层按 `days` 生成连续 UTC 日历并补齐缺失日期：补日行的计数均为 `0`，
   `prev_event_count`/`event_count_delta`/`event_change_pct` 为 `null`，`day_seq` 与
   `cumulative_event_count` 连续；补点逻辑在 API 聚合层完成，**不在视图/前端**。
3. 统计日以 UTC 划分，与事件时间字段时区一致；`busy_day_rank` 在补日后的空白天排名为末位
   （按 0 计）。
4. 空库时返回 `days` 条全 0 行，不报错。

**错误**：`422 VALIDATION_ERROR`（`days` 越界/非整数）、`503 DB_UNAVAILABLE`、
`500 INTERNAL_ERROR`。

---

### 3.11 GET /api/rules/effectiveness

**用途**：规则效果展示（数据来自 `v_rule_effectiveness`，使用 `COUNT(DISTINCT ...)` 与
`RANK()` 窗口函数），用于答辩说明“每条规则实际抓到了什么”。

**请求参数**：

| 参数 | 类型 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `limit` | integer | 50 | `1..100` | 返回规则条数上限（按 `hit_rank ASC`） |

**成功响应 `200`**：

```json
{
  "items": [
    {
      "rule_code": "R05",
      "rule_name": "破坏性操作检测",
      "rule_type": "keyword",
      "intent_type": "destructive",
      "risk_weight": 35,
      "current_version": 1,
      "is_enabled": true,
      "hit_count": 12,
      "affected_session_count": 5,
      "affected_event_count": 12,
      "affected_attacker_count": 3,
      "used_version_count": 1,
      "first_hit_at": "2026-11-19T10:20:00Z",
      "last_hit_at": "2026-11-19T12:27:50Z",
      "alert_count": 4,
      "unread_alert_count": 2,
      "alert_per_hit_ratio": 0.3333,
      "hit_rank": 1
    }
  ],
  "total": 5
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `rule_code` | string | 否 | 规则编码 |
| `rule_name` | string | 否 | 当前版本名称 |
| `rule_type` | string | 否 | `frequency`/`keyword`/`sequence`/`volume` |
| `intent_type` | string | 否 | 目标意图 |
| `risk_weight` | integer | 否 | 当前版本权重（历史命中权重见 `rule_hits.risk_weight`） |
| `current_version` | integer | 否 | 当前生效版本号 |
| `is_enabled` | boolean | 否 | 当前版本启用状态（停用规则仍保留历史效果） |
| `hit_count` | integer | 否 | 命中次数 |
| `affected_session_count` | integer | 否 | 覆盖会话数 |
| `affected_event_count` | integer | 否 | 覆盖事件数 |
| `affected_attacker_count` | integer | 否 | 覆盖来源地址数 |
| `used_version_count` | integer | 否 | 历史命中实际使用过的版本数（证明版本快照可追溯） |
| `first_hit_at` | string | 是 | 首次命中时间；从未命中为 `null` |
| `last_hit_at` | string | 是 | 最近命中时间；从未命中为 `null` |
| `alert_count` | integer | 否 | 由该规则触发的告警数 |
| `unread_alert_count` | integer | 否 | 其中未读数 |
| `alert_per_hit_ratio` | number | 否 | `alert_count / hit_count`，4 位小数；`hit_count=0` 时为 `0.0000` |
| `hit_rank` | integer | 否 | 按 `hit_count DESC, rule_code ASC` 的排名（并列按编码稳定） |

**错误**：`422 VALIDATION_ERROR`、`503 DB_UNAVAILABLE`、`500 INTERNAL_ERROR`。

---

## 4. 合成样本导入：明确采用命令行脚本（不提供 HTTP 接口）

### 4.1 决策

**本版不提供 `POST /api/samples/import`。** 合成样本导入通过独立 CLI 脚本执行，理由：

1. **写接口白名单**：规格与总纲明确“展示层唯一的写操作是告警已读状态更新与规则配置”
   （spec.md 依赖与约束、FR-068）。样本导入会伪造“攻击证据”，若暴露为 HTTP 写接口，演示
   环境的证据链可被任意脚本篡改，与审计可信度冲突。
2. **职责边界**：样本是测试与演示夹具，属于“生成测试流量/可重复验证”能力（用户故事 9、
   FR-084），应走与模拟器同类的脚本入口，而不是控制台运行时接口。
3. **安全**：CLI 只在显式执行时运行，且可要求数据库为本地实例；HTTP 接口在演示期间始终
   暴露，误触或外部触发风险更高。
4. **可测试性**：脚本可返回退出码与稳定 JSON 摘要，直接用于测试矩阵与 `quickstart.md` 的
   端到端验收，不需要额外鉴权设施。

> 如后续确需 HTTP 化，必须走宪法变更流程（记录动机、影响范围、迁移方案），并新增独立的
> 管理端点前缀与网络限制；本版不预留该路径。

### 4.2 CLI 脚本契约

**入口**（实现层为 `uv` 管理的 Python 模块，脚本名是契约，不得随实现随意改名）：

```bash
uv run python -m app.cli.import_samples --set demo_basic
uv run python -m app.cli.import_samples --sample S03 --repeat 3
uv run python -m app.cli.import_samples --set demo_basic --dry-run
```

**参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--set` | string | — | 样本组名：`demo_basic`（S01–S07 全量，覆盖五条规则）、`recon_only`（S01–S03）；与 `--sample` 二选一，必填其一 |
| `--sample` | string | — | 单个样本编号：`S01`…`S07`，可重复 |
| `--repeat` | integer | 1 | 单样本重复导入次数（`1..20`），用于验证幂等 |
| `--dry-run` | flag | 关闭 | 只解析样本并打印将产生的会话/事件/命中/告警，不写数据库 |
| `--database-url` | string | 读 `.env` 的 `DATABASE_URL` | 只允许指向本机数据库（主机为 `127.0.0.1`/`localhost`/`::1`），否则拒绝执行并退出码 `3` |
| `--json` | flag | 开启（默认） | 向 stdout 输出机器可读 JSON 摘要；`--no-json` 时输出人类可读表格 |

**输出契约（stdout JSON）**：

```json
{
  "set": "demo_basic",
  "dry_run": false,
  "generated_at": "2026-11-19T12:40:00Z",
  "samples": [
    {"sample_id": "S03", "session_id": "1a2b3c4d-5e6f-7081-9203-142536475869", "event_count": 3, "rule_hits": ["R03"], "alerts": []}
  ],
  "imported": {"sessions": 1, "events": 3, "rule_hits": 1, "alerts": 0},
  "deduped": {"sessions": 0, "events": 0, "rule_hits": 0, "alerts": 0},
  "failed": [],
  "database": {"host": "127.0.0.1", "schema": "honeypot_demo"}
}
```

**退出码**：

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部成功（含幂等去重：`deduped` 非零仍算成功） |
| `1` | 部分样本失败（`failed` 非空），已成功的已提交 |
| `2` | 参数错误或样本文件缺失/校验失败 |
| `3` | 数据库不可达、目标非本机、迁移未执行 |

**幂等语义**：

- 样本夹具为每个事件**显式写明固定的 UUID 文本**（`event_uuid` 与 `session_id` 均为
  预先固定的 UUIDv4 字面量，同一 `sample_id` 每次导入完全一致；不在运行时随机生成），因此
  重复导入命中 `uk_attack_log_event_uuid` 返回已有 `event_id`，不新增日志、不重复累计计数与
  风险贡献（SC-011）；输出中对应记入 `deduped`。
- 同一 `session_id` 在夹具中固定，重复导入不会新建会话；固定值需符合 `CHAR(36)` UUID 文本
  格式，避免与协议层生成规则冲突（`events.md` 3.4）。
- 失败时单样本整体回滚，不残留半成品事件（事务口径见 `events.md` 第 6 章）。

**安全**：

- 样本文件为仓库内固定合成夹具，不含真实个人信息、真实口令或可用密钥；认证样本的
  `credential_test_id` 带 `TEST-ONLY` 标识。
- 脚本不连接诱饵端口、不发起任何网络探测、不执行样本中的 SQL；只把样本事件按标准事件
  契约写入存储与分析流水线（“只存不执行”不变量见 `events.md` 第 8 章）。

### 4.3 样本编号与预期效果

| 样本 | 内容 | 预期 |
| --- | --- | --- |
| `S01` | connect 事件（来源固定为文档保留网段 `198.51.100.0/24`） | 建立会话，`request_count=1` |
| `S02` | auth 失败事件（未知虚构账号，`credential_test_id="TEST-ONLY-S02"`） | `status=failure`，计入认证尝试 |
| `S03` | SHOW TABLES 查询事件 | 命中 **R03**，`recon` 意图 +15，会话风险分 15 |
| `S04` | 批量 SELECT（累计返回行数超过阈值） | 命中 **R04**，`data_dump` 意图 +25，生成 `data_dump` 告警（severity=`high`，固定映射） |
| `S05` | DROP TABLE 被拒绝事件 | 命中 **R05**，`destructive` 意图 +35，生成 `destructive` 告警（severity=`critical`，固定映射） |
| `S06` | 60 秒内同一来源 10 次 connect 且无有效 SQL（固定时间戳序列） | 命中 **R01**，`scanning` 意图 +10 |
| `S07` | 5 分钟内同一来源 8 次 auth 失败、6 组虚构用户名（固定序列） | 命中 **R02**，`bruteforce` 意图 +25，生成 `bruteforce` 告警（severity=`medium`，固定映射） |

**五条规则与样本对照（SC-004）**：R01→S06、R02→S07、R03→S03、R04→S04、R05→S05；
`demo_basic` 一次导入即可覆盖全部五条规则的固定样本。

---

## 5. 控制台页面与接口映射

四页范围固定（FR-061），不新增页面；规则配置接口用于演示与运维，不单独开页面。

| 页面 | 路由（前端） | 调用接口 | 关键交互 |
| --- | --- | --- | --- |
| 首页概览 | `/` | `GET /api/overview`；`GET /api/trend?days=14`；`GET /api/health` | 四张指标卡来自 overview；折线图来自 trend；健康检查失败时顶部降级横幅 |
| 攻击者列表 | `/attackers` | `GET /api/attackers?page=&page_size=&sort=&order=` | 翻页、按风险分/最近时间排序；点击行进入详情 |
| 攻击者详情 | `/attackers/:ip` | `GET /api/attackers/{ip}`；`GET /api/sessions/{session_id}/timeline`（选中会话时） | 画像统计、意图列表、会话摘要表、规则证据；会话弹层/抽屉按时间线渲染事件 |
| 告警列表 | `/alerts` | `GET /api/alerts?...`；`PATCH /api/alerts/{alert_id}` | 按类型/等级/已读/时间筛选；标记已读后就地更新行状态；点击证据跳转会话时间线（若提供 `session_id`） |

**页面-视图-接口三方一致性（SC-009/SC-010）**：

| 页面 | 主视图 | 直接可演示的查询 |
| --- | --- | --- |
| 首页概览 | `v_session_risk_summary`、`v_attacker_profile_summary` | 见 `quickstart.md` 场景 V10 |
| 攻击者列表 | `v_attacker_profile_summary` | 见 `quickstart.md` 场景 V11 |
| 攻击者详情 | `v_session_risk_summary` + 明细表 | 见 `quickstart.md` 场景 V12 |
| 告警列表 | `alerts` + `rule_hits` + `detection_rules` | 见 `quickstart.md` 场景 V13 |
| 趋势图 | `v_daily_attack_trend` | 见 `quickstart.md` 场景 V14 |
| 规则效果（答辩查询） | `v_rule_effectiveness` | 见 `quickstart.md` 场景 V15 |

**前端数据层要求**：

- 统一封装 `api` 客户端（fetch/axios 均可），集中处理错误体 `code` 与 `request_id` 提示；
- 所有接口响应字段使用 `snake_case`，前端不做驼峰转换，避免契约漂移；
- 列表请求失败时保留上一次成功数据并显示错误条，不整页白屏；
- 空数据统一走空态组件（`el-empty`），不显示 `NaN`/`undefined`。

---

## 6. 横切验收要点

| 编号 | 验收点 | 对应需求/标准 |
| --- | --- | --- |
| API-01 | 四个页面在空库与预置数据两种状态下均可用，数字与视图查询一致 | SC-009 |
| API-02 | 列表接口空结果返回 `items: []` 与 `total: 0`，未知会话/来源返回 404 契约错误 | FR-069 |
| API-03 | 分页 `page/page_size` 默认值与上限符合 1.4，越界返回 422 而非静默截断 | 本文档 1.4 |
| API-04 | 时间线按 `event_time ASC, event_id ASC` 稳定排序，重复查询顺序一致 | FR-018/SC-003 |
| API-05 | 任何响应与页面均不含明文口令，只出现 `credential_test_id` 与 `"****"` | FR-081/SC-007 |
| API-06 | 告警已读 PATCH 为独立写操作，返回值反映数据库实际状态 | FR-058 |
| API-07 | 规则 PATCH 生成新版本（版本 +1），历史命中保留旧版本与权重快照 | FR-052/SC-004 |
| API-08 | 四个核心视图分别被对应页面/接口使用，且每条都有可执行演示查询 | FR-033/SC-010 |
| API-09 | 错误响应恒含 `code`/`message`/`detail`/`request_id`，`code` 与状态码映射唯一 | 本文档 1.8/1.9 |
| API-10 | 只读接口使用只读数据库账号；写接口仅两条且均使用应用账号 | 宪法“最小权限”、FR-068 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 | 动机 |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-19 | 首次建立 `/api` 契约：11 个接口、统一错误与分页、页面映射、样本导入 CLI 决策 | 落实 spec.md 与总纲第七章接口约定，为 plan/tasks 提供可测试契约 |
| 1.1.0 | 2026-11-19 | 按 `data-model.md` 对齐字段与口径：`session_id` 改为 UUID v4；时间线事件字段映射（`payload_truncated`/派生 `statement_type`）；`rule_hits` 改用 `risk_weight`/`triggered_at`；告警字段改 `latest_hit_id`/`first_seen_at`/`occurrence_count`/`dedup_key`；告警等级固定映射；趋势与规则效果改用视图实际列名；规则 PATCH 版本顺序与审计写入对齐 T3；样本导入幂等改为夹具固定 UUID | 消除契约与数据模型的双轨命名，保证页面、接口与视图查询结果一致（SC-009/SC-010） |

**变更规则**：接口字段、状态码、排序与分页语义属于契约，修改前必须更新本文档并在
`plan.md` 的复杂度跟踪中记录影响范围；破坏性变更需同步更新前端类型与测试用例。
