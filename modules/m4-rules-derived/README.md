# M4 规则配置与派生数据

M4 负责「**规则如何判定**」「**分数与画像是怎么算出来的**」「**告警如何去重**」三件事。
它不拥有表结构（M3）、不拥有事务入口（M1）、不拥有协议采集（M2）与页面（M5）；
所有派生数据都在 M1 打开的同一事务内写入，失败随事务一起回滚。

| 项目 | 内容 |
| --- | --- |
| 包名 | `m4_rules_derived`（安装名 `db-honeypot`） |
| 对外门面 | [`m4_rules_derived/public.py`](m4_rules_derived/public.py) |
| 拥有产物 | `detection_rules` 规则参数与版本、`rule_hits` 命中快照、`attacker_intent` 意图、
  `attacker_profile` 的风险分/等级、`alerts` 的去重键与累计次数 |
| 依赖方向 | M4 → `shared`（配置/连接/事件 Schema）；**不** import M1/M2/M3/M5 内部模块 |
| 契约 | [`specs/002-ui-console-modularization/contracts/module-boundaries.md`](../../specs/002-ui-console-modularization/contracts/module-boundaries.md) §2 |

---

## 1. 目录与职责

```text
m4-rules-derived/
├── m4_rules_derived/
│   ├── public.py              # 唯一跨模块入口：analyze_and_derive / list_* / update_rule
│   ├── rules/                 # 5 条规则定义（阈值参数 + 种子数据）
│   │   ├── base.py            #   Rule 基类、命中结果结构
│   │   ├── r01_scanning.py    #   短时高频连接扫描（frequency / scanning / 权重 10）
│   │   ├── r02_bruteforce.py  #   短时多凭据认证爆破（frequency / bruteforce / 25）
│   │   ├── r03_recon.py       #   元数据与结构探测（keyword / recon / 15）
│   │   ├── r04_data_dump.py   #   会话级批量数据读取（volume / data_dump / 25）
│   │   ├── r05_destructive.py #   破坏性写操作尝试（keyword / destructive / 35）
│   │   └── seed_data.py       #   R01–R05 v1 种子（迁移 0004 使用）
│   ├── risk.py                # 评分纯函数与等级映射（无 I/O，可单测）
│   ├── alerts.py              # 告警去重键、可告警意图、累计次数更新
│   ├── analysis.py            # 单事件分析流水线（规则 → 命中 → 派生 → 告警）
│   └── repositories/rule_repo.py # 规则版本查询/新版本写入
├── tests/{unit,integration,api} # 评分/规则/流水线/规则接口
└── evidence/                  # 规则版本、命中、评分、去重的真实输出
```

## 2. 对外契约（`public.py`）

| 函数 | 语义 | 事务 |
| --- | --- | --- |
| `analyze_and_derive(session, event_row, session_row)` | 对一条已落库事件依次执行 5 条规则 → 写 `rule_hits`（保存 `rule_version`/`risk_weight` 快照）→ 更新画像分数/等级/意图 → 生成或累计告警 | **不提交**，由 M1 事务统一提交/回滚 |
| `list_rules(session, include_history=False, enabled=None)` | 规则列表（默认每个 `rule_code` 仅当前版本） | 只读 |
| `list_rule_effectiveness(session, limit=50)` | 规则效果统计（`v_rule_effectiveness`） | 只读 |
| `update_rule(session, rule_code, ...)` | 生成新规则版本（`enabled_rule_code` 唯一约束保证同规则至多一个启用版本） | 内部单事务提交 |
| `ALERTABLE_INTENTS` | 允许产出告警的意图集合（bruteforce / data_dump / destructive） | 常量 |

跨模块调用只允许走本文件；`analysis.py`、`risk.py`、`alerts.py`、`rules/*` 均为内部实现
（边界门禁 `make boundary` 会拦截绕过 `public.py` 的导入）。

## 3. 规则与评分口径

