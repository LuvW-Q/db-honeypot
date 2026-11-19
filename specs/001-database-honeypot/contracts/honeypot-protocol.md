# 诱饵协议契约：MySQL 协议模拟范围、兼容性与配置（honeypot-protocol.md）

**Feature**: `001-database-honeypot` | **版本**: 1.1.0 | **日期**: 2026-11-19

**适用范围**：本文档定义诱饵服务（mysql-mimic 3.0.5，默认监听 `127.0.0.1:3307`）的协议
模拟范围、认证与账号策略、语句路由与响应、伪造库表内容、错误码、上限、事件产生顺序、
安全边界与配置项契约。标准事件字段见 `contracts/events.md`；HTTP 契约见
`contracts/api.md`。

**关联需求**：`spec.md` 用户故事 1、FR-001 至 FR-010、FR-030、FR-079、FR-083；总纲
“诱饵数据库模块”“安全红线”“降级路线”；宪法原则三（安全与最小权限）。

**技术基线**：Python 3.14 + `mysql-mimic` 3.0.5（Python 实现的 MySQL 服务端协议模拟库，
Tornado 不引入、不作为依赖），端口默认 3307（避开真实 MySQL 的 3306），配置文件可改。
`mysql-mimic` 负责握手、认证与命令循环；语句路由、伪造结果与事件产生由本项目实现。

---

## 1. 协议模拟范围（明确的能力边界）

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| TCP 监听与连接管理 | 支持 | 默认只绑定回环地址；最大连接数 200 |
| 服务端 greeting 握手（Protocol 10） | 支持 | 返回伪造版本号与能力位 |
| `mysql_native_password` 认证 | 支持 | 预置诱饵账号；未知账号返回 1045 且记录事件 |
| `caching_sha2_password` 认证 | **不支持（见第 4 章）** | 客户端指定该插件时认证失败；规避方式见 4.3/4.4 |
| `COM_QUERY` | 支持 | 按下表路由，全部返回伪造数据或受控错误 |
| `COM_QUIT` | 支持 | 产生 `disconnect` 事件并关闭会话 |
| `COM_PING` | 支持 | 返回 OK 包（不产生事件，仅运行日志计数） |
| `COM_INIT_DB`（`USE db`） | 支持 | 已知库切换成功并记录查询事件；未知库 1049 |
| `COM_FIELD_LIST` | 受限 | 仅对已知伪造表返回列定义；其他返回 1146 |
| `COM_STMT_PREPARE/EXECUTE`（二进制预处理协议） | **不支持（本版）** | 返回 1295；客户端需关闭预处理（见 4.3） |
| SSL/TLS 加密连接 | **不支持（本版）** | greeting 不声明 `CLIENT_SSL`；客户端强制 `ssl-mode=REQUIRED` 会失败，用 `DISABLED`/`PREFERRED` |
| 多语句（`;` 分隔一次发送） | **不支持（本版）** | 按单条语句处理并记录；不声明 `CLIENT_MULTI_STATEMENTS` |
| `LOAD DATA LOCAL INFILE` | **拒绝** | 返回 1148，记录 `status=denied`（不读客户端文件） |
| `SELECT ... INTO OUTFILE/DUMPFILE` | **拒绝** | 返回 1142，记录 `status=denied`（不写文件） |
| 事务语句（`BEGIN/COMMIT/ROLLBACK`） | 受控接受 | 返回 OK 但不维护真实事务状态（诱饵无真实数据变更），记录事件 |
| 存储过程、触发器、事件、UDF、复制协议 | **拒绝/不支持** | 返回 1064 或 1142，记录事件 |
| `GRANT/REVOKE/CREATE USER/INSTALL PLUGIN` | **拒绝** | 返回 1142，记录 `status=denied` |
| `KILL`（`COM_PROCESS_KILL`） | **拒绝** | 返回 1094，记录 `status=denied`（不得影响其他连接） |

**非目标**：不实现 MySQL 完整 SQL 语法、不实现真实执行引擎、不保证与真实 MySQL 的错误信息
逐字一致（只保证错误码与行为类别一致）。

---

## 2. 握手与认证

### 2.1 服务端 greeting（初始握手包）

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `protocol_version` | `10` | MySQL 协议版本 |
| `server_version` | `8.4.0-honeypot` | 明显的自定义后缀，避免冒充真实实例；客户端仅用于展示 |
| `connection_id` | 自增整数（进程内从 1 开始） | 仅用于协议字段，**不是** `session_id` |
| `auth_plugin_name` | `mysql_native_password` | 认证插件通告 |
| `auth_plugin_data` | 20 字节随机 scramble（每次连接重新生成） | 不得复用、不得落库 |
| `capability_flags` | 41 协议基础位：`CLIENT_LONG_PASSWORD`、`CLIENT_FOUND_ROWS`、`CLIENT_LONG_FLAG`、`CLIENT_CONNECT_WITH_DB`、`CLIENT_PROTOCOL_41`、`CLIENT_TRANSACTIONS`、`CLIENT_SECURE_CONNECTION`、`CLIENT_PLUGIN_AUTH`、`CLIENT_PLUGIN_AUTH_LENENC_CLIENT_DATA`、`CLIENT_DEPRECATE_EOF` | **不声明** `CLIENT_SSL`、`CLIENT_LOCAL_FILES`、`CLIENT_MULTI_STATEMENTS`、`CLIENT_COMPRESS` |
| `character_set` | `255`（`utf8mb4_0900_ai_ci`）；兼容性降级值 `45`（`utf8mb4_general_ci`） | 保底保证客户端按 utf8mb4 解析 |
| `status_flags` | `SERVER_STATUS_AUTOCOMMIT` | 不维护真实事务状态 |
| `server_capabilities` | 与 `capability_flags` 一致 | — |

