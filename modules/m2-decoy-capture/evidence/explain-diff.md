# M2 证据：时间线查询的 EXPLAIN 索引前后对比

| 项目 | 内容 |
| --- | --- |
| 对应用户故事 / FR | 002 US3 / T045；FR-125（M2 证据后半：时间线查询建立索引前后的 EXPLAIN 对比：访问类型 / 使用索引 / 估算行数 / 实测耗时）、FR-129、SC-028 |
| 证据日期 | **2026-11-25** |
| 环境 | 仓库根；MySQL **8.0.46** 容器 `dbhoneypot-mysql`，库 `honeypot_dev`，只读账号 `honeypot_app_ro`；解释器 `/tmp/dbh-venv/bin/python` |
| 数据快照 | `attack_log=2525`、`sessions=214`、`alerts=8`、`rule_hits=11`、`attacker_profile=14`（2026-11-25T05:31Z 重灌的确定性 demo 数据） |
| 主产物 | [`explain/explain_20261125T053230Z.json`](explain/explain_20261125T053230Z.json)（CLI 正式产出，13.5 KB） |
| 补充产物 | [`explain/explain_variants_20261125T053414Z.json`](explain/explain_variants_20261125T053414Z.json)（同时间线不同写法，10.4 KB） |
| 历史记录 | `explain/explain_20261119T145225Z.json`、`explain_20261119T145423Z.json`（旧 `app.cli` 产出，保留不覆盖，仅作对照） |

> 对比方法：**不执行任何 DDL**。before 查询用 MySQL 的 `IGNORE INDEX (<索引名>)` 显式禁用目标索引，
> 等价“索引不可用”；after 查询正常执行。两条语句在同一只读连接、同一份数据上执行，
> 记录 `EXPLAIN FORMAT=JSON` 关键字段与预热后 5 次执行的中位耗时（`timing_runs=5`）。

---

## 1. 复现命令

`explain_diff` 先看 `--help` 确认过参数与输出路径（除 `-h/--help` 外无参数，输出目录固定为
仓库根 `db/explain/`，文件名按 UTC 时间戳追加、不覆盖旧文件）：

```bash
cd /Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot

PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m2_decoy_capture.cli.explain_diff --help

# 正式对比（本轮运行时间 2026-11-25T05:32:30Z）
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m2_decoy_capture.cli.explain_diff
# → 记录已写入：db/explain/explain_20261125T053230Z.json

# 归档进模块证据目录（本轮即按此追加，不覆盖 2026-11-19 的历史记录）
mkdir -p modules/m2-decoy-capture/evidence/explain
cp db/explain/explain_20261125T053230Z.json modules/m2-decoy-capture/evidence/explain/

# 补充：同一时间线的不同写法（写入 evidence/explain/ 本身）
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python modules/m2-decoy-capture/evidence/explain_variants.py
```

CLI 的 stdout 摘要（本轮真实输出）：

```text
=== EXPLAIN 索引前后对比摘要 ===
数据库：127.0.0.1:3306/honeypot_dev（MySQL 8.0.46）
数据规模：attack_log=2525，sessions=214，alerts=8，rule_hits=11，attacker_profile=14
[G1/Q1] 按会话时间线读取事件（表 attack_log）
  before：type=ALL key=None rows=2432 filesort=True 耗时=0.712 ms
  after ：type=ref key=idx_log_session_time rows=16 filesort=False 耗时=0.402 ms
  结论：访问类型 ALL → ref；实际索引 NULL → idx_log_session_time；估算扫描行数 2432 → 16；
        实测耗时中位数 0.712 ms → 0.402 ms；filesort True → False；结论：索引可用后按预期命中
        idx_log_session_time，计划达标
[G2/Q2] 筛选近期高等级告警（表 alerts）
  before：type=ALL key=None rows=8 filesort=True 耗时=0.315 ms
  after ：type=ref key=idx_alert_level_time rows=2 filesort=False 耗时=0.32 ms
  结论：访问类型 ALL → ref；实际索引 NULL → idx_alert_level_time；估算扫描行数 8 → 2；
        实测耗时中位数 0.315 ms → 0.32 ms；filesort True → False；结论：索引可用后按预期命中
        idx_alert_level_time，计划达标
记录已写入：db/explain/explain_20261125T053230Z.json
```

（上面为便于阅读做了换行，原始单行输出见 JSON 的 `groups[].conclusion` 字段。）

---

## 2. 四组对比一览

