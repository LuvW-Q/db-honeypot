"""``shared.deploy.check_structure`` 的单元测试（临时目录构造正/反例）。"""

from __future__ import annotations

from pathlib import Path

from shared.deploy import check_structure as structure
from shared.deploy.check_structure import (
    CheckItem,
    Component,
    find_repo_root,
    passed,
    run_checks,
)


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _minimal_repo(root: Path) -> None:
    """构造可通过根目录检查的最小仓库骨架。"""
    _write(root / "pyproject.toml", "[project]\nname='x'\n")
    _write(root / "Makefile", "help:\n\t@true\n")
    _write(
        root / "alembic.ini",
        "[alembic]\nscript_location=modules/m1-transaction-integration/migrations\n",
    )
    _write(root / "conftest.py", "")
    _write(root / "compose.yaml", "services: {}\n")
    _write(root / ".env.example", "WEB_DIST_DIR=modules/m5-views-console/frontend/dist\n")
    _write(root / "README.md", "# x\n")
    _write(root / "shared" / "__init__.py", "")
    _write(root / "tests" / "__init__.py", "")
    (root / "modules").mkdir(parents=True, exist_ok=True)


def _statuses(items: list[CheckItem]) -> dict[str, str]:
    return {item.name: item.status for item in items}


def test_current_repo_passes_structure_gate() -> None:
    """当前仓库必须通过结构门禁（待交付项只记 WARN，不阻断）。"""
    repo = find_repo_root()
    items = run_checks(repo)
    assert passed(items), "结构检查未通过：" + "; ".join(
        f"{item.name} → {item.lines}" for item in items if item.status == structure.STATUS_FAIL
    )
    # 至少覆盖根目录、组件、禁止遗留、配置一致性四类
    assert any("Makefile" in item.name for item in items)
    assert any("禁止遗留" in item.name for item in items)


def test_missing_root_file_fails(tmp_path: Path) -> None:
    """缺少 pyproject.toml 等根文件必须 FAIL。"""
    _minimal_repo(tmp_path)
    (tmp_path / "README.md").unlink()
    items = structure._check_root(tmp_path)
    assert items[0].status == structure.STATUS_FAIL
    assert any(item.status == structure.STATUS_FAIL for item in items)


def test_forbidden_legacy_dirs_detected(tmp_path: Path) -> None:
    """根目录残留 backend/ app/ frontend/ scripts/ 必须 FAIL。"""
    _minimal_repo(tmp_path)
    _write(tmp_path / "backend" / "app.py", "x = 1\n")
    _write(tmp_path / "scripts" / "demo.sh", "echo hi\n")
    items = structure._check_forbidden(tmp_path)
    legacy = next(item for item in items if "根旧目录" in item.name)
    assert legacy.status == structure.STATUS_FAIL
    assert any("backend" in line for line in legacy.lines)


def test_nested_shared_package_detected(tmp_path: Path) -> None:
    """`shared/shared/` 是旧布局残留，必须 FAIL。"""
    _minimal_repo(tmp_path)
    _write(tmp_path / "shared" / "__init__.py", "")
    _write(tmp_path / "shared" / "shared" / "__init__.py", "")
    items = structure._check_forbidden(tmp_path)
    nested = next(item for item in items if "shared/shared" in item.name)
    assert nested.status == structure.STATUS_FAIL


def test_legacy_import_prefix_detected(tmp_path: Path) -> None:
    """`app.` / `backend.` 旧导入前缀必须 FAIL。"""
    _minimal_repo(tmp_path)
    _write(tmp_path / "shared" / "bad.py", "from app.services import x\nimport backend.models\n")
    items = structure._check_forbidden(tmp_path)
    legacy = next(item for item in items if "旧导入前缀" in item.name)
    assert legacy.status == structure.STATUS_FAIL
    assert any("from app." in line for line in legacy.lines)
    assert any("import backend." in line for line in legacy.lines)


def test_absolute_user_path_in_makefile_detected(tmp_path: Path) -> None:
    """Makefile/部署脚本写死本机绝对路径必须 FAIL。"""
    _minimal_repo(tmp_path)
    _write(tmp_path / "Makefile", "PY := /Users/someone/project/.venv/bin/python\n")
    items = structure._check_forbidden(tmp_path)
    abs_path = next(item for item in items if "绝对路径" in item.name)
    assert abs_path.status == structure.STATUS_FAIL


def test_extra_python_package_detected(tmp_path: Path) -> None:
    """模块下出现多余 Python 包目录（非 tests/migrations）必须 FAIL。"""
    component_dir = tmp_path / "modules" / "t-module"
    _write(component_dir / "README.md", "# t\n")
    _write(component_dir / "t_mod" / "__init__.py", "")
    _write(component_dir / "oldpkg" / "__init__.py", "")
    component = Component(
        key="T 模块",
        directory="modules/t-module",
        package="t_mod",
        required_files=("README.md",),
        required_dirs=(),
    )
    items = structure._check_component(tmp_path, component)
    naming = next(item for item in items if "Python 包命名" in item.name)
    assert naming.status == structure.STATUS_FAIL
    assert any("oldpkg" in line for line in naming.lines)


def test_tests_and_migrations_packages_are_allowed(tmp_path: Path) -> None:
    """`tests/`、`migrations/` 作为附属 Python 包不应被判为多余包。"""
    component_dir = tmp_path / "modules" / "t-module"
    _write(component_dir / "README.md", "# t\n")
    _write(component_dir / "t_mod" / "__init__.py", "")
    _write(component_dir / "tests" / "__init__.py", "")
    _write(component_dir / "migrations" / "__init__.py", "")
    component = Component(
        key="T 模块",
        directory="modules/t-module",
        package="t_mod",
        required_files=("README.md",),
        required_dirs=(),
    )
    items = structure._check_component(tmp_path, component)
    naming = next(item for item in items if "Python 包命名" in item.name)
    assert naming.status == structure.STATUS_PASS


def test_missing_required_files_and_dirs_reported(tmp_path: Path) -> None:
    """必需文件/目录缺失分别产生 FAIL 项。"""
    component_dir = tmp_path / "modules" / "t-module"
    _write(component_dir / "t_mod" / "__init__.py", "")
    component = Component(
        key="T 模块",
        directory="modules/t-module",
        package="t_mod",
        required_files=("README.md", "t_mod/public.py"),
        required_dirs=("evidence",),
    )
    items = structure._check_component(tmp_path, component)
    statuses = _statuses(items)
    assert statuses["T 模块：必需文件"] == structure.STATUS_FAIL
    assert statuses["T 模块：必需目录"] == structure.STATUS_FAIL
    assert statuses["T 模块：Python 包命名"] == structure.STATUS_PASS


def test_pending_items_are_warn_only(tmp_path: Path) -> None:
    """待交付项缺失只能是 WARN，不阻断结构门禁。"""
    component_dir = tmp_path / "modules" / "t-module"
    _write(component_dir / "README.md", "# t\n")
    _write(component_dir / "t_mod" / "__init__.py", "")
    component = Component(
        key="T 模块",
        directory="modules/t-module",
        package="t_mod",
        required_files=("README.md",),
        required_dirs=(),
        pending=("t_mod/public.py",),
    )
    items = structure._check_component(tmp_path, component)
    pending = next(item for item in items if "待交付" in item.name)
    assert pending.status == structure.STATUS_WARN
