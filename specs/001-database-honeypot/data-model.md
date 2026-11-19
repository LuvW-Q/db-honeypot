# 数据模型设计：基于 MySQL 协议模拟的数据库蜜罐与攻击行为分析系统

| 项目 | 内容 |
| --- | --- |
| 功能分支 | `001-database-honeypot` |
| 文档类型 | `/speckit-plan` Phase 1 产物（数据模型设计 / data-model） |
| 目标数据库 | MySQL 8.4 LTS，InnoDB，`utf8mb4` / `utf8mb4_0900_ai_ci` |
| 数据库名 | 按环境区分：开发库 `honeypot_dev`、测试库 `honeypot_test`、演示库 `honeypot_demo`（三者结构完全同构，脚本以环境变量传入库名） |
| 编写日期 | 2026-11-19 |
| 状态 | 待评审；评审通过后作为 DDL、Alembic 迁移与种子脚本的唯一依据 |
| 上游输入 | `specs/001-database-honeypot/spec.md`（本文简称 spec）、`docs/数据库蜜罐系统项目总纲_1.1_扩充版.md`（简称总纲）、`.specify/memory/constitution.md`（简称宪法） |

---

## 1. 文档目的与范围

### 1.1 目的

本文档把 spec 中的功能需求与总纲第五章的数据库基线，落实为一套**可直接编写 DDL 与迁移脚本**的 MySQL 8 关系模式，内容包括：

1. 11 张业务表与 4 个分析视图的完整字段定义（含可直接落库的中文 `COMMENT`）、类型、可空性、默认值；
2. 完整性约束矩阵（主键、外键、唯一、检查约束）与约束动机；
3. 四个核心分析视图的完整 `CREATE OR REPLACE VIEW` SQL、查询技术与演示查询；
4. 索引设计与 EXPLAIN 验证方案（含索引建立前后的对比方法与记录模板）；
5. 事务边界、隔离级别、幂等、死锁重试与演示重置顺序；
6. 确定性、可解释的风险评分公式与告警生成/去重规则；
7. 规则种子（R01–R05）参数设计与规则版本管理流程；
8. 四类数据库账号的最小权限矩阵与 GRANT 语句；
9. 迁移、回滚、初始化顺序、数据生命周期与需求映射。

### 1.2 范围

| 纳入本文档 | 不纳入本文档 |
| --- | --- |
| 关系模式（11 表）、约束、索引、视图、种子数据规格、账号权限、迁移与生命周期 | 协议模拟层的报文结构与握手实现（属于实现阶段设计） |
| 评分与告警的确定性算法口径 | 控制台页面结构与前端组件（属于 UI 契约与实现阶段） |
| 事务边界与并发策略 | 具体后端框架的 ORM 模型代码（由迁移脚本与模型代码在实现阶段落地） |
| ER 图（Mermaid 源文件，可版本管理） | 生产级高可用、分库分表、分区表（本项目不做，见第 15 章） |

### 1.3 读者与用法

- **DDL/迁移编写者**：第 2、4、5、12 章即建表依据；字段注释可直接复制进 `COMMENT` 子句。
- **实现工程师**：第 6、8、9 章即分析与告警逻辑的数据库侧契约；第 11 章即连接与权限要求。
- **评审与答辩**：第 3、7、14、15 章即"ER 图—关系模式—约束—索引理由—需求映射"的证据链。

### 1.4 与上游文档的一致性声明

1. 表名、视图名、字段语义沿用总纲第五章基线；字段**类型**按总纲"允许调整的实现细节"条款做了收敛，全部偏离登记在 2.6 节。
2. 与 spec 的对应关系逐条登记在第 14 章；任何未登记的实现偏离视为缺陷。
3. 宪法要求（中文注释落库、3NF、外键声明启用、约束优先于应用校验、最小权限、显式事务、迁移可回滚、ER 图与 DDL 同步）在本文档中逐项落实，落点见第 14 章末尾的"宪法条款落点"表。
4. 本文档是 ER 图的**源文件**（第 3 章 Mermaid 代码块），DDL 变更必须同步修改本文档；两者不一致时先修正文档再合并（宪法原则一、二）。

---

## 2. 设计原则与命名/类型规范

### 2.1 全局技术基线（不可协商）

| 项 | 决策 | 说明 |
| --- | --- | --- |
| 数据库版本 | MySQL 8.4 LTS | `CHECK` 约束自 8.0.16 起强制执行；8.4 默认启用。低于 8.0.16 的实例不得用于本项目 |
| 存储引擎 | InnoDB | 需要事务、行锁、外键；禁用 MyISAM |
| 行格式 | `ROW_FORMAT=DYNAMIC` | 大文本（`MEDIUMTEXT`）与索引前缀更友好 |
| 库默认字符集 | `utf8mb4` | 支持攻击载荷中的任意 Unicode（emoji、四字节字符） |
| 库默认排序规则 | `utf8mb4_0900_ai_ci` | 8.0/8.4 默认；中文与大小写不敏感比较符合展示需求 |
| 标识类字符集 | `ascii`（`ascii_bin` / `ascii_general_ci`） | 见 2.3；UUID 与 IP 不需要多字节，节省索引空间 |
| 时间类型 | `DATETIME(6)`，一律存 UTC | 不使用 `TIMESTAMP`（2038 上限 + 隐式时区转换）；不使用 `DATE` 存时刻 |
| 主键 | `BIGINT UNSIGNED AUTO_INCREMENT` | 除 `sessions`（业务主键 `session_id`）外统一；顺序写入、聚簇索引友好 |
| 外键动作 | `ON UPDATE RESTRICT ON DELETE RESTRICT` | 统一策略；重置/清理按依赖顺序显式删除，不依赖级联（见 8.6、13.2） |
| 标识符命名 | 小写 + 下划线，表名/视图名/列名不超过 64 字符，不使用 MySQL 保留字 | 保留字清单由迁移脚本 CI 校验 |
| 注释 | 每表、每列、每视图、每索引、每约束均有中文说明，DDL 使用 `COMMENT` 落库 | 宪法原则一；索引/约束注释写在迁移脚本注释与本文档中（MySQL 索引支持 `COMMENT`，`CHECK`/`FK` 不支持，靠命名 + 文档） |
| 隔离级别 | 应用写连接 `READ COMMITTED`；分析只读连接 `REPEATABLE READ` | 理由见 8.2 |
| 时区 | 所有连接 `SET SESSION time_zone = '+00:00'` | 见 2.4 |
| 外键检查 | `foreign_key_checks = 1`（默认） | 任何脚本禁止关闭；初始化顺序必须自洽（见 12.3） |

### 2.2 命名规范

| 对象 | 规则 | 示例 |
| --- | --- | --- |
| 表 | 小写上划线，沿用总纲表名（不加前缀） | `attack_log`、`fake_users` |
| 视图 | `v_` + 语义 | `v_session_risk_summary` |
| 主键约束 | `pk_<表名>`（MySQL 中主键名仅为文档规范，实际为 `PRIMARY`） | `pk_sessions` |
| 唯一约束 | `uk_<表名>_<语义>` | `uk_attack_log_event_uuid` |
| 普通索引 | `idx_<表缩写>_<列语义>`；四条规定索引名固定，不得改名 | `idx_log_session_time` |
| 外键 | `fk_<子表缩写>_<父表缩写>` | `fk_hit_log` |
| 检查约束 | `ck_<表名>_<语义>` | `ck_sessions_ended_after_started` |
| 生成列 | `<语义>_<类型>`，并在注释中写明生成表达式用途 | `enabled_rule_code`、`risk_level` |
| 时间列 | `*_at`（时刻）、`*_date`（仅视图中的日期维度） | `started_at`、`first_seen` |
| 布尔列 | `is_<语义>` | `is_read`、`is_synthetic` |
| 计数列 | `*_count` | `request_count` |
| 分数/权重列 | `*_score` / `*_weight` | `risk_score`、`risk_weight` |
| JSON 列 | `*_json` | `parameters_json` |

表缩写约定（用于索引与外键命名）：`log` = `attack_log`，`hit` = `rule_hits`，`alert` = `alerts`，`sess` = `sessions`，`prof` = `attacker_profile`，`intent` = `attacker_intent`，`rule` = `detection_rules`，`fu`/`fo`/`fc` = 三张诱饵表，`audit` = `audit_log`。

### 2.3 字符集与排序规则：为什么 UUID/IP 用 ascii

| 字段类别 | 代表字段 | 字符集 / 排序规则 | 索引空间对比 | 理由 |
| --- | --- | --- | --- | --- |
| UUID 文本 | `sessions.session_id`、`attack_log.event_uuid`、`audit_log.request_id` | `ascii` / `ascii_bin` | 36 字节 vs utf8mb4 最多 144 字节 | UUID 只含 `[0-9a-f-]`，固定 36 字符；`ascii_bin` 比较为字节比较，主键/外键查找最快，二级索引显著更小 |
| IP 文本 | `sessions.source_ip`、`attack_log.source_ip`、`attacker_profile.source_ip` | `ascii` / `ascii_general_ci` | 45 字节 vs utf8mb4 最多 180 字节 | `VARCHAR(45)` 兼容 IPv6 文本（含 `::` 压缩形式）；用 `ascii_general_ci` 而非 `bin`，使 IPv6 十六进制大小写差异不会把同一来源拆成两个画像（写入侧仍统一小写规范化） |
| 去重键 | `alerts.dedup_key` | `ascii` / `ascii_bin` | 60 字节上限 | 由应用按固定格式生成（小写 IP 已规范化），字节比较即可；`bin` 避免任何折叠 |
| 规则编码 | `detection_rules.rule_code`、`rule_hits.rule_code`、`alerts.rule_code` | `ascii` / `ascii_bin` | 3–16 字节 | 编码是稳定对外标识（`R01`），必须严格区分大小写、禁止折叠 |
| 账户/键名 | `fake_users.username`（utf8mb4）、`fake_config.config_key`、`fake_orders.order_no`、`fake_orders.currency`、`audit_log.account_name` | `ascii` / `ascii_bin`（`username` 除外） | — | 机器可读标识；`username` 可能含任意字符，必须 `utf8mb4` |
| 中文/混合文本 | `rule_name`、`description`、`evidence_summary`、`title`、`fake_users.display_name`、`email`、`username` | `utf8mb4` / `utf8mb4_0900_ai_ci` | — | 中文注释、中文证据摘要与攻击者提交的任意字符（不可信输入） |
| 攻击载荷 | `sql_statement`、`normalized_sql` | `utf8mb4` / `utf8mb4_0900_ai_ci` | 不建索引 | 必须无损保存 Unicode 载荷；字段不参与索引，排序规则仅影响检索比较 |

**强制规则**：外键列与父列必须**完全一致**的字符集与排序规则，否则 MySQL 报 `errno 3780`。本文档所有 `session_id`/`rule_code` 的引用列都显式声明 `CHARACTER SET ascii COLLATE ascii_bin`，迁移脚本必须逐列核对。

**不使用 ENUM 的理由**：`ENUM` 的存储值是隐式序号，增删枚举值时序号语义易错，且 `SHOW`/客户端展示与迁移回滚不直观；本设计用 `VARCHAR + CHECK` 表达枚举，与总纲"文本枚举"一致，新增值只需 `ALTER TABLE ... DROP CHECK / ADD CHECK`，语义自解释。

### 2.4 时间与时区约定（UTC）

1. 所有 `DATETIME(6)` 列保存 **UTC 时刻**，微秒精度；不使用 `TIMESTAMP`（隐式时区转换 + 2038 上限）。
2. 客户端连接建立后必须执行 `SET SESSION time_zone = '+00:00'`，应用侧使用带时区的 UTC `datetime` 读写；健康检查断言 `SELECT @@session.time_zone = '+00:00'`。
3. `created_at` 等列的 `DEFAULT CURRENT_TIMESTAMP(6)` 依赖会话时区，因此"连接时区必须为 UTC"是硬约束而非建议；**事件时间（`event_time`、`started_at`、`ended_at`、`triggered_at`）必须由应用显式写入**，不依赖默认值，避免"事件时间由数据库时钟产生"的口径错误。
4. 展示层按需转 `+08:00` 仅用于渲染；导出与日志一律 UTC，并在导出说明中标注时区。
5. 时间线排序口径按 FR-018：`ORDER BY event_time ASC, event_id ASC`（同时间戳由自增序号稳定打破并列）。

### 2.5 类型选择规范

| 语义 | 类型 | 约束 | 依据 |
| --- | --- | --- | --- |
| 风险分 / 意图分 / 权重 | `TINYINT UNSIGNED` | `CHECK (col <= 100)`，权重另加 `>= 1` | 0–100 只需 1 字节；宪法"最小类型" |
| 计数（事件数、行数、毫秒、次数） | `INT UNSIGNED` | 非负由无符号类型保证 | 上限约 42.9 亿，演示规模足够 |
| 端口 | `SMALLINT UNSIGNED` | `CHECK (source_port BETWEEN 1 AND 65535)` | 2 字节 |
| 版本号 | `SMALLINT UNSIGNED` | `CHECK (rule_version >= 1)` | 规则版本不会超过 65535 |
| 布尔 | `TINYINT(1)` | `CHECK (col IN (0,1))` | MySQL `BOOLEAN` 只是 `TINYINT(1)` 别名，显式写便于约束 |
| 金额 | `DECIMAL(12,2)` | `CHECK (amount >= 0)` | 宪法"金额必须精确类型"，禁用 `FLOAT/DOUBLE` |
| 大文本 | `MEDIUMTEXT` | `CHECK (CHAR_LENGTH(col) <= 65535)` | 单条 SQL 上限 64K 字符，防止畸形载荷拖垮存储（宪法原则四"输入防线"） |
| 结构参数 | MySQL 原生 `JSON` | 语法合法性由 JSON 类型保证；结构合法性由应用层 JSON Schema 校验 | 总纲要求单规则内部参数结构可变；原生 JSON 可 `JSON_EXTRACT` 查询且不破坏 3NF（不存放多值业务实体） |
| 短枚举 | `VARCHAR(16)` | `CHECK (col IN (...))` | 见 2.3 |

### 2.6 与总纲字段类型的偏离对照表（含理由）

| 序号 | 总纲定义 | 本文档实现 | 偏离理由 |
| --- | --- | --- | --- |
| 1 | `sessions.session_id` `TEXT` 主键 | `CHAR(36) CHARACTER SET ascii COLLATE ascii_bin` | 会话编号为 UUID v4 文本，长度固定 36；`TEXT` 不能做主键/外键（需前缀长度且不稳定），`CHAR(36)` 定长、可作主键、二级索引空间约为 utf8mb4 的 1/4 |
| 2 | `attack_log.event_uuid` `TEXT` 非空 UNIQUE | `CHAR(36) ascii_bin` UNIQUE | 同上；唯一约束需要可索引的定长列 |
| 3 | `source_ip` `TEXT`（非空、索引） | `VARCHAR(45) ascii_general_ci` | IPv6 文本最长 45 字符；`TEXT` 建索引需前缀长度，无法保证 `attacker_profile.source_ip` 的唯一性语义 |
| 4 | `target_service` `TEXT` | `VARCHAR(64)` | 服务名有明确上限（`mysql-honeypot:13306`），避免无界文本 |
| 5 | `username` `TEXT` 可空 | `VARCHAR(128)`，应用侧超长截断 | 外部输入必须有长度上限（宪法四）；128 覆盖演示用例 |
| 6 | `credential_test_id` `TEXT` 可空 | `VARCHAR(64)` | 测试标识是受控短串，且只保存标识不保存凭据 |
| 7 | `sql_statement` / `normalized_sql` `TEXT` | `MEDIUMTEXT` + `CHECK (CHAR_LENGTH(...) <= 65535)` | `TEXT` 仅 64KB 字节（utf8mb4 下约 16K 字符）不足以容纳长语句；`MEDIUMTEXT` 配合显式长度上限与截断标志（`payload_truncated`）实现"可截断、可追溯" |
| 8 | `parameters_json` `TEXT` + CHECK | 原生 `JSON` | 原生类型在写入时校验 JSON 语法、二进制存储更省空间，并可用 `JSON_EXTRACT` 做校验与展示；不违反"不把多值实体塞 JSON"（每行仅一条规则的参数） |
| 9 | 状态/类型字段 `TEXT` | `VARCHAR(16)` + `CHECK ... IN (...)` | 缩短类型 + 数据库层枚举校验；空值与非法值在入库时被拒绝 |
| 10 | 分数 `INTEGER` 0–100 | `TINYINT UNSIGNED` + `CHECK (<=100)` | 1 字节足够；无符号天然排除负数 |
| 11 | 计数 `INTEGER` 非负 | `INT UNSIGNED` | 无符号即非负，少一条 CHECK |
| 12 | 时间 `DATETIME` | `DATETIME(6)`，UTC | 需微秒精度区分高频事件；统一 UTC 满足 FR-018 |
| 13 | `event_id`/`attacker_id`/`rule_id`/`intent_id` `INTEGER` | `BIGINT UNSIGNED AUTO_INCREMENT` | 日志表是增长最快的表，预留空间；所有外键引用列同步为 `BIGINT UNSIGNED` |
| 14 | `rule_hits` 需记录"得分" | 合并为 `risk_weight` 快照列 | 本设计计分口径为"按 `rule_code` 去重后取权重之和"，单次命中的计分贡献**恒等于**当时的 `risk_weight`，另设同义"得分"列会造成双写不一致；用一列表述并在 9 章固定公式 |
| 15 | `enabled` `BOOLEAN` | `TINYINT(1)` + `CHECK (enabled IN (0,1))` | MySQL 的 `BOOLEAN` 即 `TINYINT(1)`，显式写法便于约束与迁移 |
| 16 | `event_type` 允许"connect auth query disconnect 等" | 固定四类 `connect/auth/query/disconnect` | 无法识别的语句与畸形报文归入 `query` 且 `status='error'`，避免枚举无界；语义仍满足 FR-008/FR-013 |
| 17 | 总纲无 `audit_log` 表 | **新增第 11 张表 `audit_log`（仅追加审计表）** | 宪法原则三要求"关键写操作必须记录审计信息，审计表仅追加、业务账号禁止修改删除"；spec 未列该表，故作为受控新增并登记（映射见第 14 章） |
| 18 | 总纲未定义告警去重支撑列 | `alerts` 增加 `dedup_key`、`first_seen_at`、`last_seen_at`、`occurrence_count`、`latest_hit_id`、`title`、`updated_at` | FR-029/FR-059 要求去重键与重复触发稳定；仅靠 `created_at` 无法表达"重复触发不新增行"，必须显式记录首末时间与次数 |
| 19 | 总纲未定义截断标志 | `attack_log.payload_truncated` | FR-020/边界情况要求超长载荷"截断或拒绝并记录"，需要可查询的截断标志 |
| 20 | 总纲未定义客户端特征 | `sessions.client_fingerprint` | FR-012/FR-016 要求记录客户端特征；以脱敏摘要形式保存，避免存储可识别个人的原始信息 |
| 21 | 总纲未定义画像失败计数/等级 | `attacker_profile.total_auth_failures`、生成列 `risk_level`、`last_calculated_at` | 爆破意图需要失败次数口径；等级由分数生成列保证"分数—等级"永不漂移；重算时间便于可解释性 |
| 22 | 总纲未定义命中快照列 | `rule_hits.rule_code`、`rule_hits.intent_type`、`rule_hits.rule_version`、`rule_hits.risk_weight` | FR-028/FR-052 要求快照；意图与权重快照使意图分、画像分可在规则改版后仍按历史口径复算 |
| 23 | 总纲未定义复核唯一性 | `uk_attack_log_event_session`、`uk_rule_hits_event_rule_version`、`uk_alerts_dedup_key`、`uk_attacker_intent_attacker_type`、`uk_detection_rules_code_version`、`uk_detection_rules_enabled_code` | FR-023/024/026/041/059 要求幂等与唯一性；最后一项用生成列保证"同一规则至多一个启用版本"，防止分析时出现并列启用版本 |
| 24 | 外键未指定动作 | 全部 `ON UPDATE RESTRICT ON DELETE RESTRICT` | 蜜罐数据不可恢复，禁止级联删除误伤证据；重置用显式事务按依赖顺序删除（FR-040） |
| 25 | 索引仅定义四条复合索引 | 保留四条规定索引，补充必要的 FK 索引、唯一索引与 2 条查询索引 | 每条补充索引在第 7 章逐条给出目标查询与理由，禁止无依据堆叠 |

### 2.7 DDL 标准写法范例

以下 `detection_rules` 建表语句同时是**命名、注释、约束、索引、字符集的写法模板**，其余 10 张表必须保持同一风格：

```sql
CREATE DATABASE IF NOT EXISTS honeypot_dev
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE detection_rules (
  rule_id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
                       COMMENT '规则行编号；每行代表一条规则的一个版本',
  rule_code            VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
                       COMMENT '稳定规则编码（R01-R05），跨版本不变，禁止复用',
  rule_name            VARCHAR(100) NOT NULL
                       COMMENT '规则显示名称，如“短时高频连接扫描”',
  rule_type            VARCHAR(16) NOT NULL
                       COMMENT '规则类型枚举：frequency 频率统计 / keyword 关键词 / sequence 序列 / volume 体量',
  intent_type          VARCHAR(16) NOT NULL
                       COMMENT '命中后归属的攻击意图：scanning/bruteforce/recon/data_dump/destructive',
  parameters_json      JSON NOT NULL
                       COMMENT '单条规则内部的阈值与时间窗口参数，结构见 data-model.md 第 10 章',
  risk_weight          TINYINT UNSIGNED NOT NULL
                       COMMENT '命中计入的风险权重 1-100；按 rule_code 去重后求和',
  rule_version         SMALLINT UNSIGNED NOT NULL DEFAULT 1
                       COMMENT '规则版本号，从 1 递增；与 rule_code 复合唯一',
  enabled              TINYINT(1) NOT NULL DEFAULT 1
                       COMMENT '是否参与检测：1 启用 / 0 停用；同一 rule_code 至多一个启用版本',
  enabled_rule_code    VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin
                       GENERATED ALWAYS AS (CASE WHEN enabled = 1 THEN rule_code ELSE NULL END) STORED
                       COMMENT '生成列：启用时等于 rule_code，停用时为 NULL；用于唯一约束保证同一规则至多一个启用版本',
  description          VARCHAR(500) NULL
                       COMMENT '规则说明、阈值依据与已知误报，供管理员与答辩解释使用',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                       COMMENT '创建时间（UTC）',
  updated_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
                       COMMENT '最近更新时间（UTC）',
  PRIMARY KEY (rule_id),
  UNIQUE KEY uk_detection_rules_code_version (rule_code, rule_version)
    COMMENT '同一编码的版本号唯一，规则版本不可覆盖',
  UNIQUE KEY uk_detection_rules_enabled_code (enabled_rule_code)
    COMMENT '同一 rule_code 至多一个启用版本，避免分析时出现并列启用版本',
  KEY idx_detection_rules_intent (intent_type, enabled, rule_code)
    COMMENT '按意图列出可用规则，供分析层与规则管理页使用',
  CONSTRAINT ck_detection_rules_rule_type
    CHECK (rule_type IN ('frequency', 'keyword', 'sequence', 'volume')),
  CONSTRAINT ck_detection_rules_intent_type
    CHECK (intent_type IN ('scanning', 'bruteforce', 'recon', 'data_dump', 'destructive')),
  CONSTRAINT ck_detection_rules_risk_weight
    CHECK (risk_weight BETWEEN 1 AND 100),
  CONSTRAINT ck_detection_rules_rule_version
    CHECK (rule_version >= 1),
  CONSTRAINT ck_detection_rules_enabled
    CHECK (enabled IN (0, 1))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci
  ROW_FORMAT = DYNAMIC
  COMMENT = '检测规则配置表：一行一条规则的一个版本；分析层只执行 enabled=1 的版本，历史命中保留命中时的版本与权重快照';
```

写法约定：

1. 每个列定义一列，`COMMENT` 紧贴类型之后，便于审阅与 `SHOW CREATE TABLE` 输出可读。
2. 约束命名统一使用 `CONSTRAINT <name> CHECK/PRIMARY/UNIQUE/FOREIGN KEY`；`CHECK` 表达式中的枚举值与第 4 章字段表完全一致。
3. 索引统一在列定义之后集中声明，并用 `COMMENT` 说明目标查询。
4. 表尾固定 `ENGINE/DEFAULT CHARSET/COLLATE/ROW_FORMAT/COMMENT` 五项。

---

## 3. ER 图

### 3.1 Mermaid erDiagram（11 张表）

> 说明：图中 `||--o{` 为强制一对多识别关系（由数据库外键保证）；`}o..o{` 为**逻辑聚合关系**（按 `source_ip` 归集画像，不是外键，属于文档化的一致性约定，见 4.3）。`audit_log` 为独立追加表，不与业务表建外键。

