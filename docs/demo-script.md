# 现场演示脚本（demo-script.md）

| 项目 | 内容 |
| --- | --- |
| 文档用途 | 给出可重复、可计时的现场演示步骤：从空库到连接、认证、踩点、拖库/破坏、控制台、伪数据隔离，并附数据库专项演示与答辩口径 |
| 目标读者 | 答辩演示者、同组替补、课程验收教师 |
| 建议时长 | 主流程 12–15 分钟；数据库专项 6–8 分钟；答辩问答 3–5 分钟 |
| 前置依赖 | MySQL 8.0.46、诱饵 3307、FastAPI 8000、前端产物（或 5173）；命令均在仓库根目录执行 |
| 与其他文档的关系 | 步骤依据 [test-plan.md](test-plan.md) 与 `quickstart.md` V01–V23；数据库对象见 [database-design.md](database-design.md)；EXPLAIN 数字见 [explain-indexes.md](explain-indexes.md)；分层说明见 [architecture.md](architecture.md) |

> **演示纪律**：所有流量均为授权模拟；只连接 `127.0.0.1:3307`，不访问任何真实业务库；
> 不展示 `.env`、完整口令、真实个人信息；演示数据可随时用 `reset_demo --yes` 重置。

---

## 0. 演示前检查（T-30 分钟）

```bash
set -a; source .env; set +a
API=http://127.0.0.1:8000

# 1) 服务与端口
docker compose ps
ss -ltnp | grep -E ':(3306|3307|8000|5173) '
curl -s "$API/api/health" | jq

# 2) 清空观测数据，保留规则/诱饵（演示从空库开始）
cd backend && .venv/bin/python -m app.cli.reset_demo --yes && cd ..

# 3) 干净副本（强烈建议）
docker exec dbhoneypot-mysql mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction honeypot_dev > /tmp/honeypot_dev_clean.sql

# 4) 录屏开始（OBS/系统录屏），并打开控制台
open http://127.0.0.1:8000/    # macOS；Linux 用 xdg-open
```

**检查表**

| 项目 | 期望 |
| --- | --- |
| `/api/health` | `status=ok`、`database=ok`、`honeypot=up` |
| 端口 | 3306/3307/8000 各一行；5173 仅开发模式 |
| 控制台 | 概览四张卡可加载；告警/攻击者页可打开 |
| 重置后 | `sessions/attack_log/rule_hits/alerts/attacker_profile` 为空；`detection_rules=5` |
| 备份 | `/tmp/honeypot_dev_clean.sql` 存在且非空 |

---

## 1. 演示总览

```mermaid
flowchart LR
    A["① 空库控制台<br/>1 min"] --> B["② 连接诱饵<br/>1 min"]
    B --> C["③ 认证失败/成功<br/>2 min"]
    C --> D["④ SHOW/DESCRIBE 踩点<br/>2 min"]
    D --> E["⑤ 样本拖库/破坏<br/>3 min"]
    E --> F["⑥ 控制台时间线/画像/告警<br/>3 min"]
    F --> G["⑦ 说明伪数据隔离<br/>1 min"]
    G --> H["数据库专项<br/>6–8 min"]
    H --> I["答辩口径与限制<br/>3–5 min"]
```

---

## 2. 七步演示

### 第 1 步：空库状态（约 1 分钟）

**操作**

```bash
curl -s "$API/api/overview" | jq
```

**预期**

```json
{"sessions":0,"queries":0,"alerts":0,"high_risk_attackers":0,"generated_at":"..."}
```

浏览器打开 `http://127.0.0.1:8000/`（开发模式 `http://127.0.0.1:5173/`），概览显示四个 0，
攻击者列表与告警列表显示空态，不报错。

**讲解点**：空库不是“坏掉”，而是证明页面数字来自数据库聚合；下一步的每条事件都会让数字变化。

**失败兜底**：若页面打不开，先用 `curl $API/api/overview` 展示 JSON 并切到已录制视频；
若数据库有残留数据，再执行一次 `reset_demo --yes`。

> 需要 2 000 级数据做 EXPLAIN 时，不要在第 1 步前生成（否则空库叙事不成立）；可在数据库专项
> 之前临时 `gen_demo_data --sessions 200 --events 2000`，或直接使用已有的 `db/explain` JSON。

---

