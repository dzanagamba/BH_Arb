"""N0-3: the CSP has no inline-style escape hatch.

The dashboard used to set colours and widths through ``style="..."`` attributes,
so ``style-src`` had to admit ``'unsafe-inline'``. The values are now written as
CSS custom properties through the CSSOM, which CSP does not treat as an inline
style attribute, and the shipped HTML/JS carries no style attributes at all.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "frontend" / "index.html"
JS_PATH = REPO_ROOT / "frontend" / "js" / "app.js"
CSS_PATH = REPO_ROOT / "frontend" / "css" / "style.css"

STYLE_ATTRIBUTE_RE = re.compile(r"(?<![\w-])style\s*=\s*[\"']")


def _directive(csp: str, name: str) -> str:
    for directive in csp.split(";"):
        key, _, value = directive.strip().partition(" ")
        if key == name:
            return value
    raise AssertionError(f"{name} is missing from CSP: {csp}")


def _style_src(csp: str) -> str:
    return _directive(csp, "style-src")


def _inline_style_attributes(text: str) -> list[str]:
    return STYLE_ATTRIBUTE_RE.findall(text)


def test_dashboard_and_api_csp_do_not_allow_inline_styles():
    client = TestClient(app)
    for path in ("/", "/api/health", "/api/results?mode=prematch"):
        response = client.get(path)
        assert response.status_code == 200, path
        style_src = _style_src(response.headers["content-security-policy"])
        assert "'unsafe-inline'" not in style_src, f"{path}: {style_src}"
        assert "'self'" in style_src
        assert "https://fonts.googleapis.com" in style_src


def test_no_shipped_html_or_javascript_contains_a_style_attribute():
    for path in (HTML_PATH, JS_PATH):
        text = path.read_text(encoding="utf-8")
        assert _inline_style_attributes(text) == [], (
            f"{path.name} still ships an inline style attribute; write the value "
            "through CSSOM or a class instead"
        )


def test_the_style_attribute_check_catches_a_sample():
    assert _inline_style_attributes('<div style="display:none"></div>')
    assert _inline_style_attributes("<span style='--color:#fff'></span>")
    assert not _inline_style_attributes('<div data-style="x"></div>')
    assert not _inline_style_attributes("element.style.setProperty('--color', '#fff')")


def test_no_inline_style_block_is_shipped():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "<style" not in html.lower(), (
        "an inline <style> block would need a style nonce; this dashboard ships "
        "a stylesheet instead"
    )


def test_dynamic_colours_and_widths_use_cssom_custom_properties():
    js = JS_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    assert "style.setProperty('--color'" in js
    assert "style.setProperty('--progress'" in js
    assert "style.setProperty('--scan-progress'" in js
    assert "var(--progress" in css
    assert "var(--scan-progress" in css
    assert "[hidden]" in css, "display toggles rely on the [hidden] rule"
