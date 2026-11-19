"""伪造库表目录单元测试：命名、结构、合成数据与凭据安全。"""

from __future__ import annotations

import pytest

from app.honeypot import fake_catalog
from app.honeypot.fake_catalog import (
    ARCHIVE_DATABASE,
    DATABASES,
    EXPECTED_ROWS,
    PRIMARY_DATABASE,
    SHOP_DATABASE,
    TABLES,
    fetch_rows,
    get_table,
    is_fallback,
    list_tables,
    load_fake_schema,
    resolve_table,
    row_count,
    schema,
)


def test_exposed_database_names_are_synthetic():
    """对外投影库名固定为 honeypot_shop / honeypot_archive。"""
    assert DATABASES == (SHOP_DATABASE, ARCHIVE_DATABASE)
    assert SHOP_DATABASE == "honeypot_shop"
    assert ARCHIVE_DATABASE == "honeypot_archive"
    assert PRIMARY_DATABASE == SHOP_DATABASE


def test_projected_tables_and_columns():
    """投影表结构：shop 三张表 + archive 一张表，且不暴露物理 fake_* 表名。"""
    assert set(TABLES) == {
        (SHOP_DATABASE, "users"),
        (SHOP_DATABASE, "orders"),
        (SHOP_DATABASE, "config"),
        (ARCHIVE_DATABASE, "orders_2025"),
    }
    assert all("fake_" not in name for _, name in TABLES)
    assert TABLES[(SHOP_DATABASE, "users")].column_names()[:3] == [
        "id",
        "username",
        "email",
    ]
    assert TABLES[(SHOP_DATABASE, "users")].column("id").key == "PRI"
    assert TABLES[(SHOP_DATABASE, "orders")].column("order_no").key == "UNI"


def test_schema_projection():
    """``schema()`` 返回 {库: {表: {列: 类型}}} 结构。"""
    projected = schema()
    assert set(projected) == set(DATABASES)
    assert set(projected[SHOP_DATABASE]) == {"users", "orders", "config"}
    assert projected[SHOP_DATABASE]["users"]["username"].startswith("varchar")
    assert "orders_2025" in projected[ARCHIVE_DATABASE]


def test_list_tables_sorted():
    """表列表按名称稳定排序。"""
    assert [t.name for t in list_tables(SHOP_DATABASE)] == ["config", "orders", "users"]
    assert list_tables("unknown_db") == []


@pytest.mark.parametrize(
    ("database", "table", "expected"),
    [
        (None, "users", (SHOP_DATABASE, "users")),
        (SHOP_DATABASE, "orders", (SHOP_DATABASE, "orders")),
        (ARCHIVE_DATABASE, "orders_2025", (ARCHIVE_DATABASE, "orders_2025")),
        (None, "`USERS`", (SHOP_DATABASE, "users")),
        (None, "unknown_table", None),
        (None, "", None),
    ],
)
def test_get_table_resolution(database, table, expected):
    """库名/表名解析支持裸表名、反引号与大小写归一。"""
    meta = get_table(database, table)
    if expected is None:
        assert meta is None
    else:
        assert meta is not None
        assert (meta.database, meta.name) == expected


def test_resolve_table_variants():
    """``resolve_table`` 支持 ``库.表`` 与默认库回退。"""
    assert resolve_table("honeypot_shop.users") == (SHOP_DATABASE, "users")
    assert resolve_table("HONEYPOT_SHOP.`ORDERS`") == (SHOP_DATABASE, "orders")
    assert resolve_table("users", SHOP_DATABASE) == (SHOP_DATABASE, "users")
    assert resolve_table("orders_2025") == (ARCHIVE_DATABASE, "orders_2025")
    assert resolve_table("missing") is None


def test_expected_row_counts_are_contractual():
    """固定行数口径与 contracts/honeypot-protocol.md 一致。"""
    assert EXPECTED_ROWS == {"users": 30, "orders": 120, "config": 8}


def _iter_row_values(rows):
    for row in rows:
        for value in row.values():
            yield str(value)


def test_fallback_data_is_obviously_synthetic():
    """内置兜底数据无可用于真实认证的内容。"""
    for key, rows in fake_catalog._FALLBACK_ROWS.items():  # noqa: SLF001 - 测试内部数据
        assert rows, key
        for value in _iter_row_values(rows):
            lowered = value.lower()
            assert "password123" not in lowered
            assert "root:" not in lowered
    for row in fake_catalog._FALLBACK_ROWS[(SHOP_DATABASE, "users")]:  # noqa: SLF001
        assert row["email"].endswith("@example.invalid")
        assert row["phone"].startswith("199")
        assert row["password_hash"].startswith("TEST-ONLY")
    for row in fake_catalog._FALLBACK_ROWS[(SHOP_DATABASE, "config")]:  # noqa: SLF001
        key = str(row["config_key"]).lower()
        if any(token in key for token in ("password", "secret", "key", "token")):
            assert str(row["config_value"]).startswith("TEST-ONLY")
        elif "host" in key:
            # 主机类配置只指向不可路由/本机无效端口
            assert str(row["config_value"]).startswith(("10.255.255.", "127.0.0.1"))


async def test_load_physical_fake_tables(db_session):
    """强制从物理 ``fake_*`` 表加载：行数与合成标记正确，无兜底。"""
    await load_fake_schema(db_session, force=True)

    assert row_count((SHOP_DATABASE, "users")) == 30
    assert row_count((SHOP_DATABASE, "orders")) == 120
    assert row_count((SHOP_DATABASE, "config")) == 5
    assert is_fallback((SHOP_DATABASE, "users")) is False

    users = fake_catalog.all_rows((SHOP_DATABASE, "users"))
    orders = fake_catalog.all_rows((SHOP_DATABASE, "orders"))
    configs = fake_catalog.all_rows((SHOP_DATABASE, "config"))

    for user in users:
        assert user["email"].endswith("@example.com")
        assert user["phone"].startswith("1380000")
        assert str(user["password_hash"]).startswith("TEST-ONLY$")
        assert user["role"] in {"admin", "staff", "customer"}

    for order in orders:
        assert str(order["order_no"]).startswith("FAKE-202611-")
        assert order["amount"] >= 0
        assert order["status"] in {"pending", "paid", "shipped", "cancelled", "refunded"}

    for config in configs:
        assert str(config["config_value"]).startswith("TEST-ONLY")


async def test_fetch_rows_projection_and_limit(db_session):
    """``fetch_rows`` 支持列投影、LIMIT 与未知表 KeyError。"""
    await load_fake_schema(db_session, force=True)

    rows = await fetch_rows(db_session, "honeypot_shop.users", ["id", "username"], limit=5)
    assert len(rows) == 5
    assert all(len(row) == 2 for row in rows)
    assert all(isinstance(row[0], int) for row in rows)

    with pytest.raises(KeyError):
        await fetch_rows(db_session, "not_a_table")


async def test_catalog_contains_no_real_credentials(db_session):
    """全量扫描投影数据：任何“凭据类”字段都必须是 TEST-ONLY 合成值。"""
    await load_fake_schema(db_session, force=True)

    users = fake_catalog.all_rows((SHOP_DATABASE, "users"))
    configs = fake_catalog.all_rows((SHOP_DATABASE, "config"))
    for user in users:
        assert "TEST-ONLY" in str(user["password_hash"])
        assert not str(user["password_hash"]).startswith("$2b$")
    for config in configs:
        key = str(config["config_key"]).lower()
        if any(token in key for token in ("password", "secret", "key", "token")):
            assert "TEST-ONLY" in str(config["config_value"]).upper()