**握手时序**：

```text
客户端                              诱饵服务
  │ ─────── TCP SYN ───────────────► │  生成 UUID v4 session_id，准备 connect 事件
  │ ◄────── Server Greeting ──────── │  protocol 10 + scramble + native password
  │ ─────── Handshake Response ────► │  解析 username / 认证响应 / 库名 / 客户端特征
  │ ◄────── OK 或 ERR(1045) ─────── │  认证判定 + 记录 auth 事件
```

**认证失败**时：服务端先发 `ERR 1045`，然后**关闭连接**；`connect` 与失败的 `auth` 事件
都已落库，`disconnect` 事件按会话关闭流程写入，`session_status` 记为 `closed`
（非 `error`——认证失败是受控结果）。

### 2.2 `mysql_native_password` 校验

- 服务端保存的是口令的**二级摘要**：`stage2 = SHA1(SHA1(password))`（由环境变量中的口令在
  启动时内存计算，**不落库、不写日志、不出现在配置模板明文**）。
- 客户端响应校验：`expected = SHA1(stage2 + scramble) XOR stage2`，与客户端返回值做
  **常量时间**比较（`hmac.compare_digest`）。
- 认证只用于判定“是否为本项目预置的诱饵账号”，不连接任何真实数据库。
- 每次认证的 scramble 独立随机；不实现“快速认证缓存”（`caching_sha2_password` 的
  `fast_auth` 不在本版范围）。

### 2.3 诱饵账号策略

| 项目 | 约定 |
| --- | --- |
| 账号数量 | 默认 2 个：`demo_app`（普通业务诱饵账号）、`demo_reader`（只读诱饵账号） |
| 口令来源 | 环境变量 `HONEYPOT_ACCOUNT_1_PASSWORD` / `HONEYPOT_ACCOUNT_2_PASSWORD`；仓库内 `.env.example` 只写 `TEST-ONLY-PASSWORD-PLACEHOLDER` 占位，**禁止提交真实口令** |
| `credential_test_id` | 每个账号配置一个合成样本标识，如 `TEST-ONLY-ACC-01`；写入 auth 事件的 `credential_test_id` 字段 |
| 未知账号 | 返回 `1045`，记录 `auth` 事件（`status=failure`, `error_code=1045`），`username` 原样记录（截断 128 字符），`credential_test_id` 记为 `TEST-ONLY-UNKNOWN-001` 起的序号 |
| 认证失败日志 | **不记录口令、不记录口令长度、不记录哈希**；只记录“一次失败尝试” |
| 空用户名 | 返回 `1045`，记录事件（`username` 为空字符串） |
| 超长用户名（> 128 字符） | 截断后记录，认证判定为失败 |
| 同一来源连续失败 | 不做封禁（本版无封禁策略，避免演示被自己锁死）；由 R02 规则识别爆破 |
| 已认证账号权限 | 与未认证无关：诱饵层不存在真实权限系统，写语句一律 1142 |

---

## 3. 语句路由与响应

### 3.1 伪造库与表

对外暴露的数据库与表（全部由固定夹具生成，**不是**采集库中的真实 `fake_*` 表）：

| 库名 | 说明 |
| --- | --- |
| `honeypot_shop` | 主业务诱饵库，包含 `users`、`orders`、`config` 三张表 |
| `honeypot_archive` | 诱饵“归档库”，包含 `orders_2025` 一张表，用于制造“多库结构”的真实感 |
| `information_schema` | 只提供 `schemata`、`tables`、`columns` 三个假视图的查询结果，内容与上述两库一致 |

> **命名分离（重要）**：采集库中持久化诱饵数据的三张物理表命名为 `fake_users`、
> `fake_orders`、`fake_config`（FR-030）；协议层对外**投影**为 `users`、`orders`、
> `config`。物理表只由存储层读取生成响应，绝不被客户端 SQL 直接访问（客户端根本没有
> 连接真实数据库的凭证）。

### 3.2 表结构（DESCRIBE / information_schema 返回）

```sql
-- users（对外投影，物理来源 fake_users）
id            INT           NOT NULL  -- 主键，1..30
username      VARCHAR(32)   NOT NULL  -- 伪造用户名，如 demo_user_01
email         VARCHAR(64)   NOT NULL  -- 形如 demo01@example.invalid
phone         VARCHAR(20)   NOT NULL  -- 形如 19900000001（明显占位段）
password_hash VARCHAR(64)   NOT NULL  -- 形如 TEST-ONLY-HASH-xxxxxxxx
role          VARCHAR(16)   NOT NULL  -- admin / staff / customer
created_at    DATETIME      NOT NULL

-- orders（对外投影，物理来源 fake_orders）
id         INT           NOT NULL  -- 主键
user_id    INT           NOT NULL  -- 关联 users.id（真实外键在采集库 fake_orders 上）
order_no   VARCHAR(32)   NOT NULL  -- 形如 TEST-ORDER-000001
amount     DECIMAL(10,2) NOT NULL  -- 0.00..9999.99，全部为演示金额
status     VARCHAR(16)   NOT NULL  -- paid / pending / cancelled
created_at DATETIME      NOT NULL

-- config（对外投影，物理来源 fake_config）
config_key   VARCHAR(64)  NOT NULL  -- 唯一键
config_value VARCHAR(256) NOT NULL  -- 全部含 TEST-ONLY 前缀且不可用
description  VARCHAR(128) NOT NULL  -- 中文说明，标注“伪造配置”
```

