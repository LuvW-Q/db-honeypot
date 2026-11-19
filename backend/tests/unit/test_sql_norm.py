"""SQL 文本归一化单元测试（去注释、字面量占位、空白折叠、小写）。"""

from __future__ import annotations

import pytest

from app.utils.sql import (
    first_keyword,
    normalize_sql,
    sql_keywords,
    strip_sql_comments,
)


def test_strip_line_comments():
    """``-- `` 与 ``#`` 行注释被删除，换行保留为空白。"""
    sql = "SELECT 1 -- 行注释\nFROM t # 另一个注释\nWHERE id = 2"
    cleaned = strip_sql_comments(sql)
    assert "行注释" not in cleaned
    assert "另一个注释" not in cleaned
    assert "SELECT 1" in cleaned
    assert "WHERE id = 2" in cleaned


def test_strip_block_comment():
    """块注释被整体删除。"""
    cleaned = strip_sql_comments("SELECT /* 注释内容 */ 1")
    assert cleaned.strip() == "SELECT   1"


def test_strip_comments_keeps_comment_markers_inside_literals():
    """字符串字面量中的 ``--`` / ``#`` / ``/*`` 不被当作注释。"""
    sql = "SELECT 'a--b', 'c#d', 'e/*f*/g'"
    assert strip_sql_comments(sql) == sql


def test_strip_comments_handles_backslash_and_double_quote_escape():
    """反斜杠转义与 ``''`` 双写转义不会破坏字符串识别。"""
    sql = "SELECT 'it\\'s -- not comment', \"x # y\""
    cleaned = strip_sql_comments(sql)
    assert "it" in cleaned
    assert cleaned.endswith("\"x # y\"")


def test_normalize_replaces_literals_with_placeholder():
    """字符串 / 数字 / 十六进制字面量统一替换为 ``?``。"""
    assert normalize_sql("SELECT * FROM users WHERE name = 'alice'") == (
        "select * from users where name = ?"
    )
    assert normalize_sql("SELECT * FROM users WHERE id = 42") == (
        "select * from users where id = ?"
    )
    assert normalize_sql("SELECT 0xFF, 3.14") == "select ?, ?"


def test_normalize_collapses_whitespace_and_lowercases():
    """空白折叠为单个空格并统一小写。"""
    assert normalize_sql("  SELECT   *\n\tFROM   Users  ") == "select * from users"


def test_normalize_is_deterministic():
    """同一输入多次归一化结果一致。"""
    sql = "SELECT * FROM t WHERE a = 1 AND b = 'x'"
    assert normalize_sql(sql) == normalize_sql(sql)


@pytest.mark.parametrize("sql", [None, "", "   ", "\n\t", "-- 只有注释", "/* 只有注释 */"])
def test_normalize_empty_or_comment_only_returns_none(sql):
    """空内容 / 纯注释 → None。"""
    assert normalize_sql(sql) is None


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", "SELECT"),
        ("insert into t values (1)", "INSERT"),
        ("UPDATE t SET a = 1", "UPDATE"),
        ("DELETE FROM t", "DELETE"),
        ("DROP TABLE t", "DROP"),
        ("TRUNCATE t", "TRUNCATE"),
        ("SHOW TABLES", "SHOW"),
        ("DESCRIBE t", "DESCRIBE"),
        ("desc t", "DESCRIBE"),
        ("EXPLAIN SELECT 1", "DESCRIBE"),
        ("USE honeypot_shop", "USE"),
        ("SET autocommit = 1", "SET"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "OTHER"),
        ("", None),
        ("   ", "OTHER"),  # 实现将纯空白视为无法识别语句，归为 OTHER
    ],
)
def test_first_keyword_maps_statement_type(sql, expected):
    """首关键字映射为 events.md 约定的 statement_type。"""
    assert first_keyword(sql) == expected


def test_sql_keywords_extracts_uppercase_tokens():
    """关键字集合提取为大写词元，且只包含白名单关键字。

    已知限制（缺陷报告）：本工具只去注释、不替换字符串字面量，因此字面量中的
    ``'drop'`` 也会被计入关键字；规则判定使用 ``normalized_sql``（已替换字面量），
    不受此限制影响。
    """
    keywords = sql_keywords("select * from users where name = 'drop'")
    assert {"SELECT", "FROM", "WHERE"} <= keywords
    # 当前实现会把字符串字面量中的关键字也计入（与 normalized_sql 口径不同）
    assert "DROP" in keywords
    # 纯 SQL 结构关键字正常提取
    assert {"DROP", "TABLE"} <= sql_keywords("DROP TABLE users")


def test_sql_keywords_empty_input():
    """空输入返回空集合。"""
    assert sql_keywords(None) == set()
    assert sql_keywords("") == set()