### 第 2 步：连接诱饵（约 1 分钟）

**操作（宿主机无 mysql 客户端时用容器内客户端，推荐）**

```bash
set -a; source .env; set +a
ACC="$HONEYPOT_ACCOUNTS"; USER="${ACC%%,*}"; USER="${USER%%:*}"
PASS="${ACC#*:}"; PASS="${PASS%%,*}"

docker run --rm --network host -e MYSQL_PWD="$PASS" \
  docker.1ms.run/library/mysql:8.0 \
  mysql -h127.0.0.1 -P3307 -u"$USER" \
        --default-auth=mysql_native_password --ssl-mode=DISABLED \
        --default-character-set=utf8mb4 \
        -e "SELECT 1 AS connected;"
```

**预期**：返回一行 `connected=1`，退出码 0；后台出现 `connect` + `auth(success)` 事件。

**核对（另开终端）**

```sql
SELECT session_id, source_ip, started_at, request_count, session_status
FROM sessions ORDER BY started_at DESC LIMIT 1;
SELECT event_id, event_type, status, event_time
FROM attack_log ORDER BY event_id DESC LIMIT 3;
```

**讲解点**：3307 是诱饵服务，不是 3306 的真实 MySQL；连接即产生一条会话。

**失败兜底**：`1045` 检查口令是否来自 `.env` 的 `HONEYPOT_ACCOUNTS`；`2059/2026` 检查
`--default-auth=mysql_native_password --ssl-mode=DISABLED`；端口占用改 `HONEYPOT_PORT` 并同步演示命令。

---

### 第 3 步：认证失败 / 认证成功（约 2 分钟）

**失败认证**

```bash
docker run --rm --network host docker.1ms.run/library/mysql:8.0 \
  mysql -h127.0.0.1 -P3307 -u no_such_user -p'TEST-ONLY-WRONG' \
        --default-auth=mysql_native_password --ssl-mode=DISABLED \
        -e "SELECT 1;" ; echo "exit=$?"
```

**预期**：客户端报 `ERROR 1045 (28000): Access denied ...`，`exit` 非 0；后台仍有
`connect(success)` 与 `auth(failure)` 事件。

**成功认证**

```bash
docker run --rm --network host -e MYSQL_PWD="$PASS" \
  docker.1ms.run/library/mysql:8.0 \
  mysql -h127.0.0.1 -P3307 -u"$USER" \
        --default-auth=mysql_native_password --ssl-mode=DISABLED \
        --default-character-set=utf8mb4 \
        -e "SHOW DATABASES;"
```

**预期**：返回 `honeypot_shop`、`honeypot_archive`；后台 `auth(success)`。

**核对**

```sql
SELECT status, username, credential_test_id, COUNT(*) AS n
FROM attack_log WHERE event_type='auth'
GROUP BY status, username, credential_test_id ORDER BY n DESC LIMIT 5;
```

**讲解点**：失败与成功都记录；表中**没有口令列**，只保存用户名与 `TEST-ONLY` 测试标识。

**失败兜底**：若失败认证没有事件，检查服务是否在 3307、是否被旧进程占用；用录屏片段兜底。

---

### 第 4 步：SHOW / DESCRIBE 踩点（约 2 分钟）

**操作**：同一连接内依次执行

```sql
SHOW DATABASES;
USE honeypot_shop;
SHOW TABLES;
DESCRIBE users;
SELECT id, username, email FROM users LIMIT 5;
```

**预期**

- `SHOW TABLES` 返回 `config`、`orders`、`users`；
- `DESCRIBE users` 返回 7 列（`id/username/email/phone/password_hash/role/created_at`）；
- `SELECT` 返回固定 5 行伪造用户，邮箱形如 `demo_user_01@example.com`；
- 后台对应 `query(success)` 事件，并命中 **R03 recon +15**。

**核对**

```sql
SELECT h.rule_code, h.intent_type, h.risk_weight, h.rule_version,
       h.triggered_at, h.evidence_summary
FROM rule_hits h JOIN attack_log l ON l.event_id = h.event_id
WHERE l.source_ip = '127.0.0.1' AND h.rule_code='R03'
ORDER BY h.hit_id DESC LIMIT 3;
```

**讲解点**：`evidence_summary` 说明“命中了哪个元数据关键词”，不是只有标签。

