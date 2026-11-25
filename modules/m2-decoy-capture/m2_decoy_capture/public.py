"""M2 对外门面：只暴露诱饵服务的启动/停止能力，不泄漏协议实现细节。

模块边界（`contracts/module-boundaries.md` §2）：M5 与运维 CLI 只能经本文件启动诱饵，
不得直接 import `m2_decoy_capture.server/session/emitter` 等内部模块。
"""

from __future__ import annotations

from typing import Any

__all__ = ["serve", "start"]


def serve() -> None:
    """阻塞式启动诱饵服务，直到收到 SIGINT/SIGTERM（等价 `python -m m2_decoy_capture.server`）。"""
    from m2_decoy_capture.server import main

    main()


async def start() -> Any:
    """以 async 方式启动监听并返回服务器实例（供集成测试/生命周期管理使用）。"""
    from m2_decoy_capture.server import start as _start

    return await _start()