| 组 | 查询 | 目标索引 | before | after | 估算行数 | 中位耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| G1 / Q1 | 按会话时间线读取事件 | `idx_log_session_time` | `ALL` / key=NULL / filesort | `ref` / 命中 / 无 filesort | 2432 → 16 | 0.712 → 0.402 ms |
| G2 / Q2 | 近期 `critical` 等级告警 | `idx_alert_level_time` | `ALL` / key=NULL / filesort | `ref` / 命中 / 反向扫描 + 覆盖 | 8 → 2 | 0.315 → 0.320 ms |
| G3 / Q3 | 同时间线 + `event_time` 下界（增量拉取写法） | `idx_log_session_time` | `ALL` / key=NULL / filesort | `range` / 命中 / 无 filesort | 2432 → 7 | 0.757 → 0.372 ms |
| G4 / Q4 | 按来源 IP 倒序取最近事件（告警溯源写法） | `idx_log_source_time` | `ALL` / key=NULL / filesort | `ref` / 命中 / 反向扫描 | 2432 → 16 | 0.681 → 0.346 ms |

索引现状（JSON `indexes` 字段，`SHOW INDEX` 真实结果）：`attack_log` 有 5 个索引
（`PRIMARY(event_id)`、`uk_attack_log_event_uuid(event_uuid)`、`uk_attack_log_event_session(event_id, session_id)`、
`idx_log_source_time(source_ip, event_time)`、`idx_log_session_time(session_id, event_time)`）；
`alerts` 有 9 个，其中 `idx_alert_level_time(severity, created_at)` 是 Q2 的目标索引。

---

## 3. 关键计划对比（type / key / rows / Extra）

### 3.1 G1：Q1 会话时间线（主线证据）

SQL（与 `GET /api/sessions/{id}/timeline` 同形态，见 [`session-events.md`](session-events.md) §2）：

```sql
-- after：索引可用
SELECT event_id, event_type, event_time, status FROM attack_log
WHERE session_id = :session_id ORDER BY event_time, event_id;

-- before：显式禁用目标索引
SELECT event_id, event_type, event_time, status FROM attack_log
IGNORE INDEX (idx_log_session_time)
WHERE session_id = :session_id ORDER BY event_time, event_id;
```

| 指标 | before（`IGNORE INDEX`） | after（索引可用） | 变化 |
| --- | --- | --- | --- |
| `type`（访问类型） | `ALL` | `ref` | 全表扫描 → 索引等值查找 |
| `possible_keys` | `null` | `["idx_log_session_time"]` | 索引进入候选 |
| `key`（使用索引） | `null` | `idx_log_session_time` | 命中目标索引 |
| `key_len` | `null` | `36` | 只用第一列 `session_id`（`CHAR(36)` ascii = 36 字节） |
| `rows`（估算扫描行数） | `2432` | `16` | 约 **152×** 下降 |
| `rows_produced` | `11` | `16` | 结果集一致（本会话 16 条事件） |
| `filtered` | `0.47%` | `100.00%` | 索引过滤后全部命中 |
| `Using filesort` | **是** | **否** | 排序由索引第二列 `event_time` 提供 |
| `query_cost` | `279.00` | `5.60` | 约 **50×** 下降 |
| 实测中位耗时 | `0.712 ms` | `0.402 ms` | 约 −44%（范围 0.693–0.839 → 0.344–0.414） |

**结论（Q1）**：走索引的是 after，全表扫描的是 before。`ORDER BY event_time, event_id` 能复用
`(session_id, event_time)` 的第二列，因此 filesort 消失；`rows` 从 2432 降到 16，符合 FR-125
要求的“访问类型 / 使用索引 / 估算行数 / 实测耗时”四项对比。

### 3.2 G2：Q2 近期高等级告警

```sql
-- after
SELECT alert_id, severity, created_at FROM alerts
WHERE severity = 'critical' ORDER BY created_at DESC LIMIT 20;
-- before
SELECT alert_id, severity, created_at FROM alerts IGNORE INDEX (idx_alert_level_time)
WHERE severity = 'critical' ORDER BY created_at DESC LIMIT 20;
```

| 指标 | before | after | 变化 |
| --- | --- | --- | --- |
| `type` | `ALL` | `ref` | 全表扫描 → 索引等值查找 |
| `key` | `null` | `idx_alert_level_time` | 命中目标索引 |
| `key_len` | `null` | `34` | `severity VARCHAR(8)` ascii = 8 + 2 长度字节 |
| `rows` | `8` | `2` | 表仅 8 行，下降有限 |
| `filtered` | `33.33%` | `100.00%` | — |
| `Using filesort` | **是** | **否** | 反向索引扫描替代排序 |
| `backward_index_scan` / `using_index` | `null` / `null` | `true` / `true` | `ORDER BY … DESC` 走反向扫描；二级索引隐含主键 `alert_id` → 覆盖索引 |
| `query_cost` | `3.72` | `0.45` | 约 **8×** 下降 |
| 实测中位耗时 | `0.315 ms` | `0.320 ms` | **无差异（噪声）**：表仅 8 行 |

