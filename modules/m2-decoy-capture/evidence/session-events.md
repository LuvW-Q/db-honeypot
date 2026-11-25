# M2 证据：同一会话的完整事件日志与 M4 命中映射

| 项目 | 内容 |
| --- | --- |
| 对应用户故事 / FR | 002 US3 / T045；FR-125（M2 证据前半：同一会话的完整事件日志）、FR-129（可复现）、SC-028 |
| 证据日期 | **2026-11-25** |
| 环境 | 仓库根 `/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot`；MySQL **8.0.46** 容器 `dbhoneypot-mysql`，库 `honeypot_dev`，只读账号 `honeypot_app_ro` |
| 解释器 | `/tmp/dbh-venv/bin/python`（不是仓库 `.venv`） |
| 数据快照 | `attack_log=2525`、`sessions=214`、`alerts=8`、`rule_hits=11`、`attacker_profile=14`（2026-11-25T05:31Z 重灌的确定性 demo 数据） |
| 读取方式 | **只读 SELECT**，无 DDL / 无写入；不使用 API（8000 端口未重启） |
| SQL 文件 | [`session-events.sql`](session-events.sql)；原样输出 [`session-events.out.txt`](session-events.out.txt) |

> 样本会话 `5a060001-0000-4000-8000-000000000001` 是 `import_samples` 的固定合成样本 S06：
> 连接 → 8 次认证失败（多凭据爆破）→ 5 次 SELECT（批量拖库）→ 被拒的 `DROP TABLE` → 断开。
> 它同时覆盖 R02/R04/R05 三条规则，因此既满足 FR-125 的完整时间线还原，也能说明事件序列
> 如何映射到 M4 命中。

---

## 1. 会话元数据

```sql
SET @sid := '5a060001-0000-4000-8000-000000000001';

SELECT session_id, source_ip, source_port, target_service,
       started_at, ended_at, session_status, request_count, max_risk_score
FROM sessions
WHERE session_id = @sid;
```

真实输出（`mysql --table` 原样）：

```text
+--------------------------------------+---------------+-------------+----------------+----------------------------+----------------------------+----------------+---------------+----------------+
| session_id                           | source_ip     | source_port | target_service | started_at                 | ended_at                   | session_status | request_count | max_risk_score |
+--------------------------------------+---------------+-------------+----------------+----------------------------+----------------------------+----------------+---------------+----------------+
| 5a060001-0000-4000-8000-000000000001 | 198.51.100.17 |       50100 | mysql-honeypot | 2026-11-18 06:00:00.000000 | 2026-11-18 06:00:15.000000 | timeout        |            16 |             85 |
+--------------------------------------+---------------+-------------+----------------+----------------------------+----------------------------+----------------+---------------+----------------+
```

会话持续 15 秒、16 条请求、风险分 85（= 25 + 25 + 35，见 §4.4）。

---

## 2. 完整事件日志（16 条，按 `event_time` 升序）

```sql
SELECT event_id, event_uuid, event_type, event_time, username,
       credential_test_id, sql_statement, status, returned_rows, response_ms
FROM attack_log
WHERE session_id = @sid
ORDER BY event_time, event_id;
```

结果 16 行（`SELECT COUNT(*)` 同 §5 为 16，与会话 `request_count=16` 一致）：

| # | event_uuid | type | event_time | username | SQL | status | rows | ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `e1060001-…-000000000001` | connect | 2026-11-18 06:00:00 | — | — | success | 0 | 0 |
| 2 | `e1060002-…-000000000002` | auth | 06:00:01 | svc_backup | — | failure | 0 | 0 |
| 3 | `e1060003-…-000000000003` | auth | 06:00:02 | svc_report | — | failure | 0 | 0 |
| 4 | `e1060004-…-000000000004` | auth | 06:00:03 | svc_admin | — | failure | 0 | 0 |
| 5 | `e1060005-…-000000000005` | auth | 06:00:04 | root | — | failure | 0 | 0 |
| 6 | `e1060006-…-000000000006` | auth | 06:00:05 | legacy_app | — | failure | 0 | 0 |
| 7 | `e1060007-…-000000000007` | auth | 06:00:06 | demo_admin | — | failure | 0 | 0 |
| 8 | `e1060008-…-000000000008` | auth | 06:00:07 | svc_backup | — | failure | 0 | 0 |
| 9 | `e1060009-…-000000000009` | auth | 06:00:08 | svc_report | — | failure | 0 | 0 |
| 10 | `e1060010-…-000000000010` | query | 06:00:09 | — | `SELECT email, phone FROM fake_users LIMIT 20` | success | 180 | 6 |
| 11 | `e1060011-…-000000000011` | query | 06:00:10 | — | `SELECT email, phone FROM fake_users LIMIT 30` | success | 180 | 6 |
| 12 | `e1060012-…-000000000012` | query | 06:00:11 | — | `SELECT email, phone FROM fake_users LIMIT 40` | success | 180 | 6 |
| 13 | `e1060013-…-000000000013` | query | 06:00:12 | — | `SELECT email, phone FROM fake_users LIMIT 50` | success | 180 | 6 |
| 14 | `e1060014-…-000000000014` | query | 06:00:13 | — | `SELECT email, phone FROM fake_users LIMIT 60` | success | 180 | 6 |
| 15 | `e1060015-…-000000000015` | query | 06:00:14 | — | `DROP TABLE fake_users` | denied | 0 | 2 |
| 16 | `e1060016-…-000000000016` | disconnect | 06:00:15 | — | — | failure | 0 | 0 |

