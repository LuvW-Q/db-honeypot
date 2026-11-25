# 证据：事件写入事务（提交/回滚）验证

- 任务：002 / T044（M1 证据）
- 对应用户故事与需求：用户故事 3（原始事件写入具备完整关系约束、事务与幂等保障）；
  **FR-039**（会话/日志/命中/告警/画像同一事务，任一步失败整体回滚）、
  **FR-043**（每个业务事务必须显式提交或回滚）、**FR-042**（失败必须显式记录，禁止静默）
- 验证时间：2026-11-25T13:33+08:00（Asia/Shanghai）
- 环境：MySQL 8.0.46（容器 `dbhoneypot-mysql`，库 `honeypot_dev`）、
  Python 3.13（`/tmp/dbh-venv`，本机 iCloud 下仓库 `.venv` 不可用）、SQLAlchemy 2 + asyncmy；
  写入账号 `honeypot_app_rw`（见 [grants.md](grants.md)）

## 1. 验证目标与判定标准

CLI [`cli/verify_transaction.py`](../m1_transaction_integration/cli/verify_transaction.py) 通过
`IngestService.ingest()` 依次投递 3 条事件（来源固定为 RFC 5737 TEST-NET-2 `198.51.100.250`，
不指向真实资产）：

1. `connect`（会话建立 + 画像写入）；
2. `query`：`SHOW TABLES`（触发 R03 recon 命中，不产生告警）；
3. `query`：`DROP TABLE fake_orders`（触发 R05 destructive 命中，产生告警）。

每个事件在 `IngestService` 内**独立的显式事务**中完成“会话 → 日志 → 规则命中 → 画像 → 告警”
写入；任一步抛错即整体回滚该事件。CLI 在两个时点抓取**五张核心表 + 会话表**行数快照：

- `before`：清理历史测试残留后的基线；
- `after_failure`：故障注入运行结束后的快照；
- `after_cleanup`：按测试来源 IP 清理本次验证数据后的快照。

判定：`clean = (after_cleanup == before)`；注入模式下还要求
`injected_failure_observed = (ingest_error is not None)`；两者同时成立才返回退出码 0。

### 1.1 故障注入点（真实实现，非业务代码改动）

- `profile_write`：`mock.patch("m4_rules_derived.analysis._upsert_attacker_profile", side_effect=_boom)`，
  使**第 1 条** `connect` 事件在画像写入阶段抛 `RuntimeError`。
- `alert_write`：经 M4 公开门面 `m4_rules_derived.public` 包装 `analyze_and_derive`——先执行完整
  分析流水线（命中/画像/告警写入均发生在**同一事务**内），若本次命中含可告警意图
  （`public.ALERTABLE_INTENTS`）则抛 `RuntimeError`。因此 `DROP TABLE` 事件的事务被回滚，
  其结果与“告警写入阶段失败”的事务语义一致：该事件写入的行全部撤销、库内零残留。
- `none`：不注入，验证正常提交路径（用于对照“提交确实发生”）。

## 2. 完整命令与输出

工作目录：仓库根（`/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot`）。
三个模式依次执行，命令与输出如下（原样粘贴）。

