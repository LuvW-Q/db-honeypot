# 证据索引（M3 ER 模型与完整性约束）

> 最近更新：**2026-11-25**；环境：容器 `dbhoneypot-mysql`（MySQL 8.0.46）、库 `honeypot_dev`、
> 解释器 `/tmp/dbh-venv/bin/python`。所有产物均由真实执行生成，命令与输出见
> [`constraints-check.md`](constraints-check.md)，未使用任何占位图或手抄数据。

## 1. 索引表

| 证据编号 | 对应任务 / 用户故事 | 内容 | 复现命令 | 期望输出 | 产物路径 | 依赖 | 最近验证时间 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M3-E01 | T013 / US3 | ER 源文件：Mermaid `erDiagram`，11 张业务表 + 10 条外键关系 + `source_ip` 逻辑聚合 | 直接阅读；渲染见 M3-E02 | 11 个实体、每个实体标注 PK/FK/UK、关系方向为父 `\|\|--o{` 子 | `../er/schema.mmd` | `honeypot_dev` 结构（迁移 0001/0003） | 2026-11-25 |
| M3-E02 | T046 / US3 | ER 渲染图（矢量 + 位图） | `npm_config_cache=/tmp/npm-cache PUPPETEER_EXECUTABLE_PATH=<chromium> npx -y @mermaid-js/mermaid-cli@11 -p modules/m3-er-constraints/er/puppeteer-config.json -i modules/m3-er-constraints/er/schema.mmd -o modules/m3-er-constraints/evidence/schema.svg -b white`（PNG 把 `-o` 换成 `schema.png` 并加 `-s 2`） | `Generating single mermaid chart`，退出码 0，产物非空 | `schema.svg`（402,602 字节）、`schema.png`（249,113 字节，1568×1174） | Node 24 + Chromium（`/tmp/pw-browsers/chromium-1255`） | 2026-11-25 |
| M3-E03 | T013 / US3 | 约束反查 JSON：`information_schema` 全量快照（列/主键/外键/唯一/CHECK/索引） | `PYTHONPATH=. /tmp/dbh-venv/bin/python modules/m3-er-constraints/tools/introspect_constraints.py --out modules/m3-er-constraints/evidence/constraints.json` | 退出码 0；`summary` 为 业务表 11 / 视图 4 / FK 10 / UK 12 / CHECK 38 / 索引 45 / 生成列 2 | `constraints.json`（128,865 字节，合法 JSON） | 只读数据库账号 `honeypot_app_rw` | 2026-11-25 |
| M3-E04 | T013 / US3 | 约束目录（人读对账）：逐表可空性 + PK/FK/UK/CHECK/索引 + 迁移行号来源 | 阅读 [`../constraints/catalog.md`](../constraints/catalog.md)；数据源为 M3-E03 | 11 张业务表逐表成节，38 条 CHECK、10 条 FK、12 条 UK 全部带迁移来源行号 | `../constraints/catalog.md` | M3-E03 | 2026-11-25 |
| M3-E05 | T046 / US3 | 主外键/CHECK/UNIQUE 正反样例实跑记录 | `docker exec -i dbhoneypot-mysql mysql --force -uroot -p<ROOT_PASSWORD> honeypot_dev < modules/m3-er-constraints/constraints/verify_constraints.sql` | 预期 7 类约束拒绝（1452 / 3819×2 / 1062×2 / 1264 / 1451）+ 2 个正例 + 收尾 `all_unchanged=1` | [`constraints-check.md`](constraints-check.md) | 容器自带 `mysql` 8.0.46 客户端 | 2026-11-25 |
| M3-E06 | T047 / US3 | 约束集成测试（CHECK/FK/UNIQUE/生成列边界） | `PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console /tmp/dbh-venv/bin/python -m pytest modules/m3-er-constraints/tests -q` | `13 passed` | `../tests/integration/test_constraints_fk.py` | `honeypot_dev` 可写连接（测试用会话回滚） | 2026-11-25 |
| M3-E07 | T013 / US3 | 可执行的正反样例 SQL（事务包裹、最终 ROLLBACK，文件内注明预期错误码） | 同 M3-E05 | 脚本可重复执行且不改变行数 | `../constraints/verify_constraints.sql` | MySQL 8.0 + `--force` | 2026-11-25 |

## 2. 结论摘要

| 维度 | 实测结果 | 对账结论 |
| --- | --- | --- |
| 业务表 | 11（另有 `alembic_version`） | 与 `docs/database-design.md` 一致 |
| 外键 | 10，全部 `ON UPDATE RESTRICT ON DELETE RESTRICT` | 一致 |
| 唯一约束 | 12（含生成列 `enabled_rule_code` 上的唯一键） | 一致 |
| CHECK | 38（枚举、上界、时序、合成标记等） | 一致 |
| 索引 | 45 = 12 主键 + 12 唯一支撑 + 21 普通 | 迁移 0001(11)+0003(10) 的 21 条普通索引全部在位 |
| 生成列 | 2（`risk_level` VIRTUAL、`enabled_rule_code` STORED） | 一致 |
| 约束活体 | 7 类拒绝 + 2 个正例 + 回滚后行数不变 | 通过 |

## 3. 复现前置

```bash
# 仓库根
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:modules/m4-rules-derived:modules/m5-views-console
export MYSQL_PWD='TestOnly-Root-2026'          # 仅本机隔离实验环境
docker inspect --format '{{.State.Health.Status}}' dbhoneypot-mysql   # 期望 healthy
```

- 数据库连接串来自 `shared.config.settings`（`DATABASE_URL`，默认 dev 库），不硬编码口令；
- 渲染需要 Node.js ≥ 18 与 Chromium；本机用 Playwright 已下载的
  `/tmp/pw-browsers/chromium-1255/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`
  通过 `PUPPETEER_EXECUTABLE_PATH` 指定，启动参数见 `../er/puppeteer-config.json`。

## 4. 已知限制与口径

1. **行数是时点快照**：`honeypot_dev` 被多个模块的验证共用，`audit_log` 等表会因
   `reset_demo`/告警已读写入而变化（本次采集 `audit_log` 为 20 行）。结构结论不受影响。
2. **错误码版本差异**：本机 MySQL 8.0.46 的外键子行错误为 **1452**、父行删除为 **1451**；
   MySQL 8.4 为 **1216/1217**。证据与测试断言同时兼容两套编码。
3. **没有宿主机 `mysql` 客户端**：统一用容器内客户端
   （`docker exec -i dbhoneypot-mysql mysql ...`）；批量执行必须带 `--force`，否则首个预期错误会中断脚本。
4. **渲染工具的坑**：`erDiagram` 之前不能写 `%%` 注释，且整行只有 `%%` 的注释行会导致 Mermaid
   预处理器合并行并报 `Parse error`（详见 `constraints-check.md` 4.3）。
5. **不在 M3 范围**：4 个分析视图的 SQL 口径（M5）、表级 `GRANT` 权限（M1 `db/grants/`）、
   前端展示与页面值核对（M5）。
