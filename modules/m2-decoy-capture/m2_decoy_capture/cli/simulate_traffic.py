"""授权模拟器 CLI：``python -m m2_decoy_capture.cli.simulate_traffic --target 127.0.0.1:3307 --rounds 3``。

用途（quickstart V23 / tasks T032/T109）：用真实 MySQL 客户端驱动（``asyncmy``）连接
**本机诱饵服务**，执行固定查询与写操作拒绝序列，产生 connect/auth/query/disconnect
事件，供演示与冒烟验证。

安全边界（硬性要求）：

1. 目标地址必须是回环地址（127.0.0.0/8、::1、localhost）或 ``.env`` 中
   ``HONEYPOT_ALLOWED_CLIENT_CIDRS`` 声明的隔离网段；否则拒绝执行并以退出码 3 退出。
2. 口令只来自 ``.env`` 的诱饵账号（``HONEYPOT_ACCOUNTS``，默认 ``demo_reader``），
   不硬编码、不打印；本脚本只连接诱饵端口，不连接任何真实业务库。
3. 写操作（UPDATE/DELETE/INSERT/DROP/TRUNCATE）预期被诱饵层以 1142 拒绝；
   脚本不重试、不绕过，仅把拒绝结果记录下来。

客户端插件说明：``asyncmy`` 0.2.18 的 ``connect()`` 没有 ``auth_plugin`` 关键字参数，
但诱饵服务在握手包中通告的默认插件就是 ``mysql_native_password``，因此真实连接会自动
使用该插件；若未来驱动支持 ``auth_plugin``，本脚本会显式传入（见 ``_connect_decoy``）。
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys
from dataclasses import dataclass
from typing import Any

import asyncmy

from shared.config import settings

# 默认目标（诱饵服务默认监听回环地址 3307，避免与真实 MySQL 冲突）
_DEFAULT_TARGET = "127.0.0.1:3307"
_DEFAULT_ROUNDS = 3
_DEFAULT_USER = "demo_reader"

# 固定语句序列：前段为元数据/查询，后段为预期被拒绝的写操作
STATEMENTS: tuple[dict[str, Any], ...] = (
    {"name": "show_databases", "sql": "SHOW DATABASES", "expect": "success"},
    {"name": "show_tables", "sql": "SHOW TABLES", "expect": "success"},
    {"name": "describe_users", "sql": "DESCRIBE users", "expect": "success"},
    {
        "name": "select_users",
        "sql": "SELECT id, username, email FROM users LIMIT 5",
        "expect": "success",
    },
    {"name": "select_orders_count", "sql": "SELECT COUNT(*) FROM orders", "expect": "success"},
    {
        "name": "update_denied",
        "sql": "UPDATE orders SET status='cancelled' WHERE id=1",
        "expect": "denied",
    },
    {"name": "delete_denied", "sql": "DELETE FROM orders WHERE id=1", "expect": "denied"},
    {
        "name": "insert_denied",
        "sql": "INSERT INTO users (username) VALUES ('demo_user_x')",
        "expect": "denied",
    },
    {"name": "drop_denied", "sql": "DROP TABLE orders", "expect": "denied"},
    {"name": "truncate_denied", "sql": "TRUNCATE TABLE orders", "expect": "denied"},
    {"name": "verify_orders_intact", "sql": "SELECT COUNT(*) FROM orders", "expect": "success"},
)


@dataclass(frozen=True)
class Target:
    """解析后的目标地址。"""

    host: str
    port: int

    @property
    def text(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


# ---------------------------------------------------------------------------
# 安全边界：目标地址授权
# ---------------------------------------------------------------------------


def parse_target(raw: str) -> Target:
    """解析 ``host:port``；非法输入抛出 ValueError。"""
    value = raw.strip()
    if not value:
        raise ValueError("--target 不能为空")
    if value.startswith("["):
        # IPv6 文本：[::1]:3307
        host, _, port_text = value[1:].partition("]:")
        if not host or not port_text:
            raise ValueError(f"无法解析目标地址 {raw!r}，应形如 127.0.0.1:3307")
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator or not host:
            raise ValueError(f"无法解析目标地址 {raw!r}，应形如 127.0.0.1:3307")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"目标端口不是整数：{port_text!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"目标端口超出范围：{port}")
    return Target(host=host.strip().lower(), port=port)


def _allowed_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """回环网段 + `.env` 中声明的允许网段。"""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("::1/128"),
    ]
    for item in settings.allowed_cidrs:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return networks


def authorize_target(target: Target) -> str | None:
    """校验目标是否在允许网段内；允许返回命中的网段文本，拒绝返回 None。

    只做地址判断，不发起 DNS 解析或网络连接，避免"检查即探测"。
    """
    host = target.host
    if host in {"localhost", "ip6-localhost"}:
        return "127.0.0.0/8"
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        # 非 IPv4/IPv6 文本视为未授权（不在本机 & 非显式 CIDR 内）
        return None
    for network in _allowed_networks():
        if address.version == network.version and address in network:
            return str(network)
    return None


# ---------------------------------------------------------------------------
# 连接与语句执行
# ---------------------------------------------------------------------------


async def _connect_decoy(target: Target, user: str, password: str):
    """连接诱饵服务；优先显式声明 mysql_native_password 插件。

    asyncmy 0.2.x 不接受 ``auth_plugin`` 关键字参数，此时回退为默认握手协商；
    诱饵服务通告的默认插件仍为 ``mysql_native_password``，行为等价。
    """
    kwargs: dict[str, Any] = {
        "host": target.host.strip("[]"),
        "port": target.port,
        "user": user,
        "password": password,
        "charset": "utf8mb4",
        "autocommit": True,
        "connect_timeout": 5,
    }
    try:
        coroutine = asyncmy.connect(**kwargs, auth_plugin="mysql_native_password")
    except TypeError:
        coroutine = asyncmy.connect(**kwargs)
    return await coroutine


async def _run_round(
    target: Target, user: str, password: str, round_no: int
) -> list[dict[str, Any]]:
    """执行一轮固定语句序列并返回逐条结果。"""
    results: list[dict[str, Any]] = []
    connection = await _connect_decoy(target, user, password)
    try:
        cursor = connection.cursor()
        try:
            for statement in STATEMENTS:
                item: dict[str, Any] = {
                    "round": round_no,
                    "name": statement["name"],
                    "sql": statement["sql"],
                    "expect": statement["expect"],
                }
                try:
                    await cursor.execute(statement["sql"])
                    rows = await cursor.fetchall()
                    item["status"] = "success"
                    item["row_count"] = len(rows or ())
                except Exception as exc:  # noqa: BLE001 - 逐条记录错误，保持连接继续
                    error_code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
                    item["status"] = "denied" if error_code == 1142 else "error"
                    item["error_code"] = error_code
                    item["error"] = str(exc.args[1] if len(exc.args) > 1 else exc)[:200]
                results.append(item)
        finally:
            await cursor.close()
    finally:
        connection.close()
    return results


def _summarize(results: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
    """汇总每轮结果：预期拒绝是否全部命中、成功语句数等。"""
    denied_expected = sum(1 for statement in STATEMENTS if statement["expect"] == "denied")
    denied_actual = sum(1 for item in results if item.get("status") == "denied")
    errors = [item for item in results if item.get("status") == "error"]
    success = sum(1 for item in results if item.get("status") == "success")
    return {
        "rounds": rounds,
        "statements_per_round": len(STATEMENTS),
        "total_statements": len(results),
        "success": success,
        "denied_expected": denied_expected * rounds,
        "denied_actual": denied_actual,
        "errors": len(errors),
        "denied_all_matched": denied_actual == denied_expected * rounds and not errors,
    }


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m m2_decoy_capture.cli.simulate_traffic",
        description="授权模拟器：仅连接本机/隔离网段内的诱饵服务，执行固定查询序列",
    )
    parser.add_argument(
        "--target",
        default=_DEFAULT_TARGET,
        help=f"诱饵服务地址 host:port（默认 {_DEFAULT_TARGET}）",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=_DEFAULT_ROUNDS,
        help=f"连接轮数（默认 {_DEFAULT_ROUNDS}），每轮建立独立会话",
    )
    parser.add_argument(
        "--user",
        default=_DEFAULT_USER,
        help=f"诱饵账号用户名（默认 {_DEFAULT_USER}，口令来自 .env 的 HONEYPOT_ACCOUNTS）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：0 成功；1 连接/执行失败；2 参数错误；3 目标未授权。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.rounds < 1 or args.rounds > 20:
        print("--rounds 必须在 1..20 之间", file=sys.stderr)
        return 2
    try:
        target = parse_target(args.target)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    matched_network = authorize_target(target)
    if matched_network is None:
        print(
            f"拒绝执行：目标 {target.text} 不在允许网段内（仅允许回环地址或 "
            f"HONEYPOT_ALLOWED_CLIENT_CIDRS={settings.honeypot_allowed_client_cidrs}）",
            file=sys.stderr,
        )
        return 3

    accounts = settings.decoy_accounts
    if args.user not in accounts:
        print(
            f"拒绝执行：账号 {args.user!r} 不在 .env 的诱饵账号列表中（{', '.join(accounts) or '空'}）",
            file=sys.stderr,
        )
        return 2

    try:
        results: list[dict[str, Any]] = []
        for round_no in range(1, args.rounds + 1):
            results.extend(
                asyncio.run(_run_round(target, args.user, accounts[args.user], round_no))
            )
    except Exception as exc:  # noqa: BLE001 - CLI 需要明确失败信息
        print(f"模拟器连接/执行失败：{exc}", file=sys.stderr)
        return 1

    summary = _summarize(results, args.rounds)
    payload = {
        "target": target.text,
        "user": args.user,
        "allowed_network": matched_network,
        "auth_plugin": "mysql_native_password",
        "auth_plugin_note": (
            "诱饵服务握手默认通告 mysql_native_password；asyncmy 0.2.18 不接受 "
            "auth_plugin 关键字参数，脚本在驱动支持时会显式传入，否则由握手协商使用同一插件"
        ),
        "rounds": args.rounds,
        "results": results,
        "summary": summary,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if summary["denied_all_matched"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
