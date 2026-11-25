#!/usr/bin/env python3
"""仓库结构检查器（FR-114–FR-123、SC-021/022 的结构侧门禁）。

检查范围（与 ``contracts/module-boundaries.md`` §1、§3 与
``contracts/deployment-verify.md`` §1 对齐）：

1. 根级必需文件/目录（``pyproject.toml``、``alembic.ini``、``conftest.py``、
   ``Makefile``、``compose.yaml``、``.env.example``、``README.md``、``tests/``）；
2. 六个组件：``shared/`` + 五个 ``modules/mN-.../``，各自包含 README 与证据目录；
3. Python 包命名：目录名严格为连字符形式，包名去掉连字符且**不加前后缀**；
4. 必需入口文件（应用工厂、公开门面、迁移目录、前端 package.json 等）；
5. 禁止遗留：根 ``backend/``、``app/``、``frontend/``、``scripts/``，嵌套
   ``shared/shared/``，``element-plus``/``echarts`` 依赖，旧导入前缀
   （``app.`` / ``backend.``），写死 ``/Users/...`` 的路径；
6. 关键配置一致性：``alembic.ini`` 的 ``script_location``、``.env.example`` 的
   ``WEB_DIST_DIR``、``compose.yaml`` 的初始化脚本挂载、``Makefile`` 的
   ``PYTHONPATH``/``WEB_DIST_DIR`` 变量、``pyproject.toml`` 的包映射。

输出逐项 ``PASS`` / ``FAIL`` / ``WARN``：``FAIL`` 为阻断项（退出码 1）；
``WARN`` 表示「规范要求、但对应任务尚未交付」的内容（默认不阻断，``--strict``
时升级为 FAIL）。全部中文提示。

用法::

    python -m shared.deploy.check_structure [--json] [--strict] [--root PATH]

退出码：0 通过；1 存在 FAIL；2 扫描失败（如无法定位仓库根）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量：结构约定（与 plan.md「Source Code (repository root)」逐条对应）
# ---------------------------------------------------------------------------

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"

ROOT_REQUIRED_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "alembic.ini",
    "conftest.py",
    "Makefile",
    "compose.yaml",
    ".env.example",
    "README.md",
)

ROOT_REQUIRED_DIRS: tuple[str, ...] = ("shared", "modules", "tests")

# 根目录禁止残留的旧布局目录（搬迁完成后必须删除）
FORBIDDEN_ROOT_DIRS: tuple[str, ...] = ("backend", "app", "frontend", "scripts")


# 组件定义：目录、Python 包目录名、必需文件（相对组件目录）、待交付文件（WARN）
@dataclass(frozen=True)
class Component:
    """一个自包含组件的结构契约。"""

    key: str
    directory: str
    package: str | None  # Python 包目录名；None 表示不提供运行时包（M3）
    required_files: tuple[str, ...] = ()
    required_dirs: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()  # 规范要求但由其他任务交付；缺失记为 WARN


COMPONENTS: tuple[Component, ...] = (
    Component(
        key="shared",
        directory="shared",
        package=None,  # 包根即 shared/ 本身
        required_files=(
            "README.md",
            "__init__.py",
            "deploy/check_structure.py",
            "deploy/check_boundaries.py",
            "deploy/boundary_check.py",
            "deploy/verify_deploy.sh",
            "tests/unit/__init__.py",
        ),
        required_dirs=("deploy", "tests"),
        pending=(),
    ),
    Component(
        key="M1 事务写入与接口集成",
        directory="modules/m1-transaction-integration",
        package="m1_transaction_integration",
        required_files=(
            "README.md",
            "m1_transaction_integration/__init__.py",
            "m1_transaction_integration/public.py",
            "m1_transaction_integration/api/app.py",
            "migrations/env.py",
        ),
        required_dirs=("evidence", "migrations", "migrations/versions"),
        pending=(),
    ),
    Component(
        key="M2 诱饵交互与事件采集",
        directory="modules/m2-decoy-capture",
        package="m2_decoy_capture",
        required_files=(
            "README.md",
            "m2_decoy_capture/__init__.py",
            "m2_decoy_capture/server.py",
        ),
        required_dirs=("evidence", "m2_decoy_capture/cli"),
        # `public.py` 由 T016 交付；缺失不阻断结构检查，但会在输出中提示
        pending=("m2_decoy_capture/public.py",),
    ),
    Component(
        key="M3 ER 与完整性约束",
        directory="modules/m3-er-constraints",
        package=None,  # 无运行时包，交付物为 ER/SQL/测试
        required_files=("README.md",),
        required_dirs=("evidence", "tests"),
        pending=(
            "er/schema.mmd",
            "constraints/catalog.md",
            "constraints/verify_constraints.sql",
            "tools/introspect_constraints.py",
            "tests/integration/test_constraints_fk.py",
        ),
    ),
    Component(
        key="M4 规则与派生数据",
        directory="modules/m4-rules-derived",
        package="m4_rules_derived",
        required_files=(
            "README.md",
            "m4_rules_derived/__init__.py",
            "m4_rules_derived/public.py",
        ),
        required_dirs=("evidence", "m4_rules_derived/rules"),
        pending=(),
    ),
    Component(
        key="M5 分析视图与控制台",
        directory="modules/m5-views-console",
        package="m5_views_console",
        required_files=(
            "README.md",
            "m5_views_console/__init__.py",
            "frontend/package.json",
        ),
        required_dirs=("evidence", "frontend/src"),
        pending=(
            "views/queries.sql",
            "cli/verify_views.py",
            "frontend/verify/run-check.mjs",
            "frontend/verify/token-audit.mjs",
        ),
    ),
)

# 旧导入前缀：出现即视为搬迁未完成
LEGACY_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(?P<name>app|backend)(?:\.|\s|$)", re.MULTILINE
)
# 前端源码中直接拼旧后端目录（HTTP 契约取代）
LEGACY_FRONTEND_REF_RE = re.compile(r"\.\./backend|/backend/")
# 写死本机绝对路径（Makefile/脚本禁止依赖具体用户目录）
ABS_USER_PATH_RE = re.compile(r"/Users/[^\s:]+|/home/[^\s:]+")

# 扫描时跳过的目录名（依赖/产物/缓存，避免遍历 iCloud dataless 目录与 node_modules）
SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "node_modules",
        "dist",
        ".ruff_cache",
        ".pytest_cache",
        ".pnpm-store",
        ".mypy_cache",
    }
)


# ---------------------------------------------------------------------------
# 数据结构与工具
# ---------------------------------------------------------------------------


@dataclass
class CheckItem:
    """单条检查结果。"""

    name: str
    status: str
    detail: str = ""
    lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "lines": self.lines,
        }


def find_repo_root(start: Path | None = None) -> Path:
    """沿父目录向上定位仓库根（含 ``pyproject.toml`` 与 ``Makefile``）。"""
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "Makefile").is_file():
            return candidate
    raise FileNotFoundError("无法定位仓库根（未找到 pyproject.toml + Makefile）")


def _iter_files(
    base: Path, suffixes: tuple[str, ...], *, skip_names: frozenset[str] = SKIP_DIR_NAMES
) -> list[Path]:
    """遍历给定后缀的文件，跳过缓存/依赖目录（os.walk + 剪枝，不跟随符号链接）。"""
    found: list[Path] = []
    if not base.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in skip_names and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith(suffixes):
                found.append(Path(dirpath) / filename)
    return found


def _rel(path: Path, root: Path) -> str:
    """返回相对仓库根的 POSIX 风格路径（失败时退回绝对路径）。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str:
    """读取文本（忽略无法解码的字节，避免检查器自身崩溃）。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - 权限/IO 异常
        raise RuntimeError(f"无法读取 {path}：{exc}") from exc


def _pkg_name_from_dir(directory: Path) -> str:
    """目录名转 Python 包名（连字符改下划线）。"""
    return directory.name.replace("-", "_")


# ---------------------------------------------------------------------------
# 各类检查
# ---------------------------------------------------------------------------


def _check_root(root: Path) -> list[CheckItem]:
    """根级必需文件与目录。"""
    items: list[CheckItem] = []
    missing_files = [name for name in ROOT_REQUIRED_FILES if not (root / name).is_file()]
    items.append(
        CheckItem(
            name="根级必需文件",
            status=STATUS_PASS if not missing_files else STATUS_FAIL,
            detail=f"{len(ROOT_REQUIRED_FILES)} 个文件",
            lines=[f"缺少：{name}" for name in missing_files],
        )
    )
    missing_dirs = [name for name in ROOT_REQUIRED_DIRS if not (root / name).is_dir()]
    items.append(
        CheckItem(
            name="根级必需目录",
            status=STATUS_PASS if not missing_dirs else STATUS_FAIL,
            detail="shared/ modules/ tests/",
            lines=[f"缺少目录：{name}" for name in missing_dirs],
        )
    )
    return items


def _check_component(root: Path, component: Component) -> list[CheckItem]:
    """单个组件：目录、README、证据目录、包名与必需文件。"""
    items: list[CheckItem] = []
    base = root / component.directory
    label = component.key

    if not base.is_dir():
        items.append(
            CheckItem(f"{label}：组件目录", STATUS_FAIL, lines=[f"缺少 {component.directory}/"])
        )
        return items
    items.append(CheckItem(f"{label}：组件目录", STATUS_PASS, component.directory))

    # README 与证据目录（SC-021/028：每模块自包含证据索引）
    missing_required = [
        name
        for name in component.required_files
        if not (base / name).is_file() and not (base / name).is_dir()
    ]
    items.append(
        CheckItem(
            name=f"{label}：必需文件",
            status=STATUS_PASS if not missing_required else STATUS_FAIL,
            detail=f"{len(component.required_files)} 项",
            lines=[f"缺少：{name}" for name in missing_required],
        )
    )

    missing_dirs = [name for name in component.required_dirs if not (base / name).is_dir()]
    items.append(
        CheckItem(
            name=f"{label}：必需目录",
            status=STATUS_PASS if not missing_dirs else STATUS_FAIL,
            detail=", ".join(component.required_dirs) or "无",
            lines=[f"缺少目录：{name}" for name in missing_dirs],
        )
    )

    # 待交付项：由其他任务负责，缺失只记 WARN（不阻断结构门禁）
    missing_pending = [name for name in component.pending if not (base / name).exists()]
    if component.pending:
        items.append(
            CheckItem(
                name=f"{label}：待交付内容",
                status=STATUS_WARN if missing_pending else STATUS_PASS,
                detail=f"{len(component.pending) - len(missing_pending)}/{len(component.pending)} 已交付",
                lines=[f"待任务交付：{name}" for name in missing_pending],
            )
        )

    # Python 包命名：只允许约定包目录（不加前后缀）；
    # `tests/`、`migrations/` 是契约允许的附属 Python 包，不计入“多余包”。
    allowed_extra = {"tests", "migrations"}
    if component.package is not None:
        package_dir = base / component.package
        extra_packages = sorted(
            child.name
            for child in base.iterdir()
            if child.is_dir()
            and child.name not in SKIP_DIR_NAMES
            and child.name not in allowed_extra
            and (child / "__init__.py").is_file()
            and child.name != component.package
        )
        lines = []
        status = STATUS_PASS
        if not package_dir.is_dir():
            status = STATUS_FAIL
            lines.append(f"缺少包目录：{component.directory}/{component.package}/")
        elif not (package_dir / "__init__.py").is_file():
            status = STATUS_FAIL
            lines.append(f"缺少包标记：{component.directory}/{component.package}/__init__.py")
        if extra_packages:
            status = STATUS_FAIL
            lines.extend(
                f"多余 Python 包目录：{component.directory}/{name}/"
                "（模块只允许一个同名下划线包，不加前后缀）"
                for name in extra_packages
            )
        items.append(
            CheckItem(
                name=f"{label}：Python 包命名",
                status=status,
                detail=component.package,
                lines=lines,
            )
        )
    return items


def _check_entry_semantics(root: Path) -> list[CheckItem]:
    """入口语义：M1 应用工厂可导入、公开门面存在、Alembic 指向 M1 迁移。"""
    items: list[CheckItem] = []

    app_file = root / "modules/m1-transaction-integration/m1_transaction_integration/api/app.py"
    app_text = _read_text(app_file) if app_file.is_file() else ""
    ok = "def create_app" in app_text
    items.append(
        CheckItem(
            name="M1：uvicorn 应用工厂",
            status=STATUS_PASS if ok else STATUS_FAIL,
            detail="m1_transaction_integration.api.app:create_app",
            lines=[] if ok else ["api/app.py 中未找到 create_app()"],
        )
    )

    alembic_text = _read_text(root / "alembic.ini") if (root / "alembic.ini").is_file() else ""
    expected_location = "modules/m1-transaction-integration/migrations"
    ok = re.search(
        r"^script_location\s*=\s*" + re.escape(expected_location) + r"\s*$",
        alembic_text,
        re.MULTILINE,
    )
    items.append(
        CheckItem(
            name="Alembic：script_location",
            status=STATUS_PASS if ok else STATUS_FAIL,
            detail=expected_location,
            lines=[] if ok else [f"alembic.ini 未指向 {expected_location}"],
        )
    )
    return items


def _check_forbidden(root: Path) -> list[CheckItem]:
    """禁止遗留：旧目录、旧包嵌套、旧依赖、旧导入前缀、写死路径。"""
    items: list[CheckItem] = []

    residue = [name for name in FORBIDDEN_ROOT_DIRS if (root / name).is_dir()]
    items.append(
        CheckItem(
            name="禁止遗留：根旧目录",
            status=STATUS_PASS if not residue else STATUS_FAIL,
            detail="backend/ app/ frontend/ scripts/",
            lines=[f"发现旧目录 {name}/：搬迁完成后应删除" for name in residue],
        )
    )

    nested_shared = root / "shared" / "shared"
    items.append(
        CheckItem(
            name="禁止遗留：shared/shared",
            status=STATUS_PASS if not nested_shared.exists() else STATUS_FAIL,
            detail="包根即 shared/",
            lines=[] if not nested_shared.exists() else ["发现 shared/shared/：包根应为 shared/"],
        )
    )

    # package.json 依赖：Element Plus / ECharts 必须移除（计划 R-01）
    package_json = root / "modules/m5-views-console/frontend/package.json"
    bad_deps: list[str] = []
    if package_json.is_file():
        try:
            payload = json.loads(_read_text(package_json))
        except json.JSONDecodeError:
            bad_deps.append("package.json 不是合法 JSON")
        else:
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                deps = payload.get(section) or {}
                if isinstance(deps, dict):
                    bad_deps.extend(
                        f"{name}（{section}）"
                        for name in deps
                        if name in {"element-plus", "echarts"}
                    )
    else:
        bad_deps.append("缺少 modules/m5-views-console/frontend/package.json")
    items.append(
        CheckItem(
            name="禁止遗留：element-plus / echarts",
            status=STATUS_PASS if not bad_deps else STATUS_FAIL,
            detail="前端依赖已移除",
            lines=[f"仍存在依赖：{name}" for name in bad_deps],
        )
    )

    # Python 旧导入前缀（app. / backend.）
    legacy: list[str] = []
    for base in (root / "shared", root / "modules"):
        for py_file in _iter_files(base, (".py",)):
            text = _read_text(py_file)
            for match in LEGACY_IMPORT_RE.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                legacy.append(f"{_rel(py_file, root)}:{line_no}: {match.group(0).strip()}")
    items.append(
        CheckItem(
            name="禁止遗留：旧导入前缀",
            status=STATUS_PASS if not legacy else STATUS_FAIL,
            detail="未发现 app./backend. 导入",
            lines=legacy[:20],
        )
    )

    # 前端源码直接引用旧后端目录
    frontend_src = root / "modules/m5-views-console/frontend/src"
    refs: list[str] = []
    for source in _iter_files(frontend_src, (".vue", ".ts", ".js", ".css")):
        text = _read_text(source)
        for match in LEGACY_FRONTEND_REF_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            refs.append(f"{_rel(source, root)}:{line_no}: {match.group(0)}")
    items.append(
        CheckItem(
            name="禁止遗留：前端直连旧后端路径",
            status=STATUS_PASS if not refs else STATUS_FAIL,
            detail="前端只经 /api HTTP 契约",
            lines=refs[:20],
        )
    )

    # Makefile / shell 脚本写死本机绝对路径（计划要求无绝对路径）
    hardcoded: list[str] = []
    for target in [root / "Makefile", *sorted((root / "shared/deploy").glob("*.sh"))]:
        if not target.is_file():
            continue
        text = _read_text(target)
        for match in ABS_USER_PATH_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            hardcoded.append(f"{_rel(target, root)}:{line_no}: {match.group(0)}")
    items.append(
        CheckItem(
            name="禁止遗留：写死绝对路径",
            status=STATUS_PASS if not hardcoded else STATUS_FAIL,
            detail="Makefile/部署脚本使用相对路径与可覆盖变量",
            lines=hardcoded[:20],
        )
    )
    return items


def _check_config_consistency(root: Path) -> list[CheckItem]:
    """关键配置一致性：Makefile / .env.example / compose.yaml / pyproject.toml。"""
    items: list[CheckItem] = []

    makefile = root / "Makefile"
    text = _read_text(makefile) if makefile.is_file() else ""
    required_snippets = (
        "VENV ?= .venv",
        "modules/m1-transaction-integration",
        "modules/m2-decoy-capture",
        "modules/m4-rules-derived",
        "modules/m5-views-console",
        "WEB_DIST_DIR",
        "shared/deploy/verify_deploy.sh",
    )
    missing = [snippet for snippet in required_snippets if snippet not in text]
    items.append(
        CheckItem(
            name="Makefile：统一变量与模块路径",
            status=STATUS_PASS if not missing else STATUS_FAIL,
            detail="VENV/PY/PYTHONPATH/WEB_DIST_DIR",
            lines=[f"缺少片段：{snippet}" for snippet in missing],
        )
    )

    env_example = root / ".env.example"
    env_text = _read_text(env_example) if env_example.is_file() else ""
    expected_dist = "WEB_DIST_DIR=modules/m5-views-console/frontend/dist"
    items.append(
        CheckItem(
            name=".env.example：WEB_DIST_DIR",
            status=STATUS_PASS if expected_dist in env_text else STATUS_FAIL,
            detail=expected_dist,
            lines=[] if expected_dist in env_text else [".env.example 未指向新前端产物目录"],
        )
    )

    compose = root / "compose.yaml"
    compose_text = _read_text(compose) if compose.is_file() else ""
    compose_ok = (
        "modules/m1-transaction-integration/db/init" in compose_text
        and "MYSQL_IMAGE" in compose_text
        and "./db/init" not in compose_text
    )
    items.append(
        CheckItem(
            name="compose.yaml：初始化脚本与镜像变量",
            status=STATUS_PASS if compose_ok else STATUS_FAIL,
            detail="容器 MySQL + 宿主后端，M1 初始化脚本挂载",
            lines=[]
            if compose_ok
            else [
                "compose.yaml 未挂载 modules/m1-transaction-integration/db/init 或缺少 MYSQL_IMAGE"
            ],
        )
    )

    pyproject = root / "pyproject.toml"
    py_text = _read_text(pyproject) if pyproject.is_file() else ""
    package_paths = [
        "shared",
        "modules/m1-transaction-integration/m1_transaction_integration",
        "modules/m2-decoy-capture/m2_decoy_capture",
        "modules/m4-rules-derived/m4_rules_derived",
        "modules/m5-views-console/m5_views_console",
    ]
    missing_packages = [path for path in package_paths if f'"{path}"' not in py_text]
    nested = '"shared/shared"' in py_text
    items.append(
        CheckItem(
            name="pyproject.toml：单发行版多包映射",
            status=STATUS_PASS if not missing_packages and not nested else STATUS_FAIL,
            detail="shared + 4 个模块包（M3 无运行时包）",
            lines=[
                *[f"packages 缺少：{path}" for path in missing_packages],
                *(['仍引用旧路径 "shared/shared"'] if nested else []),
            ],
        )
    )
    return items


# ---------------------------------------------------------------------------
# 汇总与入口
# ---------------------------------------------------------------------------


def run_checks(root: Path | None = None, *, strict: bool = False) -> list[CheckItem]:
    """执行全部结构检查，返回逐项结果（不打印）。"""
    repo = (root or find_repo_root()).resolve()
    items: list[CheckItem] = []
    items.extend(_check_root(repo))
    for component in COMPONENTS:
        items.extend(_check_component(repo, component))
    items.extend(_check_entry_semantics(repo))
    items.extend(_check_forbidden(repo))
    items.extend(_check_config_consistency(repo))
    if strict:
        for item in items:
            if item.status == STATUS_WARN:
                item.status = STATUS_FAIL
                item.lines.append("（--strict：待交付项按 FAIL 计）")
    return items


def summarize(items: list[CheckItem]) -> dict[str, int]:
    """统计各状态数量。"""
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_WARN: 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def passed(items: list[CheckItem]) -> bool:
    """是否存在阻断项。"""
    return not any(item.status == STATUS_FAIL for item in items)


def print_report(repo: Path, items: list[CheckItem]) -> None:
    """打印人类可读报告。"""
    print(f"仓库结构检查：{repo}")
    print("=" * 64)
    for item in items:
        detail = f"（{item.detail}）" if item.detail else ""
        print(f"[{item.status}] {item.name}{detail}")
        for line in item.lines:
            print(f"       - {line}")
    counts = summarize(items)
    print("=" * 64)
    verdict = "PASS" if passed(items) else "FAIL"
    print(
        f"结果：{verdict}（PASS {counts[STATUS_PASS]} 项，"
        f"FAIL {counts[STATUS_FAIL]} 项，WARN {counts[STATUS_WARN]} 项）"
    )
    if not passed(items):
        print(
            "修复建议：按 contracts/module-boundaries.md §1/§3 与 plan.md 目录结构整改；"
            "禁止通过改检查器绕过。"
        )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：``python -m shared.deploy.check_structure``。"""
    parser = argparse.ArgumentParser(
        prog="python -m shared.deploy.check_structure",
        description="仓库目录结构 / 包命名 / 必需文件 / 禁止遗留检查",
    )
    parser.add_argument("--root", default=None, help="仓库根（默认自动定位）")
    parser.add_argument("--json", action="store_true", help="末尾输出机器可读 JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把「待交付内容」的 WARN 升级为 FAIL（最终合并门禁使用）",
    )
    args = parser.parse_args(argv)

    try:
        repo = find_repo_root(Path(args.root) if args.root else None)
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    items = run_checks(repo, strict=args.strict)
    print_report(repo, items)

    if args.json:
        payload = {
            "root": str(repo),
            "items": [item.as_dict() for item in items],
            "counts": summarize(items),
            "result": "pass" if passed(items) else "fail",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed(items) else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
