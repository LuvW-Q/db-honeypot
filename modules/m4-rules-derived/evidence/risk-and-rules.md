# M4 证据：规则版本、命中记录与风险评分

- **任务**：T047（US3）｜**日期**：2026-11-25｜**数据库**：MySQL 8.0 `honeypot_dev`（确定性 demo 种子）
- **口径来源**：`m4_rules_derived/rules/`（规则参数）、`risk.py`（评分纯函数）、`analysis.py`（派生写入）
- **复现**：`PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console /tmp/dbh-venv/bin/python` 连接 `honeypot_dev` 执行下文 SQL

## 1. 规则版本表（detection_rules）

```sql
select rule_id,rule_code,rule_name,rule_type,intent_type,risk_weight,rule_version,enabled,enabled_rule_code
from detection_rules order by rule_code;
```

| rule_id | rule_code | rule_name | rule_type | intent_type | risk_weight | rule_version | enabled | enabled_rule_code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | R01 | 短时高频连接扫描 | frequency | scanning | 10 | 1 | 1 | R01 |
| 2 | R02 | 短时多凭据认证爆破 | frequency | bruteforce | 25 | 1 | 1 | R02 |
| 3 | R03 | 元数据与结构探测 | keyword | recon | 15 | 1 | 1 | R03 |
| 4 | R04 | 会话级批量数据读取 | volume | data_dump | 25 | 1 | 1 | R04 |
| 5 | R05 | 破坏性写操作尝试 | keyword | destructive | 35 | 1 | 1 | R05 |

结论：5 条规则各 1 个启用版本，`risk_weight` 与 `risk.py` 口径一致（R05 最高 35，R01 最低 10）。

## 2. 命中记录（rule_hits）

```sql
select rule_code,intent_type,rule_version,count(*) hits,count(distinct session_id) sessions,
       min(triggered_at) first_hit,max(triggered_at) last_hit
from rule_hits group by rule_code,intent_type,rule_version order by rule_code;
```

| rule_code | intent_type | rule_version | hits | sessions | first_hit | last_hit |
| --- | --- | --- | --- | --- | --- | --- |
| R01 | scanning | 1 | 2 | 2 | 2026-11-18 05:00:09 | 2026-11-18 07:00:09 |
| R02 | bruteforce | 1 | 3 | 3 | 2026-11-18 02:00:08 | 2026-11-18 07:20:08 |
| R03 | recon | 1 | 1 | 1 | 2026-11-18 01:00:02 | 2026-11-18 01:00:02 |
| R04 | data_dump | 1 | 3 | 3 | 2026-11-18 03:00:06 | 2026-11-18 07:50:05 |
| R05 | destructive | 1 | 2 | 2 | 2026-11-18 04:00:02 | 2026-11-18 06:00:14 |

结论：命中记录带 `rule_version` 快照；版本升级后旧命中仍保留触发时版本号（可追溯）。

## 3. 意图评分样例（attacker_intent，IP 198.51.100.17）

```sql
select p.source_ip,i.intent_type,i.intent_score,i.evidence_count,i.first_detected_at,i.last_detected_at
from attacker_intent i join attacker_profile p on p.attacker_id=i.attacker_id
where p.source_ip='198.51.100.17' order by i.intent_score desc;
```

| source_ip | intent_type | intent_score | evidence_count | first_detected_at | last_detected_at |
| --- | --- | --- | --- | --- | --- |
| 198.51.100.17 | destructive | 35 | 1 | 2026-11-18 06:00:14 | 2026-11-18 06:00:14 |
| 198.51.100.17 | bruteforce | 25 | 1 | 2026-11-18 06:00:08 | 2026-11-18 06:00:08 |
| 198.51.100.17 | data_dump | 25 | 1 | 2026-11-18 06:00:13 | 2026-11-18 06:00:13 |

画像风险分（`attacker_profile`）：

```sql
select source_ip,risk_score,risk_level,total_connections,total_queries,total_auth_attempts,total_auth_failures,evidence_summary
from attacker_profile where source_ip='198.51.100.17';
```

| source_ip | risk_score | risk_level | total_connections | total_queries | total_auth_attempts | total_auth_failures | evidence_summary |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 198.51.100.17 | 85 | critical | 1 | 6 | 8 | 8 | 命中规则：R05×1(权重35)、R02×1(权重25)、R04×1(权重25)；最近事件 disconnect |

