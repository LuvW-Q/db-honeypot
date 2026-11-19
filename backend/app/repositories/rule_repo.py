"""规则配置仓储：列表（每编码最新版本）、按编码生成新版本、规则效果统计。

设计对齐 contracts/api.md 3.8/3.9/3.11 与 data-model 4.5/10.3：

- `detection_rules` 采用“同一 `rule_code` 多行版本”存储，当前生效版本 = 最大 `rule_version`；
- 规则变更在单事务内完成：`SELECT ... FOR UPDATE` → 校验乐观版本 → 旧版本 `enabled=0`
  → 插入新版本 → 写审计 → 提交；任一步失败整体回滚；
- 历史版本行冻结保留，`rule_hits` 保存命中时的版本与权重快照（FR-052/SC-004）。

写函数使用应用读写会话（`DB`），由本模块显式 `commit`；只读函数不提交事务。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.audit_repo import write_audit
from app.repositories.query_repo import fetch_all, fetch_one, fetch_scalar
from app.schemas.api import conflict, not_found, unprocessable

#: 规则行对外列（`parameters_json` 在映射层解析为 `parameters`）
RULE_COLUMNS = """
SELECT d.rule_id,
       d.rule_code,
       d.rule_name,
       d.rule_type,
       d.intent_type,
       d.parameters_json,
       d.risk_weight,
       d.rule_version,
       d.enabled,
       d.description,
       d.created_at,
       d.updated_at
FROM detection_rules AS d
"""

#: 每个 rule_code 的当前版本（最大 rule_version）
LATEST_JOIN = """
JOIN (
    SELECT rule_code, MAX(rule_version) AS max_version
    FROM detection_rules
    GROUP BY rule_code
) AS latest
  ON latest.rule_code = d.rule_code
 AND latest.max_version = d.rule_version
"""

#: 规则效果视图查询（契约 3.11）
EFFECTIVENESS_SQL = """
SELECT rule_code,
       rule_name,
       rule_type,
       intent_type,
       risk_weight,
       current_version,
       is_enabled,
       hit_count,
       affected_session_count,
       affected_event_count,
       affected_attacker_count,
       used_version_count,
       first_hit_at,
       last_hit_at,
       alert_count,
       unread_alert_count,
       alert_per_hit_ratio,
       hit_rank