### 2.1 `--inject-failure alert_write`

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction --inject-failure alert_write
```

退出码：`0`（stdout 为单行 JSON，stderr 见下；`status=ok`、`clean=true`、`injected_failure_observed=true`）

**stdout**

```json
{"inject_failure": "alert_write", "session_id": "9394003e-bc08-4c04-b341-22e08a9583b8", "source_ip": "198.51.100.250", "tracked_tables": ["attack_log", "rule_hits", "attacker_profile", "attacker_intent", "alerts"], "before": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "after_failure": {"attack_log": 2527, "rule_hits": 12, "attacker_profile": 15, "attacker_intent": 12, "alerts": 8, "sessions": 215}, "after_cleanup": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "ingest_error": "RuntimeError: 注入失败：告警写入阶段（alerts UPSERT）", "injected_failure_observed": true, "clean": true, "status": "ok"}
```

**stderr**（注入异常经 `IngestService` 记录后向上抛出）

```text
事件写入失败，已回滚：event_uuid=81fb666e-f2e5-4a39-946d-c28af08f91bf session_id=9394003e-bc08-4c04-b341-22e08a9583b8 event_type=query
Traceback (most recent call last):
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m1-transaction-integration/m1_transaction_integration/services/ingest.py", line 79, in ingest
    analysis = await self._analyze(log_row, session_row)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m1-transaction-integration/m1_transaction_integration/services/ingest.py", line 173, in _analyze
    return await rules_derived.analyze_and_derive(self.db, log_row, session_row)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/unittest/mock.py", line 2332, in _execute_mock_call
    result = await effect(*args, **kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m1-transaction-integration/m1_transaction_integration/cli/verify_transaction.py", line 178, in _wrapped
    raise RuntimeError("注入失败：告警写入阶段（alerts UPSERT）")
RuntimeError: 注入失败：告警写入阶段（alerts UPSERT）
```


### 2.2 `--inject-failure profile_write`

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction --inject-failure profile_write
```

退出码：`0`（stdout 为单行 JSON，stderr 见下；`status=ok`、`clean=true`、`injected_failure_observed=true`）

**stdout**

```json
{"inject_failure": "profile_write", "session_id": "c873b060-1fbd-491a-af23-fdfe21825c02", "source_ip": "198.51.100.250", "tracked_tables": ["attack_log", "rule_hits", "attacker_profile", "attacker_intent", "alerts"], "before": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "after_failure": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "after_cleanup": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "ingest_error": "RuntimeError: 注入失败：画像写入阶段（attacker_profile UPSERT）", "injected_failure_observed": true, "clean": true, "status": "ok"}
```

**stderr**（注入异常经 `IngestService` 记录后向上抛出）

```text
事件写入失败，已回滚：event_uuid=af4c9865-bf66-49c6-84bf-debcafee644e session_id=c873b060-1fbd-491a-af23-fdfe21825c02 event_type=connect
Traceback (most recent call last):
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m1-transaction-integration/m1_transaction_integration/services/ingest.py", line 79, in ingest
    analysis = await self._analyze(log_row, session_row)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m1-transaction-integration/m1_transaction_integration/services/ingest.py", line 173, in _analyze
    return await rules_derived.analyze_and_derive(self.db, log_row, session_row)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m4-rules-derived/m4_rules_derived/public.py", line 27, in analyze_and_derive
    return await analysis.analyze_event(session, event_row, session_row)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m4-rules-derived/m4_rules_derived/analysis.py", line 479, in analyze_event
    attacker_id = await _upsert_attacker_profile(
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<7 lines>...
    )
    ^
  File "/Users/luvwq/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/unittest/mock.py", line 2332, in _execute_mock_call
    result = await effect(*args, **kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot/modules/m1-transaction-integration/m1_transaction_integration/cli/verify_transaction.py", line 153, in _boom
    raise RuntimeError("注入失败：画像写入阶段（attacker_profile UPSERT）")
RuntimeError: 注入失败：画像写入阶段（attacker_profile UPSERT）
```


### 2.3 `--inject-failure none`

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction --inject-failure none
```

退出码：`0`（stdout 为单行 JSON，stderr 见下；`status=ok`、`clean=true`、`injected_failure_observed=false`）

**stdout**

```json
{"inject_failure": "none", "session_id": "63cd009b-880c-45e3-b13a-7a26d69fd84a", "source_ip": "198.51.100.250", "tracked_tables": ["attack_log", "rule_hits", "attacker_profile", "attacker_intent", "alerts"], "before": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "after_failure": {"attack_log": 2528, "rule_hits": 13, "attacker_profile": 15, "attacker_intent": 13, "alerts": 9, "sessions": 215}, "after_cleanup": {"attack_log": 2525, "rule_hits": 11, "attacker_profile": 14, "attacker_intent": 11, "alerts": 8, "sessions": 214}, "ingest_error": null, "injected_failure_observed": false, "clean": true, "status": "ok"}
```

**stderr**：（空）


## 3. 快照对照（真实行数）

| 阶段 | attack_log | rule_hits | attacker_profile | attacker_intent | alerts | sessions |
| --- | --- | --- | --- | --- | --- | --- |
| alert_write · 提交前 before | 2525 | 11 | 14 | 11 | 8 | 214 |
| profile_write · 提交前 before | 2525 | 11 | 14 | 11 | 8 | 214 |
| none · 提交前 before | 2525 | 11 | 14 | 11 | 8 | 214 |
| alert_write · 失败后 after_failure | 2527 | 12 | 15 | 12 | 8 | 215 |
| profile_write · 失败后 after_failure | 2525 | 11 | 14 | 11 | 8 | 214 |
| none · 失败后 after_failure | 2528 | 13 | 15 | 13 | 9 | 215 |
| alert_write · 清理后 after_cleanup | 2525 | 11 | 14 | 11 | 8 | 214 |
| profile_write · 清理后 after_cleanup | 2525 | 11 | 14 | 11 | 8 | 214 |
| none · 清理后 after_cleanup | 2525 | 11 | 14 | 11 | 8 | 214 |

关键结论（逐条对应上表与 stdout 的 `clean`/`injected_failure_observed`）：

1. **`alert_write` 回滚有效**：前两条事件已正常提交（`attack_log` +2、`sessions` +1、
   `rule_hits`/`attacker_intent` 各 +1、`attacker_profile` +1），第 3 条 `DROP TABLE`
   事件在告警阶段注入失败后，其日志/命中/画像/告警写入全部随事务回滚——`alerts` 保持 8；
   `after_cleanup` 与 `before` 逐行一致，`clean=true`。
2. **`profile_write` 回滚有效**：第 1 条 `connect` 事件即失败，`after_failure` 与 `before`
   逐行一致（其余 2 条事件未投递），`clean=true`。
3. **正常提交成功（对照）**：`none` 模式下 3 条事件全部提交，`after_failure` 相对 `before`
   增量为 `attack_log +3`、`rule_hits +2`（R03 与 R05 各 1）、`attacker_profile +1`、
   `attacker_intent +2`、`alerts +1`（R05 告警）、`sessions +1`；随后清理把全部计数恢复为
   `before`，`clean=true`。这说明前两组“失败后无增量”不是因为没有写入能力，而是事务回滚的结果。
4. 三组运行 `before` 完全一致（`{'attack_log': 2525, 'rule_hits': 11, 'attacker_profile': 14, 'attacker_intent': 11, 'alerts': 8, 'sessions': 214}`），说明 CLI 先清理测试来源残留、
   基线稳定可重复；每组 `session_id` 唯一，互不干扰。

## 4. 复现说明

```bash
# 1) 确保 .env 中的 DATABASE_URL 指向 honeypot_dev，且 MySQL 容器健康
docker ps --filter name=dbhoneypot-mysql --format '{{.Names}} {{.Status}}'

# 2) 三种模式各跑一次（输出单行 JSON；退出码 0 = 通过）
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction --inject-failure alert_write
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction --inject-failure profile_write
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m1_transaction_integration.cli.verify_transaction --inject-failure none
```

清理逻辑按测试来源 IP（`198.51.100.250`）删除告警 → 意图 → 命中 → 日志 → 画像 → 会话，
因此重复运行不会累积脏数据；若数据库中存在其他来源的演示数据，`before` 会反映其当前值（属正常）。
