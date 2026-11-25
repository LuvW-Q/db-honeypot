"""演示数据重置 CLI：`python -m m1_transaction_integration.cli.reset_demo --yes`。

行为（data-model 8.6）：

- 未显式传入 `--yes` 时必须交互确认，避免误删演示数据；
- 调用 `m1_transaction_integration.services.reset.reset_demo_data` 单事务按外键顺序清空观测数据；
- 保留检测规则与三张诱饵表；
- 打印每张表删除行数（JSON）。

注意：重置不会重建演示事件；需要重新演示时再运行模拟器或
`python -m m2_decoy_capture.cli.gen_demo_data` 生成合成数据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from m1_transaction_integration.services.reset import reset_demo_data
from shared.db.session import get_rw_engine, get_rw_factory


async def run_reset(*, operator: str = "cli") -> dict[str, int]:
    """执行重置并返回每表删除行数。"""
    factory = get_rw_factory()
    async with factory() as db:
        counts = await reset_demo_data(db, operator=operator)
    await get_rw_engine().dispose()
    return counts


def _confirm() -> bool:
    """交互式确认；非交互环境直接视为拒绝。"""
    if not sys.stdin.isatty():
        print("未使用 --yes 且当前非交互环境，已取消重置。", file=sys.stderr)
        return False
    try:
        answer = input("确认重置演示数据（保留规则与诱饵种子）？输入 yes 继续：").strip().lower()
    except EOFError:
        return False
    return answer == "yes"


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m m1_transaction_integration.cli.reset_demo",
        description="按外键顺序清除观测数据（保留规则与诱饵种子）",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过交互确认，直接执行重置（自动化/演示脚本使用）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.yes and not _confirm():
        print("已取消重置。", file=sys.stderr)
        return 1

    try:
        counts = asyncio.run(run_reset())
    except Exception as exc:  # noqa: BLE001 - CLI 需要明确失败信息
        print(f"演示数据重置失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
