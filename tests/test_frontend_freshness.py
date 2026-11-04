"""P0-4: the dashboard must make a stale feed look historical, not current.

The API labels staleness; this file pins the browser half of the contract. The
age is recomputed from the scan timestamp, so a page left open crosses the TTL
without a reload, and copying stale prices is disabled while Re-check stays
available as the only way to establish a current price.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (REPO_ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
CSS = (REPO_ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on this machine")


def _js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced function {name}")


def test_stale_banner_exists_before_the_tabs():
    assert 'id="freshness-banner"' in HTML
    assert 'role="alert"' in HTML
    assert HTML.index('id="freshness-banner"') < HTML.index('class="results-tabs"')
    assert ".freshness-banner" in CSS
    assert "body.feed-stale .sb-row" in CSS


def test_results_paint_and_tick_the_banner():
    assert "freshnessSnapshot = data.freshness" in JS
    assert "renderFreshnessBanner();" in JS
    assert "currentFreshness()" in JS
    assert "const stale = Boolean(freshnessSnapshot.stale) || age == null" in JS
    tick = _js_function(JS, "tickAges")
    assert "renderFreshnessBanner();" in tick
    assert "document.body.classList" in tick


def test_stale_copy_actions_are_disabled_but_recheck_is_not():
    copy_attributes = _js_function(JS, "copyAttributes")
    assert "staleFeed()" in copy_attributes
    assert 'disabled aria-disabled="true" data-stale-blocked="true"' in copy_attributes

    copy_slip = JS[JS.index('data-action="copy-surebet"'):]
    copy_slip = copy_slip[: copy_slip.index("</button>")]
    assert "staleFeed()" in copy_slip
    assert "data-stale-blocked" in copy_slip

    recheck = JS[JS.index('data-action="verify-surebet"'):]
    recheck = recheck[: recheck.index("</button>")]
    assert "disabled" not in recheck, (
        "verify must stay enabled: it is the only path that re-establishes a "
        "leg's current price"
    )
    assert "data-stale-blocked" not in recheck


def test_slip_says_the_prices_are_historical():
    assert "These are historical scan prices, not a current opportunity" in JS
    assert "Re-check odds" in JS


@needs_node
def test_staleness_is_recomputed_from_the_scan_time():
    script = "\n".join(
        [
            _js_function(JS, "parseKickoff"),
            _js_function(JS, "currentFreshness"),
            _js_function(JS, "staleFeed"),
            "let freshnessSnapshot;",
            "const ageIso = (ms) => new Date(Date.now() - ms).toISOString();",
            "const out = [];",
            "freshnessSnapshot = {mode: 'prematch', ttl_sec: 600, "
            "scan_time: ageIso(30000), stale: false, state: 'fresh', stale_books: []};",
            "out.push(staleFeed());",
            "freshnessSnapshot = {...freshnessSnapshot, scan_time: ageIso(601000)};",
            "out.push(staleFeed());",
            "freshnessSnapshot = {mode: 'prematch', ttl_sec: 600, "
            "scan_time: ageIso(1000), stale: true, state: 'book_older_than_ttl', "
            "stale_books: ['wwin']};",
            "out.push(staleFeed());",
            "console.log(JSON.stringify(out));",
        ]
    )
    completed = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == [False, True, True]
