# Implementation Plan: 数据库蜜罐与攻击行为分析系统（全量核心功能）

**Branch**: `001-database-honeypot` | **Date**: 2026-11-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-database-honeypot/spec.md`

## Summary

本计划实现“基于 MySQL 协议模拟的数据库蜜罐与攻击行为分析系统”的最小完整闭环：
由 Python 编写的诱饵服务模拟 MySQL 8 握手、认证与元数据查询，捕获连接、认证与 SQL
事件；事件在单一数据库事务中写入 MySQL 8.4，并通过唯一约束实现幂等；确定性规则引擎
依据数据库配置的 R01–R05 识别扫描、爆破、踩点、拖库与破坏性操作，更新意图、画像、
风险分并生成可追溯的告警；Vue 3 控制台通过只读接口与四个核心视图展示概览、攻击者
画像、会话时间线与告警。数据库设计（ER 图、正式主外键、CHECK/UNIQUE、复合索引、
四个分析视图、事务与幂等、账号最小权限）是本项目的核心交付物，先于应用代码完成评审。

## Technical Context

**Language/Version**: Python 3.14.4（`requires-python >= 3.11`；已核实关键依赖提供
CPython 3.14 wheel）

**Primary Dependencies**: FastAPI 0.165、Uvicorn 0.54、Pydantic 2.14、pydantic-settings
2.16、SQLAlchemy 2.1.9（async）、asyncmy 0.2.18、Alembic 1.20.1、mysql-mimic 3.0.5、
structlog 26.1；前端 Vue 3.5、Vite 8、TypeScript 5.9、Element Plus 2.14、ECharts 6、
pnpm 12、Node 24

**Storage**: MySQL 8.0.46（本机可用版本；目标为 8.4 LTS，实现遵循 8.x 共有能力子集；InnoDB、utf8mb4、UTC、DATETIME(6)）；11 张表（含受控新增的只追加审计表 `audit_log`）、4 个核心
分析视图、四条复合索引；数据库账号按 migrate / app_rw / app_ro / backup 分离

**Testing**: pytest 9.2 + pytest-asyncio 1.5 + httpx 0.28；使用独立测试库
`honeypot_test` 与真实 MySQL 8.4 集成测试，不使用数据库 Mock；Alembic `upgrade`
/`downgrade` 往返验证

**Target Platform**: Linux 或 macOS 单机/虚拟机；Docker 29 + Docker Compose v2 作为
标准运行环境，本机进程方式作为降级路径；仅在隔离实验网络运行

**Project Type**: Web application（FastAPI 后端 + Vue SPA）+ 独立 TCP 诱饵服务

**Performance Goals**: 演示数据规模 1 千至 1 万条事件；控制台只读接口本机 p95 低于
500 ms；单条事件入库并完成规则分析低于 100 ms；诱饵握手与元数据查询在本机低于 1 s；
不设高并发目标（课程规模）

**Constraints**: 仅授权隔离网络；不暴露公网；不得连接真实业务库；采集数据只存不执行；
四页控制台固定；单机部署；中文文档与注释；规则阈值属课程演示口径，非生产安全基线

**Scale/Scope**: 4 个控制台页面、11 张表、4 个视图、5 至 8 条规则、30 条 fake_users、
120 条 fake_orders；团队规模为课程小组

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法条款 | 计划中的落地方式 | 状态 |
| --- | --- | --- |
| 一、文档与注释完备（中文优先） | 本计划、research、data-model、contracts、quickstart 全部中文；DDL 使用 `COMMENT`；ER 图用 Mermaid 源文件；接口文档由 OpenAPI + 中文说明维护 | PASS |
| 二、数据库设计优先（Schema 即契约） | Phase 1 先产出 ER 图与数据字典并经评审；再写 DDL 与迁移；关系模式达到 3NF；主键、外键、CHECK、UNIQUE 在数据库层表达；索引有查询依据 | PASS |
| 三、安全与最小权限 | 四类数据库账号与 GRANT 矩阵；全部 SQL 参数化；诱饵仅存不执行；演示与测试库分离；密钥走环境变量；控制台脱敏 | PASS |
| 四、事务完整性与鲁棒性 | 事件写入、命中、画像、告警单事务；`event_uuid` 唯一约束幂等；死锁/锁超时重试；迁移可回滚；输入长度与查询超时上限 | PASS |
| 五、测试先行与可验证性 | 规则纯函数单元测试；真实 MySQL 集成测试覆盖约束、事务、幂等、迁移；接口测试与 quickstart 端到端冒烟；安全用例（注入载荷、超长输入、只存不执行） | PASS |
| 技术栈与工程约束 | 选型已记录于本计划与 [research.md](./research.md)；未记录不得引入新依赖；协议模拟层与持久化层解耦；依赖锁定版本 | PASS |
| 开发工作流与质量门禁 | 按 Spec Kit 阶段推进；合并前 ER/DDL 一致性、迁移往返、测试、中文注释、无明文密钥五项门禁；演示环境可从迁移与种子重建 | PASS |

**结论**：Phase 0 前检查通过，无违反项，无需在 Complexity Tracking 中申请豁免。

## Project Structure

### Documentation (this feature)

```text
specs/001-database-honeypot/
├── spec.md              # 功能规格（已完成）
├── plan.md              # 本文件
├── research.md          # Phase 0 技术决策（已完成）
├── data-model.md        # Phase 1 数据模型与数据字典
├── quickstart.md        # Phase 1 验证与运行指南
├── contracts/           # Phase 1 接口与事件契约
│   ├── api.md           # 控制台 REST 接口契约
│   ├── events.md        # 标准事件与流水线内部契约
│   └── honeypot-protocol.md  # 诱饵协议能力与客户端兼容边界
├── checklists/          # 规格质量清单
└── tasks.md             # Phase 2 由 /speckit-tasks 生成
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml               # uv 管理的依赖与工具配置
├── uv.lock
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_init_schema.py  # 11 张表、约束与外键
│       ├── 0002_views.py        # 4 个核心分析视图
│       ├── 0003_indexes.py      # 复合索引与 EXPLAIN 基线
│       └── 0004_seed_rules.py   # R01–R05 种子规则
├── app/
│   ├── main.py                  # FastAPI 应用与前端静态托管
│   ├── config.py                # pydantic-settings 配置模型
│   ├── logging.py               # 应用运行日志（与业务事件分离）
│   ├── db/
│   │   ├── session.py           # async 引擎、会话与事务辅助
│   │   └── base.py
│   ├── models/                  # SQLAlchemy 表模型（11 张表 + 4 视图映射）
│   ├── schemas/                 # Pydantic 请求/响应模型
│   ├── repositories/            # 只读查询与写入仓储（复用视图）
│   ├── services/
│   │   ├── ingest.py            # 事件写入事务与幂等
│   │   ├── analysis.py          # 规则匹配与派生更新
│   │   ├── risk.py              # 风险分与等级（确定性纯函数）
│   │   ├── alerts.py            # 告警生成与去重
│   │   └── reset.py             # 演示重置事务
│   ├── api/
│   │   ├── deps.py
│   │   └── routes/              # health、overview、trend、attackers、sessions、alerts、rules
│   ├── honeypot/
│   │   ├── server.py            # mysql-mimic 服务启动与配置
│   │   ├── session.py           # 自定义 Session：SQL 路由与伪造响应
│   │   ├── auth.py              # 诱饵账号 IdentityProvider
│   │   └── fake_catalog.py      # 伪造库表目录与行数据
│   └── cli/                     # seed、import_samples、reset_demo、explain_diff
└── tests/
    ├── unit/                    # 规则判定、风险计算、SQL 归一化
    ├── integration/             # 约束、事务、幂等、视图、迁移往返
    └── api/                     # httpx+ASGI 接口测试