**三张假表的固定内容口径**：

| 表 | 行数（固定） | 内容要求 |
| --- | --- | --- |
| `users` | 30 | 用户名/邮箱/手机号/哈希全部人工生成；邮箱统一 `@example.invalid`；手机号统一 `1990000xxxx` 段；哈希统一 `TEST-ONLY-HASH-` 前缀，**不可用于任何真实认证** |
| `orders` | 120（单次查询最多返回 100 行） | 订单号 `TEST-ORDER-` 前缀；金额为演示值；`user_id` 在 1..30 内 |
| `config` | 8 | 见下 |

`config` 的 8 条固定键（值全部不可用，**不得**包含可连通的主机、真实密钥或可用凭据）：

| `config_key` | `config_value`（示例口径） | 备注 |
| --- | --- | --- |
| `db.master.host` | `10.255.255.1:3306`（RFC 1918 保留段 + 文档化不可路由地址） | 不可达，且仅在本机/隔离网语义内 |
| `db.master.user` | `app_reader` | 虚构账号 |
| `db.master.password` | `TEST-ONLY-PASSWORD-PLACEHOLDER` | 占位符，不可用 |
| `payment.api_key` | `TEST-ONLY-APIKEY-0000000000` | 占位符 |
| `payment.endpoint` | `https://pay.example.invalid/api` | 保留域名，无法解析 |
| `mail.smtp.host` | `127.0.0.1:1025` | 本机无效端口 |
| `mail.smtp.password` | `TEST-ONLY-SMTP-PLACEHOLDER` | 占位符 |
| `feature.debug_mode` | `true` | 无关紧要的诱饵配置 |

行内容**确定性生成**（固定种子），同一语句重复执行返回完全相同的行，便于演示与截图对比；
不使用随机数、不使用当前时间作为数据内容（`created_at` 使用固定历史日期）。

### 3.3 SQL 路由表

| 语句类别 | 识别方式（标准化后前缀） | 响应 | `status` | `error_code` | 命中规则 |
| --- | --- | --- | --- | --- | --- |
| `SHOW DATABASES` | `^show\s+databases?` | 返回 2 行库名（`honeypot_shop`、`honeypot_archive`） | `success` | `0` | **R03**（recon） |
| `SHOW TABLES [FROM db]` | `^show\s+tables?` 或 `^show\s+full\s+tables?` | 返回该库表列表（固定 3–4 行） | `success` | `0` | **R03** |
| `SHOW COLUMNS FROM t` / `DESCRIBE t` / `DESC t` | `^show\s+columns` / `^describe` / `^desc\b` | 返回列定义（见 3.2） | `success` | `0` | **R03** |
| `SHOW CREATE TABLE t` | `^show\s+create\s+table` | 返回伪造 DDL 字符串 | `success` | `0` | **R03** |
| `SELECT ... FROM information_schema.*` | 含 `information_schema` | 返回与 3.2 一致的假元数据行 | `success` | `0` | **R03** |
| `SELECT ...`（基础查询） | `^select` | 返回伪造行（最多 100 行） | `success` | `0` | 可能 **R04**（累计返回行数/连续 SELECT 达阈值） |
| `SHOW VARIABLES` / `SHOW STATUS` / `SHOW PROCESSLIST` | `^show` 其他 | 返回固定空结果集或 2–3 行无害伪造变量 | `success` | `0` | 不命中 |
| `USE db` / `COM_INIT_DB` | `^use\s+` | 已知库：OK；未知库：`1049` | `success` / `error` | `0` / `1049` | 不命中 |
| `SET ...` | `^set\b` | OK（忽略并记录，不改变任何服务端状态） | `success` | `0` | 不命中 |
| `BEGIN/COMMIT/ROLLBACK` | `^(begin\|start\s+transaction\|commit\|rollback)` | OK（不维护事务状态） | `success` | `0` | 不命中 |
| `INSERT ...` | `^insert` | **拒绝**：`1142` | `denied` | `1142` | **R05** |
| `UPDATE ...` | `^update` | **拒绝**：`1142` | `denied` | `1142` | **R05** |
| `DELETE ...` | `^delete` | **拒绝**：`1142` | `denied` | `1142` | **R05** |
| `DROP ...` | `^drop` | **拒绝**：`1142` | `denied` | `1142` | **R05** |
| `TRUNCATE ...` | `^truncate` | **拒绝**：`1142` | `denied` | `1142` | **R05** |
| `ALTER ...` | `^alter` | **拒绝**：`1142` | `denied` | `1142` | **R05**（按破坏性口径处理，见 3.4） |
| `CREATE ...` | `^create` | **拒绝**：`1142` | `denied` | `1142` | 不命中（本版 R05 只覆盖写/破坏五类） |
| `GRANT/REVOKE/CREATE USER/KILL/INSTALL PLUGIN` | 关键字匹配 | **拒绝**：`1142`（`KILL` 为 `1094`） | `denied` | `1142`/`1094` | 不命中 |
| `LOAD DATA ...` | `^load\s+data` | **拒绝**：`1148` | `denied` | `1148` | 不命中 |
| `SELECT ... INTO OUTFILE/DUMPFILE` | 含 `into\s+(out\|dump)file` | **拒绝**：`1142` | `denied` | `1142` | 不命中 |
| 空语句 / 仅注释 | 标准化后为空 | `1065`（Query was empty） | `error` | `1065` | 不命中 |
| 无法识别/语法错误 | 其他 | `1064` | `error` | `1064` | 不命中 |
| 超长 SQL（> 4096 字符） | 长度检查（标准化前） | 截断保存并返回 `1064`（受控拒绝） | `error` | `1064` | 不命中 |

