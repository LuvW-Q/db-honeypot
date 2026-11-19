# 技术研究与决策记录（Phase 0）

**Feature**: `001-database-honeypot`
**Date**: 2026-11-19
**输入**: [spec.md](./spec.md)、[项目总纲](../../docs/数据库蜜罐系统项目总纲_1.1_扩充版.md)、[项目宪法](../../.specify/memory/constitution.md)

本文件记录 `/speckit-plan` 阶段对全部技术未知项的研究结论。每条按“决策 / 理由 /
候选方案与取舍”组织，结论将直接约束后续实现与测试。

## 1. 存储引擎与数据库版本

- **决策**：目标版本 MySQL 8.4 LTS；本机镜像源仅提供 MySQL 8.0.46，实施按 8.x 共有能力子集
  （`CHECK`、CTE、窗口函数、`JSON`、`EXPLAIN FORMAT=JSON`）编写，8.0.46 与 8.4 均可运行。
  InnoDB，字符集 `utf8mb4`，排序规则
  `utf8mb4_0900_ai_ci`；时间统一 UTC，使用 `DATETIME(6)`；强制启用外键与 `CHECK`
  约束（MySQL 8.0.16+ 已实际执行 CHECK）。
- **理由**：用户明确要求数据库选用 MySQL 8；8.4 LTS 是 8.x 中维护周期最长、生态成熟的
  版本，原生支持 CTE、窗口函数、`JSON` 类型与 `EXPLAIN FORMAT=JSON`，可完整支撑总纲的
  四个核心视图与查询计划对比。InnoDB 提供事务、行锁与外键，是总纲“正式主外键、事务、
  幂等”要求的前提。
- **候选方案与取舍**：
  - MySQL 8.0：同样满足功能，但已进入维护后期；仅在实验机无法安装 8.4 时作为降级，
    所有 SQL 保持在 8.0 兼容子集内。
  - SQLite：总纲允许的降级方案，单机零配置，但 CHECK/视图/窗口函数与并发控制能力弱，
    不足以体现课程要求，不采用。
  - MariaDB：窗口函数与 JSON 语义存在差异，`information_schema` 行为与 MySQL 客户端
    兼容性也会增加协议模拟测试成本，不采用。

## 2. MySQL 协议模拟方案

- **决策**：采用 `mysql-mimic` 3.0.5 作为诱饵服务端协议实现，自定义 `Session` 子类处理
  查询路由，`schema()` 返回伪造库表结构以支撑 `SHOW` 与 `information_schema` 查询；
  认证使用内置 `mysql_native_password` 插件 + 自定义 `IdentityProvider` 校验预置诱饵账号。
- **理由**：`mysql-mimic` 是纯 Python 实现，PyPI 提供 CPython 3.14 的 manylinux/macOS
  wheel（已核实 3.0.5 文件列表），无需本地编译；内置基于 `sqlglot` 的元数据查询处理，
  能在不实现完整 MySQL 内核的前提下让常见客户端完成握手、认证与元数据查询；支持
  `mysql_native_password`、`mysql_clear_password`、`mysql_no_login` 等认证插件，便于
  记录认证尝试并拒绝未知账号。
- **候选方案与取舍**：
  - 自研 MySQL 协议：握手包、能力协商、认证插件、结果集编码、错误包均需自行实现，
    工期与风险远超课程规模，不采用。
  - 隔离环境中的真实 MySQL 8 + `general_log`：必须保留为**降级路线**（总纲第七章）。
    优点是可获得完整协议兼容，缺点是难以区分“诱饵成功/失败”并按事件注入伪造数据；
    降级后必须保持日志表、画像表、规则与控制台不变，仅替换诱饵层。
  - Twisted/自研 asyncio 协议库：生态与示例不足，不采用。
- **已知风险与规避**：
  - `mysql-mimic` 不提供 `caching_sha2_password` 服务端插件，MySQL 8.0/8.4 客户端默认
    使用 `caching_sha2_password`。规避方式：客户端显式使用
    `--default-auth=mysql_native_password`（MySQL CLI 8.0/8.4 仍保留该客户端插件），
    或使用 PyMySQL（默认支持 native password）；答辩前固定客户端与连接参数。
    若现场客户端无法协商，按总纲降级路线切换到真实 MySQL 8 实例。
  - `sqlglot` 对非标准语句的解析失败：捕获解析异常后按“无法识别的语句”记为 `error`
    事件并返回受控错误，不影响服务可用性。

## 3. 后端框架与运行时

- **决策**：Python 3.14.4（当前环境已安装并验证存在 3.14 wheel）+ FastAPI 0.165 +
  Uvicorn 0.54 + Pydantic 2.14；配置使用 `pydantic-settings` 2.16；依赖管理使用 `uv`
  （`pyproject.toml` + `uv.lock`），保留 `requirements.txt` 导出作为 pip 降级路径。
