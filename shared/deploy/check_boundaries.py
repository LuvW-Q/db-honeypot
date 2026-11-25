#!/usr/bin/env python3
"""模块依赖边界静态检查（FR-114–FR-123、SC-022）。

依据 ``specs/002-ui-console-modularization/contracts/module-boundaries.md`` §3/§6
的允许矩阵，对 ``shared/`` 与 ``modules/**`` 的 ``.py`` 文件做 AST 静态扫描：

- 允许边（其余跨模块导入一律违规）：
  - ``shared`` → 无（不得导入任何 ``m1_``…``m5_`` 包）；
  - ``M1`` → ``shared``、``m4_rules_derived.public``、自身；
  - ``M2`` → ``shared``、``m1_transaction_integration.public``、自身；
  - ``M3`` → ``shared``（仅 ``tests/`` 与 ``tools/`` 内）、自身；
  - ``M4`` → ``shared``、自身；
  - ``M5`` → ``shared``（仅 ``cli/`` 与 ``tests/`` 内）、自身；
- 硬性禁止：跨模块内部子模块（``api``/``repositories``/``services``/``schemas``/
  ``migrations``）、反向依赖、旧前缀 ``app.`` / ``backend.``、跨包循环依赖；
- 未知目标包（第三方/标准库）放行；
- 相对导入限定在同一包内，按「自身」放行（跨包无法用相对导入表达）。

用法::

    python -m shared.deploy.check_boundaries [--json] [--paths shared modules] [--root PATH]

退出码：0 无违规；1 存在违规；2 扫描失败（语法错误等）。

``shared/deploy/boundary_check.py`` 是本模块的契约兼容别名（module-boundaries.md
§6 指定该文件名），两者行为完全一致。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 允许矩阵（与 contracts/module-boundaries.md §3 逐行对应）
# ---------------------------------------------------------------------------

# Python 包名 -> 模块所有者标签
PACKAGE_OWNERS: dict[str, str] = {
    "m1_transaction_integration": "M1",
    "m2_decoy_capture": "M2",
    "m4_rules_derived": "M4",
    "m5_views_console": "M5",
}

# 模块目录名 -> (所有者标签, Python 包名)；M3 只有文档/SQL/测试，无运行时包
MODULE_DIRS: dict[str, tuple[str, str | None]] = {
    "m1-transaction-integration": ("M1", "m1_transaction_integration"),
    "m2-decoy-capture": ("M2", "m2_decoy_capture"),
    "m3-er-constraints": ("M3", None),
    "m4-rules-derived": ("M4", "m4_rules_derived"),
    "m5-views-console": ("M5", "m5_views_console"),
}

# 允许的跨模块边：源 -> 目标模块集合（`shared` 对所有模块公开）
ALLOWED_EDGES: dict[str, frozenset[str]] = {
    "shared": frozenset(),
    "M1": frozenset({"shared"}),
    "M2": frozenset({"shared"}),
    "M3": frozenset({"shared"}),
    "M4": frozenset({"shared"}),
    "M5": frozenset({"shared"}),
}

# 唯一允许的跨模块导入：必须且只能命中公开门面（contracts §2）
PUBLIC_FACADES: dict[tuple[str, str], str] = {
    ("M1", "M4"): "m4_rules_derived.public",
    ("M2", "M1"): "m1_transaction_integration.public",
}

# `shared` 只允许被特定位置导入（contracts §3 表内括注）
SHARED_IMPORT_SCOPES: dict[str, tuple[str, ...]] = {
    "M3": ("tests", "tools"),
    "M5": ("cli", "tests"),
}

# 已知包的仓库内路径（用于把 `from pkg import submodule` 解析为真实子模块）
PACKAGE_PATHS: dict[str, str] = {
    "shared": "shared",
    "m1_transaction_integration": "modules/m1-transaction-integration/m1_transaction_integration",
    "m2_decoy_capture": "modules/m2-decoy-capture/m2_decoy_capture",
    "m4_rules_derived": "modules/m4-rules-derived/m4_rules_derived",
    "m5_views_console": "modules/m5-views-console/m5_views_console",
}


# 其他模块禁止被导入的内部子模块（只能经 public 门面）
INTERNAL_SUBMODULES = frozenset({"api", "repositories", "services", "schemas", "migrations"})

# 旧布局包前缀：出现即违规
LEGACY_TOP_LEVEL = frozenset({"app", "backend"})

# 扫描跳过的目录名（避免遍历 node_modules / iCloud 上的构建产物）
SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "node_modules",
        "dist",
        ".ruff_cache",
        ".pytest_cache",
        ".mypy_cache",
        ".pnpm-store",
    }
)

# 违规规则名（JSON 输出使用，便于门禁统计）
RULE_LEGACY_PREFIX = "legacy_prefix"
RULE_SHARED_IMPORTS_MODULE = "shared_imports_module"
RULE_CROSS_MODULE_INTERNAL = "cross_module_internal"
RULE_FORBIDDEN_EDGE = "forbidden_edge"
RULE_SHARED_IMPORT_SCOPE = "shared_import_scope"
RULE_CIRCULAR_DEPENDENCY = "circular_dependency"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """一条边界违规（字段与 module-boundaries.md §6 JSON 契约一致）。"""

    file: str
    line: int
    import_name: str
    rule: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "import": self.import_name,
            "rule": self.rule,
            "message": self.message,
        }


@dataclass
class ScanReport:
    """一次扫描的完整结果。"""

    scanned_files: int = 0
    violations: list[Violation] = field(default_factory=list)
    legacy_imports: list[dict[str, object]] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def result(self) -> str:
        return "pass" if not self.violations and not self.scan_errors else "fail"

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned_files": self.scanned_files,
            "violations": [item.as_dict() for item in self.violations],
            "legacy_imports": self.legacy_imports,
            "scan_errors": self.scan_errors,
            "result": self.result,
        }


# ---------------------------------------------------------------------------
# 路径与所有者解析
# ---------------------------------------------------------------------------


def find_repo_root(start: Path | None = None) -> Path:
    """沿父目录向上定位仓库根（含 ``pyproject.toml`` 与 ``Makefile``）。"""
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "Makefile").is_file():
            return candidate
    return Path(__file__).resolve().parents[2]


def _iter_py_files(base: Path) -> list[Path]:
    """遍历 ``.py`` 文件（os.walk + 剪枝，不跟随符号链接）。"""
    found: list[Path] = []
    if not base.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith(".py"):
                found.append(Path(dirpath) / filename)
    return found


def _source_context(rel_path: Path) -> tuple[str | None, Path | None, str | None]:
    """由相对仓库根的路径判断（所有者, 组件目录, 包名）。"""
    parts = rel_path.parts
    if not parts:
        return None, None, None
    if parts[0] == "shared":
        return "shared", Path("shared"), "shared"
    if parts[0] == "modules" and len(parts) >= 3:
        module_dir = parts[1]
        owner, package = MODULE_DIRS.get(module_dir, (None, None))
        if owner is None:
            return None, None, None
        return owner, Path("modules") / module_dir, package
    return None, None, None


def _target_package(import_name: str) -> tuple[str | None, str]:
    """解析导入目标：返回（目标所有者标签, 顶层包名）；第三方返回 (None, top)。"""
    top = import_name.split(".", 1)[0]
    if top == "shared":
        return "shared", "shared"
    if top in PACKAGE_OWNERS:
        return PACKAGE_OWNERS[top], top
    return None, top


def _within_scopes(rel_to_component: Path, scopes: tuple[str, ...]) -> bool:
    """文件是否位于组件内允许的目录（如 M5 的 cli/、tests/）。

    契约文档中 M5 的 CLI 目录同时出现在「组件根 ``cli/``」与「包内
    ``m5_views_console/cli/``」两种写法，这里对路径任一层级命中即放行，
    只拦截组件根 / 包根级别的越界导入。
    """
    return any(part in scopes for part in rel_to_component.parts)


def _is_internal_target(import_name: str, target_package: str) -> bool:
    """是否命中其他模块的内部子模块（api/repositories/services/...）。"""
    if not import_name.startswith(target_package + "."):
        return False
    second = import_name.split(".")[1]
    return second in INTERNAL_SUBMODULES


def _module_exists(name: str, repo: Path) -> bool:
    """判断绝对模块名在仓库内是否真实存在（包或 .py 模块）。"""
    parts = name.split(".")
    base = PACKAGE_PATHS.get(parts[0])
    if base is None:
        return False
    current = repo / base
    for part in parts[1:]:
        current = current / part
        if not (current.is_dir() or current.with_suffix(".py").is_file()):
            return False
    return current.with_suffix(".py").is_file() or (current / "__init__.py").is_file()


def _resolve_absolute_imports(node: ast.Import | ast.ImportFrom, repo: Path) -> list[str]:
    """把 import 语句展开为待检查的绝对模块名候选列表。

    - ``import a.b`` → ``a.b``；
    - ``from a.b import c, d``：若 ``a.b.c`` / ``a.b.d`` 是仓库内真实模块，按子模块
      解析（这样 ``from m4_rules_derived import public`` 命中公开门面，而
      ``from m4_rules_derived import analysis`` 命中内部子模块）；
      否则按 ``a.b`` 解析（导入的是符号而非模块）；
    - 相对导入（``level > 0``）同一包内使用，返回空列表（按自身放行）。
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:  # 相对导入：同包内，按自身放行
        return []
    if not node.module:
        return []
    base = node.module
    submodules = [
        f"{base}.{alias.name}"
        for alias in node.names
        if alias.name != "*" and _module_exists(f"{base}.{alias.name}", repo)
    ]
    return submodules or [base]


