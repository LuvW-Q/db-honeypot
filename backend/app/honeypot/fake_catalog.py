"""伪造库表目录：对外投影的 `honeypot_shop` / `honeypot_archive` 结构、数据与兜底。

设计要点（`contracts/honeypot-protocol.md` 3.1–3.2、FR-030）：
- 协议层对外的**投影**是 `honeypot_shop.users/orders/config` 与
  `honeypot_archive.orders_2025`，**不是**采集库里的物理 `fake_*` 表；
- 数据优先从采集库 `fake_users` / `fake_orders` / `fake_config` 读取（只读会话），
  读取失败或无数据时使用**内置最小合成数据兜底**（运行日志明确标注）；
- 目录结构与数据是进程内只读缓存，客户端 SQL 永远不会作用到物理表上
  （安全不变量：只存不执行）。

所有值均为合成/占位数据：邮箱 `@example.invalid`、电话 `1990000xxxx`、
哈希 `TEST-ONLY$`/`TEST-ONLY-HASH-` 前缀、配置值含 `TEST-ONLY`，不可用于任何认证。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---- 对外暴露的库与固定结构 ----
SHOP_DATABASE = "honeypot_shop"
ARCHIVE_DATABASE = "honeypot_archive"
PRIMARY_DATABASE = SHOP_DATABASE
INFORMATION_SCHEMA = "information_schema"
DATABASES: tuple[str, ...] = (SHOP_DATABASE, ARCHIVE_DATABASE)

# 伪造表固定行数口径（contracts/honeypot-protocol.md 3.2）
EXPECTED_ROWS: dict[str, int] = {"users": 30, "orders": 120, "config": 8}


@dataclass(frozen=True)
class Column:
    """对外投影的列定义（DESCRIBE / information_schema.columns 使用）。"""

    name: str
    type: str  # 对外展示类型，如 varchar(32) / decimal(10,2) / datetime
    nullable: bool = False
    key: str = ""  # PRI / UNI / ""
    default: str | None = None
    extra: str = ""


@dataclass(frozen=True)
class Table:
    """对外投影的一张伪造表。"""

    database: str
    name: str
    columns: tuple[Column, ...] = field(default_factory=tuple)

    @property
    def key(self) -> tuple[str, str]:
        return (self.database, self.name)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column | None:
        lowered = name.lower()
        for col in self.columns:
            if col.name.lower() == lowered:
                return col
        return None


TABLES: dict[tuple[str, str], Table] = {
    (SHOP_DATABASE, "users"): Table(
        database=SHOP_DATABASE,
        name="users",
        columns=(
            Column("id", "int", nullable=False, key="PRI"),
            Column("username", "varchar(32)", nullable=False),
            Column("email", "varchar(64)", nullable=False),
            Column("phone", "varchar(20)", nullable=False),
            Column("password_hash", "varchar(64)", nullable=False),
            Column("role", "varchar(16)", nullable=False),
            Column("created_at", "datetime", nullable=False),
        ),
    ),
    (SHOP_DATABASE, "orders"): Table(
        database=SHOP_DATABASE,
        name="orders",
        columns=(
            Column("id", "int", nullable=False, key="PRI"),
            Column("user_id", "int", nullable=False),
            Column("order_no", "varchar(32)", nullable=False, key="UNI"),
            Column("amount", "decimal(10,2)", nullable=False),
            Column("status", "varchar(16)", nullable=False),
            Column("created_at", "datetime", nullable=False),
        ),
    ),
    (SHOP_DATABASE, "config"): Table(
        database=SHOP_DATABASE,
        name="config",
        columns=(
            Column("config_key", "varchar(64)", nullable=False, key="PRI"),
            Column("config_value", "varchar(256)", nullable=False),
            Column("description", "varchar(128)", nullable=False),
        ),
    ),
    (ARCHIVE_DATABASE, "orders_2025"): Table(
        database=ARCHIVE_DATABASE,
        name="orders_2025",
        columns=(
            Column("id", "int", nullable=False, key="PRI"),
            Column("user_id", "int", nullable=False),
            Column("order_no", "varchar(32)", nullable=False, key="UNI"),
            Column("amount", "decimal(10,2)", nullable=False),
            Column("status", "varchar(16)", nullable=False),
            Column("created_at", "datetime", nullable=False),
        ),
    ),
}


def schema() -> dict[str, dict[str, dict[str, str]]]:
    """返回 `{库: {表: {列: 类型}}}`，供 SHOW / INFORMATION_SCHEMA 使用。"""
    result: dict[str, dict[str, dict[str, str]]] = {db: {} for db in DATABASES}
    for table in TABLES.values():
        result.setdefault(table.database, {})[table.name] = {
            col.name: col.type for col in table.columns
        }
    return result


def get_table(database: str | None, table: str) -> Table | None:
    """按库名+表名取投影表；`database` 为空时在全部伪造库中查找。"""
    name = _clean_identifier(table)
    if not name:
        return None
    if database:
        return TABLES.get((_clean_identifier(database), name))
    for (_, table_name), meta in TABLES.items():
        if table_name == name:
            return meta
    return None


def list_tables(database: str) -> list[Table]:
    """列出某伪造库的全部表（按名称稳定排序）。"""
    db = _clean_identifier(database)
    return sorted(
        (t for t in TABLES.values() if t.database == db), key=lambda t: t.name
    )


def is_known_database(name: str | None) -> bool:
    return bool(name) and _clean_identifier(name or "") in DATABASES


def _clean_identifier(name: str | None) -> str:
    """去掉反引号与首尾空白，并统一小写。"""
    if not name:
        return ""
    return name.strip().strip("`").strip('"').strip().lower()


# ---------------------------------------------------------------------------
# 内置最小合成数据（兜底）
# ---------------------------------------------------------------------------

FALLBACK_NOTE = "内置最小合成数据兜底（非采集库数据）"

# 固定历史时间，保证同一语句重复执行返回完全相同的行
_BASE_TIME = datetime(2025, 1, 1, 8, 0, 0)

_FALLBACK_ROLES = ("admin", "staff", "customer", "customer", "staff", "customer")


def _fallback_users() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(1, 7):
        rows.append(
            {
                "id": i,
                "username": f"demo_user_{i:02d}",
                "email": f"demo{i:02d}@example.invalid",
                "phone": f"1990000{i:04d}",
                "password_hash": f"TEST-ONLY-HASH-{i:08x}",
                "role": _FALLBACK_ROLES[i - 1],
                "created_at": _BASE_TIME + timedelta(days=i),
            }
        )
    return rows


def _fallback_orders() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    statuses = ("paid", "pending", "cancelled", "shipped")
    for i in range(1, 13):
        rows.append(
            {
                "id": i,
                "user_id": (i - 1) % 6 + 1,
                "order_no": f"TEST-ORDER-{i:06d}",
                "amount": Decimal(f"{100 + i * 37}.{i % 100:02d}"),
                "status": statuses[(i - 1) % len(statuses)],
                "created_at": _BASE_TIME + timedelta(days=i),
            }
        )
    return rows


def _fallback_archive_orders() -> list[dict[str, Any]]:
    return [
        {
            "id": i,
            "user_id": (i - 1) % 4 + 1,
            "order_no": f"TEST-ARCHIVE-{i:06d}",
            "amount": Decimal(f"{50 + i * 11}.{i % 100:02d}"),
            "status": "paid" if i % 2 else "cancelled",
            "created_at": _BASE_TIME - timedelta(days=365 + i),
        }
        for i in range(1, 5)
    ]


def _fallback_config() -> list[dict[str, Any]]:
    """契约规定的 8 条固定键；值全部不可用。"""
    fixed = [
        ("db.master.host", "10.255.255.1:3306", "伪造配置：文档化不可路由地址"),
        ("db.master.user", "app_reader", "伪造配置：虚构数据库账号"),
        ("db.master.password", "TEST-ONLY-PASSWORD-PLACEHOLDER", "伪造配置：占位口令，不可用"),
        ("payment.api_key", "TEST-ONLY-APIKEY-0000000000", "伪造配置：占位密钥，不可用"),
        ("payment.endpoint", "https://pay.example.invalid/api", "伪造配置：保留域名，无法解析"),
        ("mail.smtp.host", "127.0.0.1:1025", "伪造配置：本机无效端口"),
        ("mail.smtp.password", "TEST-ONLY-SMTP-PLACEHOLDER", "伪造配置：占位口令，不可用"),
        ("feature.debug_mode", "true", "伪造配置：无关紧要的开关"),
    ]
    return [
        {"config_key": key, "config_value": value, "description": desc}
        for key, value, desc in fixed
    ]


_FALLBACK_ROWS: dict[tuple[str, str], list[dict[str, Any]]] = {
    (SHOP_DATABASE, "users"): _fallback_users(),
    (SHOP_DATABASE, "orders"): _fallback_orders(),
    (SHOP_DATABASE, "config"): _fallback_config(),
    (ARCHIVE_DATABASE, "orders_2025"): _fallback_archive_orders(),
}

# ---------------------------------------------------------------------------
# 物理诱饵表读取 + 进程内缓存
# ---------------------------------------------------------------------------

_catalog: dict[tuple[str, str], list[dict[str, Any]]] = {}
_fallback_tables: set[tuple[str, str]] = set()
_loaded = False
_load_lock = asyncio.Lock()


def is_loaded() -> bool:
    """缓存是否已加载（供会话层决定是否需要打开只读会话）。"""
    return _loaded


def is_fallback(table_key: tuple[str, str]) -> bool:
    """该投影表当前是否使用内置合成数据兜底（运行日志/返回值标注用）。"""
    return table_key in _fallback_tables


def _role_for(user_id: int) -> str:
    """按固定规则为物理 `fake_users` 派生对外 `role` 列（确定性）。"""
    if user_id % 10 == 1:
        return "admin"
    if user_id % 10 in (2, 3, 4):
        return "staff"
    return "customer"


async def _read_physical(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """从采集库三张 `fake_*` 物理表读取诱饵数据（只读，不做任何写操作）。"""
    from app.models.fake_models import FakeConfig, FakeOrder, FakeUser

    users = (await db.execute(select(FakeUser).order_by(FakeUser.id))).scalars().all()
    orders = (
        await db.execute(select(FakeOrder).order_by(FakeOrder.order_id))
    ).scalars().all()
    configs = (
        await db.execute(select(FakeConfig).order_by(FakeConfig.config_key))
    ).scalars().all()

    user_rows = [
        {
            "id": int(u.id),
            "username": u.username,
            "email": u.email,
            "phone": u.phone,
            "password_hash": u.password_hash,
            "role": _role_for(int(u.id)),
            "created_at": u.created_at,
        }
        for u in users
    ]
    order_rows = [
        {
            "id": int(o.order_id),
            "user_id": int(o.user_id),
            "order_no": o.order_no,
            "amount": o.amount,
            "status": o.order_status,
            "created_at": o.created_at,
        }
        for o in orders
    ]
    config_rows = [
        {
            "config_key": c.config_key,
            "config_value": c.config_value,
            "description": c.description or "伪造配置项",
        }
        for c in configs
    ]
    return {"users": user_rows, "orders": order_rows, "config": config_rows}


async def load_fake_schema(
    db: AsyncSession | None, *, force: bool = False
) -> None:
    """加载伪造表数据到进程内缓存。

    - 优先用传入的只读/读写会话读取 `fake_users`/`fake_orders`/`fake_config`；
    - 任一张表无数据或读取失败时，使用内置最小合成数据兜底，并写运行日志标注；
    - 已加载则直接返回（`force=True` 强制重载）。

    `db` 允许为 ``None``：此时直接使用内置合成数据（数据库不可达时的降级路径）。
    """
    global _catalog, _fallback_tables, _loaded
    async with _load_lock:
        if _loaded and not force:
            return

        physical: dict[str, list[dict[str, Any]]] = {}
        if db is not None:
            try:
                physical = await _read_physical(db)
            except Exception:  # noqa: BLE001 - 读取失败必须降级而非影响协议响应
                logger.exception("读取 fake_* 物理表失败，改用内置最小合成数据兜底")

        catalog: dict[tuple[str, str], list[dict[str, Any]]] = {}
        fallback: set[tuple[str, str]] = set()
        physical_name = {
            (SHOP_DATABASE, "users"): "users",
            (SHOP_DATABASE, "orders"): "orders",
            (SHOP_DATABASE, "config"): "config",
        }
        for key in TABLES:
            source = physical_name.get(key)
            rows = physical.get(source, []) if source else []
            if rows:
                catalog[key] = rows
            else:
                catalog[key] = list(_FALLBACK_ROWS.get(key, []))
                fallback.add(key)
                logger.warning(
                    "伪造表无数据，使用%s：%s.%s（行数=%s）",
                    FALLBACK_NOTE,
                    key[0],
                    key[1],
                    len(catalog[key]),
                )
        _catalog = catalog
        _fallback_tables = fallback
        _loaded = True
        logger.info(
            "伪造库表目录已加载：表数=%s 兜底表数=%s",
            len(catalog),
            len(fallback),
        )


def resolve_table(
    table: str, default_database: str | None = None
) -> tuple[str, str] | None:
    """把客户端给出的表名解析为 `(库, 表)`；支持 `库.表` 与裸表名。"""
    raw = _clean_identifier(table)
    if not raw:
        return None
    if "." in raw:
        db, _, name = raw.partition(".")
        key = (_clean_identifier(db), _clean_identifier(name))
        return key if key in TABLES else None
    db = _clean_identifier(default_database) if default_database else ""
    if db and (db, raw) in TABLES:
        return (db, raw)
    # 默认库未命中时回退到主库（客户端默认库可能仍是空/未知）
    if (PRIMARY_DATABASE, raw) in TABLES:
        return (PRIMARY_DATABASE, raw)
    for key in TABLES:
        if key[1] == raw:
            return key
    return None


def row_count(table_key: tuple[str, str]) -> int:
    """伪表当前行数（已加载则为真实缓存行数，未加载为 0）。"""
    return len(_catalog.get(table_key, []))


def _project(
    rows: list[dict[str, Any]], columns: Sequence[str] | None
) -> list[tuple[Any, ...]]:
    """按请求列投影；``columns`` 为空/``*`` 表示全部列。"""
    if not columns or list(columns) == ["*"]:
        return [tuple(row.get(name) for name in row.keys()) for row in rows]
    lowered = {name.lower(): name for name in rows[0].keys()} if rows else {}
    resolved: list[str] = []
    for requested in columns:
        key = requested.lower()
        if key in lowered:
            resolved.append(lowered[key])
        else:
            # 未知列由调用方（会话层）先行判定；此处保持列数一致以免协议错位
            resolved.append(requested)
    return [tuple(row.get(name) for name in resolved) for row in rows]


async def fetch_rows(
    db: AsyncSession | None,
    table: str,
    columns: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[tuple[Any, ...]]:
    """读取伪造表行（按请求列投影并按 ``limit`` 截断）。

    - `table` 支持 ``users`` 或 ``honeypot_shop.users``；
    - 未加载缓存时用 `db` 加载；`db` 为 None 时使用内置合成数据；
    - 未知表抛 ``KeyError``（由会话层转为 MySQL 1146）。
    """
    if not _loaded:
        await load_fake_schema(db)
    key = resolve_table(table)
    if key is None:
        raise KeyError(f"未知伪造表：{table}")
    rows = list(_catalog.get(key, []))
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return _project(rows, columns)


def all_rows(table_key: tuple[str, str]) -> list[Mapping[str, Any]]:
    """返回某伪表的完整行（information_schema 统计/过滤用，进程内缓存）。"""
    return list(_catalog.get(table_key, []))


def table_for_key(table_key: tuple[str, str]) -> Table | None:
    return TABLES.get(table_key)


def iter_table_keys() -> Iterable[tuple[str, str]]:
    return TABLES.keys()
