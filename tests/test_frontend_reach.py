"""SR9-4 frontend: the card's "Match links: N/M" count and the per-leg marking.

The shipped helpers and the real `buildSurebetRow` are lifted out of app.js and
run in node with stubbed display helpers, so the count and the marking are
tested as the browser builds them. The slip's leg markup is asserted against the
shipped source because `renderSlip` needs the whole page state.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
CATALOG = json.loads(
    (ROOT / "frontend/js/i18n.js").read_text(encoding="utf-8")
    .split("window.I18N =", 1)[1]
    .strip()
    .rstrip(";")
)["bs"]
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on this machine")

_PREAMBLE = """\
const document = { createElement: () => ({ dataset: {}, className: '', innerHTML: '', setAttribute() {}, addEventListener() {} }) };
const I18N = { bs: {} };
let language = 'en';
const verifyState = {};
const globalInvestment = 100;
let currentMode = 'prematch';
@tr@
@escapeHtml@
function placementOrder(stakes) { return stakes; }
function bookName(id) { return id; }
function bookShort(id) { return id; }
function outcomeDescription() { return 'desc'; }
function parseKickoff() { return null; }
function formatKickoff() { return ''; }
function profitTier() { return 'mid'; }
function money(value) { return Number(value).toFixed(2); }
function marketLabel(type) { return type; }
function formatLeague(league) { return league; }
function formatTeamName(name) { return name; }
function applyDynamicStyles() {}
@legReachesMatch@
@reachSummary@
@buildSurebetRow@
"""


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


def _driver(tail: str) -> str:
    source = _PREAMBLE
    for name in (
        "tr",
        "escapeHtml",
        "legReachesMatch",
        "reachSummary",
        "buildSurebetRow",
    ):
        source = source.replace(f"@{name}@", _js_function(JS, name))
    assert "@" not in source, "an unfilled placeholder is left in the node driver"
    return source + tail


def _run(source: str) -> str:
    assert NODE, "node disappeared between the skipif and this call"
    completed = subprocess.run(
        [NODE, "-e", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, f"the node driver failed:\n{completed.stderr}"
    return completed.stdout


def _leg(kind: str | None, url: str = "https://example.test/x") -> dict:
    if kind is None:
        return {"bookmaker": "maxbet", "outcome_label": "1", "odds": 2.0, "destination": None}
    return {
        "bookmaker": "maxbet",
        "outcome_label": "1",
        "odds": 2.0,
        "destination": {"kind": kind, "url": url},
    }


def _reaches(legs: list[dict]) -> list[bool]:
    payload = json.dumps(legs)
    return json.loads(
        _run(_driver(f"process.stdout.write(JSON.stringify({payload}.map(legReachesMatch)));"))
    )


@needs_node
@pytest.mark.parametrize(
    ("kind", "url", "expected"),
    [
        ("ticket_filled", "https://example.test/x", True),
        ("match_page", "https://example.test/x", True),
        ("competition", "https://example.test/x", False),
        ("search", "", False),
        ("ticket_filled", "", False),
        (None, "", False),
    ],
)
def test_only_a_ticket_or_match_url_reaches_the_fixture(kind, url, expected):
    [reaches] = _reaches([_leg(kind, url)])
    assert reaches is expected


@needs_node
def test_reach_summary_counts_every_leg_and_marks_all():
    legs = [
        _leg("ticket_filled"),
        _leg("match_page"),
        _leg("competition"),
        _leg("search", ""),
    ]
    summary = json.loads(
        _run(_driver(f"process.stdout.write(JSON.stringify(reachSummary({{stakes: {json.dumps(legs)}}})));"))
    )
    assert summary == {"opened": 2, "legs": 4, "all": False}

    all_reach = json.loads(
        _run(
            _driver(
                f"process.stdout.write(JSON.stringify(reachSummary({{stakes: {json.dumps(legs[:2])}}})));"
            )
        )
    )
    assert all_reach == {"opened": 2, "legs": 2, "all": True}

    empty = json.loads(
        _run(_driver("process.stdout.write(JSON.stringify(reachSummary({stakes: []})));"))
    )
    assert empty == {"opened": 0, "legs": 0, "all": False}


@needs_node
def test_the_row_shows_the_count_and_marks_each_generic_leg():
    sb = {
        "id": "abc12345",
        "profit_percent": 2.4,
        "kickoff": None,
        "home_team": "Home",
        "away_team": "Away",
        "league": "League",
        "market_type": "1x2",
        "stakes": [
            _leg("ticket_filled"),
            _leg("competition"),
            _leg("search", ""),
        ],
    }
    html = _run(_driver(f"process.stdout.write(buildSurebetRow({json.dumps(sb)}).innerHTML);"))
    assert "Match links: 1/3" in html
    assert html.count('data-reach="no"') == 2
    assert html.count('data-reach="yes"') == 1
    assert html.count("leg-pill-generic") == 2
    assert "no per-match link" in html


@needs_node
def test_a_fully_linked_row_is_marked_as_such():
    sb = {
        "id": "abc12345",
        "profit_percent": 1.1,
        "kickoff": None,
        "home_team": "Home",
        "away_team": "Away",
        "league": "",
        "market_type": "1x2",
        "stakes": [_leg("ticket_filled"), _leg("match_page")],
    }
    html = _run(_driver(f"process.stdout.write(buildSurebetRow({json.dumps(sb)}).innerHTML);"))
    assert "Match links: 2/2" in html
    assert "row-reach-all" in html
    assert "leg-pill-generic" not in html


def test_the_slip_marks_a_leg_without_a_per_match_link():
    assert "leg-no-match${" not in JS  # the class is composed, not concatenated raw
    assert "${reaches ? '' : ' leg-no-match'}" in JS
    assert 'class="leg-no-match-tag"' in JS
    assert "SR9-4: when the leg has no per-match link" in JS
    assert "const listingOrder = reaches ? `${listedSpan}${copyButton}` : `${copyButton}${listedSpan}`;" in JS


def test_the_new_copy_has_bosnian_entries():
    assert CATALOG["Match links: {opened}/{legs}"] == "Linkovi na utakmicu: {opened}/{legs}"
    assert CATALOG["no per-match link"] == "nema linka na utakmicu"


def test_the_hide_option_is_not_implemented_before_the_operator_decides():
    """SR9-4 is gated on a recorded decision for hiding/deprioritising rows."""
    assert "hide" not in JS[JS.index("function buildSurebetRow"): JS.index("function profitTier")]
    combined = JS.lower()
    assert "data-hide-unlinked" not in combined
    assert "hide-unlinked" not in combined
