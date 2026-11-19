"""数据库会话管理：读写、只读与迁移三类引擎。

- 应用读写使用 `honeypot_app_rw`（无 DDL）
- 控制台查询使用 `honeypot_app_ro`（仅 SELECT）
- 迁移使用 `honeypot_migrate`（唯一允许 DDL 的账号）
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger(__name__)

# 引擎惰性创建，避免导入期就连接数据库（便于测试与 CLI）
_rw_engine: AsyncEngine | None = None
_ro_engine: AsyncEngine | None = None
_migrate_engine: AsyncEngine | None = None

_rw_factory: async_sessionmaker[AsyncSession] | None = None
_ro_factory: async_sessionmaker[AsyncSession] | None = None
_migrate_factory: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs() -> dict:
    return {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": 5,
        "max_overflow": 10,
        "echo": False,
    }


def get_rw_engine() -> AsyncEngine:
    global _rw_engine
    if _rw_engine is None:
        _rw_engine = create_async_engine(settings.database_url, **_engine_kwargs())
    return _rw_engine


def get_ro_engine() -> AsyncEngine:
    global _ro_engine
    if _ro_engine is None:
        _ro_engine = create_async_engine(settings.readonly_database_url, **_engine_kwargs())
    return _ro_engine


def get_migrate_engine() -> AsyncEngine:
    global _migrate_engine
    if _migrate_engine is None:
        _migrate_engine = create_async_engine(settings.migrate_database_url, **_engine_kwargs())
    return _migrate_engine


def get_rw_factory() -> async_sessionmaker[AsyncSession]:
    global _rw_factory
    if _rw_factory is None:
        _rw_factory = async_sessionmaker(
            get_rw_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _rw_factory


def get_ro_factory() -> async_sessionmaker[AsyncSession]:
    global _ro_factory
    if _ro_factory is None:
        _ro_factory = async_sessionmaker(
            get_ro_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _ro_factory


def get_migrate_factory() -> async_sessionmaker[AsyncSession]:
    global _migrate_factory
    if _migrate_factory is None:
        _migrate_factory = async_sessionmaker(
            get_migrate_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _migrate_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：业务读写会话（自动提交/回滚由调用方事务控制）。"""
    async with get_rw_factory()() as session:
        yield session


async def get_ro_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：只读会话。"""
    async with get_ro_factory()() as session:
        yield session


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """显式事务上下文；异常时回滚。"""
    async with session.begin():
        yield session


async def retry_on_deadlock(operation, *, retries: int = 3, base_delay: float = 0.05):
    """对死锁（1213）与锁等待超时（1205）做有限重试，退避 50/100/200ms。

    参数 `operation` 为无参协程函数；重试次数与退避符合 data-model.md 8.5。
    """
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001 - 需要识别 MySQL 错误码
            code = getattr(exc, "args", [None])[0]
            if code not in (1205, 1213):
                raise
            last_error = exc
            delay = base_delay * (2**attempt)
            logger.warning("数据库锁冲突，第 %s 次重试，%ss 后继续：%s", attempt + 1, delay, exc)
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


async def ping(engine: AsyncEngine | None = None) -> bool:
    """健康检查：执行 SELECT 1。"""
    target = engine or get_rw_engine()
    try:
        async with target.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        logger.exception("数据库健康检查失败")
        return False
