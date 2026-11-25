# M2 诱饵交互与事件采集

M2 负责「**诱饵怎么假装成 MySQL**」与「**一次交互如何被切成事件**」：在回环地址上监听
MySQL 协议、只读地响应查询、拒绝破坏性写操作，并把连接/认证/查询/断开标准化为事件，
经 M1 事务入口落库。它不拥有表结构、不拥有规则与页面。

| 项目 | 内容 |
| --- | --- |
| 包名 | `m2_decoy_capture` |
| 对外门面 | [`m2_decoy_capture/public.py`](m2_decoy_capture/public.py)（仅 `serve()` / `start()`） |
| 拥有产物 | 诱饵协议实现、认证/会话/事件发射、固定合成样本、模拟流量与 EXPLAIN 对比 CLI |
| 依赖方向 | M2 → `shared`（事件 Schema/日志/配置）、M1 `public.ingest_events_in_session`；**不** import M4/M5 内部模块 |
| 监听地址 | 默认 `127.0.0.1:3307`（非回环绑定会被服务端拒绝） |

---

## 1. 目录与职责

```text
m2-decoy-capture/
├── m2_decoy_capture/
│   ├── public.py            # 对外门面：serve()（阻塞）/ start()（async）
│   ├── server.py            # 监听循环、握手、会话生命周期、SIGINT/SIGTERM
│   ├── session.py           # 单连接会话：语句序列、风险累加、断开
│   ├── emitter.py           # 标准化事件发射（connect/auth/query/disconnect）
│   ├── auth.py              # 认证失败样本（只存 username + credential_test_id）
│   ├── fake_catalog.py      # 诱饵表/列元数据（假数据、无真实业务信息）
│   ├── samples/catalog.py   # S01–S07 固定合成样本（事件时间/ID 全部写死）
│   └── cli/                 # simulate_traffic / import_samples / gen_demo_data /
│                            # seed_decoy / explain_diff
├── docs/explain-indexes.md  # 时间线与溯源查询的索引口径说明
├── tests/unit/              # 诱饵目录与事件切分
└── evidence/                # 同一会话完整事件日志、索引前后 EXPLAIN 对比
```

## 2. 对外契约

| 入口 | 语义 |
| --- | --- |
| `public.serve()` | 阻塞式启动诱饵，等价 `python -m m2_decoy_capture.server` |
| `public.start()` | async 启动并返回服务器实例（集成测试/生命周期管理） |
| `python -m m2_decoy_capture.cli.simulate_traffic --target 127.0.0.1:3307 --rounds 3` | 授权模拟器，真实 MySQL 协议跑完整语句序列 |
| `python -m m2_decoy_capture.cli.import_samples --set demo_basic --json` | 导入 S01–S07 固定样本（幂等） |
| `python -m m2_decoy_capture.cli.gen_demo_data --sessions 200 --events 2400` | 生成演示规模数据（确定性种子） |
| `python -m m2_decoy_capture.cli.seed_decoy` | 灌入诱饵表种子（`fake_*`） |
| `python -m m2_decoy_capture.cli.explain_diff` | 时间线/溯源查询索引前后 EXPLAIN 对比 |

事件字段、状态机与幂等语义见
[`contracts/events.md`](../../specs/002-ui-console-modularization/contracts/events.md)；
样本编号与预期命中见 [`m2_decoy_capture/samples/README.md`](m2_decoy_capture/samples/README.md)。

## 3. 交互语义（演示口径）

- **会话序列**：`connect` → 若干 `auth_failure` → 认证成功后 `query`（只读 SELECT）→
  破坏性写操作（`UPDATE/DELETE/INSERT/DROP/TRUNCATE`）**预期被拒 1142** → `disconnect`，
  连接不中断（证据 E-M2-001 的 16 条事件）。
- **只读诱饵**：所有 SQL 仅作为字符串入库，**绝不拼进查询执行**；诱饵表 `fake_*` 只含
  `TEST-ONLY` 前缀的无效数据。
- **认证样本**：只保存 `username` 与 `credential_test_id`，不保存任何口令（明文/哈希均无）。
- **事件标准化**：由 `emitter.py` 产出 `CapturedEvent`，经 M1 `ingest_events_in_session`
  在同一事务内写入；失败整批回滚。
- **监听安全**：默认绑定 `127.0.0.1`；`server.py` 启动时校验非回环地址并拒绝。

## 4. 复现命令

```bash
export PYTHONPATH=.:modules/m1-transaction-integration:modules/m2-decoy-capture:\
modules/m4-rules-derived:modules/m5-views-console

# 1) 启动诱饵（终端 A）
/tmp/dbh-venv/bin/python -m m2_decoy_capture.server

# 2) 制造真实诱饵流量（终端 B，授权模拟）
/tmp/dbh-venv/bin/python -m m2_decoy_capture.cli.simulate_traffic \
  --target 127.0.0.1:3307 --rounds 3

# 3) 导入固定样本（覆盖 R01–R05 与三类告警，幂等）
/tmp/dbh-venv/bin/python -m m2_decoy_capture.cli.import_samples --set demo_basic --json

# 4) 测试与静态检查
/tmp/dbh-venv/bin/python -m pytest modules/m2-decoy-capture/tests -q
/tmp/dbh-venv/bin/python -m ruff check modules/m2-decoy-capture
```

**期望输出**：模拟器每轮读操作成功、写操作返回 `1142`；`import_samples` 首次导入
新增会话/事件/告警，重复导入全部走幂等（`deduped`）；pytest 全绿。

## 5. 验收证据

索引见 [`evidence/README.md`](evidence/README.md)：

- [`evidence/session-events.md`](evidence/session-events.md)：同一会话 16 条事件完整还原
  （连接 → 8 次认证失败 → 5 次 SELECT → 被拒 DROP → 断开），并对应到 R02/R04/R05 与 3 条告警；
- [`evidence/explain-diff.md`](evidence/explain-diff.md)：时间线查询 `ALL → ref`
  （扫描行数 2432 → 16）、增量拉取 `ALL → range`（`key_len` 36 → 44）、溯源命中
  `idx_log_source_time`；
- [`evidence/session-events.sql`](evidence/session-events.sql)、[`evidence/explain_variants.py`](evidence/explain_variants.py)：
  可直接执行的只读查询与对比脚本。

## 6. 边界与限制

- **不建表、不写规则**：DDL 归 M1/M3，规则/评分/告警归 M4；M2 只产出事件。
- **不拥有视图**：四视图口径归 M5，M2 仅用 EXPLAIN 验证其查询路径。
- **模拟器限授权环境**：`simulate_traffic` 只连本机诱饵，不得指向真实数据库。
- **已知漂移**：`explain_diff.py` 目前把 JSON 写到仓库根 `db/explain/`（历史路径），
  归档时需手动复制到 `evidence/explain/`；已在 `docs/test-plan.md` 登记为已知限制。

## 7. 最近验证

| 项 | 结果 | 时间 |
| --- | --- | --- |
| `pytest modules/m2-decoy-capture/tests -q` | 16 passed | 2026-11-25 |
| `ruff check modules/m2-decoy-capture` | All checks passed | 2026-11-25 |
| `simulate_traffic --rounds 3` | 每轮写操作均 1142 被拒 | 2026-11-25 |
| 样本会话事件/命中/告警 | 16 条事件、3 条命中、3 条告警，与预期一致 | 2026-11-25 |