```mermaid
erDiagram
    sessions {
        char36 session_id PK "会话编号 UUID"
        varchar45 source_ip "来源地址"
        smallint source_port "来源端口"
        varchar64 target_service "诱饵服务"
        datetime6 started_at "开始时间 UTC"
        datetime6 ended_at "结束时间 UTC"
        varchar16 session_status "状态枚举"
        int request_count "事件计数"
        tinyint max_risk_score "最高风险分"
    }

    attack_log {
        bigint event_id PK "事件序号"
        char36 event_uuid UK "幂等键"
        char36 session_id FK "所属会话"
        varchar16 event_type "事件类型"
        varchar45 source_ip "来源地址"
        varchar128 username "用户名"
        mediumtext sql_statement "原始 SQL"
        datetime6 event_time "事件时间 UTC"
        int returned_rows "返回行数"
        varchar16 status "处理结果"
    }

    detection_rules {
        bigint rule_id PK "规则行编号"
        varchar16 rule_code UK "规则编码"
        varchar16 rule_type "规则类型"
        varchar16 intent_type "目标意图"
        json parameters_json "阈值参数"
        tinyint risk_weight "风险权重"
        smallint rule_version UK "版本号"
        tinyint enabled "是否启用"
    }

    rule_hits {
        bigint hit_id PK "命中编号"
        bigint event_id FK "命中事件"
        char36 session_id FK "命中会话"
        bigint rule_id FK "命中规则"
        varchar16 rule_code "编码快照"
        varchar16 intent_type "意图快照"
        smallint rule_version "版本快照"
        tinyint risk_weight "权重快照"
        varchar1024 evidence_summary "证据摘要"
        datetime6 triggered_at "命中时间 UTC"
    }

    alerts {
        bigint alert_id PK "告警编号"
        varchar160 dedup_key UK "去重键"
        char36 session_id FK "关联会话"
        bigint attacker_id FK "关联画像"
        bigint rule_id FK "触发规则"
        bigint latest_hit_id FK "最新证据命中"
        varchar16 alert_type "告警类型"
        varchar8 severity "等级"
        datetime6 first_seen_at "首次触发 UTC"
        datetime6 last_seen_at "最近触发 UTC"
        int occurrence_count "触发次数"
        tinyint is_read "已读标记"
    }

    attacker_profile {
        bigint attacker_id PK "画像编号"
        varchar45 source_ip UK "聚合键 IP"
        datetime6 first_seen "首次出现 UTC"
        datetime6 last_seen "最近出现 UTC"
        int total_connections "累计连接数"
        int total_auth_attempts "累计认证尝试"
        int total_queries "累计查询数"
        tinyint risk_score "风险分"
        varchar16 risk_level "风险等级生成列"
    }

    attacker_intent {
        bigint intent_id PK "意图编号"
        bigint attacker_id FK "所属画像"
        varchar16 intent_type UK "意图类型"
        tinyint intent_score "意图分"
        int evidence_count "证据计数"
        datetime6 first_detected_at "首次识别 UTC"
        datetime6 last_detected_at "最近识别 UTC"
    }

    fake_users {
        bigint id PK "诱饵用户编号"
        varchar64 username UK "虚构账号"
        varchar120 email UK "虚构邮箱"
        varchar32 phone "虚构手机号"
        varchar120 password_hash "TEST-ONLY 伪哈希"
        tinyint is_synthetic "合成标记"
    }

    fake_orders {
        bigint order_id PK "诱饵订单编号"
        varchar32 order_no UK "虚构订单号"
        bigint user_id FK "所属诱饵用户"
        decimal amount "虚构金额"
        varchar16 order_status "订单状态"
    }

    fake_config {
        bigint config_id PK "诱饵配置编号"
        varchar64 config_key UK "配置键"
        varchar512 config_value "TEST-ONLY 无效值"
        varchar32 category "配置分类"
        tinyint is_invalid "无效标记"
    }

    audit_log {
        bigint audit_id PK "审计编号"
        datetime6 occurred_at "发生时间 UTC"
        varchar64 account_name "数据库账号"
        varchar32 operation "操作类型"
        varchar16 result "结果"
        char36 request_id "关联请求编号"
    }

    sessions ||--o{ attack_log : "包含事件"
    sessions ||--o{ rule_hits : "关联命中并校验同源"
    sessions ||--o{ alerts : "关联告警"
    attack_log ||--o{ rule_hits : "触发命中"
    detection_rules ||--o{ rule_hits : "被命中(版本快照)"
    detection_rules ||--o{ alerts : "触发规则"
    rule_hits ||--o{ alerts : "作为证据"
    attacker_profile ||--o{ attacker_intent : "拥有意图"
    attacker_profile ||--o{ alerts : "产生告警"
    attacker_profile }o..o{ sessions : "按 source_ip 逻辑聚合(非外键)"
    fake_users ||--o{ fake_orders : "拥有订单"
```

### 3.2 关系、基数与实现方式

| 序 | 关系 | 基数 | 实现方式 | 说明 |
| --- | --- | --- | --- | --- |
| R1 | `sessions` → `attack_log` | 1 : 0..N | 外键 `fk_log_session(session_id)` | 一个会话包含连接、认证、多条查询、断开等事件；会话删除受 `RESTRICT` 保护 |
| R2 | `attack_log` → `rule_hits` | 1 : 0..N | 复合外键 `fk_hit_log(event_id, session_id)` | 一条事件可命中多条规则；复合外键同时保证"命中的事件与会话来自同一会话"（总纲第五章"扩充 实体关系和数据一致性"要求） |
| R3 | `sessions` → `rule_hits` | 1 : 0..N | 外键 `fk_hit_session(session_id)` | 提供独立引用完整性与更快定位"会话证据"；与 R2 冗余但错误定位更清晰（见 5.2 说明） |
| R4 | `detection_rules` → `rule_hits` | 1 : 0..N | 外键 `fk_hit_rule(rule_id)` | 命中行保存 `rule_version`/`risk_weight`/`intent_type` 快照，规则改版不回写历史 |
| R5 | `sessions` → `alerts` | 1 : 0..N | 外键 `fk_alert_session(session_id)` | 告警必须能回到具体会话 |
| R6 | `attacker_profile` → `alerts` | 1 : 0..N | 外键 `fk_alert_attacker(attacker_id)` | 告警按来源画像归集；画像先于告警写入（事务顺序见 8.3） |
| R7 | `detection_rules` → `alerts` | 1 : 0..N | 外键 `fk_alert_rule(rule_id)` | 告警记录触发规则；`rule_code` 另存快照便于展示与视图连接 |
| R8 | `rule_hits` → `alerts` | 1 : 0..N | 外键 `fk_alert_latest_hit(latest_hit_id)` | 证据关联：告警指向最近一次触发该去重键的命中行，实现 FR-057 的"可定位命中记录" |
| R9 | `attacker_profile` → `attacker_intent` | 1 : 0..N | 外键 `fk_intent_profile(attacker_id)` + `UNIQUE(attacker_id, intent_type)` | 一行一条意图；同一攻击者可同时拥有 5 类意图，但每类仅一行（FR-024） |
| R10 | `attacker_profile` ⋯ `sessions` | 1 : 0..N（逻辑） | **无外键**，按 `source_ip` 等值聚合 | 画像的聚合键是来源地址（FR-017/FR-050 口径），会话先于画像写入，且画像可因清理独立存在；因此不建 FK，改由视图与写入事务保证一致（权衡见第 15 章序号 4，一致性校验见 12.6 V14） |
| R11 | `fake_users` → `fake_orders` | 1 : 0..N | 外键 `fk_fake_orders_user(user_id)` | 诱饵表仅对外展示，与观测数据物理隔离（同库不同表，禁止与业务表混存） |
| R12 | `audit_log` | 独立 | 无外键 | 审计表仅追加；不对业务表建外键，避免被 `RESTRICT` 阻塞或产生跨表锁 |

### 3.3 实体关系对设计的约束结论

1. **中心事实表**是 `sessions` 与 `attack_log`；所有派生结果（命中、告警、意图、画像）都必须能沿 `session_id → event_id → rule_id → rule_version` 回溯到原始证据。
2. **不把多值意图写入画像**（FR-025）：`attacker_profile` 无任何意图列表列，主要意图由 `v_attacker_profile_summary` 计算。
3. **不建立 `sessions → attacker_profile` 外键**：画像行由同来源的首次事件创建、后续事件更新，若会话强依赖画像则连接事件必须先建画像，与"先有会话再有画像"的事务顺序冲突；一致性由 8.3 的固定写入顺序 + 视图聚合校验保证。

---

## 4. 实体关系说明与数据字典

> 阅读约定：
> - "可空"列中 `否` 表示 `NOT NULL`；
> - "约束/键"列中 `PK` 主键、`FK` 外键、`UK` 唯一、`CK` 检查约束（约束名见第 5 章）；
> - "注释"列的文字即 DDL 中 `COMMENT '...'` 的内容，可直接复制；
> - 所有时间列均为 `DATETIME(6)` 且保存 UTC。

### 4.1 `sessions`（会话主表）

**用途与数据来源**：一次诱饵连接一行。由协议捕获层在 TCP 连接建立（MySQL 握手开始）时生成 UUID v4 并写入，在认证、查询、断开事件中更新计数与状态。是 `attack_log`、`rule_hits`、`alerts` 的归集根。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `session_id` | `CHAR(36) CHARACTER SET ascii COLLATE ascii_bin` | 否 | 无 | PK | 会话唯一标识，UUID v4 文本（36 字符），由捕获层在连接建立时生成，全局唯一且不可复用 |
| `source_ip` | `VARCHAR(45) CHARACTER SET ascii COLLATE ascii_general_ci` | 否 | 无 | 索引 | 测试端来源地址，IPv4 或 IPv6 文本规范形式（如 192.0.2.10、2001:db8::10），写入前统一小写 |
| `source_port` | `SMALLINT UNSIGNED` | 是 | `NULL` | CK | 测试端源端口 1-65535；报文缺失或 NAT 重写导致不可知时为 NULL |
| `target_service` | `VARCHAR(64)` | 否 | `'mysql-honeypot'` | — | 被访问的诱饵服务标识，形如 mysql-honeypot:13306，用于多端口演示时区分诱饵实例 |
| `client_fingerprint` | `VARCHAR(255)` | 是 | `NULL` | — | 客户端特征摘要（协议版本、客户端能力标志等），已脱敏，不保存原始可识别信息 |
| `started_at` | `DATETIME(6)` | 否 | 无 | — | 会话开始时间（UTC），由捕获层显式写入，不使用数据库默认时间 |
| `ended_at` | `DATETIME(6)` | 是 | `NULL` | CK | 会话结束时间（UTC）；未结束或异常断连未回填时为 NULL；不得早于开始时间 |
| `session_status` | `VARCHAR(16)` | 否 | `'active'` | CK | 会话状态枚举：active 进行中 / closed 正常断开 / timeout 空闲超时 / error 协议错误终止 |
| `request_count` | `INT UNSIGNED` | 否 | `0` | — | 会话内事件计数（connect、auth、query、disconnect 均计 1）；由事件写入事务原子自增 |
| `max_risk_score` | `TINYINT UNSIGNED` | 否 | `0` | CK | 本会话最高风险分 0-100，写入事件时以 GREATEST 更新；权威值由 v_session_risk_summary 重算校验 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行创建时间（UTC），由数据库默认值填充，仅用于运维排查 |
| `updated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)`（`ON UPDATE`） | — | 行最近更新时间（UTC），用于排查计数是否停滞 |

索引与约束：

| 名称 | 类型 | 列 | 注释 |
| --- | --- | --- | --- |
| `PRIMARY` | 主键 | `session_id` | 会话主键；所有子表外键目标 |
| `idx_sessions_source_started` | 普通 | `source_ip, started_at` | 攻击者详情页按来源列出会话（FR-064）；也是画像关联统计的检索入口 |
| `idx_sessions_status_started` | 普通 | `session_status, started_at` | 巡检未关闭会话（active/timeout）并按时序扫描，供超时清理任务使用 |
| `idx_sessions_started` | 普通 | `started_at` | 首页"近 N 天连接数/会话数"按时间范围聚合（FR-062）；会话表行数小，索引维护成本低 |

表注释（`COMMENT`）：`会话主表：一次诱饵连接一行，记录来源、起止时间、状态与事件计数；数据来源为捕获层的连接与断开事件`

### 4.2 `attack_log`（攻击日志 / 标准事件表）

**用途与数据来源**：FR-012 至 FR-018 的标准事件记录。每条连接、认证、查询、断开事件一行；`event_uuid` 为幂等键，保证重复投递不重复入库。SQL 文本是**不可信数据，只存储不执行**。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `event_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 事件序号；全局单调递增，用于同时间戳事件的稳定排序（FR-018） |
| `event_uuid` | `CHAR(36) CHARACTER SET ascii COLLATE ascii_bin` | 否 | 无 | UK | 采集事件幂等键（UUID v4 文本），同一事件重复提交时由唯一约束阻止重复入库并返回已有 event_id |
| `session_id` | `CHAR(36) CHARACTER SET ascii COLLATE ascii_bin` | 否 | 无 | FK | 所属会话编号，引用 sessions.session_id |
| `event_type` | `VARCHAR(16)` | 否 | 无 | CK | 事件类型：connect 连接 / auth 认证 / query 查询或写操作 / disconnect 断开；无法识别的报文归入 query 且 status=error |
| `source_ip` | `VARCHAR(45) CHARACTER SET ascii COLLATE ascii_general_ci` | 否 | 无 | 索引 | 测试端来源地址；与会话行保持一致（写入事务内从会话复制，属受控反规范化，动机见 7.4） |
| `username` | `VARCHAR(128)` | 是 | `NULL` | — | 认证或查询使用的用户名；来自不可信输入，按 128 字符上限截断，超长时置 payload_truncated=1 |
| `credential_test_id` | `VARCHAR(64)` | 是 | `NULL` | — | 合成凭据测试标识（如 synth-auth-003），仅标识测试样本，任何情况下不保存口令明文或可逆凭据 |
| `sql_statement` | `MEDIUMTEXT` | 是 | `NULL` | CK | 原始 SQL 文本，只存储不执行；超过 65535 字符时截断并置 payload_truncated=1 |
| `normalized_sql` | `MEDIUMTEXT` | 是 | `NULL` | CK | 标准化 SQL（字面量替换为占位符、空白折叠、统一大小写）；供规则匹配与去重比较，不参与索引 |
| `event_time` | `DATETIME(6)` | 否 | 无 | 索引 | 事件发生时间（UTC），由捕获层在事件生成时确定并显式写入 |
| `returned_rows` | `INT UNSIGNED` | 否 | `0` | — | 本次查询返回给客户端的行数；非查询事件为 0 |
| `response_ms` | `INT UNSIGNED` | 否 | `0` | — | 模拟响应耗时（毫秒）；受控延迟场景记录实际等待时间 |
| `status` | `VARCHAR(16)` | 否 | 无 | CK | 处理结果枚举：success 成功 / failure 认证失败或模拟失败 / denied 权限不足 / error 协议或语句错误 |
| `payload_truncated` | `TINYINT(1)` | 否 | `0` | CK | 载荷是否被截断：1 表示 SQL 或用户名超过长度上限并按策略截断，便于审计"输入防线"是否生效 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行落库时间（UTC），与 event_time 的差值可用于评估写入延迟 |

索引与约束：

| 名称 | 类型 | 列 | 注释 |
| --- | --- | --- | --- |
| `PRIMARY` | 主键 | `event_id` | 事件主键与同时间戳排序依据 |
| `uk_attack_log_event_uuid` | 唯一 | `event_uuid` | 幂等键（FR-023/FR-041），重复提交的唯一防线 |
| `uk_attack_log_event_session` | 唯一 | `event_id, session_id` | 作为复合外键 `fk_hit_log` 的父索引，保证命中行的事件与会话同源；对主键而言该唯一键不增加新语义，仅为外键目标而设 |
| `idx_log_session_time` | 普通 | `session_id, event_time` | **规定索引 1**：按会话重建事件时间线（FR-034/FR-065） |
| `idx_log_source_time` | 普通 | `source_ip, event_time` | **规定索引 2**：按来源与时间范围查询行为（规则窗口统计、画像检索） |

表注释（`COMMENT`）：`标准事件表：一次连接/认证/查询/断开一行；event_uuid 唯一约束实现采集幂等；SQL 与用户名为不可信数据，只存储不执行`

### 4.3 `attacker_profile`（攻击者画像表）

**用途与数据来源**：按 `source_ip` 聚合的攻击者画像，一行一个来源地址。首次出现时插入，后续事件在同一事务内更新计数、时间与风险分。**不保存多值意图列表**（FR-025）。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `attacker_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 画像编号；被 attacker_intent 与 alerts 引用 |
| `source_ip` | `VARCHAR(45) CHARACTER SET ascii COLLATE ascii_general_ci` | 否 | 无 | UK | 攻击者聚合键（来源地址），唯一；同一来源仅一行画像 |
| `first_seen` | `DATETIME(6)` | 否 | 无 | CK | 该来源首次出现时间（UTC），取首次会话开始时间 |
| `last_seen` | `DATETIME(6)` | 否 | 无 | CK | 该来源最近出现时间（UTC），取最新事件时间 |
| `total_connections` | `INT UNSIGNED` | 否 | `0` | — | 累计连接次数（connect 事件数） |
| `total_auth_attempts` | `INT UNSIGNED` | 否 | `0` | — | 累计认证尝试次数（auth 事件数，含成功与失败） |
| `total_auth_failures` | `INT UNSIGNED` | 否 | `0` | — | 累计认证失败次数（auth 且 status 为 failure/denied），供爆破意图解释 |
| `total_queries` | `INT UNSIGNED` | 否 | `0` | — | 累计 SQL 数量（query 事件数） |
| `risk_score` | `TINYINT UNSIGNED` | 否 | `0` | CK | 来源画像风险分 0-100，按 9.2 公式（按 rule_code 去重取最大权重后求和并封顶）计算 |
| `risk_level` | `VARCHAR(16)` 生成列（`VIRTUAL`） | 否 | 生成 | — | 风险等级生成列：critical 严重(80-100) / high 高(60-79) / medium 中(30-59) / low 低(0-29)；由 risk_score 自动推导，禁止手工写入 |
| `evidence_summary` | `VARCHAR(1024)` | 是 | `NULL` | — | 最近一次计算的证据摘要（命中的规则编码与代表性语句类型），供列表页与答辩解释 |
| `last_calculated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 最近一次风险重算时间（UTC），用于判断画像是否为最新口径 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行创建时间（UTC） |
| `updated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)`（`ON UPDATE`） | — | 行最近更新时间（UTC） |

索引与约束：

| 名称 | 类型 | 列 | 注释 |
| --- | --- | --- | --- |
| `PRIMARY` | 主键 | `attacker_id` | 画像主键 |
| `uk_attacker_profile_source_ip` | 唯一 | `source_ip` | 一个来源一行画像（FR-050 聚合口径） |
| `idx_profile_risk` | 普通 | `risk_score, last_seen` | 攻击者列表按风险分降序、最近时间降序分页；MySQL 8 可对升序索引做反向扫描，无需 DESC 索引 |

表注释（`COMMENT`）：`攻击者画像表：按来源地址聚合的画像，一行一个来源；不保存意图列表，主要意图由 v_attacker_profile_summary 计算`

### 4.4 `attacker_intent`（攻击意图表）

**用途与数据来源**：一行一条攻击者意图（FR-024/FR-049）。命中新证据时更新分数、证据计数与最近识别时间；`(attacker_id, intent_type)` 唯一。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `intent_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 意图记录编号 |
| `attacker_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 所属画像编号，引用 attacker_profile.attacker_id |
| `intent_type` | `VARCHAR(16)` | 否 | 无 | UK+CK | 意图类型：scanning 扫描 / bruteforce 爆破 / recon 踩点 / data_dump 拖库 / destructive 破坏性操作 |
| `intent_score` | `TINYINT UNSIGNED` | 否 | `0` | CK | 该意图累计可信分 0-100，按 9.2 公式（该意图下按 rule_code 去重取最大权重后求和并封顶）计算 |
| `evidence_count` | `INT UNSIGNED` | 否 | `0` | — | 支持该意图的规则命中条数（rule_hits 计数），用于排序与解释 |
| `first_detected_at` | `DATETIME(6)` | 否 | 无 | CK | 首次识别该意图的时间（UTC） |
| `last_detected_at` | `DATETIME(6)` | 否 | 无 | CK | 最近识别该意图的时间（UTC）；主要意图排序的次级键 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行创建时间（UTC） |
| `updated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)`（`ON UPDATE`） | — | 行最近更新时间（UTC） |

索引与约束：

| 名称 | 类型 | 列 | 注释 |
| --- | --- | --- | --- |
| `PRIMARY` | 主键 | `intent_id` | 意图主键 |
| `uk_attacker_intent_attacker_type` | 唯一 | `attacker_id, intent_type` | 每名攻击者每种意图仅一行（FR-024） |
| `idx_intent_type_score` | 普通 | `intent_type, intent_score` | 意图分布统计与"按意图查看攻击者"查询（FR-064） |

表注释（`COMMENT`）：`攻击意图聚合表：一行一条攻击者意图，按画像编号与意图类型复合唯一；命中新证据时更新分数与首末识别时间`

### 4.5 `detection_rules`（检测规则配置表）

**用途与数据来源**：规则由数据库配置（FR-026/FR-027/FR-046/FR-054），一行一条规则的一个版本；分析层只执行 `enabled=1` 的版本，历史命中保留命中时版本与权重快照。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `rule_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 规则行编号；每行代表一个规则版本 |
| `rule_code` | `VARCHAR(16) ascii_bin` | 否 | 无 | UK | 稳定规则编码（R01-R05），跨版本不变，禁止复用 |
| `rule_name` | `VARCHAR(100)` | 否 | 无 | — | 规则显示名称，如"短时高频连接扫描" |
| `rule_type` | `VARCHAR(16)` | 否 | 无 | CK | 规则类型：frequency 频率统计 / keyword 关键词 / sequence 序列 / volume 体量 |
| `intent_type` | `VARCHAR(16)` | 否 | 无 | CK | 命中后归属意图：scanning / bruteforce / recon / data_dump / destructive |
| `parameters_json` | `JSON` | 否 | 无 | — | 单条规则的阈值与时间窗口参数（JSON 对象），结构见第 10 章；不用于保存多值业务实体 |
| `risk_weight` | `TINYINT UNSIGNED` | 否 | 无 | CK | 命中计入的风险权重 1-100；评分时按 rule_code 去重求和 |
| `rule_version` | `SMALLINT UNSIGNED` | 否 | `1` | UK+CK | 版本号，从 1 递增；与 rule_code 复合唯一 |
| `enabled` | `TINYINT(1)` | 否 | `1` | CK | 是否参与检测：1 启用 / 0 停用；同一 rule_code 至多一个启用版本 |
| `enabled_rule_code` | `VARCHAR(16) ascii_bin` 生成列（`STORED`） | 是（停用时为 `NULL`） | 生成 | UK | 生成列：启用时等于 rule_code，停用时为 NULL；唯一约束允许多个 NULL，从而保证同一规则至多一个启用版本 |
| `description` | `VARCHAR(500)` | 是 | `NULL` | — | 规则说明、阈值依据与已知误报，供管理员与答辩解释 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 创建时间（UTC） |
| `updated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)`（`ON UPDATE`） | — | 最近更新时间（UTC） |

索引与约束：见 2.7 完整 DDL。命名清单：`PRIMARY`、`uk_detection_rules_code_version`、`uk_detection_rules_enabled_code`、`idx_detection_rules_intent`。

表注释（`COMMENT`）：`检测规则配置表：一行一条规则的一个版本；分析层只执行 enabled=1 的版本，历史命中保留命中时的版本与权重快照`

### 4.6 `rule_hits`（规则命中表）

