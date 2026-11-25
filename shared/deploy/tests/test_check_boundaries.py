"""``shared.deploy.check_boundaries`` 的单元测试（临时目录构造依赖矩阵）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.deploy import check_boundaries as boundaries
from shared.deploy.check_boundaries import find_cycles, scan


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """最小合法多包仓库骨架（仅用于扫描 import 关系）。"""
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
    _write(tmp_path / "Makefile", "help:\n\t@true\n")
    _write(tmp_path / "shared" / "__init__.py", "")
    _write(tmp_path / "shared" / "config.py", "VALUE = 1\n")
    packages = {
        "m1-transaction-integration": "m1_transaction_integration",
        "m2-decoy-capture": "m2_decoy_capture",
        "m4-rules-derived": "m4_rules_derived",
        "m5-views-console": "m5_views_console",
    }
    for module_dir, package in packages.items():
        base = tmp_path / "modules" / module_dir / package
        _write(base / "__init__.py", "")
        _write(base / "public.py", "")
    _write(
        tmp_path
        / "modules"
        / "m1-transaction-integration"
        / "m1_transaction_integration"
        / "api"
        / "__init__.py",
        "",
    )
    _write(
        tmp_path / "modules" / "m4-rules-derived" / "m4_rules_derived" / "analysis.py",
        "",
    )
    (tmp_path / "modules" / "m3-er-constraints" / "tests").mkdir(parents=True)
    return tmp_path


def _rules(report: boundaries.ScanReport) -> list[str]:
    return [item.rule for item in report.violations]


def test_public_facade_imports_are_allowed(repo: Path) -> None:
    """M1→M4、M2→M1 只能经公开门面，合法调用不得报违规。"""
    _write(
        repo
        / "modules"
        / "m1-transaction-integration"
        / "m1_transaction_integration"
        / "api"
        / "routes.py",
        "from m4_rules_derived import public as rules_engine\n",
    )
    _write(
        repo / "modules" / "m2-decoy-capture" / "m2_decoy_capture" / "emitter.py",
        "from m1_transaction_integration import public as transaction_api\n",
    )
    report = scan(paths=["shared", "modules"], root=repo)
    assert report.result == "pass", [item.as_dict() for item in report.violations]


def test_cross_module_internal_import_flagged(repo: Path) -> None:
    """M1 直接导入 M4 内部子模块必须报 cross_module_internal 并带 file:line。"""
    _write(
        repo
        / "modules"
        / "m1-transaction-integration"
        / "m1_transaction_integration"
        / "api"
        / "routes.py",
        "import m4_rules_derived.analysis as analysis_module\n",
    )
    report = scan(paths=["shared", "modules"], root=repo)
    assert "cross_module_internal" in _rules(report)
    violation = next(item for item in report.violations if item.rule == "cross_module_internal")
    assert violation.file.endswith("api/routes.py")
    assert violation.line == 1
    assert "m4_rules_derived" in violation.import_name


def test_reverse_dependency_flagged(repo: Path) -> None:
    """M4 反向依赖 M1 必须报 forbidden_edge。"""
    _write(
        repo / "modules" / "m4-rules-derived" / "m4_rules_derived" / "rules.py",
        "from m1_transaction_integration import public\n",
    )
    report = scan(paths=["shared", "modules"], root=repo)
    assert "forbidden_edge" in _rules(report)


def test_shared_must_not_import_modules(repo: Path) -> None:
    """shared 被所有模块依赖，自己不得反向导入任何模块。"""
    _write(
        repo / "shared" / "bad.py",
        "import m1_transaction_integration\n",
    )
    report = scan(paths=["shared", "modules"], root=repo)
    assert "shared_imports_module" in _rules(report)


def test_legacy_prefix_flagged(repo: Path) -> None:
    """旧布局前缀 app./backend. 必须报 legacy_prefix。"""
    _write(
        repo / "shared" / "bad.py",
        "from app.services import x\nimport backend.models\n",
    )
    report = scan(paths=["shared", "modules"], root=repo)
    assert _rules(report).count("legacy_prefix") == 2
    assert len(report.legacy_imports) == 2


def test_m3_shared_import_scope(repo: Path) -> None:
    """M3 只在 tests/、tools/ 中允许导入 shared。"""
    bad = repo / "modules" / "m3-er-constraints" / "er" / "schema.py"
    _write(bad, "from shared.config import VALUE\n")
    report = scan(paths=["shared", "modules"], root=repo)
    assert "shared_import_scope" in _rules(report)
    # tests/ 下允许
    bad.unlink()
    _write(
        repo / "modules" / "m3-er-constraints" / "tests" / "test_x.py",
        "from shared.config import VALUE\n",
    )
    report2 = scan(paths=["shared", "modules"], root=repo)
    assert report2.result == "pass", [item.as_dict() for item in report2.violations]


def test_m5_shared_import_scope(repo: Path) -> None:
    """M5 只在 cli/、tests/ 中允许导入 shared。"""
    bad = repo / "modules" / "m5-views-console" / "m5_views_console" / "api" / "x.py"
    _write(bad, "from shared.config import VALUE\n")
    report = scan(paths=["shared", "modules"], root=repo)
    assert "shared_import_scope" in _rules(report)
    bad.unlink()
    _write(
        repo / "modules" / "m5-views-console" / "m5_views_console" / "cli" / "__init__.py",
        "",
    )
    _write(
        repo / "modules" / "m5-views-console" / "m5_views_console" / "cli" / "verify_views.py",
        "from shared.config import VALUE\n",
    )
    report2 = scan(paths=["shared", "modules"], root=repo)
    assert report2.result == "pass", [item.as_dict() for item in report2.violations]


def test_relative_import_within_package_allowed(repo: Path) -> None:
    """同包内相对导入不得报违规。"""
    _write(
        repo
        / "modules"
        / "m1-transaction-integration"
        / "m1_transaction_integration"
        / "api"
        / "routes.py",
        "from ..schemas import api\n\n__all__ = ['api']\n",
    )
    report = scan(paths=["shared", "modules"], root=repo)
    assert report.result == "pass", [item.as_dict() for item in report.violations]


@pytest.mark.parametrize(
    ("graph", "expected"),
    [
        ({}, False),
        ({"M1": {"M2"}, "M2": set()}, False),
        ({"M1": {"M2"}, "M2": {"M1"}}, True),
        ({"M1": {"M2"}, "M2": {"M4"}, "M4": {"M1"}}, True),
    ],
)
def test_find_cycles(graph: dict[str, set[str]], expected: bool) -> None:
    """包级依赖图找环。"""
    assert bool(find_cycles(graph)) is expected


def test_current_repo_passes_boundary_gate() -> None:
    """当前仓库必须通过边界门禁（真实违规由业务负责人修复，不放行）。"""
    report = scan()
    assert report.result == "pass", "\n".join(
        f"{item.file}:{item.line}: {item.import_name}（{item.rule}）{item.message}"
        for item in report.violations
    )


def test_boundary_check_alias_module_reexports() -> None:
    """契约文件名 ``boundary_check`` 必须与实现模块行为一致。"""
    from shared.deploy import boundary_check, check_boundaries

    assert boundary_check.scan is check_boundaries.scan
    assert boundary_check.main is check_boundaries.main
    assert boundary_check.ALLOWED_EDGES == check_boundaries.ALLOWED_EDGES