FROM v_rule_effectiveness
ORDER BY hit_rank ASC, rule_code ASC
LIMIT :_limit
"""

#: 规则参数模式（data-model 10.2）：键 -> (类型, 约束)
#: `int` 约束为闭区间 (min, max)；`str` 约束为允许值元组；`str_list` 约束为 None 或允许值元组。
_RULE_PARAMETER_SPECS: dict[str, dict[str, tuple[str, Any]]] = {
    "R01": {
        "scope": ("str", ("source_ip",)),
        "window_seconds": ("int", (1, 86400)),
        "min_connect_count": ("int", (1, 100000)),
        "max_valid_sql_count": ("int", (0, 100000)),
        "boundary": ("str", ("inclusive", "exclusive")),
    },
    "R02": {
        "scope": ("str", ("source_ip",)),
        "window_seconds": ("int", (1, 86400)),
        "min_auth_attempts": ("int", (1, 100000)),
        "min_distinct_credential_pairs": ("int", (1, 100000)),
        "count_failed_only": ("bool", None),
    },
    "R03": {
        "scope": ("str", ("event",)),
        "match_target": ("str", ("normalized_sql", "sql_statement")),
        "case_sensitive": ("bool", None),
        "keywords": ("str_list", None),
        "max_hits_per_event": ("int", (1, 100)),
    },
    "R04": {
        "scope": ("str", ("session", "source_ip")),
        "window_seconds": ("int", (1, 86400)),
        "min_consecutive_select": ("int", (1, 100000)),
        "session_returned_rows_threshold": ("int", (1, 100000000)),
        "count_scope": ("str", ("session_cumulative", "window")),
    },
    "R05": {
        "scope": ("str", ("event",)),
        "match_target": ("str", ("normalized_sql", "sql_statement")),
        "case_sensitive": ("bool", None),
        "word_boundary": ("bool", None),
        "keywords": ("str_list", None),
        "count_status": ("str_list", ("success", "failure", "denied", "error")),
    },
}


def _parse_parameters(raw: Any) -> dict[str, Any]:
    """把数据库 JSON 列解析成 dict（驱动可能返回字符串）。"""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:  # pragma: no cover - 数据库 JSON 列保证合法
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(raw, dict):
        return raw
    return {}


def _to_rule_row(row: dict[str, Any]) -> dict[str, Any]:
    """把数据库行映射为契约字段（`parameters_json` -> `parameters`）。"""
    return {
        "rule_id": row["rule_id"],
        "rule_code": row["rule_code"],
        "rule_name": row["rule_name"],
        "rule_type": row["rule_type"],
        "intent_type": row["intent_type"],
        "parameters": _parse_parameters(row.get("parameters_json")),
        "risk_weight": row["risk_weight"],
        "rule_version": row["rule_version"],
        "enabled": bool(row["enabled"]),
        "description": row.get("description"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _param_error(field: str, reason: str, value: Any = None) -> Exception:
    """构造规则参数校验失败（422 VALIDATION_ERROR，契约 3.9）。"""
    detail: dict[str, Any] = {"field": field, "reason": reason}
    if value is not None:
        detail["input"] = str(value)[:64]
    return unprocessable("VALIDATION_ERROR", "规则参数校验失败", detail)


def validate_rule_parameters(rule_code: str, parameters: dict[str, Any]) -> None:
    """按 `rule_code` 的参数模式做结构化校验（未知键/类型/范围非法均 422）。

    对未定义模式的规则编码（未来新增 R06-R08）只要求是 JSON 对象，避免阻塞扩展。
    """
    if not isinstance(parameters, dict):
        raise _param_error("parameters", "必须是 JSON 对象")
    spec = _RULE_PARAMETER_SPECS.get(rule_code)
    if spec is None:
        return

    unknown = sorted(set(parameters) - set(spec))
    if unknown:
        raise _param_error(f"parameters.{unknown[0]}", "未知参数键", unknown[0])
    missing = sorted(set(spec) - set(parameters))
    if missing:
        raise _param_error(f"parameters.{missing[0]}", "缺少必需参数", missing[0])

    for key, (kind, constraint) in spec.items():
        value = parameters[key]
        field = f"parameters.{key}"
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise _param_error(field, "必须是整数", value)
            minimum, maximum = constraint
            if not minimum <= value <= maximum:
                raise _param_error(field, f"必须在 {minimum}..{maximum} 之间", value)
        elif kind == "bool":
            if not isinstance(value, bool):
                raise _param_error(field, "必须是布尔值", value)
        elif kind == "str":
            if not isinstance(value, str) or value not in constraint:
                raise _param_error(
                    field, f"必须是 {'/'.join(constraint)} 之一", value
                )
        elif kind == "str_list":
            if not isinstance(value, list) or not value:
                raise _param_error(field, "必须是非空字符串数组", value)
            if any(not isinstance(item, str) or not item for item in value):
                raise _param_error(field, "数组元素必须是非空字符串", value)
            if constraint is not None:
                invalid = [item for item in value if item not in constraint]
                if invalid:
                    allowed_text = "/".join(constraint)
                    raise _param_error(field, f"取值必须是 {allowed_text} 的子集", invalid[0])


async def list_rules(
    session: AsyncSession,
    *,
    include_history: bool = False,
    enabled: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """查询规则列表；默认每个 `rule_code` 只返回当前（最大版本）行。

    `include_history=true` 时返回全部版本，按 `rule_code ASC, rule_version DESC`。
    """
    where = ""
    params: dict[str, Any] = {}
    if enabled is not None:
        where = "WHERE d.enabled = :enabled"
        params["enabled"] = 1 if enabled else 0

    if include_history:
        items_sql = f"{RULE_COLUMNS}\n{where}\nORDER BY d.rule_code ASC, d.rule_version DESC"
    else:
        items_sql = (
            f"{RULE_COLUMNS}\n{LATEST_JOIN}\n{where}\n"
            "ORDER BY d.rule_code ASC, d.rule_version DESC"
        )
    count_sql = f"SELECT COUNT(*) FROM (\n{items_sql}\n) AS rule_rows"
    rows = await fetch_all(session, items_sql, params)
    total = int(await fetch_scalar(session, count_sql, params) or 0)
    return [_to_rule_row(row) for row in rows], total


async def get_latest_rule(
    session: AsyncSession,
    rule_code: str,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    """取某规则编码的当前版本行（可选行锁，供写事务使用）。"""
    lock = " FOR UPDATE" if for_update else ""
    row = await fetch_one(
        session,
        f"{RULE_COLUMNS}\nWHERE d.rule_code = :rule_code\n"
        f"ORDER BY d.rule_version DESC\nLIMIT 1{lock}",
        {"rule_code": rule_code},
    )
    return _to_rule_row(row) if row is not None else None


async def get_rule_by_id(session: AsyncSession, rule_id: int) -> dict[str, Any] | None:
    """按规则行主键取版本行（PATCH 成功后返回新版本对象）。"""
    row = await fetch_one(
        session, f"{RULE_COLUMNS}\nWHERE d.rule_id = :rule_id", {"rule_id": rule_id}
    )
    return _to_rule_row(row) if row is not None else None


async def _disable_rule_row(session: AsyncSession, rule_id: int) -> None:
    """冻结旧版本：`enabled=0`（必须先于插入新启用版本，满足唯一约束顺序，契约 3.9）。"""
    await session.execute(
        text("UPDATE detection_rules SET enabled = 0 WHERE rule_id = :rule_id"),
        {"rule_id": rule_id},
    )


async def _insert_rule_version(
    session: AsyncSession,
    *,
    rule_code: str,
    rule_name: str,
    rule_type: str,
    intent_type: str,
    parameters: dict[str, Any],
    risk_weight: int,
    rule_version: int,
    enabled: bool,
    description: str | None,
) -> int:
    """插入新版本行并返回新 `rule_id`（时间取事务内数据库 UTC 时间）。"""
    sql = """
    INSERT INTO detection_rules
        (rule_code, rule_name, rule_type, intent_type, parameters_json,
         risk_weight, rule_version, enabled, description, created_at, updated_at)
    VALUES
        (:rule_code, :rule_name, :rule_type, :intent_type, :parameters_json,
         :risk_weight, :rule_version, :enabled, :description,
         UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
    """
    await session.execute(
        text(sql),
        {
            "rule_code": rule_code,
            "rule_name": rule_name,
            "rule_type": rule_type,
            "intent_type": intent_type,
            "parameters_json": json.dumps(parameters, ensure_ascii=False, separators=(",", ":")),
            "risk_weight": risk_weight,
            "rule_version": rule_version,
            "enabled": 1 if enabled else 0,
            "description": description,
        },
    )
    new_id = await fetch_scalar(session, "SELECT LAST_INSERT_ID()")
    return int(new_id or 0)


async def update_rule(
    session: AsyncSession,
    rule_code: str,
    *,
    enabled: bool | None,
    parameters: dict[str, Any] | None,
    risk_weight: int | None,
    expected_version: int | None,
    change_reason: str | None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """在单事务内生成规则新版本，返回新版本对象（附带 `previous_version`）。

    事务步骤（契约 3.9 / data-model 10.3 T3）：

    1. `SELECT ... FOR UPDATE` 读当前最大版本行；
    2. 校验 `expected_version`（不一致 409 RULE_VERSION_CONFLICT）；
    3. 合并并校验参数（未知键/类型/范围非法 422）；
    4. 旧版本 `enabled=0`；
    5. 插入新版本（未提供字段从当前版本复制）；
    6. 写审计 `rule_change`；
    7. 提交；任一步失败整体回滚，不产生半成品版本。
    """
    try:
        current = await get_latest_rule(session, rule_code, for_update=True)
        if current is None:
            raise not_found(
                "RULE_NOT_FOUND", "未找到规则", {"rule_code": rule_code}
            )
        if expected_version is not None and expected_version != current["rule_version"]:
            raise conflict(
                "RULE_VERSION_CONFLICT",
                "规则已被修改，请刷新后重试",
                {
                    "rule_code": rule_code,
                    "expected_version": expected_version,
                    "current_version": current["rule_version"],
                },
            )

        merged_parameters = dict(current["parameters"])
        if parameters is not None:
            merged_parameters.update(parameters)
        validate_rule_parameters(rule_code, merged_parameters)

        new_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        new_weight = current["risk_weight"] if risk_weight is None else risk_weight
        new_version = int(current["rule_version"]) + 1

        await _disable_rule_row(session, int(current["rule_id"]))
        new_rule_id = await _insert_rule_version(
            session,
            rule_code=rule_code,
            rule_name=current["rule_name"],
            rule_type=current["rule_type"],
            intent_type=current["intent_type"],
            parameters=merged_parameters,
            risk_weight=int(new_weight),
            rule_version=new_version,
            enabled=new_enabled,
            description=current.get("description"),
        )

        changed_fields = [
            name
            for name, value in (
                ("enabled", enabled),
                ("parameters", parameters),
                ("risk_weight", risk_weight),
            )
            if value is not None
        ]
        await write_audit(
            session,
            operation="rule_change",
            target_table="detection_rules",
            target_key=rule_code,
            detail=(
                f"规则 {rule_code} 由 v{current['rule_version']} 更新为 v{new_version}，"
                f"变更字段：{','.join(changed_fields) or '无'}；"
                f"原因：{(change_reason or '未提供')[:150]}"
            ),
            request_id=request_id,
        )

        new_row = await get_rule_by_id(session, new_rule_id)
        if new_row is None:  # pragma: no cover - 插入后同事务内必然可见
            raise unprocessable("DATA_INCONSISTENT", "规则新版本写入后不可见")
        new_row["previous_version"] = int(current["rule_version"])
        await session.commit()
        return new_row
    except Exception:
        await session.rollback()
        raise


async def list_rule_effectiveness(
    session: AsyncSession,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """查询规则效果视图（按 `hit_rank ASC`），返回行与 total。"""
    rows = await fetch_all(session, EFFECTIVENESS_SQL, {"_limit": limit})
    total = int(await fetch_scalar(session, "SELECT COUNT(*) FROM v_rule_effectiveness") or 0)
    return rows, total
