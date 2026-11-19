"""R02 短时多凭据认证爆破（frequency / bruteforce，权重 25）。

判定口径（data-model 10.2）：

- 统计范围：同一 `source_ip`；
- 时间窗口：当前事件 `event_time` 向前回溯 `window_seconds`（默认 300 秒，含当前事件）；
- 命中条件：窗口内 `auth` 事件数 `>= min_auth_attempts`（默认 8），
  且不同凭据组合（`username` + `credential_test_id` 去重对）数
  `>= min_distinct_credential_pairs`（默认 5）；
- `count_failed_only=true` 时仅统计 `failure/denied` 的认证（默认 false，成功与失败都计入）；
- 仅对 `auth` 事件判定，避免在后续事件上重复刷命中。
"""

from __future__ import annotations

from sqlalchemy import text

from app.services.rules.base import (
    RuleContext,
    RuleHitCandidate,
    register,
    safe_int,
    window_range,
)

# 认证失败口径：data-model 4.3 的 total_auth_failures 定义（failure/denied）
FAILED_STATUSES: frozenset[str] = frozenset({"failure", "denied"})


@register("R02")
async def evaluate(ctx: RuleContext) -> RuleHitCandidate | None:
    """判定本事件是否构成“短时多凭据认证爆破”。"""
    event = ctx.event_row
    if str(getattr(event, "event_type", "")) != "auth":
        return None

    params = ctx.parameters
    window_seconds = safe_int(params.get("window_seconds"), 300)
    min_auth_attempts = safe_int(params.get("min_auth_attempts"), 8)
    min_distinct_pairs = safe_int(params.get("min_distinct_credential_pairs"), 5)
    count_failed_only = bool(params.get("count_failed_only", False))
    start, end = window_range(ctx.event_time, window_seconds)

    rows = (
        await ctx.db.execute(
            text(
                """
                SELECT username, credential_test_id, status
                FROM attack_log
                WHERE source_ip = :source_ip
                  AND event_type = 'auth'
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
    ).all()

    attempts = 0
    credential_pairs: set[tuple[str, str]] = set()
    for row in rows:
        status = str(row.status or "")
        if count_failed_only and status not in FAILED_STATUSES:
            continue
        attempts += 1
        username = str(row.username or "")
        credential_test_id = str(row.credential_test_id or "")
        credential_pairs.add((username, credential_test_id))

    if attempts < min_auth_attempts:
        return None
    if len(credential_pairs) < min_distinct_pairs:
        return None

    summary = (
        f"{window_seconds} 秒内同一来源认证尝试 {attempts} 次"
        f"（阈值 {min_auth_attempts}），不同凭据组合 {len(credential_pairs)} 组"
        f"（阈值 {min_distinct_pairs}），符合爆破特征"
    )
    return RuleHitCandidate(
        rule_code=ctx.rule_code,
        intent_type="bruteforce",
        risk_weight=25,
        evidence_summary=summary[:1024],
        details={
            "window_seconds": window_seconds,
            "auth_attempts": attempts,
            "distinct_credential_pairs": len(credential_pairs),
            "min_auth_attempts": min_auth_attempts,
            "min_distinct_credential_pairs": min_distinct_pairs,
            "count_failed_only": count_failed_only,
        },
    )
