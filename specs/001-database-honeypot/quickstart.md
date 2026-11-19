# 快速开始与端到端验证（quickstart.md）

**Feature**: `001-database-honeypot` | **版本**: 1.1.0 | **日期**: 2026-11-19

**目标读者**：课程小组成员、答辩演示者、在另一台实验机上复现项目的同学。

**本文档能带你完成**：从零启动开发环境 → 用真实 MySQL 客户端连上诱饵 → 导入固定合成样本
→ 在控制台看到概览/攻击者/时间线/告警 → 完成数据库专项演示（幂等、外键、事务回滚、四视图、
EXPLAIN 对比）→ 重置并重跑，全程可重复三次。

**约定**：

- 除特别说明外，命令在仓库根目录执行；后端命令需先进入 `backend/`（`pyproject.toml` 所在目录），前端命令需先进入 `frontend/`；命令中的密钥/口令一律从 `.env` 读取，**不得**在命令行或文档中
  写真实口令。本文档出现的口令类值一律为 `TEST-ONLY-PASSWORD-PLACEHOLDER` 占位。
- 脚本与模块名是**契约名**（`app.cli.*`、`app.honeypot.server`）；若 `plan.md` 最终确定的前缀不同，
  只需替换前缀，命令参数与预期结果不变。
- 验证场景编号 `V01`–`V23` 在第 6 章给出，第 7 章把 `spec.md` 的 SC-001 至 SC-015 映射到
  这些场景，答辩时直接按编号演示。

**端口约定**：

| 端口 | 用途 | 说明 |
| --- | --- | --- |
| `3306` | MySQL 8.4 LTS（Docker 或本机） | 持久化库，非诱饵 |
| `3307` | 诱饵 MySQL 协议服务 | 对外“假数据库”，默认只绑定 `127.0.0.1` |
| `8000` | FastAPI（`/api` + 生产前端静态文件） | 只绑定 `127.0.0.1` |
| `5173` | Vite 开发服务器（`/api` 代理到 8000） | 仅开发使用 |

---

## 1. 前置条件

| 依赖 | 最低版本 | 校验命令 | 说明 |
| --- | --- | --- | --- |
| Docker Engine | 29.x | `docker --version` | 用于一键启动 MySQL 8.4 |
| Docker Compose | v2 | `docker compose version` | `docker compose` 子命令形式 |
| Python | 3.14 | `python3.14 --version` 或 `python3 --version` | 后端、诱饵、CLI 统一运行时 |
| uv | 0.8+ | `uv --version` | 依赖与虚拟环境管理（`pyproject.toml` + `uv.lock`） |
| Node.js | 24 LTS | `node --version` | 前端构建 |
| pnpm | 12 | `pnpm --version` | 前端包管理（`pnpm-lock.yaml`） |
| MySQL CLI（可选） | 8.0 / 8.4 | `mysql --version` | 演示连接诱饵；没有则用 PyMySQL 脚本 |

**一条命令自检**：

```bash
docker --version && docker compose version && uv --version && node --version && pnpm --version
```

**预期**：全部输出版本号，无 `command not found`。

**磁盘与内存**：Docker 镜像 + 依赖约 2 GB；演示机建议 ≥ 4 GB 可用内存。

---

## 2. 降级路径（离线 / 无 Docker / 已有 MySQL 实例）

### 2.1 无 Docker：使用本机 MySQL 8.4

1. 安装 MySQL 8.4 LTS（Ubuntu/Debian 示例；macOS 用 `brew install mysql@8.4`）。
2. 创建库与账号（口令用占位符，演示时替换为本地随机值）：

```sql
CREATE DATABASE honeypot_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
-- 迁移账号：仅用于 alembic 建表/建视图，具备 DDL 权限
CREATE USER 'honeypot_migrate'@'127.0.0.1' IDENTIFIED BY 'TEST-ONLY-PASSWORD-PLACEHOLDER';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES,
      CREATE VIEW, SHOW VIEW
  ON honeypot_demo.* TO 'honeypot_migrate'@'127.0.0.1';
-- 应用读写账号：只有 DML，无 DDL（最小权限，对应 data-model 的 app_rw）
CREATE USER 'honeypot_app_rw'@'127.0.0.1' IDENTIFIED BY 'TEST-ONLY-PASSWORD-PLACEHOLDER';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.* TO 'honeypot_app_rw'@'127.0.0.1';
-- 分析只读账号：只有 SELECT（对应 data-model 的 app_ro）
CREATE USER 'honeypot_app_ro'@'127.0.0.1' IDENTIFIED BY 'TEST-ONLY-PASSWORD-PLACEHOLDER';
GRANT SELECT ON honeypot_demo.* TO 'honeypot_app_ro'@'127.0.0.1';
-- 备份账号：只读 + 锁表 + 视图元数据（对应 data-model 的 backup）
CREATE USER 'honeypot_backup'@'127.0.0.1' IDENTIFIED BY 'TEST-ONLY-PASSWORD-PLACEHOLDER';
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT ON honeypot_demo.* TO 'honeypot_backup'@'127.0.0.1';
FLUSH PRIVILEGES;
```

3. 修改 `.env`：

```dotenv
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MIGRATE_DATABASE_URL=mysql+asyncmy://honeypot_migrate:${HONEYPOT_MIGRATE_PASSWORD}@127.0.0.1:3306/honeypot_demo?charset=utf8mb4
DATABASE_URL=mysql+asyncmy://honeypot_app_rw:${HONEYPOT_APP_RW_PASSWORD}@127.0.0.1:3306/honeypot_demo?charset=utf8mb4
READONLY_DATABASE_URL=mysql+asyncmy://honeypot_app_ro:${HONEYPOT_APP_RO_PASSWORD}@127.0.0.1:3306/honeypot_demo?charset=utf8mb4
```

