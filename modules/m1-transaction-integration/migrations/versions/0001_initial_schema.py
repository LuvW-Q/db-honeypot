"""初始结构：11 张表、主外键、唯一约束、CHECK 约束、生成列与全部索引。

修订号（Revision ID）: 0001_initial_schema
父修订（Revises）: 无（唯一基线）
创建时间（Create Date）: 2026-11-19

权威定义：`specs/001-database-honeypot/data-model.md` 第 4、5、7 章。
本迁移一次性创建完整结构，空库执行 `alembic upgrade head` 即可重建：

- 建表顺序遵循外键依赖：sessions → attack_log → attacker_profile →
  attacker_intent → detection_rules → rule_hits → alerts → fake_users →
  fake_orders → fake_config → audit_log；
- 四条规定复合索引（idx_log_session_time / idx_log_source_time /
  idx_alert_level_time / idx_hit_rule_time）随建表创建；
- 仅承担外键约束的索引与唯一键随建表创建（MySQL 会为无索引外键自动建索引，
  显式命名可避免隐式索引名不稳定）；
- 其余纯查询索引由 0003_indexes 补充，两步合并后与 data-model 7.1 索引总表一致；
- CHECK 约束用 `ALTER TABLE ... ADD CONSTRAINT` 单独添加，以保留
  data-model 5.4 中的约束名（如 ck_intent_type、ck_hit_risk_weight）；
- 所有时间列 DATETIME(6)、存 UTC；UUID/IP/编码列使用 ascii 字符集；
- 全部表、列带中文 COMMENT，字符集 utf8mb4 / utf8mb4_0900_ai_ci、
  InnoDB、ROW_FORMAT=DYNAMIC。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# Alembic 修订标识
revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# 公共列类型与表选项（与 data-model 2.3 / 2.5 / 2.7 一致）
# ---------------------------------------------------------------------------


def _uuid_char() -> mysql.CHAR:
    """UUID v4 文本列：CHAR(36) ascii_bin。"""
    return mysql.CHAR(36, charset="ascii", collation="ascii_bin")


def _source_ip() -> mysql.VARCHAR:
    """来源地址列：VARCHAR(45) ascii_general_ci。"""
    return mysql.VARCHAR(45, charset="ascii", collation="ascii_general_ci")


def _ascii_bin(length: int) -> mysql.VARCHAR:
    """稳定机器可读标识列：VARCHAR(n) ascii_bin。"""
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _ascii_char(length: int) -> mysql.CHAR:
    """定长机器可读标识列：CHAR(n) ascii_bin（如币种代码）。"""
    return mysql.CHAR(length, charset="ascii", collation="ascii_bin")


def _dt6() -> mysql.DATETIME:
    """UTC 时刻列：DATETIME(6)。"""
    return mysql.DATETIME(fsp=6)


def _bigint_u() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _int_u() -> mysql.INTEGER:
    return mysql.INTEGER(unsigned=True)


def _tinyint_u() -> mysql.TINYINT:
    return mysql.TINYINT(unsigned=True)


def _tinybool() -> mysql.TINYINT:
    return mysql.TINYINT(display_width=1)


def _smallint_u() -> mysql.SMALLINT:
    return mysql.SMALLINT(unsigned=True)


def _now() -> sa.TextClause:
    return sa.text("CURRENT_TIMESTAMP(6)")


def _now_on_update() -> sa.TextClause:
    return sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)")


# 表选项：InnoDB + utf8mb4 + DYNAMIC 行格式（data-model 2.1）
TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_row_format": "DYNAMIC",
}

# 风险等级生成列表达式：与 data-model 5.5 / 9.3 完全一致
RISK_LEVEL_SQL = (
    "CASE WHEN risk_score >= 80 THEN 'critical' "
    "WHEN risk_score >= 60 THEN 'high' "
    "WHEN risk_score >= 30 THEN 'medium' "
    "ELSE 'low' END"
)

# 启用规则编码生成列表达式（STORED）
ENABLED_RULE_CODE_SQL = "CASE WHEN enabled = 1 THEN rule_code ELSE NULL END"


def _add_checks(table: str, checks: list[tuple[str, str]]) -> None:
    """为已创建的表添加命名 CHECK 约束（data-model 5.4，约束名逐一保留）。"""
    for name, expression in checks:
        op.execute(f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` CHECK ({expression})")


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """创建 11 张表、约束、生成列与索引。"""

    # ---- 1. sessions：会话主表 ----
    op.create_table(
        "sessions",
        sa.Column(
            "session_id",
            _uuid_char(),
            nullable=False,
            comment="会话唯一标识，UUID v4 文本（36 字符），由捕获层在连接建立时生成，全局唯一且不可复用",
        ),
        sa.Column(
            "source_ip",
            _source_ip(),
            nullable=False,
            comment="测试端来源地址，IPv4 或 IPv6 文本规范形式（如 192.0.2.10、2001:db8::10），写入前统一小写",
        ),
        sa.Column(
            "source_port",
            _smallint_u(),
            nullable=True,
            comment="测试端源端口 1-65535；报文缺失或 NAT 重写导致不可知时为 NULL",
        ),
        sa.Column(
            "target_service",
            sa.String(64),
            nullable=False,
            server_default="mysql-honeypot",
            comment="被访问的诱饵服务标识，形如 mysql-honeypot:13306，用于多端口演示时区分诱饵实例",
        ),
        sa.Column(
            "client_fingerprint",
            sa.String(255),
            nullable=True,
            comment="客户端特征摘要（协议版本、客户端能力标志等），已脱敏，不保存原始可识别信息",
        ),
        sa.Column(
            "started_at",
            _dt6(),
            nullable=False,
            comment="会话开始时间（UTC），由捕获层显式写入，不使用数据库默认时间",
        ),
        sa.Column(
            "ended_at",
            _dt6(),
            nullable=True,
            comment="会话结束时间（UTC）；未结束或异常断连未回填时为 NULL；不得早于开始时间",
        ),
        sa.Column(
            "session_status",
            sa.String(16),
            nullable=False,
            server_default="active",
            comment="会话状态枚举：active 进行中 / closed 正常断开 / timeout 空闲超时 / error 协议错误终止",
        ),
        sa.Column(
            "request_count",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="会话内事件计数（connect/auth/query/disconnect 均计 1）；由事件写入事务原子自增",
        ),
        sa.Column(
            "max_risk_score",
            _tinyint_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="本会话最高风险分 0-100，写入事件时以 GREATEST 更新；权威值由 v_session_risk_summary 重算校验",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行创建时间（UTC），由数据库默认值填充，仅用于运维排查",
        ),
        sa.Column(
            "updated_at",
            _dt6(),
            nullable=False,
            server_default=_now_on_update(),
            comment="行最近更新时间（UTC），用于排查计数是否停滞",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        comment="会话主表：一次诱饵连接一行，记录来源、起止时间、状态与事件计数；数据来源为捕获层的连接与断开事件",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "sessions",
        [
            ("ck_sessions_source_port", "source_port IS NULL OR source_port BETWEEN 1 AND 65535"),
            ("ck_sessions_ended_after_started", "ended_at IS NULL OR ended_at >= started_at"),
            ("ck_sessions_status", "session_status IN ('active','closed','timeout','error')"),
            ("ck_sessions_max_risk_score", "max_risk_score <= 100"),
        ],
    )

    # ---- 2. attack_log：标准事件表 ----
    op.create_table(
        "attack_log",
        sa.Column(
            "event_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="事件序号；全局单调递增，用于同时间戳事件的稳定排序",
        ),
        sa.Column(
            "event_uuid",
            _uuid_char(),
            nullable=False,
            comment="采集事件幂等键（UUID v4 文本），重复提交时由唯一约束阻止重复入库并返回已有 event_id",
        ),
        sa.Column(
            "session_id",
            _uuid_char(),
            nullable=False,
            comment="所属会话编号，引用 sessions.session_id",
        ),
        sa.Column(
            "event_type",
            sa.String(16),
            nullable=False,
            comment="事件类型：connect 连接 / auth 认证 / query 查询或写操作 / disconnect 断开；无法识别的报文归入 query 且 status=error",
        ),
        sa.Column(
            "source_ip",
            _source_ip(),
            nullable=False,
            comment="测试端来源地址；与会话行保持一致（写入事务内从会话复制，属受控反规范化）",
        ),
        sa.Column(
            "username",
            sa.String(128),
            nullable=True,
            comment="认证或查询使用的用户名；来自不可信输入，按 128 字符上限截断，超长时置 payload_truncated=1",
        ),
        sa.Column(
            "credential_test_id",
            sa.String(64),
            nullable=True,
            comment="合成凭据测试标识（如 TEST-ONLY-ACC-01），仅标识测试样本，任何情况下不保存口令明文或可逆凭据",
        ),
        sa.Column(
            "sql_statement",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="原始 SQL 文本，只存储不执行；超过 65535 字符时截断并置 payload_truncated=1",
        ),
        sa.Column(
            "normalized_sql",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="标准化 SQL（字面量替换为占位符、空白折叠、统一大小写）；供规则匹配与去重比较，不参与索引",
        ),
        sa.Column(
            "event_time",
            _dt6(),
            nullable=False,
            comment="事件发生时间（UTC），由捕获层在事件生成时确定并显式写入",
        ),
        sa.Column(
            "returned_rows",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="本次查询返回给客户端的行数；非查询事件为 0",
        ),
        sa.Column(
            "response_ms",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="模拟响应耗时（毫秒）；受控延迟场景记录实际等待时间",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            comment="处理结果枚举：success 成功 / failure 认证失败或模拟失败 / denied 权限不足 / error 协议或语句错误",
        ),
        sa.Column(
            "payload_truncated",
            _tinybool(),
            nullable=False,
            server_default=sa.text("0"),
            comment="载荷是否被截断：1 表示 SQL 或用户名超过长度上限并按策略截断，便于审计输入防线是否生效",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行落库时间（UTC），与 event_time 的差值可用于评估写入延迟",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            name="fk_log_session",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("event_uuid", name="uk_attack_log_event_uuid"),
        sa.UniqueConstraint(
            "event_id", "session_id", name="uk_attack_log_event_session"
        ),
        sa.Index("idx_log_session_time", "session_id", "event_time"),
        sa.Index("idx_log_source_time", "source_ip", "event_time"),
        comment="标准事件表：一次连接/认证/查询/断开一行；event_uuid 唯一约束实现采集幂等；SQL 与用户名为不可信数据，只存储不执行",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "attack_log",
        [
            ("ck_attack_log_event_type", "event_type IN ('connect','auth','query','disconnect')"),
            ("ck_attack_log_status", "status IN ('success','failure','denied','error')"),
            (
                "ck_attack_log_sql_length",
                "sql_statement IS NULL OR CHAR_LENGTH(sql_statement) <= 65535",
            ),
            (
                "ck_attack_log_normalized_length",
                "normalized_sql IS NULL OR CHAR_LENGTH(normalized_sql) <= 65535",
            ),
            ("ck_attack_log_truncated_flag", "payload_truncated IN (0,1)"),
        ],
    )

    # ---- 3. attacker_profile：攻击者画像表 ----
    op.create_table(
        "attacker_profile",
        sa.Column(
            "attacker_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="画像编号；被 attacker_intent 与 alerts 引用",
        ),
        sa.Column(
            "source_ip",
            _source_ip(),
            nullable=False,
            comment="攻击者聚合键（来源地址），唯一；同一来源仅一行画像",
        ),
        sa.Column(
            "first_seen",
            _dt6(),
            nullable=False,
            comment="该来源首次出现时间（UTC），取首次会话开始时间",
        ),
        sa.Column(
            "last_seen",
            _dt6(),
            nullable=False,
            comment="该来源最近出现时间（UTC），取最新事件时间",
        ),
        sa.Column(
            "total_connections",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="累计连接次数（connect 事件数）",
        ),
        sa.Column(
            "total_auth_attempts",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="累计认证尝试次数（auth 事件数，含成功与失败）",
        ),
        sa.Column(
            "total_auth_failures",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="累计认证失败次数（auth 且 status 为 failure/denied），供爆破意图解释",
        ),
        sa.Column(
            "total_queries",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="累计 SQL 数量（query 事件数）",
        ),
        sa.Column(
            "risk_score",
            _tinyint_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="来源画像风险分 0-100，按 9.2 公式（按 rule_code 去重取最大权重后求和并封顶）计算",
        ),
        sa.Column(
            "risk_level",
            mysql.VARCHAR(16),
            sa.Computed(RISK_LEVEL_SQL, persisted=False),
            nullable=False,
            comment="风险等级生成列：critical 严重(80-100) / high 高(60-79) / medium 中(30-59) / low 低(0-29)；由 risk_score 自动推导，禁止手工写入",
        ),
        sa.Column(
            "evidence_summary",
            sa.String(1024),
            nullable=True,
            comment="最近一次计算的证据摘要（命中的规则编码与代表性语句类型），供列表页与答辩解释",
        ),
        sa.Column(
            "last_calculated_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="最近一次风险重算时间（UTC），用于判断画像是否为最新口径",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            _dt6(),
            nullable=False,
            server_default=_now_on_update(),
            comment="行最近更新时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("attacker_id"),
        sa.UniqueConstraint("source_ip", name="uk_attacker_profile_source_ip"),
        comment="攻击者画像表：按来源地址聚合的画像，一行一个来源；不保存意图列表，主要意图由 v_attacker_profile_summary 计算",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "attacker_profile",
        [
            ("ck_profile_seen_order", "last_seen >= first_seen"),
            ("ck_profile_risk_score", "risk_score <= 100"),
        ],
    )

    # ---- 4. attacker_intent：攻击意图表 ----
    op.create_table(
        "attacker_intent",
        sa.Column(
            "intent_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="意图记录编号",
        ),
        sa.Column(
            "attacker_id",
            _bigint_u(),
            nullable=False,
            comment="所属画像编号，引用 attacker_profile.attacker_id",
        ),
        sa.Column(
            "intent_type",
            sa.String(16),
            nullable=False,
            comment="意图类型：scanning 扫描 / bruteforce 爆破 / recon 踩点 / data_dump 拖库 / destructive 破坏性操作",
        ),
        sa.Column(
            "intent_score",
            _tinyint_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="该意图累计可信分 0-100，按 9.2 公式（该意图下按 rule_code 去重取最大权重后求和并封顶）计算",
        ),
        sa.Column(
            "evidence_count",
            _int_u(),
            nullable=False,
            server_default=sa.text("0"),
            comment="支持该意图的规则命中条数（rule_hits 计数），用于排序与解释",
        ),
        sa.Column(
            "first_detected_at",
            _dt6(),
            nullable=False,
            comment="首次识别该意图的时间（UTC）",
        ),
        sa.Column(
            "last_detected_at",
            _dt6(),
            nullable=False,
            comment="最近识别该意图的时间（UTC）；主要意图排序的次级键",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            _dt6(),
            nullable=False,
            server_default=_now_on_update(),
            comment="行最近更新时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("intent_id"),
        sa.ForeignKeyConstraint(
            ["attacker_id"],
            ["attacker_profile.attacker_id"],
            name="fk_intent_profile",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "attacker_id", "intent_type", name="uk_attacker_intent_attacker_type"
        ),
        comment="攻击意图聚合表：一行一条攻击者意图，按画像编号与意图类型复合唯一；命中新证据时更新分数与首末识别时间",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "attacker_intent",
        [
            (
                "ck_intent_type",
                "intent_type IN ('scanning','bruteforce','recon','data_dump','destructive')",
            ),
            ("ck_intent_score", "intent_score <= 100"),
            ("ck_intent_detected_order", "last_detected_at >= first_detected_at"),
        ],
    )

    # ---- 5. detection_rules：检测规则配置表 ----
    op.create_table(
        "detection_rules",
        sa.Column(
            "rule_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="规则行编号；每行代表一条规则的一个版本",
        ),
        sa.Column(
            "rule_code",
            _ascii_bin(16),
            nullable=False,
            comment="稳定规则编码（R01-R05），跨版本不变，禁止复用",
        ),
        sa.Column(
            "rule_name",
            sa.String(100),
            nullable=False,
            comment="规则显示名称，如“短时高频连接扫描”",
        ),
        sa.Column(
            "rule_type",
            sa.String(16),
            nullable=False,
            comment="规则类型枚举：frequency 频率统计 / keyword 关键词 / sequence 序列 / volume 体量",
        ),
        sa.Column(
            "intent_type",
            sa.String(16),
            nullable=False,
            comment="命中后归属的攻击意图：scanning/bruteforce/recon/data_dump/destructive",
        ),
        sa.Column(
            "parameters_json",
            mysql.JSON(),
            nullable=False,
            comment="单条规则内部的阈值与时间窗口参数，结构见 data-model.md 第 10 章",
        ),
        sa.Column(
            "risk_weight",
            _tinyint_u(),
            nullable=False,
            comment="命中计入的风险权重 1-100；按 rule_code 去重后求和",
        ),
        sa.Column(
            "rule_version",
            _smallint_u(),
            nullable=False,
            server_default=sa.text("1"),
            comment="规则版本号，从 1 递增；与 rule_code 复合唯一",
        ),
        sa.Column(
            "enabled",
            _tinybool(),
            nullable=False,
            server_default=sa.text("1"),
            comment="是否参与检测：1 启用 / 0 停用；同一 rule_code 至多一个启用版本",
        ),
        sa.Column(
            "enabled_rule_code",
            _ascii_bin(16),
            sa.Computed(ENABLED_RULE_CODE_SQL, persisted=True),
            nullable=True,
            comment="生成列：启用时等于 rule_code，停用时为 NULL；用于唯一约束保证同一规则至多一个启用版本",
        ),
        sa.Column(
            "description",
            sa.String(500),
            nullable=True,
            comment="规则说明、阈值依据与已知误报，供管理员与答辩解释使用",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            _dt6(),
            nullable=False,
            server_default=_now_on_update(),
            comment="最近更新时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.UniqueConstraint(
            "rule_code", "rule_version", name="uk_detection_rules_code_version"
        ),
        sa.UniqueConstraint(
            "enabled_rule_code", name="uk_detection_rules_enabled_code"
        ),
        comment="检测规则配置表：一行一条规则的一个版本；分析层只执行 enabled=1 的版本，历史命中保留命中时的版本与权重快照",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "detection_rules",
        [
            (
                "ck_detection_rules_rule_type",
                "rule_type IN ('frequency','keyword','sequence','volume')",
            ),
            (
                "ck_detection_rules_intent_type",
                "intent_type IN ('scanning','bruteforce','recon','data_dump','destructive')",
            ),
            ("ck_detection_rules_risk_weight", "risk_weight BETWEEN 1 AND 100"),
            ("ck_detection_rules_rule_version", "rule_version >= 1"),
            ("ck_detection_rules_enabled", "enabled IN (0,1)"),
        ],
    )

    # ---- 6. rule_hits：规则命中表 ----
    op.create_table(
        "rule_hits",
        sa.Column(
            "hit_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="命中编号；被 alerts.latest_hit_id 引用",
        ),
        sa.Column(
            "event_id",
            _bigint_u(),
            nullable=False,
            comment="命中的事件编号，引用 attack_log.event_id；与 session_id 组成复合外键保证同源",
        ),
        sa.Column(
            "session_id",
            _uuid_char(),
            nullable=False,
            comment="命中所属会话编号，引用 sessions.session_id",
        ),
        sa.Column(
            "rule_id",
            _bigint_u(),
            nullable=False,
            comment="命中的规则行编号，引用 detection_rules.rule_id",
        ),
        sa.Column(
            "rule_code",
            _ascii_bin(16),
            nullable=False,
            comment="命中时的规则编码快照（R01-R05），便于证据展示、视图聚合而不必回连规则表",
        ),
        sa.Column(
            "intent_type",
            sa.String(16),
            nullable=False,
            comment="命中时的目标意图快照；意图分与画像分据此按历史口径复算",
        ),
        sa.Column(
            "rule_version",
            _smallint_u(),
            nullable=False,
            comment="命中时实际采用的规则版本快照",
        ),
        sa.Column(
            "risk_weight",
            _tinyint_u(),
            nullable=False,
            comment="命中时的风险权重快照 1-100；本次命中的计分贡献即该值，规则后续调整不影响历史",
        ),
        sa.Column(
            "evidence_summary",
            sa.String(1024),
            nullable=False,
            comment="可解释证据摘要，如“会话内出现 SHOW TABLES 语句”或“5 分钟内认证 9 次、凭据组合 6 组”",
        ),
        sa.Column(
            "triggered_at",
            _dt6(),
            nullable=False,
            comment="命中时间（UTC），由分析层写入；与 event_time 可能不同（窗口统计型规则在窗口结束时触发）",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行落库时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("hit_id"),
        # 复合外键：保证命中行的事件与会话来自同一会话（父索引 uk_attack_log_event_session）
        sa.ForeignKeyConstraint(
            ["event_id", "session_id"],
            ["attack_log.event_id", "attack_log.session_id"],
            name="fk_hit_log",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            name="fk_hit_session",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["detection_rules.rule_id"],
            name="fk_hit_rule",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "event_id", "rule_id", "rule_version", name="uk_rule_hits_event_rule_version"
        ),
        sa.Index("idx_hit_event_session", "event_id", "session_id"),
        sa.Index("idx_hit_rule_time", "rule_id", "created_at"),
        sa.Index("idx_hit_session_time", "session_id", "triggered_at"),
        comment="规则命中表：一次命中一行，保存命中时的规则版本、权重与意图快照；与攻击日志、会话、规则构成可回溯证据链",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "rule_hits",
        [
            (
                "ck_hit_intent_type",
                "intent_type IN ('scanning','bruteforce','recon','data_dump','destructive')",
            ),
            ("ck_hit_risk_weight", "risk_weight BETWEEN 1 AND 100"),
            ("ck_hit_rule_version", "rule_version >= 1"),
        ],
    )

    # ---- 7. alerts：告警表 ----
    op.create_table(
        "alerts",
        sa.Column(
            "alert_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="告警编号",
        ),
        sa.Column(
            "dedup_key",
            _ascii_bin(160),
            nullable=False,
            comment="告警去重键，格式 <rule_code>:<source_ip>:<UTC 日期>，如 R05:192.0.2.10:2026-11-19；唯一约束保证同一触发条件同日只有一条告警",
        ),
        sa.Column(
            "session_id",
            _uuid_char(),
            nullable=False,
            comment="关联会话编号，引用 sessions.session_id；取首次触发告警的会话",
        ),
        sa.Column(
            "attacker_id",
            _bigint_u(),
            nullable=False,
            comment="关联攻击者画像编号，引用 attacker_profile.attacker_id",
        ),
        sa.Column(
            "rule_id",
            _bigint_u(),
            nullable=False,
            comment="首次触发告警的规则行编号，引用 detection_rules.rule_id",
        ),
        sa.Column(
            "rule_code",
            _ascii_bin(16),
            nullable=False,
            comment="触发规则编码快照，供列表展示与视图聚合，避免回连规则表",
        ),
        sa.Column(
            "latest_hit_id",
            _bigint_u(),
            nullable=False,
            comment="最近一次触发该告警的规则命中编号，引用 rule_hits.hit_id；证据可定位",
        ),
        sa.Column(
            "alert_type",
            sa.String(16),
            nullable=False,
            comment="告警类型枚举：bruteforce 爆破 / data_dump 拖库 / destructive 破坏性操作；仅这三类意图生成告警",
        ),
        sa.Column(
            "severity",
            sa.String(8),
            nullable=False,
            comment="告警等级：low 低 / medium 中 / high 高 / critical 严重；映射规则见 data-model 9.4",
        ),
        sa.Column(
            "title",
            sa.String(200),
            nullable=False,
            comment="告警标题（中文），如“疑似拖库：来自 192.0.2.10 的会话累计返回 1200 行”",
        ),
        sa.Column(
            "evidence_summary",
            sa.String(1024),
            nullable=False,
            comment="告警证据摘要：规则编码、命中时间、代表性语句与统计值，禁止只给标签",
        ),
        sa.Column(
            "first_seen_at",
            _dt6(),
            nullable=False,
            comment="首次触发时间（UTC）；插入告警时写入",
        ),
        sa.Column(
            "last_seen_at",
            _dt6(),
            nullable=False,
            comment="最近触发时间（UTC）；重复触发时以 GREATEST 更新",
        ),
        sa.Column(
            "occurrence_count",
            _int_u(),
            nullable=False,
            server_default=sa.text("1"),
            comment="触发次数；首次为 1，重复触发原子自增",
        ),
        sa.Column(
            "is_read",
            _tinybool(),
            nullable=False,
            server_default=sa.text("0"),
            comment="已读标记：0 未读 / 1 已读；已读更新是独立写操作",
        ),
        sa.Column(
            "read_at",
            _dt6(),
            nullable=True,
            comment="标记已读的时间（UTC）；未读时为 NULL；与 is_read 的一致性由检查约束保证",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行创建（首次告警）时间（UTC），等于 first_seen_at 的落库时刻",
        ),
        sa.Column(
            "updated_at",
            _dt6(),
            nullable=False,
            server_default=_now_on_update(),
            comment="行最近更新时间（UTC），重复触发与已读操作都会更新",
        ),
        sa.PrimaryKeyConstraint("alert_id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            name="fk_alert_session",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attacker_id"],
            ["attacker_profile.attacker_id"],
            name="fk_alert_attacker",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["detection_rules.rule_id"],
            name="fk_alert_rule",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_hit_id"],
            ["rule_hits.hit_id"],
            name="fk_alert_latest_hit",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("dedup_key", name="uk_alerts_dedup_key"),
        sa.Index("idx_alert_level_time", "severity", "created_at"),
        sa.Index("idx_alert_session_time", "session_id", "created_at"),
        sa.Index("idx_alert_attacker_time", "attacker_id", "created_at"),
        sa.Index("idx_alert_latest_hit", "latest_hit_id"),
        # data-model 7.1 索引总表未列出但外键 fk_alert_rule 必需的子表索引；
        # 显式命名，避免 MySQL 自动生成名 fk_alert_rule 造成结构不可预测
        sa.Index("idx_alert_rule", "rule_id"),
        comment="告警表：爆破/拖库/破坏性操作首次命中生成，dedup_key 唯一约束实现同日同规则同来源去重；重复触发更新次数与最近时间",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "alerts",
        [
            (
                "ck_alert_type",
                "alert_type IN ('bruteforce','data_dump','destructive')",
            ),
            (
                "ck_alert_severity",
                "severity IN ('low','medium','high','critical')",
            ),
            ("ck_alert_seen_order", "last_seen_at >= first_seen_at"),
            ("ck_alert_occurrence_count", "occurrence_count >= 1"),
            ("ck_alert_is_read", "is_read IN (0,1)"),
            ("ck_alert_read_at", "read_at IS NULL OR is_read = 1"),
        ],
    )

    # ---- 8. fake_users：诱饵用户表 ----
    op.create_table(
        "fake_users",
        sa.Column(
            "id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="诱饵用户编号",
        ),
        sa.Column(
            "username",
            sa.String(64),
            nullable=False,
            comment="虚构诱饵账号，形如 demo_user_01，明显非真实人员",
        ),
        sa.Column(
            "email",
            sa.String(120),
            nullable=False,
            comment="虚构邮箱，统一使用 example.test 保留域名",
        ),
        sa.Column(
            "phone",
            sa.String(32),
            nullable=False,
            comment="虚构手机号，统一使用 199-0000-00NN 号段，明显非真实号码",
        ),
        sa.Column(
            "password_hash",
            sa.String(120),
            nullable=False,
            comment="不可用的伪哈希，必须以 TEST-ONLY$ 开头（检查约束强制），不参与任何真实认证",
        ),
        sa.Column(
            "display_name",
            sa.String(64),
            nullable=False,
            comment="虚构显示名，形如 演示用户01",
        ),
        sa.Column(
            "is_synthetic",
            _tinybool(),
            nullable=False,
            server_default=sa.text("1"),
            comment="合成标记，检查约束强制恒为 1，保证所有诱饵数据可识别为人工生成",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行创建时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uk_fake_users_username"),
        sa.UniqueConstraint("email", name="uk_fake_users_email"),
        comment="诱饵用户表：完全虚构的展示数据，仅用于诱饵层返回；password_hash 为不可用伪哈希，检查约束强制 TEST-ONLY$ 前缀",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "fake_users",
        [
            ("ck_fake_users_password_hash", "password_hash LIKE 'TEST-ONLY$%'"),
            ("ck_fake_users_synthetic", "is_synthetic = 1"),
        ],
    )

    # ---- 9. fake_orders：诱饵订单表 ----
    op.create_table(
        "fake_orders",
        sa.Column(
            "order_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="诱饵订单编号",
        ),
        sa.Column(
            "order_no",
            _ascii_bin(32),
            nullable=False,
            comment="虚构订单号，形如 FAKE-202611-00001",
        ),
        sa.Column(
            "user_id",
            _bigint_u(),
            nullable=False,
            comment="所属诱饵用户编号，引用 fake_users.id",
        ),
        sa.Column(
            "amount",
            mysql.DECIMAL(12, 2),
            nullable=False,
            comment="虚构订单金额（元），精确小数，非负",
        ),
        sa.Column(
            "currency",
            _ascii_char(3),
            nullable=False,
            server_default="CNY",
            comment="币种代码，默认 CNY",
        ),
        sa.Column(
            "order_status",
            sa.String(16),
            nullable=False,
            server_default="paid",
            comment="订单状态：pending 待支付 / paid 已支付 / shipped 已发货 / cancelled 已取消 / refunded 已退款",
        ),
        sa.Column(
            "remark",
            sa.String(200),
            nullable=True,
            comment="虚构备注，用于构造更真实的大结果集响应",
        ),
        sa.Column(
            "is_synthetic",
            _tinybool(),
            nullable=False,
            server_default=sa.text("1"),
            comment="合成标记，强制恒为 1",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="虚构下单时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("order_id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["fake_users.id"],
            name="fk_fake_orders_user",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("order_no", name="uk_fake_orders_order_no"),
        sa.Index("idx_fake_orders_user", "user_id", "created_at"),
        comment="诱饵订单表：完全虚构的业务数据，含 120 条种子记录用于构造大结果集；仅用于诱饵层展示，不参与检测",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "fake_orders",
        [
            ("ck_fake_orders_amount", "amount >= 0"),
            (
                "ck_fake_orders_status",
                "order_status IN ('pending','paid','shipped','cancelled','refunded')",
            ),
            ("ck_fake_orders_synthetic", "is_synthetic = 1"),
        ],
    )

    # ---- 10. fake_config：诱饵配置表 ----
    op.create_table(
        "fake_config",
        sa.Column(
            "config_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="诱饵配置编号",
        ),
        sa.Column(
            "config_key",
            _ascii_bin(64),
            nullable=False,
            comment="配置项键名，如 db.primary.connection_string",
        ),
        sa.Column(
            "config_value",
            sa.String(512),
            nullable=False,
            comment="无效的诱饵值，必须以 TEST-ONLY 开头；连接串只指向本机无效端口，密钥为占位串",
        ),
        sa.Column(
            "category",
            sa.String(32),
            nullable=False,
            comment="配置分类：database 数据库 / mail 邮件 / api 第三方接口 / storage 对象存储",
        ),
        sa.Column(
            "description",
            sa.String(200),
            nullable=True,
            comment="配置项说明（中文），说明这是测试数据",
        ),
        sa.Column(
            "is_invalid",
            _tinybool(),
            nullable=False,
            server_default=sa.text("1"),
            comment="无效标记，强制恒为 1",
        ),
        sa.Column(
            "created_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="行创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            _dt6(),
            nullable=False,
            server_default=_now_on_update(),
            comment="行最近更新时间（UTC）",
        ),
        sa.PrimaryKeyConstraint("config_id"),
        sa.UniqueConstraint("config_key", name="uk_fake_config_config_key"),
        comment="诱饵配置表：看似敏感但完全无效的配置项；检查约束强制 config_value 以 TEST-ONLY 开头，禁止真实凭据入库",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "fake_config",
        [
            ("ck_fake_config_test_only", "config_value LIKE 'TEST-ONLY%'"),
            (
                "ck_fake_config_category",
                "category IN ('database','mail','api','storage')",
            ),
            ("ck_fake_config_invalid", "is_invalid = 1"),
        ],
    )

    # ---- 11. audit_log：审计日志表（仅追加） ----
    op.create_table(
        "audit_log",
        sa.Column(
            "audit_id",
            _bigint_u(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="审计编号",
        ),
        sa.Column(
            "occurred_at",
            _dt6(),
            nullable=False,
            server_default=_now(),
            comment="操作发生时间（UTC）",
        ),
        sa.Column(
            "account_name",
            _ascii_bin(64),
            nullable=False,
            comment="执行操作的数据库账号名（非应用用户），如 honeypot_app_rw",
        ),
        sa.Column(
            "operation",
            sa.String(32),
            nullable=False,
            comment="操作类型：reset 演示重置 / rule_change 规则版本变更 / alert_ack 告警已读 / export 数据导出 / migration 迁移执行 / manual_query 人工查询 / login_failed 连接失败",
        ),
        sa.Column(
            "target_table",
            sa.String(64),
            nullable=True,
            comment="涉及的业务表名，如 attack_log",
        ),
        sa.Column(
            "target_key",
            sa.String(128),
            nullable=True,
            comment="涉及的主键或去重键（脱敏后），如告警去重键或规则编码",
        ),
        sa.Column(
            "result",
            sa.String(16),
            nullable=False,
            comment="操作结果：success 成功 / failure 失败",
        ),
        sa.Column(
            "detail",
            sa.String(1000),
            nullable=True,
            comment="结构化说明；禁止写入口令、完整 SQL 原文或任何真实凭据",
        ),
        sa.Column(
            "request_id",
            _uuid_char(),
            nullable=True,
            comment="一次业务操作的关联编号（UUID v4 文本），用于串联同一操作的多条审计记录",
        ),
        sa.PrimaryKeyConstraint("audit_id"),
        comment="审计日志表：仅追加重放记录关键写操作（重置、规则变更、告警已读、导出、迁移）；业务账号仅可插入与查询，不可修改删除",
        **TABLE_OPTIONS,
    )
    _add_checks(
        "audit_log",
        [
            (
                "ck_audit_operation",
                "operation IN ('reset','rule_change','alert_ack','export','migration','manual_query','login_failed')",
            ),
            ("ck_audit_result", "result IN ('success','failure')"),
        ],
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """按外键逆序删除 11 张表（data-model 12.5）。"""
    for table in (
        "audit_log",
        "fake_config",
        "fake_orders",
        "fake_users",
        "alerts",
        "rule_hits",
        "detection_rules",
        "attacker_intent",
        "attacker_profile",
        "attack_log",
        "sessions",
    ):
        op.drop_table(table)
