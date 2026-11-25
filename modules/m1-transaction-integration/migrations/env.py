"""Alembic 运行时环境：加载配置、创建异步引擎并执行迁移。

设计要点（对应 data-model.md 12.2 / 2.4）：
- 连接串从仓库根目录 `.env` 的 `MIGRATE_DATABASE_URL` 读取，禁止写死在 ini；
- 使用 SQLAlchemy 2.x async engine（asyncmy 驱动）；
- `target_metadata = Base.metadata`，并导入 `shared.models` 注册全部 11 张表；
- 支持离线（`--sql`）与在线两种模式，二者共用同一份迁移脚本；
- `compare_type=True` 让 autogenerate 能识别列类型漂移（结果仍需人工评审）；
- 会话时区固定 `+00:00`、隔离级别固定 `READ-COMMITTED`，与业务连接口径一致；
- 视图由 0002 迁移管理，autogenerate 时排除，避免被当作表处理。
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import shared.models  # noqa: F401  # 副作用导入：注册 ORM 模型

# 先导入模型再读取 metadata：`import shared.models` 会注册全部表到 Base.metadata
from shared.db.base import Base

# ---------------------------------------------------------------------------
# 配置与仓库根 .env
# ---------------------------------------------------------------------------
config = context.config

# modules/m1-transaction-integration/migrations/env.py -> parents[3] 即仓库根目录
REPO_ROOT = Path(__file__).resolve().parents[3]

# override=False：真实环境变量优先于 .env，便于 CI/容器注入
load_dotenv(REPO_ROOT / ".env", override=False)

# 初始化日志（alembic.ini 中的 [loggers]/[handlers] 段）
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

DATABASE_URL = os.environ.get("MIGRATE_DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "缺少 MIGRATE_DATABASE_URL：请在仓库根 .env 中配置迁移账号连接串"
        "（形如 mysql+asyncmy://honeypot_migrate:...@127.0.0.1:3306/honeypot_dev）"
    )

# 四个分析视图由 0002_analysis_views 迁移管理，autogenerate 时排除
VIEW_NAMES = frozenset(
    {
        "v_session_risk_summary",
        "v_attacker_profile_summary",
        "v_daily_attack_trend",
        "v_rule_effectiveness",
    }
)

target_metadata = Base.metadata

# MySQL 反射 VIRTUAL 生成列时会丢失 NOT NULL 与 COMMENT 信息（expression 文本被
# 原样塞进 computed.sqltext），会让 autogenerate 对 risk_level 产生假差异；
# 生成列结构由 0001 迁移唯一管理，这里按列名排除比较（不影响真实表结构）。
REFLECTION_SKIP_COLUMNS = frozenset({"risk_level"})


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """autogenerate 过滤：排除视图、版本表与反射受限的生成列。"""
    if type_ == "table" and name in VIEW_NAMES:
        return False
    if type_ == "table" and name == "alembic_version":
        return False
    if type_ == "column" and name in REFLECTION_SKIP_COLUMNS:
        return False
    return True


# ---------------------------------------------------------------------------
# 离线模式：生成 SQL 脚本，不连接数据库
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """离线模式：`alembic upgrade head --sql` 时按字面量渲染 DDL。"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# 在线模式：异步 engine + run_sync
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    """在同步 Connection 回调中执行迁移（由 run_sync 调用）。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """创建 async engine 并在其连接上执行迁移。"""
    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        # 迁移连接与业务连接统一时区/隔离级别口径（data-model 2.4、8.2）
        connect_args={
            "init_command": (
                "SET SESSION time_zone = '+00:00', "
                "SESSION transaction_isolation = 'READ-COMMITTED'"
            )
        },
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口：运行事件循环。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