- **理由**：FastAPI 是当前成熟的异步 Web 框架，原生 Pydantic v2 数据校验与 OpenAPI 文档，
  与 MySQL 协议模拟所需的 asyncio 运行时天然一致；类型提示与自动文档有利于接口契约落地。
  项目宪法要求“技术选型在 plan 阶段记录”，此处记录并作为实现基线。
- **候选方案与取舍**：
  - Flask：总纲基线方案，同步模型与 mysql-mimic 的 asyncio 运行时割裂，需要额外线程桥接；
    且无内建数据校验与 OpenAPI，不采用。
  - Django：重量级，自带 ORM/模板/管理后台，本项目四页只读控制台用不到，反而增加复杂度。
  - Litestar：性能与特性优秀但生态与团队熟悉度不及 FastAPI，不采用。

## 4. 数据访问层与迁移

- **决策**：SQLAlchemy 2.1.9 async ORM + `asyncmy` 0.2.18 驱动（PyPI 已核实 CPython 3.14
  wheel）；迁移使用 Alembic 1.20.1；事务采用显式 `async with session.begin()`。
- **理由**：SQLAlchemy 2.x 的异步会话与 FastAPI 协程一致；`asyncmy` 是 SQLAlchemy 官方
  文档推荐的 MySQL 异步驱动之一，性能优于 `aiomysql` 且已提供 3.14 预编译 wheel；
  Alembic 与 SQLAlchemy 同生态，可版本化 DDL 并支持 `downgrade`，满足宪法“迁移可回滚、
  禁止手工改库”的要求。
- **候选方案与取舍**：
  - 同步 SQLAlchemy + PyMySQL：更简单，但会阻塞事件循环或在 FastAPI 线程池中运行，
    与诱饵服务的 asyncio 运行时形成两套并发模型。
  - `aiomysql`（纯 Python）：无需编译，可作为 `asyncmy` 在目标机无法安装时的降级驱动；
    ORM URL 只要替换驱动即可迁移。
  - 手写 SQL + 连接池：失去 ORM 的表结构与迁移能力，且更易产生拼接 SQL 风险，不采用。
- **约束**：视图、复合索引与种子数据通过 Alembic 迁移中的 `op.execute()` 原始 SQL 管理，
  保证“一键重建”；迁移必须通过 `upgrade head` + `downgrade base` 往返测试。

## 5. 前端方案

- **决策**：Vue 3.5 + Vite 8 + TypeScript 5.9 + Element Plus 2.14 + ECharts 6，
  包管理使用 pnpm 12，Node 24；四个路由页面（概览 / 攻击者列表 / 攻击者详情 / 告警列表）；
  开发期 Vite 代理 `/api` 到 `http://127.0.0.1:8000`，生产构建产物由 FastAPI 静态托管
  （或 nginx）。
- **理由**：Vue 3 + Vite 是当前成熟且主流的前端组合，Element Plus 提供表格、筛选、分页、
  抽屉等现成组件，ECharts 6 满足趋势图与规则效果图；四页只读场景不需要状态管理库与复杂
  路由权限，保持轻量。TypeScript 固定 5.9（成熟稳定），暂不采用 2026 年刚发布的
  TypeScript 7 原生编译器，避免 `vue-tsc` 兼容性风险。
- **候选方案与取舍**：
  - Jinja2 + HTMX + Alpine.js：实现最简、无构建步骤，但交互体验与图表组件化程度不如
    Vue，且“相对前沿”的技术要求更倾向于 SPA 方案。
  - React 19 + Next.js：生态同样成熟，但 SSR 对纯内部只读控制台没有必要，构建与部署
    复杂度更高。
  - Vue 2 / Element UI：已停止维护，不采用。

## 6. 测试体系

- **决策**：pytest 9.2 + pytest-asyncio 1.5 + httpx 0.28；数据库测试使用独立测试库
  `honeypot_test`（Docker MySQL 8.4），通过 Alembic 迁移与夹具初始化；不使用任何
  数据库 Mock。
- **理由**：宪法原则五要求“涉及数据库的行为必须基于真实引擎验证”，Mock 无法验证外键、
  CHECK、事务隔离与 `ON DUPLICATE KEY` 语义；pytest 生态成熟，httpx 支持 ASGI 直连
  测试 FastAPI 应用。
- **候选方案与取舍**：
  - unittest：内置但夹具与异步支持弱，不采用。
  - testcontainers：自动化程度高，但需要 Docker 拉取镜像且增加启动耗时；课程环境已有
    Docker Compose，直接用 compose 管理测试库更透明。