4. 跳过 `docker compose up`，从第 4 章步骤 3（`uv sync`）继续。

> **注意**：MySQL 8.4 默认**禁用** `mysql_native_password` 服务端插件，应用账号请用
> 默认的 `caching_sha2_password`（`asyncmy` 支持）；不要为了“省事”把账号改成
> `mysql_native_password`，8.4 上需要额外开启且已被废弃。

### 2.2 使用已有实例（课程统一提供的 MySQL）

- 只需在 `.env` 中改 `DATABASE_URL`/`READONLY_DATABASE_URL` 的主机、端口、库名；
- 要求：MySQL ≥ 8.0.16（`CHECK` 约束生效）、字符集 `utf8mb4`、支持窗口函数与 CTE；
- 不得指向任何真实业务库；库名必须独立（`honeypot_demo`），演示前可整库重建。

### 2.3 完全离线（无网络）

1. 在联网机器上执行 `uv sync` 与 `pnpm install`，把 `.venv/`、`node_modules/`（或 pnpm store）
   一并拷入离线环境；
2. 预拉取镜像 `docker pull mysql:8.4` 后 `docker save` → `docker load`；
3. 依赖锁定文件（`uv.lock`、`pnpm-lock.yaml`）必须与联网机器一致，禁止离线临时改版本。

### 2.4 若使用 pip 而非 uv（提供降级说明，不改变技术基线）

```bash
cd backend && uv export --format requirements-txt --no-hashes > ../requirements.txt   # 由 uv.lock 导出
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r ../requirements.txt
cd backend && alembic upgrade head
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`uv` 仍是基线工具；`requirements.txt` 只作为无 uv 环境的降级产物，必须由 `uv.lock` 生成。

---

## 3. 目录约定（与 `plan.md` 对应）

```text
backend/          # FastAPI 应用：app/main.py、app/api、app/services、app/honeypot、app/cli；
                  # 含 pyproject.toml、uv.lock、alembic.ini、migrations/
frontend/         # Vue 3.5 + Vite 8 + TS + Element Plus + ECharts，含 package.json、pnpm-lock.yaml
db/init/          # MySQL 容器初始化 SQL：建库与四类账号授权
scripts/          # 授权模拟器、样本导入、演示重置包装脚本
docs/             # 中文项目文档（架构、数据库设计、演示脚本、测试计划）
specs/            # 规格、计划、契约与本文档
compose.yaml      # MySQL 8.4 + backend + web 编排
Makefile          # 初始化、迁移、种子、启动、测试、重置
.env.example      # 配置模板（只含 TEST-ONLY 占位）
```

---

## 4. 首次启动（按顺序执行）

### 步骤 1：启动 MySQL 8.4

```bash
cp .env.example .env          # 首次；随后把 .env 中的占位口令替换为本地随机值
docker compose -f compose.yaml up -d mysql
docker compose -f compose.yaml ps
```

**预期**：`mysql` 服务 `STATUS` 为 `Up (healthy)`；`docker compose logs mysql` 出现
`ready for connections`。初始化脚本（`db/init/`）负责创建 `honeypot_demo` 库与
`honeypot_migrate`（DDL）、`honeypot_app_rw`（DML）、`honeypot_app_ro`（SELECT）三个账号，口令均从
`.env` 读取，不在 SQL 中硬编码。

**验证连接**：

```bash
set -a; source .env; set +a
docker compose -f compose.yaml exec -T mysql \
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT VERSION(); SHOW DATABASES;"
```

**预期**：`VERSION()` 为 `8.4.x`；`SHOW DATABASES` 含 `honeypot_demo`。

### 步骤 2：配置环境变量

```bash
grep -E '^(DATABASE_URL|READONLY_DATABASE_URL|HONEYPOT_PORT|API_PORT|WEB_DEV_PORT)' .env
```

**预期**：`DATABASE_URL` 指向 `127.0.0.1:3306/honeypot_demo`，`HONEYPOT_PORT=3307`。
`.env` 已被 `.gitignore` 忽略，**不得提交**。

### 步骤 3：安装后端依赖

```bash
cd backend && uv sync --frozen
```

**预期**：生成/复用 `.venv`，输出 `Installed N packages`；`uv run python --version` 为 3.14.x。

### 步骤 4：执行数据库迁移

```bash
cd backend && uv run alembic upgrade head
cd backend && uv run alembic current
```

（Alembic 读取 `.env` 的 `MIGRATE_DATABASE_URL`，即 `honeypot_migrate` 账号；应用运行时才使用
`DATABASE_URL`（DML）与 `READONLY_DATABASE_URL`（SELECT）。）

**预期**：`alembic current` 显示最新 revision（无 `(head)` 之外的分支）；重复执行
`upgrade head` 是幂等的（无变更）。

**核对对象已创建**：

```bash
docker compose -f compose.yaml exec -T mysql \
  mysql -uhoneypot_app_rw -p"$HONEYPOT_APP_RW_PASSWORD" honeypot_demo \
  -e "SHOW TABLES; SHOW FULL TABLES WHERE Table_type='VIEW';"