# ---------------------------------------------------------------------------
# 单条导入检查
# ---------------------------------------------------------------------------


def _check_import(
    *,
    owner: str,
    component_dir: Path,
    rel_path: Path,
    line: int,
    import_name: str,
    add: callable,
    edges: dict[str, set[str]],
) -> None:
    """检查单个导入目标；``add`` 为记录违规的回调。"""
    top = import_name.split(".", 1)[0]

    # 1) 旧布局前缀 app. / backend.
    if top in LEGACY_TOP_LEVEL:
        add(
            rel_path,
            line,
            import_name,
            RULE_LEGACY_PREFIX,
            f"旧布局前缀 {top}.* 已废止，应改为 m1_/m2_/shared 包路径",
        )
        return

    target_owner, target_package = _target_package(import_name)
    if target_owner is None:
        return  # 第三方/标准库放行

    rel_to_component = rel_path.relative_to(component_dir)

    # 2) 同包内部导入（含 shared 内部、模块内部）一律允许
    if target_owner == owner and target_package == {
        "shared": "shared",
        "M1": "m1_transaction_integration",
        "M2": "m2_decoy_capture",
        "M4": "m4_rules_derived",
        "M5": "m5_views_console",
    }.get(owner):
        return

    # 记录包级依赖边（用于循环检测；含违规边，便于报告潜在环）
    edges.setdefault(owner, set()).add(target_owner)

    # 3) shared 只能被模块导入，且部分模块限制目录范围
    if target_owner == "shared":
        allowed = ALLOWED_EDGES.get(owner, frozenset())
        if "shared" not in allowed:
            add(
                rel_path,
                line,
                import_name,
                RULE_FORBIDDEN_EDGE if owner != "shared" else RULE_SHARED_IMPORTS_MODULE,
                f"{owner} 不允许导入 shared（检查依赖矩阵）",
            )
            return
        scopes = SHARED_IMPORT_SCOPES.get(owner)
        if scopes and not _within_scopes(rel_to_component, scopes):
            add(
                rel_path,
                line,
                import_name,
                RULE_SHARED_IMPORT_SCOPE,
                f"{owner} 只允许在 {'/'.join(scopes)} 内导入 shared",
            )
        return

    # 4) shared 导入任何模块包 = 反向依赖
    if owner == "shared":
        add(
            rel_path,
            line,
            import_name,
            RULE_SHARED_IMPORTS_MODULE,
            "shared 不得导入任何业务模块包（平台层不依赖模块，禁止反向依赖）",
        )
        return

    # 5) 跨模块导入：只允许公开门面
    facade = PUBLIC_FACADES.get((owner, target_owner))
    if facade and (import_name == facade or import_name.startswith(facade + ".")):
        return
    if facade:
        add(
            rel_path,
            line,
            import_name,
            RULE_CROSS_MODULE_INTERNAL,
            f"{owner} 只能经 {facade} 导入 {target_owner}，不得使用内部子模块",
        )
        return

    rule = (
        RULE_CROSS_MODULE_INTERNAL
        if _is_internal_target(import_name, target_package)
        else RULE_FORBIDDEN_EDGE
    )
    add(
        rel_path,
        line,
        import_name,
        rule,
        f"依赖矩阵不允许 {owner} → {target_owner}（{target_package}）",
    )