口径说明：

- `event_uuid` 是稳定业务标识；`event_id` 是 `BIGINT AUTO_INCREMENT` 代理键，重灌 demo 数据后
  会整体变化（本轮快照中为 `22680…22695`，原样输出见 [`session-events.out.txt`](session-events.out.txt)），
  引用请以 `event_uuid` / `session_id` 为准。
- `response_ms=0` 的 connect/disconnect/auth 事件不产生查询耗时；auth 事件的
  `credential_test_id`（`TEST-ONLY-S06-A1…A8`）记录被测凭据组合，供 R02 统计不同凭据对。
- 长结果未截断：本会话 `sql_statement` 最长 52 字符，16 行全部在表中列出。

---

## 3. 事件序列还原（连接 → 认证失败 → 认证成功 → 查询 → 被拒破坏性操作 → 断开）

| 阶段 | 事件 | 时间 | 行为解读 |
| --- | --- | --- | --- |
| ① 连接 | #1 `connect` | 06:00:00 | 客户端 `198.51.100.17:50100` 连入诱饵 `mysql-honeypot` |
| ② 认证 | #2–#9 共 8 条 `auth`，全部 `failure` | 06:00:01–06:00:08 | 8 个不同用户名 × 8 组凭据测试标识，1 秒 1 次，典型多凭据爆破（本会话未出现认证成功，诱饵层拒绝后仍继续尝试） |
| ③ 查询 | #10–#14 共 5 条 `query`，皆 `SELECT … FROM fake_users LIMIT n`，`success` | 06:00:09–06:00:13 | 通过诱饵账号后连续读取 `fake_users` 的 email/phone（伪造恒为 180 行的假目录），单条 6 ms |
| ④ 破坏性操作 | #15 `query` = `DROP TABLE fake_users`，`status=denied` | 06:00:14 | 诱饵层识别为写操作后**拒绝执行**，返回 2 ms，事件照常落库 |
| ⑤ 断开 | #16 `disconnect`，`status=failure` | 06:00:15 | 会话结束，`sessions.session_status=timeout` |

> §3 的“认证成功”在样本中表现为“通过诱饵层进入查询阶段”：诱饵认证有独立判定
> （`auth.py`），拒绝仍在 `attack_log` 记 `failure`，因此本会话的认证段全是失败。

---

## 4. 一个会话的事件序列如何映射为 M4 命中（R02 / R04 / R05）

M4 的分析入口是 `m4_rules_derived.analysis.analyze_event`（逐条事件、在同一 ingest 事务内
按启用规则判定，命中写 `rule_hits`，再算分会话/意图/画像并生成告警）。下表是**已落库的真实结果**，
即事件日志 → 规则命中 → 告警两次数据变换。

### 4.1 命中记录（`rule_hits`）

```sql
SELECT hit_id, event_id, rule_code, intent_type, risk_weight, rule_version,
       evidence_summary, triggered_at
FROM rule_hits
WHERE session_id = @sid
ORDER BY hit_id;
```

真实结果（3 行，原样见 [`session-events.out.txt`](session-events.out.txt)）：

| hit_id | event_id | rule | intent | weight | ver | evidence_summary | triggered_at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 103 | 22688（`e1060009…`，#9） | R02 | bruteforce | 25 | 1 | 300 秒内同一来源认证尝试 8 次（阈值 8），不同凭据组合 8 组（阈值 5），符合爆破特征 | 06:00:08 |
| 104 | 22693（`e1060014…`，#14） | R04 | data_dump | 25 | 1 | 300 秒内连续 SELECT 5 次（阈值 5），符合批量拖库特征 | 06:00:13 |
| 105 | 22694（`e1060015…`，#15） | R05 | destructive | 35 | 1 | 本事件为破坏性写操作尝试：SQL 首关键词为 DROP，状态 denied，诱饵层仅记录不执行 | 06:00:14 |

