"""AI 只读辅助（可选增强，默认关闭）。

安全边界（宪法与 spec US10）：
- 只使用只读账号、只允许 SELECT；
- 只执行预设的白名单查询模板，不执行任意生成的 SQL；
- 输出标记为“辅助解释”，不参与规则命中、风险评分与最终判定；
- 功能关闭或不可用时不影响核心闭环。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging import get_logger

logger = get_logger("services.ai")


@dataclass(frozen=True)
class QueryTemplate:
    """白名单只读查询模板。"""

    key: str
    title: str
    pattern: str
    sql: str


# 仅允许针对核心视图/聚合结果的只读查询；不包含任何用户输入插值
TEMPLATES: tuple[QueryTemplate, ...] = (
    QueryTemplate(
        key="alert_summary",
        title="告警概况",
        pattern=r"告警|alerts?|风险提示",
        sql="SELECT COUNT(*) AS alert_count, SUM(is_read = 0) AS unread_count FROM alerts",
    ),
    QueryTemplate(
        key="attacker_summary",
        title="攻击者概况",
        pattern=r"攻击者|来源|ip|画像",
        sql=(
            "SELECT COUNT(*) AS attacker_count, "
            "SUM(risk_score >= 60) AS high_risk_count, "
            "MAX(risk_score) AS max_risk_score FROM attacker_profile"
        ),
    ),
    QueryTemplate(
        key="session_summary",
        title="会话与查询概况",
        pattern=r"会话|连接|查询|流量",
        sql=(
            "SELECT COUNT(*) AS session_count, "
            "COALESCE(SUM(request_count), 0) AS event_count FROM sessions"
        ),
    ),
    QueryTemplate(
        key="trend",
        title="每日攻击趋势",
        pattern=r"趋势|每天|每日|最近",
        sql=(
            "SELECT stat_date, event_count, alert_count FROM v_daily_attack_trend "
            "ORDER BY stat_date DESC LIMIT 7"
        ),
    ),
    QueryTemplate(
        key="rule_effectiveness",
        title="规则效果",
        pattern=r"规则|命中|效果",
        sql=(
            "SELECT rule_code, rule_name, hit_count, hit_rank FROM v_rule_effectiveness "
            "ORDER BY hit_rank LIMIT 10"
        ),
    ),
)


class AiDisabledError(RuntimeError):
    """AI 功能关闭时抛出。"""


def _match_template(question: str) -> QueryTemplate | None:
    """按关键词匹配白名单模板（只读、确定性）。"""
    for template in TEMPLATES:
        if re.search(template.pattern, question, flags=re.IGNORECASE):
            return template
    return None


async def answer_question(db: AsyncSession, question: str) -> dict:
    """把自然语言问题映射到白名单只读模板并返回结果。

    参数 db 必须是只读会话（`app_ro`）。任何写操作都会被白名单排除。
    """
    if not settings.ai_enabled:
        raise AiDisabledError("AI 辅助功能未启用")
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    template = _match_template(question)
    if template is None:
        return {
            "enabled": True,
            "template": None,
            "answer": "该问题不在预设只读模板范围内，请询问告警、攻击者、会话或规则相关问题。",
            "rows": [],
            "note": "辅助解释，正式结论以数据库规则命中与风险分为准。",
        }
    result = await db.execute(text(template.sql))
    rows = [dict(row._mapping) for row in result]
    logger.info("AI 辅助查询", template=template.key, rows=len(rows))
    return {
        "enabled": True,
        "template": template.key,
        "title": template.title,
        "answer": f"已按“{template.title}”预设只读模板查询，共返回 {len(rows)} 行。",
        "rows": rows,
        "note": "辅助解释，正式结论以数据库规则命中与风险分为准。",
    }