**失败兜底**：若 R03 未命中，确认 `detection_rules` 中 R03 `enabled=1`；再执行一次 `SHOW TABLES`。

---

### 第 5 步：样本拖库 / 破坏（约 3 分钟）

**方式 A（推荐，固定样本，可重复）**

```bash
cd backend
.venv/bin/python -m app.cli.import_samples --sample S03 --sample S04
```

**预期（stdout JSON 摘要）**

| 样本 | 内容 | 结果 |
| --- | --- | --- |
| `S03` | 同一会话连续 SELECT、累计 1000 行 | 命中 **R04 data_dump +25**，生成 `data_dump` 告警（`severity=high`） |
| `S04` | `DROP TABLE fake_orders` 被拒绝 | 命中 **R05 destructive +35**，生成 `destructive` 告警（`severity=critical`） |

**方式 B（真实客户端，展示“诱饵层拒绝执行”）**

```sql
-- 同一连接内逐条执行，均预期 1142
UPDATE orders SET status='cancelled' WHERE id=1;
DELETE FROM orders WHERE id=1;
DROP TABLE orders;
TRUNCATE TABLE orders;
INSERT INTO users (username) VALUES ('demo_user_x');
SELECT COUNT(*) FROM orders;   -- 仍返回 120，诱饵数据未被修改
```

**讲解点**：写操作“记录但不执行”，因此既有攻击证据，又没有真实数据破坏风险。

**失败兜底**：若 `import_samples` 报数据库不可达，检查 `DATABASE_URL` 与迁移；若样本已导入过，
重复导入会走幂等（`deduped` 非零），可改讲“幂等”而不是重复制造告警。

---

### 第 6 步：控制台时间线 / 画像 / 告警（约 3 分钟）

**入口**

- 概览：`http://127.0.0.1:8000/`
- 攻击者列表：`http://127.0.0.1:8000/#/attackers`
- 攻击者详情：点击风险最高的来源（例如 `198.51.100.17` 或 `127.0.0.1`）
- 告警列表：`http://127.0.0.1:8000/#/alerts`

**展示顺序**

1. **概览**：会话数、查询数、告警数、高风险攻击者数变化；趋势图显示有事件日期。
2. **攻击者列表**：按风险分降序；主要意图标签、连接数、认证尝试、告警数。
3. **攻击者详情**：画像统计 → 意图列表（分数/证据计数/最近时间）→ 会话摘要 → 点击会话打开时间线。
4. **时间线**：`connect → auth → query… → disconnect` 顺序；每条显示状态、SQL 摘要、规则命中。
5. **告警列表**：筛选 `critical`/`high`；点击“标记已读”，状态立即变为已读并写审计。

**可复现的接口命令（页面故障时）**

```bash
curl -s "$API/api/overview" | jq
curl -s "$API/api/attackers?page=1&page_size=5&sort=risk_score&order=desc" | jq
curl -s "$API/api/attackers/127.0.0.1" | jq '{attacker,intents,sessions,recent_rule_hits}'
SID=$(curl -s "$API/api/attackers/127.0.0.1" | jq -r '.sessions[0].session_id')
curl -s "$API/api/sessions/$SID/timeline" | jq '{session,events,rule_hits,alerts}'
curl -s "$API/api/alerts?severity=high&is_read=false" | jq
```

**讲解点**：页面数字全部来自 4 个视图；详情页才读明细与证据；告警可以定位到 `latest_hit_id`。

**失败兜底**：前端 502/空白时直接用上面的 `curl` 展示 JSON；或切到录屏。

---

### 第 7 步：说明伪数据隔离（约 1 分钟）

**操作**

```bash
# 1) 诱饵端口看到的“假库”
docker run --rm --network host -e MYSQL_PWD="$PASS" \
  docker.1ms.run/library/mysql:8.0 \
  mysql -h127.0.0.1 -P3307 -u"$USER" \
        --default-auth=mysql_native_password --ssl-mode=DISABLED \
        -e "SHOW DATABASES; SELECT config_key, config_value FROM honeypot_shop.config LIMIT 3;"

# 2) 真实 MySQL 端口（3306）没有 honeypot_shop 库
docker exec dbhoneypot-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
  -e "SHOW DATABASES LIKE 'honeypot_shop';"   # 期望：空结果

# 3) 物理诱饵表可在 3306 查到，但只是 TEST-ONLY 数据
docker exec dbhoneypot-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
  -e "SELECT username,email,LEFT(password_hash,18) FROM honeypot_dev.fake_users LIMIT 3;"
```

