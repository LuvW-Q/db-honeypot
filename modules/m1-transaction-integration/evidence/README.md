# 证据索引

| 证据编号 | 对应用户故事 / FR | 复现命令 | 期望输出 | 产物路径 | 依赖 | 最近验证时间 |
| --- | --- | --- | --- | --- | --- | --- |
| E-API-002 | FR-062 / FR-064 / FR-066（002 T019–T021） | 见 [api-extensions.md](api-extensions.md) §1、§4 | EXPLAIN 表 + 冒烟状态码与样例 | [api-extensions.md](api-extensions.md) | MySQL 8.0.46 `honeypot_dev`、uvicorn :8001 | 2026-11-25 |
| E-TX-001 | FR-039 / FR-042 / FR-043（事件写入事务与回滚） | 见 [transaction.md](transaction.md) §2 | 三组 before/after/cleanup 行数快照 + `clean=true`、退出码 0 | [transaction.md](transaction.md) | MySQL 8.0.46 `honeypot_dev`、`honeypot_app_rw` | 2026-11-25 |
| E-GRANT-001 | FR-068 / FR-079 / FR-082（账号最小权限与列级暴露） | 见 [grants.md](grants.md) §3、§4 | 四类账号 `SHOW GRANTS` 矩阵；只读 SELECT 成功、INSERT 被拒（1142） | [grants.md](grants.md) | MySQL 8.0.46 运行库（root 仅取证） | 2026-11-25 |
| E-API-001 | FR-062 / FR-064 / FR-066 / API-10（控制台只读 API） | 见 [api.md](api.md) §1、§2 | 10 个请求的状态码与关键字段，含一次 422 与一次 404 | [api.md](api.md) | uvicorn `127.0.0.1:8000`（未重启） | 2026-11-25 |
| E-SEC-001 | T077 安全复核（凭据/注入面/权限/写边界/反制承诺） | 见 [security-review.md](security-review.md) §8 四条复核命令 | 凭据检查无明文；f-string 仅白名单标识符；四条越权探针全部被拒（1142/1143）；控制台仅 PATCH 已读一处写 | [security-review.md](security-review.md) | MySQL 8.0.46、应用最小权限已收口（grants.md §5） | 2026-11-25 |
