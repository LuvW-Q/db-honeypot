"""R05 破坏性写操作尝试（keyword / destructive，权重 35）。

判定口径（data-model 10.2）：

- 逐事件判定：匹配本事件 SQL（优先 `normalized_sql`）；
- 命中条件 1：SQL **首关键词**属于 DROP / TRUNCATE / DELETE / UPDATE / INSERT，
  且事件 `status` 在 `count_status`（默认 denied/error/success）内；
- 命中条件 2：`status='denied'` 且 SQL 中按词边界出现任一写操作关键词
  （诱饵层拒绝执行是预期结果，仍须记录并告警）；
- 按词边界匹配，避免 `UPDATE_TIME` 之类的列名误报。
"""

from __future__ import annotations

from m4_rules_derived.rules.base import (
    RuleContext,
    RuleHitCandidate,
    event_sql_text,
    first_keyword,
    match_any_keyword,
    register,
)

# parameters_json 缺失时的安全缺省写操作关键词
DEFAULT_KEYWORDS: tuple[str, ...] = ("DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT")
# 计入命中的事件状态（诱饵层拒绝执行时仍属“尝试”）
DEFAULT_COUNT_STATUS: tuple[str, ...] = ("denied", "error", "success")


@register("R05")
async def evaluate(ctx: RuleContext) -> RuleHitCandidate | None:
    """判定本事件是否为破坏性写操作尝试。"""
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
    count_status = params.get("count_status")
    if not isinstance(count_status, list) or not count_status:
        count_status = list(DEFAULT_COUNT_STATUS)
    status = str(getattr(event, "status", "") or "")
    case_sensitive = bool(params.get("case_sensitive", False))
    word_boundary = bool(params.get("word_boundary", True))

    head = first_keyword(sql)
    matched: str | None = None
    reason = ""

    if status in [str(s) for s in count_status]:
        for keyword in keyword_list:
            upper_keyword = keyword if case_sensitive else keyword.upper()
            if head == upper_keyword:
                matched = keyword
                reason = f"SQL 首关键词为 {head}"
                break

        # 拒绝执行的写操作：即使首关键词不是写操作（如注释/包裹语句），仍计入
        if matched is None and status == "denied":
            matched = match_any_keyword(
                sql,
                keyword_list,
                case_sensitive=case_sensitive,
                word_boundary=word_boundary,
            )
            if matched is not None:
                reason = f"写操作被拒绝（status=denied），SQL 含关键词 {matched.upper()}"

    if matched is None:
        return None

    summary = f"本事件为破坏性写操作尝试：{reason}，状态 {status}，诱饵层仅记录不执行"
    return RuleHitCandidate(
        rule_code=ctx.rule_code,
        intent_type="destructive",
        risk_weight=35,
        evidence_summary=summary[:1024],
        details={
            "matched_keyword": matched,
            "first_keyword": head,
            "status": status,
            "word_boundary": word_boundary,
            "case_sensitive": case_sensitive,
        },
    )