| rule_code | 规则 | 类型 | 意图 | 权重 | 触发要点（v1） |
| --- | --- | --- | --- | --- | --- |
| R01 | 短时高频连接扫描 | frequency | scanning | 10 | 时间窗内同一来源连接数超阈值 |
| R02 | 短时多凭据认证爆破 | frequency | bruteforce | 25 | 时间窗内认证失败次数/凭据数超阈值 |
| R03 | 元数据与结构探测 | keyword | recon | 15 | `SHOW DATABASES/TABLES`、`DESCRIBE` 等结构探测语句 |
| R04 | 会话级批量数据读取 | volume | data_dump | 25 | 会话内 SELECT 次数/返回量超阈值 |
| R05 | 破坏性写操作尝试 | keyword | destructive | 35 | `UPDATE/DELETE/INSERT/DROP/TRUNCATE` 被拒事件 |

- **分数**：`risk_score = LEAST(100, Σ 每条命中规则权重)`，同一 `rule_code` 只计一次
  （`LEAST(100, …)` 防止多规则叠加溢出）；`risk_level` 为数据库生成列，按分数区间映射
  critical ≥80、high ≥60、medium ≥30、low <30。
- **快照**：`rule_hits` 保存命中时的 `rule_version` 与 `risk_weight`，规则升级后历史命中不重算
  （FR-048），证据见 [`evidence/risk-and-rules.md`](evidence/risk-and-rules.md) §1–§2。
- **意图**：`attacker_intent` 按 `(attacker_id, intent_type)` 去重累计，命中计数用于画像展示。
- **告警去重**：`dedup_key = "<rule_code>:<source_ip>:<UTC 日期>"`，唯一索引 `uk_alerts_dedup_key`；
  同一键重复触发只 `occurrence_count + 1`、刷新 `last_seen`，不新增行（FR-052）。
- **可告警意图**：仅 bruteforce / data_dump / destructive 生成告警；scanning/recon 只留命中与画像。

## 4. 复现命令

以下命令在仓库根执行；MySQL 需已 `make db-up && make migrate`，解释器用
`/tmp/dbh-venv/bin/python`（或项目虚拟环境）：

```bash
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console

# 单测 + 规则接口 + 流水线（真实 MySQL：honeypot_test）
/tmp/dbh-venv/bin/python -m pytest modules/m4-rules-derived/tests -q

# 评分纯函数（无需数据库）
/tmp/dbh-venv/bin/python -m pytest modules/m4-rules-derived/tests/unit/test_risk.py -q

# 规则/命中/评分的真实只读查询：见 evidence/risk-and-rules.md 各节 SQL
```

**期望输出**：`pytest` 全部通过、`ruff check modules/m4-rules-derived` 无告警；
`evidence/risk-and-rules.md` 中的 SQL 可直接在 `honeypot_dev` 复现出同样的规则版本表、
命中分布、画像分数与告警去重结果。

## 5. 验收证据

索引见 [`evidence/README.md`](evidence/README.md)。核心三条：

- [`evidence/risk-and-rules.md`](evidence/risk-and-rules.md)：规则版本与命中、意图评分样例
  （`198.51.100.17` → 85 / critical）、告警去重前后对比（8 行 / 8 个键，重复导入 125 事件 0 新告警）；
- `tests/unit/test_risk.py`：`LEAST(100, Σ)` 与等级边界；
- `tests/integration/test_analysis_pipeline.py`：事件 → 命中 → 画像 → 告警的整链与事务回滚。

## 6. 边界与限制

- **不建表**：`detection_rules`/`rule_hits`/`alerts` 等 DDL 归 M3（`er/schema.mmd`）与 M1 迁移；
  M4 只写数据、不执行 DDL。
- **不提交事务**：`analyze_and_derive` 由 M1 调用方提交；单独调用后必须由调用方 `commit/rollback`。
- **不做实时窗口计算**：命中基于已落库事件与规则参数，时间窗口径在 `rules/*` 内，
  跨会话统计依赖 `v_*` 视图（M5 只读）。
- **规则变更不回溯**：新版本只影响后续命中；历史 `rule_hits` 保留旧版本与权重快照。

## 7. 最近验证

| 项 | 结果 | 时间 |
| --- | --- | --- |
| `pytest modules/m4-rules-derived/tests -q` | 通过（单元 + 接口 + 流水线） | 2026-11-25 |
| `ruff check modules/m4-rules-derived` | All checks passed | 2026-11-25 |
| 证据 SQL（规则版本/命中/评分/去重） | 已在 `honeypot_dev` 实跑，数值见 risk-and-rules.md | 2026-11-25 |
