"""M7-1: dashboard presentation fixes found in the 2026-11-07 browser pass.

Each test runs the shipped helper in Node, so a regression is caught in the
exact code the browser loads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
CATALOG = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on this machine")


def _js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced function {name}")


def _run(functions: list[str], body: str):
    assert NODE
    script = "\n".join(
        [
            "let language = 'en'; const I18N = {bs: {}};",
            *(_js_function(JS, name) for name in functions),
            body,
        ]
    )
    done = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_names_with_diacritics_keep_their_case():
    out = _run(
        ["tr", "capitalizeWords", "formatTeamName", "formatLeague"],
        "process.stdout.write(JSON.stringify(["
        "formatTeamName('FK Željezničar'), formatTeamName('atlético madrid'),"
        "formatTeamName('čelik_zenica'), formatTeamName(\"o'higgins\"),"
        "formatLeague('premijer liga BiH')]));",
    )
    assert out == [
        "FK Željezničar",
        "Atlético Madrid",
        "Čelik Zenica",
        "O'higgins",
        "Premijer Liga BiH",
    ]


@needs_node
def test_recheck_banner_renders_the_age_span_not_escaped_markup():
    out = _run(
        ["tr", "escapeHtml", "trWithMarkup"],
        "const ago = '<span data-ago=\"1\">5s ago</span>';"
        "process.stdout.write(JSON.stringify(["
        "trWithMarkup('Checked {ago}. Do not place.', { ago }),"
        "trWithMarkup('<b>{ago}</b>', { ago: '<i>x</i>' })]));",
    )
    assert out[0] == 'Checked <span data-ago="1">5s ago</span>. Do not place.'
    # The copy itself is still escaped; only the named markup is trusted.
    assert out[1] == "&lt;b&gt;<i>x</i>&lt;/b&gt;"


def test_banner_placeholders_go_through_trWithMarkup():
    banner = _js_function(JS, "renderVerifyBanner")
    assert "escapeHtml(tr('Checked {ago}" not in banner
    assert "escapeHtml(tr('re-checked {ago}" not in banner
    assert banner.count("trWithMarkup(") == 3


def test_unconfirmed_recheck_badge_is_a_word_in_both_languages():
    label = _js_function(JS, "verifyShortLabel")
    assert "return '?'" not in label
    assert "tr('unconfirmed')" in label
    assert '"unconfirmed": "nepotvrđeno"' in CATALOG
    assert ".row-check-unknown" in CSS


def test_quiet_banner_only_applies_before_a_scan_with_nothing_listed():
    banner = _js_function(JS, "renderFreshnessBanner")
    assert "fresh.state === 'never_scanned' && allSurebets.length === 0" in banner
    # Rows on screen must restore the full warning, so the row count is part
    # of the re-render signature.
    assert "allSurebets.length === 0," in banner
    assert ".freshness-banner-quiet" in CSS
