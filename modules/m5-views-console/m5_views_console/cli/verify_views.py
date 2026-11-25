#!/usr/bin/env python3
"""M5 四个分析视图的只读核对 CLI（Spec Kit T048）。

功能分两部分，全部只读（`honeypot_app_ro` + `SET SESSION TRANSACTION READ ONLY`）：

1. **视图口径断言**（默认开启）：对四个视图执行 COUNT / 关键列非空 /
   口径一致性查询，例如
   - `v_session_risk_summary` 行数 = `sessions` 行数，且 `stored_max_risk_score`
     与 `calculated_risk_score` 无漂移；
   - `v_daily_attack_trend` 的每日事件数与 `attack_log` 按日聚合逐日同值，
     查询事件总数与 `attack_log` 的 `event_type='query'` 行数一致；
   - `v_attacker_profile_summary` 行数 = `attacker_profile` 行数，
     risk_level 与重算分数阈值一致且 stored/calculated 风险分无漂移；
   - `v_rule_effectiveness` 行数 = 规则编码数，命中/告警总数与明细表一致。
2. **`--check-pages`**：把数据库视图/表结果与页面 API 的关键数值逐项对比
   （overview、alerts/summary、attackers、attackers/{ip}），输出
   `db_value / api_value / ok`。

用法（仓库根）::

    PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console \
      /tmp/dbh-venv/bin/python -m m5_views_console.cli.verify_views --check-pages --json

参数：

- `--json`：以 JSON 输出完整报告（默认输出中文逐项文本）；
- `--check-pages`：追加数据库 ↔ 页面 API 的数值核对；
- `--base-url`：API 根地址，默认 `http://127.0.0.1:8000`（可省略 scheme）。

退出码：0 全部通过；1 存在断言失败；2 数据库或 API 连接错误。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.config import settings
from shared.db.session import get_ro_factory

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
HTTP_TIMEOUT_SECONDS = 10.0
VIEWS: tuple[str, ...] = (
    "v_session_risk_summary",
    "v_attacker_profile_summary",
    "v_daily_attack_trend",
    "v_rule_effectiveness",
)


class ApiUnavailableError(RuntimeError):
    """页面 API 不可达（连接错误 → 退出码 2）。"""


class DatabaseUnavailableError(RuntimeError):
    """数据库不可达（连接错误 → 退出码 2）。"""


@dataclass
class Check:
    """一条视图口径断言或页面核对项。"""

    group: str
    name: str
    sql: str
    db_value: Any
    expected: Any = None
    api_value: Any = None
    api: str = ""
    ok: bool = True
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "group": self.group,
            "name": self.name,
            "sql": " ".join(self.sql.split()),
            "db_value": self.db_value,
            "ok": self.ok,
        }
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.api_value is not None or self.api:
            payload["api_value"] = self.api_value
            payload["api"] = self.api
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class Report:
    """CLI 完整报告。"""

    started_at: str
    database: dict[str, Any]
    assertions: list[Check] = field(default_factory=list)
    page_checks: list[Check] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [item for item in [*self.assertions, *self.page_checks] if not item.ok]

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool": "m5_views_console.cli.verify_views",
            "checked_at": self.started_at,
            "database": self.database,
            "views": list(VIEWS),
            "assertions": [item.as_dict() for item in self.assertions],
            "summary": {
                "assertions_total": len(self.assertions),
                "assertions_passed": sum(1 for item in self.assertions if item.ok),
                "page_checks_total": len(self.page_checks),
                "page_checks_passed": sum(1 for item in self.page_checks if item.ok),
                "failed": [item.name for item in self.failed],
            },
            "result": "pass" if not self.failed else "fail",
        }
        if self.page_checks or self.page_errors:
            payload["page_checks"] = [item.as_dict() for item in self.page_checks]
            if self.page_errors:
                payload["page_errors"] = self.page_errors
        return payload


# ---------------------------------------------------------------------------
# 数据库侧：视图口径断言
# ---------------------------------------------------------------------------

#: (视图, 断言名, 期望值, SQL)。SQL 必须返回单标量，`db_value == expected` 即通过。
ASSERTION_SPECS: tuple[tuple[str, str, int, str], ...] = (
    (
        "v_session_risk_summary",
        "行数 = sessions 行数",
        0,
        "SELECT (SELECT COUNT(*) FROM v_session_risk_summary) - (SELECT COUNT(*) FROM sessions)",
    ),
    (
        "v_session_risk_summary",
        "主键/来源列无 NULL",
        0,
        "SELECT COUNT(*) FROM v_session_risk_summary "
        "WHERE session_id IS NULL OR source_ip IS NULL",
    ),
    (
        "v_session_risk_summary",
        "事件总数 = attack_log 行数",
        0,
        "SELECT (SELECT COALESCE(SUM(event_count), 0) FROM v_session_risk_summary) "
        "- (SELECT COUNT(*) FROM attack_log)",
    ),
    (
        "v_session_risk_summary",
        "重算风险分与存储分无漂移",
        0,
        "SELECT COUNT(*) FROM v_session_risk_summary "
        "WHERE stored_max_risk_score <> calculated_risk_score",
    ),
    (
        "v_attacker_profile_summary",
        "行数 = attacker_profile 行数",
        0,
        "SELECT (SELECT COUNT(*) FROM v_attacker_profile_summary) "
        "- (SELECT COUNT(*) FROM attacker_profile)",
    ),
    (
        "v_attacker_profile_summary",
        "画像/来源列无 NULL",
        0,
        "SELECT COUNT(*) FROM v_attacker_profile_summary "
        "WHERE attacker_id IS NULL OR source_ip IS NULL",
    ),
    (
        "v_attacker_profile_summary",
        "risk_level 与重算分数阈值一致",
        0,
        "SELECT COUNT(*) FROM v_attacker_profile_summary WHERE "
        "CASE WHEN calculated_risk_score >= 80 THEN 'critical' "
        "     WHEN calculated_risk_score >= 60 THEN 'high' "
        "     WHEN calculated_risk_score >= 30 THEN 'medium' "
        "     ELSE 'low' END <> risk_level",
    ),
    (
        "v_attacker_profile_summary",
        "重算风险分与存储分无漂移",
        0,
        "SELECT COUNT(*) FROM v_attacker_profile_summary "
        "WHERE stored_risk_score <> calculated_risk_score",
    ),
    (
        "v_daily_attack_trend",
        "行数 = attack_log 有事件日期数",
        0,
        "SELECT (SELECT COUNT(*) FROM v_daily_attack_trend) "
        "- (SELECT COUNT(DISTINCT DATE(event_time)) FROM attack_log)",
    ),
    (
        "v_daily_attack_trend",
        "日期列无 NULL",
        0,
        "SELECT COUNT(*) FROM v_daily_attack_trend WHERE stat_date IS NULL",
    ),
    (
        "v_daily_attack_trend",
        "逐日事件数与 attack_log 按日聚合同值",
        0,
        "SELECT "
        "  (SELECT COUNT(*) FROM ("
        "     SELECT DATE(event_time) AS d, COUNT(*) AS c FROM attack_log GROUP BY DATE(event_time)"
        "   ) AS l LEFT JOIN v_daily_attack_trend AS v ON v.stat_date = l.d"
        "   WHERE v.stat_date IS NULL OR v.event_count <> l.c) "
        "+ (SELECT COUNT(*) FROM v_daily_attack_trend AS v LEFT JOIN ("
        "     SELECT DATE(event_time) AS d, COUNT(*) AS c FROM attack_log GROUP BY DATE(event_time)"
        "   ) AS l ON l.d = v.stat_date WHERE l.d IS NULL)",
    ),
    (
        "v_daily_attack_trend",
        "查询事件总数 = attack_log 查询行数",
        0,
        "SELECT (SELECT COALESCE(SUM(query_count), 0) FROM v_daily_attack_trend) "
        "- (SELECT COUNT(*) FROM attack_log WHERE event_type = 'query')",
    ),
    (
        "v_rule_effectiveness",
        "行数 = 规则编码数",
        0,
        "SELECT (SELECT COUNT(*) FROM v_rule_effectiveness) "
        "- (SELECT COUNT(DISTINCT rule_code) FROM detection_rules)",
    ),
    (
        "v_rule_effectiveness",
        "规则编码无 NULL",
        0,
        "SELECT COUNT(*) FROM v_rule_effectiveness WHERE rule_code IS NULL",
    ),
    (
        "v_rule_effectiveness",
        "命中总数 = rule_hits 行数",
        0,
        "SELECT (SELECT COALESCE(SUM(hit_count), 0) FROM v_rule_effectiveness) "
        "- (SELECT COUNT(*) FROM rule_hits)",
    ),
    (
        "v_rule_effectiveness",
        "告警总数 = alerts 行数",
        0,
        "SELECT (SELECT COALESCE(SUM(alert_count), 0) FROM v_rule_effectiveness) "
        "- (SELECT COUNT(*) FROM alerts)",
    ),
)


async def _scalar(session: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> Any:
    """执行单值查询并规整返回类型。"""
    return normalize_scalar(
        (await session.execute(text(sql), params or {})).scalar_one()
    )


def normalize_scalar(value: Any) -> Any:
    """把 bool/Decimal 规整成 int/float，便于与 API JSON 严格比较。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


