"""诱饵 MySQL 会话：SQL 路由、伪造响应与标准事件产生。

对齐 `contracts/honeypot-protocol.md` 第 3 章路由表与 `contracts/events.md`：
- 只做**前缀/关键字**判定，不实现完整 SQL 解析器，更不执行客户端 SQL；
- 元数据类（SHOW / DESCRIBE / information_schema）返回伪造结构；
- SELECT 只从进程内伪造目录取行（来源 `fake_*` 或内置合成兜底），按 LIMIT 与
  行数上限截断；未知表 1146、未知库 1049、无法解析 1064、空语句 1065；
- 写/破坏性操作一律 1142（`LOAD DATA` 1148、`KILL` 1094），连接保持可用；
- 每次查询构造一条 `query` 事件：原始 SQL、归一化 SQL、返回行数、耗时 ms、status；
- 事件发射失败只写运行日志，不影响协议响应。

安全红线：采集到的 SQL 只作为字符串保存，绝不交给任何数据库驱动/`exec`/子进程。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from mysql_mimic.errors import ErrorCode, MysqlError
from mysql_mimic.session import Session as MimicSession
from sqlglot import expressions as exp

from app.config import settings
from app.honeypot import fake_catalog
from app.honeypot.auth import (
    AuthAttempt,
    begin_auth_attempts,
    build_credential_test_id,
    drain_auth_attempts,
)
from app.honeypot.emitter import EventEmitter
from app.schemas.events import CapturedEvent, EventStatus, EventType
from app.services.event_builder import (
    build_event,
    new_session_id,
    normalize_sql,
    utc_now_seconds,
)
from app.utils.sql import strip_sql_comments

logger = logging.getLogger(__name__)

# ---- 上限与超时（contracts/honeypot-protocol.md 第 6 章；存储层兜底 64KB）----
PROTOCOL_MAX_SQL_LENGTH = 4096  # 协议层上限：超出截断保存并受控返回 1064
STORAGE_MAX_SQL_LENGTH = 65535  # 存储列兜底上限：超出截断并置 payload_truncated
MAX_ROWS_RETURNED = 100  # 单次查询返回行数上限
QUERY_TIMEOUT_S = 5.0  # 单条语句处理超时
MAX_USERNAME_LENGTH = 128

# 被拒绝类错误码（status=denied），其余为 error
_DENIED_CODES = frozenset({1142, 1148, 1094})


class _UnsupportedQuery(Exception):
    """语句可解析但当前不支持求值（转为 1064 受控错误）。"""


def _mysql_error(message: str, code: int) -> MysqlError:
    """构造 MySQL 协议错误；能映射到上游 `ErrorCode` 时顺带带上 SQLSTATE。"""
    try:
        error_code: object = ErrorCode(code)
    except ValueError:
        error_code = code
    return MysqlError(message, code=error_code)  # type: ignore[arg-type]


def _sanitize(value: str | None, limit: int = 64) -> str:
    """错误消息/日志用的不可信文本清洗：去控制字符并截断。"""
    if not value:
        return ""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", str(value))
    return cleaned[:limit]


def _clean_identifier(name: str | None) -> str:
    """去反引号/双引号与首尾空白，统一小写。"""
    if not name:
        return ""
    return name.strip().strip("`").strip('"').strip().lower()


def _leading_word(normalized: str) -> str:
    match = re.match(r"^[\s(]*([a-z_][a-z0-9_]*)", normalized)
    return match.group(1) if match else ""


def _like_match(value: Any, pattern: str) -> bool:
    """实现 MySQL SHOW ... LIKE 的通配语义（% 任意、_ 单字符）。"""
    regex = "^" + re.escape(pattern).replace("%", ".*").replace("_", ".") + "$"
    return re.fullmatch(regex, str(value), flags=re.IGNORECASE | re.DOTALL) is not None


def _coerce(value: Any) -> Any:
    """比较前做轻量类型归一（数字字符串 → 数值），失败则原样返回。"""
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return value
    return value


def _row_value(row: dict[str, Any], name: str) -> Any:
    """按列名大小写不敏感地从行字典取值。"""
    if name in row:
        return row[name]
    lowered = name.lower()
    for key, value in row.items():
        if key.lower() == lowered:
            return value
    return None


# 服务端变量伪造值（SHOW VARIABLES / @@变量 / information_schema 之外的基础探测）
_SERVER_VARIABLES: dict[str, Any] = {
    "version": "8.4.0-honeypot",
    "version_comment": "MySQL Community Server - 蜜罐模拟实例（TEST-ONLY）",
    "version_compile_os": "Linux",
    "version_compile_machine": "x86_64",
    "protocol_version": 10,
    "character_set_client": "utf8mb4",
    "character_set_connection": "utf8mb4",
    "character_set_results": "utf8mb4",
    "character_set_server": "utf8mb4",
    "character_set_database": "utf8mb4",
    "collation_connection": "utf8mb4_0900_ai_ci",
    "collation_server": "utf8mb4_0900_ai_ci",
    "collation_database": "utf8mb4_0900_ai_ci",
    "autocommit": 1,
    "max_allowed_packet": 67108864,
    "max_connections": 200,
    "net_write_timeout": 60,
    "net_read_timeout": 30,
    "interactive_timeout": 28800,
    "wait_timeout": 28800,
    "time_zone": "+00:00",
    "system_time_zone": "UTC",
    "transaction_isolation": "READ-COMMITTED",
    "tx_isolation": "READ-COMMITTED",
    "lower_case_table_names": 0,
    "default_storage_engine": "InnoDB",
    "sql_mode": "",
    "license": "TEST-ONLY",
    "hostname": "honeypot-node",
    "port": settings.honeypot_port,
    "socket": "/tmp/mysql-honeypot.sock",
    "server_id": 1,
    "thread_cache_size": 8,
    "performance_schema": 0,
}

_DEFAULT_COLUMNS: dict[str, list[str]] = {
    "schemata": [
        "CATALOG_NAME",
        "SCHEMA_NAME",
        "DEFAULT_CHARACTER_SET_NAME",
        "DEFAULT_COLLATION_NAME",
        "SQL_PATH",
    ],
    "tables": [
        "TABLE_CATALOG",
        "TABLE_SCHEMA",
        "TABLE_NAME",
        "TABLE_TYPE",
        "ENGINE",
        "TABLE_ROWS",
        "TABLE_COMMENT",
    ],
    "columns": [
        "TABLE_CATALOG",
        "TABLE_SCHEMA",
        "TABLE_NAME",
        "COLUMN_NAME",
        "ORDINAL_POSITION",
        "COLUMN_DEFAULT",
        "IS_NULLABLE",
        "DATA_TYPE",
        "COLUMN_TYPE",
        "COLUMN_KEY",
        "EXTRA",
        "COLUMN_COMMENT",
    ],
}


class HoneypotSession(MimicSession):
    """自定义 mysql-mimic 会话：路由 SQL、返回伪造数据并产生标准事件。"""

    def __init__(
        self,
        emitter: EventEmitter | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.session_id = session_id or new_session_id()
        self._emitter = emitter or EventEmitter()

        # 认证尝试收集器：由 DecoyNativePasswordAuthPlugin 写入，init 时 drain
        self._auth_attempts = begin_auth_attempts()

        # 会话上下文（init 时补齐）
        self._connect_time = utc_now_seconds()
        self._source_ip = "0.0.0.0"
        self._source_port: int | None = None
        self._client_info: str | None = None
        self._auth_username: str | None = None
        self._connected_emitted = False
        self._disconnect_emitted = False
        self._error_occurred = False
        self._query_count = 0

    # ------------------------------------------------------------------
    # 生命周期钩子
    # ------------------------------------------------------------------
    async def init(self, connection) -> None:  # type: ignore[override]
        """连接阶段完成后：补来源信息，按 connect → auth 顺序产生事件。"""
        await super().init(connection)
        self._resolve_peer(connection)
        self._client_info = self._build_client_info(connection)
        self._auth_username = self._external_username(connection)

        # ① connect 事件（连接建立后立即产生；此事件创建 sessions 行）
        connect_event = build_event(
            event_type=EventType.CONNECT,
            session_id=self.session_id,
            source_ip=self._source_ip,
            source_port=self._source_port,
            event_time=self._connect_time,
            status=EventStatus.SUCCESS,
            client_info=self._client_info,
        )
        await self._emit(connect_event)
        self._connected_emitted = True

        # ② auth 事件（成功/失败均记录；失败尝试计入认证统计）
        attempts = drain_auth_attempts()
        if not attempts and self._auth_username is not None:
            # 兜底：认证插件未写入时按最终用户名判定（理论上不会发生）
            success = self.username is not None
            attempts = [
                AuthAttempt(
                    username=self._auth_username,
                    success=success,
                    credential_test_id=build_credential_test_id(
                        self._auth_username, "*UNKNOWN*"
                    ),
                )
            ]
        for attempt in attempts:
            auth_event = build_event(
                event_type=EventType.AUTH,
                session_id=self.session_id,
                source_ip=self._source_ip,
                source_port=self._source_port,
                username=attempt.username,
                credential_test_id=attempt.credential_test_id,
                event_time=utc_now_seconds(),
                status=EventStatus.SUCCESS if attempt.success else EventStatus.FAILURE,
                client_info=self._client_info if len(attempts) == 1 else None,
            )
            await self._emit(auth_event)

        if self.username is None:
            logger.info(
                "连接认证未通过：session_id=%s username=%s",
                self.session_id,
                self._auth_username,
            )

    async def close(self) -> None:  # type: ignore[override]
        """连接关闭：产生 disconnect 事件并同步会话结束状态。"""
        if not self._disconnect_emitted:
            self._disconnect_emitted = True
            status = (
                EventStatus.FAILURE if self._error_occurred else EventStatus.SUCCESS
            )
            disconnect_event = build_event(
                event_type=EventType.DISCONNECT,
                session_id=self.session_id,
                source_ip=self._source_ip,
                source_port=self._source_port,
                event_time=utc_now_seconds(),
                status=status,
            )
            await self._emit(disconnect_event)
            logger.info(
                "会话关闭：session_id=%s source_ip=%s queries=%s error=%s",
                self.session_id,
                self._source_ip,
                self._query_count,
                self._error_occurred,
            )
        await super().close()

    async def reset(self) -> None:  # type: ignore[override]
        """COM_RESET_CONNECTION：不维护真实会话状态，仅清空待处理认证记录。"""
        drain_auth_attempts()

    async def use(self, database: str) -> None:  # type: ignore[override]
        """COM_INIT_DB（二进制 `USE` 命令）：校验库名并记录一条 query 事件。"""
        started = time.perf_counter()
        db = _clean_identifier(database)
        status = EventStatus.SUCCESS
        error: MysqlError | None = None
        if db in fake_catalog.DATABASES:
            self.database = db
        else:
            status = EventStatus.ERROR
            error = _mysql_error(f"Unknown database '{_sanitize(db)}'", 1049)
        elapsed = int(round((time.perf_counter() - started) * 1000))
        await self._emit(
            build_event(
                event_type=EventType.QUERY,
                session_id=self.session_id,
                source_ip=self._source_ip,
                source_port=self._source_port,
                username=self.username or self._auth_username,
                sql_statement=f"USE `{db}`",
                event_time=utc_now_seconds(),
                status=status,
                response_ms=elapsed,
            )
        )
        if error is not None:
            raise error

    # ------------------------------------------------------------------
    # 查询入口：路由 + 事件
    # ------------------------------------------------------------------
    async def handle_query(self, sql: str, attrs: dict[str, str]):  # type: ignore[override]
        """处理一条 COM_QUERY：受控截断 → 路由 → 构造 query 事件。"""
        started = time.perf_counter()
        raw = sql or ""
        truncated = False
        if len(raw) > STORAGE_MAX_SQL_LENGTH:
            raw = raw[:STORAGE_MAX_SQL_LENGTH]
            truncated = True
        protocol_overflow = len(raw) > PROTOCOL_MAX_SQL_LENGTH
        stored = raw[:PROTOCOL_MAX_SQL_LENGTH] if protocol_overflow else raw
        if protocol_overflow:
            truncated = True

        status = EventStatus.SUCCESS
        returned_rows = 0
        result: Any = ([], [])
        try:
            if protocol_overflow:
                status = EventStatus.ERROR
                raise _mysql_error(
                    "You have an error in your SQL syntax; check the manual that "
                    "corresponds to your MySQL server version for the right syntax "
                    f"to use near '{_sanitize(stored, 64)}' at line 1",
                    1064,
                )
            self._query_count += 1
            try:
                self.timestamp = datetime.now(tz=self.timezone())
            except Exception:  # noqa: BLE001 - 会话变量异常不影响路由
                self.timestamp = datetime.now()
            expression = self._safe_parse(stored)
            result = await asyncio.wait_for(
                self.query(expression, stored, attrs), timeout=QUERY_TIMEOUT_S
            )
            rows = result[0] if result else []
            try:
                returned_rows = len(rows)  # type: ignore[arg-type]
            except TypeError:
                returned_rows = 0
            return result
        except TimeoutError:
            status = EventStatus.ERROR
            self._error_occurred = False
            raise _mysql_error("Unknown error", 1105) from None
        except MysqlError as exc:
            code = _error_code_of(exc)
            status = EventStatus.DENIED if code in _DENIED_CODES else EventStatus.ERROR
            raise
        except _UnsupportedQuery:
            status = EventStatus.ERROR
            raise _mysql_error(
                "You have an error in your SQL syntax; check the manual that "
                "corresponds to your MySQL server version for the right syntax "
                f"to use near '{_sanitize(stored, 64)}' at line 1",
                1064,
            ) from None
        except Exception:
            status = EventStatus.ERROR
            self._error_occurred = True
            logger.exception(
                "查询处理异常：session_id=%s sql=%s", self.session_id, _sanitize(stored, 200)
            )
            raise _mysql_error("Unknown error", 1105) from None
        finally:
            response_ms = int(round((time.perf_counter() - started) * 1000))
            normalized = normalize_sql(stored)
            event = build_event(
                event_type=EventType.QUERY,
                session_id=self.session_id,
                source_ip=self._source_ip,
                source_port=self._source_port,
                username=self.username or self._auth_username,
                sql_statement=stored,
                event_time=utc_now_seconds(),
                returned_rows=returned_rows,
                response_ms=response_ms,
                status=status,
                payload_truncated=truncated,
            )
            await self._emit(event)
            logger.info(
                "query session=%s status=%s rows=%s ms=%s norm=%s",
                self.session_id,
                status,
                returned_rows,
                response_ms,
                (normalized or "")[:200],
            )

    async def query(self, expression, sql: str, attrs: dict[str, str]):  # type: ignore[override]
        """按 `contracts/honeypot-protocol.md` 3.3 的路由顺序返回伪造结果。"""
        normalized = normalize_sql(sql) or ""
        if not normalized:
            raise _mysql_error("Query was empty", 1065)

        leading = _leading_word(normalized)

        # 1) 危险/写操作优先判定（带注释、大小写混写也能识别）
        if re.match(r"^load\s+data\b", normalized):
            raise _mysql_error(
                "The used command is not allowed with this MySQL version", 1148
            )
        if re.search(r"\binto\s+(out|dump)file\b", normalized):
            raise _mysql_error(self._denied_message("SELECT"), 1142)
        if leading in {
            "insert",
            "update",
            "delete",
            "drop",
            "truncate",
            "alter",
            "create",
            "rename",
            "grant",
            "revoke",
            "install",
            "uninstall",
            "optimize",
            "repair",
        }:
            raise _mysql_error(self._denied_message(leading.upper()), 1142)
        if leading == "kill":
            kill_id = ""
            match = re.search(r"\bkill\s+(\d+)", sql, flags=re.IGNORECASE)
            if match:
                kill_id = match.group(1)
            raise _mysql_error(f"Unknown thread id: {_sanitize(kill_id, 20)}", 1094)
        if leading in {"explain", "analyze", "call", "do", "handler", "lock", "unlock"}:
            raise _mysql_error(
                "You have an error in your SQL syntax; check the manual that "
                "corresponds to your MySQL server version",
                1064,
            )

        # 2) 元数据类
        if leading == "show":
            return self._route_show(expression, normalized, sql)
        if leading in {"describe", "desc"}:
            return self._route_describe(expression, normalized)
        if leading == "use":
            return self._route_use(normalized)
        if leading == "set":
            return ([], [])
        if leading in {"begin", "start", "commit", "rollback", "savepoint", "release"}:
            return ([], [])

        # 3) SELECT
        if leading == "select":
            if "information_schema" in normalized:
                return self._select_information_schema(expression, normalized, sql)
            target = self._extract_table(expression, normalized)
            if target is None:
                return self._select_probe(expression, normalized, sql)
            return await self._select_fake_table(expression, normalized, sql, target)

        # 4) 其他一律受控语法错误
        raise _mysql_error(
            "You have an error in your SQL syntax; check the manual that "
            "corresponds to your MySQL server version for the right syntax "
            f"to use near '{_sanitize(sql, 64)}' at line 1",
            1064,
        )

    # ------------------------------------------------------------------
    # SHOW / DESCRIBE / USE
    # ------------------------------------------------------------------
    def _route_show(self, expression, normalized: str, raw: str):
        kind = self._show_kind(normalized)
        target = self._show_target(kind, expression, normalized)
        database = self._show_database(expression, normalized)
        like = self._show_like(expression, raw)

        if kind == "DATABASES":
            rows = [(db,) for db in fake_catalog.DATABASES]
            if like:
                rows = [r for r in rows if _like_match(r[0], like)]
            return rows, ["Database"]

        if kind == "TABLES":
            db = database or _clean_identifier(self.database) or fake_catalog.PRIMARY_DATABASE
            if db not in fake_catalog.DATABASES:
                raise _mysql_error(f"Unknown database '{_sanitize(db)}'", 1049)
            tables = fake_catalog.list_tables(db)
            if like:
                tables = [t for t in tables if _like_match(t.name, like)]
            full = bool(
                isinstance(expression, exp.Show) and expression.args.get("full")
            ) or normalized.startswith("show full tables")
            if full:
                return (
                    [(t.name, "BASE TABLE") for t in tables],
                    [f"Tables_in_{db}", "Table_type"],
                )
            return ([(t.name,) for t in tables], [f"Tables_in_{db}"])

        if kind == "COLUMNS":
            db, table_name = self._split_db_table(
                target or "", database or _clean_identifier(self.database)
            )
            return self._describe_rows(db, table_name, full=self._is_full_columns(normalized, expression))

        if kind == "CREATE TABLE":
            db, table_name = self._split_db_table(
                target or "", database or _clean_identifier(self.database)
            )
            meta = self._require_table(db, table_name)
            return [(meta.name, self._create_table_ddl(meta))], ["Table", "Create Table"]

        if kind == "CREATE DATABASE":
            db = database or _clean_identifier(target) or fake_catalog.PRIMARY_DATABASE
            if db not in fake_catalog.DATABASES:
                raise _mysql_error(f"Unknown database '{_sanitize(db)}'", 1049)
            return (
                [
                    (
                        db,
                        f"CREATE DATABASE `{db}` /*!40100 DEFAULT CHARACTER SET utf8mb4 "
                        "COLLATE utf8mb4_0900_ai_ci */ /* TEST-ONLY 伪造库 */",
                    )
                ],
                ["Database", "Create Database"],
            )

        if kind == "VARIABLES":
            rows = [
                (name, str(value)) for name, value in sorted(_SERVER_VARIABLES.items())
            ]
            if like:
                rows = [r for r in rows if _like_match(r[0], like)]
            return rows, ["Variable_name", "Value"]

        if kind == "STATUS":
            rows = [
                ("Threads_connected", "1"),
                ("Threads_running", "1"),
                ("Uptime", "0"),
                ("Questions", str(self._query_count)),
                ("Slow_queries", "0"),
                ("Open_tables", "0"),
            ]
            if like:
                rows = [r for r in rows if _like_match(r[0], like)]
            return rows, ["Variable_name", "Value"]

        if kind == "PROCESSLIST":
            return (
                [
                    (
                        1,
                        self.username or self._auth_username or "honeypot",
                        f"{self._source_ip}:{self._source_port or 0}",
                        self.database or fake_catalog.PRIMARY_DATABASE,
                        "Query",
                        0,
                        "init",
                        None,
                    )
                ],
                ["Id", "User", "Host", "db", "Command", "Time", "State", "Info"],
            )

        if kind == "ENGINES":
            return (
                [
                    ("InnoDB", "DEFAULT", "Supports transactions, row-level locking", "YES", "YES", "YES"),
                    ("MyISAM", "YES", "Non-transactional engine", "NO", "NO", "YES"),
                ],
                ["Engine", "Support", "Comment", "Transactions", "XA", "Savepoints"],
            )

        if kind == "CHARSET":
            return (
                [("utf8mb4", "UTF-8 Unicode", "utf8mb4_0900_ai_ci", 4)],
                ["Charset", "Description", "Default collation", "Maxlen"],
            )

        if kind == "COLLATION":
            return (
                [("utf8mb4_0900_ai_ci", "utf8mb4", 255, "Yes", "Yes", 0, "NO PAD")],
                ["Collation", "Charset", "Id", "Default", "Compiled", "Sortlen", "Pad_attribute"],
            )

        if kind == "GRANTS":
            user = _sanitize(self.username or self._auth_username or "demo", 64)
            return (
                [(f"GRANT USAGE ON *.* TO `{user}`@`%` /* TEST-ONLY 伪造权限 */",)],
                [f"Grants for {user}@%"],
            )

        if kind == "INDEX":
            db, table_name = self._split_db_table(
                target or "", database or _clean_identifier(self.database)
            )
            return self._show_index_rows(db, table_name, like)

        if kind == "TABLE STATUS":
            db = database or _clean_identifier(self.database) or fake_catalog.PRIMARY_DATABASE
            if db not in fake_catalog.DATABASES:
                raise _mysql_error(f"Unknown database '{_sanitize(db)}'", 1049)
            rows = [
                (
                    t.name,
                    "InnoDB",
                    10,
                    "Dynamic",
                    self._row_count(t.key),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    None,
                )
                for t in fake_catalog.list_tables(db)
            ]
            return (
                rows,
                [
                    "Name",
                    "Engine",
                    "Version",
                    "Row_format",
                    "Rows",
                    "Avg_row_length",
                    "Data_length",
                    "Max_data_length",
                    "Index_length",
                    "Data_free",
                    "Auto_increment",
                    "Comment",
                ],
            )

        if kind == "WARNINGS":
            return [], ["Level", "Code", "Message"]
        if kind == "ERRORS":
            return [], ["Level", "Code", "Message"]
        if kind == "EMPTY":
            return [], []
        raise _mysql_error(
            "You have an error in your SQL syntax; check the manual that "
            "corresponds to your MySQL server version",
            1064,
        )

    def _route_describe(self, expression, normalized: str):
        if isinstance(expression, exp.Describe):
            this = expression.this
            if isinstance(this, exp.Query):
                # EXPLAIN <query> 被解析为 Describe；本版拒绝
                raise _mysql_error(
                    "You have an error in your SQL syntax; check the manual that "
                    "corresponds to your MySQL server version",
                    1064,
                )
            db = _clean_identifier(getattr(this, "db", "") or "")
            table_name = _clean_identifier(getattr(this, "name", "") or "")
        else:
            match = re.match(
                r"^(?:describe|desc)\s+([`\"\w.]+)", normalized, flags=re.IGNORECASE
            )
            if not match:
                raise _mysql_error(
                    "You have an error in your SQL syntax; check the manual that "
                    "corresponds to your MySQL server version",
                    1064,
                )
            db, table_name = self._split_db_table(
                match.group(1), _clean_identifier(self.database)
            )
        if not db:
            db = _clean_identifier(self.database) or fake_catalog.PRIMARY_DATABASE
        return self._describe_rows(db, table_name, full=False)

    def _route_use(self, normalized: str):
        match = re.match(r"^use\s+([`\"\w.]+)", normalized, flags=re.IGNORECASE)
        db = _clean_identifier(match.group(1)) if match else ""
        if db not in fake_catalog.DATABASES:
            raise _mysql_error(f"Unknown database '{_sanitize(db)}'", 1049)
        self.database = db
        return ([], [])

    # -- SHOW 解析辅助 --
    @staticmethod
    def _show_kind(normalized: str) -> str:
        text = re.sub(r"^show\s+", "", normalized.strip())
        text = re.sub(r"^full\s+", "", text)
        if text.startswith(("databases", "schemas")):
            return "DATABASES"
        if text.startswith("tables"):
            return "TABLES"
        if text.startswith(("columns", "fields")):
            return "COLUMNS"
        if text.startswith("create table"):
            return "CREATE TABLE"
        if text.startswith(("create database", "create schema")):
            return "CREATE DATABASE"
        if text.startswith("table status"):
            return "TABLE STATUS"
        if text.startswith(("index", "indexes", "keys")):
            return "INDEX"
        if text.startswith("variables"):
            return "VARIABLES"
        if text.startswith("status"):
            return "STATUS"
        if text.startswith("processlist"):
            return "PROCESSLIST"
        if text.startswith("engines"):
            return "ENGINES"
        if text.startswith(("charset", "character set", "character_set")):
            return "CHARSET"
        if text.startswith("collation"):
            return "COLLATION"
        if text.startswith("grants"):
            return "GRANTS"
        if text.startswith("warnings"):
            return "WARNINGS"
        if text.startswith("errors"):
            return "ERRORS"
        if text.startswith(
            (
                "triggers",
                "events",
                "plugins",
                "master",
                "slave",
                "replica",
                "binary",
                "open",
                "global",
                "session",
                "profiles",
                "privileges",
                "function",
                "procedure",
            )
        ):
            return "EMPTY"
        return "UNKNOWN"

    def _show_target(self, kind: str, expression, normalized: str) -> str:
        if isinstance(expression, exp.Show):
            target = expression.text("target")
            if target:
                return _clean_identifier(target)
        patterns = {
            "COLUMNS": r"(?:from|in)\s+([`\"\w.]+)",
            "CREATE TABLE": r"create\s+table\s+([`\"\w.]+)",
            "CREATE DATABASE": r"create\s+(?:database|schema)\s+([`\"\w.]+)",
            "INDEX": r"(?:from|in)\s+([`\"\w.]+)",
            "TABLES": r"(?:from|in)\s+([`\"\w.]+)",
        }
        pattern = patterns.get(kind)
        if not pattern:
            return ""
        match = re.search(pattern, normalized)
        return _clean_identifier(match.group(1)) if match else ""

    def _show_database(self, expression, normalized: str) -> str:
        if isinstance(expression, exp.Show):
            db = expression.text("db")
            if db:
                return _clean_identifier(db)
        match = re.search(r"(?:from|in)\s+([`\"\w.]+)", normalized)
        return _clean_identifier(match.group(1)) if match else ""

    @staticmethod
    def _show_like(expression, raw: str) -> str | None:
        if isinstance(expression, exp.Show):
            like_node = expression.args.get("like")
            if like_node is not None:
                value = getattr(like_node, "this", None)
                if value is not None:
                    return str(value)
        match = re.search(r"like\s+'((?:[^'\\]|\\.)*)'", raw, flags=re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _is_full_columns(normalized: str, expression) -> bool:
        if normalized.startswith("show full columns") or normalized.startswith(
            "show full fields"
        ):
            return True
        return bool(isinstance(expression, exp.Show) and expression.args.get("full"))

    def _split_db_table(self, name: str, default_db: str | None) -> tuple[str, str]:
        cleaned = _clean_identifier(name)
        if not cleaned:
            raise _mysql_error(
                "You have an error in your SQL syntax. Table name is missing.", 1064
            )
        if "." in cleaned:
            db, _, table = cleaned.partition(".")
            return _clean_identifier(db), _clean_identifier(table)
        db = _clean_identifier(default_db) or fake_catalog.PRIMARY_DATABASE
        if db not in fake_catalog.DATABASES:
            db = fake_catalog.PRIMARY_DATABASE
        return db, cleaned

    def _require_table(self, db: str, table_name: str) -> fake_catalog.Table:
        meta = fake_catalog.get_table(db, table_name)
        if meta is None:
            if db not in fake_catalog.DATABASES:
                raise _mysql_error(f"Unknown database '{_sanitize(db)}'", 1049)
            raise _mysql_error(
                f"Table '{_sanitize(db)}.{_sanitize(table_name)}' doesn't exist", 1146
            )
        return meta

    def _describe_rows(self, db: str, table_name: str, *, full: bool) -> tuple[list, list]:
        meta = self._require_table(db, table_name)
        rows: list[tuple] = []
        for col in meta.columns:
            row = [
                col.name,
                col.type,
                "YES" if col.nullable else "NO",
                col.key,
                col.default,
                col.extra,
            ]
            if full:
                row.extend([None, "select,insert,update,delete", "TEST-ONLY 伪造列"])
            rows.append(tuple(row))
        columns = ["Field", "Type", "Null", "Key", "Default", "Extra"]
        if full:
            columns.extend(["Collation", "Privileges", "Comment"])
        return rows, columns

    @staticmethod
    def _create_table_ddl(meta: fake_catalog.Table) -> str:
        lines: list[str] = []
        for col in meta.columns:
            null = "" if col.nullable else " NOT NULL"
            default = f" DEFAULT {col.default}" if col.default else ""
            lines.append(f"  `{col.name}` {col.type}{null}{default} COMMENT 'TEST-ONLY 伪造列'")
        keys: list[str] = []
        for col in meta.columns:
            if col.key == "PRI":
                keys.append(f"  PRIMARY KEY (`{col.name}`)")
        for col in meta.columns:
            if col.key == "UNI":
                keys.append(f"  UNIQUE KEY `uk_{meta.name}_{col.name}` (`{col.name}`)")
        body = ",\n".join(lines + keys)
        return (
            f"CREATE TABLE `{meta.name}` (\n{body}\n) ENGINE=InnoDB "
            "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci "
            "COMMENT='TEST-ONLY 伪造表结构（非真实业务数据）'"
        )

    def _show_index_rows(self, db: str, table_name: str, like: str | None):
        meta = self._require_table(db, table_name)
        rows: list[tuple] = []
        seq = 0
        for col in meta.columns:
            if col.key == "PRI":
                seq += 1
                rows.append(
                    (meta.name, 0, "PRIMARY", seq, col.name, "A", 0, None, None, "", "BTREE", "", "")
                )
        for col in meta.columns:
            if col.key == "UNI":
                rows.append(
                    (meta.name, 0, f"uk_{meta.name}_{col.name}", 1, col.name, "A", 0, None, None, "", "BTREE", "", "")
                )
        if like:
            rows = [r for r in rows if _like_match(r[2], like)]
        columns = [
            "Table",
            "Non_unique",
            "Key_name",
            "Seq_in_index",
            "Column_name",
            "Collation",
            "Cardinality",
            "Sub_part",
            "Packed",
            "Null",
            "Index_type",
            "Comment",
            "Index_comment",
        ]
        return rows, columns

    def _denied_message(self, statement_type: str) -> str:
        user = _sanitize(self.username or self._auth_username or "demo", MAX_USERNAME_LENGTH)
        host = _sanitize(self._source_ip, 45) or "localhost"
        return (
            f"{statement_type} command denied to user '{user}'@'{host}' "
            "for table '*' /* TEST-ONLY 诱饵：写操作被安全策略拒绝 */"
        )

    # ------------------------------------------------------------------
    # SELECT：伪造表 / information_schema / 客户端探测
    # ------------------------------------------------------------------
    async def _select_fake_table(self, expression, normalized: str, raw: str, target):
        database, table_name = target
        db = _clean_identifier(database) or _clean_identifier(self.database)
        if not db:
            db = fake_catalog.PRIMARY_DATABASE
        if db not in fake_catalog.DATABASES:
            # 未知库中的表按 1146 处理更贴近客户端预期
            raise _mysql_error(
                f"Table '{_sanitize(db)}.{_sanitize(table_name)}' doesn't exist", 1146
            )
        key = fake_catalog.resolve_table(f"{db}.{table_name}", db)
        if key is None:
            raise _mysql_error(
                f"Table '{_sanitize(db)}.{_sanitize(table_name)}' doesn't exist", 1146
            )
        meta = fake_catalog.get_table(*key)
        if meta is None:  # pragma: no cover - resolve_table 已保证
            raise _mysql_error(f"Table '{_sanitize(table_name)}' doesn't exist", 1146)

        await self._ensure_catalog()
        rows: list[dict[str, Any]] = [dict(r) for r in fake_catalog.all_rows(key)]
        rows = self._apply_where(expression, rows)

        # 聚合查询（COUNT(*) 等，演示常用）
        aggregate = self._aggregate_result(expression, rows)
        if aggregate is not None:
            return aggregate

        requested = self._requested_columns(expression)
        if requested is None:
            selected = meta.column_names()
        else:
            selected = []
            for lookup, _output in requested:
                col = meta.column(lookup)
                if col is None:
                    # 契约错误码集合中不含 1054，这里统一按 1064 受控拒绝
                    raise _mysql_error(
                        "You have an error in your SQL syntax; check the manual that "
                        "corresponds to your MySQL server version for the right syntax "
                        f"to use near '{_sanitize(lookup)}' at line 1",
                        1064,
                    )
                selected.append(col.name)

        count, offset = self._parse_limit(raw)
        if offset:
            rows = rows[offset:]
        if count is not None:
            rows = rows[:count]
        rows = rows[:MAX_ROWS_RETURNED]
        projected = [tuple(_row_value(row, name) for name in selected) for row in rows]
        return projected, list(selected)

    def _select_information_schema(self, expression, normalized: str, raw: str):
        """返回与伪造库一致的 information_schema 假元数据（支持 WHERE / LIMIT）。"""
        table_name = ""
        if isinstance(expression, exp.Select):
            table_node = expression.find(exp.Table)
            if table_node is not None:
                table_name = _clean_identifier(table_node.name)
        if not table_name:
            match = re.search(
                r"information_schema\s*\.\s*([`\"\w]+)", normalized, flags=re.IGNORECASE
            )
            table_name = _clean_identifier(match.group(1)) if match else ""

        rows: list[dict[str, Any]]
        default_columns: list[str]
        if table_name == "schemata":
            rows = self._info_schemata_rows()
            default_columns = _DEFAULT_COLUMNS["schemata"]
        elif table_name == "tables":
            rows = self._info_tables_rows()
            default_columns = _DEFAULT_COLUMNS["tables"]
        elif table_name == "columns":
            rows = self._info_columns_rows()
            default_columns = _DEFAULT_COLUMNS["columns"]
        else:
            # 其他 information_schema 视图：返回空结果集，避免客户端探测失败
            return [], ["TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME"]

        rows = self._apply_where(expression, rows)

        requested = self._requested_columns(expression)
        if requested is None:
            selected = default_columns
            output_names = default_columns
        else:
            selected = [lookup.upper() for lookup, _ in requested]
            output_names = [output for _, output in requested]

        count, offset = self._parse_limit(raw)
        if offset:
            rows = rows[offset:]
        if count is not None:
            rows = rows[:count]
        rows = rows[:MAX_ROWS_RETURNED]
        projected = [
            tuple(row.get(column) for column in selected) for row in rows
        ]
        return projected, output_names

    def _info_schemata_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "CATALOG_NAME": "def",
                "SCHEMA_NAME": db,
                "DEFAULT_CHARACTER_SET_NAME": "utf8mb4",
                "DEFAULT_COLLATION_NAME": "utf8mb4_0900_ai_ci",
                "SQL_PATH": None,
            }
            for db in fake_catalog.DATABASES
        ]

    def _info_tables_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key in fake_catalog.iter_table_keys():
            table = fake_catalog.table_for_key(key)
            if table is None:  # pragma: no cover
                continue
            rows.append(
                {
                    "TABLE_CATALOG": "def",
                    "TABLE_SCHEMA": key[0],
                    "TABLE_NAME": key[1],
                    "TABLE_TYPE": "BASE TABLE",
                    "ENGINE": "InnoDB",
                    "TABLE_ROWS": self._row_count(key),
                    "TABLE_COMMENT": "TEST-ONLY 伪造表",
                }
            )
        return rows

    def _info_columns_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key in fake_catalog.iter_table_keys():
            table = fake_catalog.table_for_key(key)
            if table is None:  # pragma: no cover
                continue
            for position, column in enumerate(table.columns, start=1):
                rows.append(
                    {
                        "TABLE_CATALOG": "def",
                        "TABLE_SCHEMA": key[0],
                        "TABLE_NAME": key[1],
                        "COLUMN_NAME": column.name,
                        "ORDINAL_POSITION": position,
                        "COLUMN_DEFAULT": column.default,
                        "IS_NULLABLE": "YES" if column.nullable else "NO",
                        "DATA_TYPE": column.type.split("(")[0],
                        "COLUMN_TYPE": column.type,
                        "COLUMN_KEY": column.key,
                        "EXTRA": column.extra,
                        "COLUMN_COMMENT": "TEST-ONLY 伪造列",
                    }
                )
        return rows

    def _select_probe(self, expression, normalized: str, raw: str):
        """无 FROM 的 SELECT：客户端探测（SELECT 1 / @@version / DATABASE() 等）。"""
        names: list[str] = []
        values: list[Any] = []
        if isinstance(expression, exp.Select) and expression.expressions:
            for item in expression.expressions:
                node = item.this if isinstance(item, exp.Alias) else item
                name = item.alias_or_name or item.sql()
                names.append(name or "?")
                values.append(self._eval_scalar(node))
        else:
            names, values = self._fallback_probe(raw)
        return [tuple(values)], names

    def _fallback_probe(self, raw: str) -> tuple[list[str], list[Any]]:
        """解析失败时的兜底：按逗号切分 SELECT 列表并求值常见探测表达式。"""
        text = strip_sql_comments(raw)
        match = re.match(
            r"^\s*select\s+(.*?)(?:\s+from\b|\s+limit\b|;|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ["?"], [None]
        names: list[str] = []
        values: list[Any] = []
        for part in match.group(1).split(","):
            token = part.strip()
            if not token:
                continue
            names.append(token[:64])
            values.append(self._eval_raw_probe(token))
        return names or ["?"], values or [None]

    def _eval_raw_probe(self, token: str) -> Any:
        lowered = token.lower()
        if lowered in {"null"}:
            return None
        if lowered in {"true"}:
            return 1
        if lowered in {"false"}:
            return 0
        if re.fullmatch(r"[-+]?\d+", lowered):
            return int(lowered)
        if re.fullmatch(r"[-+]?\d+\.\d+", lowered):
            return float(lowered)
        if re.fullmatch(r"'(?:[^'\\]|\\.)*'", token):
            return token[1:-1]
        if lowered.startswith("@@"):
            return self._variable_value(lowered[2:])
        if lowered.startswith("@"):
            return self._variable_value(lowered[1:])
        function = re.match(r"([a-z_][a-z0-9_]*)\s*\(.*\)$", lowered)
        if function:
            return self._function_value(function.group(1))
        return None

    def _eval_scalar(self, node) -> Any:
        """求值客户端探测表达式中的单个节点（只读、无副作用）。"""
        if isinstance(node, exp.Literal):
            if node.is_string:
                return node.this
            text = str(node.this)
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return text
        if isinstance(node, exp.Null):
            return None
        if isinstance(node, exp.Boolean):
            return 1 if node.this else 0
        if isinstance(node, exp.SessionParameter):
            return self._variable_value(node.name)
        if isinstance(node, exp.CurrentSchema):
            return self.database or fake_catalog.PRIMARY_DATABASE
        if isinstance(node, exp.CurrentVersion):
            return _SERVER_VARIABLES["version"]
        if isinstance(node, exp.Anonymous):
            return self._function_value(node.name)
        if isinstance(node, exp.Paren):
            return self._eval_scalar(node.this)
        if isinstance(node, exp.Cast):
            return self._eval_scalar(node.this)
        if isinstance(node, exp.Neg):
            inner = self._eval_scalar(node.this)
            try:
                return -inner  # type: ignore[operator]
            except TypeError:
                return None
        if isinstance(node, exp.Column):
            # 无 FROM 的列引用（如 SELECT 'x' AS a 的别名）不参与计算
            return None
        raise _UnsupportedQuery(node.sql())

    def _variable_value(self, name: str) -> Any:
        key = (name or "").strip().lower()
        if key in _SERVER_VARIABLES:
            return _SERVER_VARIABLES[key]
        return None

    def _function_value(self, name: str) -> Any:
        key = (name or "").strip().upper()
        if key in {"DATABASE", "SCHEMA", "CURRENT_SCHEMA", "CURRENT_DATABASE"}:
            return self.database or fake_catalog.PRIMARY_DATABASE
        if key in {"USER", "CURRENT_USER", "SYSTEM_USER", "SESSION_USER"}:
            user = self.username or self._auth_username or "honeypot"
            return f"{user}@{self._source_ip}"
        if key in {"VERSION", "CURRENT_VERSION"}:
            return _SERVER_VARIABLES["version"]
        if key == "CONNECTION_ID":
            try:
                return self.connection.connection_id
            except Exception:  # noqa: BLE001 - 会话未绑定连接时给出固定值
                return 1
        if key in {"LAST_INSERT_ID", "ROW_COUNT", "FOUND_ROWS"}:
            return 0
        if key in {"NOW", "CURRENT_TIMESTAMP", "SYSDATE", "LOCALTIME", "LOCALTIMESTAMP"}:
            return datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if key in {"UNIX_TIMESTAMP"}:
            return int(datetime.now(UTC).timestamp())
        if key == "PI":
            return 3.141593
        if key in {"UUID", "RAND"}:
            return None
        return None

    # ------------------------------------------------------------------
    # WHERE / LIMIT / 列投影
    # ------------------------------------------------------------------
    def _apply_where(
        self, expression, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not isinstance(expression, exp.Select):
            return rows
        where = expression.args.get("where")
        if where is None:
            return rows
        try:
            return [row for row in rows if self._eval_condition(where.this, row)]
        except _UnsupportedQuery:
            logger.info("WHERE 条件暂不支持求值，忽略过滤条件")
            return rows

    def _eval_condition(self, node, row: dict[str, Any]) -> bool:
        if isinstance(node, exp.Paren):
            return self._eval_condition(node.this, row)
        if isinstance(node, exp.And):
            return self._eval_condition(node.this, row) and self._eval_condition(
                node.expression, row
            )
        if isinstance(node, exp.Or):
            return self._eval_condition(node.this, row) or self._eval_condition(
                node.expression, row
            )
        if isinstance(node, exp.Not):
            return not self._eval_condition(node.this, row)
        if isinstance(node, exp.EQ):
            return self._compare(
                self._operand(node.this, row), self._operand(node.expression, row), "eq"
            )
        if isinstance(node, exp.NEQ):
            return self._compare(
                self._operand(node.this, row), self._operand(node.expression, row), "ne"
            )
        if isinstance(node, exp.GT):
            return self._compare(
                self._operand(node.this, row), self._operand(node.expression, row), "gt"
            )
        if isinstance(node, exp.GTE):
            return self._compare(
                self._operand(node.this, row), self._operand(node.expression, row), "ge"
            )
        if isinstance(node, exp.LT):
            return self._compare(
                self._operand(node.this, row), self._operand(node.expression, row), "lt"
            )
        if isinstance(node, exp.LTE):
            return self._compare(
                self._operand(node.this, row), self._operand(node.expression, row), "le"
            )
        if isinstance(node, (exp.Like, exp.ILike)):
            actual = self._operand(node.this, row)
            pattern = self._operand(node.expression, row)
            return actual is not None and _like_match(actual, str(pattern))
        if isinstance(node, exp.Is):
            actual = self._operand(node.this, row)
            expected = self._operand(node.expression, row)
            return actual is None if expected is None else actual == expected
        if isinstance(node, exp.In):
            actual = self._operand(node.this, row)
            options = [self._operand(item, row) for item in node.expressions]
            return actual in options
        if isinstance(node, exp.Between):
            actual = self._operand(node.this, row)
            low = self._operand(node.args.get("low"), row)
            high = self._operand(node.args.get("high"), row)
            try:
                return low <= actual <= high  # type: ignore[operator]
            except TypeError:
                return False
        raise _UnsupportedQuery(node.sql())

    def _operand(self, node, row: dict[str, Any]) -> Any:
        if isinstance(node, exp.Paren):
            return self._operand(node.this, row)
        if isinstance(node, exp.Column):
            return _coerce(_row_value(row, node.name))
        if isinstance(node, exp.Literal):
            return _coerce(self._eval_scalar(node))
        if isinstance(node, exp.Null):
            return None
        if isinstance(node, exp.Boolean):
            return 1 if node.this else 0
        if isinstance(node, exp.Neg):
            value = self._operand(node.this, row)
            try:
                return -value  # type: ignore[operator]
            except TypeError:
                return None
        raise _UnsupportedQuery(node.sql())

    @staticmethod
    def _compare(left: Any, right: Any, operator: str) -> bool:
        left = _coerce(left)
        right = _coerce(right)
        if operator == "eq":
            return left == right
        if operator == "ne":
            return left != right
        if left is None or right is None:
            return False
        try:
            if operator == "gt":
                return left > right
            if operator == "ge":
                return left >= right
            if operator == "lt":
                return left < right
            if operator == "le":
                return left <= right
        except TypeError:
            return False
        return False

    def _requested_columns(self, expression) -> list[tuple[str, str]] | None:
        """返回 [(查找列名, 输出列名)]；``SELECT *`` 或无表达式返回 None。"""
        if not isinstance(expression, exp.Select):
            return None
        items = expression.expressions or []
        if not items:
            return None
        result: list[tuple[str, str]] = []
        for item in items:
            node = item.this if isinstance(item, exp.Alias) else item
            if isinstance(node, exp.Star):
                return None
            if isinstance(node, exp.Column):
                output = item.alias_or_name or node.name
                result.append((node.name, output))
                continue
            raise _UnsupportedQuery(item.sql())
        return result

    def _aggregate_result(self, expression, rows: list[dict[str, Any]]):
        """支持单聚合查询（当前实现 COUNT(*) / COUNT(col)，演示与客户端常用）。"""
        if not isinstance(expression, exp.Select):
            return None
        items = expression.expressions or []
        if len(items) != 1:
            return None
        item = items[0]
        node = item.this if isinstance(item, exp.Alias) else item
        if not isinstance(node, exp.Count):
            return None
        target = node.this
        if isinstance(target, exp.Star):
            value = len(rows)
        elif isinstance(target, exp.Column):
            value = sum(1 for row in rows if _row_value(row, target.name) is not None)
        else:
            raise _UnsupportedQuery(item.sql())
        name = item.alias if isinstance(item, exp.Alias) else item.sql()
        return [(value,)], [name or "COUNT(*)"]

    @staticmethod
    def _parse_limit(sql: str) -> tuple[int | None, int]:
        """从原始 SQL 解析 LIMIT（支持 ``LIMIT n`` / ``LIMIT m,n`` / ``OFFSET``）。"""
        text = strip_sql_comments(sql)
        match = re.search(r"\blimit\s+(\d+)(?:\s*,\s*(\d+))?", text, flags=re.IGNORECASE)
        if not match:
            return None, 0
        if match.group(2) is not None:
            return int(match.group(2)), int(match.group(1))
        count = int(match.group(1))
        offset_match = re.search(
            r"\blimit\s+\d+\s+offset\s+(\d+)", text, flags=re.IGNORECASE
        )
        offset = int(offset_match.group(1)) if offset_match else 0
        return count, offset

    def _extract_table(self, expression, normalized: str) -> tuple[str, str] | None:
        if isinstance(expression, exp.Select):
            table_node = expression.find(exp.Table)
            if table_node is not None and table_node.name:
                database = _clean_identifier(table_node.db or table_node.catalog or "")
                return database, _clean_identifier(table_node.name)
        match = re.search(r"\bfrom\s+([`\"\w.]+)", normalized, flags=re.IGNORECASE)
        if match:
            name = _clean_identifier(match.group(1))
            if "." in name:
                db, _, table = name.partition(".")
                return db, table
            return "", name
        return None

    # ------------------------------------------------------------------
    # 伪造目录加载与行数
    # ------------------------------------------------------------------
    async def _ensure_catalog(self) -> None:
        if fake_catalog.is_loaded():
            return
        try:
            from app.db.session import get_ro_factory

            async with get_ro_factory()() as db:
                await fake_catalog.load_fake_schema(db)
        except Exception:  # noqa: BLE001 - 数据库不可达时降级为内置合成数据
            logger.exception("加载伪造库表数据失败，改用内置最小合成数据兜底")
            await fake_catalog.load_fake_schema(None)

    def _row_count(self, table_key: tuple[str, str]) -> int:
        if fake_catalog.is_loaded():
            return fake_catalog.row_count(table_key)
        return fake_catalog.EXPECTED_ROWS.get(table_key[1], 0)

    # ------------------------------------------------------------------
    # 连接信息与事件发射
    # ------------------------------------------------------------------
    def _resolve_peer(self, connection) -> None:
        peer: Any = None
        try:
            peer = connection.stream.writer.get_extra_info("peername")
        except Exception:  # noqa: BLE001 - 拿不到对端信息时使用占位值
            peer = None
        host = ""
        port: int | None = None
        if isinstance(peer, (tuple, list)) and peer:
            host = str(peer[0])
            if len(peer) > 1 and isinstance(peer[1], int):
                port = peer[1]
        elif isinstance(peer, str):
            host = peer
        host = host.strip().strip("[]").lower()
        if not host:
            host = "0.0.0.0"
        self._source_ip = host[:45]
        self._source_port = port

    def _external_username(self, connection) -> str | None:
        try:
            value = connection.session.variables.get("external_user")
        except Exception:  # noqa: BLE001
            value = None
        if value is None:
            return None
        return str(value)[:MAX_USERNAME_LENGTH]

    def _build_client_info(self, connection) -> str:
        attrs: dict[str, Any] = {}
        try:
            attrs = dict(getattr(connection, "client_connect_attrs", {}) or {})
        except Exception:  # noqa: BLE001
            attrs = {}
        client = attrs.get("_client_name") or attrs.get("client_name") or "unknown"
        version = attrs.get("_client_version") or attrs.get("client_version") or ""
        plugin = getattr(connection, "client_plugin_name", None) or "mysql_native_password"
        charset = self.variables.get("character_set_client")
        database = self.database or ""
        info = (
            f"client={str(client)[:40]}"
            f"{('/' + str(version)[:20]) if version else ''} "
            f"plugin={str(plugin)[:40]} db={database[:40]} charset={str(charset)[:20]}"
        )
        return info[:255]

    async def _emit(self, event: CapturedEvent) -> None:
        """发射事件；任何异常只记日志（协议响应不受影响）。"""
        try:
            await self._emitter.emit(event)
        except Exception:  # noqa: BLE001 - 双保险：发射器内部已捕获
            logger.exception(
                "会话事件发射异常：event_uuid=%s session_id=%s",
                getattr(event, "event_uuid", None),
                getattr(event, "session_id", None),
            )

    def _safe_parse(self, sql: str):
        """解析 SQL 为 AST；解析失败返回 None（路由仍按关键字兜底）。"""
        try:
            parsed = [item for item in self._parse(sql) if item]
        except Exception:  # noqa: BLE001 - 语法错误由路由统一返回 1064
            return None
        return parsed[0] if parsed else None


def _error_code_of(exc: MysqlError) -> int:
    """从 MysqlError 取整数错误码（上游 `code` 既可能是枚举也可能是 int）。"""
    code = getattr(exc, "code", None)
    try:
        return int(code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1105


__all__ = ["HoneypotSession"]