```

**预期**：表含 `sessions`、`attack_log`、`attacker_profile`、`attacker_intent`、
`detection_rules`、`rule_hits`、`alerts`、`audit_log`、`fake_users`、`fake_orders`、`fake_config`；
视图含 `v_session_risk_summary`、`v_attacker_profile_summary`、`v_daily_attack_trend`、
`v_rule_effectiveness`。

### 步骤 5：导入种子数据（规则 + 诱饵数据）

```bash
cd backend && uv run python -m app.cli.seed --all
```

**预期**（stdout JSON）：`rules=5..8`（至少 R01–R05）、`fake_users=30`（20–50 之间）、
`fake_orders=120`、`fake_config=5`；重复执行不产生重复规则（`rule_code+rule_version` 唯一）。

### 步骤 6：启动 FastAPI（端口 8000）

```bash
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**预期**：日志出现 `Uvicorn running on http://127.0.0.1:8000`；建议在另一个终端执行
`curl -s http://127.0.0.1:8000/api/health | jq`，返回 `"status": "ok"`（此时诱饵未启动，
`honeypot.status` 为 `down` 属正常）。

### 步骤 7：启动诱饵服务（端口 3307）

```bash
cd backend && uv run python -m app.honeypot.server
```

**预期**：日志出现 `honeypot listening on 127.0.0.1:3307`；再次 `curl /api/health` 时
`honeypot.status` 变为 `ok`。若端口被占用，进程以非 0 退出并提示端口（见第 8 章）。

### 步骤 8：启动前端

开发模式（推荐联调）：

```bash
cd frontend && pnpm install --frozen-lockfile && pnpm dev
```

**预期**：Vite 输出 `Local: http://127.0.0.1:5173/`；浏览器打开后概览页能请求到
`/api/overview`（`/api` 已由 Vite 代理到 8000）。

生产模式（答辩推荐，少一个进程）：

```bash
cd frontend && pnpm build          # 产物 frontend/dist
cd backend && uv run python -m app.cli.serve_web --dist ../frontend/dist   # 或由 FastAPI 自动挂载 WEB_DIST_DIR
```

**预期**：`http://127.0.0.1:8000/` 直接返回控制台页面，`/api/*` 仍由同一进程提供。

---

## 5. 启动完成检查表

| 检查 | 命令 | 期望 |
| --- | --- | --- |
| 健康检查 | `curl -s http://127.0.0.1:8000/api/health \| jq` | `status=ok`、`database.status=ok`、`honeypot.status=ok` |
| 端口监听 | `ss -ltnp \| grep -E ':(3306\|3307\|8000\|5173) '` | 四个端口各一行（生产模式无 5173） |
| 规则种子 | `curl -s http://127.0.0.1:8000/api/rules \| jq '.total'` | `>= 5` |
| 概览空态 | `curl -s http://127.0.0.1:8000/api/overview \| jq` | 四个数字为 0，HTTP 200 |
| 视图可查 | `V19` 的四条 SQL | 均返回结果集，无报错 |

---

## 6. 端到端验证场景

> 统一准备：`set -a; source .env; set +a`；`API=http://127.0.0.1:8000`。
> 数据库命令统一用：
> `docker compose -f compose.yaml exec -T mysql mysql -uhoneypot_app_rw -p"$HONEYPOT_APP_RW_PASSWORD" honeypot_demo -e "<SQL>"`
> （本机 MySQL 降级时改为 `mysql -h127.0.0.1 -uhoneypot_app_rw -p"$HONEYPOT_APP_RW_PASSWORD" honeypot_demo -e "<SQL>"`）。

### V01 健康检查

```bash
curl -s "$API/api/health" | jq
```

**预期**：`status="ok"`、`database.status="ok"`、`honeypot.listen="127.0.0.1:3307"`、
`generated_at` 以 `Z` 结尾；响应头含 `X-Request-ID`。

### V02 连接诱饵并完成元数据查询（MySQL CLI，重复 3 次）

```bash
for i in 1 2 3; do
  mysql -h 127.0.0.1 -P 3307 -u demo_app -p"$HONEYPOT_ACCOUNT_1_PASSWORD" \
        --default-auth=mysql_native_password --ssl-mode=DISABLED \
        --default-character-set=utf8mb4 \
        -e "SHOW DATABASES; USE honeypot_shop; SHOW TABLES; DESCRIBE users;
            SELECT id, username, email FROM users LIMIT 5;"
  echo "round $i exit=$?"
done
```

**预期**：三轮全部成功；`SHOW DATABASES` 返回 `honeypot_shop`、`honeypot_archive`；
`SHOW TABLES` 返回 `users/orders/config`；`DESCRIBE users` 返回 7 列；`SELECT` 返回固定
5 行伪造数据（邮箱形如 `*@example.invalid`）。

**PyMySQL 等价写法（无 MySQL CLI 时使用）**：

```python
import pymysql
conn = pymysql.connect(host="127.0.0.1", port=3307, user="demo_app",
                       password="TEST-ONLY-PASSWORD-PLACEHOLDER",
                       charset="utf8mb4", connect_timeout=3)
with conn.cursor() as cur:
    cur.execute("SHOW TABLES"); print(cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM users"); print(cur.fetchone())
conn.close()
```

**核对事件**（三条查询语句对应三条 `query` 事件，`status=success`）：

```sql
SELECT s.session_id, s.request_count,
       SUM(l.event_type='connect') AS connects,
       SUM(l.event_type='auth')    AS auths,
       SUM(l.event_type='query')   AS queries,
       SUM(l.event_type='disconnect') AS disconnects
FROM sessions s JOIN attack_log l ON l.session_id = s.session_id
GROUP BY s.session_id, s.request_count ORDER BY s.started_at DESC LIMIT 3;
```

**预期**：3 行；每行 `request_count = connects + auths + queries + disconnects`。

### V03 未知账号认证失败

```bash
mysql -h 127.0.0.1 -P 3307 -u no_such_user -p'TEST-ONLY-PASSWORD-PLACEHOLDER' \
      --default-auth=mysql_native_password --ssl-mode=DISABLED \
      -e "SELECT 1;" ; echo "exit=$?"
```