# ---------------------------------------------------------------------------
# 循环依赖检测（跨包；同包内部环按契约放行）
# ---------------------------------------------------------------------------


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """DFS 找出有向图环，返回环路径列表（首尾相同节点）。"""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()
    seen_keys: set[frozenset[str]] = set()

    def dfs(node: str) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt not in visited:
                dfs(nxt)
            elif nxt in on_stack:
                index = stack.index(nxt)
                cycle = [*stack[index:], nxt]
                key = frozenset(cycle)
                if key not in seen_keys:
                    seen_keys.add(key)
                    cycles.append(cycle)
        stack.pop()
        on_stack.discard(node)

    for node in sorted(graph):
        if node not in visited:
            dfs(node)
    return cycles


# ---------------------------------------------------------------------------
# 扫描与入口
# ---------------------------------------------------------------------------


def scan(paths: list[str] | None = None, root: Path | None = None) -> ScanReport:
    """执行边界扫描，返回报告（不打印、不退出）。"""
    repo = (root or find_repo_root()).resolve()
    targets = paths or ["shared", "modules"]
    report = ScanReport()
    edges: dict[str, set[str]] = {}

    def add(
        rel_path: Path,
        line: int,
        import_name: str,
        rule: str,
        message: str,
    ) -> None:
        violation = Violation(
            file=rel_path.as_posix(),
            line=line,
            import_name=import_name,
            rule=rule,
            message=message,
        )
        report.violations.append(violation)
        if rule == RULE_LEGACY_PREFIX:
            report.legacy_imports.append(
                {"file": rel_path.as_posix(), "line": line, "import": import_name}
            )

    for target in targets:
        base = (repo / target).resolve()
        for py_file in _iter_py_files(base):
            try:
                rel_path = py_file.resolve().relative_to(repo)
            except ValueError:  # pragma: no cover - 符号链接越界
                continue
            owner, component_dir, _package = _source_context(rel_path)
            if owner is None or component_dir is None:
                continue
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(rel_path))
            except (OSError, SyntaxError) as exc:
                report.scan_errors.append(f"{rel_path.as_posix()}: {exc}")
                continue
            report.scanned_files += 1
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for import_name in _resolve_absolute_imports(node, repo):
                    _check_import(
                        owner=owner,
                        component_dir=component_dir,
                        rel_path=rel_path,
                        line=node.lineno,
                        import_name=import_name,
                        add=add,
                        edges=edges,
                    )

    # 跨包循环依赖：把包级图补成只含已知包节点，再找环
    known_nodes = {"shared", *PACKAGE_OWNERS.values()}
    cycle_graph = {
        source: {dest for dest in dests if dest in known_nodes}
        for source, dests in edges.items()
        if source in known_nodes
    }
    for cycle in find_cycles(cycle_graph):
        report.violations.append(
            Violation(
                file="（模块依赖图）",
                line=0,
                import_name=" -> ".join(cycle),
                rule=RULE_CIRCULAR_DEPENDENCY,
                message="跨包循环依赖：依赖矩阵必须无环；请改为经 shared 或公开门面单向依赖",
            )
        )
    return report


