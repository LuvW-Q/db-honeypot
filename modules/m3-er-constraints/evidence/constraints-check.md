# M3 证据：约束正反样例与 ER 渲染执行记录

| 项目 | 内容 |
| --- | --- |
| 日期 | **2026-11-25** |
| 环境 | 容器 `dbhoneypot-mysql`（`mysql:8.0`，实测 **8.0.46**），库 `honeypot_dev`，会话时区 `+00:00` |
| 解释器 | `/tmp/dbh-venv/bin/python`（Python 3.13.5，SQLAlchemy 2.1 + asyncmy） |
| 覆盖任务 | T013（ER/约束目录/反查工具/正反样例）、T046（M3 证据产出） |
| 结论 | 结构对账 11 表 / 10 FK / 12 UNIQUE / 38 CHECK / 45 索引 / 2 生成列与迁移一致；SQL 样例实测 7 类约束拒绝 + 2 个正例，最终 `all_unchanged=1`；ER 图由 mermaid-cli 11.17.1 渲染成功 |
| 证据文件 | [`constraints.json`](constraints.json)、[`schema.svg`](schema.svg)、[`schema.png`](schema.png)、本文件 |

> 本文件中的命令与输出均为真实执行结果；`ERROR NNNN` 是**预期**的约束拒绝（脚本故意触发），
> 不是失败。执行时 stdout 与 stderr 用 `2>&1` 合并，故错误行与表头行会交错出现。

## 1. 环境快照

```console
$ docker ps --filter name=dbhoneypot-mysql --format '{{.Names}} {{.Image}} {{.Status}}'
dbhoneypot-mysql mysql:8.0 Up 2 hours (healthy)

$ docker exec -i dbhoneypot-mysql mysql -uroot -p*** -N \
    -e "SELECT VERSION(), @@session.time_zone, @@GLOBAL.sql_mode;"
8.0.46	+00:00	ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION
```

`STRICT_TRANS_TABLES` 开启是 S8（无符号列写 -1 报 1264 而非被静默截断为 0）的前提。

## 2. 约束反查：`tools/introspect_constraints.py`

### 2.1 摘要输出（默认模式）

```console
$ PYTHONPATH=. /tmp/dbh-venv/bin/python \
    modules/m3-er-constraints/tools/introspect_constraints.py
库: honeypot_dev    MySQL: 8.0.46    时区: +00:00
连接: mysql+asyncmy://honeypot_app_rw:***@127.0.0.1:3306/honeypot_dev?charset=utf8mb4
业务表 11 / 基础表 12 / 视图 4
外键 10 / 唯一 12 / CHECK 38 / 索引 45 / 生成列 2

表名                   列  PK  FK  UK  CK  IDX     行数
alembic_version      1   1   0   0   0    1      1
alerts              18   1   4   1   6    9      8
attack_log          15   1   1   2   5    5   2525
attacker_intent      9   1   1   1   3    3     11
attacker_profile    14   1   0   1   2    3     14
audit_log            9   1   0   0   2    3     20
detection_rules     13   1   0   2   5    4      5
fake_config          8   1   0   1   3    2      5
fake_orders          9   1   1   1   3    3    120
fake_users           8   1   0   2   2    3     30
rule_hits           11   1   3   1   3    5     11
sessions            12   1   0   0   4    4    214
v_attacker_profile_summary  21   0   0   0   0    0      -
v_daily_attack_trend  19   0   0   0   0    0      -
v_rule_effectiveness  18   0   0   0   0    0      -
v_session_risk_summary  26   0   0   0   0    0      -

视图: v_attacker_profile_summary, v_daily_attack_trend, v_rule_effectiveness, v_session_risk_summary
[exit=0]
```

### 2.2 落盘 JSON 证据

```console
$ PYTHONPATH=. /tmp/dbh-venv/bin/python \
    modules/m3-er-constraints/tools/introspect_constraints.py \
    --out modules/m3-er-constraints/evidence/constraints.json
[introspect] 已写入 modules/m3-er-constraints/evidence/constraints.json
$ ... --json | /tmp/dbh-venv/bin/python -c "import json,sys; d=json.load(sys.stdin); ..."
valid JSON, keys: ['meta', 'summary', 'tables', 'views'] tables: 16
summary: {"schema": "honeypot_dev", "base_tables": 12, "business_tables": 11, "business_table_names": ["alerts", "attack_log", "attacker_intent", "attacker_profile", "audit_log", "detection_rules", "fake_config", "fake_orders", "fake_users", "rule_hits", "sessions"], "views": 4, "view_names": ["v_attacker_profile_summary", "v_daily_attack_trend", "v_rule_effectiveness", "v_session_risk_summary"], "foreign_keys": 10, "unique_constraints": 12, "check_constraints": 38, "indexes": 45, "generated_columns": 2, "rows_total": 2964}
```

说明：`--json` 时 **stdout 只有 JSON**（`[introspect] 已写入 ...` 走 stderr），可直接管道解析；
连接失败返回 **1**（实测错误账号报 `Access denied ... (1045)`），参数错误由 argparse 返回 2。

### 2.3 原始 JSON 结构