**预期**：客户端报 `ERROR 1045 (28000): Access denied for user 'no_such_user'@'127.0.0.1'`，
`exit` 非 0；后台仍产生 `connect(success)` + `auth(failure, 1045)` + `disconnect` 事件：

```sql
SELECT status, username, credential_test_id, COUNT(*) AS n
FROM attack_log WHERE event_type='auth' AND username='no_such_user'
GROUP BY status, username, credential_test_id;
```

**预期**：`status=failure`（客户端侧错误码 1045），`credential_test_id` 以 `TEST-ONLY-UNKNOWN` 开头；
表中**不存在**任何口令字段。

### V04 踩点查询触发 R03

```bash
cd backend && uv run python -m app.cli.import_samples --sample S03 --repeat 1
```

**预期**（stdout JSON）：`samples[0].rule_hits=["R03"]`；随后：

```sql
SELECT h.rule_code, h.intent_type, h.risk_weight, h.rule_version, h.triggered_at, h.evidence_summary
FROM rule_hits h JOIN attack_log l ON l.event_id = h.event_id
WHERE l.source_ip='198.51.100.23' ORDER BY h.hit_id DESC LIMIT 3;
```

**预期**：出现 `R03 / recon / 15 / 1`（`risk_weight=15`，`rule_version=1`），
`evidence_summary` 说明触发语句类型（如“语句类型 SHOW，对象 TABLE”）。

### V05 写操作被拒绝（R05 与安全边界）

分别执行以下语句（同一次连接内，逐条执行并确认连接仍可用）：

```sql
UPDATE orders SET status='cancelled' WHERE id=1;
DELETE FROM orders WHERE id=1;
DROP TABLE orders;
TRUNCATE TABLE orders;
INSERT INTO users (username) VALUES ('demo_user_x');
```

**预期**：每条返回 `ERROR 1142 ... command denied`；连接不中断，随后 `SELECT COUNT(*) FROM orders;`
仍返回 `120`（诱饵数据未被修改）。

**核对**：

```sql
SELECT status,
       SUM(normalized_sql LIKE 'update%')  AS n_update,
       SUM(normalized_sql LIKE 'delete%')  AS n_delete,
       SUM(normalized_sql LIKE 'drop%')    AS n_drop,
       SUM(normalized_sql LIKE 'truncate%')AS n_truncate,
       SUM(normalized_sql LIKE 'insert%')  AS n_insert,
       COUNT(*)                            AS n_total
FROM attack_log
WHERE event_type='query' AND status='denied' AND source_ip LIKE '127.0.0.1%';
```

**预期**：`n_total >= 5`，且 `n_update/n_delete/n_drop/n_truncate/n_insert` 各至少 1；
`fake_orders` 行数不变：`SELECT COUNT(*) FROM fake_orders;` 仍为原值。

### V06 会话时间线可还原

从 V02 的查询结果取一个 `session_id`，然后：

```bash
curl -s "$API/api/sessions/<session_id>/timeline" | jq \
  '{session: .session.session_id, status: .session.session_status,
    events: [.events[] | {event_id, event_type, status, event_time, sql: .sql_statement}]}'
```

**预期**：`event_type` 顺序为 `connect → auth → query… → disconnect`；`event_time` 升序；
同一时间戳的多条事件按 `event_id` 升序；响应中不含任何明文口令。

**未知会话**：`curl -s -o /dev/null -w '%{http_code}' "$API/api/sessions/00000000-0000-4000-8000-0000000000ff/timeline"`
→ `404`，且响应体 `code=SESSION_NOT_FOUND`。

### V07 拖库样本触发 R04 与告警

```bash
cd backend && uv run python -m app.cli.import_samples --sample S04
```

**预期**：输出 `rule_hits=["R04"]`、`alerts` 非空；`alerts` 中 `alert_type=data_dump`、
`severity=high`（R04 固定映射），`latest_hit_id` 可定位到 `rule_hits.hit_id`。

### V08 破坏性样本触发 R05 与告警

```bash
cd backend && uv run python -m app.cli.import_samples --sample S05
```

**预期**：`rule_hits=["R05"]`，`alert_type=destructive`；会话 `max_risk_score` 上升；
`alert.dedup_key` 非空（重复导入不新增告警）。

### V09 扫描与爆破样本触发 R01/R02

```bash
cd backend && uv run python -m app.cli.import_samples --sample S06 --sample S07
```

**预期**：S06 → `R01`（`scanning`）；S07 → `R02`（`bruteforce`）且生成 `bruteforce` 告警。
至此五条规则全部有固定样本命中（SC-004）。

一次性覆盖全部规则（在 `backend/` 下执行）：`cd backend && uv run python -m app.cli.import_samples --set demo_basic`。

### V10 概览数字与视图一致

```bash
curl -s "$API/api/overview" | jq
```

```sql
SELECT COUNT(*) AS sessions, SUM(query_count) AS queries, SUM(alert_count) AS alerts
FROM v_session_risk_summary;
SELECT COUNT(*) AS high_risk_attackers FROM v_attacker_profile_summary
WHERE risk_level IN ('high','critical');
```

**预期**：接口的 `sessions/queries/alerts/high_risk_attackers` 与两条 SQL 的结果**逐项相等**
（视图列名以 `data-model.md` 为准）。

### V11 攻击者列表分页与排序稳定

```bash
curl -s "$API/api/attackers?page=1&page_size=2&sort=risk_score&order=desc" | jq
curl -s "$API/api/attackers?page=2&page_size=2&sort=risk_score&order=desc" \
  | jq '[.items[].source_ip]'
```

**预期**：`page/page_size/total/total_pages` 正确；`198.51.100.23` 出现在前页且
`risk_level` 为 `high`/`critical`；两页 `source_ip` **无重复**；重复执行同一请求结果一致。

