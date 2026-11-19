"""固定合成样本目录（S01–S07 与 demo_basic / recon_only 集合）。

设计约束（`specs/001-database-honeypot/contracts/api.md` 第 4 章、
`contracts/events.md` 第 3/4 章）：

1. **完全固定**：每个事件的 `event_uuid` 与 `session_id` 都是代码里预先写定的
   UUIDv4 文本，重复导入同一 ``sample_id`` 得到完全一致的事件序列；幂等由
   ``attack_log.event_uuid`` 唯一约束裁决（同一事件不会重复计数、重复分析）。
2. **只存不执行**：样本中的 SQL 只是字符串夹具，导入脚本不会把它交给任何数据库
   驱动执行；认证样本只保存合成标识 ``TEST-ONLY-*``，不出现真实口令。
3. **来源固定**：全部来源使用 RFC 5737 文档保留网段 ``198.51.100.0/24``，
   与真实环境隔离；不同样本/边界分组使用不同地址，避免时间窗口互相污染。
4. **预期可核对**：每个样本都声明预期规则命中、会话风险分/等级与告警
   （R02→medium、R04→high、R05→critical，固定映射见 events.md 6.5）。

编号口径说明：本目录按任务要求采用「S01 闭环 / S02 认证失败边界 / S03 拖库 /
S04 破坏性 / S05 扫描 / S06 综合 / S07 阈值边界」的编号；`contracts/api.md` 4.3
的旧编号表存在差异，但五条规则与告警映射语义仍严格遵循该契约。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.events import CapturedEvent, EventStatus, EventType
from app.services.risk import risk_level
from app.utils.sql import normalize_sql

# 样本基准时刻（UTC naive，与 DATETIME(6) 口径一致）。
# 选择 2026-11-18 与 gen_demo_data 的 2026-11-01 数据错开，避免窗口统计互相影响。
_BASE_TIME = datetime(2026, 11, 18, 1, 0, 0)

# 允许使用的来源网段（RFC 5737 TEST-NET-2，文档保留地址，不指向任何真实主机）
_SOURCE_NET = "198.51.100."


# ---------------------------------------------------------------------------
# 数据类：事件、告警预期、会话预期与样本
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventSpec:
    """一条固定样本事件（尚未入库；字段与 `CapturedEvent` 对应）。"""

    event_uuid: str
    session_id: str
    event_type: EventType
    source_ip: str
    event_time: datetime
    status: EventStatus
    source_port: int | None = None
    username: str | None = None
    credential_test_id: str | None = None
    sql_statement: str | None = None
    normalized_sql: str | None = None
    returned_rows: int = 0
    response_ms: int = 0
    client_info: str | None = None
    payload_truncated: bool = False

    def to_captured_event(self) -> CapturedEvent:
        """转换为捕获层标准事件对象（不会触发任何 SQL 执行）。"""
        return CapturedEvent(
            event_uuid=self.event_uuid,
            session_id=self.session_id,
            event_type=self.event_type,
            source_ip=self.source_ip,
            source_port=self.source_port,
            username=self.username,
            credential_test_id=self.credential_test_id,
            sql_statement=self.sql_statement,
            normalized_sql=self.normalized_sql,
            event_time=self.event_time,
            returned_rows=self.returned_rows,
            response_ms=self.response_ms,
            status=self.status,
            payload_truncated=self.payload_truncated,
            client_info=self.client_info,
        )


@dataclass(frozen=True)
class AlertExpectation:
    """一条预期告警（等级为规则固定映射，不是按分数区间计算）。"""

    rule_code: str
    alert_type: str
    severity: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_code": self.rule_code,
            "alert_type": self.alert_type,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class SessionExpectation:
    """单个会话的预期结果。"""

    session_id: str
    expected_hits: tuple[str, ...]
    expected_risk_score: int
    expected_alerts: tuple[AlertExpectation, ...] = ()

    @property
    def expected_risk_level(self) -> str:
        return risk_level(self.expected_risk_score)


@dataclass(frozen=True)
class Sample:
    """一个固定样本：事件序列 + 预期规则/分数/告警。"""

    sample_id: str
    title: str
    description: str
    events: tuple[EventSpec, ...]
    expected_hits: tuple[str, ...]
    expected_risk_score: int
    expected_alerts: tuple[AlertExpectation, ...]
    expected_sessions: tuple[SessionExpectation, ...]
    boundary_note: str = ""

    @property
    def expected_risk_level(self) -> str:
        return risk_level(self.expected_risk_score)

    @property
    def session_ids(self) -> tuple[str, ...]:
        """按出现顺序去重的会话编号。"""
        seen: list[str] = []
        for event in self.events:
            if event.session_id not in seen:
                seen.append(event.session_id)
        return tuple(seen)

    def expected_summary(self) -> dict[str, object]:
        """返回机器可读的预期摘要（供导入脚本与测试对照）。"""
        return {
            "sample_id": self.sample_id,
            "title": self.title,
            "event_count": len(self.events),
            "session_count": len(self.session_ids),
            "rule_hits": list(self.expected_hits),
            "risk_score": self.expected_risk_score,
            "risk_level": self.expected_risk_level,
            "alerts": [alert.as_dict() for alert in self.expected_alerts],
            "sessions": [
                {
                    "session_id": item.session_id,
                    "rule_hits": list(item.expected_hits),
                    "risk_score": item.expected_risk_score,
                    "risk_level": item.expected_risk_level,
                    "alerts": [alert.as_dict() for alert in item.expected_alerts],
                }
                for item in self.expected_sessions
            ],
            "boundary_note": self.boundary_note,
        }


# ---------------------------------------------------------------------------
# 固定 UUID 与时间构造工具
# ---------------------------------------------------------------------------


def _event_uuid(sample_no: int, sequence: int) -> str:
    """构造固定的 UUIDv4 文本事件键：第 1 组编码样本号，末组编码序号。"""
    return f"e1{sample_no:02d}{sequence:04d}-0000-4000-8000-{sequence:012d}"


def _session_uuid(sample_no: int, session_no: int) -> str:
    """构造固定的 UUIDv4 文本会话编号：第 1 组编码样本号，末组编码会话序号。"""
    return f"5a{sample_no:02d}{session_no:04d}-0000-4000-8000-{session_no:012d}"


def _at(hour: int, minute: int = 0) -> datetime:
    """样本内部基准时间：2026-11-18 的第 hour 点（UTC）。"""
    return _BASE_TIME.replace(hour=hour, minute=minute)


def _alert(rule_code: str, alert_type: str, severity: str) -> AlertExpectation:
    return AlertExpectation(rule_code=rule_code, alert_type=alert_type, severity=severity)


class _SampleBuilder:
    """样本事件构造器：自动递增事件序号与事件时间，保证固定且可复现。"""

    def __init__(self, sample_no: int) -> None:
        self.sample_no = sample_no
        self._sequence = 0
        self._session_no = 0
        self._source_ip = ""
        self._start = _BASE_TIME
        self._offset = -1

    def session(self, session_no: int, source_ip: str, start: datetime) -> _SampleBuilder:
        """切换到指定会话；后续事件时间从 start 起每秒递增。"""
        self._session_no = session_no
        self._source_ip = source_ip
        self._start = start
        self._offset = -1
        return self

    def _add(
        self,
        event_type: EventType,
        *,
        status: EventStatus = EventStatus.SUCCESS,
        sql_statement: str | None = None,
        returned_rows: int = 0,
        response_ms: int = 0,
        username: str | None = None,
        credential_test_id: str | None = None,
    ) -> EventSpec:
        self._sequence += 1
        self._offset += 1
        return EventSpec(
            event_uuid=_event_uuid(self.sample_no, self._sequence),
            session_id=_session_uuid(self.sample_no, self._session_no),
            event_type=event_type,
            source_ip=self._source_ip,
            source_port=50000 + self._session_no * 100 + (self._offset % 100),
            event_time=self._start + timedelta(seconds=self._offset),
            status=status,
            username=username,
            credential_test_id=credential_test_id,
            sql_statement=sql_statement,
            normalized_sql=normalize_sql(sql_statement),
            returned_rows=returned_rows,
            response_ms=response_ms,
            client_info="固定合成样本（TEST-ONLY，不含真实客户端信息）",
        )

    def connect(self) -> EventSpec:
        """追加 connect 事件（样本中的连接事件恒为 success）。"""
        return self._add(EventType.CONNECT)

    def auth(
        self,
        username: str,
        credential_test_id: str,
        *,
        status: EventStatus = EventStatus.SUCCESS,
    ) -> EventSpec:
        """追加 auth 事件；只保存用户名与合成凭据标识，绝不保存口令。"""
        return self._add(
            EventType.AUTH,
            status=status,
            username=username,
            credential_test_id=credential_test_id,
        )

    def query(
        self,
        sql_statement: str,
        *,
        status: EventStatus = EventStatus.SUCCESS,
        returned_rows: int = 0,
        response_ms: int = 2,
    ) -> EventSpec:
        """追加 query 事件（SQL 仅作为字符串保存，绝不执行）。"""
        return self._add(
            EventType.QUERY,
            status=status,
            sql_statement=sql_statement,
            returned_rows=returned_rows,
            response_ms=response_ms,
        )

    def disconnect(self, *, status: EventStatus = EventStatus.SUCCESS) -> EventSpec:
        """追加 disconnect 事件。"""
        return self._add(EventType.DISCONNECT, status=status)


def _session_expectation(
    sample_no: int,
    session_no: int,
    hits: tuple[str, ...],
    risk_score: int,
    alerts: tuple[AlertExpectation, ...] = (),
) -> SessionExpectation:
    return SessionExpectation(
        session_id=_session_uuid(sample_no, session_no),
        expected_hits=hits,
        expected_risk_score=risk_score,
        expected_alerts=alerts,
    )


# ---------------------------------------------------------------------------
# S01 样本闭环：连接 + 认证 + 查看表列表，仅命中 R03
# ---------------------------------------------------------------------------


def _build_s01() -> Sample:
    builder = _SampleBuilder(1).session(1, _SOURCE_NET + "11", _at(1))
    events = [
        builder.connect(),
        builder.auth("s01_synthetic_reader", "TEST-ONLY-S01-AUTH"),
        builder.query("SHOW TABLES", returned_rows=3, response_ms=3),
        builder.disconnect(),
    ]
    return Sample(
        sample_id="S01",
        title="样本闭环：连接 + 认证 + 查看表列表",
        description=(
            "一次完整会话包含 connect/auth/query/disconnect，仅 SHOW TABLES 触发 R03"
            "（recon +15），会话风险分 15、等级 low、不生成告警。"
        ),
        events=tuple(events),
        expected_hits=("R03",),
        expected_risk_score=15,
        expected_alerts=(),
        expected_sessions=(_session_expectation(1, 1, ("R03",), 15),),
    )


# ---------------------------------------------------------------------------
# S02 认证失败序列：R02 阈值边界内 / 外各一组
# ---------------------------------------------------------------------------

_S02_USERS = ("svc_backup", "svc_report", "svc_admin", "root", "legacy_app", "demo_admin")


def _build_s02() -> Sample:
    # 注意：同一批次必须复用同一个 builder，事件序号才会全局递增；
    # 若每个会话各起一个 builder，会让不同会话的事件 UUID 重复而触发幂等跳过。
    builder = _SampleBuilder(2)

    # 边界内：8 次失败认证、8 组不同凭据组合（>= 5），触发 R02（bruteforce +25）
    builder.session(1, _SOURCE_NET + "12", _at(2))
    events = [builder.connect()]
    for index in range(8):
        events.append(
            builder.auth(
                _S02_USERS[index % len(_S02_USERS)],
                f"TEST-ONLY-S02-A{index + 1}",
                status=EventStatus.FAILURE,
            )
        )
    events.append(builder.disconnect(status=EventStatus.FAILURE))

    # 边界外：仅 7 次失败认证（< 8），不触发 R02；另用独立来源地址隔离窗口
    builder.session(2, _SOURCE_NET + "13", _at(2, minute=10))
    events2 = [builder.connect()]
    for index in range(7):
        events2.append(
            builder.auth(
                _S02_USERS[index % len(_S02_USERS)],
                f"TEST-ONLY-S02-B{index + 1}",
                status=EventStatus.FAILURE,
            )
        )
    events2.append(builder.disconnect(status=EventStatus.FAILURE))

    return Sample(
        sample_id="S02",
        title="失败认证序列：R02 阈值边界内/外各一组",
        description=(
            "边界内：8 次失败认证、8 组凭据（达到 8 次/5 组阈值）命中 R02，"
            "会话 25 分、medium 告警；边界外：7 次失败认证不命中。"
        ),
        events=tuple(events + events2),
        expected_hits=("R02",),
        expected_risk_score=25,
        expected_alerts=(_alert("R02", "bruteforce", "medium"),),
        expected_sessions=(
            _session_expectation(2, 1, ("R02",), 25, (_alert("R02", "bruteforce", "medium"),)),
            _session_expectation(2, 2, (), 0),
        ),
        boundary_note="R02：认证尝试 >= 8 且不同凭据组合 >= 5；7 次为边界外。",
    )


# ---------------------------------------------------------------------------
# S03 拖库：连续 SELECT + 大量返回行，命中 R04
# ---------------------------------------------------------------------------


def _build_s03() -> Sample:
    builder = _SampleBuilder(3).session(1, _SOURCE_NET + "14", _at(3))
    events = [
        builder.connect(),
        builder.auth("s03_synthetic_reader", "TEST-ONLY-S03-AUTH"),
    ]
    for index in range(5):
        events.append(
            builder.query(
                f"SELECT id, order_no, amount FROM fake_orders LIMIT {100 + index * 50}",
                returned_rows=200,
                response_ms=8,
            )
        )
    events.append(builder.disconnect())
    return Sample(
        sample_id="S03",
        title="拖库：连续 SELECT 批量读取",
        description=(
            "同一会话窗口内连续 5 次 SELECT 且累计返回 1000 行，命中 R04"
            "（data_dump +25），生成 data_dump/high 告警。"
        ),
        events=tuple(events),
        expected_hits=("R04",),
        expected_risk_score=25,
        expected_alerts=(_alert("R04", "data_dump", "high"),),
        expected_sessions=(
            _session_expectation(3, 1, ("R04",), 25, (_alert("R04", "data_dump", "high"),)),
        ),
    )


# ---------------------------------------------------------------------------
# S04 破坏性：被拒绝的 DROP TABLE，命中 R05
# ---------------------------------------------------------------------------


def _build_s04() -> Sample:
    builder = _SampleBuilder(4).session(1, _SOURCE_NET + "15", _at(4))
    events = [
        builder.connect(),
        builder.auth("s04_synthetic_writer", "TEST-ONLY-S04-AUTH"),
        builder.query("DROP TABLE fake_orders", status=EventStatus.DENIED),
        builder.disconnect(status=EventStatus.FAILURE),
    ]
    return Sample(
        sample_id="S04",
        title="破坏性写操作：DROP TABLE 被拒绝",
        description=(
            "诱饵层拒绝执行 DROP，事件状态 denied；命中 R05（destructive +35），"
            "会话 35 分、medium，生成 destructive/critical 告警。"
        ),
        events=tuple(events),
        expected_hits=("R05",),
        expected_risk_score=35,
        expected_alerts=(_alert("R05", "destructive", "critical"),),
        expected_sessions=(
            _session_expectation(4, 1, ("R05",), 35, (_alert("R05", "destructive", "critical"),)),
        ),
    )


# ---------------------------------------------------------------------------
# S05 扫描：60 秒内 10 次 connect 且无有效 SQL，命中 R01
# ---------------------------------------------------------------------------


def _build_s05() -> Sample:
    builder = _SampleBuilder(5).session(1, _SOURCE_NET + "16", _at(5))
    events = [builder.connect() for _ in range(10)]
    events.append(builder.disconnect())
    return Sample(
        sample_id="S05",
        title="端口/服务扫描：60 秒内 10 次 connect",
        description=(
            "60 秒内同一来源 10 次 connect，且没有任何成功 SQL；命中 R01"
            "（scanning +10），会话 10 分、low，不生成告警。"
        ),
        events=tuple(events),
        expected_hits=("R01",),
        expected_risk_score=10,
        expected_alerts=(),
        expected_sessions=(_session_expectation(5, 1, ("R01",), 10),),
        boundary_note="R01：connect 数 >= 10 且窗口内有效 SQL <= 0；样本恰为 10 次。",
    )


# ---------------------------------------------------------------------------
# S06 综合：R02 + R04 + R05，会话风险分 85（critical）
# ---------------------------------------------------------------------------

_S06_USERS = ("svc_backup", "svc_report", "svc_admin", "root", "legacy_app", "demo_admin")


def _build_s06() -> Sample:
    builder = _SampleBuilder(6).session(1, _SOURCE_NET + "17", _at(6))
    events = [builder.connect()]
    for index in range(8):
        events.append(
            builder.auth(
                _S06_USERS[index % len(_S06_USERS)],
                f"TEST-ONLY-S06-A{index + 1}",
                status=EventStatus.FAILURE,
            )
        )
    for index in range(5):
        events.append(
            builder.query(
                f"SELECT email, phone FROM fake_users LIMIT {20 + index * 10}",
                returned_rows=180,
                response_ms=6,
            )
        )
    events.append(builder.query("DROP TABLE fake_users", status=EventStatus.DENIED))
    events.append(builder.disconnect(status=EventStatus.FAILURE))

    alerts = (
        _alert("R02", "bruteforce", "medium"),
        _alert("R04", "data_dump", "high"),
        _alert("R05", "destructive", "critical"),
    )
    return Sample(
        sample_id="S06",
        title="综合攻击：爆破 + 拖库 + 破坏性操作",
        description=(
            "同一来源先 8 次失败认证触发 R02，再连续 5 次 SELECT 触发 R04，"
            "最后 DROP 被拒绝触发 R05；会话风险分 85、等级 critical，生成 3 条告警。"
        ),
        events=tuple(events),
        expected_hits=("R02", "R04", "R05"),
        expected_risk_score=85,
        expected_alerts=alerts,
        expected_sessions=(_session_expectation(6, 1, ("R02", "R04", "R05"), 85, alerts),),
    )


# ---------------------------------------------------------------------------
# S07 阈值边界与重复导入幂等
# ---------------------------------------------------------------------------


def _build_s07() -> Sample:
    events: list[EventSpec] = []
    # 同一 builder 贯穿 7 个边界分组，保证事件序号全局唯一（避免跨组 UUID 重复）。
    builder = _SampleBuilder(7)

    # G1：R01 边界内（恰好 10 次 connect）
    builder.session(1, _SOURCE_NET + "18", _at(7))
    events.append(builder.connect())
    events.extend(builder.connect() for _ in range(9))
    events.append(builder.disconnect())

    # G2：R01 边界外（9 次 connect，差 1 次）
    builder.session(2, _SOURCE_NET + "19", _at(7, minute=10))
    events.append(builder.connect())
    events.extend(builder.connect() for _ in range(8))
    events.append(builder.disconnect())

    # G3：R02 边界内（8 次认证、5 组凭据）
    builder.session(3, _SOURCE_NET + "20", _at(7, minute=20))
    events.append(builder.connect())
    for index in range(8):
        username = _S02_USERS[index % 5]
        events.append(
            builder.auth(
                username, f"TEST-ONLY-S07-C-{username.upper()}", status=EventStatus.FAILURE
            )
        )
    events.append(builder.disconnect(status=EventStatus.FAILURE))

    # G4：R02 边界外（7 次认证，未达 8 次）
    builder.session(4, _SOURCE_NET + "21", _at(7, minute=30))
    events.append(builder.connect())
    for index in range(7):
        username = _S02_USERS[index % 5]
        events.append(
            builder.auth(
                username, f"TEST-ONLY-S07-D-{username.upper()}", status=EventStatus.FAILURE
            )
        )
    events.append(builder.disconnect(status=EventStatus.FAILURE))

    # G5：R02 边界外（8 次认证，但只有 4 组凭据）
    builder.session(5, _SOURCE_NET + "22", _at(7, minute=40))
    events.append(builder.connect())
    for index in range(8):
        username = _S02_USERS[index % 4]
        events.append(
            builder.auth(
                username, f"TEST-ONLY-S07-E-{username.upper()}", status=EventStatus.FAILURE
            )
        )
    events.append(builder.disconnect(status=EventStatus.FAILURE))

    # G6：R04 边界内（恰好 5 次连续 SELECT）
    builder.session(6, _SOURCE_NET + "23", _at(7, minute=50))
    events.append(builder.connect())
    for index in range(5):
        events.append(
            builder.query(
                f"SELECT id, amount FROM fake_orders LIMIT {10 + index * 10}",
                returned_rows=10,
                response_ms=3,
            )
        )
    events.append(builder.disconnect())

    # G7：R04 边界外（4 次连续 SELECT，差 1 次）
    builder.session(7, _SOURCE_NET + "24", _at(7, minute=55))
    events.append(builder.connect())
    for index in range(4):
        events.append(
            builder.query(
                f"SELECT id, amount FROM fake_orders LIMIT {10 + index * 10}",
                returned_rows=10,
                response_ms=3,
            )
        )
    events.append(builder.disconnect())

    alerts = (
        _alert("R02", "bruteforce", "medium"),
        _alert("R04", "data_dump", "high"),
    )
    return Sample(
        sample_id="S07",
        title="阈值边界与重复导入幂等",
        description=(
            "同时给出 R01/R02/R04 的边界内与边界外序列：边界内分别命中 R01、R02、R04，"
            "边界外均不命中；配合 --repeat 可验证同一 event_uuid 重复导入完全幂等。"
        ),
        events=tuple(events),
        expected_hits=("R01", "R02", "R04"),
        expected_risk_score=25,
        expected_alerts=alerts,
        expected_sessions=(
            _session_expectation(7, 1, ("R01",), 10),
            _session_expectation(7, 2, (), 0),
            _session_expectation(7, 3, ("R02",), 25, (alerts[0],)),
            _session_expectation(7, 4, (), 0),
            _session_expectation(7, 5, (), 0),
            _session_expectation(7, 6, ("R04",), 25, (alerts[1],)),
            _session_expectation(7, 7, (), 0),
        ),
        boundary_note=(
            "R01 10/9、R02 8 次 5 组 / 7 次 / 8 次 4 组、R04 5/4 条连续 SELECT，"
            "分别覆盖阈值内与差一单位的阈值外。"
        ),
    )


# ---------------------------------------------------------------------------
# 对外目录与集合
# ---------------------------------------------------------------------------

SAMPLES: dict[str, Sample] = {
    sample.sample_id: sample
    for sample in (
        _build_s01(),
        _build_s02(),
        _build_s03(),
        _build_s04(),
        _build_s05(),
        _build_s06(),
        _build_s07(),
    )
}

# 样本组：demo_basic 覆盖全部五条规则；recon_only 为契约保留的轻量集合。
GROUPS: dict[str, tuple[str, ...]] = {
    "demo_basic": ("S01", "S02", "S03", "S04", "S05", "S06", "S07"),
    "recon_only": ("S01", "S02", "S03"),
}

SAMPLE_IDS: tuple[str, ...] = tuple(SAMPLES)


def get_sample(sample_id: str) -> Sample:
    """按编号取样本；不存在时抛出 KeyError（由 CLI 转成参数错误）。"""
    key = sample_id.strip().upper()
    if key not in SAMPLES:
        raise KeyError(f"未知样本编号 {sample_id!r}，可选：{', '.join(SAMPLE_IDS)}")
    return SAMPLES[key]


def get_group(group_name: str) -> tuple[Sample, ...]:
    """按组名取样本列表；不存在时抛出 KeyError。"""
    key = group_name.strip().lower()
    if key not in GROUPS:
        raise KeyError(f"未知样本组 {group_name!r}，可选：{', '.join(GROUPS)}")
    return tuple(SAMPLES[sample_id] for sample_id in GROUPS[key])


def expected_rule_coverage() -> dict[str, list[str]]:
    """返回「规则编码 → 命中该规则的样本编号」，便于核对 SC-004 覆盖。"""
    coverage: dict[str, list[str]] = {}
    for sample in SAMPLES.values():
        for rule_code in sample.expected_hits:
            coverage.setdefault(rule_code, []).append(sample.sample_id)
    return dict(sorted(coverage.items()))


__all__ = [
    "AlertExpectation",
    "EventSpec",
    "GROUPS",
    "SAMPLES",
    "SAMPLE_IDS",
    "Sample",
    "SessionExpectation",
    "expected_rule_coverage",
    "get_group",
    "get_sample",
]