```text
meta     采集时间/库名/脱敏 DSN/MySQL 版本/时区/sql_mode
summary  业务表 11、视图 4、FK 10、UNIQUE 12、CHECK 38、索引 45、生成列 2、总行数 2964
tables   每表 columns（类型/可空/默认/额外/生成列表达式/注释）、primary_key、
         foreign_keys（引用表/列/update_rule/delete_rule）、unique_constraints、
         check_constraints（check_clause 原文）、indexes（唯一性/列序/基数/可见性）
views    4 个视图的 security_type 与定义
```

`evidence/constraints.json` 是 `constraints/catalog.md` 的机器可读源；两者一一对应。

## 3. `constraints/verify_constraints.sql` 实跑

### 3.1 执行命令与完整输出

```console
$ docker exec -i dbhoneypot-mysql mysql --force -uroot -p*** honeypot_dev < modules/m3-er-constraints/constraints/verify_constraints.sql
ERROR 1452 (23000) at line 57: Cannot add or update a child row: a foreign key constraint fails (`honeypot_dev`.`attack_log`, CONSTRAINT `fk_log_session` FOREIGN KEY (`session_id`) REFERENCES `sessions` (`session_id`) ON DELETE RESTRICT ON UPDATE RESTRICT)
mysql_version	session_time_zone	current_schema	autocommit
8.0.46	+00:00	honeypot_dev	1
base_sessions	base_attack_log	base_profile	base_rule_hits	base_alerts
214	2525	14	11	8
sample	session_rows	event_rows
S2 合法插入	1	1
ERROR 3819 (HY000) at line 87: Check constraint 'ck_sessions_status' is violated.
ERROR 3819 (HY000) at line 94: Check constraint 'ck_profile_risk_score' is violated.
ERROR 1062 (23000) at line 131: Duplicate entry '4ca2a0e9-e890-11f1-b4d6-c22b5974fdd2' for key 'attack_log.uk_attack_log_event_uuid'
sample	risk_score	risk_level	generated_level_ok
S5 风险分边界+生成列	80	critical	1
ERROR 1062 (23000) at line 152: Duplicate entry '203.0.113.250' for key 'attacker_profile.uk_attacker_profile_source_ip'
sample	rows_with_uuid
S6 首次写入保留	1
sample	rows_with_ip
S7 首行保留	1
ERROR 1264 (22003) at line 164: Out of range value for column 'total_connections' at row 1
ERROR 1451 (23000) at line 183: Cannot delete or update a parent row: a foreign key constraint fails (`honeypot_dev`.`attack_log`, CONSTRAINT `fk_log_session` FOREIGN KEY (`session_id`) REFERENCES `sessions` (`session_id`) ON DELETE RESTRICT ON UPDATE RESTRICT)
sample	session_rows
S9 删除被拒后会话仍在	1
sessions_unchanged	attack_log_unchanged	profile_unchanged	rule_hits_unchanged	alerts_unchanged	all_unchanged
1	1	1	1	1	1
expected_level	stored_level	rows_cnt
low	low	12
medium	medium	1
critical	critical	1
[exit=0]
```

### 3.2 逐条判读（错误码取自上面真实输出）

| 样例 | 类别 | 触发语句 | 实测错误码与约束 | 说明 |
| --- | --- | --- | --- | --- |
| S1 | FK 拒绝 | `attack_log` 插入不存在的 `session_id` | `ERROR 1452` `fk_log_session` | 子行无父行；MySQL 8.4 上同类错误为 1216 |
| S2 | FK 正例 | 先插会话再插事件 | 无错误；`session_rows=1, event_rows=1` | 合法链路可写入，随后 `ROLLBACK TO SAVEPOINT` 复原 |
| S3 | CHECK/ENUM 拒绝 | `sessions.session_status='hacked'` | `ERROR 3819` `ck_sessions_status` | 枚举只有 active/closed/timeout/error |
| S4 | CHECK 拒绝 | `attacker_profile.risk_score=101` | `ERROR 3819` `ck_profile_risk_score` | 分数上界 100 |
| S5 | CHECK 正例 + 生成列 | `risk_score=80` | 无错误；`risk_level=critical, generated_level_ok=1` | VIRTUAL 生成列按 80/60/30 阈值实时计算 |
| S6 | UNIQUE 拒绝 | 同一 `event_uuid` 重复投递 | `ERROR 1062` `uk_attack_log_event_uuid` | 事件幂等的数据库保证；首次写入保留 1 行 |
| S7 | UNIQUE 拒绝 | 同一 `source_ip` 两行画像 | `ERROR 1062` `uk_attacker_profile_source_ip` | 一来源一画像；首行保留 |
| S8 | 无符号拒绝 | `total_connections=-1` | `ERROR 1264` Out of range | INT UNSIGNED 下界由类型本身保证 |
| S9 | FK RESTRICT 拒绝 | 删除仍被 `attack_log` 引用的会话 | `ERROR 1451` `fk_log_session` | `ON DELETE RESTRICT`；MySQL 8.4 上为 1217 |
| 收尾 | 不污染校验 | `ROLLBACK` 后对比基线 | 5 个 `*_unchanged=1`，`all_unchanged=1` | 行数与脚本开始时完全一致 |

