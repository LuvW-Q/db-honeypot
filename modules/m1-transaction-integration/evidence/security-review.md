# M1 安全复核（T077）

- **范围**：M1 事务写入、迁移、账号权限、`/api/*` 接口、控制台只读路径与演示脚本。
- **日期**：2026-11-25｜**环境**：仓库根 `db-honeypot`，MySQL 8.0.46 容器 `dbhoneypot-mysql`，
  API `http://127.0.0.1:8000`（构建产物同源托管）。
- **结论**：**通过**。未发现明文凭据、SQL 注入路径、越权写入口或主动反制承诺；
  遗留项仅为课程环境的“TEST-ONLY 口令写入 `.env`”，已在 §7 明确边界。

---

## 1. 凭据与配置

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 仓库是否提交真实凭据 | 否。`.env` 未入库（`.gitignore`），模板 [`.env.example`](../../.env.example) 全为 `TestOnly-*` 占位 | `.env.example` 头注释、`.gitignore` |
| 配置来源 | 全部经 `shared/config.py` 从环境变量读取；代码内无硬编码口令 | `shared/config.py` 的 `Settings` 字段 |
| 日志是否泄漏连接串 | 日志只打印 host/port/账号名，不打印 URL 密码 | `shared/logging.py`、`shared/db/session.py` |
| 前端是否含密钥 | `dist` 为纯静态产物，`fetch` 只访问同源 `/api/*`；无 token/密钥 | `frontend/src/api/index.ts`、`browser.json` 的 `external_requests=[]` |
| 截图/证据是否含明文口令 | 控制台只展示 `credential_test_id` 与脱敏用户名；`masking.py` 负责掩码 | `shared/utils/masking.py`、`tests/unit/test_masking.py` |

## 2. SQL 注入面

- **业务查询**：全部使用 SQLAlchemy `text()` + 绑定参数（`WHERE source_ip = :ip`、
  `LIMIT :limit OFFSET :offset`），用户输入只作为参数值，不拼接进 SQL 文本。
- **标识符插值**：仅有的 f-string 插值用于**白名单常量**（表名、列名、`IN (...)`
  占位符数量、`ORDER BY` 白名单分支），不接收任意用户字符串；`sort`/`order` 参数在
  repository 内做白名单归一化。
- **规则/告警写入**：`rule_hits`、`alerts` 的写入使用 ORM/绑定参数；`dedup_key` 由
  `rule_code:source_ip:日期` 结构化拼接，再作为**参数**写入。
- **AI 辅助（默认关闭）**：只执行 `TEMPLATES` 白名单只读查询，不执行模型生成的 SQL；
  输出标记为“辅助解释”，不参与命中/评分/判定。
- **验证**：`pytest modules/m1-transaction-integration/tests` 覆盖 422/404 与非法参数；
  `grep` 复核见 §8。

## 3. 账号权限（数据库强制，非应用自律）

- 四类账号分离：`honeypot_migrate`（DDL）、`honeypot_app_rw`（业务写）、
  `honeypot_app_ro`（控制台只读）、`honeypot_backup`（导出）。
- 2026-11-25 已执行
  [`db/grants/apply_table_grants.sh`](../db/grants/apply_table_grants.sh) `honeypot_dev`，
  收口为表级/列级最小权限：

| 探针（真实执行） | 结果 |
| --- | --- |
| `app_rw`：`DELETE FROM detection_rules` | `ERROR 1142 … DELETE command denied` |
| `app_rw`：`UPDATE audit_log` | `ERROR 1142 … UPDATE command denied` |
| `app_ro`：`SELECT COUNT(password_hash) FROM fake_users` | `ERROR 1143 … column access denied` |
| `app_ro`：`INSERT INTO audit_log` | `ERROR 1142 … INSERT command denied` |

完整 `SHOW GRANTS` 矩阵与收口前后对比见 [`grants.md`](grants.md) §3、§5。
`honeypot_demo` 当前无表（演示数据写入 `honeypot_dev`），脚本在该库会因 1146 中止，
属已知现状，不影响运行库。