**用途与数据来源**：一次规则命中一行（FR-028/FR-052）。写入时保存规则版本、权重与意图的**快照**，使规则改版后历史证据仍可解释。该表是"日志 → 规则 → 证据 → 告警"链路的关键连接点。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `hit_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 命中编号；被 alerts.latest_hit_id 引用 |
| `event_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 命中的事件编号，引用 attack_log.event_id；与 session_id 组成复合外键保证同源 |
| `session_id` | `CHAR(36) ascii_bin` | 否 | 无 | FK | 命中所属会话编号，引用 sessions.session_id |
| `rule_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 命中的规则行编号，引用 detection_rules.rule_id |
| `rule_code` | `VARCHAR(16) ascii_bin` | 否 | 无 | 索引 | 命中时的规则编码快照（R01-R05），便于证据展示、视图聚合而不必回连规则表 |
| `intent_type` | `VARCHAR(16)` | 否 | 无 | CK | 命中时的目标意图快照；意图分与画像分据此按历史口径复算 |
| `rule_version` | `SMALLINT UNSIGNED` | 否 | 无 | UK+CK | 命中时实际采用的规则版本快照 |
| `risk_weight` | `TINYINT UNSIGNED` | 否 | 无 | CK | 命中时的风险权重快照 1-100；本次命中的计分贡献即该值，规则后续调整不影响历史 |
| `evidence_summary` | `VARCHAR(1024)` | 否 | 无 | — | 可解释证据摘要，如"会话内出现 SHOW TABLES 语句"或"5 分钟内认证 9 次、凭据组合 6 组" |
| `triggered_at` | `DATETIME(6)` | 否 | 无 | 索引 | 命中时间（UTC），由分析层写入；与 event_time 可能不同（窗口统计型规则在窗口结束时触发） |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行落库时间（UTC） |

索引与约束：

| 名称 | 类型 | 列 | 注释 |
| --- | --- | --- | --- |
| `PRIMARY` | 主键 | `hit_id` | 命中主键 |
| `uk_rule_hits_event_rule_version` | 唯一 | `event_id, rule_id, rule_version` | 同一事件在同一规则版本下只保留一条命中，重复分析不重复计数（边界情况要求） |
| `idx_hit_event_session` | 普通 | `event_id, session_id` | 复合外键 `fk_hit_log` 所需的子表索引（同源校验） |
| `idx_hit_rule_time` | 普通 | `rule_id, created_at` | **规定索引 4**：统计规则命中趋势（FR-034）；同时作为 `fk_hit_rule` 的索引 |
| `idx_hit_session_time` | 普通 | `session_id, triggered_at` | 会话详情页按时间展示规则证据（FR-064）；同时作为 `fk_hit_session` 的索引 |

表注释（`COMMENT`）：`规则命中表：一次命中一行，保存命中时的规则版本、权重与意图快照；与攻击日志、会话、规则构成可回溯证据链`

### 4.7 `alerts`（告警表）

**用途与数据来源**：爆破、拖库、破坏性操作首次命中即生成告警（FR-055/FR-059/FR-060）。`dedup_key` 唯一，重复触发只累加 `occurrence_count` 并更新 `last_seen_at`，不插入重复行。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `alert_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 告警编号 |
| `dedup_key` | `VARCHAR(160) ascii_bin` | 否 | 无 | UK | 告警去重键，格式 <rule_code>:<source_ip>:<UTC 日期>，如 R05:192.0.2.10:2026-11-19；唯一约束保证同一触发条件同日只有一条告警 |
| `session_id` | `CHAR(36) ascii_bin` | 否 | 无 | FK | 关联会话编号，引用 sessions.session_id；取首次触发告警的会话 |
| `attacker_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 关联攻击者画像编号，引用 attacker_profile.attacker_id |
| `rule_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 首次触发告警的规则行编号，引用 detection_rules.rule_id |
| `rule_code` | `VARCHAR(16) ascii_bin` | 否 | 无 | 索引 | 触发规则编码快照，供列表展示与视图聚合，避免回连规则表 |
| `latest_hit_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 最近一次触发该告警的规则命中编号，引用 rule_hits.hit_id；证据可定位（FR-057） |
| `alert_type` | `VARCHAR(16)` | 否 | 无 | CK | 告警类型枚举：bruteforce 爆破 / data_dump 拖库 / destructive 破坏性操作；仅这三类意图生成告警（9.4） |
| `severity` | `VARCHAR(8)` | 否 | 无 | CK | 告警等级：low 低 / medium 中 / high 高 / critical 严重；映射规则见 9.4 |
| `title` | `VARCHAR(200)` | 否 | 无 | — | 告警标题（中文），如"疑似拖库：来自 192.0.2.10 的会话累计返回 1200 行" |
| `evidence_summary` | `VARCHAR(1024)` | 否 | 无 | — | 告警证据摘要：规则编码、命中时间、代表性语句与统计值，禁止只给标签（FR-051/FR-060） |
| `first_seen_at` | `DATETIME(6)` | 否 | 无 | CK | 首次触发时间（UTC）；插入告警时写入 |
| `last_seen_at` | `DATETIME(6)` | 否 | 无 | CK | 最近触发时间（UTC）；重复触发时以 GREATEST 更新 |
| `occurrence_count` | `INT UNSIGNED` | 否 | `1` | CK | 触发次数；首次为 1，重复触发原子自增 |
| `is_read` | `TINYINT(1)` | 否 | `0` | CK | 已读标记：0 未读 / 1 已读；已读更新是独立写操作（FR-058） |
| `read_at` | `DATETIME(6)` | 是 | `NULL` | CK | 标记已读的时间（UTC）；未读时为 NULL；与 is_read 的一致性由检查约束保证 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行创建（首次告警）时间（UTC），等于 first_seen_at 的落库时刻 |
| `updated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)`（`ON UPDATE`） | — | 行最近更新时间（UTC），重复触发与已读操作都会更新 |

索引与约束：

| 名称 | 类型 | 列 | 注释 |
| --- | --- | --- | --- |
| `PRIMARY` | 主键 | `alert_id` | 告警主键 |
| `uk_alerts_dedup_key` | 唯一 | `dedup_key` | 去重键唯一（FR-059）：重复触发更新同一条告警 |
| `idx_alert_level_time` | 普通 | `severity, created_at` | **规定索引 3**：筛选近期高等级告警（FR-034/FR-066），按等级等值 + 时间范围检索 |
| `idx_alert_type_time` | 普通 | `alert_type, created_at` | 告警类型筛选（FR-056/FR-066） |
| `idx_alert_session_time` | 普通 | `session_id, created_at` | 会话时间线中的告警关联；同时作为 `fk_alert_session` 的索引 |
| `idx_alert_attacker_time` | 普通 | `attacker_id, created_at` | 攻击者详情页的告警列表；同时作为 `fk_alert_attacker` 的索引 |
| `idx_alert_read_time` | 普通 | `is_read, created_at` | 未读告警筛选与"最近未读"默认排序；告警量小，维护成本可接受 |
| `idx_alert_latest_hit` | 普通 | `latest_hit_id` | 证据外键索引（`fk_alert_latest_hit`），并提供"按命中反查告警"的能力 |

表注释（`COMMENT`）：`告警表：爆破/拖库/破坏性操作首次命中生成，dedup_key 唯一约束实现同日同规则同来源去重；重复触发更新次数与最近时间`

### 4.8 `fake_users`（诱饵用户表）

**用途与数据来源**：诱饵层对外返回的虚构用户数据（FR-005/FR-006/FR-085），与观测数据物理隔离于同库不同表，不参与任何检测计算。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 诱饵用户编号 |
| `username` | `VARCHAR(64)` | 否 | 无 | UK | 虚构诱饵账号，形如 demo_user_01，明显非真实人员 |
| `email` | `VARCHAR(120)` | 否 | 无 | UK | 虚构邮箱，统一使用 example.test 保留域名 |
| `phone` | `VARCHAR(32)` | 否 | 无 | — | 虚构手机号，统一使用 199-0000-00NN 号段，明显非真实号码 |
| `password_hash` | `VARCHAR(120)` | 否 | 无 | CK | 不可用的伪哈希，必须以 TEST-ONLY$ 开头（检查约束强制），不参与任何真实认证 |
| `display_name` | `VARCHAR(64)` | 否 | 无 | — | 虚构显示名，形如 演示用户01 |
| `is_synthetic` | `TINYINT(1)` | 否 | `1` | CK | 合成标记，检查约束强制恒为 1，保证所有诱饵数据可识别为人工生成 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行创建时间（UTC） |

索引与约束：`PRIMARY`、`uk_fake_users_username`、`uk_fake_users_email`。

表注释（`COMMENT`）：`诱饵用户表：完全虚构的展示数据，仅用于诱饵层返回；password_hash 为不可用伪哈希，检查约束强制 TEST-ONLY$ 前缀`

### 4.9 `fake_orders`（诱饵订单表）

**用途与数据来源**：构造普通业务数据与"大结果集"演示（FR-085），并由外层键关联 `fake_users`。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `order_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 诱饵订单编号 |
| `order_no` | `VARCHAR(32) ascii_bin` | 否 | 无 | UK | 虚构订单号，形如 FAKE-202611-00001 |
| `user_id` | `BIGINT UNSIGNED` | 否 | 无 | FK | 所属诱饵用户编号，引用 fake_users.id |
| `amount` | `DECIMAL(12,2)` | 否 | 无 | CK | 虚构订单金额（元），精确小数，非负 |
| `currency` | `CHAR(3) ascii_bin` | 否 | `'CNY'` | — | 币种代码，默认 CNY |
| `order_status` | `VARCHAR(16)` | 否 | `'paid'` | CK | 订单状态：pending 待支付 / paid 已支付 / shipped 已发货 / cancelled 已取消 / refunded 已退款 |
| `remark` | `VARCHAR(200)` | 是 | `NULL` | — | 虚构备注，用于构造更真实的大结果集响应 |
| `is_synthetic` | `TINYINT(1)` | 否 | `1` | CK | 合成标记，强制恒为 1 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 虚构下单时间（UTC） |

索引与约束：`PRIMARY`、`uk_fake_orders_order_no`、`idx_fake_orders_user (user_id, created_at)`（外键索引 + 按用户查订单）。

表注释（`COMMENT`）：`诱饵订单表：完全虚构的业务数据，含 120 条种子记录用于构造大结果集；仅用于诱饵层展示，不参与检测`

### 4.10 `fake_config`（诱饵配置表）

**用途与数据来源**：提供"看似敏感但完全无效"的连接串与密钥（FR-005/FR-006/FR-085）。检查约束强制所有值以 `TEST-ONLY` 开头，从数据库层杜绝真实密钥混入。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `config_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 诱饵配置编号 |
| `config_key` | `VARCHAR(64) ascii_bin` | 否 | 无 | UK | 配置项键名，如 db.primary.connection_string |
| `config_value` | `VARCHAR(512)` | 否 | 无 | CK | 无效的诱饵值，必须以 TEST-ONLY 开头；连接串只指向本机无效端口，密钥为占位串 |
| `category` | `VARCHAR(32)` | 否 | 无 | CK | 配置分类：database 数据库 / mail 邮件 / api 第三方接口 / storage 对象存储 |
| `description` | `VARCHAR(200)` | 是 | `NULL` | — | 配置项说明（中文），说明这是测试数据 |
| `is_invalid` | `TINYINT(1)` | 否 | `1` | CK | 无效标记，强制恒为 1 |
| `created_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | — | 行创建时间（UTC） |
| `updated_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)`（`ON UPDATE`） | — | 行最近更新时间（UTC） |

索引与约束：`PRIMARY`、`uk_fake_config_config_key`。

表注释（`COMMENT`）：`诱饵配置表：看似敏感但完全无效的配置项；检查约束强制 config_value 以 TEST-ONLY 开头，禁止真实凭据入库`

### 4.11 `audit_log`（审计日志表，仅追加）

**用途与数据来源**：记录关键写操作（重置、规则变更、告警已读、导出、迁移、失败登录等）的审计留痕（宪法原则三）。`app_rw` 仅有 `INSERT`/`SELECT` 权限，无 `UPDATE`/`DELETE`，从权限层保证仅追加。

| 列名 | 类型 | 可空 | 默认 | 约束/键 | 注释 |
| --- | --- | --- | --- | --- | --- |
| `audit_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | 否 | 自增 | PK | 审计记录编号 |
| `occurred_at` | `DATETIME(6)` | 否 | `CURRENT_TIMESTAMP(6)` | 索引 | 操作发生时间（UTC） |
| `account_name` | `VARCHAR(64) ascii_bin` | 否 | 无 | — | 执行操作的数据库账号名（非应用用户），如 honeypot_app_rw |
| `operation` | `VARCHAR(32)` | 否 | 无 | CK | 操作类型：reset 演示重置 / rule_change 规则版本变更 / alert_ack 告警已读 / export 数据导出 / migration 迁移执行 / manual_query 人工查询 / login_failed 连接失败 |
| `target_table` | `VARCHAR(64)` | 是 | `NULL` | — | 涉及的业务表名，如 attack_log |
| `target_key` | `VARCHAR(128)` | 是 | `NULL` | — | 涉及的主键或去重键（脱敏后），如告警去重键或规则编码 |
| `result` | `VARCHAR(16)` | 否 | 无 | CK | 操作结果：success 成功 / failure 失败 |
| `detail` | `VARCHAR(1000)` | 是 | `NULL` | — | 结构化说明；禁止写入口令、完整 SQL 原文或任何真实凭据 |
| `request_id` | `CHAR(36) ascii_bin` | 是 | `NULL` | — | 一次业务操作的关联编号（UUID v4 文本），用于串联同一操作的多条审计记录 |

索引与约束：`PRIMARY`、`idx_audit_time (occurred_at)`、`idx_audit_operation_time (operation, occurred_at)`。

表注释（`COMMENT`）：`审计日志表：仅追加重放记录关键写操作（重置、规则变更、告警已读、导出、迁移）；业务账号仅可插入与查询，不可修改删除`

---

## 5. 完整性约束矩阵

### 5.1 主键约束

| 序号 | 表 | 约束名 | 列 | 类型 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 1 | `sessions` | `PRIMARY` | `session_id` | 业务主键（`CHAR(36)`） | UUID 文本作为会话主键；不使用自增代理键，避免多一层映射 |
| 2 | `attack_log` | `PRIMARY` | `event_id` | 自增代理键 | 全局单调，用于同时间戳稳定排序 |
| 3 | `attacker_profile` | `PRIMARY` | `attacker_id` | 自增代理键 | 画像编号 |
| 4 | `attacker_intent` | `PRIMARY` | `intent_id` | 自增代理键 | 意图行编号 |
| 5 | `detection_rules` | `PRIMARY` | `rule_id` | 自增代理键 | 规则版本行编号 |
| 6 | `rule_hits` | `PRIMARY` | `hit_id` | 自增代理键 | 命中编号 |
| 7 | `alerts` | `PRIMARY` | `alert_id` | 自增代理键 | 告警编号 |
| 8 | `fake_users` | `PRIMARY` | `id` | 自增代理键 | 诱饵用户编号 |
| 9 | `fake_orders` | `PRIMARY` | `order_id` | 自增代理键 | 诱饵订单编号 |
| 10 | `fake_config` | `PRIMARY` | `config_id` | 自增代理键 | 诱饵配置编号 |
| 11 | `audit_log` | `PRIMARY` | `audit_id` | 自增代理键 | 审计编号 |

### 5.2 外键约束（全部 `ON UPDATE RESTRICT ON DELETE RESTRICT`）

| 序号 | 子表 | 约束名 | 子列 | 父表 | 父列 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `attack_log` | `fk_log_session` | `session_id` | `sessions` | `session_id` | 事件必须属于已存在会话；未知会话写入被拒绝（spec 用户故事 3 场景 3） |
| 2 | `attacker_intent` | `fk_intent_profile` | `attacker_id` | `attacker_profile` | `attacker_id` | 意图必须挂在已存在画像上 |
| 3 | `rule_hits` | `fk_hit_log` | `event_id, session_id` | `attack_log` | `event_id, session_id` | **复合外键**：保证命中行的事件与会话来自同一会话（总纲第五章"扩充 实体关系和数据一致性"）；父索引为 `uk_attack_log_event_session` |
| 4 | `rule_hits` | `fk_hit_session` | `session_id` | `sessions` | `session_id` | 独立会话引用，错误定位更直接，并支撑会话证据查询索引；与 3 冗余但可接受（见 5.2 下方说明） |
| 5 | `rule_hits` | `fk_hit_rule` | `rule_id` | `detection_rules` | `rule_id` | 命中必须引用存在的规则行 |
| 6 | `alerts` | `fk_alert_session` | `session_id` | `sessions` | `session_id` | 告警必须关联会话 |
| 7 | `alerts` | `fk_alert_attacker` | `attacker_id` | `attacker_profile` | `attacker_id` | 告警必须关联攻击者画像；要求画像先于告警写入（8.3） |
| 8 | `alerts` | `fk_alert_rule` | `rule_id` | `detection_rules` | `rule_id` | 告警必须关联触发规则 |
| 9 | `alerts` | `fk_alert_latest_hit` | `latest_hit_id` | `rule_hits` | `hit_id` | 告警证据可定位到具体命中（FR-057） |
| 10 | `fake_orders` | `fk_fake_orders_user` | `user_id` | `fake_users` | `id` | 诱饵订单必须关联诱饵用户（FR-030） |

**关于 3 与 4 的冗余说明**：复合外键（3）已经通过 `attack_log.session_id → sessions.session_id` 传递保证会话存在，理论上可去掉（4）。保留的理由是：① 直接引用 `sessions` 使"会话被 `RESTRICT` 保护"的语义显式，数据库错误信息指向 `fk_hit_session` 而非 `fk_hit_log`；② `idx_hit_session_time` 作为 FK 索引的同时是会话证据查询的必需索引，没有额外索引成本。若评审认为冗余不可接受，可删除（4）并把（3）作为唯一会话引用，功能不变（记录于第 15 章权衡）。

**为什么全部使用 `RESTRICT`**：蜜罐证据不可重建；级联删除会在演示重置或清理时静默丢失证据链。所有删除都走显式事务并按 8.6 的依赖顺序执行，避免"一条 DELETE 清空半个库"。

### 5.3 唯一约束

| 序号 | 表 | 约束名 | 列 | 对应需求 |
| --- | --- | --- | --- | --- |
| 1 | `attack_log` | `uk_attack_log_event_uuid` | `event_uuid` | FR-023/FR-041 事件幂等 |
| 2 | `attack_log` | `uk_attack_log_event_session` | `event_id, session_id` | 复合外键父索引（同源校验） |
| 3 | `attacker_profile` | `uk_attacker_profile_source_ip` | `source_ip` | 每来源一行画像（FR-050 口径） |
| 4 | `attacker_intent` | `uk_attacker_intent_attacker_type` | `attacker_id, intent_type` | FR-024 每攻击者每意图一行 |
| 5 | `detection_rules` | `uk_detection_rules_code_version` | `rule_code, rule_version` | FR-026 规则版本复合唯一 |
| 6 | `detection_rules` | `uk_detection_rules_enabled_code` | `enabled_rule_code`（生成列） | 同一规则至多一个启用版本，避免分析时版本并列 |
| 7 | `rule_hits` | `uk_rule_hits_event_rule_version` | `event_id, rule_id, rule_version` | 同一事件同版本规则不重复命中（边界情况） |
| 8 | `alerts` | `uk_alerts_dedup_key` | `dedup_key` | FR-059 告警去重 |
| 9 | `fake_users` | `uk_fake_users_username` | `username` | FR-030 诱饵用户名唯一 |
| 10 | `fake_users` | `uk_fake_users_email` | `email` | 诱饵邮箱唯一（展示一致性） |
| 11 | `fake_orders` | `uk_fake_orders_order_no` | `order_no` | 订单号唯一（展示一致性） |
| 12 | `fake_config` | `uk_fake_config_config_key` | `config_key` | FR-030 配置键唯一 |

### 5.4 检查约束（MySQL 8.0.16+ 强制执行）

| 序号 | 表 | 约束名 | 表达式 | 对应需求 |
| --- | --- | --- | --- | --- |
| 1 | `sessions` | `ck_sessions_source_port` | `source_port IS NULL OR source_port BETWEEN 1 AND 65535` | FR-017/FR-031 |
| 2 | `sessions` | `ck_sessions_ended_after_started` | `ended_at IS NULL OR ended_at >= started_at` | FR-017 结束时间不早于开始时间 |
| 3 | `sessions` | `ck_sessions_status` | `session_status IN ('active','closed','timeout','error')` | FR-017/FR-031 |
| 4 | `sessions` | `ck_sessions_max_risk_score` | `max_risk_score <= 100` | FR-031 分数 0-100（无符号保证下界） |
| 5 | `attack_log` | `ck_attack_log_event_type` | `event_type IN ('connect','auth','query','disconnect')` | FR-013 |
| 6 | `attack_log` | `ck_attack_log_status` | `status IN ('success','failure','denied','error')` | FR-012/FR-031 |
| 7 | `attack_log` | `ck_attack_log_sql_length` | `sql_statement IS NULL OR CHAR_LENGTH(sql_statement) <= 65535` | FR-020/宪法四（输入上限） |
| 8 | `attack_log` | `ck_attack_log_normalized_length` | `normalized_sql IS NULL OR CHAR_LENGTH(normalized_sql) <= 65535` | 同上 |
| 9 | `attack_log` | `ck_attack_log_truncated_flag` | `payload_truncated IN (0,1)` | FR-020 截断可追溯 |
| 10 | `attacker_profile` | `ck_profile_seen_order` | `last_seen >= first_seen` | 时间范围自洽 |
| 11 | `attacker_profile` | `ck_profile_risk_score` | `risk_score <= 100` | FR-047 |
| 12 | `attacker_intent` | `ck_intent_type` | `intent_type IN ('scanning','bruteforce','recon','data_dump','destructive')` | FR-044 |
| 13 | `attacker_intent` | `ck_intent_score` | `intent_score <= 100` | FR-047/FR-049 |
| 14 | `attacker_intent` | `ck_intent_detected_order` | `last_detected_at >= first_detected_at` | 时间范围自洽 |
| 15 | `detection_rules` | `ck_detection_rules_rule_type` | `rule_type IN ('frequency','keyword','sequence','volume')` | FR-026 |
| 16 | `detection_rules` | `ck_detection_rules_intent_type` | `intent_type IN ('scanning','bruteforce','recon','data_dump','destructive')` | FR-026/FR-044 |
| 17 | `detection_rules` | `ck_detection_rules_risk_weight` | `risk_weight BETWEEN 1 AND 100` | FR-047 |
| 18 | `detection_rules` | `ck_detection_rules_rule_version` | `rule_version >= 1` | FR-026/FR-052 |
| 19 | `detection_rules` | `ck_detection_rules_enabled` | `enabled IN (0,1)` | FR-046/FR-054 |
| 20 | `rule_hits` | `ck_hit_intent_type` | `intent_type IN ('scanning','bruteforce','recon','data_dump','destructive')` | FR-028 快照合法性 |
| 21 | `rule_hits` | `ck_hit_risk_weight` | `risk_weight BETWEEN 1 AND 100` | FR-028/FR-047 |
| 22 | `rule_hits` | `ck_hit_rule_version` | `rule_version >= 1` | FR-052 |
| 23 | `alerts` | `ck_alert_type` | `alert_type IN ('bruteforce','data_dump','destructive')` | FR-055/FR-060 |
| 24 | `alerts` | `ck_alert_severity` | `severity IN ('low','medium','high','critical')` | FR-060 |
| 25 | `alerts` | `ck_alert_seen_order` | `last_seen_at >= first_seen_at` | FR-059 |
| 26 | `alerts` | `ck_alert_occurrence_count` | `occurrence_count >= 1` | FR-059 |
| 27 | `alerts` | `ck_alert_is_read` | `is_read IN (0,1)` | FR-058 |
| 28 | `alerts` | `ck_alert_read_at` | `read_at IS NULL OR is_read = 1` | FR-058 已读时间一致性 |
| 29 | `fake_users` | `ck_fake_users_password_hash` | `password_hash LIKE 'TEST-ONLY$%'` | FR-006/FR-085 禁止真实口令 |
| 30 | `fake_users` | `ck_fake_users_synthetic` | `is_synthetic = 1` | FR-006/FR-085 |
| 31 | `fake_orders` | `ck_fake_orders_amount` | `amount >= 0` | 金额非负 |
| 32 | `fake_orders` | `ck_fake_orders_status` | `order_status IN ('pending','paid','shipped','cancelled','refunded')` | 展示枚举合法 |
| 33 | `fake_orders` | `ck_fake_orders_synthetic` | `is_synthetic = 1` | FR-085 |
| 34 | `fake_config` | `ck_fake_config_test_only` | `config_value LIKE 'TEST-ONLY%'` | FR-006/FR-085 禁止可用密钥 |
| 35 | `fake_config` | `ck_fake_config_category` | `category IN ('database','mail','api','storage')` | 展示分类合法 |
| 36 | `fake_config` | `ck_fake_config_invalid` | `is_invalid = 1` | FR-085 |
| 37 | `audit_log` | `ck_audit_operation` | `operation IN ('reset','rule_change','alert_ack','export','migration','manual_query','login_failed')` | 宪法三（审计口径收敛） |
| 38 | `audit_log` | `ck_audit_result` | `result IN ('success','failure')` | 宪法三（失败留痕） |

### 5.5 生成列与默认值约束

| 对象 | 类型 | 表达式 / 默认值 | 说明 |
| --- | --- | --- | --- |
| `attacker_profile.risk_level` | `VIRTUAL` 生成列 | `CASE WHEN risk_score >= 80 THEN 'critical' WHEN risk_score >= 60 THEN 'high' WHEN risk_score >= 30 THEN 'medium' ELSE 'low' END` | 分数—等级永不漂移；虚拟列不占存储，查询时才计算 |
| `detection_rules.enabled_rule_code` | `STORED` 生成列 | `CASE WHEN enabled = 1 THEN rule_code ELSE NULL END` | 参与唯一索引，强制"至多一个启用版本"；`STORED` 使唯一索引可持久化 |
| `*_score` / `*_weight` | 默认值 `0`（权重无默认） | —— | 分数默认 0 表示"尚无证据"；权重必须显式给出，避免漏配置时静默计 0 分 |
| 时间列 | `CURRENT_TIMESTAMP(6)` | 仅 `created_at`/`updated_at`/`occurred_at` | 业务时间列不使用默认值（2.4） |

### 5.6 不在数据库层强制、由应用保证的规则

| 规则 | 为什么不能入库 | 应用层保障手段 |
| --- | --- | --- |
| `attack_log.source_ip` 与所属会话的 `source_ip` 一致 | 跨表条件无法用单表 `CHECK` 表达；用触发器会引入隐式写入与审计复杂度 | 写入事务内从会话行取值复制；`v_session_risk_summary` 不依赖该一致性；实现阶段提供一致性校验 SQL（12.6） |
| `attack_log.event_time` 落在 `started_at` 与 `ended_at` 之间 | 同上（跨表） | 写入事务中由捕获层保证；校验脚本定期抽查 |
| `rule_hits.rule_code/intent_type` 与 `detection_rules` 的对应关系在命中时一致 | 快照列与当前规则行允许不同（这正是快照的目的），无法用 `CHECK` 约束历史一致 | 写入事务内由分析层从已加载的规则行赋值；迁移脚本提供快照一致性抽样校验 |
| 画像计数与会话/日志的真实计数一致 | 聚合值可重算，强制同步会引入大量触发器 | 事件事务内原子自增；`v_attacker_profile_summary` 展示重算值；每日/重置前校验 |
| `dedup_key` 的格式（`rule_code:source_ip:date`） | 可由 `CHECK` 做正则，但表达式复杂且难维护 | 由应用统一函数生成；写入前校验长度 ≤160；迁移脚本提供格式抽样检查 |
| 口令从不入库 | 数据库无法识别"这是口令" | 表结构不设口令列；`credential_test_id` 仅存测试标识；检查约束强制诱饵哈希带 `TEST-ONLY$` |
| `event_uuid` 的生成时机与唯一性 | 生成策略属应用职责 | 捕获层在事件生成时用 UUID v4 生成一次并随事件传递；重试复用同一 `event_uuid` |

---

## 6. 四个核心分析视图

### 6.1 通用约定

1. **创建方式**：统一使用 `CREATE OR REPLACE ... SQL SECURITY DEFINER VIEW`，由 `honeypot_migrate` 账号执行；不显式写 `DEFINER`（由创建账号决定），部署说明中要求视图脚本必须用迁移账号执行。
2. **列别名**：每个表达式列必须显式起别名，且长度 ≤64 字符（MySQL 规定视图列名/别名上限 64，超过会导致 `SHOW CREATE VIEW` 输出不可重放）。
3. **不写 `ORDER BY`**：视图定义中不排序，排序交给查询侧（`ORDER BY` 写在视图内会被优化器忽略，且易造成误解）。
4. **两阶段聚合防放大**：多张明细表（日志、命中、告警）先各自按自身粒度 `GROUP BY` 聚合，再与主表 `LEFT JOIN`。若直接"多明细表 JOIN 后 `GROUP BY`"，行数会相乘导致计数虚高——这是总纲"扩充 视图验证"明确要求核对的点。
5. **统计口径固定**：风险分一律按 9.2 的确定性公式（同一 `rule_code` 在统计范围内取 `MAX(risk_weight)` 后求和并 `LEAST(100, ...)`），视图与写入侧使用同一口径。
6. **视图只读**：含 `GROUP BY`/窗口函数/CTE，视图不可更新；控制台只做 `SELECT`（FR-068/FR-070）。
7. **引用表数**：每个视图引用的表不超过 61 张（MySQL 限制），当前最多 5 张。
8. **失效处理**：底层表 `DROP`/`ALTER` 不会报错但会让视图失效，`CHECK TABLE <view>` 可检测；迁移必须按"先改表、再重建视图"的顺序执行（12.4）。

### 6.2 `v_session_risk_summary`（会话风险汇总）

**用途**：FR-032/FR-033/FR-062/FR-065。每个会话一行，汇总事件计数、认证失败数、规则命中与告警，给出**重算风险分**并与会话表存储的 `max_risk_score` 并列对照，方便答辩时验证"存储值与重算值一致"。

**查询技术**：多张明细表分别聚合（CTE）+ 多表 `LEFT JOIN` + `GROUP BY` 两级聚合，避免 JOIN 放大。

```sql
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_session_risk_summary AS
WITH log_agg AS (
  SELECT
    al.session_id                                                 AS session_id,
    COUNT(*)                                                      AS event_count,
    SUM(CASE WHEN al.event_type = 'connect' THEN 1 ELSE 0 END)    AS connect_count,
    SUM(CASE WHEN al.event_type = 'auth' THEN 1 ELSE 0 END)       AS auth_attempt_count,
    SUM(CASE WHEN al.event_type = 'auth'
              AND al.status IN ('failure', 'denied') THEN 1 ELSE 0 END) AS auth_failure_count,
    SUM(CASE WHEN al.event_type = 'query' THEN 1 ELSE 0 END)      AS query_count,
    SUM(CASE WHEN al.status = 'denied' THEN 1 ELSE 0 END)         AS denied_count,
    CAST(SUM(al.returned_rows) AS UNSIGNED)                       AS returned_rows_total,
    MAX(al.event_time)                                            AS last_event_at
  FROM attack_log AS al
  GROUP BY al.session_id
),
hit_agg AS (
  SELECT
    rh.session_id                                                 AS session_id,
    COUNT(*)                                                      AS hit_count,
    COUNT(DISTINCT rh.rule_code)                                  AS hit_rule_count,
    MAX(rh.triggered_at)                                          AS last_hit_at
  FROM rule_hits AS rh
  GROUP BY rh.session_id
),
rule_max AS (
  SELECT
    rh.session_id                                                 AS session_id,
    rh.rule_code                                                  AS rule_code,
    MAX(rh.risk_weight)                                           AS rule_weight
  FROM rule_hits AS rh
  GROUP BY rh.session_id, rh.rule_code
),
risk_agg AS (
  SELECT
    rm.session_id                                                 AS session_id,
    LEAST(100, SUM(rm.rule_weight))                               AS calculated_risk_score,
    GROUP_CONCAT(rm.rule_code ORDER BY rm.rule_code SEPARATOR ',') AS hit_rule_codes
  FROM rule_max AS rm
  GROUP BY rm.session_id
),
alert_agg AS (
  SELECT
    a.session_id                                                  AS session_id,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.is_read = 0 THEN 1 ELSE 0 END)                AS unread_alert_count,
    MAX(CASE a.severity WHEN 'critical' THEN 4
                        WHEN 'high'     THEN 3
                        WHEN 'medium'   THEN 2
                        WHEN 'low'      THEN 1
                        ELSE 0 END)                               AS severity_rank
  FROM alerts AS a
  GROUP BY a.session_id
)
SELECT
  s.session_id                                                    AS session_id,
  s.source_ip                                                     AS source_ip,
  s.source_port                                                   AS source_port,
  s.target_service                                                AS target_service,
  s.started_at                                                    AS started_at,
  s.ended_at                                                      AS ended_at,
  s.session_status                                                AS session_status,
  s.request_count                                                 AS stored_request_count,
  COALESCE(la.event_count, 0)                                     AS event_count,
  COALESCE(la.connect_count, 0)                                   AS connect_count,
  COALESCE(la.auth_attempt_count, 0)                              AS auth_attempt_count,
  COALESCE(la.auth_failure_count, 0)                              AS auth_failure_count,
  COALESCE(la.query_count, 0)                                     AS query_count,
  COALESCE(la.denied_count, 0)                                    AS denied_count,
  COALESCE(la.returned_rows_total, 0)                             AS returned_rows_total,
  la.last_event_at                                                AS last_event_at,
  COALESCE(ha.hit_count, 0)                                       AS hit_count,
  COALESCE(ha.hit_rule_count, 0)                                  AS hit_rule_count,
  ha.last_hit_at                                                  AS last_hit_at,
  ra.hit_rule_codes                                               AS hit_rule_codes,
  COALESCE(ra.calculated_risk_score, 0)                           AS calculated_risk_score,
  CASE
    WHEN COALESCE(ra.calculated_risk_score, 0) >= 80 THEN 'critical'
    WHEN COALESCE(ra.calculated_risk_score, 0) >= 60 THEN 'high'
    WHEN COALESCE(ra.calculated_risk_score, 0) >= 30 THEN 'medium'
    ELSE 'low'
  END                                                             AS risk_level,
  s.max_risk_score                                                AS stored_max_risk_score,
  COALESCE(aa.alert_count, 0)                                     AS alert_count,
  COALESCE(aa.unread_alert_count, 0)                              AS unread_alert_count,
  CASE aa.severity_rank
    WHEN 4 THEN 'critical'
    WHEN 3 THEN 'high'
    WHEN 2 THEN 'medium'
    WHEN 1 THEN 'low'
    ELSE NULL
  END                                                             AS highest_alert_severity