### 3.3 为什么用 `mysql --force`

`mysql` 批量模式默认遇到第一个 SQL 错误即中止，脚本后续样例不会执行。
`--force` 让客户端在记录错误后继续，因此才能在一个文件里连续展示多类拒绝；
事务语义不受影响——每条语句失败只回滚该语句，最终 `ROLLBACK` 清空全部正例插入。

### 3.4 不污染的证明

脚本开头把 5 张核心表的行数存入会话变量（`@base_sessions` 等），`ROLLBACK` 之后重新
`COUNT(*)` 对比，输出：

```text
sessions_unchanged  attack_log_unchanged  profile_unchanged  rule_hits_unchanged  alerts_unchanged  all_unchanged
1                   1                     1                  1                    1                 1
```

会话变量不受 `ROLLBACK` 影响，所以这是对“回滚是否彻底”的独立校验，而非同事务内自证。

## 4. ER 图渲染：`er/schema.mmd` → `evidence/schema.svg` / `schema.png`

### 4.1 工具与命令

```console
$ node -v
v24.22.2
$ npm_config_cache=/tmp/npm-cache npx -y @mermaid-js/mermaid-cli@11 --version
11.17.1
```

```console
$ npm_config_cache=/tmp/npm-cache PUPPETEER_EXECUTABLE_PATH=<chromium-bin> npx -y @mermaid-js/mermaid-cli@11 -p modules/m3-er-constraints/er/puppeteer-config.json -i modules/m3-er-constraints/er/schema.mmd -o modules/m3-er-constraints/evidence/schema.svg -b white
Generating single mermaid chart
[svg exit=0]

$ ... -o modules/m3-er-constraints/evidence/schema.png -s 2
Generating single mermaid chart
[png exit=0]
```

- 渲染器：`@mermaid-js/mermaid-cli@11.17.1`（npx 临时安装；`npm_config_cache=/tmp/npm-cache` 绕过宿主 `~/.npm` 权限问题）；
- 无头浏览器：`PUPPETEER_EXECUTABLE_PATH` 指向已存在的 Playwright Chromium
  `/tmp/pw-browsers/chromium-1255/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`；
- 启动参数：模块内 [`../er/puppeteer-config.json`](../er/puppeteer-config.json)
  （`--no-sandbox --disable-dev-shm-usage --disable-gpu`）；实测缺少该参数文件时
  mermaid-cli 会在 `page.close` 处抛 `ConnectionClosedError`；
- 产物：`schema.svg` **402602 字节**（矢量）、`schema.png` **249113 字节**（1568×1174，`-s 2`）；
- `mmdc` 解析并渲染成功即代表 Mermaid 语法有效；**未做**任何图片伪造或占位。

### 4.2 渲染内容核对

SVG/PNG 中可见 11 张业务表的列清单与 PK/FK/UK 标记、10 条外键关系标签
（`fk_log_session`、`fk_hit_log`、`fk_hit_session`、`fk_hit_rule`、`fk_alert_session`、
`fk_alert_attacker`、`fk_alert_rule`、`fk_alert_latest_hit`、`fk_intent_profile`、
`fk_fake_orders_user`）以及 `attacker_profile }o..o{ sessions` 的逻辑聚合虚线。

### 4.3 踩坑记录（真实、可复现）

`erDiagram` 关键字之前不能放 `%%` 注释；且整行只有 `%%` 的注释行会让 mermaid 预处理器
把后续行合并成一行并报 `Parse error on line 2 ... got '%'`。本文件已把所有注释移到
`erDiagram` 之后并删除空注释行；后续编辑请遵守这两条，否则渲染失败。

## 5. 结论、覆盖边界与已知差异

1. **结构对账通过**：迁移 0001/0003 声明的 11 表、10 FK、12 UK、38 CHECK、2 生成列与
   `information_schema` 实查完全一致；45 条索引 = 12 主键 + 12 唯一支撑 + 21 普通。
2. **约束活体生效**：FK 子行/父行、CHECK 枚举/上界、UNIQUE 幂等/画像、无符号下界均被数据库拒绝，
   合法样例可写入，回滚后行数不变。
3. **错误码口径**：本环境（8.0.46）FK 子行 **1452**、父行删除 **1451**；MySQL 8.4 对应
   **1216/1217**，CHECK 一律 **3819**，UNIQUE **1062**，数值越界 **1264**。若 CI 升级到 8.4，
   断言需按此放宽（现有 pytest 同时兼容两套编码）。
4. **行数是时点快照**：dev 库被多个模块的验证流程共用（实测同期 `audit_log` 因
   `reset_demo`/告警已读写入从 16 增至 20 行）。因此 `constraints.json` 的 `row_count`
   与本文件基线数字只代表采集时刻；结构断言不受影响。
5. **未覆盖（不在 M3 范围）**：4 个分析视图的 SQL 口径属 M5；表级最小权限（`GRANT`）属 M1 的
   `db/grants/`；应用层跨表一致性（如 `attack_log.source_ip` 与会话一致）由事务与校验 SQL 保证，
   非数据库约束。