def print_report(repo: Path, report: ScanReport, targets: list[str]) -> None:
    """打印人类可读报告。"""
    print(f"模块边界检查：{repo}")
    print(f"扫描路径：{', '.join(targets)}；Python 文件：{report.scanned_files}")
    print("=" * 64)
    if report.scan_errors:
        for error in report.scan_errors:
            print(f"[FAIL] 扫描失败：{error}")
    if not report.violations and not report.scan_errors:
        print("[PASS] 依赖边界、公开门面、旧前缀与循环依赖检查全部通过")
    else:
        print(f"[FAIL] 发现 {len(report.violations)} 处违规：")
        for item in report.violations:
            location = f"{item.file}:{item.line}" if item.line else item.file
            print(f"  - {location}: {item.import_name}（{item.rule}）")
            print(f"      {item.message}")
    print("=" * 64)
    print(f"结果：{report.result}")
    if report.result != "pass":
        print(
            "修复建议：按 contracts/module-boundaries.md §3 允许矩阵改为公开门面调用；"
            "不要直接改允许表绕过。"
        )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="python -m shared.deploy.check_boundaries",
        description="模块依赖边界静态检查（允许矩阵 / 公开门面 / 旧前缀 / 循环依赖）",
    )
    parser.add_argument("--root", default=None, help="仓库根（默认自动定位）")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=["shared", "modules"],
        help="扫描目录（相对仓库根），默认 shared modules",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    repo = find_repo_root(Path(args.root) if args.root else None)
    report = scan(paths=args.paths, root=repo)

    if args.json:
        payload = report.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(repo, report, args.paths)

    if report.scan_errors:
        return 2
    return 0 if report.result == "pass" else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