**异常参数**：`page_size=500` → `422 VALIDATION_ERROR`；`sort=password` → `422 SORT_FIELD_INVALID`。

### V12 攻击者详情与意图证据

```bash
curl -s "$API/api/attackers/198.51.100.23" | jq \
  '{stats: .attacker, intents: [.intents[] | {intent_type, intent_score, evidence_count}],
    sessions: [.sessions[] | {session_id, event_count, risk_score, hit_rule_codes}],
    hits: [.recent_rule_hits[] | {rule_code, risk_weight, rule_version, evidence_summary}]}'
```

**预期**：`intents` 覆盖已命中的意图；`recent_rule_hits` 每条都带 `rule_code`、`risk_weight`
与中文 `evidence_summary`（禁止只给标签）；`total_connections/total_auth_attempts/total_queries`
与 `sessions` 汇总一致；`risk_score` 与 `calculated_risk_score` 相等。

### V13 告警筛选与标记已读

```bash
curl -s "$API/api/alerts?severity=high&is_read=false&page=1&page_size=20" | jq '.total'
ALERT_ID=$(curl -s "$API/api/alerts?is_read=false&page=1&page_size=1" | jq -r '.items[0].alert_id')
curl -s -X PATCH "$API/api/alerts/$ALERT_ID" \
     -H 'Content-Type: application/json' -d '{"is_read": true}' | jq '{alert_id, is_read, read_at}'
```

**预期**：PATCH 返回 `200`，`is_read=true`、`read_at` 非空；再次发送同样请求仍 `200`，
`read_at` **不变**（幂等）；`is_read=false` 可撤回（`read_at=null`）。
未知告警 `PATCH /api/alerts/999999` → `404 ALERT_NOT_FOUND`；
`-d '{"is_read": "true"}'` → `422 VALIDATION_ERROR`。

### V14 每日趋势（含前一日变化）

```bash
curl -s "$API/api/trend?days=14" | jq '{days, n: (.items|length), first: .items[0], last: .items[-1]}'
```

**预期**：`n=14`；`items` 按 `stat_date` 升序且日期连续；首行 `*_delta=null`；
`alerts_change_ratio` 在前一日为 0 时为 `null`；`days=0` → `422 VALIDATION_ERROR`。

### V15 规则配置与版本自增

```bash
curl -s "$API/api/rules" | jq '.items[] | {rule_code, rule_version, enabled, risk_weight}'
curl -s -X PATCH "$API/api/rules/R01" -H 'Content-Type: application/json' \
  -d '{"risk_weight": 12, "expected_version": 1, "change_reason": "演示：调整扫描权重"}' \
  | jq '{rule_code, rule_version, previous_version, risk_weight, enabled}'
curl -s "$API/api/rules?include_history=true" | jq '[.items[] | select(.rule_code=="R01") | {rule_version, enabled, risk_weight}]'
```

**预期**：PATCH 后 `rule_version` 比原值 +1、`previous_version` 为旧值；历史版本行保留且
`enabled=false`；旧 `rule_hits` 的 `rule_version`/`risk_weight` **不变**：

```sql
SELECT rule_version, risk_weight, COUNT(*) FROM rule_hits
WHERE rule_code='R01' GROUP BY rule_version, risk_weight;
```

再次用 `expected_version=1` 提交 → `409 RULE_VERSION_CONFLICT`。
空体 `-d '{}'` → `422 VALIDATION_ERROR`。

### V16 幂等：重复导入不重复计数

```bash
# 记录基线
BEFORE=$(curl -s "$API/api/overview" | jq -c '{sessions, queries, alerts}')
cd backend && uv run python -m app.cli.import_samples --sample S03 --repeat 10
AFTER=$(curl -s "$API/api/overview" | jq -c '{sessions, queries, alerts}')
echo "before=$BEFORE"; echo "after=$AFTER"; test "$BEFORE" = "$AFTER" && echo "IDEMPOTENT-OK"
```

```sql
SELECT event_uuid, COUNT(*) FROM attack_log GROUP BY event_uuid HAVING COUNT(*) > 1;  -- 期望 0 行
```

**预期**：`IDEMPOTENT-OK`；重复导入输出中 `deduped.events=9`、`imported.events=1`；
`rule_hits` 与 `alerts` 计数不因重复导入增加（SC-011）。

### V17 外键拦截

```sql
-- 期望失败：ERROR 1452 (23000) Cannot add or update a child row
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000ff', 'connect',
        '203.0.113.9', UTC_TIMESTAMP(), 'success');
```

**预期**：报错 `1452`，`attack_log` 行数不变；该错误说明“日志不能引用不存在的会话”
（FR-022/边界情况）。

### V18 事务回滚（数据库层与应用层）

**数据库层（手工事务）**：

```sql
START TRANSACTION;
INSERT INTO sessions (session_id, source_ip, target_service, started_at, session_status,
                      request_count, max_risk_score)
VALUES ('00000000-0000-4000-8000-00000000aa01', '203.0.113.9', 'mysql-honeypot', UTC_TIMESTAMP(), 'active', 0, 0);
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-00000000aa01', 'connect',
        '203.0.113.9', UTC_TIMESTAMP(), 'success');
-- 故意触发外键失败：引用不存在会话
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-000000000003', '00000000-0000-4000-8000-0000000000ff', 'connect',
        '203.0.113.9', UTC_TIMESTAMP(), 'success');
ROLLBACK;
SELECT COUNT(*) FROM sessions WHERE session_id='00000000-0000-4000-8000-00000000aa01';  -- 期望 0
```

**预期**：第三条 `INSERT` 报 `1452`；`ROLLBACK` 后会话与事件均不存在（SC-012 的等价演示）。

