#!/usr/bin/env python3
"""T051 解耦回归：对比 `tests/fixtures/api_baseline.json` 与当前运行中的 API。

规则（contracts/api-extensions.md §1 兼容性）：
- 允许新增字段/新增端点（002 的 additive 契约）；
- 既有字段名缺失或类型变化 = 破坏性回归，退出码 1；
- 数值/状态字段的示例值允许因种子数据变化而不同，只记录不判失败。

用法：
    python tools/compare_api_baseline.py [--base-url http://127.0.0.1:8000] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8000"
BASELINE = Path(__file__).resolve().parents[1] / "tests/fixtures/api_baseline.json"


def shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def diff_shape(expected: Any, actual: Any, path: str, missing: list[str], added: list[str], changed: list[str]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key, value in expected.items():
            if key not in actual:
                missing.append(f"{path}.{key}")
            else:
                diff_shape(value, actual[key], f"{path}.{key}", missing, added, changed)
        for key in actual:
            if key not in expected:
                added.append(f"{path}.{key}")
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if expected and actual:
            diff_shape(expected[0], actual[0], f"{path}[]", missing, added, changed)
        return
    if expected != actual:
        changed.append(f"{path}: {expected} -> {actual}")


def fetch(base: str, path: str) -> Any:
    with urllib.request.urlopen(f"{base}{path}", timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "baseline": str(BASELINE),
        "captured_at": baseline.get("captured_at"),
        "base_url": args.base_url,
        "endpoints": [],
        "ok": True,
    }
    for name, entry in baseline["endpoints"].items():
        missing: list[str] = []
        added: list[str] = []
        changed: list[str] = []
        item: dict[str, Any] = {"name": name, "path": entry["path"]}
        try:
            payload = fetch(args.base_url, entry["path"])
        except Exception as error:  # noqa: BLE001 - 记录后继续，最终以 ok 判定
            item.update({"ok": False, "error": str(error)})
            report["ok"] = False
            report["endpoints"].append(item)
            continue
        diff_shape(entry["shape"], shape(payload), name, missing, added, changed)
        item.update(
            {
                "ok": not missing and not changed,
                "missing_fields": missing,
                "added_fields": added,
                "type_changes": changed,
            }
        )
        if missing or changed:
            report["ok"] = False
        report["endpoints"].append(item)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(f"{text}\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
