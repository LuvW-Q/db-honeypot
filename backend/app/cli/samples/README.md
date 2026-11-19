# 固定合成样本目录

本目录定义导入脚本使用的固定夹具（`contracts/api.md` 第 4 章、`contracts/events.md`
第 3/4 章）。所有事件时间、`event_uuid`、`session_id` 均在 `catalog.py` 中写死，
重复导入完全幂等；SQL 只作为字符串保存，导入过程**绝不执行**样本中的 SQL。

## 样本与预期

| 样本 | 内容 | 预期规则命中 | 会话风险分/等级 | 预期告警 |
| --- | --- | --- | --- | --- |
| S01 | 连接 + 认证 + `SHOW TABLES` + 断开（闭环） | R03（recon +15） | 15 / low | 无 |
| S02 | 边界内 8 次失败认证；边界外 7 次 | R02（bruteforce +25） | 25 / low（边界外 0） | `bruteforce` / medium ×1 |
| S03 | 同一会话连续 5 次 SELECT、累计 1000 行 | R04（data_dump +25） | 25 / low | `data_dump` / high ×1 |
| S04 | `DROP TABLE fake_orders` 被拒绝 | R05（destructive +35） | 35 / medium | `destructive` / critical ×1 |
| S05 | 60 秒内 10 次 connect、无有效 SQL | R01（scanning +10） | 10 / low | 无 |
| S06 | 8 次失败认证 + 5 次 SELECT + DROP 被拒绝 | R02 + R04 + R05 | 85 / critical | medium + high + critical ×3 |
| S07 | R01/R02/R04 阈值内与阈值外各一组 | R01、R02、R04 | 25 / low（边界外 0） | `bruteforce` medium、`data_dump` high 各 1 |

`demo_basic` = S01–S07，一次导入覆盖 R01–R05；`recon_only` = S01–S03（契约保留的轻量集合）。

## 编号口径说明

任务要求采用「S01 闭环 / S02 认证失败边界 / S03 拖库 / S04 破坏性 / S05 扫描 /
S06 综合 / S07 阈值边界」编号；`contracts/api.md` 4.3 的旧编号表与本目录存在差异，
但规则命中、风险分与告警等级映射（R02→medium、R04→high、R05→critical）严格遵循
该契约与 `events.md` 6.5。

## 安全约定

- 来源全部使用 RFC 5737 文档保留网段 `198.51.100.0/24`；
- 认证样本只保存 `username` 与 `credential_test_id`（`TEST-ONLY-*`），不含口令；
- 所有 SQL 为合成语句，指向 `fake_*` 诱饵表，不指向真实业务数据。
