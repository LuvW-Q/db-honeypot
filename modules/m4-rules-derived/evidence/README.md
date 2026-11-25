# 证据索引

M4「规则配置、证据关联与派生数据」的验收证据。所有数值来自 `honeypot_dev` 的确定性 demo
种子（`attack_log=2525`、`sessions=214`、`rule_hits=11`、`alerts=8`、`attacker_profile=14`），
由**真实执行**的只读查询产生。

- 证据日期：**2026-11-25**
- 解释器：`/tmp/dbh-venv/bin/python`；MySQL 8.0.46 容器 `dbhoneypot-mysql`
- `PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console`

| 证据编号 | 对应用户故事 / FR | 复现命令 | 期望输出 | 产物路径 | 依赖 | 最近验证时间 |
| --- | --- | --- | --- | --- | --- | --- |
| E-M4-001 | US3 / T047；FR-048 / FR-127（规则版本与命中记录） | 见 [risk-and-rules.md](risk-and-rules.md) §1–§2 的 SQL | `detection_rules` 5 条各 1 个启用版本，`risk_weight` 10/25/15/25/35；“命中分布”按 `rule_code` 聚合出 `rule_version` 与命中数 | [risk-and-rules.md](risk-and-rules.md) §1–§2 | `honeypot_dev` + `honeypot_app_ro` | 2026-11-25 |
| E-M4-002 | US3 / T047；FR-049 / FR-127（意图与评分可追溯） | 同文件 §3 SQL（`attacker_intent` ⋈ `attacker_profile`，IP `198.51.100.17`） | 分数 85 = 25+25+35，等级 `critical`；意图计数与命中快照可逐条对上 | [risk-and-rules.md](risk-and-rules.md) §3 | E-M4-001 同库 | 2026-11-25 |
| E-M4-003 | US3 / T047；FR-052 / FR-127（告警去重） | 同文件 §4.2：`python -m m2_decoy_capture.cli.import_samples --set demo_basic --json` | `imported` 新增 0、`deduped.events=125`、`failed=[]`；重复导入后 `alerts` 仍 8 行、8 个 `dedup_key`、0 新增告警 | [risk-and-rules.md](risk-and-rules.md) §4 | demo 样本已导入过一轮；`alerts.uk_alerts_dedup_key` 存在 | 2026-11-25 |
| E-M4-004 | US3 / T047；FR-129（可独立复现） | `/tmp/dbh-venv/bin/python -m pytest modules/m4-rules-derived/tests -q`；`/tmp/dbh-venv/bin/python -m ruff check modules/m4-rules-derived` | pytest 全绿（真实 MySQL `honeypot_test`）；ruff `All checks passed!` | 终端输出；本目录只留结论 | 解释器 + 测试库 | 2026-11-25 |

## 结论摘要

1. 规则版本可追溯：5 条规则各一个启用版本，`rule_hits` 保存命中时的版本与权重快照，
   规则升级不改变历史命中的解释（E-M4-001）。
2. 评分可解释：`risk_score = LEAST(100, Σ 权重)`，画像 85 分 = R02(25)+R04(25)+R05(35)，
   等级由数据库生成列映射，页面与 SQL 一致（E-M4-002）。
3. 去重有效：重复导入 125 条事件、0 条新增告警，`occurrence_count` 累计而不扩散行数（E-M4-003）。
4. 实现与测试同源：`public.py` 是唯一跨模块入口，单测/接口测试/集成测试全部通过（E-M4-004）。

## 说明

- 代理键（`rule_id/hit_id/alert_id`）随重置变化，证据以 `rule_code`、`source_ip`、`dedup_key` 锚定。
- 本目录不含业务代码；所有 SQL 均为只读查询，不改数据。