**路由实现约束**：

1. 只做**前缀与关键字**判定，不实现完整 SQL 解析器；所有判定基于 `normalized_sql`
   （小写、空白折叠、字面量替换、去注释）。
2. 判定顺序：长度/空语句 → 写与危险关键字 → 元数据类 → SELECT → 其他受控错误；保证
   带注释或大小写混写的 `DrOp TaBlE` 仍被识别为破坏性操作。
3. 任何分支都**不得**把客户端 SQL 交给真实数据库、`eval`/`exec`、子进程或模板渲染。
4. 写操作被拒绝后连接保持可用，客户端可继续执行其他语句（FR-004/FR-008）。

### 3.4 响应构造

- **结果集**：正确构造 `column count` + `column definition` + `row` + `EOF/OK` 包，字符集
  utf8mb4；字段类型按 3.2 声明；值全部来自固定夹具。
- **返回行数上限**：单次查询最多返回 `max_rows_returned`（默认 100）行；即使伪造表有 120
  行也只返回 100 行，`returned_rows=100`（事件记录实际返回行数，不是表总行数）。
- **模拟延迟**：`simulated_latency_ms` 默认 `[0, 20]` 区间随机（仅影响 `response_ms`，
  不改变内容）；不提供“超长延迟”选项，避免演示卡顿。
- **错误包**：使用 MySQL `ERR` 包结构（`0xFF` + error code + SQLSTATE + 中文/英文消息），
  消息模板见第 5 章；消息中不得回显客户端口令。
- **多行结果稳定性**：行顺序固定（按主键升序），保证重复执行结果一致。

---

## 4. 客户端兼容性

### 4.1 兼容矩阵

| 客户端 | 版本 | 支持情况 | 必需参数/说明 |
| --- | --- | --- | --- |
| MySQL CLI | 8.0.x | ✅ 支持 | `--default-auth=mysql_native_password`；可选 `--ssl-mode=DISABLED` |
| MySQL CLI | 8.4.x | ✅ 支持（有废弃告警） | 同上；8.4 客户端仍随包提供 `mysql_native_password` 客户端插件，但该插件已废弃 |
| PyMySQL | 1.1.x | ✅ 支持（推荐） | 默认走 `mysql_native_password`，无需额外参数；`charset='utf8mb4'` |
| mysqlclient（C 扩展） | 2.2.x | ✅ 支持 | 默认 native password |
| mysql-connector-python | 8.x/9.x | ⚠️ 需配置 | 需 `auth_plugin='mysql_native_password'`、`ssl_disabled=True`，并使用**非预处理**游标（`cursor()` 而非 `cursor(prepared=True)`） |
| Navicat / DBeaver / DataGrip 等 GUI | 各版本 | ⚠️ 视配置 | 若工具强制 `caching_sha2_password` 或强制 SSL，认证会失败；需关闭 SSL 并显式选 native password |
| MySQL CLI | 9.x（未来版本） | ❌ 预计不支持 | `mysql_native_password` 客户端插件被移除，需扩展认证插件（见 4.4） |

### 4.2 握手与认证插件协商机制

1. 服务端 greeting 通告 `auth_plugin_name = mysql_native_password`。
2. 客户端默认**服从**服务端通告的插件；因此多数客户端（含 MySQL CLI 8.0/8.4、PyMySQL）
   会自动走 native password 并成功。
3. 失败发生在客户端**不服从**通告的情况：显式 `--default-auth=caching_sha2_password`、
   工具默认强制 `caching_sha2_password`、或强制 SSL（服务端不声明 `CLIENT_SSL`）。
4. 服务端对客户端发起的其他插件名不做降级尝试，直接返回 `1045` 并记录失败事件
   （`client_info` 中记录客户端请求的插件名，便于排查）。

### 4.3 兼容性规避方式（演示与验收按此执行）

```bash
# MySQL CLI 8.0/8.4：显式指定 native password，关闭 SSL（服务端不支持）
mysql -h 127.0.0.1 -P 3307 -u demo_app -p \
      --default-auth=mysql_native_password --ssl-mode=DISABLED \
      --default-character-set=utf8mb4
```