### 4.2 告警（`alerts`）

```sql
SELECT alert_id, rule_code, severity, title, evidence_summary,
       first_seen_at, last_seen_at, occurrence_count
FROM alerts
WHERE session_id = @sid
ORDER BY alert_id;
```

真实结果（3 行）：

| alert_id | rule | severity | title | occurrence |
| --- | --- | --- | --- | --- |
| 73 | R02 | medium | 疑似认证爆破：来自 198.51.100.17 的规则 R02 命中 | 1 |
| 74 | R04 | high | 疑似批量拖库：来自 198.51.100.17 的规则 R04 命中 | 1 |
| 75 | R05 | critical | 疑似破坏性操作：来自 198.51.100.17 的规则 R05 命中 | 1 |

### 4.3 逐条映射（事件 → 规则口径 → 命中）

**R02 短时多凭据认证爆破**（`rules/r02_bruteforce.py`，阈值来自 `detection_rules.parameters_json`：
`window_seconds=300`、`min_auth_attempts=8`、`min_distinct_credential_pairs=5`、`count_failed_only=false`）

- 只对 `auth` 事件判定，所以候选事件是 #2–#9；向前回看 300 秒（06:00:01–06:00:08 落在窗口内）。
- 第 9 条（06:00:08）时窗口内 auth 事件 = **8 ≥ 8**，不同 `(username, credential_test_id)`
  组合 = **8 ≥ 5** → 命中，`hit_id=103` 绑定 `event_id=22688`。
- #2–#8 虽然各自都在累积，但在各自时刻未同时满足 8 次 / 5 组，因此不产生命中——
  这解释了为什么 8 条 auth 只出现 1 条 R02 命中（规则在“首次达标”的那一条上落库，幂等键防重复）。

**R04 会话级批量数据读取**（`rules/r04_data_dump.py`；`window_seconds=300`、
`min_consecutive_select=5`、`session_returned_rows_threshold=1000`）

- 只对 `query` 事件且 SQL 以 `SELECT` 开头的事件判定，候选是 #10–#14。
- 条件 A（连续 SELECT）：到 #14 时向前连续 SELECT = **5 ≥ 5** → 满足。
- 条件 B（会话累计行数）：`SUM(returned_rows)=900`（180 × 5）**不大于** 1000 → 不满足。
- 结论：R04 由**条件 A**命中，`hit_id=104` 绑定 `event_id=22693`（第 5 条 SELECT）。
  这也说明样本刻意把累计行数压在 1000 以下，以单独验证“连续 SELECT 次数”口径。

**R05 破坏性写操作尝试**（`rules/r05_destructive.py`；`keywords=[DROP,TRUNCATE,DELETE,UPDATE,INSERT]`、
`count_status=[denied,error,success]`、`word_boundary=true`）

- 逐事件判定：`first_keyword("DROP TABLE fake_users") = DROP` 且 `status=denied` 属于 `count_status`
  → 命中条件 1 成立，`hit_id=105` 绑定 `event_id=22694`（#15）。
- 诱饵层拒绝执行是**预期**结果：规则统计的是“尝试”，`denied` 仍计入并告警（`alerts` 证据摘要
  明确写“诱饵层仅记录不执行”）。

**为什么只有 3 条命中**：R01（扫描）与 R03（recon）按设计只进入画像/意图/证据、不生成告警
（`m4_rules_derived/alerts.py` 顶部注释与 `SEVERITY_BY_RULE` 仅含 R02/R04/R05）。本会话也没有
连接洪泛与 `SHOW TABLES`/`information_schema` 类元数据探测，因此不存在 R01/R03 候选。

### 4.4 分数与告警联动（交叉校验）

- `risk_weight`：R02=25、R04=25、R05=35 → 按 `rule_code` 取最大权重后求和 = **85**，
  与 `sessions.max_risk_score=85` 完全一致（§1 实测）。
- 规则→等级映射（`m4_rules_derived/alerts.py`）：R02→medium、R04→high、R05→critical，
  与 §4.2 实测 severity 一致；三条告警 `occurrence_count=1`（同一会话内每条规则只触发一次命中）。

### 4.5 与时间线查询索引的关系