**讲解点**

- `honeypot_shop` / `honeypot_archive` 只存在于诱饵协议投影中，真实库没有这两个库；
- 物理 `fake_*` 表只是诱饵数据源，所有邮箱/手机号/哈希/密钥均为 `TEST-ONLY` 虚构值；
- 诱饵服务只监听 `127.0.0.1:3307`，不暴露公网，不连接真实资产；
- 采集到的 SQL 只存储不执行。

**失败兜底**：用 `fake_catalog.py` 与 `db/init` 截图说明，不强行现场操作。

---

## 3. 数据库专项演示（6–8 分钟）

### 3.1 外键拦截（约 1 分钟）

```sql
-- 用不存在的 session_id 写事件，预期 ERROR 1452
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-0000000000f1',
        '00000000-0000-4000-8000-0000000000ff',
        'connect', '203.0.113.9', UTC_TIMESTAMP(), 'success');
```

**预期**：`ERROR 1452 (23000): Cannot add or update a child row ...`，`attack_log` 行数不变。

**讲解点**：`sessions` 是会话主表，日志不能引用不存在的会话；外键是数据库层保证，不靠代码。

### 3.2 `event_uuid` 幂等（约 1 分钟）

先用一个真实存在的会话编号，插入固定 `event_uuid` 两次：

```sql
SET @sid = (SELECT session_id FROM sessions LIMIT 1);
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-0000000000f2', @sid, 'connect', '203.0.113.9', UTC_TIMESTAMP(), 'success');
-- 再执行一次相同语句：
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-0000000000f2', @sid, 'connect', '203.0.113.9', UTC_TIMESTAMP(), 'success');
```

**预期**：第二次 `ERROR 1062 (23000): Duplicate entry ... for key 'uk_attack_log_event_uuid'`；
`SELECT COUNT(*) FROM attack_log WHERE event_uuid='...f2'` 仍为 1。

**讲解点**：幂等由唯一约束裁决，不依赖应用“先查后插”；重复请求返回已有事件编号，不重复计数。

### 3.3 事务回滚（约 1.5 分钟）

**方式 A（应用层，推荐）**

```bash
cd backend
.venv/bin/python -m app.cli.verify_transaction --inject-failure profile_write
```

**预期**：输出显示 `sessions/attack_log/rule_hits/attacker_profile/attacker_intent/alerts`
在“执行前 / 注入失败后 / 清理后”计数一致，`exit=0`；日志中可见失败阶段与 `event_uuid`。

**方式 B（数据库层手工事务）**

```sql
START TRANSACTION;
INSERT INTO sessions (session_id, source_ip, target_service, started_at, session_status,
                      request_count, max_risk_score)
VALUES ('00000000-0000-4000-8000-00000000aa01', '203.0.113.9', 'mysql-honeypot',
        UTC_TIMESTAMP(), 'active', 0, 0);
-- 故意触发外键失败
INSERT INTO attack_log (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES ('00000000-0000-4000-8000-0000000000f3',
        '00000000-0000-4000-8000-0000000000ff', 'connect', '203.0.113.9',
        UTC_TIMESTAMP(), 'success');
ROLLBACK;
SELECT COUNT(*) FROM sessions WHERE session_id='00000000-0000-4000-8000-00000000aa01';  -- 0
```

**讲解点**：事件写入的会话、日志、命中、画像、意图、告警在同一事务；任一步失败整体回滚。

### 3.4 四个分析视图（约 1.5 分钟）

