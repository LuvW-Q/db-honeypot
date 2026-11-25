# 证据：数据库四类账号与最小权限（GRANT）

- 任务：002 / T044（M1 证据）
- 对应需求：**FR-068**（只读控制台 / 最小权限）、**FR-079**（仅授权主机与隔离网段，
  禁止 `%` 通配）、**FR-082**（字段级最小暴露，导出需字段审查）；
  宪法原则三（安全与最小权限）、数据模型 §11（账号清单 / 权限矩阵 / GRANT 语句）
- 验证时间：2026-11-25T13:33+08:00（Asia/Shanghai）
- 环境：MySQL 8.0.46（容器 `dbhoneypot-mysql`，映射 `127.0.0.1:3306`）、
  运行库 `honeypot_dev` / `honeypot_demo`、测试库 `honeypot_test`

## 1. 依据文件

| 文件 | 作用 |
| --- | --- |
| [`db/init/01-init-databases.sh`](../db/init/01-init-databases.sh) | 建库 + 创建四类账号（`127.0.0.1` 与 `172.28.0.%` 两套）+ 库级授权 |
| [`db/grants/apply_table_grants.sh`](../db/grants/apply_table_grants.sh) | 迁移后表级收口：`audit_log` 仅追加、`detection_rules` 不可删除、`fake_users` 列级授权 |
| `specs/001-database-honeypot/data-model.md` §11.1–11.3 | 账号职责、权限矩阵与 GRANT/REVOKE 语句（设计口径） |
| `.env`（本地，未入库） | `MIGRATE_/DATABASE_/READONLY_/TEST_DATABASE_URL` 四个连接串与口令 |

四类账号与连接的对应关系：

| 用途 | 连接串 | 账号 | 目标库 |
| --- | --- | --- | --- |
| 迁移 / DDL / 种子 / 视图 | `MIGRATE_DATABASE_URL` | `honeypot_migrate` | `honeypot_dev`（`honeypot_demo` 同权限） |
| 诱饵服务与分析业务读写 | `DATABASE_URL` | `honeypot_app_rw` | `honeypot_dev` |
| 控制台只读查询 | `READONLY_DATABASE_URL` | `honeypot_app_ro` | `honeypot_dev` |
| 测试（及备份） | `TEST_DATABASE_URL` | `honeypot_migrate` | `honeypot_test` |

> 说明：测试库不新增独立账号，测试通过迁移账号连接 `honeypot_test`
> （`TEST_DATABASE_URL`），这是 `pyproject`/`conftest` 的既定做法；备份账号
> `honeypot_backup` 用于只读 + 锁表备份，不参与业务。

## 2. 设计权限矩阵（data-model §11.2 口径）

| 对象 | `honeypot_migrate`（迁移） | `honeypot_app_rw`（读写） | `honeypot_app_ro`（只读控制台） | `honeypot_backup`（备份/测试准备） |
| --- | --- | --- | --- | --- |
| `sessions` / `attack_log` / `attacker_profile` / `attacker_intent` / `rule_hits` / `alerts` | S I U D + DDL | S I U D | S | S |
| `detection_rules` | S I U D + DDL | S I U（不可删除） | S | S |
| `fake_users` | S I U D + DDL | S | **S（列级，不含 `password_hash`）** | S |
| `fake_orders` / `fake_config` | S I U D + DDL | S | S | S |
| `audit_log` | S I U D + DDL | **仅 S、I** | S | S |
| 四个视图 `v_*` | S + CREATE VIEW/SHOW VIEW | S | S | S |
| 全局权限 | 无（无 SUPER/FILE/GRANT OPTION） | 无 | 无 | `LOCK TABLES`（库级） |
| 写范围 | 全部（含 DDL） | 业务表；`audit_log` 仅插入；无 DDL | 无 | 无 |

## 3. 运行库授权快照（收口前，2026-11-25）

> 本节是**执行 `apply_table_grants.sh` 之前**的库级授权快照，用于证明收口前的差距；
> 收口后的实际授权与越权探针见 §5。

查询方式：以 `root`（容器内管理员，仅用于运维取证）连接 `honeypot_dev` 执行
`SHOW GRANTS FOR '<账号>'@'127.0.0.1'`；`172.28.0.%` 账号逐项比对结果见本节末尾。

### SHOW GRANTS FOR 'honeypot_migrate'@'127.0.0.1'
```sql
GRANT USAGE ON *.* TO `honeypot_migrate`@`127.0.0.1`;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, REFERENCES, INDEX, ALTER, CREATE VIEW, SHOW VIEW ON `honeypot_demo`.* TO `honeypot_migrate`@`127.0.0.1`;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, REFERENCES, INDEX, ALTER, CREATE VIEW, SHOW VIEW ON `honeypot_dev`.* TO `honeypot_migrate`@`127.0.0.1`;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, REFERENCES, INDEX, ALTER, CREATE VIEW, SHOW VIEW ON `honeypot_test`.* TO `honeypot_migrate`@`127.0.0.1`;
```