- **测试分层**：单元测试（规则判定纯函数、SQL 归一化、UUID/脱敏工具）→ 集成测试
  （存储事务、幂等、约束、视图查询、迁移往返）→ 接口测试（httpx + 真实测试库）→
  端到端冒烟（quickstart 场景）。

## 7. 规则引擎与风险评分实现方式

- **决策**：规则配置存 `detection_rules`，分析引擎为 Python 纯函数 + 数据库查询；每条
  规则实现为可注册的判定函数（`rule_code` → 判定器），参数全部来自规则行；评分按
  [data-model.md](./data-model.md) 的确定性公式计算，同一 `rule_code` 在一个统计范围内
  只计一次最大权重，封顶 100。
- **理由**：总纲要求规则“简单、可测试、可解释”，且参数、权重、版本、启停入库；纯函数
  便于单元测试覆盖阈值边界，数据库配置便于演示“停用规则/调整阈值/版本切换”。
- **候选方案与取舍**：
  - 通用规则语言（DSL）：解释器工期与调试成本高，且容易让学生把重点放在语言实现而非
    数据库设计，不采用。
  - 纯 SQL 存储过程实现规则：难以表达跨事件窗口与多步判定，也不便于单元测试。
  - 机器学习异常检测：明确不做（总纲）。

## 8. 幂等、事务与并发

- **决策**：`attack_log.event_uuid` 唯一约束 + 应用侧“先查后写、冲突回查”；
  事件写入、规则命中、意图/画像更新、告警生成在同一数据库事务内完成；隔离级别使用
  `READ COMMITTED`；死锁/锁等待超时最多重试 3 次，指数退避（50ms/100ms/200ms）并记录
  运行日志。
- **理由**：唯一约束是幂等的最终防线，应用侧先查避免常见重复写；单事务保证“事件—命中—
  画像—告警”原子一致；`READ COMMITTED` 减少间隙锁与死锁概率，适合以 INSERT 为主、
  少范围更新的负载。MySQL 默认 `REPEATABLE READ` 可作为回退配置。
- **候选方案与取舍**：
  - `INSERT ... ON DUPLICATE KEY UPDATE` 返回 `affected_rows=0` 判断重复：可行，但
    无法同时返回旧 `event_id`，需要额外查询；文档中作为等价实现记录。
  - 消息队列异步分析：引入额外组件，超出课程规模，不采用。
  - 用应用锁/Redis 去重：数据库唯一约束已足够，不引入。

## 9. 部署与运行

- **决策**：Docker Compose 编排 `mysql:8.4`（含初始化 SQL 建库建账号）、`backend`
  （FastAPI + 诱饵服务双进程或 supervisor 启动）、可选 `web`（nginx 托管前端构建产物）；
  本机进程方式作为无 Docker 降级路径。配置通过 `.env` + `pydantic-settings` 注入，
  仓库提供 `.env.example`。
- **理由**：总纲要求隔离与可复现，Compose 能固定版本、网络与数据卷；本机路径保证实验机
  没有 Docker 时仍可运行。
- **候选方案与取舍**：
  - 手工安装 MySQL：步骤多、易污染实验机，仅作降级。
  - Kubernetes：课程规模完全不需要。

## 10. 日志、可观测性与配置

- **决策**：应用日志使用标准库 `logging` + `structlog`（JSON 输出），与业务事件日志
  （`attack_log`）严格分离；日志包含 `request_id`/`session_id`/`event_id` 便于定位；
  配置项集中在 `pydantic-settings` 模型（端口、数据库 URL、诱饵账号、规则默认值、保留
  天数、CORS、前端托管目录）。
- **理由**：宪法要求失败可观测、禁止吞异常；总纲要求“业务事件与运行日志分开”。结构化
  日志便于答辩时展示故障定位。
- **候选方案与取舍**：
  - 纯文件日志无结构：检索困难，不采用。
  - 接入 Prometheus/Grafana：超出课程范围，列为后续可选项。

## 11. 文档与注释语言

- **决策**：全部文档、DDL `COMMENT`、代码注释、提交信息使用中文；技术专有名词保留英文；
  ER 图使用 Mermaid 源文件；接口文档由 FastAPI OpenAPI 自动生成并人工补充中文说明。
- **理由**：用户明确要求与宪法原则一（中文文档与注释完备）的强制约束。

## 12. 结论

上述决策已消除计划模板中的全部 `NEEDS CLARIFICATION`：数据库为 MySQL 8.4 LTS；后端为
Python 3.14 + FastAPI + SQLAlchemy 2.1 async；协议模拟为 mysql-mimic；前端为 Vue 3 +
Vite 8；测试为 pytest + 真实 MySQL 集成；部署为 Docker Compose。实现阶段不得在未记录
的情况下偏离这些决策；需要调整时按总纲与宪法变更规则更新本文件与 `plan.md`。
