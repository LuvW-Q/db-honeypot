"""R01 短时高频连接扫描（frequency / scanning，权重 10）。

判定口径（data-model 10.2）：

- 统计范围：同一 `source_ip`；
- 时间窗口：当前事件 `event_time` 向前回溯 `window_seconds`（默认 60 秒，含当前事件）；
- 命中条件：窗口内 `connect` 事件数 `>= min_connect_count`（默认 10），
  且窗口内“有效 SQL”（`event_type='query' AND status='success'`）数量
  `<= max_valid_sql_count`（默认 0）；
- 仅对 `connect` 事件判定，避免同一批扫描在后续 auth/query 事件上重复刷命中
  （即使重复命中，会话分也按 rule_code 去重，只计一次权重）。
"""

from __future__ import annotations

from sqlalchemy import text

from m4_rules_derived.rules.base import (
    RuleContext,
    RuleHitCandidate,
    register,
    safe_int,
    window_range,
)


@register("R01")
async def evaluate(ctx: RuleContext) -> RuleHitCandidate | None:
    """判定本事件是否构成“短时高频连接扫描”。"""
    event = ctx.event_row
    if str(getattr(event, "event_type", "")) != "connect":
        return None

    params = ctx.parameters
    window_seconds = safe_int(params.get("window_seconds"), 60)
    min_connect_count = safe_int(params.get("min_connect_count"), 10)
    max_valid_sql_count = safe_int(params.get("max_valid_sql_count"), 0)
    start, end = window_range(ctx.event_time, window_seconds)

    row = (
        await ctx.db.execute(
            text(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN event_type = 'connect' THEN 1 ELSE 0 END), 0)
                        AS connect_count,
                    COALESCE(SUM(CASE WHEN event_type = 'query' AND status = 'success'
                                      THEN 1 ELSE 0 END), 0)
                        AS valid_sql_count
                FROM attack_log
                WHERE source_ip = :source_ip
                  AND event_time >= :window_start
                  AND event_time <= :window_end
                """
            ),
            {
                "source_ip": ctx.source_ip,
                "window_start": start,
                "window_end": end,
            },
        )
    ).one()
    connect_count = safe_int(row.connect_count, 0)
    valid_sql_count = safe_int(row.valid_sql_count, 0)

    if connect_count < min_connect_count:
        return None
    if valid_sql_count > max_valid_sql_count:
        return None

    summary = (
        f"{window_seconds} 秒内同一来源连接 {connect_count} 次"
        f"（阈值 {min_connect_count}），有效 SQL {valid_sql_count} 条"
        f"（上限 {max_valid_sql_count}），符合扫描特征"
    )
    return RuleHitCandidate(
        rule_code=ctx.rule_code,
        intent_type="scanning",
        risk_weight=10,
        evidence_summary=summary[:1024],
        details={
            "window_seconds": window_seconds,
            "connect_count": connect_count,
            "valid_sql_count": valid_sql_count,
            "min_connect_count": min_connect_count,
            "max_valid_sql_count": max_valid_sql_count,
        },
    )