frontend/
├── package.json
├── vite.config.ts               # /api 代理与构建输出
├── index.html
└── src/
    ├── main.ts
    ├── App.vue
    ├── router/index.ts          # 四个核心路由
    ├── api/client.ts            # 类型化接口封装
    ├── types/                   # 与 contracts/api.md 对齐的类型
    ├── views/                   # OverviewView、AttackersView、AttackerDetailView、AlertsView
    └── components/              # StatCard、TrendChart、RiskBadge、IntentTag、SessionTimeline、AlertTable

db/
├── init/                        # 容器初始化：建库与四类账号授权
└── explain/                     # EXPLAIN 前后对比记录（JSON/截图说明）

docs/                            # 中文项目文档（总纲已归档）
├── 数据库蜜罐系统项目总纲_1.1_扩充版.md
├── architecture.md              # 分层架构、数据流与部署视图
├── database-design.md           # 数据库设计说明书（链接 ER 图与数据字典）
├── demo-script.md               # 现场演示脚本与检查表
├── test-plan.md                 # 测试矩阵与预期结果
└── explain-indexes.md           # 复合索引验证记录

scripts/                         # 授权模拟器、样本导入、演示重置的包装脚本
compose.yaml                     # MySQL 8.4 + backend + web
Makefile                         # 初始化、迁移、种子、启动、测试、重置
README.md                        # 环境、启动、演示与故障处理说明
.env.example                     # 端口、数据库 URL、诱饵账号、规则默认值模板
```

**Structure Decision**: 采用单仓多目录结构。后端为一个 FastAPI 应用包，内部按
`api/service/repository/model` 分层，诱饵服务作为同进程独立 asyncio 服务（也可单独
进程启动），与持久化层通过标准事件契约解耦；前端为独立 Vue SPA，通过 `/api` 契约
通信；数据库 DDL、视图、索引与种子全部纳入 Alembic 迁移，`db/init` 只负责建库与
授权。选择该结构是为了满足宪法“数据库设计优先”与“迁移可重建”，同时让协议模拟、
规则分析、展示三层可分别测试与替换（降级为真实 MySQL 时只需替换 `app/honeypot`）。

## Phase 0：研究与决策

已完成，输出 [research.md](./research.md)，结论包括：MySQL 8.4 LTS 与 InnoDB；
mysql-mimic 3.0.5 协议模拟（含 `caching_sha2_password` 兼容风险与规避）；FastAPI +
SQLAlchemy 2.1 async + asyncmy；Vue 3 + Vite 8 前端；pytest + 真实 MySQL 测试；
Docker Compose 部署；事件幂等与事务策略。所有 `NEEDS CLARIFICATION` 已消除。

## Phase 1：设计与契约

1. **数据模型** → [data-model.md](./data-model.md)：11 张表、Mermaid ER 图、完整数据
   字典、约束矩阵、4 个视图 SQL、索引与 EXPLAIN 验证、事务与幂等、评分与告警算法、
   四类账号 GRANT、种子数据、迁移与回滚、生命周期、FR 映射。
2. **接口契约** → [contracts/api.md](./contracts/api.md)、
   [contracts/events.md](./contracts/events.md)、
   [contracts/honeypot-protocol.md](./contracts/honeypot-protocol.md)：控制台 REST 接口、
   标准事件与流水线不变量、诱饵协议能力与客户端兼容边界。
3. **验证指南** → [quickstart.md](./quickstart.md)：环境准备、启动顺序、端到端验证
   命令、SC-001 至 SC-015 映射、故障处理。

### 设计后宪法复核

| 宪法条款 | Phase 1 设计证据 | 状态 |
| --- | --- | --- |
| 文档与注释 | data-model 含逐列中文注释；contracts 全中文；ER 图为 Mermaid 源文件 | PASS |
| 数据库设计优先 | ER 图与数据字典先于代码；3NF；主外键/CHECK/UNIQUE 齐全；迁移可重建 | PASS |
| 安全与最小权限 | 四类账号 GRANT 矩阵；只读接口使用 app_ro；诱饵只存不执行；脱敏字段约定 | PASS |
| 事务与鲁棒性 | 单事务流水线、幂等键、死锁重试、迁移回滚、查询上限 | PASS |
| 测试与可验证性 | quickstart 覆盖全部 SC；测试分层明确；真实引擎集成 | PASS |

**结论**：设计后复核通过，无违反项。

## Complexity Tracking

无宪法违反项，不需要豁免。以下复杂度属必要设计，已在 research.md 说明取舍：

| 复杂度 | 必要性 | 更简方案未采用的原因 |
| --- | --- | --- |
| 双 asyncio 运行时（FastAPI + 诱饵服务） | 协议模拟库要求异步服务端，且需与 Web 并行运行 | 改用同步 Web 框架会让协议层与 API 层并发模型割裂 |
| 视图承载部分分析逻辑 | 课程要求体现视图、聚合与窗口函数能力，且控制台直接复用 | 全部放应用层会削弱数据库设计这一核心交付物 |
| 独立 Vue SPA 构建链 | 四页控制台需要图表、分页与筛选交互，且要求相对前沿技术栈 | 服务端模板可更简单，但图表与交互维护成本更高、展示效果较弱 |
| mysql-mimic 依赖 | 自研 MySQL 协议风险与工期不可接受 | 真实 MySQL + general_log 保留为降级路线，但无法灵活伪造库表与按事件注入 |

## 后续阶段

- **Phase 2**：运行 `/speckit-tasks` 依据本计划、data-model 与 contracts 生成依赖有序
  的 `tasks.md`。
- **实现顺序建议**：数据库迁移与种子 → 存储/事件契约 → 规则与画像 → 诱饵服务 →
  只读接口 → 前端四页 → 演示脚本与 EXPLAIN 记录 → 测试与文档收尾。
- **验收**：以 spec.md 成功标准 SC-001 至 SC-015 与 quickstart 验证清单为准。