**评分推导（与 `risk.py` 一致）**：画像分 = `LEAST(100, Σ 各 rule_code 最大权重)` = 35(R05) + 25(R02) + 25(R04) = **85 → critical**；意图分按 `intent_type` 分组后同规则去重取最大权重，因此 destructive=35、bruteforce=25、data_dump=25。注意画像分**不是**意图分相加后再封顶（destructive 35 + bruteforce 25 + data_dump 25 = 85 恰好同值，但口径不同：画像分按规则维度聚合）。

## 4. 告警去重前后对比

去重键：`dedup_key = "<rule_code>:<source_ip>:<UTC 日期>"`，唯一约束 `uk_alerts_dedup_key`；首触发 INSERT，重复触发原子 `UPDATE occurrence_count+1 / last_seen_at / latest_hit_id / evidence_summary`。

### 4.1 当前告警分布（重复导入前）

```sql
select count(*) total,count(distinct dedup_key) distinct_keys,sum(is_read) read_cnt from alerts;
```

| total | distinct_keys | read_cnt |
| --- | --- | --- |
| 8 | 8 | 0 |

```sql
select dedup_key,count(*) c from alerts group by dedup_key having c>1;
```

结果：**空集**（0 行），每个 `dedup_key` 唯一。

### 4.2 重复导入（幂等 / 去重）

命令：

```bash
PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console \
  /tmp/dbh-venv/bin/python -m m2_decoy_capture.cli.import_samples --set demo_basic --json
```

真实输出摘要（`imported`/`deduped`/`failed`）：

```json
{"imported": {"sessions": 0, "events": 0, "rule_hits": 0, "alerts": 0},
 "deduped": {"sessions": 0, "events": 125, "rule_hits": 0, "alerts": 0},
 "failed": []}
```

逐样本（第二次导入全部走幂等路径，无新增告警）：

| sample | status | deduped_events | new_alerts |
| --- | --- | --- | --- |
| S01 | imported | 4 | [] |
| S02 | imported | 19 | [] |
| S03 | imported | 8 | [] |
| S04 | imported | 4 | [] |
| S05 | imported | 11 | [] |
| S06 | imported | 16 | [] |
| S07 | imported | 63 | [] |

去重后再查：

```sql
select count(*) total,count(distinct dedup_key) distinct_keys,sum(is_read) read_cnt from alerts;
```

| total | distinct_keys | read_cnt |
| --- | --- | --- |
| 8 | 8 | 0 |

结论：重复导入 125 条事件、0 条新增告警，`alerts` 总数与去重键数不变（8/8），满足 FR-052 幂等与告警去重要求。

### 4.3 告警样本（去重键结构）

```sql
select alert_id,dedup_key,rule_code,alert_type,severity,occurrence_count,is_read from alerts order by alert_id limit 10;
```

| alert_id | dedup_key | rule_code | alert_type | severity | occurrence_count | is_read |
| --- | --- | --- | --- | --- | --- | --- |
| 60 | R02:198.51.100.12:2026-11-18 | R02 | bruteforce | medium | 1 | 0 |
| 61 | R04:198.51.100.14:2026-11-18 | R04 | data_dump | high | 1 | 0 |
| 62 | R05:198.51.100.15:2026-11-18 | R05 | destructive | critical | 1 | 0 |
| 63 | R02:198.51.100.17:2026-11-18 | R02 | bruteforce | medium | 1 | 0 |
| 64 | R04:198.51.100.17:2026-11-18 | R04 | data_dump | high | 1 | 0 |
| 65 | R05:198.51.100.17:2026-11-18 | R05 | destructive | critical | 1 | 0 |
| 66 | R02:198.51.100.20:2026-11-18 | R02 | bruteforce | medium | 1 | 0 |
| 67 | R04:198.51.100.23:2026-11-18 | R04 | data_dump | high | 1 | 0 |

## 5. 验证

- `ruff check modules/m4-rules-derived`：All checks passed（与本次证据同时执行）。
- `pytest modules/m4-rules-derived/tests -q`：见模块 README「最近验证」；本次证据只读查询未改代码。