```python
# PyMySQL（推荐演示客户端：默认兼容 native password）
import pymysql

conn = pymysql.connect(
    host="127.0.0.1", port=3307,
    user="demo_app", password="TEST-ONLY-PASSWORD-PLACEHOLDER",
    charset="utf8mb4", connect_timeout=3, read_timeout=5,
)
```

- GUI 工具：连接设置里关闭 SSL、把“认证插件/默认认证方式”设为 `mysql_native_password`。
- 若客户端仍失败，**以 PyMySQL 作为演示客户端**（已在验收清单中固定），并在答辩中主动
  说明上述限制。

### 4.4 限制说明与扩展路径（答辩风险点，必须主动交代）

**限制**：本版只实现 `mysql_native_password`。

- MySQL 8.4 起 `mysql_native_password` 已被官方标记废弃（服务端插件默认禁用，客户端插件
  仍提供），未来大版本（9.x）将移除；
- 现代客户端与云数据库生态默认偏好 `caching_sha2_password`，部分 GUI 工具可能无法连接；
- 本版不支持 SSL，因此无法走 `caching_sha2_password` 的“完整认证”路径。

**规避（本版已采用）**：固定演示客户端为 PyMySQL 与 MySQL CLI 8.0/8.4（显式 native
password 参数），在 `quickstart.md` 中给出可复制命令；GUI 工具不作为验收对象。

**扩展路径（若评审要求支持 caching_sha2_password）**：

1. 实现 `caching_sha2_password` 的 **fast auth** 分支：服务端缓存 `stage2` 并在
   scramble 校验通过后返回 `fast_auth_success`；首次认证需 `full auth`。
2. `full auth` 需要客户端公开密钥加密口令（RSA）或 TLS 通道；RSA 方式需生成一次性密钥对
   并按协议交换，TLS 方式需为诱饵服务引入自签证书与 `CLIENT_SSL` 能力位。
3. 两项都会增加实现与测试成本，且与本项目“最小协议子集”定位冲突；因此列为**后续增强**，
   不纳入本版验收。若工期不足，还可用总纲“降级路线”：改用隔离网内真实 MySQL 实例 +
   `general_log` 采集，保留同一事件模型与下游分析。

**答辩口径**：明确说“本版只支持 native password，这是刻意收敛的协议子集；演示客户端固定为
PyMySQL/MySQL CLI，并通过参数收敛插件协商；caching_sha2 与 TLS 属于后续增强或降级方案”，
避免被追问时被动。

---

## 5. 错误码约定

| 错误码 | 名称（MySQL 语义） | 触发场景 | 消息模板（不回显口令） |
| --- | --- | --- | --- |
| `1040` | `ER_CON_COUNT_ERROR` | 并发连接超过 `max_connections` | `Too many connections` |
| `1045` | `ER_ACCESS_DENIED_ERROR` | 未知账号、口令错误、客户端请求不支持的认证插件 | `Access denied for user '{username}'@'{host}' (using password: YES)` |
| `1049` | `ER_BAD_DB_ERROR` | `USE` 不存在的库 | `Unknown database '{db}'` |
| `1064` | `ER_PARSE_ERROR` | 语法错误、无法识别语句、SQL 超长 | `You have an error in your SQL syntax; check the manual ... near '{截断前 64 字符}'` |
| `1065` | `ER_EMPTY_QUERY` | 空语句或仅注释 | `Query was empty` |
| `1094` | `ER_NO_SUCH_THREAD` | `KILL` 不存在的连接（本版一律拒绝） | `Unknown thread id: {id}` |
| `1142` | `ER_TABLEACCESS_DENIED_ERROR` | 写操作、DDL、越权对象操作、`INTO OUTFILE` | `{username} command denied to user '{username}'@'{host}' for table '{table}'` |
| `1146` | `ER_NO_SUCH_TABLE` | 查询不存在的伪造表 | `Table '{db}.{table}' doesn't exist` |
| `1148` | `ER_NOT_ALLOWED_COMMAND` | `LOAD DATA LOCAL INFILE` | `The used command is not allowed with this MySQL version` |
| `1295` | `ER_UNSUPPORTED_PS` | `COM_STMT_PREPARE` | `This command is not supported in the prepared statement protocol yet` |
| `2013` | `ER_SERVER_LOST` | 空闲超时、服务端关闭连接 | `Lost connection to MySQL server during query` |
| `1105` | `ER_UNKNOWN_ERROR` | 未预期的内部异常（兜底） | `Unknown error`（详细原因只写运行日志，含 `event_uuid`） |

**约束**：

1. 错误消息中的 `username` 截断 128 字符、`db`/`table` 截断 64 字符，且做控制字符过滤，
   防止日志注入与终端转义注入。
2. 所有错误响应同时产生一条 `status=error/denied/failure` 的事件；事件与客户端看到的
   错误码一致。注意 `attack_log` **没有** `error_code` 列（以 `status` 表达结果类别），
   错误码写入运行日志并进入 `rule_hits`/`alerts` 的 `evidence_summary` 供解释。
3. 错误不得导致进程退出：单连接异常只关闭该连接，服务继续监听（FR-008）。

---

## 6. 上限与超时

