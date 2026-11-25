#!/usr/bin/env python3
"""兼容入口：结构检查约定的 `modules/m5-views-console/cli/verify_views.py`。

实际实现位于包内 `m5_views_console/cli/verify_views.py`（支持
`python -m m5_views_console.cli.verify_views`）。本文件只做路径注入后转发，
保证两种调用方式行为一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from m5_views_console.cli.verify_views import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
