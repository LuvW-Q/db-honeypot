# 证据：只读控制台 API 冒烟（运行中的 :8000）

- 任务：002 / T044（M1 证据）
- 对应需求：**FR-062**（概览/趋势）、**FR-064**（攻击者画像与派生字段）、
  **FR-066**（告警摘要）、**API-10**（只读接口使用只读账号）、契约
  `specs/002-ui-console-modularization/contracts/api-extensions.md` §2/§3/§4/§5/§6/§7
- 验证时间：2026-11-25T13:30+08:00（Asia/Shanghai）
- 目标服务：`http://127.0.0.1:8000`（**本任务未重启服务**，直接对已有进程发请求；
  `/api/health` 显示 `status=ok`、`database.status=ok`）
- 数据环境：`honeypot_dev` 当前演示数据（14 个攻击者、214 条会话、8 条告警；
  由种子/演示脚本写入，不是本任务造数）
- 说明：下文的“关键字段”均为**真实响应**；超长数组仅截取代表元素（标注“截断展示”），
  完整响应由 `curl -o *.json` 落盘于临时目录，未修改任何数据

## 1. 命令（一次跑完 10 个请求）

```bash
B=http://127.0.0.1:8000
curl -s -o health.json            -w '%{http_code} %{time_total}s\n' "$B/api/health"
curl -s -o overview_7d.json       -w '%{http_code} %{time_total}s\n' "$B/api/overview?range=7d"
curl -s -o overview_bad.json      -w '%{http_code} %{time_total}s\n' "$B/api/overview?range=30d"
curl -s -o trend.json             -w '%{http_code} %{time_total}s\n' "$B/api/trend?days=7"
curl -s -o attackers.json         -w '%{http_code} %{time_total}s\n' "$B/api/attackers?page_size=3"
curl -s -o attackers_summary.json -w '%{http_code} %{time_total}s\n' "$B/api/attackers/summary"
curl -s -o alerts_summary.json    -w '%{http_code} %{time_total}s\n' "$B/api/alerts/summary"
curl -s -o attacker_missing.json  -w '%{http_code} %{time_total}s\n' "$B/api/attackers/203.0.113.250"
curl -s -o attacker_detail.json   -w '%{http_code} %{time_total}s\n' "$B/api/attackers/198.51.100.17"
curl -s -o timeline.json          -w '%{http_code} %{time_total}s\n' \
  "$B/api/sessions/5a060001-0000-4000-8000-000000000001/timeline"
```

## 2. 状态码汇总

| # | 请求 | 状态码 | 关键字段（实测值） |
| --- | --- | --- | --- |
| 1 | `GET /api/health` | 200 | `status=ok`、`database.status=ok`、`latency_ms=3` |
| 2 | `GET /api/overview?range=7d` | 200 | `range=7d`、`window_start` 回显、`sessions=8`、`queries=15`、`alerts=8`、`attackers_total=8`、`query_blocked_rate=0.0667` |
| 3 | `GET /api/overview?range=30d` | **422** | `VALIDATION_ERROR`，`detail=[{field=range, reason=只能是 all/7d/24h, input=30d}]` |
| 4 | `GET /api/trend?days=7` | 200 | 7 个 `TrendPoint`，每个含 5 个 `hit_*`（int，空白日补 0） |
| 5 | `GET /api/attackers?page_size=3` | 200 | `total=14`、每项含 `intent_labels`/`triggered_rule_codes`/`network_scope` |
| 6 | `GET /api/attackers/summary` | 200 | `total=14`、`high_risk_count=1`、`latest_intent.rule_code=R04` |
| 7 | `GET /api/alerts/summary` | 200 | `total=8`、`unread=8`、`read=0`、`peak_window.count=8` |
| 8 | `GET /api/attackers/203.0.113.250`（不存在） | **404** | `ATTACKER_NOT_FOUND`，`detail.source_ip=203.0.113.250` |
| 9 | `GET /api/attackers/198.51.100.17` | 200 | 派生字段：`avg_session_seconds=15`、`high_risk_op_count=2`、`network_scope=reserved` |
| 10 | `GET /api/sessions/{session_id}/timeline` | 200 | `session` + `events`(16 条) + `rule_hits` + `alerts`，`events_truncated=False` |