FROM sessions AS s
LEFT JOIN log_agg    AS la ON la.session_id = s.session_id
LEFT JOIN hit_agg    AS ha ON ha.session_id = s.session_id
LEFT JOIN risk_agg   AS ra ON ra.session_id = s.session_id
LEFT JOIN alert_agg  AS aa ON aa.session_id = s.session_id;
```

**演示查询**（可直接用于答辩"会话风险排行"）：

```sql
SELECT session_id, source_ip, started_at, event_count, query_count,
       hit_rule_codes, calculated_risk_score, risk_level,
       stored_max_risk_score, alert_count
FROM v_session_risk_summary
ORDER BY calculated_risk_score DESC, started_at DESC
LIMIT 20;
```

### 6.3 `v_attacker_profile_summary`（攻击者画像汇总）

**用途**：FR-032/FR-050/FR-063/FR-064。每个来源一行，给出画像统计、重算风险分、会话数、高风险会话数、告警数，并用窗口函数在**并列条件下稳定**地选出主要意图。

**查询技术**：多表 `JOIN` + 分源聚合 + 窗口函数 `ROW_NUMBER()` 取主要意图（`ORDER BY intent_score DESC, last_detected_at DESC, 危害等级 DESC`）+ `GROUP_CONCAT` 生成展示用意图串（仅视图计算，不落库，符合 FR-025）。

```sql
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_attacker_profile_summary AS
WITH session_agg AS (
  SELECT
    s.source_ip                                                   AS source_ip,
    COUNT(*)                                                      AS session_count,
    MIN(s.started_at)                                             AS first_session_at,
    MAX(s.started_at)                                             AS last_session_at
  FROM sessions AS s
  GROUP BY s.source_ip
),
intent_rank AS (
  SELECT
    ai.attacker_id                                                AS attacker_id,
    ai.intent_type                                                AS intent_type,
    ai.intent_score                                               AS intent_score,
    ai.evidence_count                                             AS evidence_count,
    ai.last_detected_at                                           AS last_detected_at,
    ROW_NUMBER() OVER (
      PARTITION BY ai.attacker_id
      ORDER BY ai.intent_score DESC,
               ai.last_detected_at DESC,
               CASE ai.intent_type
                 WHEN 'destructive' THEN 5
                 WHEN 'data_dump'   THEN 4
                 WHEN 'bruteforce'  THEN 3
                 WHEN 'recon'       THEN 2
                 ELSE 1
               END DESC
    )                                                             AS intent_rank_no
  FROM attacker_intent AS ai
),
intent_labels AS (
  SELECT
    ai.attacker_id                                                AS attacker_id,
    GROUP_CONCAT(ai.intent_type
                 ORDER BY ai.intent_score DESC, ai.last_detected_at DESC
                 SEPARATOR ',')                                   AS intent_labels
  FROM attacker_intent AS ai
  GROUP BY ai.attacker_id
),
hit_source AS (
  SELECT
    al.source_ip                                                  AS source_ip,
    rh.session_id                                                 AS session_id,
    rh.rule_code                                                  AS rule_code,
    rh.risk_weight                                                AS risk_weight
  FROM rule_hits AS rh
  JOIN attack_log AS al ON al.event_id = rh.event_id
),
source_rule_max AS (
  SELECT
    hs.source_ip                                                  AS source_ip,
    hs.rule_code                                                  AS rule_code,
    MAX(hs.risk_weight)                                           AS rule_weight
  FROM hit_source AS hs
  GROUP BY hs.source_ip, hs.rule_code
),
profile_risk AS (
  SELECT
    srm.source_ip                                                 AS source_ip,
    LEAST(100, SUM(srm.rule_weight))                              AS calculated_risk_score,
    GROUP_CONCAT(srm.rule_code ORDER BY srm.rule_code SEPARATOR ',') AS triggered_rule_codes
  FROM source_rule_max AS srm
  GROUP BY srm.source_ip
),
session_rule_max AS (
  SELECT
    hs.source_ip                                                  AS source_ip,
    hs.session_id                                                 AS session_id,
    hs.rule_code                                                  AS rule_code,
    MAX(hs.risk_weight)                                           AS rule_weight
  FROM hit_source AS hs
  GROUP BY hs.source_ip, hs.session_id, hs.rule_code
),
session_risk AS (
  SELECT
    srm.source_ip                                                 AS source_ip,
    srm.session_id                                                AS session_id,
    LEAST(100, SUM(srm.rule_weight))                              AS session_risk_score
  FROM session_rule_max AS srm
  GROUP BY srm.source_ip, srm.session_id
),
high_risk AS (
  SELECT
    sr.source_ip                                                  AS source_ip,
    SUM(CASE WHEN sr.session_risk_score >= 60 THEN 1 ELSE 0 END)  AS high_risk_session_count
  FROM session_risk AS sr
  GROUP BY sr.source_ip
),
alert_agg AS (
  SELECT
    a.attacker_id                                                 AS attacker_id,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.is_read = 0 THEN 1 ELSE 0 END)                AS unread_alert_count
  FROM alerts AS a
  GROUP BY a.attacker_id
)
SELECT
  p.attacker_id                                                   AS attacker_id,
  p.source_ip                                                     AS source_ip,
  p.first_seen                                                    AS first_seen,
  p.last_seen                                                     AS last_seen,
  p.total_connections                                             AS total_connections,
  p.total_auth_attempts                                           AS total_auth_attempts,
  p.total_auth_failures                                           AS total_auth_failures,
  p.total_queries                                                 AS total_queries,
  p.risk_score                                                    AS stored_risk_score,
  COALESCE(pr.calculated_risk_score, 0)                           AS calculated_risk_score,
  CASE
    WHEN COALESCE(pr.calculated_risk_score, 0) >= 80 THEN 'critical'
    WHEN COALESCE(pr.calculated_risk_score, 0) >= 60 THEN 'high'
    WHEN COALESCE(pr.calculated_risk_score, 0) >= 30 THEN 'medium'
    ELSE 'low'
  END                                                             AS risk_level,
  COALESCE(sa.session_count, 0)                                   AS session_count,
  COALESCE(hr.high_risk_session_count, 0)                         AS high_risk_session_count,
  COALESCE(aa.alert_count, 0)                                     AS alert_count,
  COALESCE(aa.unread_alert_count, 0)                              AS unread_alert_count,
  ir.intent_type                                                  AS primary_intent_type,
  ir.intent_score                                                 AS primary_intent_score,
  ir.last_detected_at                                             AS primary_intent_last_detected_at,
  COALESCE(il.intent_labels, '')                                  AS intent_labels,
  pr.triggered_rule_codes                                         AS triggered_rule_codes,
  p.evidence_summary                                              AS evidence_summary
FROM attacker_profile AS p
LEFT JOIN session_agg  AS sa ON sa.source_ip = p.source_ip
LEFT JOIN profile_risk AS pr ON pr.source_ip = p.source_ip
LEFT JOIN high_risk    AS hr ON hr.source_ip = p.source_ip
LEFT JOIN alert_agg    AS aa ON aa.attacker_id = p.attacker_id
LEFT JOIN intent_rank  AS ir ON ir.attacker_id = p.attacker_id
                             AND ir.intent_rank_no = 1
LEFT JOIN intent_labels AS il ON il.attacker_id = p.attacker_id;
```

**演示查询**（攻击者列表页数据源，FR-063）：

```sql
SELECT source_ip, first_seen, last_seen, session_count, total_queries,
       calculated_risk_score, risk_level, primary_intent_type, intent_labels