**应用层（受控失败注入，推荐答辩用）**：

```bash
cd backend && uv run python -m app.cli.verify_transaction --inject-failure profile_write
```

**预期**：脚本输出五类表（`sessions/attack_log/rule_hits/alerts/attacker_profile`）在事务前后
**计数完全一致**，退出码 `0`；运行日志中可见失败阶段与 `event_uuid`；随后同一事件重试成功
（脚本会再跑一次并输出 `retry_ok=true`）。

### V19 四个核心视图可查（SC-010）

```sql
-- ① 会话风险汇总（CTE 分表聚合 + 多表 LEFT JOIN + GROUP BY）
SELECT session_id, source_ip, event_count, query_count, hit_count, hit_rule_codes,
       calculated_risk_score, risk_level, stored_max_risk_score, alert_count
FROM v_session_risk_summary ORDER BY calculated_risk_score DESC, session_id LIMIT 5;

-- ② 攻击者画像汇总（JOIN 聚合 + ROW_NUMBER 取主要意图）
SELECT source_ip, calculated_risk_score, risk_level, primary_intent_type,
       primary_intent_score, session_count, total_queries
FROM v_attacker_profile_summary ORDER BY calculated_risk_score DESC, source_ip LIMIT 5;

-- ③ 每日攻击趋势（CTE + LAG 求变化）
SELECT stat_date, event_count, session_count, alert_count,
       prev_event_count, event_count_delta, event_change_pct, busy_day_rank
FROM v_daily_attack_trend ORDER BY stat_date DESC LIMIT 7;

-- ④ 规则效果统计（COUNT DISTINCT + RANK 排名）
SELECT rule_code, rule_name, hit_count, affected_session_count, affected_attacker_count,
       alert_count, current_version, is_enabled, hit_rank
FROM v_rule_effectiveness ORDER BY hit_rank;
```

**预期**：四条查询均成功；① 的 `calculated_risk_score` 等于该会话 `rule_hits` 按 `rule_code`
去重取 `MAX(risk_weight)` 后求和（封顶 100），且与 `stored_max_risk_score` 一致；② 的
`primary_intent_type` 与 `/api/attackers` 的 `main_intent.intent_type` 一致；③ 的行数与
`/api/trend` 的“有事件日期”行数一致（接口会额外补空白日）；④ 的 `hit_rank` 从 1 起按
命中数排名（并列按 `rule_code` 稳定）。

### V20 EXPLAIN 索引对比（SC-013）

先准备有规模的演示数据（几千至几万条，避免空表上索引无效）：

```bash
cd backend && uv run python -m app.cli.gen_demo_data --sessions 2000 --events 20000
```

**目标查询 A（按会话重建时间线）**：

```sql
EXPLAIN SELECT event_id, event_type, event_time
FROM attack_log WHERE session_id='<任一真实 session_id>'
ORDER BY event_time, event_id;
```

**索引建立前**（演示时手动删索引，记录后再恢复）：

```sql
ALTER TABLE attack_log DROP INDEX idx_log_session_time;
EXPLAIN SELECT event_id, event_type, event_time FROM attack_log
WHERE session_id='<session_id>' ORDER BY event_time, event_id;
ALTER TABLE attack_log ADD INDEX idx_log_session_time (session_id, event_time);
EXPLAIN SELECT event_id, event_type, event_time FROM attack_log
WHERE session_id='<session_id>' ORDER BY event_time, event_id;
```

**预期**：两次 `EXPLAIN` 的 `type` 由 `ALL` 变为 `ref`，`key` 由 `NULL` 变为
`idx_log_session_time`，`rows` 显著下降；把两组结果（`type/key/rows` 与实测耗时）记录到
测试材料（FR-035）。

**目标查询 B（近期高等级告警）**：

```sql
EXPLAIN SELECT alert_id, severity, created_at FROM alerts
WHERE severity='critical' ORDER BY created_at DESC LIMIT 20;
```

**预期**：命中 `idx_alert_level_time`（`severity, created_at`）。

### V21 重置演示数据并核对（SC-008/SC-015）

```bash
cd backend && uv run python -m app.cli.reset_demo --yes
```

**预期**（stdout JSON）：`cleared.sessions/attack_log/rule_hits/alerts/attacker_profile` 均为
清理前计数、当前为 0；`kept.detection_rules>=5`；`kept.fake_users=30`。

```sql
SELECT (SELECT COUNT(*) FROM sessions) AS s, (SELECT COUNT(*) FROM attack_log) AS e,
       (SELECT COUNT(*) FROM rule_hits) AS h, (SELECT COUNT(*) FROM alerts) AS a,
       (SELECT COUNT(*) FROM attacker_profile) AS p,
       (SELECT COUNT(*) FROM detection_rules) AS r;   -- 期望 0,0,0,0,0,>=5
```

**纯 SQL 重置（无脚本时的降级做法，按外键依赖顺序）**：

```sql
START TRANSACTION;
DELETE FROM alerts;
DELETE FROM rule_hits;
DELETE FROM attack_log;
DELETE FROM attacker_intent;
DELETE FROM attacker_profile;
DELETE FROM sessions;
COMMIT;
-- 注意：不得删除 detection_rules、fake_* 种子数据与 audit_log（仅追加）
```

### V22 连续三轮演示（SC-008）

```bash
for round in 1 2 3; do
  echo "===== ROUND $round ====="
  (cd backend && uv run python -m app.cli.reset_demo --yes > /dev/null)
  (cd backend && uv run python -m app.cli.import_samples --set demo_basic) | jq '{imported, deduped, alerts: [.samples[].alerts] | add}'
  curl -s "$API/api/overview" | jq -c
  curl -s "$API/api/attackers?page=1&page_size=1&sort=risk_score" | jq -c '.items[0] | {source_ip, risk_score, risk_level}'
done
```

