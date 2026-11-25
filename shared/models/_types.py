"""ORM 模型公共列类型构造函数。

数据模型（`specs/001-database-honeypot/data-model.md` 2.3 / 2.5）要求：
- UUID 文本列使用 `CHAR(36) CHARACTER SET ascii COLLATE ascii_bin`；
- IP 文本列使用 `VARCHAR(45) CHARACTER SET ascii COLLATE ascii_general_ci`；
- 稳定编码/去重键使用 `ascii_bin`，中文与攻击载荷使用库默认 `utf8mb4_0900_ai_ci`；
- 时刻列统一 `DATETIME(6)` 并存 UTC；
- 分数/权重使用 `TINYINT UNSIGNED`，计数使用 `INT UNSIGNED`，端口使用 `SMALLINT UNSIGNED`。

这里集中构造 MySQL 方言类型，保证 11 张表的字符集与精度口径一致。
"""

from __future__ import annotations

from sqlalchemy.dialects import mysql


def uuid_char() -> mysql.CHAR:
    """UUID v4 文本列：CHAR(36) ascii_bin（会话主键、幂等键、审计关联编号）。"""
    return mysql.CHAR(36, charset="ascii", collation="ascii_bin")


def source_ip() -> mysql.VARCHAR:
    """来源地址列：VARCHAR(45) ascii_general_ci，兼容 IPv4/IPv6 文本。"""
    return mysql.VARCHAR(45, charset="ascii", collation="ascii_general_ci")


def ascii_bin(length: int) -> mysql.VARCHAR:
    """稳定机器可读标识列：ascii_bin，大小写严格区分。"""
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def ascii_char(length: int) -> mysql.CHAR:
    """定长机器可读标识列：CHAR(n) ascii_bin（如币种代码）。"""
    return mysql.CHAR(length, charset="ascii", collation="ascii_bin")


def datetime6() -> mysql.DATETIME:
    """UTC 时刻列：DATETIME(6)，微秒精度，不使用 TIMESTAMP。"""
    return mysql.DATETIME(fsp=6)


def bigint_unsigned() -> mysql.BIGINT:
    """自增代理主键/外键列：BIGINT UNSIGNED。"""
    return mysql.BIGINT(unsigned=True)


def int_unsigned() -> mysql.INTEGER:
    """非负计数列：INT UNSIGNED（行数、次数、毫秒）。"""
    return mysql.INTEGER(unsigned=True)


def tinyint_unsigned() -> mysql.TINYINT:
    """分数/权重列：TINYINT UNSIGNED（0-100 / 1-100）。"""
    return mysql.TINYINT(unsigned=True)


def tinyint_bool() -> mysql.TINYINT:
    """布尔标记列：TINYINT(1)，配合 CHECK (col IN (0,1))。"""
    return mysql.TINYINT(display_width=1)


def smallint_unsigned() -> mysql.SMALLINT:
    """端口/版本号列：SMALLINT UNSIGNED。"""
    return mysql.SMALLINT(unsigned=True)