## 4. 控制台与接口的写边界

- 控制台侧**唯一写操作**是 `PATCH /api/alerts/{id}` 标记已读；其余接口均为只读。
- 规则变更 `PUT /api/rules/{code}` 生成新版本（不覆盖历史），且仅在 API 侧显式调用；
  前端“规则推送”等控件为禁用态（“演示未开放”），见 §5。
- 事务写入只发生在 M1 `IngestService`（诱饵事件/样本导入/模拟器）与演示重置 CLI；
  控制台请求走 `app_ro` 会话，数据库层无法写。
- 异常统一结构，不返回堆栈/SQL 文本；`/api/health` 不暴露连接串。

## 5. 主动反制与演示承诺（安全红线）

- 前端禁用态控件均带 `title` 与“演示未开放…”说明，不会产生假成功：
  取证报告导出（JSON/CSV）、遥测 CSV 导出、DMZ 隔离、证据链同步、SQL 回放、规则推送。
- 系统不具备也不承诺：主动反制、漏洞利用、真实隔离联动、SQL 回放执行；
  诱饵只读、写操作在协议层返回 `1142`（`evidence/session-events.md`）。
- 页面文案不使用“已阻断攻击/已反制”等误导性表述；只陈述捕获、命中与只读分析。

## 6. 审计与可追溯

- `audit_log` 仅追加：`app_rw` 仅 `SELECT, INSERT`（§3 探针实测 UPDATE 被拒）。
- 写路径（事件入库、重置、规则版本变更）都写审计记录（操作者、操作、结果、时间），
  `AuditRepository` 为唯一写入口。
- 时间统一 UTC 存储、界面 UTC+8 展示；证据以 `session_id`/`dst_ip`/`dedup_key` 锚定。

## 7. 已知边界与遗留（课程环境）

1. `.env` 中的密码是 `TEST-ONLY` 占位，仅用于隔离实验环境；生产部署必须替换并交由
   密钥管理，不得复用。
2. 诱饵监听默认仅 `127.0.0.1:3307`；若改为非回环地址，`server.py` 会拒绝启动。
3. `honeypot_demo` 库为空、未收口；本仓库演示统一使用 `honeypot_dev`。
4. `test-plan.md` 已登记 `explain_diff.py` 输出目录漂移等非安全类已知限制。
5. 依赖漏洞扫描（`pip-audit`/`pnpm audit`）不在本轮课程验收范围，未执行；升级前应补做。

## 8. 复核命令（可重跑）

```bash
cd /path/to/db-honeypot
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console

# 1) 测试（接口 + 事务 + 迁移 + 幂等）
/tmp/dbh-venv/bin/python -m pytest modules/m1-transaction-integration/tests -q

# 2) 静态检查
/tmp/dbh-venv/bin/python -m ruff check .

# 3) 权限探针（root 仅取证；输出应全部 denied）
docker exec -i dbhoneypot-mysql mysql -h127.0.0.1 -P3306 --protocol=TCP \
  -uhoneypot_app_rw -p"$HONEYPOT_APP_RW_PASSWORD" honeypot_dev \
  -e "DELETE FROM detection_rules WHERE rule_id=-1;"
docker exec -i dbhoneypot-mysql mysql -h127.0.0.1 -P3306 --protocol=TCP \
  -uhoneypot_app_ro -p"$HONEYPOT_APP_RO_PASSWORD" honeypot_dev \
  -e "SELECT COUNT(password_hash) FROM fake_users;"

# 4) 明文凭据/注入面检索（期望只命中 .env.example 占位与白名单标识符插值）
rg -n "TestOnly-|password\\s*=\\s*['\\\"]" --glob '!*.env*' --glob '!docs/**'
rg -n "text\\(f\\\"" modules shared --glob '*.py'
```

> 命令 4 的 f-string 命中为表名/列名/占位符白名单插值，逐条人工核对见 §2；值一律绑定参数。