**结论（Q2）**：同样由 `ALL` → `ref`，filesort 消除；但因为 `alerts` 只有 8 行、命中 2 行，
毫秒差落在噪声区间（after 甚至略高 0.005 ms）。这条证据的价值是**计划字段**而不是绝对耗时，
答辩时不要把它当性能提升来宣称。

### 3.3 G3：同一时间线的另一种写法（增量拉取）

SQL：

```sql
-- after
SELECT event_id, event_type, event_time, status FROM attack_log
WHERE session_id = :sid AND event_time >= :t0 ORDER BY event_time, event_id;
-- before
SELECT event_id, event_type, event_time, status FROM attack_log
IGNORE INDEX (idx_log_session_time)
WHERE session_id = :sid AND event_time >= :t0 ORDER BY event_time, event_id;
```

| 指标 | before | after | 变化 |
| --- | --- | --- | --- |
| `type` | `ALL` | **`range`** | 从全表扫描变为索引范围扫描 |
| `key` | `null` | `idx_log_session_time` | 命中同一目标索引 |
| `key_len` | `null` | **`44`** | 36（`session_id`）+ 8（`event_time DATETIME(6)`），两列都用上 |
| `rows` | `2432` | `7` | 只剩 `event_time >= '2026-11-18 06:00:09'` 的 7 条 |
| `filtered` | `0.16%` | `100.00%` | — |
| `Using filesort` | **是** | **否** | 索引顺序即 `ORDER BY` 顺序 |
| `query_cost` | `271.30` | `3.41` | 约 **80×** 下降 |
| 实测中位耗时 | `0.757 ms` | `0.372 ms` | 约 −51% |

**结论（G3）**：同一张表、同一个索引，只把 WHERE 从“等值”写成“等值 + 时间下界”，访问类型就变成
`range` 且 `key_len` 从 36 增到 44——说明复合索引第二列被真正用于范围过滤，而不是“等值后再回表过滤”。

### 3.4 G4：按来源 IP 溯源（另一种索引）

`WHERE source_ip = :ip ORDER BY event_time DESC LIMIT 20`：before `ALL` + filesort（2432 行，0.681 ms）
→ after `type=ref`、`key=idx_log_source_time`、`backward_index_scan=true`、无 filesort（16 行，0.346 ms，
约 −49%）。证明 `idx_log_source_time(source_ip, event_time)` 同样支撑“按来源倒序取最近事件”的告警溯源查询。

---

## 4. 结论：哪条走索引、哪条全表扫描、为什么不动索引

**走索引 / 全表扫描的判定**

- after 四条全部命中预定义复合索引：G1/G3 → `idx_log_session_time`，G4 → `idx_log_source_time`，
  G2 → `idx_alert_level_time`；`type ∈ {ref, range}`、`key` 非空、`filesort=false`。
- before 四条全部 `type=ALL`、`key=NULL`、`filesort=true`——它们是同一个索引被 `IGNORE INDEX`
  禁用后的对照，**不是**“缺索引”的证据。

**为什么本轮不改索引（也不删/不建/不设 INVISIBLE）**

1. **计划已经达标，改索引没有收益**：Q1/Q3 由 `(session_id, event_time)` 同时满足等值与排序，
   `key_len` 已用满（36 / 44）；Q4 由 `(source_ip, event_time)` 覆盖；Q2 已靠
   `(severity, created_at)` + 隐式主键实现覆盖索引 + 反向扫描。再加索引只会增加写放大。
2. **`attack_log` 是高频写表**：每个诱饵请求都写一条事件，索引数量直接影响 insert 成本；
   现有 5 个索引已覆盖主键、业务唯一键、会话时间线与来源时间线，冗余索引不划算。
3. **改索引必须走既定流程**：按 FR-120，数据模型变更顺序是 M3 设计 → M1 迁移与回滚演练 →
   M2/M4/M5 适配；本轮 T045 只做**证据交付**，不越界改结构（也避免污染演示库统计信息）。
