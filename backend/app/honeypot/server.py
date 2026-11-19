"""诱饵 MySQL 服务入口（mysql-mimic 3.0.5）。

- 默认只监听回环地址 `127.0.0.1:3307`（安全边界，`contracts/honeypot-protocol.md` 第 8 章）；
- 非回环地址一律拒绝启动（本版无 `allow_non_loopback` 开关，宁可失败不带病运行）；
- 端口被占用时输出明确错误并以非 0 退出码退出（FR-074）；
- 支持 SIGINT/SIGTERM 优雅关闭；
- 可用 `python -m app.honeypot.server` 直接运行。
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from mysql_mimic import MysqlServer

from app.config import settings
from app.honeypot.auth import DecoyIdentityProvider
from app.honeypot.emitter import EventEmitter
from app.honeypot.session import HoneypotSession

logger = logging.getLogger(__name__)

# 允许监听的本地回环地址（安全边界：诱饵服务不暴露到公网）
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _validate_host(host: str) -> None:
    """校验监听地址；非回环地址拒绝启动。"""
    if host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            f"拒绝监听非回环地址 {host!r}：本版诱饵服务只允许绑定 127.0.0.1/::1/localhost"
        )


def create_server() -> MysqlServer:
    """创建 MySQL 协议模拟服务器（共享一个事件发射器）。"""
    emitter = EventEmitter()

    def session_factory() -> HoneypotSession:
        # 每个 TCP 连接一个会话对象；连接结束时由 mysql-mimic 调用 close()
        return HoneypotSession(emitter=emitter)

    return MysqlServer(
        session_factory=session_factory,
        identity_provider=DecoyIdentityProvider(),
    )


async def start() -> MysqlServer:
    """启动监听并返回服务器实例（端口占用等错误直接抛出）。"""
    host = settings.honeypot_host
    port = settings.honeypot_port
    _validate_host(host)

    server = create_server()
    try:
        await server.start_server(host=host, port=port)
    except OSError as exc:
        logger.error(
            "诱饵服务启动失败：无法监听 %s:%s（端口可能已被占用）：%s", host, port, exc
        )
        raise

    logger.info(
        "诱饵服务已启动：host=%s port=%s service=%s 账号数=%s 允许客户端网段=%s",
        host,
        port,
        settings.honeypot_service_name,
        len(settings.decoy_accounts),
        ",".join(settings.allowed_cidrs) or "未配置",
    )
    return server


async def _run() -> int:
    """运行服务直到收到停止信号，然后优雅关闭。"""
    server = await start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - 平台差异
            logger.debug("当前事件循环不支持注册信号：%s", sig)

    serve_task = asyncio.create_task(server.serve_forever())
    try:
        await stop_event.wait()
    finally:
        logger.info("收到停止信号，正在优雅关闭诱饵服务…")
        server.close()
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass
        await server.wait_closed()
        logger.info("诱饵服务已关闭")
    return 0


def main() -> None:
    """命令行入口：初始化日志后运行服务；失败以非 0 退出码退出。"""
    try:
        from app.logging import configure_logging

        configure_logging()
    except Exception:  # noqa: BLE001 - 日志初始化失败不阻断服务（退回标准 logging）
        logging.basicConfig(level=logging.INFO)

    try:
        exit_code = asyncio.run(_run())
    except OSError:
        # 端口占用/绑定失败：明确非 0 退出
        sys.exit(1)
    except RuntimeError as exc:
        logger.error("诱饵服务拒绝启动：%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:  # pragma: no cover - 交互式终端
        logger.info("收到键盘中断，退出")
        sys.exit(0)
    except Exception:  # noqa: BLE001
        logger.exception("诱饵服务异常退出")
        sys.exit(1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