| 项 | 默认值 | 上限/行为 |
| --- | --- | --- |
| SQL 长度 | 4096 字符 | 超长截断保存（`sql_truncated=true`），向客户端返回 `1064` |
| 单次返回行数 | 100 行 | 超出部分丢弃，`returned_rows` 记实际返回行数 |
| 用户名长度 | 128 字符 | 超长截断记录，认证判定失败 |
| 客户端信息字符串 | 256 字符 | 截断 |
| 最大连接数 | 200 | 超出返回 `1040` 并写运行日志（不写事件——无会话可归属） |
| 会话空闲超时 | 600 秒 | 超时关闭连接，写 `disconnect` 事件与 `session_status='timeout'` |
| 单条语句处理超时 | 5 秒 | 超时返回 `1105`（受控），写 `status=error`，连接继续可用 |
| 握手超时 | 10 秒 | 未完成握手则关闭连接，运行日志记录来源地址 |
| 认证重试次数 | 每连接 1 次 | 失败即断开（与真实 MySQL 默认行为对齐），不提供重试 |
| 模拟响应延迟 | 0–20 ms | 仅影响 `response_ms` |

---

## 7. 每次交互的事件产生与顺序

### 7.1 正常交互（成功路径）

```text
① TCP accept
   └─ 生成 UUID v4 session_id（36 字符）；写入 sessions(active) + attack_log(connect, status=success)
② 客户端认证成功
   └─ 写入 attack_log(auth, status=success, username=demo_app, credential_test_id=TEST-ONLY-ACC-01)
③ 客户端执行 query（可能多条）
   └─ 每条 COM_QUERY 写一条 attack_log(query, status=success|denied|error,
      sql_statement, normalized_sql, statement_type, returned_rows, response_ms, error_code)
   └─ 触发规则分析：rule_hits / attacker_intent / attacker_profile / alerts / sessions.max_risk_score
④ 客户端 COM_QUIT 或断开
   └─ 写入 attack_log(disconnect, status=success)；更新 sessions(session_status=closed, ended_at)
```

**顺序保证**：同一会话内事件按产生顺序写入，`event_time` 单调不减；时间线展示排序为
`event_time ASC, event_id ASC`（见 `events.md` 与 `api.md` 3.5）。

### 7.2 失败路径

| 场景 | 事件序列 | 会话状态 |
| --- | --- | --- |
| 认证失败 | `connect(success)` → `auth(failure, 1045)` → `disconnect(success)` | `closed` |
| 写操作被拒绝 | `connect` → `auth(success)` → `query(denied, 1142)` → … → `disconnect` | `closed`（连接保持可用） |
| 语法错误 | `… query(error, 1064) …` | 连接继续可用 |
| 空闲超时 | `… disconnect(failure, error_code=2013)` | `timeout` |
| 协议畸形/内部异常 | 尽量写 `query(error, 1105)`（无法解析时只写运行日志）→ `disconnect(failure)` | `error` |
| 连接数超限 | 不写事件（无 session），发 `1040` 并关闭；运行日志记录来源 | — |

### 7.3 记录字段来源

| 事件字段 | 来源 | 落库位置（见 `data-model.md`） |
| --- | --- | --- |
| `session_id` | 连接建立时生成 UUID v4（36 字符），`sessions` 主键 | `sessions.session_id` / `attack_log.session_id` |
| `event_uuid` | 捕获层每条事件独立生成（UUIDv4） | `attack_log.event_uuid`（唯一） |
| `source_ip` | 套接字对端地址（规范化为小写文本） | `attack_log.source_ip`、`sessions.source_ip` |
| `source_port` | 套接字对端端口 | `sessions.source_port`（`attack_log` 无该列） |
| `username` | 握手响应包中的用户名（截断 128 字符） | `attack_log.username` |
| `credential_test_id` | 账号配置或“未知账号”序号标识，**不来自客户端** | `attack_log.credential_test_id` |
| `client_info` | 客户端能力位、客户端名称/版本（若客户端上报）、默认库、字符集；截断 256 字符 | `sessions.client_fingerprint`（会话级） |
| `sql_statement` / `normalized_sql` | 从 `COM_QUERY` 载荷严格 UTF-8 解码后原样保存 / 归一化 | `attack_log.sql_statement` / `normalized_sql` |
| `statement_type` | 由 `normalized_sql` 首关键字派生 | 不落库（规则与接口共用派生函数） |
| `returned_rows` | 实际写入结果集的行数 | `attack_log.returned_rows` |
| `response_ms` | 处理耗时（含模拟延迟） | `attack_log.response_ms` |
| `status` | 路由与响应构造结果 | `attack_log.status` |
| `error_code` | 路由与响应构造结果（MySQL 错误码） | **不落库**（`attack_log` 无该列）：写运行日志并进入 `evidence_summary` |
| `payload_truncated` | SQL/用户名是否超限截断 | `attack_log.payload_truncated` |

---

## 8. 安全边界（“只记录不执行”）

诱饵协议层是本项目唯一的对外攻击面，以下约束为**红线**：

1. **无真实数据库连接**：诱饵进程不持有任何真实业务数据库的连接串或凭证；伪造数据来自
   本地固定夹具，与采集库的 `fake_*` 表**只读同步**或独立加载。客户端无法通过任何语句
   触达真实库。
2. **SQL 只做字符串处理**：路由只做长度、关键字与前缀判断；不解析执行、不拼接进 SQL、
   不传给任何驱动或子进程。
