"""API 依赖：数据库会话、请求编号与通用查询参数。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db, get_ro_db


async def db_session() -> AsyncSession:
    """业务读写会话依赖。"""
    async for session in get_db():
        yield session


async def ro_session() -> AsyncSession:
    """只读会话依赖（控制台查询）。"""
    async for session in get_ro_db():
        yield session


DB = Annotated[AsyncSession, Depends(db_session)]
RODB = Annotated[AsyncSession, Depends(ro_session)]

PageQuery = Annotated[int, Query(ge=1, description="页码，从 1 开始")]
PageSizeQuery = Annotated[int, Query(ge=1, le=100, description="每页条数")]
