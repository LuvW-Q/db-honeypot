"""结构门禁测试（T042）：五模块目录、README/证据目录、旧目录与依赖残留。

直接复用 `shared/deploy/check_structure.py` 的检查实现，避免测试与门禁出现两套口径。
运行：`pytest tests/test_module_structure.py -q`
"""

from __future__ import annotations

from pathlib import Path

from shared.deploy import check_structure

REPO = Path(__file__).resolve().parents[1]
MODULES = [
    "m1-transaction-integration",
    "m2-decoy-capture",
    "m3-er-constraints",
    "m4-rules-derived",
    "m5-views-console",
]


def test_structure_has_no_blocking_failures() -> None:
    """结构检查不得出现 FAIL（WARN 允许，代表待交付项）。"""
    items = check_structure.run_checks(REPO)
    summary = check_structure.summarize(items)
    failures = [item for item in items if item.status == check_structure.STATUS_FAIL]
    assert not failures, "\n".join(
        f"{item.title}: {item.lines}" for item in failures[:10]
    )
    assert summary[check_structure.STATUS_FAIL] == 0
    assert check_structure.passed(items)


def test_five_module_dirs_with_readme_and_evidence() -> None:
    """五个模块目录必须存在，且各自有 README 与 evidence 目录。"""
    for name in MODULES:
        base = REPO / "modules" / name
        assert base.is_dir(), f"缺少模块目录 {base}"
        assert (base / "README.md").is_file(), f"{name} 缺少 README.md"
        assert (base / "evidence").is_dir(), f"{name} 缺少 evidence/"


def test_no_legacy_top_level_dirs() -> None:
    """旧布局目录不得复活。"""
    for legacy in ("backend", "app", "frontend", "scripts"):
        assert not (REPO / legacy).exists(), f"发现旧目录 {legacy}/"


def test_shared_package_is_flat() -> None:
    """shared 包根即 shared/，不得嵌套 shared/shared。"""
    assert (REPO / "shared" / "__init__.py").is_file()
    assert not (REPO / "shared" / "shared").exists()