**预期**：三轮的 `imported`、概览数字与首位攻击者风险分**完全一致**；无人工修补步骤；
每轮结束后 `detection_rules` 仍为 5 条以上、历史会话已清空。

### V23（可选）授权模拟器生成测试流量

```bash
cd backend && uv run python -m app.cli.simulate_traffic --target 127.0.0.1:3307 --rounds 3
```

**预期**：仅连接 `.env` 中声明的 `HONEYPOT_ALLOWED_CLIENT_CIDRS` 内地址；每轮产生新的
`connect/auth/query/disconnect` 事件与控制台数据；不对任何未声明地址发起连接（FR-077/FR-009）。

---

## 7. 成功标准（SC）与验证步骤映射

| 成功标准 | 内容摘要 | 验证场景 | 现场证据 |
| --- | --- | --- | --- |
| **SC-001** | 客户端可连接并完成握手，连续三次成功 | V02（循环 3 次） | 客户端输出 + 3 个新 `session_id` |
| **SC-002** | 连接/认证/SQL 事件全部入库，关键字段无缺失 | V02、V03、V06 | `attack_log` 查询结果与时间线截图 |
| **SC-003** | 任选会话可还原事件顺序，与查询逐条一致 | V06 | 时间线 JSON 与 SQL 结果对照 |
| **SC-004** | 五条规则各有固定样本稳定触发，重复执行一致 | V04、V07、V08、V09 | `demo_basic` 两次导入结果对比 |
| **SC-005** | 画像连接数/查询数/首末时间/风险分与聚合一致 | V10、V12 | API 返回与视图查询对照 |
| **SC-006** | 爆破/拖库/破坏性样本生成告警，证据可追溯 | V07、V08、V09、V13 | `alerts.latest_hit_id` → `rule_hits` → `event_id` |
| **SC-007** | 展示与导出 100% 无真实个人信息/口令/可用内网信息 | V03、V05、V13 | 诱饵数据抽样 + 接口响应全文检索 |
| **SC-008** | 演示脚本连续执行三次结果一致 | V22 | 三轮输出对比记录 |
| **SC-009** | 四页在预置数据与空数据下均可用，数字与视图一致 | V10、V11、V12、V13、V21 | 空态截图 + 数字对照表 |
| **SC-010** | 四个视图均被使用，各有可执行演示查询 | V19 | 四条 SQL 结果截图 |
| **SC-011** | 重复提交同一事件 10 次效果与 1 次相同 | V16 | 前后概览快照与 `event_uuid` 分组查询 |
| **SC-012** | 写事务注入失败后五类数据与事务前一致且可重试 | V18 | `verify_transaction` 输出与前后计数 |
| **SC-013** | 至少两组高频查询索引前后计划变化 | V20 | 两组 `EXPLAIN` 的 `type/key/rows` 与耗时 |
| **SC-014** | 本机页面查询与画像刷新在可接受时间内完成 | V10–V13 | 浏览器 Network 面板耗时（建议 < 500 ms） |
| **SC-015** | 可从迁移/种子/视图/索引脚本在另一台机器完整重建 | 第 4 章全流程 + V21 | 复现记录（版本、命令、结果） |

**分阶段验收对应**：

| 阶段 | 场景 | 现场证据 |
| --- | --- | --- |
| 样本闭环 | V04（S03）+ `attack_log` 三条有序事件 | 仅 `SHOW TABLES` 事件命中 R03 |
| 诱饵闭环 | V02 + V06 | 客户端返回伪造表列表 + 新会话时间线 |
| 课程交付 | V01–V22 全量 | 测试矩阵、EXPLAIN 记录、四页截图 |

---

## 8. 重置与关闭顺序

### 8.1 重置（每轮演示前）

```bash
cd backend && uv run python -m app.cli.reset_demo --yes
```

- 单事务执行，按外键依赖顺序清理 `alerts → rule_hits → attack_log → attacker_intent →
  sessions → attacker_profile`，保留 `detection_rules` 与 `fake_*`（FR-040）。
- 脚本失败整体回滚并返回非 0；若脚本不可用，用 V21 的纯 SQL 事务降级。
- 重置后先核对 `detection_rules` 仍在、会话已清空，再开始下一轮。

### 8.2 关闭顺序

```bash
# 1) 前端（开发模式）：Ctrl+C
# 2) 后端：Ctrl+C（Uvicorn 优雅停机）
# 3) 诱饵：Ctrl+C
# 4) 数据库：保留容器，仅停止
docker compose -f compose.yaml stop mysql
# 需要完全移除容器（数据卷保留）：
docker compose -f compose.yaml down
```

**注意**：先停诱饵再停数据库，避免诱饵在数据库不可用时持续写失败日志；`docker compose down -v`
会删除数据卷（仅演示前重建时使用）。

### 8.3 演示前兜底

- 保留一份干净库备份：`uv run python -m app.cli.backup_demo --out backup/demo_clean.sql`；
- 关闭诱饵后 `mysqldump honeypot_demo > backup/demo_$(date +%Y%m%d_%H%M).sql`；
- 准备完整录屏；端口被占用时按第 9 章切换端口并同步 `.env` 与前端代理。

---

