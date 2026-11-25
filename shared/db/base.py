"""SQLAlchemy 声明基类与统一约束命名约定。

命名约定让 Alembic 自动生成的约束名可预测，便于评审与回滚。
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 约束命名约定：ix_ 索引、uq_ 唯一、ck_ 检查、fk_ 外键、pk_ 主键
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