### SHOW GRANTS FOR 'honeypot_app_rw'@'127.0.0.1'
```sql
GRANT USAGE ON *.* TO `honeypot_app_rw`@`127.0.0.1`;
GRANT SELECT, INSERT, UPDATE, DELETE ON `honeypot_demo`.* TO `honeypot_app_rw`@`127.0.0.1`;
GRANT SELECT, INSERT, UPDATE, DELETE ON `honeypot_dev`.* TO `honeypot_app_rw`@`127.0.0.1`;
```

### SHOW GRANTS FOR 'honeypot_app_ro'@'127.0.0.1'
```sql
GRANT USAGE ON *.* TO `honeypot_app_ro`@`127.0.0.1`;
GRANT SELECT ON `honeypot_demo`.* TO `honeypot_app_ro`@`127.0.0.1`;
GRANT SELECT ON `honeypot_dev`.* TO `honeypot_app_ro`@`127.0.0.1`;
```

### SHOW GRANTS FOR 'honeypot_backup'@'127.0.0.1'
```sql
GRANT USAGE ON *.* TO `honeypot_backup`@`127.0.0.1`;
GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON `honeypot_demo`.* TO `honeypot_backup`@`127.0.0.1`;
GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON `honeypot_dev`.* TO `honeypot_backup`@`127.0.0.1`;
```

### mysql.user 中的账号（四类 × 两个来源主机）
```
honeypot_app_ro@127.0.0.1
honeypot_app_ro@172.28.0.%
honeypot_app_rw@127.0.0.1
honeypot_app_rw@172.28.0.%
honeypot_backup@127.0.0.1
honeypot_backup@172.28.0.%
honeypot_migrate@127.0.0.1
honeypot_migrate@172.28.0.%
```

### 测试库连接（TEST_DATABASE_URL，密码已隐去）
```
连接账号：honeypot_migrate@127.0.0.1:3306，库 honeypot_test
SELECT CURRENT_USER(), DATABASE(), information_schema 表数 -> honeypot_migrate@172.28.0.% | honeypot_test | 16
```

两个来源主机的权限一致性比对（脚本输出）：

```text
honeypot_migrate: 127.0.0.1 与 172.28.0.% 权限逐项等价 -> True（各 4 条）
honeypot_app_rw: 127.0.0.1 与 172.28.0.% 权限逐项等价 -> True（各 3 条）
honeypot_app_ro: 127.0.0.1 与 172.28.0.% 权限逐项等价 -> True（各 3 条）
honeypot_backup: 127.0.0.1 与 172.28.0.% 权限逐项等价 -> True（各 3 条）
```

**实际矩阵归纳**（依据上面的 `SHOW GRANTS`）：

| 对象/范围 | `honeypot_migrate` | `honeypot_app_rw` | `honeypot_app_ro` | `honeypot_backup` |
| --- | --- | --- | --- | --- |
| `honeypot_dev.*` | S I U D + CREATE/DROP/REFERENCES/INDEX/ALTER/CREATE VIEW/SHOW VIEW | S I U D | S | S + LOCK TABLES + SHOW VIEW + EVENT + TRIGGER |
| `honeypot_demo.*` | 同上 | 同上 | 同上 | 同上 |
| `honeypot_test.*` | 同上（测试库专用授权） | — | — | — |
| 表级单独授权 | 无 | 无 | 无 | 无 |
| 全局权限 | `USAGE`（即无全局权限） | `USAGE` | `USAGE` | `USAGE` |

> 生效主机：`SHOW GRANTS` 对 `127.0.0.1` 与 `172.28.0.%` 两个账号逐项一致（脚本已比对，
> 见 §3）；本机进程经 Docker 端口映射连接时 MySQL 观察到来源是 `172.28.0.1`，实际命中的是
> `172.28.0.%` 账号。

## 4. 只读账号实测：SELECT 成功、INSERT 被拒（1142）

以只读控制台账号 `honeypot_app_ro` 连接 `honeypot_dev`（口令取自 `.env`
`READONLY_DATABASE_URL`，不落文档）执行一条读查询、一条写语句：

```bash
# 实际执行脚本的等价命令（完整脚本见本节末尾；口令来自 .env，未打印）
/tmp/dbh-venv/bin/python - <<'EOF'
# 读取 .env 的 READONLY_DATABASE_URL → asyncmy.connect(...) → 依次执行：
#   SELECT COUNT(*) FROM v_session_risk_summary
#   SELECT COUNT(*) FROM v_attacker_profile_summary
#   INSERT INTO audit_log (account_name, operation) VALUES ('honeypot_app_ro', 'probe')
#   SELECT COUNT(password_hash) FROM fake_users      # 仅取计数，不读取哈希内容
EOF
```

真实输出：

