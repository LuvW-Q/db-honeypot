# 接口契约增量：控制台接口扩展（v1.x 向后兼容）

**Feature**: `002-ui-console-modularization` | **Date**: 2026-11-25

本文件是 `specs/001-database-honeypot/contracts/api.md`（下称**基契约**）的**增量**，
不重述基契约已定义的信封、错误体、时间格式、分页与鉴权约定。冲突时基契约优先，
本文件只负责新增字段、新增端点与新参数。所有变更均为**加法**：既有字段名、类型、
语义、状态码不变；客户端可忽略未知字段（FR-123、SC-023）。

通用约定（沿用基契约 §1）：

- 响应时间均为 UTC ISO8601（带 `Z` 或 `+00:00`）；页面展示时转换为 UTC+8。
- 分页信封：`items/page/page_size/total/total_pages`。
- 错误体：`{code, message, detail, request_id}`；本文件新增错误码在 §9 列出。
- 查询参数一律白名单校验，非法 → `422 VALIDATION_ERROR`。
- 所有读接口使用只读账号；本文件**不新增写接口**。

---

## 1. 语义约定

### 1.1 时间范围 `range`

`range ∈ {all, 7d, 24h}`，默认 `all`。范围以**服务端当前 UTC 时刻**为终点：

| 值 | 窗口 | 说明 |
| --- | --- | --- |
| `all` | 全部历史 | `window_start = null` |
| `7d` | 最近 7×24 小时 | `window_start = now - 7d` |
| `24h` | 最近 24 小时 | `window_start = now - 24h` |

窗口对指标的应用口径（各端点一致）：

- 会话：`sessions.started_at >= window_start`；
- 查询/事件：`attack_log.event_time >= window_start`；
- 告警：`alerts.created_at >= window_start`；
- 攻击者：`attacker_profile.last_seen >= window_start`。

### 1.2 "今日/昨日"的时区

`today/yesterday` 统计固定使用 **UTC+8（Asia/Shanghai）自然日**——与页面时钟一致，
避免答辩时出现"今日"与界面时间错位。响应返回 `today_window`/`yesterday_window`
（UTC 起止时刻），供前端标注口径。该口径写入代码注释与本契约，不新增配置项。

### 1.3 派生字段

- `network_scope`：由来源 IP 派生——`private`（RFC1918/ULA）、`loopback`
  （127.0.0.0/8、::1）、`reserved`（RFC5737 TEST-NET、文档保留段）、`public`（其余）。
- `network_scope_label`：`内网`/`回环`/`文档保留`/`公网`（页面直接展示）。
- 派生值不落库、不新增表，纯函数实现于 M1（`shared.utils` 之上）。

---

## 2. `GET /api/overview`（扩展）

### 2.1 新增 query 参数

| 参数 | 类型 | 默认 | 约束 |
| --- | --- | --- | --- |
| `range` | string | `all` | 枚举 `all/7d/24h` |

### 2.2 响应新增字段（全部有默认值）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `range` | string | 回显生效范围 |
| `window_start` | string \| null | UTC 起止时刻；`all` 时为 `null` |
| `attackers_total` | int | 窗口内 `last_seen` 命中的攻击者总数 |
| `high_risk_ratio` | float | `high_risk_attackers / attackers_total`，0–1；分母 0 时 0.0 |
| `alerts_unread` | int | 窗口内未读告警数 |
| `alerts_by_severity` | object | `{low,medium,high,critical}` → 窗口内告警数 |
| `sessions_today` | int | 今日（UTC+8）会话数 |
| `queries_today` | int | 今日（UTC+8）查询事件数 |
| `sessions_delta_pct` | float \| null | 今日相对昨日会话数变化百分比（保留 1 位）；昨日为 0 → `null` |
| `queries_delta_pct` | float \| null | 同上，查询事件 |
| `query_blocked_rate` | float \| null | `denied_count / query_count`（窗口内），0–1；分母 0 → `null` |
| `today_window` | object | `{start, end}` UTC 时刻（半开区间） |
| `yesterday_window` | object | 同上 |

### 2.3 示例

```http
GET /api/overview?range=7d
```

