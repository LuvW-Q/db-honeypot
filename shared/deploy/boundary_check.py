#!/usr/bin/env python3
"""``shared.deploy.boundary_check``：模块边界检查的契约兼容别名。

``specs/002-ui-console-modularization/contracts/module-boundaries.md`` §6 与任务
T017 指定文件名为 ``shared/deploy/boundary_check.py``；实现位于
``shared/deploy/check_boundaries.py``（本仓库交付物统一命名），本模块只做薄转发，
保证以下两种入口完全等价：

    python -m shared.deploy.boundary_check --json
    python -m shared.deploy.check_boundaries --json
"""

from __future__ import annotations

from shared.deploy.check_boundaries import (
    ALLOWED_EDGES,
    INTERNAL_SUBMODULES,
    MODULE_DIRS,
    PACKAGE_OWNERS,
    PUBLIC_FACADES,
    RULE_CIRCULAR_DEPENDENCY,
    RULE_CROSS_MODULE_INTERNAL,
    RULE_FORBIDDEN_EDGE,
    RULE_LEGACY_PREFIX,
    RULE_SHARED_IMPORT_SCOPE,
    RULE_SHARED_IMPORTS_MODULE,
    SHARED_IMPORT_SCOPES,
    ScanReport,
    Violation,
    find_cycles,
    find_repo_root,
    main,
    scan,
)

__all__ = [
    "ALLOWED_EDGES",
    "INTERNAL_SUBMODULES",
    "MODULE_DIRS",
    "PACKAGE_OWNERS",
    "PUBLIC_FACADES",
    "RULE_CIRCULAR_DEPENDENCY",
    "RULE_CROSS_MODULE_INTERNAL",
    "RULE_FORBIDDEN_EDGE",
    "RULE_LEGACY_PREFIX",
    "RULE_SHARED_IMPORTS_MODULE",
    "RULE_SHARED_IMPORT_SCOPE",
    "SHARED_IMPORT_SCOPES",
    "ScanReport",
    "Violation",
    "find_cycles",
    "find_repo_root",
    "main",
    "scan",
]

if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
