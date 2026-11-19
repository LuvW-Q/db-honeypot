"""控制台 API 的仓储层。

- 只读仓储（`overview_repo`/`attacker_repo`/`session_repo`/`alert_repo`/`rule_repo`）
  接收只读会话，仅执行 SELECT，不提交事务；
- 写路径（告警已读、规则变更）由路由层注入读写会话，仓储内显式提交；
- `audit_repo` 提供两个写接口的审计留痕插入（随业务事务提交）；
- `query_repo` 提供通用 SQL 执行、行映射、分页与参数校验辅助。
"""

from __future__ import annotations

from app.repositories import (
    alert_repo,
    attacker_repo,
    audit_repo,
    overview_repo,
    query_repo,
    rule_repo,
    session_repo,
)

__all__ = [
    "alert_repo",
    "attacker_repo",
    "audit_repo",
    "overview_repo",
    "query_repo",
    "rule_repo",
    "session_repo",
]
