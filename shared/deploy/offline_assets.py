#!/usr/bin/env python3
"""前端构建产物离线检查（FR-106、SC-026）。

扫描 ``WEB_DIST_DIR`` 下的文本产物（``index.html``、``*.js``、``*.css``、``*.svg``
等），断言不存在任何指向外部主机的资源引用（``src`` / ``href`` / ``url(...)`` /
``@import`` 中的 ``http(s)://``）。字体、图标、Logo、favicon 必须全部来自本地构建
产物（计划 R-03；ui-contracts §9）。

用法::

    python -m shared.deploy.offline_assets --dist modules/m5-views-console/frontend/dist

退出码：0 通过；1 发现外链/缺少产物；2 参数或读取错误。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# 只扫描这些文本类型（二进制资源不解析）
TEXT_SUFFIXES = frozenset(
    {".html", ".htm", ".js", ".mjs", ".css", ".svg", ".json", ".webmanifest", ".txt"}
)

# 外部资源引用：src/href 属性、CSS url()、@import
_EXTERNAL_REF_RE = re.compile(
    r"""(?:
        (?:src|href|poster|data-src)\s*=\s*["'](?P<attr>https?://[^"']+)
      | url\(\s*["']?(?P<css>https?://[^)"'\s]+)
      | @import\s+(?:url\()?\s*["'](?P<import>https?://[^"']+)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# 允许出现的非资源引用（SVG/XML 命名空间；不是网络请求）
_ALLOWED_PREFIXES = (
    "http://www.w3.org/",  # SVG/XML 命名空间，不产生网络请求
)


@dataclass
class OfflineReport:
    """离线检查结果。"""

    dist: str
    checked_files: int = 0
    external_refs: list[dict[str, object]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def result(self) -> str:
        return "pass" if not self.external_refs and not self.errors else "fail"

    def as_dict(self) -> dict[str, object]:
        return {
            "dist": self.dist,
            "checked_files": self.checked_files,
            "external_refs": self.external_refs,
            "errors": self.errors,
            "result": self.result,
        }


def _allowed(url: str) -> bool:
    """SVG/XML 命名空间等非网络引用放行。"""
    return url.startswith(_ALLOWED_PREFIXES)


def scan_dist(dist: Path) -> OfflineReport:
    """扫描构建产物目录中的外部资源引用。"""
    report = OfflineReport(dist=str(dist))
    if not dist.is_dir():
        report.errors.append(f"构建产物目录不存在：{dist}（先执行 make frontend-build）")
        return report
    if not (dist / "index.html").is_file():
        report.errors.append(f"缺少入口文件：{dist / 'index.html'}")

    for path in sorted(dist.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {"node_modules", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - IO 异常
            report.errors.append(f"无法读取 {path}：{exc}")
            continue
        report.checked_files += 1
        for match in _EXTERNAL_REF_RE.finditer(text):
            url = match.group("attr") or match.group("css") or match.group("import") or ""
            if not url or _allowed(url):
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            report.external_refs.append(
                {
                    "file": str(path.relative_to(dist)),
                    "line": line_no,
                    "url": url,
                }
            )
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="python -m shared.deploy.offline_assets",
        description="前端构建产物离线检查（禁止外部 http(s) 资源引用）",
    )
    parser.add_argument(
        "--dist",
        default="modules/m5-views-console/frontend/dist",
        help="构建产物目录（相对仓库根或绝对路径）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    dist = Path(args.dist)
    report = scan_dist(dist)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"离线资源检查：{dist}（扫描 {report.checked_files} 个文本文件）")
        if report.errors:
            for error in report.errors:
                print(f"[FAIL] {error}")
        for ref in report.external_refs:
            print(f"[FAIL] {ref['file']}:{ref['line']} 外链 {ref['url']}")
        print(f"结果：{report.result}")
    return 0 if report.result == "pass" else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