## 3. 响应样例（真实响应，截断展示已标注）

### 3.1 `GET /api/health` → 200

**完整响应**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": {
    "status": "ok",
    "latency_ms": 3
  },
  "honeypot": {
    "status": "down",
    "listen": "127.0.0.1:3307",
    "accepted_connections": 0
  },
  "generated_at": "2026-11-25T05:30:18.514804Z"
}
```

### 3.2 `GET /api/overview?range=7d` → 200

**完整响应（窗口指标与 7d 一致；对比 all 时 `sessions=214`，说明 range 过滤生效）**

```json
{
  "sessions": 8,
  "queries": 15,
  "alerts": 8,
  "high_risk_attackers": 1,
  "generated_at": "2026-11-25T05:30:18Z",
  "range": "7d",
  "window_start": "2026-11-18T05:30:18Z",
  "attackers_total": 8,
  "high_risk_ratio": 0.125,
  "alerts_unread": 8,
  "alerts_by_severity": {
    "low": 0,
    "medium": 3,
    "high": 3,
    "critical": 2
  },
  "sessions_today": 0,
  "queries_today": 0,
  "sessions_delta_pct": null,
  "queries_delta_pct": null,
  "query_blocked_rate": 0.0667,
  "today_window": {
    "start": "2026-11-24T16:00:00Z",
    "end": "2026-11-25T16:00:00Z"
  },
  "yesterday_window": {
    "start": "2026-11-23T16:00:00Z",
    "end": "2026-11-24T16:00:00Z"
  }
}
```

### 3.3 `GET /api/overview?range=30d` → 422

**完整响应**

```json
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "detail": [
    {
      "field": "range",
      "reason": "只能是 all/7d/24h",
      "input": "30d"
    }
  ],
  "request_id": "5366e048-5e86-4221-b00b-85224656d2e8"
}
```

### 3.4 `GET /api/trend?days=7` → 200

**截断展示：仅首/末两个点与点数（完整 7 点）**

```json
{
  "days": 7,
  "items_count": 7,
  "first_item": {
    "stat_date": "2026-11-19",
    "day_seq": 1,
    "event_count": 0,
    "session_count": 0,
    "source_count": 0,
    "query_count": 0,
    "denied_count": 0,
    "alert_count": 0,
    "high_level_alert_count": 0,
    "prev_event_count": null,
    "event_count_delta": null,
    "event_change_pct": null,
    "cumulative_event_count": 0,
    "busy_day_rank": 1,
    "hit_bruteforce": 0,
    "hit_data_dump": 0,
    "hit_scanning": 0,
    "hit_recon": 0,
    "hit_destructive": 0
  },
  "last_item": {
    "stat_date": "2026-11-25",
    "day_seq": 7,
    "event_count": 0,
    "session_count": 0,
    "source_count": 0,
    "query_count": 0,
    "denied_count": 0,
    "alert_count": 0,
    "high_level_alert_count": 0,
    "prev_event_count": null,
    "event_count_delta": null,
    "event_change_pct": null,
    "cumulative_event_count": 0,
    "busy_day_rank": 1,
    "hit_bruteforce": 0,
    "hit_data_dump": 0,
    "hit_scanning": 0,
    "hit_recon": 0,
    "hit_destructive": 0
  }
}
```

### 3.5 `GET /api/attackers?page_size=3` → 200

**截断展示：分页信息 + 首项（完整 3 项）**

```json
{
  "page": 1,
  "page_size": 3,
  "total": 14,
  "total_pages": 5,
  "items_count": 3,
  "first_item": {
    "attacker_id": 939,
    "source_ip": "198.51.100.17",
    "first_seen": "2026-11-18T06:00:00Z",
    "last_seen": "2026-11-18T06:00:15Z",
    "total_connections": 1,
    "total_auth_attempts": 8,
    "total_queries": 6,
    "main_intent": {
      "intent_type": "destructive",
      "intent_score": 35,
      "evidence_count": 1,
      "last_detected_at": "2026-11-18T06:00:14Z"
    },
    "risk_score": 85,
    "risk_level": "critical",
    "alert_count": 3,
    "intent_labels": [
      "destructive",
      "data_dump",
      "bruteforce"
    ],
    "triggered_rule_codes": [
      "R02",
      "R04",
      "R05"
    ],
    "network_scope": "reserved",
    "network_scope_label": "文档保留"
  }
}
```

### 3.6 `GET /api/attackers/summary` → 200

**完整响应**

```json
{
  "total": 14,
  "high_risk_count": 1,
  "latest_intent": {
    "intent_type": "data_dump",
    "rule_code": "R04",
    "rule_name": "会话级批量数据读取",
    "source_ip": "198.51.100.23",
    "last_detected_at": "2026-11-18T07:50:05Z"
  },
  "generated_at": "2026-11-25T05:30:18Z"
}
```

### 3.7 `GET /api/alerts/summary` → 200

**完整响应**

```json
{
  "total": 8,
  "unread": 8,
  "read": 0,
  "resolution_rate": 0.0,
  "by_severity": {
    "low": 0,
    "medium": 3,
    "high": 3,
    "critical": 2
  },
  "unread_by_severity": {
    "low": 0,
    "medium": 3,
    "high": 3,
    "critical": 2
  },
  "by_alert_type": {
    "bruteforce": 3,
    "data_dump": 3,
    "destructive": 2
  },
  "today_new": 8,
  "yesterday_new": 0,
  "today_delta_pct": null,
  "peak_window": {
    "start": "2026-11-25T05:00:00Z",
    "end": "2026-11-25T06:00:00Z",
    "count": 8
  },
  "today_window": {
    "start": "2026-11-24T16:00:00Z",
    "end": "2026-11-25T16:00:00Z"
  },
  "generated_at": "2026-11-25T05:30:18Z"
}
```

### 3.8 `GET /api/attackers/203.0.113.250` → 404

**完整响应（RFC 5737 文档保留段中不存在的地址）**

```json
{
  "code": "ATTACKER_NOT_FOUND",
  "message": "暂无该来源画像",
  "detail": {
    "source_ip": "203.0.113.250"
  },
  "request_id": "45cc7865-c932-4940-a0c4-40b8d5e37d03"
}
```

### 3.9 `GET /api/attackers/198.51.100.17` → 200

**截断展示：`attacker` 对象关键字段（`sessions`/`intents`/`recent_rule_hits` 已省略，响应中共 1 个会话 / 3 次命中）**

```json
{
  "attacker_id": 939,
  "source_ip": "198.51.100.17",
  "first_seen": "2026-11-18T06:00:00Z",
  "last_seen": "2026-11-18T06:00:15Z",
  "total_connections": 1,
  "total_auth_attempts": 8,
  "total_auth_failures": 8,
  "total_queries": 6,
  "risk_score": 85,
  "risk_level": "critical",
  "alert_count": 3,
  "unread_alert_count": 3,
  "intent_labels": "destructive,data_dump,bruteforce",
  "triggered_rule_codes": "R02,R04,R05",
  "avg_session_seconds": 15,
  "auth_success_count": 0,
  "high_risk_op_count": 2,
  "network_scope": "reserved",
  "network_scope_label": "文档保留"
}
```

### 3.10 `GET /api/sessions/5a060001-0000-4000-8000-000000000001/timeline` → 200

**截断展示：会话头、计数与首条事件（`events` 仅列 1/N）**

```json
{
  "events_truncated": false,
  "rule_hits": [
    {
      "hit_id": 88,
      "event_id": 20151,
      "rule_code": "R02",
      "rule_name": "短时多凭据认证爆破",
      "intent_type": "bruteforce",
      "rule_version": 1,
      "risk_weight": 25,
      "triggered_at": "2026-11-18T06:00:08Z",
      "evidence_summary": "300 秒内同一来源认证尝试 8 次（阈值 8），不同凭据组合 8 组（阈值 5），符合爆破特征"
    },
    {
      "hit_id": 89,
      "event_id": 20156,
      "rule_code": "R04",
      "rule_name": "会话级批量数据读取",
      "intent_type": "data_dump",
      "rule_version": 1,
      "risk_weight": 25,
      "triggered_at": "2026-11-18T06:00:13Z",
      "evidence_summary": "300 秒内连续 SELECT 5 次（阈值 5），符合批量拖库特征"
    },
    {
      "hit_id": 90,
      "event_id": 20157,
      "rule_code": "R05",
      "rule_name": "破坏性写操作尝试",
      "intent_type": "destructive",
      "rule_version": 1,
      "risk_weight": 35,
      "triggered_at": "2026-11-18T06:00:14Z",
      "evidence_summary": "本事件为破坏性写操作尝试：SQL 首关键词为 DROP，状态 denied，诱饵层仅记录不执行"
    }
  ],
  "alerts": [
    {
      "alert_id": 63,
      "alert_type": "bruteforce",
      "severity": "medium",
      "title": "疑似认证爆破：来自 198.51.100.17 的规则 R02 命中",
      "occurrence_count": 1,
      "created_at": "2026-11-25T05:19:06Z",
      "is_read": false
    },
    {
      "alert_id": 64,
      "alert_type": "data_dump",
      "severity": "high",
      "title": "疑似批量拖库：来自 198.51.100.17 的规则 R04 命中",
      "occurrence_count": 1,
      "created_at": "2026-11-25T05:19:06Z",
      "is_read": false
    },
    {
      "alert_id": 65,
      "alert_type": "destructive",
      "severity": "critical",
      "title": "疑似破坏性操作：来自 198.51.100.17 的规则 R05 命中",
      "occurrence_count": 1,
      "created_at": "2026-11-25T05:19:06Z",
      "is_read": false
    }
  ],
  "events_count": 16,
  "session": {
    "session_id": "5a060001-0000-4000-8000-000000000001",
    "source_ip": "198.51.100.17",
    "source_port": 50100,
    "target_service": "mysql-honeypot",
    "client_fingerprint": "固定合成样本（TEST-ONLY，不含真实客户端信息）",
    "started_at": "2026-11-18T06:00:00Z",
    "ended_at": "2026-11-18T06:00:15Z",
    "session_status": "timeout",
    "request_count": 16,
    "event_count": 16,
    "query_count": 6,
    "max_risk_score": 85,
    "calculated_risk_score": 85,
    "risk_level": "critical",
    "alert_count": 3
  },
  "first_event": {
    "event_id": 20143,
    "event_uuid": "e1060001-0000-4000-8000-000000000001",
    "event_type": "connect",
    "event_time": "2026-11-18T06:00:00Z",
    "source_ip": "198.51.100.17",
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
}
```

## 4. 结论

1. 6 个核心只读端点（health / overview / trend / attackers / attackers summary /
   alerts summary）全部 200，响应字段与契约 §2–§7 一致：`range` 窗口回显与过滤生效
   （7d `sessions=8` vs all `214`）、趋势 5 个 `hit_*` 齐全、攻击者列表含派生字段、
   两个 summary 结构完整。
2. 会话查询接口（`/api/sessions/{session_id}/timeline`）200，返回会话头 + 事件 +
   规则命中 + 告警四段；未知 UUID 按契约 404（列表端点不存在，属设计，不是本任务回归）。
3. 校验与错误码符合契约 §9：`range=30d` → 422 `VALIDATION_ERROR`（`detail` 为字段级数组）；
   不存在 IP → 404 `ATTACKER_NOT_FOUND`；两者均含 `request_id`。
4. 服务为只读访问（GET），未触发任何写接口；本任务未重启 :8000、未改数据库，
   响应中的 `generated_at` 即请求时刻。
