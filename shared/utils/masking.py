"""脱敏工具：控制台与导出绝不能出现完整口令或原始凭据。"""

from __future__ import annotations


def mask_username(username: str | None) -> str | None:
    """用户名脱敏：保留前 2 位与后 2 位，其余以 * 代替。"""
    if username is None:
        return None
    if len(username) <= 4:
        return username[0] + "*" * (len(username) - 1) if username else username
    return f"{username[:2]}{'*' * (len(username) - 4)}{username[-2:]}"


def mask_secret(value: str | None, visible: int = 4) -> str | None:
    """通用敏感值脱敏：只保留末尾少量字符；visible<=0 时全部掩码。"""
    if value is None:
        return None
    if visible <= 0:
        return "*" * len(value)
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


def safe_display(value: str | None, max_len: int = 200) -> str | None:
    """展示用截断，避免超长 SQL 撑爆页面。"""
    if value is None:
        return None
    return value if len(value) <= max_len else value[: max_len - 3] + "..."
