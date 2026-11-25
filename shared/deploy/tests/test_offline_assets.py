"""``shared.deploy.offline_assets`` 的单元测试：构建产物不得含外部资源引用。"""

from __future__ import annotations

from pathlib import Path

from shared.deploy.offline_assets import main, scan_dist


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_clean_dist_passes(tmp_path: Path) -> None:
    """只用本地资源（字体/图标/CSS）时应通过。"""
    dist = tmp_path / "dist"
    _write(
        dist / "index.html",
        "<!doctype html><html><head>"
        '<link rel="stylesheet" href="/assets/index.css">'
        '<link rel="icon" href="/favicon-overview.svg">'
        '</head><body><div id="app"></div>'
        '<script type="module" src="/assets/index.js"></script></body></html>',
    )
    _write(dist / "assets" / "index.css", "@font-face{src:url('/assets/font.woff2')}")
    _write(dist / "assets" / "index.js", "console.log('ok')\n")
    _write(dist / "favicon-overview.svg", '<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    report = scan_dist(dist)
    assert report.result == "pass", report.as_dict()


def test_external_script_flagged_with_line(tmp_path: Path) -> None:
    """外链脚本必须 FAIL，并给出文件与行号。"""
    dist = tmp_path / "dist"
    _write(
        dist / "index.html",
        '<!doctype html>\n<script src="https://cdn.example.com/vue.js"></script>\n',
    )
    report = scan_dist(dist)
    assert report.result == "fail"
    ref = report.external_refs[0]
    assert ref["file"] == "index.html"
    assert ref["line"] == 2
    assert str(ref["url"]).startswith("https://cdn.example.com")


def test_external_css_url_flagged(tmp_path: Path) -> None:
    """CSS 中的外链字体/背景图同样必须 FAIL。"""
    dist = tmp_path / "dist"
    _write(dist / "index.html", '<link rel="stylesheet" href="/assets/a.css">')
    _write(
        dist / "assets" / "a.css",
        "@font-face{src:url('https://fonts.example.com/x.woff2')}\n",
    )
    report = scan_dist(dist)
    assert report.result == "fail"
    assert any("fonts.example.com" in str(item["url"]) for item in report.external_refs)


def test_svg_namespace_is_allowed(tmp_path: Path) -> None:
    """SVG/XML 命名空间不是网络请求，不应误报。"""
    dist = tmp_path / "dist"
    _write(dist / "index.html", "<html></html>")
    _write(
        dist / "logo.svg",
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>',
    )
    report = scan_dist(dist)
    assert report.result == "pass", report.as_dict()


def test_missing_dist_and_index_reported(tmp_path: Path) -> None:
    """产物目录或 index.html 缺失时应返回错误。"""
    report = scan_dist(tmp_path / "nope")
    assert report.result == "fail"
    assert report.errors

    dist = tmp_path / "dist"
    dist.mkdir()
    report2 = scan_dist(dist)
    assert report2.result == "fail"
    assert any("index.html" in error for error in report2.errors)


def test_cli_exit_codes(tmp_path: Path) -> None:
    """CLI：干净产物退出 0，外链退出 1。"""
    dist = tmp_path / "dist"
    _write(dist / "index.html", "<html><script src='/a.js'></script></html>")
    assert main(["--dist", str(dist)]) == 0
    _write(dist / "index.html", "<html><script src='https://evil.example/a.js'></script></html>")
    assert main(["--dist", str(dist)]) == 1