```text
[连接] honeypot_app_ro@127.0.0.1:3306/honeypot_dev  （只读控制台账号，密码来自 .env READONLY_DATABASE_URL，已隐去）
[SELECT 1] SELECT COUNT(*) FROM v_session_risk_summary -> 214
[SELECT 2] SELECT COUNT(*) FROM v_attacker_profile_summary -> 14
[INSERT] 被拒绝：error_code=1142, message=INSERT command denied to user 'honeypot_app_ro'@'172.28.0.1' for table 'audit_log'
[SELECT fake_users.password_hash] 成功，行数 = 30 （说明当前为库级 SELECT，列级最小权限未生效）
```

结论：

- **只读账号可以查询视图**（`v_session_risk_summary` 214 行、`v_attacker_profile_summary`
  14 行），满足控制台只读需求；
- **写语句被 MySQL 权限层拒绝**：`error_code=1142`
  （`INSERT command denied to user 'honeypot_app_ro'@'172.28.0.1' for table 'audit_log'`），
  应用代码没有机会绕过，证明“只读”由数据库强制而非应用自律（FR-068）；
- 错误中的主机 `172.28.0.1` 是 Docker 端口映射的 NAT 来源，说明命中的是
  `honeypot_app_ro@172.28.0.%` 账号（与 `127.0.0.1` 账号权限一致）。

## 5. 表级最小权限收口（2026-11-25 已执行）

`db/grants/apply_table_grants.sh` 已于 2026-11-25 在运行库执行；执行前本节记录的三处差距
（`app_rw` 可 DELETE `detection_rules`、可 UPDATE/DELETE `audit_log`、`app_ro` 可读
`password_hash`）均已收口。所有输出为真实终端结果（root 仅用于取证）。

### 5.1 执行命令

```bash
bash modules/m1-transaction-integration/db/grants/apply_table_grants.sh honeypot_dev
# 输出：[grants] honeypot_dev 的表级最小权限已收紧（退出码 0）
```

`honeypot_demo` 当前**没有任何表**（`information_schema.tables` 中 0 行，演示数据实际写入
`honeypot_dev`），脚本在该库执行会在 `GRANT … ON honeypot_demo.sessions` 处报 1146 并中止；
属预期现状，不影响运行库权限。`honeypot_test` 由测试夹具按库级权限临时建表，不参与收口。

### 5.2 收口后的授权（`SHOW GRANTS` 实测）

```text
GRANT SELECT, INSERT ON `honeypot_dev`.`audit_log` TO `honeypot_app_rw`@`127.0.0.1`
GRANT SELECT, INSERT, UPDATE ON `honeypot_dev`.`detection_rules` TO `honeypot_app_rw`@`127.0.0.1`
GRANT SELECT (`created_at`, `display_name`, `email`, `id`, `is_synthetic`, `phone`, `username`)
  ON `honeypot_dev`.`fake_users` TO `honeypot_app_ro`@`127.0.0.1`
```

- `honeypot_dev.*` 的库级宽授权已不存在；`app_rw` 对 `detection_rules` 无 `DELETE`，
  对 `audit_log` 仅 `S/I`（审计仅追加）；`app_ro` 对 `fake_users` 为列级授权，不含
  `password_hash`。
- 越权探针（真实执行）：

```text
$ mysql -uhoneypot_app_rw … -e "DELETE FROM detection_rules WHERE rule_id=-1"
ERROR 1142 (42000): DELETE command denied to user 'honeypot_app_rw'@'127.0.0.1' for table 'detection_rules'

$ mysql -uhoneypot_app_rw … -e "UPDATE audit_log SET result='x' WHERE audit_id=-1"
ERROR 1142 (42000): UPDATE command denied to user 'honeypot_app_rw'@'127.0.0.1' for table 'audit_log'

$ mysql -uhoneypot_app_ro … -e "SELECT COUNT(password_hash) FROM fake_users"
ERROR 1143 (42000): SELECT command denied to user 'honeypot_app_ro'@'127.0.0.1' for column 'password_hash' in table 'fake_users'
```

### 5.3 收口后接口回归

权限收紧后立即重跑控制台只读接口，全部 200（说明最小权限未误伤应用路径）：

```text
200 /api/health          200 /api/overview?range=all
200 /api/attackers       200 /api/alerts
200 /api/rules           200 /api/trend?days=7
200 /api/alerts/summary  200 /api/attackers/summary
```

## 6. 复现

```bash
# 1) 账号清单（8 个 = 四类 × 两主机）
/tmp/dbh-venv/bin/python - <<'EOF'  # 见 §3 查询方式
EOF

# 2) 逐账号 SHOW GRANTS（root 仅用于取证）
SHOW GRANTS FOR 'honeypot_migrate'@'127.0.0.1';
SHOW GRANTS FOR 'honeypot_app_rw'@'127.0.0.1';
SHOW GRANTS FOR 'honeypot_app_ro'@'127.0.0.1';
SHOW GRANTS FOR 'honeypot_backup'@'127.0.0.1';

# 3) 只读探针（§4 完整脚本）
#    SELECT 视图 ×2 → 成功；INSERT audit_log → 1142
```
