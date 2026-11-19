"""诱饵认证：基于 `settings.decoy_accounts` 的 `mysql_native_password` 身份校验。

对齐 `contracts/honeypot-protocol.md` 第 2 章与 `events.md` 3.2：
- 只支持 `mysql_native_password`（本版刻意收敛的协议子集）；
- 服务端口令只在内存派生 `SHA1(SHA1(password))` 摘要，**不落库、不写日志**；
- 客户端响应用常量时间比较（`hmac.compare_digest`）；
- 每次认证尝试记录：用户名、成功/失败、`credential_test_id = sha256(user:pass)[:12]`。

说明（重要）：native password 握手只传客户端算好的 scramble，服务端拿不到明文口令。
因此失败尝试的 `credential_test_id` 对已知诱饵账号按"用户名 + 配置口令"计算，
未知账号按"用户名 + 未知标记"计算；它只用于统计"凭据组合"，不含任何可用口令。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha1

from mysql_mimic import utils
from mysql_mimic.auth import (
    AuthPlugin,
    Forbidden,
    IdentityProvider,
    NativePasswordAuthPlugin,
    NoLoginAuthPlugin,
    Success,
    User,
)

from app.config import settings

logger = logging.getLogger(__name__)

MAX_USERNAME_LENGTH = 128
_KNOWN_PASSWORD_PLACEHOLDER = "*UNKNOWN*"


@dataclass
class AuthAttempt:
    """一次认证尝试（仅描述结果，不含口令）。"""

    username: str
    success: bool
    credential_test_id: str


# 每连接一份认证尝试列表：由 HoneypotSession.__init__ 初始化，认证插件写入，
# 会话 init 时 drain 并转换为标准 auth 事件（同一事件循环任务内可见）。
_auth_attempts: ContextVar[list[AuthAttempt] | None] = ContextVar(
    "honeypot_auth_attempts", default=None
)
# 无会话上下文时的兜底（理论上不会发生；用于诊断认证插件被独立调用的情况）
_orphan_attempts: list[AuthAttempt] = []


def begin_auth_attempts() -> list[AuthAttempt]:
    """为当前连接创建认证尝试收集器（在会话构造时调用）。"""
    attempts: list[AuthAttempt] = []
    _auth_attempts.set(attempts)
    return attempts


def drain_auth_attempts() -> list[AuthAttempt]:
    """取出并清空当前连接的认证尝试列表。"""
    attempts = _auth_attempts.get() or []
    _auth_attempts.set(None)
    return list(attempts)


def build_credential_test_id(username: str, password_material: str) -> str:
    """合成凭据标识：``sha256("用户:口令材料")[:12]`` 大写（兼容 `^[A-Z0-9_-]+$`）。"""
    digest = hashlib.sha256(
        f"{username}:{password_material}".encode()
    ).hexdigest()
    return digest[:12].upper()


def record_auth_attempt(
    *, username: str, success: bool, password_material: str | None
) -> AuthAttempt:
    """记录一次认证尝试（口令材料只用于生成摘要，不做任何持久化）。"""
    safe_username = (username or "")[:MAX_USERNAME_LENGTH]
    material = password_material or _KNOWN_PASSWORD_PLACEHOLDER
    attempt = AuthAttempt(
        username=safe_username,
        success=bool(success),
        credential_test_id=build_credential_test_id(safe_username, material),
    )
    sink = _auth_attempts.get()
    if sink is None:
        logger.info(
            "认证尝试（无会话上下文）：username=%s success=%s", safe_username, success
        )
        _orphan_attempts.append(attempt)
        # 只保留最近 100 条诊断记录，避免无界增长
        del _orphan_attempts[:-100]
        return attempt
    sink.append(attempt)
    return attempt


class DecoyNativePasswordAuthPlugin(NativePasswordAuthPlugin):
    """`mysql_native_password` 插件：校验诱饵账号并记录认证尝试。

    与上游实现相同的握手流程，差别在于：
    - 使用 `hmac.compare_digest` 做常量时间比较；
    - 每次判定后记录一次认证尝试（不回显、不记录口令）。
    """

    name = "mysql_native_password"
    client_plugin_name = "mysql_native_password"

    def __init__(self, provider: DecoyIdentityProvider) -> None:
        self.provider = provider

    def verify_scramble(
        self, auth_string: str | None, scramble: bytes, nonce: bytes
    ) -> bool:
        """校验客户端 native password 响应（常量时间比较）。"""
        try:
            stage2 = bytes.fromhex(auth_string or "")
            expected = utils.xor(scramble, sha1(nonce + stage2).digest())
            return hmac.compare_digest(sha1(expected).digest(), stage2)
        except Exception:  # noqa: BLE001 - 畸形响应一律判失败，不抛异常
            logger.info("认证响应格式非法，判定为失败")
            return False

    async def auth(self, auth_info=None):  # type: ignore[override]
        if (
            auth_info
            and auth_info.handshake_plugin_name == self.name
            and auth_info.handshake_auth_data
        ):
            # mysql_native_password 可复用初始握手的 nonce（省一次往返）
            nonce = auth_info.handshake_auth_data.rstrip(b"\x00")
        else:
            nonce = utils.nonce(20)
            # 部分客户端期望 nonce 以 \x00 结尾
            auth_info = yield nonce + b"\x00"

        user: User = auth_info.user
        matched = self.password_matches(
            user=user, scramble=auth_info.data, nonce=nonce
        )
        record_auth_attempt(
            username=auth_info.username,
            success=matched,
            password_material=self.provider.password_for(auth_info.username),
        )
        if matched:
            logger.info("诱饵账号认证成功：username=%s", auth_info.username)
            yield Success(user.name)
        else:
            # 不记录口令、口令长度或哈希，只记录一次失败尝试
            logger.info("诱饵账号认证失败：username=%s", auth_info.username)
            yield Forbidden()


class DecoyIdentityProvider(IdentityProvider):
    """用 `settings.decoy_accounts` 校验用户名/口令的身份提供者。

    - 已知账号：返回带 `SHA1(SHA1(password))` 摘要的 `User`，由 native password 校验；
    - 未知账号/空用户名：返回固定伪摘要，使认证必然失败并返回 1045
      （避免暴露"账号是否存在"的差异）。
    """

    def __init__(self, accounts: dict[str, str] | None = None) -> None:
        self._accounts: dict[str, str] = dict(
            accounts if accounts is not None else settings.decoy_accounts
        )
        self._plugin = DecoyNativePasswordAuthPlugin(self)
        self._no_login_plugin = NoLoginAuthPlugin()
        # 未知账号的固定伪摘要（不可用于登录，仅用于走完 native password 校验路径）
        self._unknown_auth_string = NativePasswordAuthPlugin.create_auth_string(
            "*TEST-ONLY-UNKNOWN-ACCOUNT*"
        )
        if not self._accounts:
            logger.warning(
                "未配置诱饵账号（settings.decoy_accounts 为空），所有认证都将失败"
            )

    # -- IdentityProvider 接口 --
    def get_plugins(self) -> list[AuthPlugin]:
        return [self._plugin, self._no_login_plugin]

    def get_default_plugin(self) -> AuthPlugin:
        return self._plugin

    async def get_user(self, username: str) -> User:
        name = (username or "")[:MAX_USERNAME_LENGTH]
        password = self._accounts.get(name)
        if password:
            return User(
                name=name,
                auth_string=NativePasswordAuthPlugin.create_auth_string(password),
                auth_plugin=self._plugin.name,
            )
        return User(
            name=name,
            auth_string=self._unknown_auth_string,
            auth_plugin=self._plugin.name,
        )

    # -- 辅助 --
    def password_for(self, username: str | None) -> str | None:
        """返回某诱饵账号的配置口令（仅用于派生 credential_test_id，不写日志/库）。"""
        if not username:
            return None
        return self._accounts.get(username[:MAX_USERNAME_LENGTH])

    @property
    def accounts(self) -> dict[str, str]:
        """返回账号名列表（不含口令），供启动日志打印。"""
        return {name: "****" for name in self._accounts}