§2 的查询形态（`WHERE session_id = ? ORDER BY event_time, event_id`）正是 `explain_diff` 的 Q1：
控制台“会话时间线”接口按此读取。索引前后的计划对比见
[`explain-diff.md`](explain-diff.md) §3（`ALL + filesort` → `ref idx_log_session_time`，扫描行数 2432 → 16）。

---

## 5. 事件计数与累计行数（R04 条件 B 的判定输入）

```sql
SELECT COUNT(*) AS event_count,
       SUM(returned_rows) AS total_returned_rows,
       SUM(event_type = 'auth') AS auth_events,
       SUM(event_type = 'query') AS query_events
FROM attack_log
WHERE session_id = @sid;
```

```text
+-------------+---------------------+-------------+--------------+
| event_count | total_returned_rows | auth_events | query_events |
+-------------+---------------------+-------------+--------------+
|          16 |                 900 |           8 |            6 |
+-------------+---------------------+-------------+--------------+
```

`query_events=6` 含被拒的 `DROP`（#15 也是 `query`），其中以 SELECT 开头的只有 5 条，即 R04 的候选集。

---

## 6. 复现命令（只读，无需 API）

```bash
cd /Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot

# 方式一：容器自带 mysql 客户端（本轮原样输出即由此产生）
docker exec -i dbhoneypot-mysql mysql -h127.0.0.1 -P3306 --protocol=TCP \
  --default-character-set=utf8mb4 -uhoneypot_app_ro -p'TestOnly-AppRo-2026' --table honeypot_dev \
  < modules/m2-decoy-capture/evidence/session-events.sql

# 方式二：用应用只读连接执行同一条 SQL（不经容器）
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from shared.config import settings
from sqlalchemy.ext.asyncio import create_async_engine

SID = "5a060001-0000-4000-8000-000000000001"

async def main():
    engine = create_async_engine(settings.readonly_database_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT event_uuid, event_type, event_time, username, sql_statement, status, "
            "returned_rows, response_ms FROM attack_log WHERE session_id=:sid "
            "ORDER BY event_time, event_id"), {"sid": SID})).all()
        print(len(rows), "events")
        for r in rows:
            print(*r, sep=" | ")
    await engine.dispose()

asyncio.run(main())
PY
```

**期望输出**：16 条事件、时间升序、首条 `connect`、末条 `disconnect`；`rule_hits` 3 行
（R02/R04/R05，权重 25/25/35）；`alerts` 3 行（medium/high/critical）。

---

## 7. 验证

| 检查项 | 命令 | 结果（2026-11-25） |
| --- | --- | --- |
| 静态检查 | `/tmp/dbh-venv/bin/python -m ruff check modules/m2-decoy-capture` | **All checks passed!**（0 error，退出码 0） |
| 单元/集成测试 | `PYTHONPATH=.:modules/... /tmp/dbh-venv/bin/python -m pytest modules/m2-decoy-capture/tests -q` | **16 passed**（本轮两次执行：22.51s 冷启动、1.77s 复跑） |
| 本证据一致性 | 16 条事件 = `request_count`；3 条 `rule_hits` → 3 条 `alerts`；25+25+35=85 = `max_risk_score` | 全部一致 |
| 只读性 | 全程 `SELECT`，无 `INSERT/UPDATE/DELETE/DDL` | 满足约束 |

---

## 8. 已知限制

| 限制 | 说明 |
| --- | --- |
| 合成样本 | 会话为 `import_samples` 固定合成数据（RFC 5737 TEST-NET-2 来源 `198.51.100.17`），非真实攻击流量；用于口径验证而非威胁情报 |
| 代理键漂移 | `event_id/hit_id/alert_id` 为自增列，重灌 demo 数据后整体变化；证据以 `event_uuid`/`session_id` 锚定 |
| 数据规模 | `attack_log` 2525 行、会话 16 条事件，属于课程验证规模；`response_ms` 为诱饵层合成值 |
| 认证段 | 样本未演示“认证成功后查询”的中间态（诱饵认证由 `auth.py` 独立判定），时间线呈现为“认证失败段 → 查询段” |

---

## 9. 相关材料

- [`session-events.sql`](session-events.sql)：本文全部 SQL（5 段，只读）。
- [`session-events.out.txt`](session-events.out.txt)：上述 SQL 的原样输出（44 行）。
- [`explain-diff.md`](explain-diff.md)：同一时间线查询的 EXPLAIN 索引前后对比。
- [`../m2_decoy_capture/cli/import_samples.py`](../m2_decoy_capture/cli/import_samples.py)：样本会话来源。
- [`../../m4-rules-derived/m4_rules_derived/rules/`](../../m4-rules-derived/m4_rules_derived/rules/)：R02/R04/R05 判定实现。
