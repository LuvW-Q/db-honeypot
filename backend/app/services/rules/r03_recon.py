"""R03 元数据与结构探测（keyword / recon，权重 15）。

判定口径（data-model 10.2）：

- 逐事件判定：只匹配本事件的 `normalized_sql`（缺失时回落 `sql_statement`）；
- 默认不区分大小写，任一关键词命中即命中；
- 默认关键词：SHOW TABLES / SHOW DATABASES / SHOW COLUMNS / SHOW FIELDS /
  DESCRIBE / DESC（带空格） / INFORMATION_SCHEMA；
- 同一事件最多产生一条命中（`max_hits_per_event=1`），本实现天然只返回一个候选。
"""

from __future__ import annotations

from app.services.rules.base import (
    RuleContext,
    RuleHitCandidate,
    event_sql_text,
    match_any_keyword,
    register,
)

# parameters_json 缺失时的安全缺省关键词（与迁移种子保持一致）
DEFAULT_KEYWORDS: tuple[str, ...] = (
    "SHOW TABLES",
    "SHOW DATABASES",
    "SHOW COLUMNS",
    "SHOW FIELDS",
    "DESCRIBE",
    "DESC ",
    "INFORMATION_SCHEMA",
)

@register("R03")
async def evaluate(ctx: RuleContext) -> RuleHitCandidate | None:
    """判定本事件 SQL 是否包含元数据/结构探测关键词。"""
    event = ctx.event_row
    if str(getattr(event, "event_type", "")) != "query":
        return None

    sql = event_sql_text(event)
    if not sql:
        return None

    params = ctx.parameters
    keywords = params.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = list(DEFAULT_KEYWORDS)
    keyword_list = [str(k) for k in keywords]
    case_sensitive = bool(params.get("case_sensitive", False))

    matched = match_any_keyword(
        sql,
        keyword_list,
        case_sensitive=case_sensitive,
        # R03 的 "DESC " 带尾部空格，必须按子串匹配，不能加词边界
        word_boundary=False,
    )
    if matched is None:
        return None

    summary = f"本事件 SQL 命中元数据探测关键词“{matched.strip()}”，属结构/元数据踩点行为"
    return RuleHitCandidate(
        rule_code=ctx.rule_code,
        intent_type="recon",
        risk_weight=15,
        evidence_summary=summary[:1024],
        details={
            "matched_keyword": matched,
            "match_target": params.get("match_target", "normalized_sql"),
            "case_sensitive": case_sensitive,
        },
    )