```sql
-- ① 会话风险汇总：CTE + 多表 LEFT JOIN + GROUP BY
SELECT session_id, source_ip, event_count, query_count, hit_rule_codes,
       calculated_risk_score, risk_level, stored_max_risk_score, alert_count
FROM v_session_risk_summary
ORDER BY calculated_risk_score DESC, started_at DESC LIMIT 5;

-- ② 攻击者画像汇总：JOIN 聚合 + ROW_NUMBER 选主要意图
SELECT source_ip, calculated_risk_score, risk_level, primary_intent_type,
       session_count, total_queries, alert_count
FROM v_attacker_profile_summary
ORDER BY calculated_risk_score DESC, last_seen DESC LIMIT 5;

-- ③ 每日趋势：CTE + LAG + SUM() OVER + RANK()
SELECT stat_date, event_count, prev_event_count, event_count_delta,
       event_change_pct, cumulative_event_count, busy_day_rank
FROM v_daily_attack_trend ORDER BY stat_date DESC LIMIT 7;

-- ④ 规则效果：COUNT(DISTINCT) + RANK()
SELECT hit_rank, rule_code, rule_name, intent_type, is_enabled,
       hit_count, affected_attacker_count, alert_count, alert_per_hit_ratio
FROM v_rule_effectiveness ORDER BY hit_rank;
```

**讲解点**：四个视图分别体现 JOIN、窗口函数、CTE、排名；页面优先查视图，详情页再查明细。

### 3.5 EXPLAIN 前后对比（约 1.5 分钟）

**生成记录**

```bash
cd backend
.venv/bin/python -m app.cli.explain_diff
# 结果写入 ../db/explain/explain_<UTC时间戳>.json，并在 stdout 打印摘要
```

**现场查询（两条高频查询）**

```sql
-- Q1 会话时间线
EXPLAIN SELECT event_id, event_type, event_time, status
FROM attack_log
WHERE session_id = '5a060001-0000-4000-8000-000000000001'
ORDER BY event_time, event_id;

-- Q2 近期高等级告警
EXPLAIN SELECT alert_id, severity, created_at
FROM alerts WHERE severity='critical'
ORDER BY created_at DESC LIMIT 20;
```

**预期**：Q1 命中 `idx_log_session_time`（`type=ref`，`key_len=36`，`rows` 显著小于全表）；
Q2 命中 `idx_alert_level_time`（`type=ref`，`key_len=34`，反向扫描）。

**已生成的证据**：`db/explain/explain_20261119T145423Z.json`。实测摘要：

| 组 | 查询 | 索引前 | 索引后 | 估算行数 | 中位耗时 |
| --- | --- | --- | --- | --- | --- |
| G1 | Q1 会话时间线 | `ALL / key=NULL / filesort=true` | `ref / idx_log_session_time / 无 filesort` | 2174 → 16 | 2.749 ms → 1.253 ms |
| G2 | Q2 近期高等级告警 | `ALL / key=NULL / filesort=true` | `ref / idx_alert_level_time / 反向索引扫描` | 9 → 3 | 1.054 ms → 0.998 ms |

**讲解点**：`type/key/rows/filesort` 的变化比毫秒数更有说服力；当前数据量小，耗时差异有限，
数据量增大后差距会拉开。完整对比与复现见 [explain-indexes.md](explain-indexes.md)。

---

## 4. 失败兜底与恢复

### 4.1 现场故障处理

| 故障 | 快速处理 |
| --- | --- |
| 3307 端口占用 | `ss -ltnp \| grep 3307` 找进程；改 `HONEYPOT_PORT=3308` 并同步所有演示命令 |
| API 8000 不通 | `cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| 控制台空白 | 用 `curl` 展示 JSON；或切录屏 |
| 数据库不可用 | `docker compose up -d mysql`；必要时恢复备份 |
| 数据被污染 | `python -m app.cli.reset_demo --yes`，再导入样本 |
| 规则被改坏 | `git` 恢复迁移/种子；或重建库后 `alembic upgrade head && seed --all` |
| 全部失败 | 播放完整录屏，按本文顺序讲解截图与查询结果 |

### 4.2 从干净副本恢复

```bash
docker exec -i dbhoneypot-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" honeypot_dev \
  < /tmp/honeypot_dev_clean.sql
# 恢复后复查：
docker exec dbhoneypot-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N \
  -e "SELECT COUNT(*) FROM honeypot_dev.detection_rules; SELECT COUNT(*) FROM honeypot_dev.sessions;"