3. **无命令与文件能力**：不调用 shell、不读写客户端指定路径、不允许 `LOAD DATA`、
   `INTO OUTFILE`、UDF、插件安装、复制协议。
4. **监听边界**：默认 `host=127.0.0.1`；若配置为非回环地址，启动时**拒绝启动**，除非同时
   显式设置 `allow_non_loopback=true` 且来源命中 `allowed_client_cidrs`；启动日志打印监听
   地址与授权范围（FR-009/FR-079）。
5. **不做主动行为**：不反向连接、不做 DNS 解析、不探测、不“反制”、不投递任何内容；对
   畸形报文的唯一反应是受控错误 + 记录（FR-007/FR-080）。
6. **不可信输入处理**：用户名、SQL、客户端信息全部按不可信数据对待：长度截断、控制字符
   过滤、UTF-8 严格解码、日志转义；绝不写入运行日志中的可执行片段。
7. **凭据不落库**：账号口令只从环境变量读取并在内存派生摘要；认证事件只写
   `username`/`credential_test_id`；采集库、页面、导出中**不存在**完整口令（FR-081）。
8. **进程权限最小化**：以普通用户运行，不监听 1024 以下端口，不使用 root，不开启调试
   远程端口；`mysql-mimic` 的调试日志不得包含原始认证响应字节。

---

## 9. 配置项契约

配置来源优先级：环境变量 > `.env` > 默认值；`.env.example` 只提供占位符，不含真实口令与密钥。

| 配置键（YAML/代码） | 环境变量 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `honeypot.host` | `HONEYPOT_HOST` | string | `127.0.0.1` | IPv4/IPv6/主机名；非回环需 `allow_non_loopback=true` | 监听地址 |
| `honeypot.port` | `HONEYPOT_PORT` | integer | `3307` | 1–65535，且不得等于真实 MySQL 端口（默认 3306） | 监听端口 |
| `honeypot.service_name` | `HONEYPOT_SERVICE_NAME` | string | `mysql-honeypot` | ≤ 64 字符；多端口演示可写 `mysql-honeypot:3307` | 写入 `sessions.target_service` 的服务标识 |
| `honeypot.server_version` | `HONEYPOT_SERVER_VERSION` | string | `8.4.0-honeypot` | ≤ 32 字符 | 握手通告版本 |
| `honeypot.charset` | `HONEYPOT_CHARSET` | string | `utf8mb4` | 固定 utf8mb4；未识别值拒绝启动 | 字符集 |
| `honeypot.collation_id` | `HONEYPOT_COLLATION_ID` | integer | `255` | `255` 或兼容值 `45` | 握手字符集 ID |
| `honeypot.max_connections` | `HONEYPOT_MAX_CONNECTIONS` | integer | `200` | 1–1000 | 最大并发连接 |
| `honeypot.max_sql_length` | `HONEYPOT_MAX_SQL_LENGTH` | integer | `4096` | 1–65536 字符 | SQL 长度上限（超长截断并报 1064） |
| `honeypot.max_rows_returned` | `HONEYPOT_MAX_ROWS_RETURNED` | integer | `100` | 1–1000 | 单次查询返回行数上限 |
| `honeypot.session_idle_timeout_s` | `HONEYPOT_SESSION_IDLE_TIMEOUT_S` | integer | `600` | 30–86400 | 空闲超时（秒） |
| `honeypot.query_timeout_s` | `HONEYPOT_QUERY_TIMEOUT_S` | integer | `5` | 1–60 | 单语句处理超时 |
| `honeypot.handshake_timeout_s` | `HONEYPOT_HANDSHAKE_TIMEOUT_S` | integer | `10` | 1–60 | 握手超时 |
| `honeypot.simulated_latency_ms` | `HONEYPOT_SIMULATED_LATENCY_MS` | string | `0-20` | `min-max`，0–500，min ≤ max | 模拟延迟区间 |
| `honeypot.allow_non_loopback` | `HONEYPOT_ALLOW_NON_LOOPBACK` | boolean | `false` | `true` 时才允许非回环监听 | 安全开关 |
| `honeypot.allowed_client_cidrs` | `HONEYPOT_ALLOWED_CLIENT_CIDRS` | string（逗号分隔） | `127.0.0.1/32,::1/128` | 合法 CIDR 列表 | 允许的客户端网段 |
| `honeypot.accounts` | —（列表，见下） | list | 2 个预置账号 | 1–5 个 | 诱饵账号定义 |
| `honeypot.accounts[].username` | `HONEYPOT_ACCOUNT_1_USERNAME` | string | `demo_app` | `^[a-z][a-z0-9_]{2,31}$` | 诱饵登录名（虚构） |
| `honeypot.accounts[].password_env` | — | string | `HONEYPOT_ACCOUNT_1_PASSWORD` | 必须是环境变量名 | 口令**只**通过该环境变量注入 |
| `honeypot.accounts[].credential_test_id` | `HONEYPOT_ACCOUNT_1_TEST_ID` | string | `TEST-ONLY-ACC-01` | `^[A-Z0-9_-]{3,64}$` | 写入 auth 事件的合成标识 |
| `honeypot.databases` | — | list | `[honeypot_shop, honeypot_archive]` | 1–3 个，名称 `^[a-z][a-z0-9_]{2,31}$` | 对外伪造库列表 |
| `honeypot.primary_database` | `HONEYPOT_PRIMARY_DATABASE` | string | `honeypot_shop` | 必须存在于 `databases` | 默认库（`users`/`orders`/`config` 所在） |
| `honeypot.strict_utf8` | `HONEYPOT_STRICT_UTF8` | boolean | `true` | — | 非法 UTF-8 时拒绝（`status=error`）而非替换 |
| `honeypot.log_sql_verbatim` | `HONEYPOT_LOG_SQL_VERBATIM` | boolean | `true` | — | 是否原样保存 SQL（关闭时只保存 normalized_sql） |
| `honeypot.enabled` | `HONEYPOT_ENABLED` | boolean | `true` | — | 关闭时诱饵不监听（降级为真实 MySQL 方案的开关） |

