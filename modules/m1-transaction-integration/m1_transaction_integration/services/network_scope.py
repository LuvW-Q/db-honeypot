"""来源地址的展示派生：网络位置（`network_scope`）与标签。

契约 `contracts/api-extensions.md` §1.3：

- `loopback`：`127.0.0.0/8`、`::1`；
- `reserved`：RFC5737 TEST-NET（`192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24`）
  与文档保留段（`2001:db8::/32`）；
- `private`：RFC1918（`10/8`、`172.16/12`、`192.168/16`）与 IPv6 ULA（`fc00::/7`）；
- `public`：其余地址。

判定顺序固定为 loopback → reserved → private → public：Python 的
`ipaddress.IPv4Address.is_private` 会把 TEST-NET 文档段也算作 private，因此不能直接
用它，必须显式按契约给的网段判定。派生值不落库、不新增表，纯函数实现于 M1。

本模块同时提供 `split_labels`：把画像视图的 `GROUP_CONCAT` 字符串（逗号分隔）拆成
去空、去重、顺序稳定的列表，供列表项 `intent_labels`/`triggered_rule_codes` 使用。
"""

from __future__ import annotations

import ipaddress
from typing import Final

#: 契约 §1.3 的四类取值
NETWORK_SCOPE_PRIVATE: Final = "private"
NETWORK_SCOPE_LOOPBACK: Final = "loopback"
NETWORK_SCOPE_RESERVED: Final = "reserved"
NETWORK_SCOPE_PUBLIC: Final = "public"

#: 网络位置 → 页面展示标签（契约 §1.3）
NETWORK_SCOPE_LABELS: Final[dict[str, str]] = {
    NETWORK_SCOPE_PRIVATE: "内网",
    NETWORK_SCOPE_LOOPBACK: "回环",
    NETWORK_SCOPE_RESERVED: "文档保留",
    NETWORK_SCOPE_PUBLIC: "公网",
}

#: 判定网段（顺序即判定优先级）
_LOOPBACK_NETWORKS: Final = tuple(
    ipaddress.ip_network(network) for network in ("127.0.0.0/8", "::1/128")
)
_RESERVED_NETWORKS: Final = tuple(
    ipaddress.ip_network(network)
    for network in (
        "192.0.2.0/24",  # RFC5737 TEST-NET-1
        "198.51.100.0/24",  # RFC5737 TEST-NET-2
        "203.0.113.0/24",  # RFC5737 TEST-NET-3
        "2001:db8::/32",  # RFC3849 文档保留段
    )
)
_PRIVATE_NETWORKS: Final = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",  # RFC1918
        "172.16.0.0/12",  # RFC1918
        "192.168.0.0/16",  # RFC1918
        "fc00::/7",  # RFC4193 ULA
    )
)


def _in_networks(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    """判断地址是否落在任一网段（跨 IPv4/IPv6 版本时视为不匹配）。"""
    return any(address.version == network.version and address in network for network in networks)


def derive_network_scope(source_ip: str | None) -> str:
    """由来源地址派生网络位置；无法解析的地址归为 `public`（防御性兜底）。

    地址列由数据库约束为 IPv4/IPv6 文本规范形式，正常路径不会触发兜底分支。
    """
    if not source_ip:
        return NETWORK_SCOPE_PUBLIC
    try:
        address = ipaddress.ip_address(str(source_ip).strip())
    except ValueError:
        return NETWORK_SCOPE_PUBLIC
    if _in_networks(address, _LOOPBACK_NETWORKS):
        return NETWORK_SCOPE_LOOPBACK
    if _in_networks(address, _RESERVED_NETWORKS):
        return NETWORK_SCOPE_RESERVED
    if _in_networks(address, _PRIVATE_NETWORKS):
        return NETWORK_SCOPE_PRIVATE
    return NETWORK_SCOPE_PUBLIC


def network_scope_label(scope: str) -> str:
    """网络位置 → 中文标签；未知取值按公网展示（不抛异常）。"""
    return NETWORK_SCOPE_LABELS.get(scope, NETWORK_SCOPE_LABELS[NETWORK_SCOPE_PUBLIC])


def split_labels(raw: str | None) -> list[str]:
    """拆分 `GROUP_CONCAT` 字符串：去空、去重、保留首次出现顺序。"""
    if not raw:
        return []
    result: list[str] = []
    for item in str(raw).split(","):
        value = item.strip()
        if value and value not in result:
            result.append(value)
    return result


def scope_fields(source_ip: str | None) -> dict[str, str]:
    """一次性返回 `{network_scope, network_scope_label}`，供路由/仓储组装响应。"""
    scope = derive_network_scope(source_ip)
    return {"network_scope": scope, "network_scope_label": network_scope_label(scope)}


__all__ = [
    "NETWORK_SCOPE_LABELS",
    "NETWORK_SCOPE_LOOPBACK",
    "NETWORK_SCOPE_PRIVATE",
    "NETWORK_SCOPE_PUBLIC",
    "NETWORK_SCOPE_RESERVED",
    "derive_network_scope",
    "network_scope_label",
    "scope_fields",
    "split_labels",
]