async def run_assertions(session: AsyncSession) -> list[Check]:
    """执行全部视图口径断言。"""
    checks: list[Check] = []
    for view, name, expected, sql in ASSERTION_SPECS:
        try:
            value = await _scalar(session, sql)
            checks.append(
                Check(
                    group=view,
                    name=name,
                    sql=sql,
                    db_value=value,
                    expected=expected,
                    ok=value == expected,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单条失败记录后继续跑其余断言
            checks.append(
                Check(
                    group=view,
                    name=name,
                    sql=sql,
                    db_value=None,
                    expected=expected,
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    return checks


# ---------------------------------------------------------------------------
# 页面侧：数据库 ↔ API 数值核对
# ---------------------------------------------------------------------------


def normalize_base_url(raw: str) -> str:
    """规范化 API 根地址：允许省略 scheme 与尾部斜杠。"""
    value = raw.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    parsed = urllib.parse.urlparse(value)
    if not parsed.netloc:
        raise ValueError(f"非法 base URL：{raw!r}")
    return value


def http_json(url: str) -> dict[str, Any]:
    """GET 一个 JSON 端点；网络/HTTP/解析错误统一视为 API 不可达。"""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiUnavailableError(f"GET {url} 失败：{exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ApiUnavailableError(f"GET {url} 返回非 JSON：{exc}") from exc


def _sql_upper(value: str | None) -> str:
    """把 API 的 ISO8601 UTC 时刻转成 MySQL DATETIME 字符串（用于同口径过滤）。"""
    if not value:
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _ratio(parts: int, total: int) -> float:
    """与 API 契约一致的比率（分母 0 → 0.0，保留 4 位）。"""
    return 0.0 if total == 0 else round(parts / total, 4)


async def _page_check(
    session: AsyncSession,
    checks: list[Check],
    *,
    group: str,
    name: str,
    sql: str,
    api_value: Any,
    api: str,
    params: dict[str, Any] | None = None,
    expected: Any = None,
    tolerance: float = 0.0,
) -> None:
    """执行一条 DB 查询并与 API 值比较（默认与 API 值严格相等）。"""
    try:
        db_value = await _scalar(session, sql, params)
    except Exception as exc:  # noqa: BLE001 - 单条失败记录后继续
        checks.append(
            Check(
                group=group,
                name=name,
                sql=sql,
                db_value=None,
                expected=api_value if expected is None else expected,
                api_value=api_value,
                api=api,
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        return
    target = api_value if expected is None else expected
    if tolerance:
        try:
            ok = abs(float(db_value) - float(target)) <= tolerance
        except (TypeError, ValueError):
            ok = db_value == target
    else:
        ok = db_value == target
    checks.append(
        Check(
            group=group,
            name=name,
            sql=sql,
            db_value=db_value,
            expected=target,
            api_value=api_value,
            api=api,
            ok=ok,
        )
    )


async def run_page_checks(session: AsyncSession, base_url: str) -> list[Check]:
    """数据库视图/表结果 vs 页面四类 API 的关键数值。"""
    checks: list[Check] = []
    overview_url = f"{base_url}/api/overview?range=all"
    summary_url = f"{base_url}/api/alerts/summary"
    attackers_url = f"{base_url}/api/attackers?page_size=1"
    summary_attackers_url = f"{base_url}/api/attackers/summary"

    overview = http_json(overview_url)
    alerts = http_json(summary_url)
    attackers = http_json(attackers_url)
    attacker_summary = http_json(summary_attackers_url)

    upper = _sql_upper(overview.get("generated_at"))
    alerts_upper = _sql_upper(alerts.get("generated_at"))
    window_params = {"upper": upper}

    # ---- 1. 概览 KPI（页面 #/） ----
    await _page_check(
        session,
        checks,
        group="overview",
        name="sessions（页面「连接数」）",
        sql="SELECT COUNT(*) FROM sessions WHERE started_at <= :upper",
        api_value=overview.get("sessions"),
        api="GET /api/overview?range=all",
        params=window_params,
    )
    await _page_check(
        session,
        checks,
        group="overview",
        name="queries（页面「查询数」）",
        sql="SELECT COUNT(*) FROM attack_log WHERE event_type = 'query' AND event_time <= :upper",
        api_value=overview.get("queries"),
        api="GET /api/overview?range=all",
        params=window_params,
    )
    await _page_check(
        session,
        checks,
        group="overview",
        name="alerts（概览告警总数）",
        sql="SELECT COUNT(*) FROM alerts WHERE created_at <= :upper",
        api_value=overview.get("alerts"),
        api="GET /api/overview?range=all",
        params=window_params,
    )
    await _page_check(
        session,
        checks,
        group="overview",
        name="high_risk_attackers（页面「高风险攻击者」）",
        sql="SELECT COUNT(*) FROM v_attacker_profile_summary "
        "WHERE risk_level IN ('high', 'critical') AND last_seen <= :upper",
        api_value=overview.get("high_risk_attackers"),
        api="GET /api/overview?range=all",
        params=window_params,
    )
    await _page_check(
        session,
        checks,
        group="overview",
        name="attackers_total（页面「/ N 总量」）",
        sql="SELECT COUNT(*) FROM v_attacker_profile_summary WHERE last_seen <= :upper",
        api_value=overview.get("attackers_total"),
        api="GET /api/overview?range=all",
        params=window_params,
    )
    await _page_check(
        session,
        checks,
        group="overview",
        name="alerts_unread（页面「未处理告警」）",
        sql="SELECT COALESCE(SUM(is_read = 0), 0) FROM alerts WHERE created_at <= :upper",
        api_value=overview.get("alerts_unread"),
        api="GET /api/overview?range=all",
        params=window_params,
    )

    # ---- 2. 告警统计（页面 #/alerts 顶部统计卡） ----
    alert_params = {"upper": alerts_upper}
    await _page_check(
        session,
        checks,
        group="alerts",
        name="total（页面「告警总数」）",
        sql="SELECT COUNT(*) FROM alerts WHERE created_at < :upper",
        api_value=alerts.get("total"),
        api="GET /api/alerts/summary",
        params=alert_params,
    )
    await _page_check(
        session,
        checks,
        group="alerts",
        name="unread（页面「未读告警」）",
        sql="SELECT COALESCE(SUM(is_read = 0), 0) FROM alerts WHERE created_at < :upper",
        api_value=alerts.get("unread"),
        api="GET /api/alerts/summary",
        params=alert_params,
    )
    await _page_check(
        session,
        checks,
        group="alerts",
        name="read（页面「已读 / 共」的已读）",
        sql="SELECT COUNT(*) - COALESCE(SUM(is_read = 0), 0) FROM alerts "
        "WHERE created_at < :upper",
        api_value=alerts.get("read"),
        api="GET /api/alerts/summary",
        params=alert_params,
    )
    resolution = _ratio(int(alerts.get("read") or 0), int(alerts.get("total") or 0))
    await _page_check(
        session,
        checks,
        group="alerts",
        name="resolution_rate（页面「处置完成率」）",
        sql="SELECT CASE WHEN COUNT(*) = 0 THEN 0.0000 "
        "ELSE ROUND((COUNT(*) - COALESCE(SUM(is_read = 0), 0)) / COUNT(*), 4) END "
        "FROM alerts WHERE created_at < :upper",
        api_value=alerts.get("resolution_rate"),
        api="GET /api/alerts/summary",
        params=alert_params,
        expected=resolution,
        tolerance=0.0001,
    )

    # ---- 3. 攻击者列表（页面 #/attackers） ----
    await _page_check(
        session,
        checks,
        group="attackers",
        name="total（页面「/ N IP」与列表总数）",
        sql="SELECT COUNT(*) FROM v_attacker_profile_summary",
        api_value=attackers.get("total"),
        api="GET /api/attackers?page_size=1",
    )
    await _page_check(
        session,
        checks,
        group="attackers",
        name="high_risk_count（页面「高危及严重攻击源」）",
        sql="SELECT COALESCE(SUM(risk_level IN ('high', 'critical')), 0) "
        "FROM v_attacker_profile_summary",
        api_value=attacker_summary.get("high_risk_count"),
        api="GET /api/attackers/summary",
    )
    first_item = (attackers.get("items") or [{}])[0]
    first_ip = first_item.get("source_ip")
    if first_ip:
        await _page_check(
            session,
            checks,
            group="attackers",
            name=f"首行 {first_ip} risk_score",
            sql="SELECT stored_risk_score FROM v_attacker_profile_summary WHERE source_ip = :ip",
            api_value=first_item.get("risk_score"),
            api="GET /api/attackers?page_size=1",
            params={"ip": first_ip},
        )
        await _page_check(
            session,
            checks,
            group="attackers",
            name=f"首行 {first_ip} total_connections",
            sql="SELECT total_connections FROM v_attacker_profile_summary WHERE source_ip = :ip",
            api_value=first_item.get("total_connections"),
            api="GET /api/attackers?page_size=1",
            params={"ip": first_ip},
        )
        await _page_check(
            session,
            checks,
            group="attackers",
            name=f"首行 {first_ip} total_queries",
            sql="SELECT total_queries FROM v_attacker_profile_summary WHERE source_ip = :ip",
            api_value=first_item.get("total_queries"),
            api="GET /api/attackers?page_size=1",
            params={"ip": first_ip},
        )

        # ---- 4. 攻击者详情（页面 #/attackers/:ip） ----
        detail_url = f"{base_url}/api/attackers/{urllib.parse.quote(first_ip)}"
        detail = http_json(detail_url)
        profile = detail.get("attacker") or {}
        detail_params = {"ip": first_ip}
        for name, field_name in (
            ("total_connections（累计会话）", "total_connections"),
            ("total_queries（执行查询）", "total_queries"),
            ("session_count（页面「累计会话」）", "session_count"),
            ("risk_score（页面「综合风险分」）", "risk_score"),
            ("alert_count（告警数）", "alert_count"),
        ):
            column = "stored_risk_score" if field_name == "risk_score" else field_name
            await _page_check(
                session,
                checks,
                group="attacker-detail",
                name=f"{first_ip} {name}",
                sql=f"SELECT {column} FROM v_attacker_profile_summary WHERE source_ip = :ip",
                api_value=profile.get(field_name),
                api=f"GET /api/attackers/{first_ip}",
                params=detail_params,
            )
        # 详情页会话摘要来自 v_session_risk_summary：核对「会话数」与视图行数
        await _page_check(
            session,
            checks,
            group="attacker-detail",
            name=f"{first_ip} v_session_risk_summary 会话行数",
            sql="SELECT COUNT(*) FROM v_session_risk_summary WHERE source_ip = :ip",
            api_value=len(detail.get("sessions") or []),
            api=f"GET /api/attackers/{first_ip}",
            params=detail_params,
            expected=profile.get("session_count"),
        )
    return checks


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def mask_url(raw: str) -> dict[str, Any]:
    """连接串脱敏描述（不输出口令）。"""
    url = make_url(raw)
    return {
        "driver": url.drivername,
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "account": url.username,
        "read_only": True,
    }


def connect_readonly() -> async_sessionmaker[AsyncSession]:
    """返回只读会话工厂；首次连接失败由 `_run` 统一处理。"""
    return get_ro_factory()


async def _run(args: argparse.Namespace) -> Report:
    """执行断言与（可选）页面核对，返回报告。"""
    base_url = normalize_base_url(args.base_url)
    factory = connect_readonly()
    report = Report(
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        database=mask_url(settings.readonly_database_url),
    )
    async with factory() as session:
        try:
            await session.execute(text("SET SESSION TRANSACTION READ ONLY"))
            await _scalar(session, "SELECT 1")
        except Exception as exc:  # noqa: BLE001 - 连接阶段失败 → 退出码 2
            raise DatabaseUnavailableError(f"{type(exc).__name__}: {exc}") from exc
        report.assertions = await run_assertions(session)
        if args.check_pages:
            report.page_checks = await run_page_checks(session, base_url)
        await session.rollback()
    return report


def render_text(report: Report) -> str:
    """人类可读的中文报告。"""
    lines = [
        "M5 视图核对（只读）",
        f"检查时间（UTC）：{report.started_at}",
        f"数据库：{report.database['account']}@{report.database['host']}:"
        f"{report.database['port']}/{report.database['database']}（只读）",
        "",
        f"一、视图口径断言（{len(report.assertions)} 项）",
    ]
    current_group = ""
    for item in report.assertions:
        if item.group != current_group:
            current_group = item.group
            lines.append(f"  [{current_group}]")
        status = "PASS" if item.ok else "FAIL"
        suffix = f"（{item.detail}）" if item.detail else ""
        lines.append(
            f"    {status} {item.name}：db={item.db_value} expected={item.expected}{suffix}"
        )
    if report.page_checks:
        lines.append("")
        lines.append(f"二、数据库 ↔ 页面 API 核对（{len(report.page_checks)} 项）")
        current_group = ""
        for item in report.page_checks:
            if item.group != current_group:
                current_group = item.group
                lines.append(f"  [{current_group}]")
            status = "PASS" if item.ok else "FAIL"
            lines.append(
                f"    {status} {item.name}：db={item.db_value} api={item.api_value} "
                f"（{item.api}）"
            )
    lines.append("")
    lines.append(
        f"结论：{'全部通过' if not report.failed else f'存在 {len(report.failed)} 项失败'} "
        f"（断言 {sum(1 for item in report.assertions if item.ok)}/{len(report.assertions)}，"
        f"页面核对 {sum(1 for item in report.page_checks if item.ok)}/{len(report.page_checks)}）"
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="verify_views",
        description="M5 四个分析视图的只读核对 CLI（口径断言 + 页面 API 对比）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出完整报告")
    parser.add_argument(
        "--check-pages",
        action="store_true",
        help="追加数据库视图结果与页面 API 关键数值的对比",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"页面 API 根地址，默认 {DEFAULT_BASE_URL}（可省略 http://）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口；返回进程退出码。"""
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(_run(args))
    except ApiUnavailableError as exc:
        print(f"[连接错误] 页面 API 不可达：{exc}", file=sys.stderr)
        return 2
    except DatabaseUnavailableError as exc:
        print(f"[连接错误] 数据库不可达：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
