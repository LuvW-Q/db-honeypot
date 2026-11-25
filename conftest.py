"""测试全局夹具：真实 MySQL 测试库隔离、迁移、数据清理与事件构造辅助。

设计原则（对应任务约束）：

1. **绝不使用数据库 Mock**：所有测试连接真实的 ``honeypot_test`` 库；
2. **不破坏开发库**：连接串只允许指向库名 ``honeypot_test``，否则在导入阶段直接报错；
3. **会话级准备**：清空测试库 → 执行 Alembic 迁移链 → 导入种子数据（规则 + 诱饵数据）；
4. **函数级隔离**：每个用例前后按外键顺序清理观测数据表，并把 ``detection_rules``
   恢复为 R01–R05 v1 启用基线；``fake_*`` 诱饵表与规则基线数据保留；
5. **事件循环安全**：pytest-asyncio 默认每个用例一个新事件循环，因此每个用例结束后
   释放应用全局异步引擎连接池，避免连接被跨事件循环复用。

关于账号：仓库当前只给 ``honeypot_migrate`` 授予了 ``honeypot_test`` 权限，
``honeypot_app_rw`` / ``honeypot_app_ro`` 在测试库上无授权（环境限制，非应用缺陷）。
因此测试进程把三个连接串统一指向测试库的迁移账号；接口测试依旧走真实数据库与
真实应用依赖，只是数据库账号换成有权访问测试库的迁移账号。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

# ---------------------------------------------------------------------------
# 一、先固定测试连接串，再导入 shared.*（shared.config 在导入时读取环境变量）
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT  # 兼容旧变量名：仓库根即子进程工作目录

# 子进程（alembic / seed CLI）必须显式带上各模块目录：editable 安装的 .pth
# 在部分 macOS 文件系统上会被标记 hidden 而被 site 跳过，不能作为唯一依赖。
MODULE_PATHS: tuple[str, ...] = (
    "modules/m1-transaction-integration",
    "modules/m2-decoy-capture",
    "modules/m4-rules-derived",
    "modules/m5-views-console",
)


def _resolve_test_database_url() -> str:
    """读取 ``TEST_DATABASE_URL``：优先真实环境变量，其次仓库根 `.env`。"""
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            raw = dotenv_values(env_file).get("TEST_DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "缺少 TEST_DATABASE_URL：请在仓库根 .env 配置 honeypot_test 的连接串"
        )
    return raw.strip()


TEST_DATABASE_URL = _resolve_test_database_url()
_TEST_URL = make_url(TEST_DATABASE_URL)
TEST_DATABASE_NAME = _TEST_URL.database or ""

# 安全哨兵：测试绝不允许连到 dev/demo 库
if TEST_DATABASE_NAME != "honeypot_test":
    raise RuntimeError(
        f"测试库必须为 honeypot_test，当前为 {TEST_DATABASE_NAME!r}；"
        "拒绝在非测试库上执行清空/迁移操作"
    )

# 应用读写/只读账号未获测试库授权，统一改用迁移账号访问 honeypot_test
os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["MIGRATE_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["READONLY_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["AI_ENABLED"] = "false"

# shared.config 使用 lru_cache 单例；确保导入前环境变量已就绪（防御性清理）
if "shared.config" in sys.modules:  # pragma: no cover - 正常测试收集顺序下不会触发
    from shared.config import get_settings

    get_settings.cache_clear()

import asyncmy  # noqa: E402  # 在环境变量的安全设定之后导入
from sqlalchemy import text  # noqa: E402

from tests.support import EXPECTED_TABLES, EXPECTED_VIEWS  # noqa: E402

# 业务表清理顺序：严格遵守 RESTRICT 外键依赖（子表在前、父表在后）
DELETE_ORDER: tuple[str, ...] = (
    "alerts",
    "rule_hits",
    "attack_log",
    "attacker_intent",
    "attacker_profile",
    "sessions",
    # audit_log 仅追加、无外键；用例内会写入审计（告警已读/规则变更），
    # 为保证用例独立性一并清理（它不是任务要求保留的基线数据）
    "audit_log",
)

# 规则种子 upsert（与迁移 0004 / m2_decoy_capture.cli.seed_decoy 的 R01–R05 v1 定义一致）
_RULE_UPSERT_SQL = text(
    """
    INSERT INTO detection_rules (
        rule_code, rule_name, rule_type, intent_type, parameters_json,
        risk_weight, rule_version, enabled, description
    ) VALUES (
        :rule_code, :rule_name, :rule_type, :intent_type, :parameters_json,
        :risk_weight, 1, 1, :description
    )
    ON DUPLICATE KEY UPDATE
        rule_name = VALUES(rule_name),
        rule_type = VALUES(rule_type),
        intent_type = VALUES(intent_type),
        parameters_json = VALUES(parameters_json),
        risk_weight = VALUES(risk_weight),
        enabled = 1,
        description = VALUES(description)
    """
)


def _subprocess_env() -> dict[str, str]:
    """构造子进程环境：保证迁移/种子只作用于测试库。"""
    env = os.environ.copy()
    env["MIGRATE_DATABASE_URL"] = TEST_DATABASE_URL
    env["DATABASE_URL"] = TEST_DATABASE_URL
    env["READONLY_DATABASE_URL"] = TEST_DATABASE_URL
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), *[str(REPO_ROOT / path) for path in MODULE_PATHS]]
    )
    return env


def _run_python_module(module: str, *args: str) -> None:
    """在 backend 目录下以当前解释器运行模块（alembic / seed）。"""
    completed = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=str(REPO_ROOT),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"`python -m {module} {' '.join(args)}` 执行失败：\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def _run_alembic_upgrade() -> None:
    """执行 ``alembic upgrade head``（子进程，避免与 pytest 事件循环相互影响）。"""
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "alembic upgrade head 执行失败：\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def _drop_all_objects_sync() -> None:
    """清空测试库中的所有视图与表（只对 honeypot_test 生效）。"""

    async def _drop() -> None:
        connection = await asyncmy.connect(
            host=_TEST_URL.host or "127.0.0.1",
            port=int(_TEST_URL.port or 3306),
            user=_TEST_URL.username or "",
            password=_TEST_URL.password or "",
            database=TEST_DATABASE_NAME,
        )
        try:
            cursor = connection.cursor()
            await cursor.execute(
                """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = %s
                """,
                (TEST_DATABASE_NAME,),
            )
            rows = await cursor.fetchall()
            views = [str(name) for name, kind in rows if str(kind).upper() == "VIEW"]
            tables = [str(name) for name, kind in rows if str(kind).upper() == "BASE TABLE"]
            await cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for view in views:
                await cursor.execute(f"DROP VIEW IF EXISTS `{view}`")
            for table in tables:
                await cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
            await cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            await connection.commit()
        finally:
            connection.close()

    asyncio.run(_drop())


async def _cleanup_business_data() -> None:
    """按外键顺序清理观测数据，并恢复规则 v1 基线（保持 fake_* 诱饵数据）。"""
    from m4_rules_derived.rules.seed_data import RULE_SEEDS

    from shared.db.session import get_rw_factory

    async with get_rw_factory()() as session:
        for table in DELETE_ORDER:
            await session.execute(text(f"DELETE FROM `{table}`"))

        # 规则版本管理类用例会生成 v2+ 版本；先删除非基线版本/未知规则，避免
        # 唯一启用位冲突，再把 v1 基线 upsert 回启用状态。
        await session.execute(
            text(
                "DELETE FROM detection_rules "
                "WHERE rule_version > 1 "
                "   OR rule_code NOT IN ('R01','R02','R03','R04','R05')"
            )
        )
        for rule in RULE_SEEDS:
            await session.execute(
                _RULE_UPSERT_SQL,
                {
                    "rule_code": rule["rule_code"],
                    "rule_name": rule["rule_name"],
                    "rule_type": rule["rule_type"],
                    "intent_type": rule["intent_type"],
                    "parameters_json": json.dumps(
                        rule["parameters_json"], ensure_ascii=False, separators=(",", ":")
                    ),
                    "risk_weight": rule["risk_weight"],
                    "description": rule["description"],
                },
            )
        await session.commit()


async def _dispose_app_engines() -> None:
    """释放应用全局引擎连接池（每个用例结束时调用，避免跨事件循环复用连接）。"""
    from shared.db import session as app_session

    for name in ("_rw_engine", "_ro_engine", "_migrate_engine"):
        engine = getattr(app_session, name, None)
        if engine is not None:
            await engine.dispose()


# ---------------------------------------------------------------------------
# 二、会话级：重建测试库结构 + 导入种子（只跑一次）
# ---------------------------------------------------------------------------


def _verify_schema_sync() -> bool:
    """校验测试库结构是否完整（11 表 + 4 视图 + 迁移 head）。"""

    async def _verify() -> bool:
        connection = await asyncmy.connect(
            host=_TEST_URL.host or "127.0.0.1",
            port=int(_TEST_URL.port or 3306),
            user=_TEST_URL.username or "",
            password=_TEST_URL.password or "",
            database=TEST_DATABASE_NAME,
        )
        try:
            cursor = connection.cursor()
            await cursor.execute(
                """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = %s
                """,
                (TEST_DATABASE_NAME,),
            )
            rows = await cursor.fetchall()
            tables = {str(name) for name, kind in rows if str(kind).upper() == "BASE TABLE"}
            views = {str(name) for name, kind in rows if str(kind).upper() == "VIEW"}
            await cursor.execute("SELECT version_num FROM alembic_version")
            version_row = await cursor.fetchone()
            version = str(version_row[0]) if version_row else ""
            await connection.ensure_closed()
            return (
                EXPECTED_TABLES <= tables
                and EXPECTED_VIEWS <= views
                and version == "0004_seed_rules"
            )
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass

    try:
        return asyncio.run(_verify())
    except Exception:  # noqa: BLE001 - 校验失败按“结构不完整”处理
        return False


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database() -> Iterator[None]:
    """清空 honeypot_test、执行迁移链并导入确定性种子数据。

    测试库可能被同一台机器上的并行任务短暂占用（DDL 死锁/元数据竞争），
    因此准备阶段做有限重试，并在每次迁移后校验结构完整性。
    """
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            _drop_all_objects_sync()
            _run_alembic_upgrade()
            _run_python_module("m2_decoy_capture.cli.seed_decoy", "--all")
            if _verify_schema_sync():
                break
            last_error = RuntimeError("迁移后结构校验未通过")
        except Exception as exc:  # noqa: BLE001 - 并行任务导致的瞬时失败可重试
            last_error = exc
        time.sleep(0.5 * attempt)
    else:
        raise RuntimeError(f"测试库准备失败（已重试 3 次）：{last_error}")
    yield


@pytest.fixture(autouse=True)
async def database_isolation() -> AsyncIterator[None]:
    """用例级隔离：前后清空观测数据、恢复规则基线、释放引擎连接池。"""
    await _cleanup_business_data()
    try:
        yield
    finally:
        await _cleanup_business_data()
        await _dispose_app_engines()


# ---------------------------------------------------------------------------
# 三、数据库会话与事件辅助夹具
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncIterator[Any]:
    """应用读写会话（真实数据库，不 Mock）；用例结束回滚未提交事务。"""
    from shared.db.session import get_rw_factory

    async with get_rw_factory()() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001 - 关闭阶段的回滚失败不应影响测试结论
                pass


@pytest.fixture
async def ro_session() -> AsyncIterator[Any]:
    """只读会话夹具；测试库中同样使用迁移账号连接（环境限制见模块说明）。"""
    from shared.db.session import get_ro_factory

    async with get_ro_factory()() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass


@pytest.fixture
def event_factory() -> Callable[..., object]:
    """构造 ``CapturedEvent`` 的辅助工厂：默认 UUID 唯一、时间为当前 UTC 秒。"""
    from shared.events.builder import build_event
    from shared.events.schema import EventStatus, EventType

    def _factory(
        *,
        event_type: EventType = EventType.CONNECT,
        session_id: str | None = None,
        source_ip: str = "192.0.2.10",
        source_port: int | None = 51234,
        username: str | None = None,
        credential_test_id: str | None = None,
        sql_statement: str | None = None,
        event_time: datetime | None = None,
        returned_rows: int = 0,
        response_ms: int = 0,
        status: EventStatus = EventStatus.SUCCESS,
        payload_truncated: bool = False,
        client_info: str | None = None,
    ):
        return build_event(
            event_type=event_type,
            session_id=session_id or str(uuid.uuid4()),
            source_ip=source_ip,
            source_port=source_port,
            username=username,
            credential_test_id=credential_test_id,
            sql_statement=sql_statement,
            event_time=event_time or datetime.now(UTC).replace(microsecond=0),
            returned_rows=returned_rows,
            response_ms=response_ms,
            status=status,
            payload_truncated=payload_truncated,
            client_info=client_info,
        )

    return _factory


@pytest.fixture
async def ingest_event(db_session) -> Callable[..., object]:
    """使用 ``IngestService`` 在当前测试会话中写入一条事件并返回 IngestResult。"""
    from m1_transaction_integration.services.ingest import IngestService

    async def _ingest(event):
        return await IngestService(db_session).ingest(event)

    return _ingest


@pytest.fixture
def seed_sequences():
    """确定性序列辅助：生成互不相同的测试来源地址、UUID 与时间点。"""

    class _Sequences:
        def __init__(self) -> None:
            self._counter = itertools.count(1)

        def next_int(self) -> int:
            return next(self._counter)

        def ip(self, prefix: str = "198.51.100") -> str:
            """生成 ``198.51.100.N`` 形式的测试地址（N 从 1 递增）。"""
            return f"{prefix}.{self.next_int()}"

        @staticmethod
        def uuid() -> str:
            return str(uuid.uuid4())

        @staticmethod
        def utc_now(microsecond: int = 0) -> datetime:
            return datetime.now(UTC).replace(microsecond=microsecond)

    return _Sequences()


@pytest.fixture
async def client() -> AsyncIterator[object]:
    """httpx.AsyncClient + ASGITransport，直接调用 FastAPI 应用（真实测试库）。"""
    from httpx import ASGITransport, AsyncClient
    from m1_transaction_integration.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