```

### 4.3 结束清场

```bash
cd backend && .venv/bin/python -m app.cli.reset_demo --yes
# 先停前端/后端/诱饵，再停数据库
docker compose stop mysql
```

---

## 5. 答辩口径

### 5.1 创新点（诚实表述）

> 本项目把 **MySQL 协议诱饵、结构化行为日志、可解释规则、攻击者画像和实时控制台**
> 整合为一个课程级闭环：访问者在 3307 看到的是一套完全虚构的库表；后台把同一次连接的
> 连接、认证与 SQL 串成会话，用数据库配置的 R01–R05 规则生成意图、0–100 风险分和可追溯
> 告警，并能在控制台中从告警逐级回到原始事件。创新点在**场景组合与完整闭环**，
> 不在新的检测算法。

### 5.2 主动说明的限制

| 限制 | 表述 |
| --- | --- |
| 规则阈值 | 来自课程演示数据，不是生产安全基线；误报/漏报未做大规模评估 |
| 协议范围 | 只支持 MySQL 最小子集与 `mysql_native_password`；不支持 SSL、预处理协议、多语句，部分 GUI 客户端需特殊配置 |
| 部署规模 | 单机、Docker 隔离网段；不做高并发、分区、分布式与高可用 |
| 检测能力 | 只观察进入诱饵环境的流量；不能发现绕过蜜罐的真实攻击 |
| AI | 默认关闭，只做白名单只读模板与辅助解释；不参与评分与最终判定 |
| 权限 | 四类账号已分离；表级最小权限收紧脚本需在演示前执行（若现场未执行，应说明“设计已定义，实例待收紧”） |
| 测试 | 自动化测试已补齐部分单元/冒烟用例；完整集成/接口回归仍以手工验收为主 |
| 错误码 | 只保证 MySQL 错误码与行为类别一致，不保证错误文案逐字相同 |

### 5.3 预设问答

| 问题 | 回答要点 |
| --- | --- |
| 为什么用 MySQL 模拟库而不是真实 MySQL？ | 真实 MySQL 难以灵活伪造库表与按事件注入，且 general_log 粒度/权限复杂；模拟库安全、可控，降级路线可换真实 MySQL |
| 风险分怎么保证可解释？ | 每个命中写 `rule_hits`，保存规则版本/权重/证据摘要；分数按 `rule_code` 去重取最大权重求和并封顶，每分可回溯 |
| 重复事件会不会重复计数？ | 不会。`event_uuid` 唯一约束是唯一裁决点；重复提交返回已有 `event_id`，不重复分析 |
| 告警为什么会去重？ | `dedup_key=<rule_code>:<source_ip>:<UTC日期>` 唯一；重复触发只累加次数、更新最近时间与证据 |
| 视图会不会拖慢页面？ | 当前规模（千至万级事件）可接受；页面查询带 LIMIT；数据量增大后可物化汇总表 |
| 为什么画像和会话没有外键？ | 画像按 IP 聚合、先有会话后有画像；强加外键会破坏写入顺序，改由事务顺序 + 视图重算 + 校验 SQL 保证一致 |
| 裁判/老师问“这是不是真攻击”？ | 全部为授权模拟/合成样本；来源使用 RFC 5737 保留网段；不连接真实资产 |
| AI 会不会改分数？ | 不会。AI 只用只读账号执行白名单模板，输出标记为辅助解释，不参与规则/评分/等级 |

---

## 6. 演示后记录

| 字段 | 内容 |
| --- | --- |
| 日期/环境 | 2026-11-19，MySQL 8.0.46，API 8000，诱饵 3307 |
| 使用样本 | `demo_basic`（S01–S07）或 `S03+S04` |
| 关键会话 | `5a030001-...`（R04）、`5a040001-...`（R05）、`5a060001-...`（综合 85 分） |
| 关键告警 | `alert_id`、`latest_hit_id`、`dedup_key` |
| 结果 | 7 步是否全部完成；失败步骤与兜底方式 |
| 录屏/截图 | 文件名与存放位置（建议 `docs/evidence/`，当前仓库未创建） |

---

## 7. 相关文档

- [test-plan.md](test-plan.md)：测试矩阵、SC 映射与证据记录模板。
- [database-design.md](database-design.md)：ER、约束、视图、事务与账号。
- [explain-indexes.md](explain-indexes.md)：EXPLAIN JSON 依据与复现步骤。
- [architecture.md](architecture.md)：五层架构、端口、安全边界。
- `specs/001-database-honeypot/quickstart.md`：V01–V23 命令全集与故障处理。
- `backend/app/cli/samples/README.md`：S01–S07 样本编号与预期（与实际代码一致）。