**配置校验（启动即失败，不允许带病运行）**：

1. `port` 被占用 → 输出明确错误（含端口与占用提示）并以非 0 退出码退出（FR-074）。
2. `host` 非回环且 `allow_non_loopback=false` → 拒绝启动。
3. `accounts[].password_env` 指向的环境变量不存在或为空 → 拒绝启动，并提示变量名（不打印值）。
4. `max_rows_returned > max_sql_length` 之类的无意义组合不禁止，但需在启动日志提示。
5. 配置日志只打印键与非敏感值；口令、scramble、认证响应字节**永不打印**。

**配置文件示例（`.env.example`，仅占位符）**：

```dotenv
HONEYPOT_HOST=127.0.0.1
HONEYPOT_PORT=3307
HONEYPOT_MAX_CONNECTIONS=200
HONEYPOT_MAX_SQL_LENGTH=4096
HONEYPOT_MAX_ROWS_RETURNED=100
HONEYPOT_SESSION_IDLE_TIMEOUT_S=600
HONEYPOT_ALLOW_NON_LOOPBACK=false
HONEYPOT_ALLOWED_CLIENT_CIDRS=127.0.0.1/32,::1/128
HONEYPOT_ACCOUNT_1_USERNAME=demo_app
HONEYPOT_ACCOUNT_1_PASSWORD=TEST-ONLY-PASSWORD-PLACEHOLDER
HONEYPOT_ACCOUNT_1_TEST_ID=TEST-ONLY-ACC-01
HONEYPOT_ACCOUNT_2_USERNAME=demo_reader
HONEYPOT_ACCOUNT_2_PASSWORD=TEST-ONLY-PASSWORD-PLACEHOLDER
HONEYPOT_ACCOUNT_2_TEST_ID=TEST-ONLY-ACC-02
```

---

## 10. 验收对照

| 编号 | 验收点 | 对应标准 | 验证方式 |
| --- | --- | --- | --- |
| HP-01 | 客户端可完成握手，连续 3 次尝试均成功 | SC-001 | `quickstart.md` 场景 V02 重复 3 次 |
| HP-02 | 预置账号认证成功、未知账号认证失败且两者均入库 | FR-002/SC-002 | 场景 V02/V03，对比 `auth` 事件 |
| HP-03 | `SHOW DATABASES/TABLES`、`DESCRIBE`、`SELECT`、`information_schema` 均返回伪造结构 | FR-003/SC-002 | 场景 V04 |
| HP-04 | 写操作记录语句并返回 1142，连接不中断、诱饵数据不变 | FR-004/FR-010 | 场景 V05 |
| HP-05 | 三张假表内容全部可识别为人工生成，无真实信息 | FR-005/FR-006/SC-007 | 抽样检查 `users/orders/config` 值 |
| HP-06 | 畸形/未知语句返回受控错误且服务可用 | FR-008 | 发送 `FOOBAR` 与超长语句，核对 1064 与后续可用 |
| HP-07 | 诱饵未暴露到公网，非回环监听需显式开关 | FR-009/FR-079 | 配置 `0.0.0.0` 且不设开关 → 启动失败 |
| HP-08 | 客户端兼容：PyMySQL 与 MySQL CLI 8.0/8.4 均能完成认证与查询 | 本文档 4.1 | 场景 V02/V04，记录客户端与参数 |
| HP-09 | 每次交互产生 connect→auth→query→disconnect 事件序列，字段完整 | FR-012/FR-014 | 场景 V06，查 `attack_log` |
| HP-10 | 采集到的 SQL 只存不执行，诱饵进程无真实库凭证 | FR-083 | 代码审查 + 写操作后 `fake_*` 行数不变 |

---

## 11. 变更记录

| 版本 | 日期 | 变更 | 动机 |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-19 | 首次建立协议模拟范围、认证与兼容矩阵（含 native password 限制与扩展路径）、语句路由、错误码、上限、事件顺序、安全边界与配置项契约 | 落实 spec.md 用户故事 1 与 FR-001 至 FR-010，固定答辩风险点口径 |
| 1.1.0 | 2026-11-19 | 按 `data-model.md` 对齐：`session_id` 明确为 UUID v4；7.3 字段落库映射（`source_port`/`client_info`/`error_code`/`statement_type`/`payload_truncated`）；配置新增 `honeypot.service_name`（默认 `mysql-honeypot`，写入 `sessions.target_service`） | 保证协议层产出的事件可直接按数据模型落库，避免字段语义歧义 |
