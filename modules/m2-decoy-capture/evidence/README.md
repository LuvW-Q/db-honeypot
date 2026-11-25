# 证据索引

M2「诱饵交互与事件采集」的验收证据。全部产物由**真实执行**生成（只读查询 / EXPLAIN，
无 DDL、无写入、不重启 API）；统一环境见下表与各 md 的「环境」表。

- 证据日期：**2026-11-25**
- 环境：仓库根 `/Users/luvwq/Documents/大学资料/课程资料/大二上/数据库/项目/db-honeypot`；
  MySQL 8.0.46 容器 `dbhoneypot-mysql`，库 `honeypot_dev`，只读账号 `honeypot_app_ro`；
  解释器 `/tmp/dbh-venv/bin/python`（不是仓库 `.venv`）；
  `PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console`
- 数据快照（确定性 demo）：`attack_log=2525`、`sessions=214`、`alerts=8`、`rule_hits=11`、
  `attacker_profile=14`；样本会话 `5a060001-0000-4000-8000-000000000001`

| 证据编号 | 对应用户故事 / FR | 复现命令 | 期望输出 | 产物路径 | 依赖 | 最近验证时间 |
| --- | --- | --- | --- | --- | --- | --- |
| E-M2-001 | US3 / T045；FR-125（同一会话完整事件日志） | `docker exec -i dbhoneypot-mysql mysql -h127.0.0.1 -P3306 --protocol=TCP --default-character-set=utf8mb4 -uhoneypot_app_ro -p'TestOnly-AppRo-2026' --table honeypot_dev < modules/m2-decoy-capture/evidence/session-events.sql` | 16 条事件按 `event_time` 升序；首条 `connect`、8 条 `auth failure`、5 条 `SELECT … success`、1 条 `DROP … denied`、末条 `disconnect` | [`session-events.md`](session-events.md) §1–§3、[`session-events.sql`](session-events.sql)、[`session-events.out.txt`](session-events.out.txt) | dev 库样本会话存在；容器 mysql 客户端 | 2026-11-25 |
| E-M2-002 | US3 / T045；FR-125（时间线可完整还原 + 命中可追溯，衔接 FR-127） | 同 E-M2-001（`session-events.sql` §4–§5）或 `session-events.md` §6 的 python 只读片段 | `rule_hits` 3 行：R02(25, bruteforce)@06:00:08、R04(25, data_dump)@06:00:13、R05(35, destructive)@06:00:14；`alerts` 3 行 medium/high/critical；`max_risk_score=85=25+25+35` | [`session-events.md`](session-events.md) §4 | E-M2-001；M4 规则已灌入 `detection_rules` | 2026-11-25 |
| E-M2-003 | US3 / T045；FR-125（时间线查询建立索引前后的 EXPLAIN 对比） | `PYTHONPATH=…  /tmp/dbh-venv/bin/python -m m2_decoy_capture.cli.explain_diff`（输出在仓库根 `db/explain/`，本轮已 `cp` 进 `evidence/explain/`） | 退出码 0；G1 `ALL→ref`、`rows 2432→16`、filesort 消除；G2 `ALL→ref`、`rows 8→2` | [`explain-diff.md`](explain-diff.md) §3、[`explain/explain_20261125T053230Z.json`](explain/explain_20261125T053230Z.json) | dev 库 + 只读账号；`attack_log`/`alerts` 索引已迁移 | 2026-11-25 |
| E-M2-004 | US3 / T045 补充；FR-125（同一时间线的不同写法）、FR-129 | `PYTHONPATH=… /tmp/dbh-venv/bin/python modules/m2-decoy-capture/evidence/explain_variants.py` | 退出码 0；G3 `ALL→range`、`key_len 36→44`、`rows 2432→7`；G4 `ALL→ref`、`idx_log_source_time`、反向扫描 | [`explain-diff.md`](explain-diff.md) §3.3–§3.4、[`explain_variants.py`](explain_variants.py)、[`explain/explain_variants_20261125T053414Z.json`](explain/explain_variants_20261125T053414Z.json) | 同 E-M2-003 | 2026-11-25 |
| E-M2-005 | US3 / T045；FR-129（可独立复现）、SC-028 | `/tmp/dbh-venv/bin/python -m ruff check modules/m2-decoy-capture`；`PYTHONPATH=… /tmp/dbh-venv/bin/python -m pytest modules/m2-decoy-capture/tests -q` | `All checks passed!`（退出码 0）；`16 passed`（冷启动 22.51s / 复跑 1.77s） | [`session-events.md`](session-events.md) §7、[`explain-diff.md`](explain-diff.md) §6 | 解释器 `/tmp/dbh-venv/bin/python`、dev 库 | 2026-11-25 |

## 结论摘要

1. 样本会话 `5a060001-…-0001` 的 16 条事件可完整还原为“连接 → 8 次认证失败 → 5 次批量 SELECT →
   被拒 `DROP` → 断开”，并一一对应到 M4 的 R02 / R04 / R05 命中与 3 条告警（E-M2-001/002）。
2. 会话时间线查询 `ALL → ref`（扫描行数 2432 → 16、filesort 消除），增量拉取写法 `ALL → range`
   （key_len 36 → 44）；来源 IP 溯源查询命中 `idx_log_source_time`；告警等级查询命中
   `idx_alert_level_time`（表仅 8 行，耗时差属噪声）。
3. 现有复合索引已覆盖演示查询，本轮**不改索引结构**：理由见 [`explain-diff.md`](explain-diff.md) §4。
4. `ruff check` 干净、M2 测试 16 passed（E-M2-005）。

## 说明

- `explain/` 中另有 2026-11-19 的两份 JSON（`explain_20261119T145225Z.json`、
  `explain_20261119T145423Z.json`），由旧 `app.cli.explain_diff` 生成，作为历史记录保留、
  不被本轮覆盖；评审以 2026-11-25 的两份为准。
- 代理键（`event_id/hit_id/alert_id`）是自增列，重灌 demo 数据后会变化；证据以 `session_id` /
  `event_uuid` 锚定，见 [`session-events.md`](session-events.md) §2 口径说明。
- 本目录不含业务代码；新增的 `explain_variants.py` 仅复用模块 CLI 的解析/计时函数做补充对比。
