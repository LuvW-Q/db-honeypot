"""固定合成样本包：对外导出 S01–S07 目录与 demo_basic / recon_only 集合。

只包含静态夹具，不连接数据库、不执行任何 SQL；导入动作由
``app.cli.import_samples`` 通过 ``IngestService`` 完成。
"""

from __future__ import annotations

from app.cli.samples.catalog import (
    GROUPS,
    SAMPLE_IDS,
    SAMPLES,
    AlertExpectation,
    EventSpec,
    Sample,
    SessionExpectation,
    expected_rule_coverage,
    get_group,
    get_sample,
)

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
