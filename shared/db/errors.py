"""MySQL 驱动错误辅助：从 SQLAlchemy 包装异常中提取 errno。"""

from __future__ import annotations


def mysql_errno(exc: BaseException) -> int | None:
    """返回 MySQL 错误码（asyncmy 错误位于 exc.orig.args[0]），无法识别时返回 None。"""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ()) if orig is not None else ()
    if args and isinstance(args[0], int):
        return args[0]
    return None


__all__ = ["mysql_errno"]
