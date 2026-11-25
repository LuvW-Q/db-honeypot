"""所有权测试（T043）：共享能力单点定义、迁移/约束/规则/视图各归其主。

复用 `shared/deploy/check_boundaries.py` 的 AST 扫描，断言跨模块只经公开门面、
无循环依赖；再对“唯一归属”做路径级断言（迁移只在 M1、ER 只在 M3、规则只在 M4、
视图口径只在 M5、共享能力只在 shared）。
"""

from __future__ import annotations

from pathlib import Path

from shared.deploy import check_boundaries

REPO = Path(__file__).resolve().parents[1]


def test_boundary_scan_is_clean() -> None:
    """依赖边界扫描：违规 0、扫描错误 0、无循环依赖。"""
    report = check_boundaries.scan(root=REPO)
    assert report.result == "pass", [v.as_dict() for v in report.violations[:10]]
    assert report.violations == []
    assert report.scan_errors == []
    assert report.scanned_files >= 80


def test_cross_module_edges_only_use_public_facades() -> None:
    """跨模块导入只允许 M1→M4.public、M2→M1.public。"""
    report = check_boundaries.scan(root=REPO)
    offenders = [
        v
        for v in report.violations
        if v.rule == check_boundaries.RULE_CROSS_MODULE_INTERNAL
    ]
    assert not offenders, [v.as_dict() for v in offenders]


def test_shared_capabilities_defined_once() -> None:
    """脱敏/评分/配置/连接/日志只在 shared 定义，模块内不得复制同名实现。"""
    shared_files = {
        path.name
        for path in (REPO / "shared").rglob("*.py")
        if path.name != "__init__.py"
    }
    assert {"config.py", "logging.py"} <= shared_files
    for forbidden in ("config.py", "logging.py"):
        copies = [
            path
            for path in (REPO / "modules").rglob(f"*/{forbidden}")
            if "tests" not in path.parts
        ]
        assert not copies, f"{forbidden} 只应在 shared 定义，发现副本：{copies}"


def test_ownership_dirs() -> None:
    """迁移在 M1、ER/约束在 M3、规则在 M4、视图口径在 M5。"""
    assert (REPO / "modules/m1-transaction-integration/migrations/versions").is_dir()
    assert (REPO / "modules/m3-er-constraints/er/schema.mmd").is_file()
    assert (REPO / "modules/m3-er-constraints/constraints/verify_constraints.sql").is_file()
    assert (REPO / "modules/m4-rules-derived/m4_rules_derived/rules").is_dir()
    assert (REPO / "modules/m5-views-console/views/queries.sql").is_file()
    # 反向：这些目录不得出现在其它模块
    assert not (REPO / "modules/m5-views-console/migrations").exists()
    assert not (REPO / "modules/m4-rules-derived/views").exists()
