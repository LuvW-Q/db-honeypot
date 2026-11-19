"""R04 会话级批量数据读取（volume / data_dump，权重 25）。

判定口径（data-model 10.2，阈值按本任务约定使用 10 / 500 作为缺省值）：

- 统计范围：同一 `session_id`；
- 条件 A（连续 SELECT）：最近 `window_seconds`（默认 300 秒）内，
  从当前事件向前连续出现的 `SELECT` 查询数量 `>= min_consecutive_select`
  （默认 10，若参数存在则取 `parameters_json` 配置值），遇到非 SELECT 查询、
  auth/connect 等事件即中断；
- 条件 B（累计行数）：本会话累计 `returned_rows` `> session_returned_rows_threshold`（严格大于）
  （默认 500；口径为整会话累计，不受窗口限制）；
- 满足任一条件即命中；仅对 `query` 事件判定。
"""

from __future__ import annotations

from sqlalchemy import text

from app.services.rules.base import (
    RuleContext,
    RuleHitCandidate,
    event_sql_text,
    is_select_statement,
    register,
    safe_int,
    window_range,
)

# 连续 SELECT 扫描上限：避免异常会话导致分析阶段读取过多行
_MAX_SCAN_ROWS = 1000


@register("R04")
async def evaluate(ctx: RuleContext) -> RuleHitCandidate | None:
    """判定本事件是否构成“会话级批量数据读取”。"""
    event = ctx.event_row
    if str(getattr(event, "event_type", "")) != "query":
        return None
    # 仅 SELECT 查询参与“批量读取”判定，避免 SHOW/DROP 等查询被会话累计行数条件误命中
    if not is_select_statement(event_sql_text(event)):
        return None

    session_id = str(getattr(event, "session_id", "") or "")
    if not session_id:
        return None

    params = ctx.parameters
    window_seconds = safe_int(params.get("window_seconds"), 300)
    min_consecutive_select = safe_int(params.get("min_consecutive_select"), 10)
    rows_threshold = safe_int(params.get("session_returned_rows_threshold"), 500)
    start, end = window_range(ctx.event_time, window_seconds)

    # ---- 条件 A：窗口内连续 SELECT ----
    recent_rows = (
        await ctx.db.execute(
            text(
                """
                SELECT event_type, normalized_sql, sql_statement
                FROM attack_log
                WHERE session_id = :session_id
                  AND event_time >= :window_start
                  AND event_time <= :window_end
                ORDER BY event_time DESC, event_id DESC
                LIMIT :scan_limit
                """
            ),
            {
                "session_id": session_id,
                "window_start": start,
                "window_end": end,
                "scan_limit": _MAX_SCAN_ROWS,
            },
        )
    ).all()

    consecutive_select = 0
    for row in recent_rows:
        if str(row.event_type or "") != "query":
            break
        sql = str(row.normalized_sql or row.sql_statement or "")
        if not is_select_statement(sql):
            break
        consecutive_select += 1

    # ---- 条件 B：会话累计返回行数 ----
    total_returned_rows = safe_int(
        (
            await ctx.db.execute(
                text(
                    """
                    SELECT COALESCE(SUM(returned_rows), 0) AS total_returned_rows
                    FROM attack_log
                    WHERE session_id = :session_id
                    """
                ),
                {"session_id": session_id},
            )
        ).scalar(),
        0,
    )

    hit_by_select = consecutive_select >= min_consecutive_select
    hit_by_rows = total_returned_rows > rows_threshold
    if not (hit_by_select or hit_by_rows):
        return None

    reasons: list[str] = []
    if hit_by_select:
        reasons.append(
            f"{window_seconds} 秒内连续 SELECT {consecutive_select} 次（阈值 {min_consecutive_select}）"
        )
    if hit_by_rows:
        reasons.append(
            f"会话累计返回 {total_returned_rows} 行（阈值 {rows_threshold}）"
        )
    summary = "；".join(reasons) + "，符合批量拖库特征"

    return RuleHitCandidate(
        rule_code=ctx.rule_code,
        intent_type="data_dump",
        risk_weight=25,
        evidence_summary=summary[:1024],
        details={
            "window_seconds": window_seconds,
            "consecutive_select": consecutive_select,
            "min_consecutive_select": min_consecutive_select,
            "total_returned_rows": total_returned_rows,
            "session_returned_rows_threshold": rows_threshold,
            "hit_by_select": hit_by_select,
            "hit_by_rows": hit_by_rows,
        },
    )
