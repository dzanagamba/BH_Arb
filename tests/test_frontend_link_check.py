"""SR9-3 frontend: the slip's per-leg link-check panel, driven as shipped.

The real functions are lifted out of `frontend/js/app.js` and run in node with
stubbed display helpers, so the panel's rows, its timestamp and its escaping are
tested as the browser gets them, not as a transcription of them.
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
const I18N = { bs: {} };
let language = 'en';
let linkCheckState = {};
@tr@
@escapeHtml@
@trWithMarkup@
function formatAgo(dt) { return '1 min ago'; }
function bookName(id) { return String(id).toUpperCase(); }
@linkStatusLabel@
@renderLinkCheckPanel@
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
    for name in ("tr", "escapeHtml", "trWithMarkup", "linkStatusLabel", "renderLinkCheckPanel"):
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


def _render(payload: dict) -> str:
    tail = (
        f"linkCheckState[{json.dumps(payload['id'])}] = "
        f"{{ state: {json.dumps(payload.get('state', 'done'))}, "
        f"at: new Date({int(payload.get('at', 1_700_000_000_000))}), "
        f"data: {json.dumps(payload.get('data') or {})}, "
        f"message: {json.dumps(payload.get('message', ''))} }};\n"
        f"process.stdout.write(renderLinkCheckPanel({{ id: {json.dumps(payload['id'])} }}));"
    )
    return _run(_driver(tail))


def _report(legs: list[dict], **overrides) -> dict:
    payload = {
        "id": "abc12345",
        "state": "done",
        "at": 1_700_000_000_000,
        "data": {"legs": legs, "skip_reason": ""},
    }
    payload.update(overrides)
    return payload


def _leg(**overrides) -> dict:
    leg = {
        "bookmaker": "maxbet",
        "kind": "match_page",
        "opens_fixture": True,
        "ticket_has_selection": False,
        "failed": False,
        "status": "ok",
        "evidence": "the page shows both team names",
        "error": "",
    }
    leg.update(overrides)
    return leg


@needs_node
def test_the_panel_shows_one_row_per_leg_and_its_time():
    html = _render(
        _report(
            [
                _leg(kind="ticket_filled", ticket_has_selection=True),
                _leg(bookmaker="mdshop"),
            ]
        )
    )
    assert '<ul class="linkcheck-legs">' in html
    assert html.count("<li") == 2
    assert "MAXBET" in html and "MDSHOP" in html
    assert "Ticket has the pick" in html
    assert "Opens the match" in html
    assert "1 min ago" in html
    assert "data-ago=" in html
    assert "2 of 2 legs open the match" in html
    assert "advisory" in html


@needs_node
def test_a_failed_leg_is_marked_bad_and_a_skip_is_greyed():
    html = _render(
        _report(
            [
                _leg(status="ticket_empty", failed=True, ticket_has_selection=False),
                _leg(
                    bookmaker="sportplus",
                    kind="competition",
                    opens_fixture=False,
                    status="skipped",
                    evidence="no per-fixture link",
                ),
            ]
        )
    )
    assert "linkcheck-bad" in html
    assert "Ticket is empty" in html
    assert "linkcheck-skip" in html
    assert "Not checked (no per-fixture link)" in html


@needs_node
def test_a_surebet_with_nothing_to_open_says_why():
    html = _render(
        _report([], data={"legs": [], "skip_reason": "no leg has a per-fixture link"})
    )
    assert "no leg has a per-fixture link" in html
    assert "<ul" not in html


@needs_node
def test_a_failed_request_shows_the_reason():
    html = _render(
        {
            "id": "abc12345",
            "state": "error",
            "at": 1_700_000_000_000,
            "message": "This surebet's links were checked moments ago",
        }
    )
    assert "This surebet&#039;s links were checked moments ago" in html


@needs_node
def test_the_leg_evidence_is_escaped():
    html = _render(_report([_leg(evidence='<img src=x onerror="alert(1)">')]))
    assert "<img" not in html
    assert "&lt;img" in html


@needs_node
def test_the_skip_reason_is_escaped():
    html = _render(_report([], data={"legs": [], "skip_reason": "<script>alert(1)</script>"}))
    assert "<script" not in html
    assert "&lt;script" in html


@needs_node
@pytest.mark.parametrize(
    ("status", "kind", "label"),
    [
        ("ok", "ticket_filled", "Ticket has the pick"),
        ("ok", "match_page", "Opens the match"),
        ("ticket_empty", "ticket_filled", "Ticket is empty"),
        ("fixture_not_found", "match_page", "Fixture not found"),
        ("error", "match_page", "Link check failed"),
        ("skipped", "competition", "Not checked (no per-fixture link)"),
    ],
)
def test_every_backend_status_has_a_label(status: str, kind: str, label: str):
    tail = (
        "process.stdout.write(linkStatusLabel("
        f"{json.dumps({'status': status, 'kind': kind})}));"
    )
    assert _run(_driver(tail)) == label


def test_every_new_label_has_bosnian_copy():
    for key in (
        "Check links",
        "Checking links…",
        "Ticket has the pick",
        "Opens the match",
        "Ticket is empty",
        "Fixture not found",
        "Link check failed",
        "Not checked (no per-fixture link)",
        "Could not check the links: {error}",
        "{opened} of {legs} legs open the match",
        "checked {ago}.",
        "The link check is advisory; it never proves a link for the certainty gate.",
    ):
        assert key in CATALOG, f"missing Bosnian copy for {key!r}"


def test_the_slip_wires_the_button_to_the_scoped_route():
    assert 'data-action="check-links"' in JS
    assert "/check-links?mode=${currentMode}" in JS
    assert "case 'check-links': checkSurebetLinks(element.dataset.slipId); break;" in JS
    assert "${renderLinkCheckPanel(sb)}" in JS