FROM v_attacker_profile_summary
ORDER BY calculated_risk_score DESC, last_seen DESC
LIMIT 20 OFFSET 0;
```

### 6.4 `v_daily_attack_trend`（每日攻击趋势）

**用途**：FR-032/FR-067。按 UTC 自然日汇总攻击事件与告警，给出与前一日的变化量/变化率、累计事件数、当日繁忙排名。

**查询技术**：CTE 日期分组 + 窗口函数 `LAG()`（取前一日）+ `SUM() OVER`（累计）+ `RANK()`（繁忙排名）+ 告警按日聚合后 `LEFT JOIN`。

```sql
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_daily_attack_trend AS
WITH daily AS (
  SELECT
    DATE(al.event_time)                                           AS stat_date,
    COUNT(*)                                                      AS event_count,
    COUNT(DISTINCT al.session_id)                                 AS session_count,
    COUNT(DISTINCT al.source_ip)                                  AS source_count,
    SUM(CASE WHEN al.event_type = 'connect' THEN 1 ELSE 0 END)    AS connect_count,
    SUM(CASE WHEN al.event_type = 'auth' THEN 1 ELSE 0 END)       AS auth_attempt_count,
    SUM(CASE WHEN al.event_type = 'auth'
              AND al.status IN ('failure', 'denied') THEN 1 ELSE 0 END) AS auth_failure_count,
    SUM(CASE WHEN al.event_type = 'query' THEN 1 ELSE 0 END)      AS query_count,
    SUM(CASE WHEN al.status = 'denied' THEN 1 ELSE 0 END)         AS denied_count,
    CAST(SUM(al.returned_rows) AS UNSIGNED)                       AS returned_rows_total
  FROM attack_log AS al
  GROUP BY DATE(al.event_time)
),
daily_alert AS (
  SELECT
    DATE(a.created_at)                                            AS stat_date,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.severity IN ('high', 'critical') THEN 1 ELSE 0 END) AS high_level_alert_count
  FROM alerts AS a
  GROUP BY DATE(a.created_at)
),
daily_lag AS (
  SELECT
    d.stat_date                                                   AS stat_date,
    d.event_count                                                 AS event_count,
    d.session_count                                               AS session_count,
    d.source_count                                                AS source_count,
    d.connect_count                                               AS connect_count,
    d.auth_attempt_count                                          AS auth_attempt_count,
    d.auth_failure_count                                          AS auth_failure_count,
    d.query_count                                                 AS query_count,
    d.denied_count                                                AS denied_count,
    d.returned_rows_total                                         AS returned_rows_total,
    LAG(d.event_count) OVER (ORDER BY d.stat_date)                AS prev_event_count,
    LAG(d.session_count) OVER (ORDER BY d.stat_date)              AS prev_session_count,
    SUM(d.event_count) OVER (
      ORDER BY d.stat_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                             AS cumulative_event_count,
    ROW_NUMBER() OVER (ORDER BY d.stat_date)                      AS day_seq,
    RANK() OVER (ORDER BY d.event_count DESC)                     AS busy_day_rank
  FROM daily AS d
)
SELECT
  dl.stat_date                                                    AS stat_date,
  dl.day_seq                                                      AS day_seq,
  dl.event_count                                                  AS event_count,
  dl.session_count                                                AS session_count,
  dl.source_count                                                 AS source_count,
  dl.connect_count                                                AS connect_count,
  dl.auth_attempt_count                                           AS auth_attempt_count,
  dl.auth_failure_count                                           AS auth_failure_count,
  dl.query_count                                                  AS query_count,
  dl.denied_count                                                 AS denied_count,
  dl.returned_rows_total                                          AS returned_rows_total,
  dl.prev_event_count                                             AS prev_event_count,
  dl.event_count - dl.prev_event_count                            AS event_count_delta,
  CASE
    WHEN dl.prev_event_count IS NULL OR dl.prev_event_count = 0 THEN NULL
    ELSE ROUND((dl.event_count - dl.prev_event_count) * 100.0 / dl.prev_event_count, 2)
  END                                                             AS event_change_pct,
  dl.prev_session_count                                           AS prev_session_count,
  dl.cumulative_event_count                                       AS cumulative_event_count,
  dl.busy_day_rank                                                AS busy_day_rank,
  COALESCE(da.alert_count, 0)                                     AS alert_count,
  COALESCE(da.high_level_alert_count, 0)                          AS high_level_alert_count
FROM daily_lag AS dl
LEFT JOIN daily_alert AS da ON da.stat_date = dl.stat_date;
```

**口径限制（必须写入演示说明）**：`LAG` 只在"有事件的日期"之间比较，**无事件的空白天不会出现行**，因此 `event_change_pct` 表示"相对上一个有事件日"的变化，不是严格的前一日历日。若需连续日历日，使用 6.6.4 的降级/增强写法（递归 CTE 生成日期序列），本版不进入视图以保证可维护性。

**演示查询**（首页趋势图数据源）：

```sql
SELECT stat_date, event_count, prev_event_count, event_count_delta,
       event_change_pct, cumulative_event_count, alert_count, busy_day_rank
FROM v_daily_attack_trend
ORDER BY stat_date DESC
LIMIT 14;
```

### 6.5 `v_rule_effectiveness`（规则效果统计）

**用途**：FR-032/FR-054。每条规则编码一行：命中次数、覆盖会话数、覆盖来源数、告警数、首末命中时间，并用 `RANK()` 给出命中次数排名；`is_enabled` 取自该编码的最新版本，停用规则仍保留历史效果。

**查询技术**：`COUNT(DISTINCT ...)` 去重计数 + 分规则聚合 + 窗口函数 `RANK()` 排名 + 最新版本 `JOIN`。

```sql
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_rule_effectiveness AS
WITH latest_rule AS (
  SELECT
    d.rule_code                                                   AS rule_code,
    MAX(d.rule_version)                                           AS latest_version
  FROM detection_rules AS d
  GROUP BY d.rule_code
),
rule_current AS (
  SELECT
    d.rule_code                                                   AS rule_code,
    d.rule_id                                                     AS rule_id,
    d.rule_name                                                   AS rule_name,
    d.rule_type                                                   AS rule_type,
    d.intent_type                                                 AS intent_type,
    d.risk_weight                                                 AS risk_weight,
    d.rule_version                                                AS current_version,
    d.enabled                                                     AS is_enabled
  FROM detection_rules AS d
  JOIN latest_rule AS lr
    ON lr.rule_code = d.rule_code
   AND lr.latest_version = d.rule_version
),
hit_stats AS (
  SELECT
    rh.rule_code                                                  AS rule_code,
    COUNT(*)                                                      AS hit_count,
    COUNT(DISTINCT rh.session_id)                                 AS affected_session_count,
    COUNT(DISTINCT rh.event_id)                                   AS affected_event_count,
    COUNT(DISTINCT al.source_ip)                                  AS affected_attacker_count,
    COUNT(DISTINCT rh.rule_version)                               AS used_version_count,
    MIN(rh.triggered_at)                                          AS first_hit_at,
    MAX(rh.triggered_at)                                          AS last_hit_at
  FROM rule_hits AS rh
  JOIN attack_log AS al ON al.event_id = rh.event_id
  GROUP BY rh.rule_code
),
alert_stats AS (
  SELECT
    a.rule_code                                                   AS rule_code,
    COUNT(*)                                                      AS alert_count,
    SUM(CASE WHEN a.is_read = 0 THEN 1 ELSE 0 END)                AS unread_alert_count
  FROM alerts AS a
  GROUP BY a.rule_code
),
combined AS (
  SELECT
    rc.rule_code                                                  AS rule_code,
    rc.rule_name                                                  AS rule_name,
    rc.rule_type                                                  AS rule_type,
    rc.intent_type                                                AS intent_type,
    rc.risk_weight                                                AS risk_weight,
    rc.current_version                                            AS current_version,
    rc.is_enabled                                                 AS is_enabled,
    COALESCE(hs.hit_count, 0)                                     AS hit_count,
    COALESCE(hs.affected_session_count, 0)                        AS affected_session_count,
    COALESCE(hs.affected_event_count, 0)                          AS affected_event_count,
    COALESCE(hs.affected_attacker_count, 0)                       AS affected_attacker_count,
    COALESCE(hs.used_version_count, 0)                            AS used_version_count,
    hs.first_hit_at                                               AS first_hit_at,
    hs.last_hit_at                                                AS last_hit_at,
    COALESCE(aa.alert_count, 0)                                   AS alert_count,
    COALESCE(aa.unread_alert_count, 0)                            AS unread_alert_count
  FROM rule_current AS rc
  LEFT JOIN hit_stats   AS hs ON hs.rule_code = rc.rule_code
  LEFT JOIN alert_stats AS aa ON aa.rule_code = rc.rule_code
)
SELECT
  cb.rule_code                                                    AS rule_code,
  cb.rule_name                                                    AS rule_name,
  cb.rule_type                                                    AS rule_type,
  cb.intent_type                                                  AS intent_type,
  cb.risk_weight                                                  AS risk_weight,
  cb.current_version                                              AS current_version,
  cb.is_enabled                                                   AS is_enabled,
  cb.hit_count                                                    AS hit_count,
  cb.affected_session_count                                       AS affected_session_count,
  cb.affected_event_count                                         AS affected_event_count,
  cb.affected_attacker_count                                      AS affected_attacker_count,
  cb.used_version_count                                           AS used_version_count,
  cb.first_hit_at                                                 AS first_hit_at,
  cb.last_hit_at                                                  AS last_hit_at,
  cb.alert_count                                                  AS alert_count,
  cb.unread_alert_count                                           AS unread_alert_count,
  CASE WHEN cb.hit_count = 0 THEN 0.0000
       ELSE ROUND(cb.alert_count / cb.hit_count, 4) END            AS alert_per_hit_ratio,
  RANK() OVER (ORDER BY cb.hit_count DESC, cb.rule_code ASC)       AS hit_rank
FROM combined AS cb;
```

**演示查询**（规则效果页/答辩"哪条规则最有效"）：

```sql
SELECT hit_rank, rule_code, rule_name, intent_type, is_enabled,
       hit_count, affected_attacker_count, alert_count, alert_per_hit_ratio
FROM v_rule_effectiveness
ORDER BY hit_rank;
```

### 6.6 版本限制与降级写法

#### 6.6.1 事实核对（MySQL 8.4）

- MySQL 8.4 官方"视图的限制"（<https://dev.mysql.com/doc/refman/8.4/en/view-restrictions.html>）未禁止视图定义中使用 CTE、窗口函数或派生表；上述四个视图在 8.4 LTS 上可直接创建。
- 仍存在的限制：① 视图最多引用 61 张表；② 视图不能建索引，`ALGORITHM=TEMPTABLE` 的视图无法利用基表索引；③ 视图列别名 ≤64 字符；④ 从视图查询时不能使用索引提示（`USE INDEX`）。
- 已知缺陷：`SHOW CREATE VIEW` 在处理"CTE 内未显式命名别名的窗口函数列"时可能生成不可重放的视图定义（8.0.39/8.0.40 有相关缺陷报告）。因此本文档规定**所有表达式列（含窗口函数列）必须显式起别名**，该规范已在上面的 SQL 中执行。
- `CHECK` 约束需 MySQL ≥ 8.0.16，`JSON` 原生类型需 ≥5.7；`ROW_NUMBER/RANK/LAG` 与 CTE 需 ≥8.0。若部署环境低于 8.0.16，必须升级，不接受"约束不生效"的降级运行。
- **视图中的 CTE 与窗口函数不影响可更新性判断**（视图本就不可更新），无需 `ALGORITHM=TEMPTABLE` 提示；如遇优化器合并问题，可显式声明 `ALGORITHM = TEMPTABLE`，代价是失去基表索引下推。

#### 6.6.2 降级写法 A：CTE → 派生表（等价改写）

若目标实例对视图内 CTE 支持异常（或需兼容 8.0.13 之前的小版本），把 `WITH x AS (...)` 改为 `FROM (...) AS x`。以 `v_session_risk_summary` 的关键部分为例：

```sql
-- 降级写法：不用 CTE，用派生表；语义与 6.2 完全一致
SELECT s.session_id, s.source_ip,
       COALESCE(la.event_count, 0) AS event_count,
       COALESCE(ra.calculated_risk_score, 0) AS calculated_risk_score,
       ra.hit_rule_codes
FROM sessions AS s
LEFT JOIN (
  SELECT al.session_id, COUNT(*) AS event_count
  FROM attack_log AS al
  GROUP BY al.session_id
) AS la ON la.session_id = s.session_id
LEFT JOIN (
  SELECT rm.session_id, LEAST(100, SUM(rm.rule_weight)) AS calculated_risk_score,
         GROUP_CONCAT(rm.rule_code ORDER BY rm.rule_code SEPARATOR ',') AS hit_rule_codes
  FROM (
    SELECT rh.session_id, rh.rule_code, MAX(rh.risk_weight) AS rule_weight
    FROM rule_hits AS rh
    GROUP BY rh.session_id, rh.rule_code
  ) AS rm
  GROUP BY rm.session_id
) AS ra ON ra.session_id = s.session_id;
```

#### 6.6.3 降级写法 B：`ROW_NUMBER()` → 相关子查询（取主要意图）

```sql
-- 不用窗口函数，用相关子查询按同样排序键取主要意图（并列规则完全一致）
SELECT p.source_ip,
       (SELECT ai.intent_type
        FROM attacker_intent AS ai
        WHERE ai.attacker_id = p.attacker_id
        ORDER BY ai.intent_score DESC,
                 ai.last_detected_at DESC,
                 CASE ai.intent_type
                   WHEN 'destructive' THEN 5 WHEN 'data_dump' THEN 4
                   WHEN 'bruteforce' THEN 3 WHEN 'recon' THEN 2 ELSE 1 END DESC
        LIMIT 1) AS primary_intent_type
FROM attacker_profile AS p;
```

#### 6.6.4 降级写法 C：`LAG()` → 自连接 / 连续日期增强

```sql
-- 不用窗口函数：用自连接取"上一个有事件的日期"
SELECT d1.stat_date, d1.event_count, MAX(d2.event_count) AS prev_event_count
FROM (SELECT DATE(al.event_time) AS stat_date, COUNT(*) AS event_count
      FROM attack_log AS al GROUP BY DATE(al.event_time)) AS d1
LEFT JOIN (SELECT DATE(al.event_time) AS stat_date, COUNT(*) AS event_count
           FROM attack_log AS al GROUP BY DATE(al.event_time)) AS d2
       ON d2.stat_date < d1.stat_date
GROUP BY d1.stat_date, d1.event_count;
```

若需要严格"前一日历日"（把空白日补 0），在查询侧（不进视图）用递归 CTE 生成日期序列后左连接 `v_daily_attack_trend`：

```sql
-- 查询侧增强：补齐连续日期，仅用于首页图表，不写入视图定义
WITH RECURSIVE calendar AS (
  SELECT DATE(MIN(al.event_time)) AS stat_date FROM attack_log AS al
  UNION ALL
  SELECT DATE_ADD(cal.stat_date, INTERVAL 1 DAY)
  FROM calendar AS cal
  WHERE cal.stat_date < (SELECT DATE(MAX(al2.event_time)) FROM attack_log AS al2)
)
SELECT cal.stat_date,
       COALESCE(t.event_count, 0) AS event_count,
       t.event_change_pct
FROM calendar AS cal
LEFT JOIN v_daily_attack_trend AS t ON t.stat_date = cal.stat_date
ORDER BY cal.stat_date;
```

#### 6.6.5 降级写法 D：`RANK()` → 计数子查询

```sql
-- 不用窗口函数：命中次数排名 = 命中次数严格大于本规则的行数 + 1
SELECT c.rule_code, c.hit_count,
       (SELECT COUNT(*) + 1
        FROM (SELECT rh.rule_code, COUNT(*) AS hit_count
              FROM rule_hits AS rh GROUP BY rh.rule_code) AS x
        WHERE x.hit_count > c.hit_count
           OR (x.hit_count = c.hit_count AND x.rule_code < c.rule_code)) AS hit_rank
FROM (SELECT rh.rule_code, COUNT(*) AS hit_count
      FROM rule_hits AS rh GROUP BY rh.rule_code) AS c;
```

**结论**：主版本使用 6.2–6.5 的 CTE + 窗口函数写法（MySQL 8.4 原生支持，可读性与答辩展示效果最好）；降级写法仅用于兼容旧实例或排障对照，二者必须产出相同的数值口径。

---

## 7. 索引设计与 EXPLAIN 验证方案

### 7.1 索引总表

> 表中"规定索引"指 spec/总纲明确要求的四条复合索引，名称与列顺序不得变更；其余为支撑外键、唯一性与实际查询的必要索引。

| 序号 | 表 | 索引名 | 类型 | 列顺序 | 目标查询 / 存在理由 | 需求 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `sessions` | `PRIMARY` | 主键 | `session_id` | 会话主键查找、外键目标 | FR-011 |
| 2 | `sessions` | `idx_sessions_source_started` | 普通 | `source_ip, started_at` | 按来源列会话（攻击者详情）、按来源统计首末时间 | FR-064 |
| 3 | `sessions` | `idx_sessions_status_started` | 普通 | `session_status, started_at` | 巡检未关闭会话、超时回收任务 | FR-017 |
| 4 | `sessions` | `idx_sessions_started` | 普通 | `started_at` | 首页"近 N 天连接数/会话数"按时间范围聚合；表行数小，维护成本低 | FR-062 |
| 5 | `attack_log` | `PRIMARY` | 主键 | `event_id` | 事件主键与并列排序 | FR-018 |
| 6 | `attack_log` | `uk_attack_log_event_uuid` | 唯一 | `event_uuid` | 幂等键点查（重复事件返回已有 event_id） | FR-023/FR-041 |
| 7 | `attack_log` | `uk_attack_log_event_session` | 唯一 | `event_id, session_id` | 复合外键父索引，保证命中同源 | FR-022 |
| 8 | `attack_log` | `idx_log_session_time` | 普通 | `session_id, event_time` | **规定索引 1**：按会话重建事件时间线 | FR-034/FR-065 |
| 9 | `attack_log` | `idx_log_source_time` | 普通 | `source_ip, event_time` | **规定索引 2**：按来源 + 时间范围查询行为（规则窗口统计） | FR-034 |
| 10 | `attacker_profile` | `PRIMARY` | 主键 | `attacker_id` | 画像主键 | FR-050 |
| 11 | `attacker_profile` | `uk_attacker_profile_source_ip` | 唯一 | `source_ip` | 画像按来源唯一 + 画像点查 | FR-050 |
| 12 | `attacker_profile` | `idx_profile_risk` | 普通 | `risk_score, last_seen` | 攻击者列表按风险分降序分页（反向扫描） | FR-063 |
| 13 | `attacker_intent` | `PRIMARY` | 主键 | `intent_id` | 意图主键 | FR-024 |
| 14 | `attacker_intent` | `uk_attacker_intent_attacker_type` | 唯一 | `attacker_id, intent_type` | 每攻击者每意图一行 + Upsert 定位 | FR-024 |
| 15 | `attacker_intent` | `idx_intent_type_score` | 普通 | `intent_type, intent_score` | 意图分布统计、按意图查看 | FR-064 |
| 16 | `detection_rules` | `PRIMARY` | 主键 | `rule_id` | 规则行主键 | FR-026 |
| 17 | `detection_rules` | `uk_detection_rules_code_version` | 唯一 | `rule_code, rule_version` | 规则版本唯一 | FR-026 |
| 18 | `detection_rules` | `uk_detection_rules_enabled_code` | 唯一 | `enabled_rule_code` | 同一规则至多一个启用版本 | FR-046 |
| 19 | `detection_rules` | `idx_detection_rules_intent` | 普通 | `intent_type, enabled, rule_code` | 按意图/启用状态列出规则 | FR-054 |
| 20 | `rule_hits` | `PRIMARY` | 主键 | `hit_id` | 命中主键、告警证据目标 | FR-028 |
| 21 | `rule_hits` | `uk_rule_hits_event_rule_version` | 唯一 | `event_id, rule_id, rule_version` | 同一事件同版本规则不重复命中 | 边界情况 |
| 22 | `rule_hits` | `idx_hit_event_session` | 普通 | `event_id, session_id` | 复合外键子索引（同源校验） | FR-028 |
| 23 | `rule_hits` | `idx_hit_rule_time` | 普通 | `rule_id, created_at` | **规定索引 4**：统计规则命中趋势 + 规则外键索引 | FR-034 |
| 24 | `rule_hits` | `idx_hit_session_time` | 普通 | `session_id, triggered_at` | 会话证据按时间展示 + 会话外键索引 | FR-064 |
| 25 | `alerts` | `PRIMARY` | 主键 | `alert_id` | 告警主键 | FR-060 |
| 26 | `alerts` | `uk_alerts_dedup_key` | 唯一 | `dedup_key` | 告警去重键点查、Upsert 定位 | FR-059 |
| 27 | `alerts` | `idx_alert_level_time` | 普通 | `severity, created_at` | **规定索引 3**：筛选近期高等级告警 | FR-034/FR-066 |
| 28 | `alerts` | `idx_alert_type_time` | 普通 | `alert_type, created_at` | 按告警类型 + 时间筛选 | FR-056/FR-066 |
| 29 | `alerts` | `idx_alert_session_time` | 普通 | `session_id, created_at` | 会话告警 + 会话外键索引 | FR-057 |
| 30 | `alerts` | `idx_alert_attacker_time` | 普通 | `attacker_id, created_at` | 攻击者告警 + 画像外键索引 | FR-064 |
| 31 | `alerts` | `idx_alert_read_time` | 普通 | `is_read, created_at` | 未读告警筛选与"最近未读"排序 | FR-058/FR-066 |
| 32 | `alerts` | `idx_alert_latest_hit` | 普通 | `latest_hit_id` | 证据外键索引 + 按命中反查告警 | FR-057 |
| 33 | `fake_users` | `PRIMARY` / `uk_fake_users_username` / `uk_fake_users_email` | 主键/唯一 | `id` / `username` / `email` | 诱饵用户展示与唯一性 | FR-030 |
| 34 | `fake_orders` | `PRIMARY` / `uk_fake_orders_order_no` / `idx_fake_orders_user` | 主键/唯一/普通 | `order_id` / `order_no` / `user_id, created_at` | 订单展示、按用户查订单、外键索引 | FR-030/FR-085 |
| 35 | `fake_config` | `PRIMARY` / `uk_fake_config_config_key` | 主键/唯一 | `config_id` / `config_key` | 配置键唯一 | FR-030 |
| 36 | `audit_log` | `PRIMARY` / `idx_audit_time` / `idx_audit_operation_time` | 主键/普通/普通 | `audit_id` / `occurred_at` / `operation, occurred_at` | 审计按时间检索、按操作类型检索 | 宪法三 |

**索引设计原则**：① 每条索引都必须指向第 7.2 节的一个目标查询或一个外键/唯一性需求；② 不为"可能有用"建索引；③ 等值列在前、范围列在后；④ 四个视图中不含索引提示，其性能依赖基表索引与两阶段聚合。

### 7.2 目标查询与预期访问计划

| 编号 | 目标查询（示意） | 预期 `type` | 预期 `key` | 判定标准 |
| --- | --- | --- | --- | --- |
| Q1 | `SELECT * FROM attack_log WHERE session_id = ? ORDER BY event_time, event_id` | `ref` | `idx_log_session_time` | 不出现 `ALL`，不出现 `Using filesort`（排序由索引前缀提供） |
| Q2 | `SELECT * FROM attack_log WHERE source_ip = ? AND event_time >= ? AND event_time < ? ORDER BY event_time` | `range` | `idx_log_source_time` | `rows` 约为该来源窗口内事件数；`Extra` 含 `Using index condition` 可接受 |
| Q3 | `SELECT * FROM alerts WHERE severity = 'critical' AND created_at >= ? ORDER BY created_at DESC LIMIT 50` | `range` | `idx_alert_level_time` | 使用索引反向扫描，`rows` 为严重级告警量级，无临时表 |
| Q4 | `SELECT DATE(created_at) d, COUNT(*) FROM rule_hits WHERE rule_id = ? AND created_at >= ? GROUP BY DATE(created_at)` | `range` | `idx_hit_rule_time` | 仅对索引列做范围过滤；`Using temporary; Using filesort` 可接受（分组需临时结构），但扫描行数必须受 `rule_id + 时间范围` 限制 |
| Q5 | `SELECT ... FROM attack_log WHERE event_uuid = ?` | `const` | `uk_attack_log_event_uuid` | 幂等短路查询必须 `const` |
| Q6 | `SELECT attacker_id FROM attacker_profile WHERE source_ip = ?` | `const` | `uk_attacker_profile_source_ip` | 画像定位必须 `const` |
| Q7 | `SELECT alert_id, occurrence_count FROM alerts WHERE dedup_key = ?` / Upsert | `const` | `uk_alerts_dedup_key` | 去重必须走唯一索引 |
| Q8 | `SELECT ... FROM sessions WHERE session_status = 'active' AND started_at >= ?` | `range` | `idx_sessions_status_started` | 巡检查询命中范围索引 |
| Q9 | `SELECT COUNT(*), COUNT(DISTINCT session_id) FROM sessions WHERE started_at >= ?` | `range` | `idx_sessions_started` | 首页概览聚合不扫全表（数据量增长后仍可用） |
| Q10 | 四个视图的整体查询 | `ALL`/`index` 可接受 | 依赖聚合 | 视图不做物化，演示规模（几千至几万事件）下允许扫描基表；页面必须带 `LIMIT` 且设置 `max_execution_time`，禁止无界导出（宪法四） |

### 7.3 EXPLAIN 验证方法与记录模板

**前置条件**

1. 数据集：≥3 000 条 `attack_log`、≥200 个 `sessions`、≥500 条 `rule_hits`、≥100 条 `alerts`、≥50 条 `attacker_profile`，覆盖 ≥10 个来源地址与 ≥5 个自然日；数据由固定合成样本 + 模拟器生成，可重复。
2. 执行 `ANALYZE TABLE attack_log, alerts, rule_hits, sessions, attacker_profile;` 更新统计信息。
3. 关闭无关干扰：固定 `sql_mode`、固定会话时区；MySQL 8.0 已移除查询缓存，无需处理。
4. 每条查询先执行一次预热（缓冲池加载），再执行 `EXPLAIN`、`EXPLAIN FORMAT=TREE`、`EXPLAIN ANALYZE`（8.0.18+ 可用，8.4 可用）各一次。

**索引前后对比（至少两组，对应 FR-035/SC-013）**

推荐使用 MySQL 8 的**不可见索引**做无损对比，避免反复建删索引污染统计信息：

```sql
-- 第 1 组：按会话重建时间线
ALTER TABLE attack_log ALTER INDEX idx_log_session_time INVISIBLE;
EXPLAIN ANALYZE SELECT * FROM attack_log WHERE session_id = ? ORDER BY event_time, event_id;
ALTER TABLE attack_log ALTER INDEX idx_log_session_time VISIBLE;
EXPLAIN ANALYZE SELECT * FROM attack_log WHERE session_id = ? ORDER BY event_time, event_id;

-- 第 2 组：筛选近期高等级告警
ALTER TABLE alerts ALTER INDEX idx_alert_level_time INVISIBLE;
EXPLAIN ANALYZE SELECT * FROM alerts WHERE severity = 'critical' AND created_at >= ? ORDER BY created_at DESC LIMIT 50;
ALTER TABLE alerts ALTER INDEX idx_alert_level_time VISIBLE;
EXPLAIN ANALYZE SELECT * FROM alerts WHERE severity = 'critical' AND created_at >= ? ORDER BY created_at DESC LIMIT 50;
```

也可以采用"先灌数据后建索引"的方式对比（等价、更直观），两种方式都必须固定同一份数据与同一组参数。

**记录模板（列定义）**

| 记录列 | 含义 | 取值要求 |
| --- | --- | --- |
| `组号` | 对比组编号 | G1 / G2 |
| `查询编号` | Q1–Q10 | 与 7.2 对应 |
| `索引状态` | 索引可用性 | `before`（无可用索引/INVISIBLE）/ `after`（可见） |
| `type` | 访问类型 | `const/eq_ref/ref/range/index/ALL` |
| `possible_keys` / `key` | 候选与实际使用索引 | 实际索引名必须与预期一致 |
| `key_len` | 使用索引长度（字节） | 记录实测值，用于核对联合索引用到第几列 |
| `rows` | 估算扫描行数 | 记录实测值 |
| `filtered` | 过滤后比例（%） | 记录实测值 |
| `Extra` | 附加信息 | 关注 `Using filesort` / `Using temporary` / `Using index condition` |
| `EXPLAIN ANALYZE 实际耗时(ms)` | 实测执行时间 | 取 5 次中位数，注明数据版本与机器配置 |
| `结论` | 计划是否变化、是否达标 | 按 7.2 判定标准填写 |

**示例记录（格式示意，非实测值）**

| 组号 | 查询编号 | 索引状态 | type | key | key_len | rows | Extra | 实际耗时(ms) | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | Q1 | before | `ALL` | `NULL` | `NULL` | 3000 | `Using where; Using filesort` | 12.4 | 全表扫描 + 排序，未达标 |
| G1 | Q1 | after | `ref` | `idx_log_session_time` | 37 | 18 | `NULL` | 0.6 | 计划由全表变为索引查找，达标 |
| G2 | Q3 | before | `ALL` | `NULL` | `NULL` | 100 | `Using where; Using filesort` | 1.1 | 未达标 |
| G2 | Q3 | after | `range` | `idx_alert_level_time` | 10 | 12 | `Using index condition` | 0.3 | 命中范围索引，达标 |

> 说明：上表数值仅用于说明记录格式，正式数据必须在实现阶段按固定数据集实测填写，并保存在 `docs/db/explain/`（该目录由实现阶段创建，本文档不创建任何文件）。答辩材料必须同时给出"数据规模、查询参数、机器配置"，否则对比无意义。

### 7.4 关于反规范化、视图扫描与约束边界

1. **`attack_log.source_ip` 冗余**（宪法允许并记录动机）：事件按来源与时间检索是最热的规则窗口查询（R01/R02），若每次 `JOIN sessions` 会放大扫描并引入额外锁；来源地址在会话生命周期内不变，因此作为"会话属性快照"冗余存储在事件行，写入事务内从会话行复制。一致性由写入顺序与 12.6 校验脚本保证。
2. **视图不做物化**：四个视图是实时聚合，规模在演示范围内可接受；不在本版引入汇总表（会带来双写一致性问题）。演进方向见第 15 章。
3. **禁止无界扫描**：所有页面查询必须带 `LIMIT`；`app_ro` 连接设置 `max_execution_time`（默认 5 000 ms），超时由数据库中止（FR-042/宪法四）。
4. **`CHECK` 的边界**：`CHECK` 只能约束单行，跨表规则见 5.6；不要试图用触发器补跨表约束（会引入隐式写入、审计与死锁复杂度）。

---

## 8. 事务边界、隔离级别、幂等与并发控制

### 8.1 事务边界清单

| 事务 | 触发 | 涉及表与操作 | 隔离级别 | 失败处理 |
| --- | --- | --- | --- | --- |
| T1 事件写入 | 每条标准事件（connect/auth/query/disconnect） | `sessions`（INSERT/UPDATE）、`attack_log`（INSERT）、`rule_hits`（INSERT）、`attacker_profile`（UPSERT+重算）、`attacker_intent`（UPSERT）、`alerts`（UPSERT） | `READ COMMITTED` | 全部回滚；可重试错误按 8.5 重试；返回明确错误码 |
| T2 告警已读 | 观察者标记已读（FR-058） | `alerts`（UPDATE）、`audit_log`（INSERT） | `READ COMMITTED` | 单行更新失败即回滚，返回失败 |
| T3 规则版本变更 | 管理员停用/调阈值/改权重 | `detection_rules`（旧行 UPDATE enabled=0、新行 INSERT）、`audit_log`（INSERT） | `READ COMMITTED` | 回滚，规则保持旧版本；唯一约束防止出现两个启用版本 |
| T4 演示重置 | 演示前重置（FR-040） | `alerts`/`rule_hits`/`attack_log`/`attacker_intent`/`attacker_profile`/`sessions`（DELETE）、`audit_log`（INSERT） | `READ COMMITTED` | 整体回滚到重置前（8.6） |
| T5 保留清理 | 定时清理任务（FR-020） | 按 13.2 顺序分批 DELETE、`audit_log`（INSERT） | `READ COMMITTED` | 当前批次回滚，已提交批次保留；下轮继续 |
| T6 会话超时回收 | 后台巡检 | `sessions`（UPDATE，置 timeout/ended_at） | `READ COMMITTED` | 回滚，下一轮重试 |

**显式事务要求**：`app_rw` 连接 `autocommit=0`，所有业务写操作必须显式 `START TRANSACTION ... COMMIT/ROLLBACK`；禁止依赖隐式提交（例如误用 `TRUNCATE`、`CREATE` 等会隐式提交的语句，见 8.6）。

### 8.2 隔离级别选择与理由

| 连接类型 | 隔离级别 | 理由 |
| --- | --- | --- |
| `app_rw`（诱饵服务写入、分析写入） | `READ COMMITTED` | ① 事件写入事务是"少量行读 + 多表写"，不需要事务级一致性快照；② RC 下普通范围扫描不加间隙锁（仅在唯一键冲突检查与 FK 检查时短暂加锁），可显著降低与画像热点行 Upsert 的死锁概率，而默认 RR 的间隙锁会在并发插入时互相阻塞；③ 幂等与计数正确性由唯一约束 + 行锁保证，不依赖 RR；④ 已提交数据立即可见，告警/画像在下一事件即可读到最新值，符合演示预期 |
| `app_ro`（控制台只读、答辩查询） | `REPEATABLE READ`（默认） | 同一页面可能连续多条 SELECT（概览 + 列表 + 详情），RR 提供事务级一致快照，避免同一屏数据出现"半更新"错位；视图聚合查询也受益于稳定快照 |
| `migrate`（DDL/迁移/种子） | `REPEATABLE READ`（默认） | DDL 隐式提交，事务语义有限；种子脚本按单事务批量执行，保持一致 |
| `backup`（备份） | `REPEATABLE READ` + `--single-transaction` | 一致性快照备份，备份期间不阻塞业务写入 |

**设置方式**（连接初始化，实现阶段固化到驱动配置）：

```sql
SET SESSION time_zone = '+00:00';
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;  -- 仅 app_rw
SET SESSION innodb_lock_wait_timeout = 5;
SET SESSION max_execution_time = 5000;                   -- 仅 app_ro，单位毫秒
```

禁止事项：事务执行中途切换隔离级别（`SET TRANSACTION` 只对下一个事务生效）；使用 `READ UNCOMMITTED`；在业务事务内执行 DDL；跨事务持有行锁等待人工操作。

### 8.3 事件写入事务（T1）详细步骤

| 步骤 | 操作 | 锁 / 约束要点 |
| --- | --- | --- |
| 0 | 连接初始化：UTC 时区、RC、`autocommit=0`、锁等待 5s | 健康检查断言 `@@session.time_zone = '+00:00'` |
| 1 | `START TRANSACTION` | —— |
| 2 | 会话定位：`connect` 事件执行 `INSERT sessions(...)`；其他事件执行 `SELECT ... FROM sessions WHERE session_id = ? FOR UPDATE` | `connect` 时若 `session_id` 重复 → 回滚并返回"会话编号冲突"，不得覆盖已有会话（边界情况）；其他事件无行 → 回滚返回"未知会话" |
| 3 | `INSERT attack_log(...)`，`source_ip` 从会话行复制，`sql_statement` 按 64K 上限截断并置 `payload_truncated` | 唯一键 `uk_attack_log_event_uuid` 是幂等裁决点（8.4） |
| 4 | 规则判定：读取 `detection_rules WHERE enabled = 1`（走 `uk_detection_rules_enabled_code` / `idx_detection_rules_intent`），按第 9、10 章口径计算本事件命中；窗口统计只读取本来源/本会话窗口（走 `idx_log_source_time` / `idx_log_session_time`） | 只读，不加锁；规则行可被并发停用，读取到的版本即"本事件采用版本" |
| 5 | `INSERT rule_hits(...)`，写入 `rule_id/rule_code/intent_type/rule_version/risk_weight/evidence_summary/triggered_at`；重复键用 `ON DUPLICATE KEY UPDATE hit_id = hit_id` 空更新 | `uk_rule_hits_event_rule_version` 保证重复分析不重复插入 |
| 6 | 画像 Upsert：`INSERT attacker_profile ... ON DUPLICATE KEY UPDATE attacker_id = LAST_INSERT_ID(attacker_id), last_seen = GREATEST(last_seen, VALUES(last_seen)), total_* = total_* + 1 ...` | `LAST_INSERT_ID(expr)` 惯用法在"新插入"和"命中已有行"两种路径都返回正确的 `attacker_id`；同一来源行是热点，事务必须短 |
| 7 | 按 9.2 公式重算画像分与证据摘要：`UPDATE attacker_profile SET risk_score = ?, evidence_summary = ?, last_calculated_at = ?` | 重算而非累加，避免漂移；`risk_level` 由生成列自动维护，禁止写入 |
| 8 | 意图 Upsert：对本次命中的每个 `intent_type` 执行 `INSERT attacker_intent ... ON DUPLICATE KEY UPDATE intent_score = ?, evidence_count = ?, last_detected_at = GREATEST(last_detected_at, VALUES(last_detected_at))` | `uk_attacker_intent_attacker_type` 定位；分数按 9.2 重算 |
| 9 | 告警 Upsert：对符合 9.4 条件的首次命中执行 `INSERT alerts ... ON DUPLICATE KEY UPDATE last_seen_at = GREATEST(last_seen_at, VALUES(last_seen_at)), occurrence_count = occurrence_count + 1, latest_hit_id = VALUES(latest_hit_id), updated_at = CURRENT_TIMESTAMP(6)` | 唯一键 `uk_alerts_dedup_key`；`session_id/attacker_id` 必须在步骤 2、6 之后才可用 |
| 10 | 会话计数与最高分：`UPDATE sessions SET request_count = request_count + 1, max_risk_score = GREATEST(max_risk_score, ?), ended_at = ?, session_status = ? WHERE session_id = ?`（`disconnect` 事件置 `closed` 并写 `ended_at`） | 与步骤 2 的行锁同一行，事务内串行 |
| 11 | `COMMIT`；返回 `(event_id, is_new = true, hit_count, alert_ids, risk_score)` | —— |
| E | 任一步异常：`ROLLBACK`；写应用日志（`event_uuid`、阶段、`errno`、`sqlstate`、重试次数）；按 8.5 判定是否重试 | 不得吞异常、不得部分提交（FR-039/FR-042） |

### 8.4 幂等处理伪流程（以 event_uuid 为唯一真相）

1. **生成时机**：捕获层在把协议交互构造成标准事件时，一次性生成 UUID v4 作为 `event_uuid`；该值随事件对象传递，任何重试/重投复用同一值，**不得重新生成**。
2. **先插入后判定**：事务内直接 `INSERT attack_log`，让唯一索引成为唯一裁决者；**禁止**"先 SELECT 是否存在再 INSERT"（两步之间存在竞态窗口）。
3. **冲突识别**：捕获 `errno 1062 (ER_DUP_ENTRY)` 且键名为 `uk_attack_log_event_uuid` → 立即 `ROLLBACK`（撤销本次已做的会话计数、命中、告警、画像更新），再执行 `SELECT event_id, session_id FROM attack_log WHERE event_uuid = ?`。
4. **返回语义**：向调用方返回已有 `event_id` 且 `is_new = false`；调用方必须区分"已存在"与"本次新增"（FR-041），不得再次累计计数或风险贡献。
5. **非幂等冲突**：若 1062 命中的是其他唯一键（如 `uk_alerts_dedup_key`、`uk_attacker_profile_source_ip`），说明是**正常并发/重复触发**，不是幂等重放；这类写入一律走 `ON DUPLICATE KEY UPDATE` 路径，事务继续。
6. **事务外重试**：死锁/锁等待超时导致的重试复用同一 `event_uuid`；即使第一次实际已提交，第二次插入必然冲突并得到 `is_new = false`，结果仍然正确。
7. **边界**：`event_uuid` 格式非法（非 36 字符 UUID）在入库前被应用拒绝；`event_uuid` 唯一性不依赖应用内存缓存，后续多实例部署同样成立。

### 8.5 并发、死锁与重试策略

| 项目 | 策略 |
| --- | --- |
| 锁顺序 | 固定为 `sessions → attack_log → rule_hits → attacker_profile → attacker_intent → alerts`，禁止在事务中反向访问，消除交叉锁序死锁 |
| 热点行 | 同一 `source_ip` 的 `attacker_profile` 行是唯一热点；缓解手段：事务内不做网络/文件 IO、单来源事件按队列串行处理（或应用层按 `source_ip` 分片）、事务目标时长 <100 ms |
| 重试范围 | 仅 `1213 ER_LOCK_DEADLOCK`、`1205 ER_LOCK_WAIT_TIMEOUT`，以及由并发导致的短暂 gap 冲突 |
| 重试次数 | 最多 3 次（首次 + 3 次重试） |
| 退避 | 50 ms → 200 ms → 800 ms，附加 ±20% 随机抖动，避免重试风暴 |
| 不重试 | `1062` 之外的约束错误：`1452` 外键失败、`3819` CHECK 失败、类型/长度错误——属数据缺陷，重试无意义，必须暴露给调用方 |
| 重试幂等性 | 每次重试重新 `BEGIN` 并重跑完整流程；因复用 `event_uuid`，重复提交仍收敛为一条日志（8.4） |
| 超限处理 | 3 次仍失败：返回明确错误码（FR-042），把事件放入待重投队列（持久化到本地文件/内存队列），后台任务限速重投；**禁止静默丢弃** |
| 监控 | 应用日志记录每次重试的阶段与 `errno`；演示环境为单机低并发，正常情况死锁计数应为 0 |

### 8.6 演示重置事务（T4）

**依赖顺序（必须严格按此顺序删除，受 `RESTRICT` 外键约束）**

| 顺序 | 语句 | 被删除行依赖的外键 |
| --- | --- | --- |
| 1 | `DELETE FROM alerts;` | `fk_alert_session`、`fk_alert_attacker`、`fk_alert_rule`、`fk_alert_latest_hit` |
| 2 | `DELETE FROM rule_hits;` | `fk_hit_log`、`fk_hit_session`、`fk_hit_rule`；且 `alerts.latest_hit_id` 已在上一步清空 |
| 3 | `DELETE FROM attack_log;` | `fk_log_session` |
| 4 | `DELETE FROM attacker_intent;` | `fk_intent_profile` |
| 5 | `DELETE FROM attacker_profile;` | 被 `alerts`、`attacker_intent` 引用，二者已清空 |
| 6 | `DELETE FROM sessions;` | 被 `attack_log`、`rule_hits`、`alerts` 引用，均已清空 |
| 7 | `INSERT INTO audit_log(...) VALUES(..., 'reset', 'success', '各表删除行数摘要');` | 审计留痕 |

**保留对象**：`detection_rules`（规则种子，FR-040 要求保留）、`fake_users`/`fake_orders`/`fake_config`（诱饵种子）、`audit_log`（审计不可删除）。

**实现要求**

1. 使用 `DELETE` 而非 `TRUNCATE`：`TRUNCATE` 属 DDL，会**隐式提交**并破坏事务原子性，无法回滚（FR-040 明确要求"中途异常时整体回滚"）。
2. 整个重置是一个显式事务（RC），期间禁止诱饵服务写入（维护窗口），或用 `GET_LOCK('honeypot_reset', 10)` 与写入路径串行化。
3. 事务内执行断言：`detection_rules` 行数不变、三张 `fake_*` 行数不变、目标 6 表行数为 0；断言失败立即 `ROLLBACK` 并报错。
4. 结束后再断言一次并写 `audit_log`；失败场景（回滚）也要写一条 `result='failure'` 的审计记录（审计写入需在回滚之后单独提交，避免被回滚）。
5. 演示数据备份：重置前执行 `mysqldump --single-transaction` 生成干净副本；`honeypot_demo` 与 `honeypot_dev` 分离（FR-072/FR-075）。

### 8.7 失败可观测性要求

- **应用日志字段**：UTC 时间、`trace_id`、`event_uuid`、`session_id`、`stage`（connect/insert_log/analyze/insert_hit/profile/intent/alert/commit）、`errno`、`sqlstate`、`attempt`、耗时、脱敏错误摘要。
- **禁止记录**：任何口令（系统从不存储）、可复用的凭据、完整攻击载荷原文；如需排障，记录 `normalized_sql` 的长度与 SHA-256 前 16 位。
- **业务事件不静默丢失**：写入失败必须返回错误码并在应用日志中保留可定位信息（FR-019/FR-042）；协议解析失败不得影响持久化层可用性（宪法"技术栈与工程约束"）。

---

## 9. 风险评分与告警生成算法

### 9.1 计分口径（必须先固定，再实现）

1. **计分单元是 `rule_code`，不是命中行**：同一规则在一个统计范围内重复命中只计一次权重，取该规则命中的**最大权重快照**（`MAX(risk_weight)`）。
2. **权重取快照**：使用 `rule_hits.risk_weight`（命中当时的权重），规则后续调整权重不改变历史分数（FR-052）。
3. **统计范围三档**：会话（`session_id`）、意图（某画像的某 `intent_type`）、画像（某 `source_ip` 的全部命中）。
4. **封顶**：结果一律 `LEAST(100, ...)`，且每一分都能追溯到具体 `rule_hits` 行（FR-047）。
5. **确定性**：给定同一批 `rule_hits`，三档分数与等级唯一确定；AI 不参与计算（FR-053）。

### 9.2 确定性公式

**（1）会话风险分**（统计范围：该会话内全部命中）

```
risk_session(s) = LEAST(100, Σ_{c ∈ rule_codes(s)} MAX_{h ∈ hits(s, c)} h.risk_weight)
```

```sql
SELECT LEAST(100, SUM(t.rule_weight)) AS risk_session
FROM (
  SELECT rh.rule_code, MAX(rh.risk_weight) AS rule_weight
  FROM rule_hits AS rh
  WHERE rh.session_id = ?
  GROUP BY rh.rule_code
) AS t;
```

**（2）意图风险分**（统计范围：该画像该意图下的全部命中，按 `intent_type` 快照过滤）

```
risk_intent(a, i) = LEAST(100, Σ_{c ∈ rules(i)} MAX_{h ∈ hits(a, c, i)} h.risk_weight)
```

```sql
SELECT LEAST(100, SUM(t.rule_weight)) AS risk_intent
FROM (
  SELECT rh.rule_code, MAX(rh.risk_weight) AS rule_weight
  FROM rule_hits AS rh
  JOIN attack_log AS al ON al.event_id = rh.event_id
  WHERE al.source_ip = ?
    AND rh.intent_type = ?
  GROUP BY rh.rule_code
) AS t;
```

**（3）画像风险分**（统计范围：该来源全部命中）

```
risk_profile(ip) = LEAST(100, Σ_{c ∈ rule_codes(ip)} MAX_{h ∈ hits(ip, c)} h.risk_weight)
```

```sql
SELECT LEAST(100, SUM(t.rule_weight)) AS risk_profile
FROM (
  SELECT rh.rule_code, MAX(rh.risk_weight) AS rule_weight
  FROM rule_hits AS rh
  JOIN attack_log AS al ON al.event_id = rh.event_id
  WHERE al.source_ip = ?
  GROUP BY rh.rule_code
) AS t;
```

**口径说明**：画像分按"规则维度"直接计算，而不是"把各意图分相加再封顶"。两者在单意图被封顶时会不同（例如某意图已封顶 100，其余意图仍有贡献），本设计**以画像公式为准**，意图分只用于排序与展示，不参与画像分合成。该差异必须在答辩口径中说明，避免"分数对不上"的质疑。

### 9.3 风险等级映射（唯一口径）

| 分数区间 | 等级枚举 | 中文 | 生成列 / 视图 CASE |
| --- | --- | --- | --- |
| 0–29 | `low` | 低风险 | `risk_score < 30` |
| 30–59 | `medium` | 中风险 | `risk_score >= 30 AND risk_score < 60` |
| 60–79 | `high` | 高风险 | `risk_score >= 60 AND risk_score < 80` |
| 80–100 | `critical` | 严重风险 | `risk_score >= 80` |

区间为左闭右开（整数分数下无歧义），与 FR-048 完全一致；`attacker_profile.risk_level` 生成列、四个视图中的 CASE 均使用同一阈值，不得各自维护。

### 9.4 告警生成条件与等级映射

**生成条件**：规则命中且其 `intent_type ∈ { bruteforce, data_dump, destructive }`（对应 R02/R04/R05），**首次命中即生成告警**；R01（scanning）与 R03（recon）只进入画像/意图/证据，不生成告警。

| 规则编码 | 意图 | 告警类型 `alert_type` | 等级 `severity` | 中文等级 |
| --- | --- | --- | --- | --- |
| R02 | bruteforce | `bruteforce` | `medium` | 中 |
| R04 | data_dump | `data_dump` | `high` | 高 |
| R05 | destructive | `destructive` | `critical` | 严重 |
| 其他（未来新增的告警类规则） | 三类意图之一 | 取意图 | `medium`（默认） | 中 |

**插入告警时写入的字段**：`dedup_key`、`session_id`（首次触发告警的会话）、`attacker_id`（步骤 6 得到的画像）、`rule_id`/`rule_code`、`latest_hit_id`（本次命中）、`alert_type`、`severity`、`title`（中文可读标题）、`evidence_summary`（含规则编码、时间、语句类型/统计值）、`first_seen_at = last_seen_at = triggered_at`、`occurrence_count = 1`、`is_read = 0`。

**重复触发时的更新语义**（`ON DUPLICATE KEY UPDATE`）：

| 列 | 是否更新 | 说明 |
| --- | --- | --- |
| `last_seen_at` | 是（`GREATEST`） | 最近触发时间前进 |
| `occurrence_count` | 是（`+1`） | 触发次数累加 |
| `latest_hit_id` | 是 | 证据指向最新命中 |
| `evidence_summary` | 是 | 用最新证据摘要刷新（保留可解释性） |
| `updated_at` | 是 | 运维可观测 |
| `first_seen_at` / `created_at` | 否 | 保留"首次"语义 |
| `severity` / `alert_type` / `rule_id` | 否 | 因去重键含 `rule_code`，同一键必为同一规则，等级固定；不引入隐式升级逻辑 |
| `session_id` | 否 | 保留首次触发会话，避免"告警漂移" |

> 演进方向（不在本版）：若将来希望"同一意图同日只产生一条告警"，可把去重键改为 `<alert_type>:<source_ip>:<date>`，并在重复触发时取最高 `severity`；届时需同时修改唯一约束与 `severity` 更新逻辑（记录于第 15 章）。

### 9.5 `dedup_key` 定义

- **格式**：`<rule_code>:<source_ip>:<YYYY-MM-DD>`。
- **各段规则**：`rule_code` 取快照编码（3–16 字符，大写 R 前缀）；`source_ip` 为已归一化为小写的文本形式（≤45 字符）；日期取 `triggered_at` 的 UTC 日期（`DATE(triggered_at)`），不使用本地时区。
- **示例**：`R05:192.0.2.10:2026-11-19`、`R04:2001:db8::10:2026-11-19`。
- **长度**：最坏 16 + 1 + 45 + 1 + 10 = 73 字符；列定义为 `VARCHAR(160)`，为未来扩展留余量。
- **唯一性**：`uk_alerts_dedup_key` 是去重的唯一防线；应用不做"先查后插"。
- **跨日行为**：同一攻击跨越 UTC 日界会产生两条告警（各自日期的去重键），这是有意的业务取舍——便于按日统计与演示"重复触发去重"；该行为写入演示说明（第 15 章记录权衡）。
- **重放测试**：固定样本重复导入两次，第二次必须是 `occurrence_count` 从 1 变 2、`alert_id` 不变、`alerts` 行数不变（SC-011/FR-059）。

### 9.6 计算示例（可手算，验收基准）

假设五条规则权重 R01=10、R02=25、R03=15、R04=25、R05=35：

| 场景 | 命中（规则/权重） | 会话分 | 画像分 | 等级 | 告警 |
| --- | --- | --- | --- | --- | --- |
| S1 仅踩点 | R03(15) | 15 | 15 | 低 | 0 |
| S2 扫描 + 踩点 | R01(10) + R03(15) | 25 | 25 | 低 | 0 |
| S3 爆破 + 拖库 | R02(25) + R04(25) | 50 | 50 | 中 | 2（R02 中、R04 高） |
| S4 爆破 + 拖库 + 破坏 | R02(25) + R04(25) + R05(35) | 85 | 85 | 严重 | 3（中、高、严重） |
| S5 五规则全命中 | 10+25+15+25+35 = 110 | 100（封顶） | 100 | 严重 | 3 |
| S6 同一 R05 命中 3 个事件 | R05(35) × 3 行 | 35（不重复累计） | 35 | 中 | 1 条，`occurrence_count = 3` |
| S7 规则全部停用 | 无 | 0 | 0 | 低 | 0 |
| S8 R05 权重由 35 调为 20 后重放历史 | 历史命中仍为 35 | 35 | 35 | 中 | 历史告警等级不变 |
| S9 同一来源两个会话分别命中 R03 与 R04 | R03 + R04 | 会话 A=15，会话 B=25 | 40 | 中 | 1（R04 高） |

**边界约定**：无命中 → 0 分、等级 `low`、无标签无告警；分数封顶 100 且仍可逐分追溯；规则全部停用 → 分数 0（历史命中不参与新口径重算，除非显式重算，见 10.3）。

---

## 10. 规则种子数据与规则版本管理

### 10.1 五条种子规则（`rule_version = 1`，`enabled = 1`）

| 规则编码 | 规则名称 | `rule_type` | `intent_type` | `risk_weight` | 版本 | 启用 | 规则说明（`description`） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | 短时高频连接扫描 | `frequency` | `scanning` | 10 | 1 | 1 | 60 秒内同一来源连接不少于 10 次且无有效 SQL，典型端口/服务扫描特征 |
| R02 | 短时多凭据认证爆破 | `frequency` | `bruteforce` | 25 | 1 | 1 | 5 分钟内同一来源认证尝试不少于 8 次，且不同用户名与测试标识组合不少于 5 组 |
| R03 | 元数据与结构探测 | `keyword` | `recon` | 15 | 1 | 1 | 出现 SHOW TABLES、SHOW DATABASES、SHOW COLUMNS、DESCRIBE、information_schema 查询 |
| R04 | 会话级批量数据读取 | `volume` | `data_dump` | 25 | 1 | 1 | 同一会话连续 SELECT 不少于 5 次，或会话累计返回行数超过 1000 行 |
| R05 | 破坏性写操作尝试 | `keyword` | `destructive` | 35 | 1 | 1 | 出现 DROP、TRUNCATE、DELETE、UPDATE、INSERT（诱饵层拒绝执行，仅记录并告警） |

种子由迁移 `0003_seed_rules_and_fakes` 写入，**不参与演示重置**（8.6）。

### 10.2 `parameters_json` 设计（R01–R05）

参数只描述**单条规则内部的阈值与时间窗口**，不保存任何业务实体列表（FR-027）。所有阈值均为"达到即命中"（`>=`）；时间窗口以秒为单位，窗口起点为"当前事件的 `event_time` 向前回溯 `window_seconds`"，窗口内统计含当前事件。

**R01（frequency / scanning）**

```json
{"scope": "source_ip", "window_seconds": 60, "min_connect_count": 10, "max_valid_sql_count": 0, "boundary": "inclusive"}
```

| 键 | 类型 | 语义 | 边界 |
| --- | --- | --- | --- |
| `scope` | string | 统计范围：同一来源地址 | 固定 `source_ip` |
| `window_seconds` | int | 时间窗口长度（秒） | `>= 1` |
| `min_connect_count` | int | 窗口内 connect 事件最少数量 | `count >= 10` 命中 |
| `max_valid_sql_count` | int | 窗口内"有效 SQL"数量上限（有效 = query 且 status=success） | `<= 0` 才满足"无有效 SQL" |
| `boundary` | string | 阈值比较方式 | `inclusive` 表示含等号 |

**R02（frequency / bruteforce）**

```json
{"scope": "source_ip", "window_seconds": 300, "min_auth_attempts": 8, "min_distinct_credential_pairs": 5, "count_failed_only": false}
```

| 键 | 类型 | 语义 | 边界 |
| --- | --- | --- | --- |
| `scope` | string | 统计范围：同一来源地址 | 固定 `source_ip` |
| `window_seconds` | int | 时间窗口（秒） | 默认 300 |
| `min_auth_attempts` | int | 窗口内 auth 事件最少数量（含成功与失败） | `>= 8` 命中 |
| `min_distinct_credential_pairs` | int | 窗口内不同凭据组合数（`username` + `credential_test_id` 去重对） | `>= 5` 命中 |
| `count_failed_only` | bool | 是否仅统计失败认证 | `false` 表示成功与失败都计入 |

**R03（keyword / recon）**

```json
{"scope": "event", "match_target": "normalized_sql", "case_sensitive": false,
 "keywords": ["SHOW TABLES", "SHOW DATABASES", "SHOW COLUMNS", "SHOW FIELDS", "DESCRIBE", "DESC ", "INFORMATION_SCHEMA"],
 "max_hits_per_event": 1}
```

| 键 | 类型 | 语义 | 边界 |
| --- | --- | --- | --- |
| `scope` | string | 逐事件判定 | 固定 `event` |
| `match_target` | string | 匹配字段：标准化 SQL | 固定 `normalized_sql` |
| `case_sensitive` | bool | 是否区分大小写 | `false`：统一转大写后匹配 |
| `keywords` | string[] | 关键短语列表 | 任一命中即命中 |
| `max_hits_per_event` | int | 同一事件最多产生命中行数 | 固定 1，避免单事件刷爆命中表 |

**R04（volume / data_dump）**

```json
{"scope": "session", "window_seconds": 300, "min_consecutive_select": 5, "session_returned_rows_threshold": 1000, "count_scope": "session_cumulative"}
```

| 键 | 类型 | 语义 | 边界 |
| --- | --- | --- | --- |
| `scope` | string | 统计范围：同一会话 | 固定 `session` |
| `window_seconds` | int | 窗口（秒），既用于"连续 SELECT"也用于滑动统计 | 默认 300 |
| `min_consecutive_select` | int | 窗口内连续 SELECT 事件最少数量（中间无 auth/写操作打断） | `>= 5` 命中 |
| `session_returned_rows_threshold` | int | 会话累计返回行数阈值 | `> 1000` 命中（严格大于，避免边界抖动） |
| `count_scope` | string | 行数累计口径 | 固定 `session_cumulative`（整会话累计，不受窗口限制） |

**R05（keyword / destructive）**

```json
{"scope": "event", "match_target": "normalized_sql", "case_sensitive": false, "word_boundary": true,
 "keywords": ["DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT"],
 "count_status": ["denied", "error", "success"]}
```

| 键 | 类型 | 语义 | 边界 |
| --- | --- | --- | --- |
| `scope` | string | 逐事件判定 | 固定 `event` |
| `match_target` | string | 匹配字段：标准化 SQL | 固定 `normalized_sql` |
| `case_sensitive` | bool | 是否区分大小写 | `false` |
| `word_boundary` | bool | 是否按词边界匹配（避免 `UPDATE_TIME` 误报） | `true` |
| `keywords` | string[] | 写操作关键字 | 任一命中即命中 |
| `count_status` | string[] | 计入命中的处理状态 | 诱饵层拒绝执行时仍计入（`denied` 是预期结果） |

**参数校验规则**（应用层 + 迁移校验脚本）：

1. `parameters_json` 必须是 JSON 对象（`JSON_TYPE(...) = 'OBJECT'`），且包含该 `rule_type` 的必需键；缺失键的规则视为配置错误，分析层跳过并记录告警日志（不静默）。
2. 数值参数必须为正整数、单位明确（秒、次数、行数），禁止使用浮点阈值。
3. 修改任何阈值/权重都必须**新建版本**，禁止就地 `UPDATE parameters_json`（10.3）；`JSON` 列本身不限制原地修改，流程约束由迁移脚本评审与 `audit_log` 保证。

### 10.3 规则版本管理

**版本唯一与启用唯一**

- `uk_detection_rules_code_version` 保证同一编码的版本号唯一，规则版本不可覆盖。
- `uk_detection_rules_enabled_code`（生成列 `enabled_rule_code`）保证**同一 `rule_code` 至多一个启用版本**，从而消除"分析时多个启用版本并列"的歧义；"取启用的最大版本"在本约束下退化为唯一命中。

**变更流程（T3 事务，RC）**

1. `START TRANSACTION`；
2. `UPDATE detection_rules SET enabled = 0 WHERE rule_code = 'R0x' AND enabled = 1;`（先停用旧版本，否则新版本插入会触发启用唯一约束冲突）；
3. `INSERT detection_rules (rule_code, rule_name, rule_type, intent_type, parameters_json, risk_weight, rule_version, enabled, description) VALUES (..., 'R0x', ..., 旧版本号 + 1, 1, ...);`
4. `INSERT audit_log(...) VALUES (..., 'rule_change', 'success', 'R0x vN -> vN+1，变更参数与权重');`
5. `COMMIT`；任一步失败整体回滚，规则保持旧版本可用。

**分析取版本**：`SELECT ... FROM detection_rules WHERE enabled = 1;`（每编码最多一行，可整表缓存到分析进程内存，规则变更后失效重载）。

**历史命中快照**：`rule_hits.rule_version/risk_weight/intent_type` 一旦写入不再随规则变更回写；规则改版后旧命中仍按旧权重计分（S8 场景）。

**回退方式**：不允许"把旧版本改回启用"来覆盖当前版本（会丢失版本历史）；回退 = 新建一个版本（版本号继续递增，参数复制旧版），流程同上。

**重算历史数据**：默认禁止静默重算。必须同时明确三项并写入 `audit_log`（`operation='manual_query'` 不适用，重算使用 `rule_change` 的扩展说明）：
1. **重算范围**：时间区间、来源地址或会话编号集合；
2. **规则版本口径**：使用命中快照（`rule_hits` 原值）还是当前启用版本重新判定；
3. **结果写回口径**：仅生成报表（不写回）或更新 `attacker_profile`/`attacker_intent`（并记录旧值）。
未满足三项的重算视为流程缺陷（FR-052）。

**规则编码管理**：`R01`–`R05` 已分配且禁止复用；新增规则从 `R06` 起（FR-045 允许 5–8 条）；修改规则语义必须换新编码，不得复用旧编码改变含义。

### 10.4 诱饵种子数据（30 / 120 / 5）

**`fake_users`：30 条确定性生成规则**

| 字段 | 生成规则 | 示例 |
| --- | --- | --- |
| `id` | 1–30 自增 | `1` |
| `username` | `demo_user_` + 两位序号 | `demo_user_01` … `demo_user_30` |
| `email` | `demo_user_` + 两位序号 + `@example.test` | `demo_user_01@example.test` |
| `phone` | `199-0000-` + 四位序号（明显非真实号段） | `199-0000-0001` |
| `password_hash` | `TEST-ONLY$FAKEHASH$` + 32 位零填充序号（不可用伪哈希） | `TEST-ONLY$FAKEHASH$00000000000000000000000000000001` |
| `display_name` | `演示用户` + 两位序号 | `演示用户01` |
| `is_synthetic` | 恒为 1（检查约束强制） | `1` |
| `created_at` | 固定基准时刻 `2026-11-01 00:00:00`（UTC）起每行 +1 分钟 | `2026-11-01 00:00:00` |

示例行（其余 25 行按同一规则生成）：

| id | username | email | phone | password_hash | display_name |
| --- | --- | --- | --- | --- | --- |
| 1 | demo_user_01 | demo_user_01@example.test | 199-0000-0001 | TEST-ONLY$FAKEHASH$00000000000000000000000000000001 | 演示用户01 |
| 2 | demo_user_02 | demo_user_02@example.test | 199-0000-0002 | TEST-ONLY$FAKEHASH$00000000000000000000000000000002 | 演示用户02 |
| 3 | demo_user_03 | demo_user_03@example.test | 199-0000-0003 | TEST-ONLY$FAKEHASH$00000000000000000000000000000003 | 演示用户03 |
| 30 | demo_user_30 | demo_user_30@example.test | 199-0000-0030 | TEST-ONLY$FAKEHASH$00000000000000000000000000000030 | 演示用户30 |

**`fake_orders`：120 条确定性生成规则（30 用户 × 4 单）**

| 字段 | 生成规则 |
| --- | --- |
| `order_no` | `FAKE-202611-` + 五位序号（`00001`–`00120`） |
| `user_id` | `((序号 - 1) % 30) + 1`，保证每个诱饵用户恰好 4 单 |
| `amount` | 按 `序号 % 4` 循环取 `19.90 / 99.00 / 199.50 / 899.00`（固定值，不使用随机数，保证可重复） |
| `currency` | `CNY` |
| `order_status` | 按 `序号 % 10` 映射：0–4 `paid`（60 条）、5–6 `shipped`（24 条）、7–8 `pending`（24 条）、9 `cancelled`（12 条），另将序号 120 置 `refunded` 作为演示样例 |
| `remark` | `演示订单，仅用于蜜罐展示` 或 NULL（交替） |
| `is_synthetic` | 恒为 1 |
| `created_at` | `2026-11-01 00:00:00` + `序号 × 7` 分钟（UTC） |

示例行：

| order_no | user_id | amount | currency | order_status |
| --- | --- | --- | --- | --- |
| FAKE-202611-00001 | 1 | 19.90 | CNY | paid |
| FAKE-202611-00002 | 2 | 99.00 | CNY | paid |
| FAKE-202611-00003 | 3 | 199.50 | CNY | paid |
| FAKE-202611-00004 | 4 | 899.00 | CNY | paid |
| FAKE-202611-00120 | 30 | 899.00 | CNY | refunded |

**`fake_config`：5 条（全部以 `TEST-ONLY` 开头，检查约束强制）**

| `config_key` | `category` | `config_value` | `description` |
| --- | --- | --- | --- |
| `db.primary.connection_string` | `database` | `TEST-ONLY mysql://fake_admin:TEST-ONLY-NOT-A-REAL-PASSWORD@127.0.0.1:13307/fake_shop?connect_timeout=1` | 伪造主库连接串：指向本机无效端口，口令为占位串，仅用于诱饵展示 |
| `db.replica.connection_string` | `database` | `TEST-ONLY mysql://fake_reader:TEST-ONLY-NOT-A-REAL-PASSWORD@127.0.0.1:13308/fake_shop?connect_timeout=1` | 伪造只读副本连接串：同样指向本机无效端口 |
| `mail.smtp.password` | `mail` | `TEST-ONLY-SMTP-PASSWORD-0000` | 伪造邮件服务口令占位，不可用于任何真实认证 |
| `api.payment.secret_key` | `api` | `TEST-ONLY-SK-fake0000000000000000` | 伪造支付接口密钥占位，格式像密钥但不可用 |
| `storage.s3.access_key` | `storage` | `TEST-ONLY-AKIA0000000000000000` | 伪造对象存储访问键占位，不可用 |

**安全红线自检（每次种子变更必须复核）**

1. 不含任何真实个人信息（姓名、真实邮箱、真实手机号、身份证号等）；邮箱只用 `example.test` 保留域名，手机号只用明显虚构号段。
2. 不含真实口令、真实密钥或可用凭据；`fake_users.password_hash` 由 `CHECK (LIKE 'TEST-ONLY$%')` 强制，`fake_config.config_value` 由 `CHECK (LIKE 'TEST-ONLY%')` 强制。
3. 连接串只指向 `127.0.0.1` 的**无监听端口**，不指向任何真实内网资产（FR-006/FR-080）。
4. 诱饵表不参与检测、画像与告警的任何计算，也不对外导出原始明文（FR-081/FR-082）。

### 10.5 种子脚本的可重复执行

| 脚本 | 幂等方式 | 说明 |
| --- | --- | --- |
| 规则种子 | `INSERT ... ON DUPLICATE KEY UPDATE rule_name = VALUES(rule_name), parameters_json = VALUES(parameters_json), ...`，唯一键 `(rule_code, rule_version)` | 重复执行不新增行、不改变行数；但**生产/演示库调整过规则后重跑会覆盖种子版本参数**，因此种子仅在初始化与重建时执行，日常调整走 T3 事务 |
| 诱饵种子 | 同上，按 `username` / `order_no` / `config_key` 唯一键 | 30 / 120 / 5 条行数可重复校验 |
| 数据库与账号 | `CREATE DATABASE IF NOT EXISTS`、`CREATE USER IF NOT EXISTS` | 账号口令必须由环境变量或交互输入注入，禁止写入仓库 |
| 视图 | `CREATE OR REPLACE VIEW` | 幂等；底层表结构变更后需重建 |
| 种子审计 | 每次种子执行写一条 `audit_log`（`operation='migration'`，`result='success'`） | 可追溯"哪次初始化写入了多少行" |

---

## 11. 数据库账号与权限矩阵

### 11.1 账号清单（四类，职责分离，最小权限）

| 账号（建议名） | 职责 | 允许的来源主机 | 认证插件 | 口令来源 |
| --- | --- | --- | --- | --- |
| `honeypot_migrate` | DDL、迁移、视图与种子执行 | 本机 `127.0.0.1`/`localhost`；Compose 隔离网段 `172.28.0.%`（仅迁移时） | `caching_sha2_password`（8.4 默认） | 环境变量 `HONEYPOT_MIGRATE_PASSWORD` |
| `honeypot_app_rw` | 诱饵服务与分析的业务读写 | 本机 `127.0.0.1`/`localhost`；Compose 隔离网段 `172.28.0.%` | `caching_sha2_password` | 环境变量 `HONEYPOT_APP_RW_PASSWORD` |
| `honeypot_app_ro` | 控制台与答辩查询（只读） | 本机 `127.0.0.1`/`localhost`；Compose 隔离网段 `172.28.0.%` | `caching_sha2_password` | 环境变量 `HONEYPOT_APP_RO_PASSWORD` |
| `honeypot_backup` | 备份（只读 + 锁表 + 视图） | 本机 `127.0.0.1`/`localhost`；Compose 隔离网段 `172.28.0.%` | `caching_sha2_password` | 环境变量 `HONEYPOT_BACKUP_PASSWORD` |

> **主机匹配约定**：本机进程连接优先使用 `127.0.0.1` 账号（`localhost` 仅用于 Unix socket）；Docker Compose 固定隔离网段 `172.28.0.0/24`，容器互访与宿主机端口映射访问时 MySQL 看到的来源地址属于 `172.28.0.%`，因此 `db/init` 必须同时为四类账号创建该网段账号。禁止使用 `%` 或公网网段（FR-079）。
>
> MySQL 8.4 默认禁用 `mysql_native_password`，四类账号一律使用默认 `caching_sha2_password`。**绝不创建 `root` 用于应用**、绝不使用 `%` 通配主机，绝不授予 `GRANT OPTION`。
>
> **命名别名约定**：若实现阶段沿用更短的账号名（如 `honeypot_app` 对应 `app_rw`、`honeypot_ro` 对应 `app_ro`），必须在配置模板与运行说明中显式标注"简称 ↔ 本文件账号"的对应关系，且权限必须按 11.2 矩阵授予；**不得**为图省事使用 `GRANT ALL PRIVILEGES`，该写法会隐含 DDL 与 `GRANT` 之外的多余权限，违反宪法最小权限原则。
>
> 注意：诱饵层对外的"MySQL 账号"是**协议模拟层的虚构账号**（如 `demo_user_01`），只在诱饵内容中展示，**不会**在本实例中创建真实 MySQL 用户。

### 11.2 权限矩阵

图例：`S`=SELECT、`I`=INSERT、`U`=UPDATE、`D`=DELETE、`DDL`=CREATE/ALTER/DROP/INDEX/REFERENCES、`V`=CREATE VIEW/SHOW VIEW、`—`=无权限。

| 对象 | `honeypot_migrate` | `honeypot_app_rw` | `honeypot_app_ro` | `honeypot_backup` |
| --- | --- | --- | --- | --- |
| `sessions` | S I U D + DDL | S I U D | S | S |
| `attack_log` | S I U D + DDL | S I U D | S | S |
| `attacker_profile` | S I U D + DDL | S I U D | S | S |
| `attacker_intent` | S I U D + DDL | S I U D | S | S |
| `detection_rules` | S I U D + DDL | S I U | S | S |
| `rule_hits` | S I U D + DDL | S I U D | S | S |
| `alerts` | S I U D + DDL | S I U D | S | S |
| `fake_users` | S I U D + DDL | S（诱饵层读取） | S（**列级**，不含 `password_hash`） | S |
| `fake_orders` | S I U D + DDL | S | S | S |
| `fake_config` | S I U D + DDL | S | S | S |
| `audit_log` | S I U D + DDL | **仅 S、I** | S | S |
| `v_session_risk_summary` | S + V | S | S | S |
| `v_attacker_profile_summary` | S + V | S | S | S |
| `v_daily_attack_trend` | S + V | S | S | S |
| `v_rule_effectiveness` | S + V | S | S | S |
| 全局权限 | 无（禁止 `SUPER`/`FILE`/`GRANT OPTION`） | 无 | 无 | `LOCK TABLES`（库级） |
| 允许的写范围 | 全部（含 DDL） | 业务表；`audit_log` 仅插入；**无 DDL** | 无 | 无 |

**关键约束**：

- `app_rw` 对 `detection_rules` 只有 `S/I/U`：规则**不可删除**（保留版本历史），`D` 权限不授予；重置流程也不删除规则。
- `app_rw` 对 `audit_log` 只有 `S/I`：宪法要求"审计表仅追加、业务账号禁止修改或删除"；该限制由权限层强制，不依赖应用自律。
- `app_ro` 对 `fake_users` 使用**列级授权**，明确排除 `password_hash`，从权限层保证控制台与导出不可能带出伪哈希（FR-068/FR-082）。
- 视图对 `app_rw`/`app_ro` 只授予 `SELECT`；视图由 `SQL SECURITY DEFINER` 定义，执行时使用定义者权限，因此不能通过视图绕过列级限制（视图中不引用 `password_hash`）。
- 备份账号只有 `SELECT`/`LOCK TABLES`/`SHOW VIEW`/`TRIGGER`/`EVENT`，不含任何写权限与 DDL。

### 11.3 GRANT / REVOKE 语句

```sql
-- ============================================================
-- 0. 由 DBA（root）执行：建库与建账号
-- 口令一律从环境变量注入或交互输入，仓库中不得出现真实口令
-- ============================================================
-- 以下以演示库 honeypot_demo 为例；开发库 honeypot_dev、测试库 honeypot_test 替换库名即可
CREATE DATABASE IF NOT EXISTS honeypot_demo
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'honeypot_migrate'@'localhost'
  IDENTIFIED BY '<HONEYPOT_MIGRATE_PASSWORD 由环境变量注入>';
CREATE USER IF NOT EXISTS 'honeypot_app_rw'@'localhost'
  IDENTIFIED BY '<HONEYPOT_APP_RW_PASSWORD 由环境变量注入>';
CREATE USER IF NOT EXISTS 'honeypot_app_ro'@'localhost'
  IDENTIFIED BY '<HONEYPOT_APP_RO_PASSWORD 由环境变量注入>';
CREATE USER IF NOT EXISTS 'honeypot_backup'@'localhost'
  IDENTIFIED BY '<HONEYPOT_BACKUP_PASSWORD 由环境变量注入>';

-- Docker Compose 固定隔离网段 172.28.0.0/24：为四类账号创建同权限的网段账号（源地址属于 172.28.0.%）
CREATE USER IF NOT EXISTS 'honeypot_migrate'@'172.28.0.%' IDENTIFIED BY '<HONEYPOT_MIGRATE_PASSWORD>';
CREATE USER IF NOT EXISTS 'honeypot_app_rw'@'172.28.0.%'  IDENTIFIED BY '<HONEYPOT_APP_RW_PASSWORD>';
CREATE USER IF NOT EXISTS 'honeypot_app_ro'@'172.28.0.%'  IDENTIFIED BY '<HONEYPOT_APP_RO_PASSWORD>';
CREATE USER IF NOT EXISTS 'honeypot_backup'@'172.28.0.%'  IDENTIFIED BY '<HONEYPOT_BACKUP_PASSWORD>';
-- 上述网段账号的 GRANT 与下方 @'localhost' 账号逐条对应（库名与主机名替换后重复执行）；
-- 实现阶段的 db/init 脚本以账号列表循环生成，避免手工复制遗漏权限。

-- 若诱饵服务/控制台运行在其他隔离实验网段，按需追加同权限账号，禁止使用 '%' 或公网网段

-- ============================================================
-- 1. 迁移账号：可 DDL、可读写全部对象，但无全局特权
-- ============================================================
GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, DROP, INDEX, REFERENCES,
      CREATE VIEW, SHOW VIEW
  ON honeypot_demo.* TO 'honeypot_migrate'@'localhost';

-- ============================================================
-- 2. 业务读写账号：最小写权限，无 DDL
-- ============================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.sessions         TO 'honeypot_app_rw'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.attack_log       TO 'honeypot_app_rw'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.attacker_profile TO 'honeypot_app_rw'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.attacker_intent  TO 'honeypot_app_rw'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.rule_hits        TO 'honeypot_app_rw'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.alerts           TO 'honeypot_app_rw'@'localhost';
-- 规则只允许读、插（新版本）、改（停用/启用），不允许删除
GRANT SELECT, INSERT, UPDATE          ON honeypot_demo.detection_rules TO 'honeypot_app_rw'@'localhost';
-- 诱饵数据由诱饵层只读返回
GRANT SELECT                          ON honeypot_demo.fake_users      TO 'honeypot_app_rw'@'localhost';
GRANT SELECT                          ON honeypot_demo.fake_orders     TO 'honeypot_app_rw'@'localhost';
GRANT SELECT                          ON honeypot_demo.fake_config     TO 'honeypot_app_rw'@'localhost';
-- 审计表仅允许追加与查询
GRANT SELECT, INSERT                  ON honeypot_demo.audit_log       TO 'honeypot_app_rw'@'localhost';

-- ============================================================
-- 3. 只读账号：控制台与答辩查询；无任何写权限与 DDL
-- ============================================================
GRANT SELECT ON honeypot_demo.sessions         TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.attack_log       TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.attacker_profile TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.attacker_intent  TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.detection_rules  TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.rule_hits        TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.alerts           TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.fake_orders      TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.fake_config      TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.audit_log        TO 'honeypot_app_ro'@'localhost';
-- fake_users 列级授权：显式排除 password_hash，杜绝伪哈希外泄
GRANT SELECT (id, username, email, phone, display_name, is_synthetic, created_at)
  ON honeypot_demo.fake_users TO 'honeypot_app_ro'@'localhost';
-- 四个分析视图
GRANT SELECT ON honeypot_demo.v_session_risk_summary    TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.v_attacker_profile_summary TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.v_daily_attack_trend      TO 'honeypot_app_ro'@'localhost';
GRANT SELECT ON honeypot_demo.v_rule_effectiveness      TO 'honeypot_app_ro'@'localhost';

-- ============================================================
-- 4. 备份账号：只读 + 锁表 + 视图元数据
-- ============================================================
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT
  ON honeypot_demo.* TO 'honeypot_backup'@'localhost';

-- ============================================================
-- 5. 显式收口（防御性 REVOKE；新实例默认本就无权限）
-- ============================================================
REVOKE GRANT OPTION ON *.* FROM 'honeypot_migrate'@'localhost';
REVOKE GRANT OPTION ON *.* FROM 'honeypot_app_rw'@'localhost';
REVOKE GRANT OPTION ON *.* FROM 'honeypot_app_ro'@'localhost';
REVOKE GRANT OPTION ON *.* FROM 'honeypot_backup'@'localhost';

FLUSH PRIVILEGES;
```

**权限验收查询**：

```sql
SHOW GRANTS FOR 'honeypot_app_rw'@'localhost';
SHOW GRANTS FOR 'honeypot_app_ro'@'localhost';
-- 预期：app_rw 无 CREATE/ALTER/DROP/INDEX；app_ro 无任何 INSERT/UPDATE/DELETE
SELECT * FROM information_schema.USER_PRIVILEGES
WHERE GRANTEE IN ("'honeypot_migrate'@'localhost'", "'honeypot_app_rw'@'localhost'",
                  "'honeypot_app_ro'@'localhost'", "'honeypot_backup'@'localhost'");
-- 预期：四账号均无 SUPER / FILE / GRANT OPTION / PROCESS
```

### 11.4 禁止事项（评审与合并门禁）

1. 禁止应用与前端使用 `root` 或任何具备 `SUPER`/`FILE`/`GRANT OPTION`/全局 `ALL` 的账号（宪法原则三）。
2. 禁止 `app_rw`/`app_ro` 拥有 DDL 权限；禁止从应用侧执行 `CREATE/ALTER/DROP/TRUNCATE`。
3. 禁止 `app_rw` 对 `audit_log`、`detection_rules` 执行 `DELETE`；审计与规则历史只能保留。
4. 禁止把口令写进仓库、迁移脚本、日志或文档；配置模板只保留占位符，口令由环境变量注入（宪法"技术栈与工程约束"）。
5. 禁止账号主机使用 `%` 或公网网段；仅本机或隔离实验网段（FR-079）。
6. 禁止"为了方便"给分析/展示账号开写权限——控制台唯一写操作是告警已读（FR-066/FR-068）。
7. 每次迁移与权限变更后必须执行 11.3 的验收查询并归档截图/输出（答辩材料）。

### 11.5 连接初始化参数（四类账号共用时区约定）

```sql
SET NAMES utf8mb4;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
SET SESSION innodb_lock_wait_timeout = 5;
-- 仅 app_rw：
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
-- 仅 app_ro：
SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION max_execution_time = 5000;
SET SESSION group_concat_max_len = 8192;  -- 视图中的 GROUP_CONCAT 结果上限
```

实现阶段必须把这些语句固化到连接池初始化（驱动 `init_command` / 连接钩子），并在健康检查中断言 `@@session.time_zone = '+00:00'`、`@@session.transaction_isolation` 符合预期。

---

## 12. 迁移、回滚与初始化顺序

### 12.1 产物规划（实现阶段创建，本文档只定义契约）

```text
db/
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial_schema.py        # 11 张表、约束、索引（含四条规定索引）
│       ├── 0002_analysis_views.py        # 四个 CREATE OR REPLACE VIEW
│       └── 0003_seed_rules_and_fakes.py  # 5 规则 + 30 用户 + 120 订单 + 5 配置
└── sql/
    ├── 00_create_database.sql            # 建库（字符集/排序规则）
    ├── 10_bootstrap_accounts.sql         # 四类账号与 GRANT（DBA 执行）
    └── 90_verify.sql                     # 迁移后验证查询（12.6）
```

**单一事实来源**：DDL、视图、种子以 **Alembic 迁移**为唯一事实来源；第 6 章的视图 SQL 与第 2.7/4 章的表定义必须与迁移脚本逐字一致。若课程环境不使用 Alembic，可将第 6 章 SQL 原样保存为 `sql/20_views.sql` 由 `migrate` 账号执行，但**必须与 `0002` 内容一致**，并在 CI 中做文本比对；不允许两份定义各改各的。

### 12.2 Alembic 基线要求

| 项目 | 要求 |
| --- | --- |
| 基线 | `0001_initial_schema` 为唯一基线，空库执行 `alembic upgrade head` 即可得到完整结构；禁止使用"手工建表 + 后续补迁移"的方式 |
| 命名 | `revision = "0001_initial_schema"` 等可读前缀 + 语义；`down_revision` 严格线性（本项目不需要分支） |
| 字符集/排序规则 | 每个 `ascii` 列必须显式 `mysql_charset='ascii', mysql_collate='ascii_bin'`（或 `ascii_general_ci`）；表级 `mysql_engine='InnoDB'`、`mysql_default_charset='utf8mb4'`、`mysql_collate='utf8mb4_0900_ai_ci'`、`mysql_row_format='DYNAMIC'`、`comment='...'` |
| 注释 | 每列 `comment='中文注释'`、每表 `comment='...'`；与本文档字段表一致 |
| 约束 | `op.create_check_constraint(...)`、`op.create_unique_constraint(...)`、`op.create_foreign_key(..., onupdate='RESTRICT', ondelete='RESTRICT')`；生成列通过 `sa.Column(..., Computed("...", persisted=True/False))` 表达 |
| 外键顺序 | 建表顺序：`sessions → attack_log → attacker_profile → attacker_intent → detection_rules → rule_hits → alerts → fake_users → fake_orders → fake_config → audit_log`；`rule_hits` 的复合外键要求 `attack_log` 已建 `uk_attack_log_event_session` |
| 视图 | 在 `0002` 中用 `op.execute("CREATE OR REPLACE ... VIEW ...")`；`downgrade` 中 `DROP VIEW IF EXISTS` |
| autogenerate | 仅作为差异参考，不允许直接把 autogenerate 结果提交；每次变更必须人工评审（列类型、字符集、CHECK、注释易被 autogenerate 丢失） |
| 连接 | `env.py` 必须设置 UTC 时区、事务隔离级别、`compare_type=True`、`include_object` 排除视图（视图由 0002 管理） |

### 12.3 初始化顺序（首次部署与演示环境重建）

| 步骤 | 执行账号 | 操作 | 依赖 / 校验 |
| --- | --- | --- | --- |
| 1 | DBA(root) | 执行 `sql/00_create_database.sql` | 库不存在时创建，字符集 `utf8mb4` |
| 2 | DBA(root) | 执行 `sql/10_bootstrap_accounts.sql` | 四类账号与 GRANT；口令从环境变量注入 |
| 3 | `honeypot_migrate` | `alembic upgrade head` → `0001` 建表与索引 | 需要 `REFERENCES`/`CREATE` 权限；顺序见 12.2 |
| 4 | `honeypot_migrate` | `alembic upgrade head` → `0002` 建四个视图 | 依赖 `0001` 全部表 |
| 5 | `honeypot_migrate` | `alembic upgrade head` → `0003` 写种子 | 依赖 `0001`（规则表）与约束 |
| 6 | `honeypot_migrate` | 执行 `sql/90_verify.sql` | 见 12.6，全部断言通过后继续 |
| 7 | `honeypot_app_ro` | 查询四个视图各一次 | 验证视图可读、权限正确 |
| 8 | 运维 | 启动诱饵服务 → 健康检查 → 启动分析/控制台 | 端口、数据库连通、时区断言 |

> 权限脚本可以在建库后立即执行：MySQL 允许对尚不存在的对象授予库级权限；但**视图级 GRANT 必须在视图创建之后**执行，因此 `10_bootstrap_accounts.sql` 中视图授权部分需在 `0002` 之后重跑一次（脚本设计为可重复执行）。

### 12.4 可重复执行与幂等

| 对象 | 是否可重复执行 | 机制 / 注意事项 |
| --- | --- | --- |
| `alembic upgrade head` | 是 | 由 `alembic_version` 表记录当前版本；重复执行为空操作 |
| `CREATE DATABASE/USER IF NOT EXISTS` | 是 | 脚本级幂等 |
| `CREATE OR REPLACE VIEW` | 是 | 覆盖同名视图；若视图列被删除/改名，需先 `DROP VIEW` |
| `CREATE INDEX` | **否**（MySQL 不支持 `IF NOT EXISTS`） | 只在 `0001` 内执行一次；手工脚本必须先查 `information_schema.statistics` 判断是否存在，或改用 `ALTER TABLE ... ADD INDEX` 前做存在性检查 |
| `ALTER TABLE ... ADD CONSTRAINT` | **否**（重复报 1826/1061） | 约束创建全部由版本化迁移负责；手工补丁必须查 `information_schema.table_constraints` |
| 种子 `INSERT ... ON DUPLICATE KEY UPDATE` | 是 | 按唯一键幂等；行数可断言（5/30/120/5） |
| `90_verify.sql` | 是 | 纯只读断言 |
| `DROP DATABASE` + 重建 | 是 | 演示环境彻底重建方式（FR-036）；必须先备份 |

**索引/视图脚本的重复执行策略**：把"是否存在"判断写进迁移脚本（`op.get_bind().execute(sa.text("SELECT ... FROM information_schema.statistics ..."))`），而不是依赖裸 SQL；这是 MySQL 无 `IF NOT EXISTS` 时的标准做法。

### 12.5 回滚策略与顺序

| 迁移 | `downgrade` 内容 | 注意 |
| --- | --- | --- |
| `0003_seed_rules_and_fakes` | 按唯一键删除 5 条规则、30 条用户、120 条订单、5 条配置 | 若规则已被 `rule_hits` 引用、诱饵用户已被 `fake_orders` 引用，`RESTRICT` 会阻止删除 → **必须先清空业务数据或使用演示库**；回滚脚本必须显式报错而不是关闭外键检查 |
| `0002_analysis_views` | `DROP VIEW IF EXISTS` 四个视图（逆依赖顺序） | 先删视图再删表 |
| `0001_initial_schema` | 按外键逆序 `DROP TABLE`：`audit_log → fake_config → fake_orders → fake_users → alerts → rule_hits → detection_rules → attacker_intent → attacker_profile → attack_log → sessions` | 表间存在外键，顺序错误会报 3730 |

**通用回滚纪律**

1. 任何迁移执行前必须备份：`mysqldump --single-transaction --routines --triggers --events honeypot_demo > backup_$(date -u +%Y%m%dT%H%M%SZ).sql`（备份账号执行，加密存放）。
2. 破坏性变更（删列、改类型、拆表、改约束）必须"三步走"：备份 → 迁移并校验 → 记录旧值与回滚方案；不接受"直接改结构再看情况"。
3. 演示环境回滚优先使用"`DROP DATABASE` + 从迁移重建"或"恢复备份"，而不是在生产数据上逐版本 `downgrade`（FR-075 的干净副本策略）。
4. 回滚后必须重跑 12.6 的验证；回滚行为写入 `audit_log`（`operation='migration'`，`result` 反映最终状态）。
5. 迁移与回滚期间禁止诱饵服务写入（维护窗口），`lock_wait_timeout` 设为 10 秒，避免 DDL 长时间等待行锁。

### 12.6 迁移后验证（`sql/90_verify.sql` 断言清单）

| 编号 | 断言 | 期望 | 对应需求 |
| --- | --- | --- | --- |
| V1 | `information_schema.tables` 中 `table_type='BASE TABLE'` 的数量 | 11 | FR-021/FR-036 |
| V2 | `information_schema.views` 中视图数量 | 4 | FR-032 |
| V3 | `information_schema.referential_constraints` 中本库外键数量 | 10，且 `update_rule`/`delete_rule` 全为 `RESTRICT` | FR-022/FR-039 |
| V4 | `information_schema.table_constraints` 中 `CHECK` 约束数量 | 38（5.4 清单） | FR-031 |
| V5 | `session_id`/`event_uuid` 的 `character_set_name='ascii'`、`collation_name='ascii_bin'` | 全部符合 | 2.3 |
| V6 | `@@session.time_zone` | `+00:00` | 2.4/FR-018 |
| V7 | 四视图 `SELECT COUNT(*)` | 均不报错（可为 0） | FR-032/FR-069 |
| V8 | 种子行数 | `detection_rules=5`（v1、启用）、`fake_users=30`、`fake_orders=120`、`fake_config=5` | FR-045/FR-085 |
| V9 | 非法写入被拒：`sessions.max_risk_score=101`、`alerts.severity='fatal'`、`sessions.ended_at < started_at` | 全部报 3819 | FR-031/SC 约束演示 |
| V10 | 外键拦截：插入不存在的 `session_id` 到 `attack_log` | 报 1452 | FR-022/演示专项 |
| V11 | 幂等：同一 `event_uuid` 插入两次 | 第二次报 1062，表行数不变 | FR-023/SC-011 |
| V12 | 快照一致性：`attack_log.source_ip` 与所属 `sessions.source_ip` 不一致行数 | 0 | 5.6 |
| V13 | 快照一致性：`rule_hits` 的 `(rule_id, rule_version)` 在 `detection_rules` 中不存在行数 | 0 | FR-028 |
| V14 | 画像计数偏差：`attacker_profile.total_connections` 与会话表实际 connect 事件数偏差 | 0 | FR-049 |
| V15 | 权限：`SHOW GRANTS` 中 `app_rw` 无 DDL、`app_ro` 无写权限、`audit_log` 无 `UPDATE/DELETE` | 全部符合 | 11.4/宪法三 |

---

## 13. 数据生命周期、保留与清理

### 13.1 五个阶段的数据库侧职责

| 阶段 | 触发者 | 写入/读取的表 | 数据库职责 | 约束与要求 |
| --- | --- | --- | --- | --- |
| 生成 | 协议捕获层 | 不落库 | 无 | 事件编号、`event_uuid` 在进入数据库前一次性生成（8.4） |
| 写入 | 分析/存储服务（`app_rw`） | `sessions`、`attack_log`、`rule_hits`、`attacker_profile`、`attacker_intent`、`alerts` | 单事务原子写入 + 唯一约束幂等 | T1（8.3）；失败不静默 |
| 分析 | 同一事务内（在线）或离线重算 | 读 `detection_rules`/`attack_log`，写 `rule_hits`/`attacker_intent`/`attacker_profile`/`alerts` | 确定性评分 | 第 9 章公式；快照不可回写 |
| 展示 | 控制台（`app_ro`） | 读四个视图 + 明细表 | 只读、带 `LIMIT`、`max_execution_time` | FR-068/FR-070；列级权限排除伪哈希 |
| 清理 | 定时任务/演示重置（`app_rw`） | 按顺序 DELETE | 分批、按索引删除、写审计 | 13.2；FR-020/FR-040 |

### 13.2 保留矩阵与清理顺序

| 表 | 默认保留 | 演示库基准 | 清理方式 | 说明 |
| --- | --- | --- | --- | --- |
| `sessions` | 90 天 | 按演示需要 | `DELETE ... WHERE started_at < ? LIMIT 5000` | 需先删除依赖行（见顺序） |
| `attack_log` | 90 天 | 同上 | `DELETE ... WHERE event_time < ? LIMIT 5000`（走 `idx_log_source_time`/`idx_log_session_time` 或主键范围） | 最热表，分批避免长事务 |
| `rule_hits` | 与 `attack_log` 同期（90 天） | 同上 | `DELETE ... WHERE triggered_at < ? LIMIT 5000` | 必须先删引用它的 `alerts`（`latest_hit_id` RESTRICT） |
| `alerts` | 180 天 | 同上 | `DELETE ... WHERE created_at < ? LIMIT 5000` | 先删告警再删命中/会话 |
| `attacker_intent` | 180 天（随画像） | 同上 | 随画像清理或按 `last_detected_at` | 建议与画像同生命周期 |
| `attacker_profile` | 180 天 | 同上 | `DELETE ... WHERE last_seen < ? LIMIT 1000` | 删除前确认无 `alerts`/`attacker_intent` 引用 |
| `detection_rules` | 永久 | 永久 | 不清理（只停用/新增版本） | FR-040 要求重置保留规则种子 |
| `fake_users`/`fake_orders`/`fake_config` | 永久 | 永久 | 不清理 | 诱饵种子，重建时由迁移恢复 |
| `audit_log` | 365 天 | 演示期间保留 | `DELETE ... WHERE occurred_at < ? LIMIT 5000` | 审计不可由 `app_rw` 删除；清理由 `migrate`/DBA 账号执行 |

**清理顺序（严格）**：

```
1. alerts（含 latest_hit_id 依赖、created_at 最旧）
2. rule_hits
3. attack_log
4. attacker_intent
5. attacker_profile
6. sessions
7. audit_log（可选，365 天口径）
```

**为什么不能先删 `attack_log`**：`rule_hits.fk_hit_log` 为 `RESTRICT`；先删日志会被外键拒绝并回滚整批。跨表清理必须按上面的依赖顺序执行，且每批单独提交（T5）。

**为什么不用 `TRUNCATE`**：`TRUNCATE` 是 DDL，会隐式提交、无法回滚，且绕过逐行外键检查语义；本设计只在"整库重建"时使用 `DROP DATABASE`（12.4），运行期清理一律 `DELETE` 分批。

### 13.3 清理实现要求

1. 分批大小 1 000–5 000 行/批，批间休眠 100 ms，降低锁等待与主从延迟（如有）。
2. 每批按主键或时间索引有序删除（`ORDER BY ... LIMIT`），避免全表扫描与长事务；
3. 清理任务必须设置超时（`max_execution_time`、应用侧超时），失败只回滚当前批；
4. 清理结果写 `audit_log`（`operation='export'` 不适用；使用 `migration` 之外的口径时需在实现阶段扩展枚举值——**若确需新增审计操作类型，必须走迁移修改 `ck_audit_operation`，不得绕过约束**）；
5. 清理后可选重算受影响画像的 `risk_score`（因为历史命中被删除），重算必须写审计并按 10.3 口径声明。

### 13.4 导出与脱敏

| 数据 | 导出策略 |
| --- | --- |
| `username`、`credential_test_id` | 视为不可信输入：导出时脱敏（保留前 2 字符 + 哈希前缀）或仅导出聚合值；不导出原始明文批量清单 |
| `sql_statement` / `normalized_sql` | 只导出统计特征（长度、类型、命中规则编码）；如需样例，仅导出经人工审查的固定合成样本 |
| `password_hash`（`fake_users`） | **永不导出**（`app_ro` 无列权限；导出脚本使用同一列白名单） |
| `fake_config.config_value` | 可导出（全部为 `TEST-ONLY` 虚构值），导出说明中标注"演示数据" |
| 时间字段 | 统一 UTC 并在导出文件头注明时区；不接受本地时区导出 |
| 导出行数 | 必须有 `LIMIT` 与时间范围；禁止无界导出（宪法四） |

### 13.5 备份与恢复

| 项目 | 要求 |
| --- | --- |
| 备份方式 | `mysqldump --single-transaction --routines --triggers --events --set-gtid-purged=OFF`（`honeypot_backup` 账号），或物理快照（演示环境用逻辑备份即可） |
| 备份频率 | 每次演示前、每次迁移前、每次规则批量变更后 |
| 备份保留 | 演示环境保留最近 5 份 + 一份"干净演示副本"（FR-075） |
| 备份安全 | 备份文件加密存储、按最小权限管控、仓库中不得提交备份文件（宪法三"备份安全"） |
| 恢复演练 | 每学期至少 1 次完整恢复演练并记录；恢复后执行 12.6 验证 + 时区断言 |
| 恢复顺序 | 恢复整库 → 校验 11 表 / 4 视图 / 10 外键 / 种子行数 → 校验账号权限 → 启动服务 |
| 与迁移的关系 | 恢复的备份必须与当前 `alembic_version` 兼容；跨版本恢复后需执行 `alembic upgrade head` 补齐 |

---

## 14. 与 spec.md 功能需求（FR-021..FR-043 等）的映射表

### 14.1 存储与数据库设计需求（FR-021..FR-038）

| 需求 | 内容摘要 | 本文档落点 | 验证方式 |
| --- | --- | --- | --- |
| FR-021 | 关系库持久化会话、事件、命中、意图、规则、画像、告警、诱饵；正式 PK/FK/UNIQUE/CHECK | 第 3、4、5 章 | V1–V4（12.6） |
| FR-022 | `sessions` 为会话主表；`attack_log`/`rule_hits`/`alerts` 经 `session_id` 建外键 | 3.2 R1–R5、5.2 | V3、V10 |
| FR-023 | `event_uuid` 唯一实现幂等，重复不新增并返回已有事件 | 4.2、5.3、8.4 | V11、SC-011 |
| FR-024 | `attacker_intent` 一行一意图，`(attacker_id, intent_type)` 唯一 | 4.4、5.3 | V1、V4 |
| FR-025 | 画像不存多值意图列表，主要意图由视图计算 | 3.3、4.3、6.3 | 视图查询 + 表结构检查 |
| FR-026 | 规则表字段完整，`rule_code + rule_version` 复合唯一 | 2.7、4.5、10.3 | V1/V4 |
| FR-027 | 参数按单条规则结构保存，不存多值实体 | 10.2 | JSON 结构校验脚本 |
| FR-028 | 命中记录事件、规则、会话、得分、证据、时间与版本/权重快照 | 4.6、9.1 | V13 |
| FR-029 | 告警记录会话、攻击者、类型、等级、证据、去重键、创建时间、已读状态 | 4.7 | V4/V11 |
| FR-030 | 三张诱饵表；订单关联用户；配置键唯一 | 4.8–4.10、3.2 R11 | V8 |
| FR-031 | 分数 0–100、计数非负、时间/状态/类型 CHECK | 5.4 | V9 |
| FR-032 | 四个视图，使用 JOIN/聚合/CTE/窗口函数 | 第 6 章 | V2/V7 |
| FR-033 | 四视图被控制台/答辩查询使用，各有演示查询 | 6.2–6.5 | 每节"演示查询" |
| FR-034 | 四类高频查询的复合索引 | 7.1（规定索引 1–4）、7.2 | Q1–Q4 EXPLAIN |
| FR-035 | 至少两组索引前后 EXPLAIN 对比记录 | 7.3 | G1/G2 记录 |
| FR-036 | 可从建表、种子、视图、索引脚本完整重建 | 12.1–12.4 | 空库 `upgrade head` 演练 |
| FR-037 | 统一启动入口与运行说明 | 由 `quickstart.md`（Phase 1 另一产物）承载；本文档只定义数据库侧初始化顺序 | 12.3 |
| FR-038 | DDL/迁移/种子/索引纳入版本控制 | 12.1/12.2 | 迁移目录与提交记录 |

### 14.2 事务与幂等需求（FR-039..FR-043）

| 需求 | 内容摘要 | 本文档落点 |
| --- | --- | --- |
| FR-039 | 会话更新、日志、命中、告警、画像同一事务，任一步失败整体回滚 | 8.1 T1、8.3 |
| FR-040 | 重置按外键顺序清理并保留规则种子，异常回滚 | 8.6 |
| FR-041 | 幂等由唯一约束保证，调用方区分"已存在/本次新增" | 8.4 |
| FR-042 | 写入失败/约束冲突/锁定/端口占用返回明确错误并记日志 | 8.5、8.7 |
| FR-043 | 连接启用外键约束；事务显式提交/回滚 | 2.1、8.1、11.5 |

### 14.3 数据与捕获需求（FR-011..FR-020，数据库侧）

| 需求 | 内容摘要 | 落点 |
| --- | --- | --- |
| FR-011 | 每次连接生成全局唯一 `session_id` | 4.1（UUID 主键 + 唯一性） |
| FR-012 | 标准事件字段（编号、唯一键、会话、类型、来源、时间、结果、行数） | 4.2 |
| FR-013 | 覆盖 connect/auth/query/disconnect，连接与认证成功分别记录 | 4.2（`event_type`） |
| FR-014 | 认证记录用户名/结果/测试标识；查询记录原始与标准化 SQL、行数、耗时 | 4.2 |
| FR-015 | 事件幂等键 `event_uuid` 的时机/时区/唯一性固定 | 8.4、4.2 |
| FR-016 | 同会话事件共享 `session_id` | 4.1、5.2 |
| FR-017 | 会话记录来源/端口/服务/起止/状态/计数/最高分；结束不早于开始 | 4.1、5.4 |
| FR-018 | 统一 UTC 与格式；时间线按时间升序、同刻按事件序号 | 2.4、4.2、7.2 Q1 |
| FR-019 | 写入失败保留定位信息，不静默丢失 | 8.7 |
| FR-020 | 保留策略清理；导出前删/遮口令 | 13.2、13.4（系统不设口令列） |

### 14.4 分析与告警需求（FR-044..FR-060，数据库侧）

| 需求 | 内容摘要 | 落点 |
| --- | --- | --- |
| FR-044 | 只执行启用规则，输出规则编号/意图/得分/证据 | 4.5、9.1、10.3 |
| FR-045 | 内置 5 条规则及初始阈值与权重 | 10.1 |
| FR-046 | 规则参数/权重/版本/启用由数据库配置 | 4.5、10.2、10.3 |
| FR-047 | 确定性聚合、最高 100、每分可追溯 | 9.1、9.2 |
| FR-048 | 四档风险等级 | 9.3 |
| FR-049 | 意图记录累计分/证据计数/最近时间，可多意图 | 4.4、8.3 步骤 8 |
| FR-050 | 主要意图按分数、最近时间、危害程度稳定排序 | 6.3（窗口排序 + 危害 CASE） |
| FR-051 | 画像页面显示规则编号、命中时间、证据摘要 | 4.6、6.3、4.7 |
| FR-052 | 版本切换后新命中保存新快照，历史保留旧快照；重算口径明确 | 4.6、9.1、10.3 |
| FR-053 | AI 不参与评分/改命中/定等级 | 9.1（AI 无写权限，见 11.2） |
| FR-054 | 规则启停、阈值/权重调整与版本管理 | 10.3 |
| FR-055 | 爆破/拖库/破坏性命中达条件生成告警 | 9.4 |
| FR-056 | 告警可按类型/时间/等级/已读筛选 | 7.1 索引 27/28/31 |
| FR-057 | 告警关联会话与攻击者，证据可定位 | 4.7（`latest_hit_id` + FK）、5.2 |
| FR-058 | 已读更新是独立写操作并反馈结果 | 8.1 T2、4.7 |
| FR-059 | 去重键与触发条件匹配，重复触发稳定去重 | 9.5、5.3 |
| FR-060 | 告警含等级、类型、时间、触发规则、处置状态 | 4.7 |

### 14.5 展示与安全需求（数据库侧）

| 需求 | 内容摘要 | 落点 |
| --- | --- | --- |
| FR-061/FR-062 | 四页控制台；首页连接数/查询数/告警数/高风险攻击者数 | 6.2、6.3、7.2 Q9 |
| FR-063 | 攻击者列表分页展示来源/首末时间/意图/风险分 | 6.3、7.1 索引 12 |
| FR-064 | 攻击者详情展示统计、会话摘要、证据 | 6.3、4.4、7.1 索引 24 |
| FR-065 | 会话时间线按 `session_id` 展示先后与结果 | 6.2、7.2 Q1 |
| FR-066 | 告警筛选 + 标记已读 | 4.7、8.1 T2 |
| FR-068/FR-082 | 控制台只读、不显示完整口令；导出字段审查 | 11.2（列级授权）、13.4 |
| FR-070 | 优先查询核心视图，详情再读原始日志与证据 | 6.1 约定、第 6 章 |
| FR-079/FR-080 | 仅隔离网络；不连接真实业务库、不使用真实数据 | 10.4 自检、11.1 主机限制 |
| FR-081/FR-083 | 展示脱敏；采集数据只存不执行 | 4.2 注释、13.4 |
| FR-085 | 预置 20–50 条 `fake_users` 与足够订单；密钥无效且带测试标识 | 10.4（30/120/5），5.4 CHECK 强制 TEST-ONLY |
| FR-089 | AI 只读、只允许 SELECT、限定视图 | 11.2 提供 `app_ro` 只读账号，AI 复用该账号 |

### 14.6 宪法条款落点

| 宪法条款 | 落点 |
| --- | --- |
| 一、文档与注释完备（中文、COMMENT 落库、ER 图同步） | 2.2/2.7（注释模板）、第 3 章（ER 图源文件）、第 4 章（字段注释即 COMMENT） |
| 二、数据库设计优先：Schema 即契约、3NF、约束优先、索引有据、版本化迁移 | 1.4、3.3、第 5 章、7.1、12.1/12.2 |
| 三、安全与最小权限（账号分离、审计留痕、蜜罐数据隔离、备份安全） | 11.1–11.4、4.11、4.8–4.10、13.5 |
| 四、事务完整性与鲁棒性（显式事务、幂等、重试、输入上限、迁移可回滚） | 8.1–8.7、2.5（64K 上限）、12.5 |
| 五、测试先行与可验证性（真实库验证、约束/事务/迁移覆盖） | 7.3、12.6（V1–V15）、9.6（可手算基准） |

---

## 15. 已知限制与设计权衡

| 序号 | 限制 / 权衡 | 决策与理由 | 风险与缓解 | 演进方向（不在本版） |
| --- | --- | --- | --- | --- |
| 1 | `source_ip` 用 `VARCHAR(45)` 文本而非 `VARBINARY(16)` | 可读性、可直接展示与查询、跨 IPv4/IPv6 简单；索引 45 字节在演示规模无压力 | IPv6 文本格式不唯一（`::1` 与 `0:0:0:0:0:0:0:1`）可能被当作不同来源 | 写入前统一规范化（推荐 inet6_ntoa 风格）；或新增 `source_ip_bin VARBINARY(16)` 生成列并索引 |
| 2 | 视图实时聚合、不物化 | 数据量小（几千至几万行），避免汇总表双写不一致 | 数据量增大后视图变慢 | 引入增量汇总表（由 T1 事务维护）或离线物化，需重新定义一致性与重算口径 |
| 3 | 单机、无分区、无分库分表 | 课程演示规模与单机部署；宪法要求"复杂度必须可解释" | `attack_log` 增长后归档与查询变慢 | 按月 `RANGE` 分区需把主键改为 `(event_id, event_time)`；或按时间归档到历史库 |
| 4 | `sessions` 与 `attacker_profile` 之间无外键 | 画像按 `source_ip` 聚合，先有会话后有画像；强加 FK 会要求先建画像，破坏写入顺序 | 若应用漏更新画像，两者不一致 | 12.6 V14 校验 + 每日重算任务；必要时增加"画像创建前置"步骤 |
| 5 | `rule_hits` 同时用复合外键与单列会话外键（冗余） | 复合 FK 保证同源；单列 FK 提供更清晰的错误定位与证据查询索引 | 多一个 FK 的校验开销（可忽略） | 若评审要求精简，可删除 `fk_hit_session`，保留复合 FK（见 5.2 说明） |
| 6 | 告警去重键含 UTC 日期，跨日会新增告警 | 便于按日统计与演示"重复触发去重"；避免无限累积为一条 | 长时间持续攻击产生"每日一条"告警 | 改为滑动窗口去重（如 24 小时内）需引入"去重时间桶"列与清理策略 |
| 7 | `uk_detection_rules_enabled_code` 限制每规则仅一个启用版本 | 消除"取最大启用版本"的歧义，规则管理更简单 | 无法并存"影子规则/灰度版本" | 若需灰度：移除该唯一约束，改为应用层选版本 + 增加 `rollout_percent` 字段 |
| 8 | 视图依赖 MySQL 8 的 CTE/窗口函数 | 4 个视图的语义（LAG/RANK/主要意图）用窗口函数表达最直观 | 低版本实例不可用 | 6.6 已给全部降级写法；部署要求明确 ≥8.0.16（推荐 8.4 LTS） |
| 9 | `DATETIME` 无时区，依赖"连接时区=UTC"约定 | 避免 `TIMESTAMP` 的 2038 上限与隐式转换；`DATETIME(6)` 精度足够 | 直接用第三方 SQL 客户端写入可能写入本地时间 | 服务侧统一连接初始化（11.5）；校验脚本抽查"未来时间/异常偏移"事件；禁止非服务账号写入业务表 |
| 10 | `MEDIUMTEXT` + 64K 字符上限会截断超长 SQL | 防止畸形载荷拖垮存储（宪法四"输入防线"）；截断可追溯 | 超长载荷尾部丢失，影响深度分析 | 记录 `payload_truncated=1` 与长度；如需完整载荷，可在隔离环境另存文件并保存 SHA-256 引用 |
| 11 | 枚举值使用英文代码（如 `data_dump`） | 与 spec/总纲术语一致、跨语言稳定、便于索引与比较 | 展示需中文映射 | 在控制台维护字典表/常量；视图返回代码，页面负责本地化 |
| 12 | 意图分与画像分按不同公式（画像不按意图分求和） | 与 spec FR-047 的"启用规则权重确定性聚合"一致；避免双重封顶歧义 | 演示时可能被问"意图分之和≠画像分" | 答辩材料用 9.2 口径说明；如需一致，可改为"画像分 = LEAST(100, Σ意图分)"并同步修改公式与测试 |
| 13 | 计数列（`total_*`）与可重算聚合并存 | 计数列保证页面与画像查询快，重算值用于校验 | 清理/重算后可能短暂不一致 | 事务内同源更新 + 12.6 V14 校验；清理后可选重算 |
| 14 | 无软删除、无历史归档表 | 简化模型，删除即物理删除；重置是核心演示操作 | 误删不可恢复（除备份） | 依赖备份与迁移重建；如需审计追溯，扩展 `audit_log` 记录删除行数摘要 |
| 15 | 不使用触发器/存储过程/事件调度器 | 业务逻辑集中在应用层，便于测试、评审与答辩；避免隐式写入与死锁调试困难 | 跨表规则（5.6）只能靠应用保证 | 若未来需要强一致，可用触发器实现少数字段级校验，但必须重新评估锁与性能 |
| 16 | JSON 参数仅在数据库层校验语法合法性 | 原生 `JSON` 类型保证可解析；结构校验放在应用层，避免 `CHECK` 依赖 JSON 函数带来的版本兼容风险 | 结构错误的规则可能入库 | 迁移/启动校验脚本检查必需键；规则保存 API 做 Schema 校验 |
| 17 | 权限依赖人工执行 `10_bootstrap_accounts.sql` | MySQL 的账号与库对象授权属实例级操作，不纳入业务迁移 | 部署时容易漏授权 | 12.3 将授权纳入初始化顺序，并执行 11.3 验收查询；CI 用容器化实例验证 |
| 18 | 备份为逻辑备份 | 演示规模小、可读、可精确重建 | 恢复时间随数据量增长 | 数据量增大后改用物理备份（`mysqlbackup`/文件系统快照） |

---

## 附录 A：评审检查清单

- [ ] 11 张表、4 个视图与第 3 章 ER 图一致，且 ER 图与后文 DDL 契约一致。
- [ ] 每个字段都有中文注释（可直接复制进 `COMMENT`），每张表有表注释。
- [ ] 所有外键列与父列字符集/排序规则完全一致（特别是 `session_id`/`rule_code` 的 `ascii_bin`）。
- [ ] 四条规定索引名称与列顺序未被改动：`idx_log_session_time`、`idx_log_source_time`、`idx_alert_level_time`、`idx_hit_rule_time`。
- [ ] 全部外键动作均为 `RESTRICT`，且删除顺序与 8.6/13.2 一致。
- [ ] 分数列有 `<= 100` 检查约束，枚举列有 `CHECK IN`，时间列有先后顺序检查。
- [ ] 诱饵数据的 `TEST-ONLY` 约束与安全自检（10.4）已复核，无真实 PII/口令/密钥。
- [ ] 幂等、隔离级别、死锁重试、重置回滚的口径与 spec FR-039..FR-043 一致。
- [ ] 四个视图 SQL 在 MySQL 8.4 上可执行，且表达式列全部显式命名。
- [ ] 每个视图至少一条演示查询；EXPLAIN 验证方案含"索引前后"对比方法。
- [ ] 四类账号的 GRANT 与"禁止事项"符合宪法最小权限；`audit_log` 对 `app_rw` 仅 S/I。
- [ ] 迁移顺序、幂等执行、回滚顺序与验证断言（V1–V15）完整。
- [ ] 第 14 章需求映射无遗漏（FR-021..FR-043 全覆盖）。

## 附录 B：术语与口径速查

| 术语 | 本文档口径 |
| --- | --- |
| 会话风险分 | 该会话内按 `rule_code` 取 `MAX(risk_weight)` 后求和，封顶 100（9.2） |
| 意图风险分 | 该画像该意图下按 `rule_code` 取 `MAX(risk_weight)` 后求和，封顶 100 |
| 画像风险分 | 该来源全部命中按 `rule_code` 取 `MAX(risk_weight)` 后求和，封顶 100 |
| 风险等级 | 0–29 低、30–59 中、60–79 高、80–100 严重 |
| 有效 SQL | `event_type='query'` 且 `status='success'` 的事件（R01 口径） |
| 凭据组合 | `(username, credential_test_id)` 去重对（R02 口径） |
| 去重键 | `<rule_code>:<source_ip>:<UTC 日期>`（9.5） |
| 快照 | 命中时写入 `rule_hits` 的 `rule_version`/`risk_weight`/`intent_type`，此后不回写 |
| 演示重置 | 按 8.6 顺序清空 6 张业务表、保留规则/诱饵/审计的单事务操作 |

## 附录 C：变更记录

| 版本 | 日期（UTC） | 变更内容 | 评审状态 |
| --- | --- | --- | --- |
| v0.1 | 2026-11-19 | 初稿：11 表 / 4 视图 / 约束矩阵 / 索引与 EXPLAIN 方案 / 事务与幂等 / 评分与告警 / 种子 / 账号权限 / 迁移与生命周期 / 需求映射 | 待评审 |

> 后续任何 Schema 变更必须同时更新本文档、第 3 章 ER 图与对应 Alembic 迁移，三者保持一致后才允许合并（宪法"合并前门禁"）。