```json
{
  "sessions": 128, "queries": 1376, "alerts": 9, "high_risk_attackers": 4,
  "generated_at": "2026-11-25T02:10:00Z",
  "range": "7d",
  "window_start": "2026-11-18T02:10:00Z",
  "attackers_total": 12,
  "high_risk_ratio": 0.3333,
  "alerts_unread": 5,
  "alerts_by_severity": {"low": 2, "medium": 3, "high": 3, "critical": 1},
  "sessions_today": 21,
  "queries_today": 240,
  "sessions_delta_pct": 16.7,
  "queries_delta_pct": -4.5,
  "query_blocked_rate": 0.087,
  "today_window": {"start": "2026-11-24T16:00:00Z", "end": "2026-11-25T16:00:00Z"},
  "yesterday_window": {"start": "2026-11-23T16:00:00Z", "end": "2026-11-24T16:00:00Z"}
}
```

---

## 3. `GET /api/trend`（扩展）

### 3.1 响应点新增字段

`TrendPoint` 在每个既有字段后追加（来自 `rule_hits` 按 UTC 统计日与意图族聚合，
无数据补 0）：

| 字段 | 类型 | 意图族（规则） |
| --- | --- | --- |
| `hit_bruteforce` | int | `bruteforce`（R02） |
| `hit_data_dump` | int | `data_dump`（R04） |
| `hit_scanning` | int | `scanning`（R01） |
| `hit_recon` | int | `recon`（R03） |
| `hit_destructive` | int | `destructive`（R05） |

规则：与 `v_daily_attack_trend` 的日期序列对齐；`days` 参数与补齐逻辑不变；
前端趋势图默认展示三条序列：爆破=`hit_bruteforce`、拖库/查询=`hit_data_dump`、
踩点扫描=`hit_scanning + hit_recon`；`hit_destructive` 作为图例可选/悬浮明细。

### 3.2 示例（片段）

```json
{"stat_date": "2026-11-24", "event_count": 310, "session_count": 26,
 "hit_bruteforce": 4, "hit_data_dump": 2, "hit_scanning": 5,
 "hit_recon": 3, "hit_destructive": 1, "...": "其余字段不变"}
```

---

## 4. `GET /api/alerts/summary`（新端点）

### 4.1 参数

| 参数 | 类型 | 默认 | 约束 |
| --- | --- | --- | --- |
| `from` | string | 无 | UTC 时刻；与 `to` 成对出现或同时缺省 |
| `to` | string | 无 | 必须晚于 `from`，窗口 ≤ 366 天 |

缺省时统计全部历史（与列表默认一致）。空库/无匹配返回全 0，不返回 404。

### 4.2 响应 `AlertSummaryResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | int | 告警总数（窗口内） |
| `unread` | int | 未读数 |
| `read` | int | 已读数（= `total - unread`） |
| `resolution_rate` | float | `read / total`，0–1；分母 0 → 0.0 |
| `by_severity` | object | 窗口内各等级总数 `{low,medium,high,critical}` |
| `unread_by_severity` | object | 未读中各等级数 |
| `by_alert_type` | object | `{bruteforce,data_dump,destructive}` → 数量（筛选项计数） |
| `today_new` | int | 今日（UTC+8）新增（`created_at`） |
| `yesterday_new` | int | 昨日（UTC+8）新增 |
| `today_delta_pct` | float \| null | 今日相对昨日新增百分比；昨日 0 → `null` |
| `peak_window` | object \| null | 今日按 1 小时分桶的告警最多时段：`{start,end,count}`（UTC 时刻）；今日无告警 → `null` |
| `today_window` | object | 今日 UTC+8 自然日对应的 UTC 半开区间 |
| `generated_at` | string | 响应生成时刻 |

### 4.3 示例

```json
{
  "total": 9, "unread": 5, "read": 4, "resolution_rate": 0.4444,
  "by_severity": {"low": 2, "medium": 3, "high": 3, "critical": 1},
  "unread_by_severity": {"low": 1, "medium": 2, "high": 1, "critical": 1},
  "by_alert_type": {"bruteforce": 4, "data_dump": 3, "destructive": 2},
  "today_new": 2, "yesterday_new": 3, "today_delta_pct": -33.3,
  "peak_window": {"start": "2026-11-25T01:00:00Z", "end": "2026-11-25T02:00:00Z", "count": 2},
  "today_window": {"start": "2026-11-24T16:00:00Z", "end": "2026-11-25T16:00:00Z"},
  "generated_at": "2026-11-25T02:10:00Z"
}
```

---