## 9. 常见故障与处理

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `Address already in use`（3307） | 已有诱饵实例或真实 MySQL 占用 3307 | `ss -ltnp \| grep 3307` 找到进程；改 `HONEYPOT_PORT`（如 3308）并同步文档/演示脚本 |
| `Address already in use`（8000/5173/3306） | 端口冲突 | 改 `API_PORT`/`WEB_DEV_PORT`/`MYSQL_PORT`；前端 Vite 代理目标同步改 `vite.config.ts` 的 `/api` target |
| 客户端报 `ERROR 1045`（预置账号） | 口令错误、`HONEYPOT_ACCOUNT_*_PASSWORD` 未导出、`.env` 未 source | 确认 `source .env`；确认用 `--default-auth=mysql_native_password` 与 `--ssl-mode=DISABLED` |
| 客户端报 `ERROR 2059 (HY000): Authentication plugin ... cannot be loaded` 或认证插件错误 | 客户端强制 `caching_sha2_password`，服务端只支持 native | 加 `--default-auth=mysql_native_password`；GUI 工具关闭 SSL 并显式选 native；改用 PyMySQL（见 `contracts/honeypot-protocol.md` 4.3） |
| 客户端报 `ERROR 2026 (HY000): SSL connection error` | 客户端 `ssl-mode=REQUIRED`，服务端不支持 TLS | 加 `--ssl-mode=DISABLED`；不要为演示开启强制 TLS |
| 客户端报 `ERROR 1040: Too many connections` | 超过 `HONEYPOT_MAX_CONNECTIONS` | 关闭残留连接、调大上限；演示前重启诱饵 |
| 应用报 `1142`/`1044` 权限不足 | 账号缺少库权限 | 用管理员账号补 `GRANT`；确认使用的是 `honeypot_app_rw` 而非 `honeypot_app_ro` 写库 |
| `alembic upgrade head` 报 “Can't locate revision” | 迁移文件缺失或 `.venv` 版本不一致 | `git status` 检查迁移目录；`uv sync --frozen` 后重试；必要时重建库 |
| 视图创建失败（`ERROR 1356` 或语法错误） | MySQL < 8.0（CTE/窗口函数不支持）或 5.7 | 必须使用 8.0.16+；优先 8.4 LTS；检查 `SELECT VERSION()` |
| 建表报 `ERROR 1273: Unknown collation: 'utf8mb4_0900_ai_ci'` | MySQL 5.7 或 MariaDB | 改用 MySQL 8.4；不要用 MariaDB 代替 |
| 写入报 `ERROR 1366: Incorrect string value` 或中文乱码 | 连接未用 utf8mb4 | `DATABASE_URL` 加 `?charset=utf8mb4`；库/表排序规则为 `utf8mb4_0900_ai_ci`；客户端 `--default-character-set=utf8mb4` |
| 创建应用账号报插件相关错误 | MySQL 8.4 默认禁用 `mysql_native_password` | 使用默认 `caching_sha2_password` 并确认驱动（`asyncmy`）支持；不要强行启用已废弃插件 |
| 前端页面 502/`ECONNREFUSED`（`/api`） | 后端未启动或端口不对 | 确认 `curl 127.0.0.1:8000/api/health`；检查 `vite.config.ts` 代理 target |
| 浏览器控制台 CORS 报错 | 生产静态页与 API 不同源、或开发来源未在允许列表 | 生产用同源托管；开发仅允许 `127.0.0.1:5173`/`localhost:5173` |
| 概览数字与页面不一致 | 前端缓存或视图口径不一致 | 接口带 `no-store`；用 V10 的视图 SQL 对账；确认页面读的是视图而非明细表 |
| 时间显示相差 8 小时 | 时区未统一 | 数据库连接 `time_zone='+00:00'`；表字段存 UTC；前端按 UTC 渲染并在文档中说明 |
| `uv sync` 失败 | 网络/镜像/锁文件不一致 | 检查 `uv.lock` 是否提交；离线按 2.3；不要手动改锁文件 |
| `pnpm install` 失败 | 网络/Node 版本不符 | 确认 Node 24、pnpm 12；离线使用 pnpm store |
| Docker 不可用 | 实验机无 Docker 或权限不足 | 走第 2.1 降级路径（本机 MySQL 8.4） |
| 诱饵进程启动即退出 | 非回环监听未开开关 / 口令环境变量缺失 | 启动日志会指明具体校验项；按第 9 章配置说明修正 |

---

## 10. 安全提醒（每次演示必须遵守）

1. 诱饵端口只在本机或授权隔离网内监听，**不得**改 `HONEYPOT_ALLOW_NON_LOOPBACK=true` 后暴露
   到公网或校园网可路由网段。
2. `.env`、备份 SQL、录屏中不得出现真实口令；演示前 `git status` 确认没有误提交 `.env`。
3. 只使用本文档与 `contracts/` 中的 `TEST-ONLY` 占位口令；诱饵账号是虚构账号，与任何真实
   系统无关。
4. 采集到的 SQL/用户名/客户端信息一律视为不可信数据，只能在隔离环境查看与重放。
5. 不连接、不扫描任何未授权地址；模拟器只允许连接配置声明的授权目标（`127.0.0.1:3307`）。

---

## 11. 变更记录

| 版本 | 日期 | 变更 | 动机 |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-19 | 首次给出前置条件、Docker 与本机降级路径、8 步启动、V01–V23 验证场景、SC-001–SC-015 映射、故障处理与关闭顺序 | 落实 spec.md 用户故事 1–9、SC-001 至 SC-015 与总纲第九章演示方案，提供可重复执行的验收路径 |
| 1.1.0 | 2026-11-19 | 按 `data-model.md` 校正可执行 SQL 与字段：视图列名、`rule_hits.risk_weight/triggered_at`、告警 `latest_hit_id`、`session_id` UUID 形式、`audit_log` 与重置顺序；账号按最小权限拆为 `honeypot_migrate`/`honeypot_app_rw`/`honeypot_app_ro`，Alembic 使用迁移账号 | 保证快速开始的命令与查询可直接在定稿 Schema 上执行并得到文档所述结果 |
