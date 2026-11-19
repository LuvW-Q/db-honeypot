"""SQL 文本处理辅助：去注释、归一化、关键词检测。

供捕获层（协议路由）与分析层（规则匹配）共用，保证"采集语句归一化"只有一个
事实来源（contracts/events.md 3.3、contracts/honeypot-protocol.md 3.3）。

安全说明：本模块只做**字符串**处理，绝不执行任何 SQL；采集到的语句不会被交给
数据库驱动、`eval`/`exec`、子进程或模板引擎。
"""

from __future__ import annotations

import re

# 归一化后的 SQL 允许出现的"首个关键字 → 语句类型"映射（events.md 3.2）。
# 未列出的关键字一律归为 OTHER，避免把新语法误判成已知类型。
_STATEMENT_TYPES: dict[str, str] = {
    "SELECT": "SELECT",
    "INSERT": "INSERT",
    "UPDATE": "UPDATE",
    "DELETE": "DELETE",
    "DROP": "DROP",
    "TRUNCATE": "TRUNCATE",
    "ALTER": "ALTER",
    "CREATE": "CREATE",
    "SHOW": "SHOW",
    "DESCRIBE": "DESCRIBE",
    "DESC": "DESCRIBE",
    "EXPLAIN": "DESCRIBE",
    "USE": "USE",
    "SET": "SET",
}

# 用于规则匹配/路由判定的关键字集合（大小写不敏感，统一比较大写）。
# 覆盖 R03/R04/R05 需要的侦察、批量读取与破坏性关键词；不追求完整 SQL 词表。
KEYWORDS: frozenset[str] = frozenset(
    {
        "SELECT",
        "FROM",
        "WHERE",
        "AND",
        "OR",
        "UNION",
        "ALL",
        "JOIN",
        "INTO",
        "OUTFILE",
        "DUMPFILE",
        "INFORMATION_SCHEMA",
        "TABLE",
        "TABLES",
        "DATABASE",
        "DATABASES",
        "SCHEMA",
        "SHOW",
        "DESCRIBE",
        "DESC",
        "EXPLAIN",
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "GRANT",
        "REVOKE",
        "INSTALL",
        "KILL",
        "LOAD",
        "DATA",
        "INFILE",
        "LOCAL",
        "SLEEP",
        "BENCHMARK",
        "WAITFOR",
        "DELAY",
        "PROCEDURE",
        "ANALYZE",
        "LIMIT",
        "ORDER",
        "GROUP",
        "HAVING",
        "LIKE",
        "VERSION",
        "USER",
        "CURRENT_USER",
        "COUNT",
        "COLUMNS",
        "FIELDS",
    }
)

# 字符串字面量：单引号/双引号，支持反斜杠转义与 '' 双写转义。
_STRING_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"", re.DOTALL)
# 十六进制字面量：0x1F、X'1F' 中后者已按字符串处理。
_HEX_LITERAL_RE = re.compile(r"(?<![\w.])0x[0-9a-fA-F]+(?![\w.])")
# 数字字面量：整数/小数；用 \b 语义避免误伤 users_2025 这类标识符。
_NUMBER_LITERAL_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LEADING_WORD_RE = re.compile(r"^[\s(]*([A-Za-z_][A-Za-z0-9_]*)")


def strip_sql_comments(sql: str | None) -> str:
    """去掉 SQL 注释，保留字符串字面量中的内容。

    支持 MySQL 三种注释：``-- ``（要求后跟空白或行尾）、``#`` 行注释、``/* ... */``
    块注释；识别单引号、双引号与反引号，避免把字面量里的 ``--``/``#`` 误删。
    不尝试处理嵌套块注释（MySQL 本身也不支持）。
    """
    if not sql:
        return ""
    out: list[str] = []
    i = 0
    n = len(sql)
    quote: str | None = None
    while i < n:
        ch = sql[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:  # 字符串内反斜杠转义
                out.append(sql[i + 1])
                i += 2
                continue
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:  # '' 双写转义
                    out.append(quote)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-" and (
            i + 2 >= n or sql[i + 2].isspace()
        ):
            i += 2
            while i < n and sql[i] not in "\r\n":
                i += 1
            out.append(" ")
            continue
        if ch == "#":
            i += 1
            while i < n and sql[i] not in "\r\n":
                i += 1
            out.append(" ")
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize_sql(sql: str | None) -> str | None:
    """确定性归一化：去注释 → 字面量替换 ``?`` → 折叠空白 → 统一小写。

    - 关键字与标识符统一小写（与 events.md 3.3 示例一致）；
    - 字符串/数字/十六进制字面量替换为 ``?``，便于规则匹配与去重比较；
    - 结果可复现，不依赖时间与随机数。
    """
    if sql is None:
        return None
    text = strip_sql_comments(sql)
    if not text:
        return None
    text = _STRING_LITERAL_RE.sub("?", text)
    text = _HEX_LITERAL_RE.sub("?", text)
    text = _NUMBER_LITERAL_RE.sub("?", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    return text.lower()


def sql_keywords(sql: str | None) -> set[str]:
    """返回语句中出现的关键字集合（大写），供分析层做关键词类规则判定。

    仅基于 ``strip_sql_comments`` 后的词元做集合匹配，不做语法分析。
    """
    text = strip_sql_comments(sql)
    if not text:
        return set()
    return {token.upper() for token in _WORD_RE.findall(text) if token.upper() in KEYWORDS}


def first_keyword(sql: str | None) -> str | None:
    """取语句首个关键字并映射为 events.md 3.2 的 ``statement_type``。

    返回 ``SELECT/INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/SHOW/
    DESCRIBE/USE/SET/OTHER`` 之一；空语句返回 ``None``。
    """
    text = strip_sql_comments(sql)
    if not text:
        return None
    match = _LEADING_WORD_RE.match(text)
    if not match:
        return "OTHER"
    token = match.group(1).upper()
    return _STATEMENT_TYPES.get(token, "OTHER")
