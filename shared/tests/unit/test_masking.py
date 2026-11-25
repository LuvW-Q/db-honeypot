"""脱敏工具单元测试：用户名与敏感值脱敏。"""

from __future__ import annotations

import pytest

from shared.utils.masking import mask_secret, mask_username, safe_display


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", ""),
        ("a", "a"),
        ("ab", "a*"),
        ("abcd", "a***"),
        ("abcde", "ab*de"),
        ("attacker01", "at******01"),
        ("x" * 20, "xx" + "*" * 16 + "xx"),
    ],
)
def test_mask_username(value, expected):
    """用户名保留首尾、中间打码；短用户名按位打码。"""
    assert mask_username(value) == expected


def test_mask_username_never_returns_full_value_for_long_names():
    """长度 > 4 的用户名必须出现掩码字符。"""
    masked = mask_username("very_long_username")
    assert masked is not None
    assert "*" in masked
    assert masked != "very_long_username"
    assert masked.startswith("ve")
    assert masked.endswith("me")


@pytest.mark.parametrize(
    ("value", "visible", "expected"),
    [
        (None, 4, None),
        ("", 4, ""),
        ("abc", 4, "***"),
        ("abcd", 4, "****"),
        ("TestOnly-Decoy-01", 4, "*" * 13 + "y-01"),
    ],
)
def test_mask_secret(value, visible, expected):
    """敏感值只保留末尾可见字符。"""
    assert mask_secret(value, visible) == expected


def test_mask_secret_with_zero_visible_should_mask_everything():
    """visible=0 时应全部打码（不得泄露任何明文字符）。"""
    assert mask_secret("secret", 0) == "******"


def test_mask_secret_output_never_contains_full_value():
    """脱敏结果不得包含完整敏感值。"""
    secret = "TestOnly-Migrate-2026"
    masked = mask_secret(secret)
    assert masked is not None
    assert masked != secret
    assert masked.startswith("*")
    assert len(masked) == len(secret)


def test_safe_display_truncates_long_text():
    """展示截断保留 max_len 内长度并追加省略号。"""
    value = "x" * 250
    shown = safe_display(value, 200)
    assert shown is not None
    assert len(shown) == 200
    assert shown.endswith("...")
    assert safe_display(value, 1000) == value
    assert safe_display(None) is None


def test_safe_display_boundary_length():
    """恰好等于上限时不追加省略号。"""
    value = "y" * 50
    assert safe_display(value, 50) == value
    assert safe_display("y" * 51, 50) == "y" * 47 + "..."