## 5. `GET /api/attackers/summary`（新端点）

### 5.1 参数

无。

### 5.2 响应 `AttackerSummaryResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | int | 攻击者总数（画像表行数） |
| `high_risk_count` | int | `risk_level ∈ {high, critical}` 的数量 |
| `latest_intent` | object \| null | 最近一次规则命中：`{intent_type, rule_code, rule_name, source_ip, last_detected_at}`；无命中 → `null` |
| `generated_at` | string | 响应生成时刻 |

### 5.3 示例

```json
{
  "total": 44, "high_risk_count": 14,
  "latest_intent": {"intent_type": "bruteforce", "rule_code": "R02",
                    "rule_name": "高频认证失败爆破探测", "source_ip": "203.0.113.42",
                    "last_detected_at": "2026-11-25T01:42:00Z"},
  "generated_at": "2026-11-25T02:10:00Z"
}
```

---

## 6. `GET /api/attackers`（扩展）

### 6.1 新增参数

| 参数 | 类型 | 默认 | 约束 |
| --- | --- | --- | --- |
| `q` | string | 无 | 1–64 字符，按 `source_ip` 子串匹配；`%`/`_`/`\` 转义；含控制字符 → 422；空白串视为未提供 |
| `sort` | string | `risk_score` | 新增允许值 `total_connections`；其余允许值不变 |

### 6.2 列表项新增字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `intent_labels` | string[] | 画像 `intent_labels` 拆分（去空、去重、顺序稳定） |
| `triggered_rule_codes` | string[] | 画像 `triggered_rule_codes` 拆分 |
| `network_scope` | string | 见 §1.3 |
| `network_scope_label` | string | 见 §1.3 |

### 6.3 排序稳定性

`sort=total_connections` 的 ORDER BY 为
`v.total_connections {order}, v.source_ip ASC`；其余排序的次级键与基契约 §3.3 一致。

---

## 7. `GET /api/attackers/{ip}`（扩展）

### 7.1 画像新增字段（`attacker` 对象内）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `avg_session_seconds` | int \| null | 该来源已结束会话的平均时长（秒，四舍五入）；无会话 → `null` |
| `auth_success_count` | int | `total_auth_attempts - total_auth_failures`，下限 0 |
| `high_risk_op_count` | int | `rule_hits` 中意图为 `data_dump`/`destructive` 的命中数 |
| `network_scope` | string | §1.3 |
| `network_scope_label` | string | §1.3 |

### 7.2 不变项

`intents`、`sessions`、`recent_rule_hits`、`session_limit`/`hit_limit` 参数与错误码
`ATTACKER_NOT_FOUND` 全部不变；`sessions[].query_count` 即页面"含 SQL 数"口径。

---

## 8. 兼容性规则

1. 本文件所有字段均为可选/带默认值；001 客户端与测试忽略新字段仍可通过。
2. 既有字段的类型与含义不变；`risk_score`、`risk_level`、`severity` 语义不变。
3. 本文件不新增写接口；`PATCH /api/alerts/{alert_id}` 的请求/响应不变。
4. 前端若需旧契约行为，可直接按基契约使用；`range` 缺省即 `all`（与 001 一致）。

---

## 9. 新增/复用错误码

| code | HTTP | 触发 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | `range` 非法、`q` 超长/含控制字符、`from/to` 不成对或窗口超限 |
| `ATTACKER_NOT_FOUND` | 404 | 详情 IP 不存在（既有） |
| `ALERT_NOT_FOUND` | 404 | 已读更新时告警不存在（既有） |
| `DB_UNAVAILABLE` | 503 | 数据库不可用（既有，健康检查与降级页使用） |

校验失败时 `detail` 采用基契约的字段级数组：
`[{field, reason, input}]`（`input` 截断到 64 字符，禁止回显敏感值）。

---

## 10. 新增查询的数据库约束

- 全部使用参数化 SQL，禁止拼接（宪法三）；
- 聚合查询必须带时间窗口上界或 `LIMIT`，窗口上限 366 天；
- 新增聚合只读 `sessions`/`attack_log`/`alerts`/`rule_hits`/`attacker_profile` 既有表
  与 4 个视图，**不新增索引、不新增视图**（DDL 不变）；
- 每个新查询在实现时给出 `EXPLAIN` 记录（存 M1 证据），证明使用既有索引或可接受
  的小表扫描。