4. **对比不需要 DDL**：`IGNORE INDEX` 能在不改结构、不改数据的前提下制造“索引不可用”的等价场景；
   删索引/`ALTER INDEX … INVISIBLE` 都需要 DDL 权限且要保证恢复可见，演示时容易留下半改状态。
5. **数据规模不支持“再加索引”的结论**：`attack_log` 2525 行、`alerts` 8 行，任何新索引的收益都无法
   在本数据集上被可信测量；能站得住脚的结论只有“计划字段正确”。

**一句话**：索引在索引可用路径上全部被命中，问题只在“有没有用上”，不在“索引够不够”，
所以本轮不动索引结构，只把计划差异固化为可复现证据。

---

## 5. JSON 记录字段（评审读法）

`explain_YYYYMMDDTHHMMSSZ.json` 顶层字段：

| 字段 | 含义（本轮值） |
| --- | --- |
| `generated_at` | 生成时间 UTC（`2026-11-25T05:32:30Z`） |
| `database` | `127.0.0.1:3306/honeypot_dev` |
| `dataset.mysql_version` | `8.0.46` |
| `dataset.tables` | `attack_log=2525, sessions=214, alerts=8, rule_hits=11, attacker_profile=14` |
| `dataset.session_id_used` | `5a060001-0000-4000-8000-000000000001`（Q1 参数） |
| `method` / `timing_runs` | `IGNORE INDEX` 无 DDL 对比；5 次中位数 |
| `indexes.attack_log` / `indexes.alerts` | `SHOW INDEX` 快照（名称、唯一性、可见性、列顺序） |
| `groups[].sql.before/after` | 实际执行的 SQL |
| `groups[].plan_fields.before/after` | `type/key/key_len/rows/rows_produced/filtered/using_filesort/using_index/backward_index_scan/query_cost` |
| `groups[].explain.before/after` | 原始 `EXPLAIN FORMAT=JSON` |
| `groups[].timing_ms.before/after` | `runs/row_count/median_ms/min_ms/max_ms` |
| `groups[].conclusion` | 自动生成的中文结论 |

补充文件 `explain_variants_*.json` 结构相同，另含 `kind="supplementary-variants"`、
`evidence_date="2026-11-25"`、`note` 说明其为 CLI 之外的追加两组。

---

## 6. 验证

| 检查项 | 命令 | 结果（2026-11-25） |
| --- | --- | --- |
| 静态检查 | `/tmp/dbh-venv/bin/python -m ruff check modules/m2-decoy-capture` | **All checks passed!** |
| M2 测试 | `PYTHONPATH=.:modules/... /tmp/dbh-venv/bin/python -m pytest modules/m2-decoy-capture/tests -q` | **16 passed**（22.51s 冷启动 / 1.77s 复跑） |
| CLI 可重跑 | 见 §1 的 `explain_diff` 命令 | 退出码 0，stdout 打印 G1/G2 摘要，新增 `db/explain/explain_<UTC>.json` |
| 变体脚本可重跑 | 见 §1 的 `evidence/explain_variants.py` | 退出码 0，新增 `evidence/explain/explain_variants_<UTC>.json` |
| 只读性 | 全程 `EXPLAIN` / `SELECT` / `SHOW INDEX`，无 DDL/DML | 满足约束（API 8000 未重启） |

---

## 7. 已知限制

| 限制 | 说明 |
| --- | --- |
| 数据规模 | `attack_log` 仅 2525 行，`alerts` 仅 8 行；属于课程验证规模，不构成性能承诺 |
| 耗时噪声 | 单机 Docker + 冷热缓存，已用预热 + 5 次中位缓解；Q2 的毫秒差无意义 |
| 计划估计 | `rows` 是优化器估算（本轮 2432，与表行数 2525 不同），存在采样误差；对比看数量级而不是精确值 |
| before 的语义 | `IGNORE INDEX` 模拟的是“索引不可用”，与“索引不存在”的估计值可能略有差异 |
| 快照时效 | demo 数据可被重灌（`reset_demo`/`gen_demo_data`），代理键会变化；JSON 的 `generated_at` + `dataset` 即快照边界 |

---

## 8. 相关材料

- [`explain/`](explain/)：本轮 2 份 JSON + 2026-11-19 历史 2 份。
- [`explain_variants.py`](explain_variants.py)：补充两组变体的可复现脚本（复用 CLI 的解析/计时函数）。
- [`session-events.md`](session-events.md)：Q1 的同一个会话的完整事件日志与 M4 命中映射。
- `modules/m2-decoy-capture/m2_decoy_capture/cli/explain_diff.py`：CLI 实现（Q1/Q2 定义与结论生成）。
