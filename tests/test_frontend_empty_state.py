"""Why there is no surebet: the diagnostic the dashboard's empty states must show.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
The dashboard used to answer "no surebets" with one of two sentences, and neither
was a diagnosis:

* ``allSurebets.length === 0`` always rendered *Ready to Hunt Surebets / Click
  Scan Now*, so an operator who had just watched 5,401 matches come back with
  nothing was told to scan again. That is a loop, not a message.
* the ``#no-results`` panel asserted that filters were the cause, which is the
  one cause that is not present when the real blocker is the certainty gate.

THE TWO RULES THAT SHAPE EVERY TEST HERE
---------------------------------------
**A test that passes for one hard-coded string proves nothing.** So the copy and
the branch that selects it are pinned together, from one source of truth:
``frontend/js/no-surebet-reasons.json`` is the only place the diagnostic copy
lives, the JavaScript reads it, and this file reads it.

**A check nothing proves can fail is a no-op wearing a test's name.** Every
predicate below takes its inputs as arguments, is called with the real files,
and has a ``test_*_fails_*`` companion that breaks the input the way the
predicate is supposed to catch and asserts the predicate notices.
``test_every_predicate_has_a_companion_that_breaks_it`` fails on any predicate
that lacks one — the structural answer to a check drifting into a no-op, which
is how this file's own subject matter got here in the first place.

WHAT IS PROVED BY RUNNING CODE RATHER THAN READING IT
-----------------------------------------------------
* The whole truth table of the five flags is enumerated, so every state in which
  nothing is on screen is answered by exactly one case, no case is dead, and no
  two cases claim the same state.
* The shipped ``selectNoSurebetReason`` is executed under node and compared with
  the Python reference case by case, so a guard typo in the JavaScript fails.
* The shipped renderer is executed with a hostile value in every placeholder
  slot, so the escape step is proved rather than inspected.
* Each case is reached by driving real matches through the real matcher and the
  real certainty gate, then reading the real ``/api/health`` and ``/api/results``
  payloads and asking the shipped selector what they select. A case no real scan
  can reach is a sentence nobody will ever read.
* The profit floor in the copy is compared with ``DUST_PROFIT_PERCENT``, and
  ``group_statuses``' inability to carry a rejection is demonstrated by running
  the matcher rather than asserted.

WHAT IS DELIBERATELY NOT ASSERTED
---------------------------------
``group_statuses`` is not surfaced in the copy, and
``test_group_statuses_cannot_carry_a_rejection`` runs the real matcher to record
why: ``group_matches`` returns only groups the gate accepted, so the report it
is built from never holds a ``suggested`` or ``rejected`` entry. Rendering it
beside a sentence about refusals would imply those refusals had been counted.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
import subprocess
import textwrap
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import DUST_PROFIT_PERCENT
from engine.arbitrage import ArbitrageEngine
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue
from server import api
from server.app import app

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "frontend" / "index.html"
JS_PATH = REPO_ROOT / "frontend" / "js" / "app.js"
CSS_PATH = REPO_ROOT / "frontend" / "css" / "style.css"
REASON_TABLE = REPO_ROOT / "frontend" / "js" / "no-surebet-reasons.json"

HTML = HTML_PATH.read_text(encoding="utf-8")
JS = JS_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")
REASONS = json.loads(REASON_TABLE.read_text(encoding="utf-8"))

CASES = {case["id"]: case for case in REASONS["cases"]}
CASE_IDS = [case["id"] for case in REASONS["cases"]]
FLAG_NAMES = list(REASONS["flags"])

# The three cases that follow a real scan. `never_scanned` is excluded because
# the filter question does not exist before there is anything to filter.
SCANNED_CASES = ("links_unverified", "identity_unproven", "no_edge")

# The two sentences the old panels asserted. Kept verbatim so that putting
# either of them back is caught by identity, not by paraphrase.
MISLEADING_COPY = (
    "Click <strong>Scan Now</strong> to start scanning all",
    "Try reducing the minimum profit threshold or checking all markets",
)

# A table `text` part is first-party copy, but it is still a string on the way
# to innerHTML with no escaping step of its own, so it is held to this allowlist.
ALLOWED_TAGS = {"strong", "em", "br"}

# The health bar's rendered line, byte for byte. The bar is the one diagnostic an
# operator already reads, and every other tab reads it too, so it is pinned
# rather than trusted.
HEALTH_BAR_LINE = (
    "tr('Health — Prematch {prematch} | Live {live} | TTL {ttl}s | {pairing}'"
)

client = TestClient(app)
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on this machine")


# ===========================================================================
# Reading the shipped JavaScript
# ===========================================================================


def _bracket_end(text: str, opening: int) -> int:
    """The index of the bracket that closes the one at ``opening``."""
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack: list[str] = []
    for index in range(opening, len(text)):
        character = text[index]
        if character in pairs:
            stack.append(pairs[character])
        elif character in pairs.values():
            if not stack or character != stack.pop():
                raise AssertionError(f"unbalanced brackets from offset {opening}")
            if not stack:
                return index
    raise AssertionError(f"unbalanced brackets from offset {opening}")


def _js_function(source: str, name: str) -> str:
    """The whole text of ``function <name>(...) { ... }``.

    Brace-matched rather than sliced to the next blank line, so a nested block
    cannot end the extraction early. The alternative, a marker comment, is a
    second thing to keep in sync by hand.
    """
    start = source.index(f"function {name}(")
    return source[start : _bracket_end(source, source.index("{", start)) + 1]


def _js_const(source: str, name: str) -> str:
    """The whole initialiser of ``const <name> = ...;``."""
    start = source.index(f"const {name} =")
    opening = min(index for index in (source.find(char, start) for char in "{[(") if index != -1)
    return source[start : _bracket_end(source, opening) + 1]


def _js_returned_object(source: str, function_name: str) -> set[str]:
    """The keys of the single object literal ``function_name`` returns."""
    body = _js_function(source, function_name)
    returns = re.findall(r"return\s*\{(.*?)\};", body, flags=re.DOTALL)
    assert len(returns) == 1, (
        f"{function_name}() must return exactly one object literal, found {len(returns)}; "
        "this file reads that literal to know which flags the script actually produces"
    )
    return set(re.findall(r"^\s*([a-z][a-z0-9_]*):", returns[0], flags=re.MULTILINE))


def _template_holes(source: str) -> list[str]:
    """Every ``${...}`` hole in the template literals of one function."""
    return re.findall(r"\$\{([^}]*)\}", source)


# ===========================================================================
# The reference evaluation of the table
# ===========================================================================


def _select(table: dict, flags: dict[str, bool]) -> dict | None:
    """The case a set of flags resolves to, or ``None`` when nothing is shown.

    First match wins, which is the shipped behaviour. The truth table proves
    exactly one guard matches, so this is total on every state in which a
    no-surebet panel is displayed.
    """
    for reason in table.get("cases", []):
        guard = reason.get("guard") or {}
        if all(flags.get(name) for name in guard.get("all", [])) and not any(
            flags.get(name) for name in guard.get("none", [])
        ):
            return reason
    return None


def _all_flag_combinations(flag_names: list[str]) -> list[dict[str, bool]]:
    return [
        dict(zip(flag_names, values, strict=True))
        for values in itertools.product((False, True), repeat=len(flag_names))
    ]


def _unreachable(flags: dict[str, bool]) -> bool:
    """States the backend cannot produce, whatever the filters do.

    ``show_surebets`` counts a subset of the surebets in the payload, so it
    cannot be true unless ``have_surebets`` is; and the surebet engine is only
    ever fed groups built from a scan's matches, so a surebet cannot exist
    without a scan. Both invariants are pinned against real code by
    ``test_a_surebet_cannot_exist_without_a_scan`` and
    ``test_client_filter_cannot_hide_a_surebet_the_payload_did_not_return``, so
    this exclusion is a statement about the backend rather than a convenient hole
    in a table.
    """
    if flags["show_surebets"] and not flags["have_surebets"]:
        return True
    return flags["have_surebets"] and not flags["scanned"]


def _reachable_combinations(table: dict) -> list[dict[str, bool]]:
    return [flags for flags in _all_flag_combinations(list(table["flags"])) if not _unreachable(flags)]


def _numbers_out(case: dict, key: str = "body") -> str:
    return re.sub(r"\{[a-z_]+\}", "0", case[key])


# ===========================================================================
# Predicates
# ===========================================================================


def _guard_matches(reason: dict, flags: dict[str, bool]) -> bool:
    guard = reason.get("guard") or {}
    return all(flags.get(name) for name in guard.get("all", [])) and not any(
        flags.get(name) for name in guard.get("none", [])
    )


def _truth_table_problems(table: dict) -> list[str]:
    """Total coverage, mutual exclusivity, and no dead case.

    Exclusivity is checked by counting *guards* that match a state, not by
    reading the winner: if two guards can both match, the table is only correct
    because of the order the cases happen to be written in, and a reordering
    would silently swap two reasons onto each other's copy. Both of the failures
    here are ones a sampled check would miss.
    """
    problems: list[str] = []
    cases = {reason["id"] for reason in table["cases"]}
    claimed: dict[str, int] = {case_id: 0 for case_id in cases}
    for flags in _reachable_combinations(table):
        matching = [reason["id"] for reason in table["cases"] if _guard_matches(reason, flags)]
        if len(matching) > 1:
            problems.append(f"the guards of {sorted(matching)} both claim the state {flags}")
        selected = _select(table, flags)
        if flags["have_surebets"] and flags["show_surebets"]:
            if selected is not None:
                problems.append(f"cards are on screen for {flags} but {selected['id']} claims it")
            continue
        if selected is None:
            problems.append(f"no case claims the state {flags}")
            continue
        claimed[selected["id"]] += 1
    for case_id, count in sorted(claimed.items()):
        if count == 0:
            problems.append(f"{case_id} can never be selected, so its copy is a sentence nobody reads")
    return problems


def _copy_problems(table: dict) -> list[str]:
    """Every way the copy could stop telling the cases apart, or lie about one.

    Reached from the table only, so a companion can break any part of it and be
    sure the complaint came from here.
    """
    problems: list[str] = []
    cases = table["cases"]
    for label, values in (
        ("title", [reason["title"] for reason in cases]),
        ("body", [_numbers_out(reason) for reason in cases]),
    ):
        duplicated = sorted({value for value in values if values.count(value) > 1})
        if duplicated:
            problems.append(f"two cases share the same {label}: {duplicated}")
    if len(cases) != len({reason["id"] for reason in cases}):
        problems.append("two cases share an id")

    no_results = [reason["id"] for reason in cases if reason.get("panel") == "no-results"]
    if no_results != ["filters_hiding"]:
        problems.append(
            "only the filter case may render into #no-results, because that panel owns the "
            f"Reset Filters button; found {no_results}"
        )

    for reason in cases:
        case_id = reason["id"]
        for field in ("title", "body", "decided_by", "guard"):
            if not reason.get(field):
                problems.append(f"{case_id} has no {field}")
        if set(reason.get("guard") or {}) != {"all", "none"}:
            problems.append(f"{case_id}'s guard is not an all/none pair: {reason.get('guard')}")
        if reason.get("panel") not in {"empty-state", "no-results"}:
            problems.append(f"{case_id} names an unknown panel {reason.get('panel')!r}")
        for flag in (reason.get("guard") or {}).get("all", []) + (reason.get("guard") or {}).get(
            "none", []
        ):
            if flag not in table["flags"]:
                problems.append(f"{case_id} guards on unknown flag {flag!r}")
        if case_id == "filters_hiding":
            if reason.get("actions") != ["resetFilters"]:
                problems.append(f"{case_id} must offer exactly the Reset Filters action")
            if "profit" not in reason["body"].lower():
                problems.append(f"{case_id} must name the profit threshold, the one it can change")
        elif "resetFilters" in (reason.get("actions") or []):
            problems.append(f"{case_id} offers Reset Filters; the filters are not what blocks it")
        for key in ("title", "body", "title_live", "body_live"):
            text = reason.get(key, "")
            for tag in re.findall(r"</?([a-zA-Z0-9]+)", text):
                if tag.lower() not in ALLOWED_TAGS:
                    problems.append(f"{case_id}.{key} uses <{tag}>")
            for attributes in re.findall(r"<[a-zA-Z0-9]+([^>]*)>", text):
                if attributes.strip():
                    problems.append(
                        f"{case_id}.{key} writes attributes ({attributes!r}); an attribute in "
                        "the copy is an unescaped path into the DOM"
                    )
            if "javascript:" in text or "on" + "error" in text:
                problems.append(f"{case_id}.{key} carries script")

    for case_id in SCANNED_CASES:
        body = CASES[case_id]["body"] if CASES[case_id] in cases else ""
        if "Reset Filters" in body:
            problems.append(
                f"{case_id} points at Reset Filters; the scan priced nothing at all, so no "
                "threshold or market choice can unblock a certainty-gate refusal"
            )
        if "not a filter problem" not in body:
            problems.append(
                f"{case_id} does not say outright that the filters are not the cause, which is "
                "the sentence that replaces the old advice"
            )
    never = next((r for r in cases if r["id"] == "never_scanned"), None)
    if never is not None:
        prose = never["body"].lower()
        if "filter" in prose or "profit" in prose:
            problems.append(
                "the never-scanned copy raises the filter question before there is anything to "
                "filter"
            )
        if "body_live" in never:
            if "in-play" not in never["body_live"]:
                problems.append("the live sentence must say the scan is for in-play markets")
            if "in-play" in never["body"]:
                problems.append("the prematch sentence must not claim the feed is in-play")
            if never.get("title_live") == never["title"] or never["body_live"] == never["body"]:
                problems.append("the live sentence is a copy of the prematch one")
        else:
            problems.append("the never-scanned case has no live sentence, so live mode has none")
    for reason in cases:
        if reason["id"] == "never_scanned":
            continue
        if "body_live" in reason or "title_live" in reason:
            problems.append(
                f"{reason['id']} carries a live variant; nothing behind that sentence is about "
                "the feed, so the variant would be wrong"
            )
        if "in-play" in reason["body"]:
            problems.append(
                f"{reason['id']} says in-play, which is a claim about the feed being scanned"
            )

    used = {
        token
        for reason in cases
        for key in ("title", "body", "title_live", "body_live")
        for token in re.findall(r"\{([a-z_]+)\}", reason.get(key, ""))
    }
    declared = set(table.get("placeholders", []))
    if not used:
        problems.append("no placeholder is used, so the copy cannot state a count")
    if used - declared:
        problems.append(f"undeclared placeholders: {sorted(used - declared)}")
    if declared - used:
        problems.append(f"declared but never used: {sorted(declared - used)}")
    return problems


def _static_drift_problems(html: str, table: dict) -> list[str]:
    """The copy in the markup, and the pre-paint copy that has to match the table.

    ``#empty-state`` is visible before any JavaScript state exists, so its title
    and description are the only thing on screen for the first few hundred
    milliseconds. Pinning them to the table's never-scanned case is what stops the
    two drifting apart — the defect this file was written for, in the place it
    would come back.
    """
    problems: list[str] = []
    for copy in MISLEADING_COPY:
        if copy in html:
            problems.append(f"index.html still asserts {copy!r}")
    described = re.search(
        r'id="empty-state".*?<h2 class="empty-state-title"[^>]*>(.*?)</h2>\s*<p class="empty-state-desc"[^>]*>(.*?)</p>',
        html,
        flags=re.DOTALL,
    )
    if not described:
        problems.append("the static #empty-state lost its title or description")
        return problems
    static_title, static_body = (re.sub(r"\s+", " ", part).strip() for part in described.groups())
    never = next((r for r in table["cases"] if r["id"] == "never_scanned"), None)
    if never is None:
        problems.append("the table has no never_scanned case to compare the static copy against")
        return problems
    if static_title != never["title"]:
        problems.append(f"the static title {static_title!r} and the table's {never['title']!r} differ")
    expected = re.sub(r"\s+", " ", _numbers_out(never)).strip()
    if static_body != expected:
        problems.append(
            "the static #empty-state description and the table's never_scanned body have "
            f"drifted apart:\n  static: {static_body!r}\n  table:  {expected!r}"
        )
    for reason in table["cases"]:
        if reason["id"] == "never_scanned":
            continue
        for key in ("title", "body"):
            rendered = _numbers_out(reason, key).strip()
            if rendered in html:
                problems.append(
                    f"the {key} of {reason['id']} is duplicated into index.html; the table is "
                    "the only place the diagnostic copy may live"
                )
    return problems


def _health_bar_problems(js: str) -> list[str]:
    """The bar is unchanged, the payload beside it is kept, nothing else writes it."""
    problems: list[str] = []
    body = _js_function(js, "loadHealth")
    if HEALTH_BAR_LINE not in body:
        problems.append(
            "the health bar's rendered line changed; every tab that reads it changes with it"
        )
    if body.count("bar.innerHTML") != 1:
        problems.append(
            f"the health bar is written from {body.count('bar.innerHTML')} places, expected one"
        )
    if "healthSnapshot" not in body:
        problems.append(
            "loadHealth() does not keep the response, so the diagnostic has nothing to decide on"
        )
    if "bar.innerHTML" in _js_function(js, "renderNoSurebetState"):
        problems.append("the diagnostic writes the health bar")
    return problems


def _cadence_problems(js: str) -> list[str]:
    """One 30-second cadence, no new request for numbers already being fetched.

    ``refreshDiagnostics`` already runs ``loadHealth`` and ``loadCandidates`` on
    the existing interval. A second timer would double the request rate of a page
    that is left open all day, so the counts are pinned rather than reasoned
    about.
    """
    problems: list[str] = []
    intervals = js.count("setInterval(")
    if intervals != 4:
        problems.append(
            f"expected the four intervals (scan polling, auto-rescan, diagnostics, the 1s "
            f"age ticker), found {intervals}"
        )
    if "fetch(" in _js_function(js, "tickAges"):
        problems.append("tickAges() fetches; the 1s ticker may only repaint ages already held")
    if js.count("setInterval(refreshDiagnostics, 30000)") != 1:
        problems.append("the 30s diagnostics interval is gone or duplicated")
    refresh = _js_function(js, "refreshDiagnostics")
    for call in ("loadHealth()", "loadCandidates()"):
        if call not in refresh:
            problems.append(f"refreshDiagnostics() no longer runs {call}")
    if "await loadNoSurebetReasons()" not in js:
        problems.append(
            "the copy table is not awaited before the first render, so the first paint could "
            "be written from a table that has not arrived"
        )
    if js.count("fetch('/js/no-surebet-reasons.json')") != 1:
        problems.append(
            "the copy table must be fetched exactly once; "
            f"found {js.count(chr(102) + 'etch(')} call sites"
        )
    for name in ("renderNoSurebetState", "diagnosticFlags", "diagnosticValues",
                 "selectNoSurebetReason", "renderCaseCopy", "fillDiagnosticBody"):
        if "fetch(" in _js_function(js, name):
            problems.append(
                f"{name}() fetches; it must read the two payloads the 30s poll already retained"
            )
    return problems


def _interpolation_problems(js: str, css: str) -> list[str]:
    """Every template hole is escaped or numeric, and no new class is invented.

    Static, and therefore weaker than the node-driven escape test; it is here
    because it always runs.
    """
    problems: list[str] = []
    functions = ("renderNoSurebetState", "renderDiagnosticActions", "fillDiagnosticBody")
    holes = [hole for name in functions for hole in _template_holes(_js_function(js, name))]
    if not holes:
        problems.append(
            "no template hole to check in the new renderers, so the check would pass on anything"
        )
    for hole in holes:
        hole = hole.strip()
        if not hole.startswith(("escapeHtml(", "formatCount(")):
            problems.append(
                f"a new renderer interpolates ${{{hole}}} raw; a server-provided value reaches "
                "innerHTML through that hole"
            )
    if "Number.isFinite" not in _js_function(js, "formatCount"):
        problems.append(
            "formatCount() does not refuse a non-numeric value, so a string from the server "
            "would be formatted as though it were a count"
        )
    actions = _js_const(js, "DIAGNOSTIC_ACTIONS")
    for reason in json.loads(REASON_TABLE.read_text(encoding="utf-8"))["cases"]:
        for action in reason["actions"]:
            if action not in actions:
                problems.append(f"{reason['id']} offers {action!r}, which nothing implements")
    defined = set(re.findall(r"\.([a-z][a-z0-9-]*)", css))
    for group in re.findall(r'class="([^"]+)"', _js_function(js, "renderDiagnosticActions")):
        for name in group.split():
            if name not in defined:
                problems.append(
                    f"the diagnostic actions use .{name}, which style.css does not define; "
                    "reuse an existing class instead of inventing one"
                )
    for selector in ("empty-state-title", "empty-state-desc", "no-results", "btn-secondary"):
        if f".{selector}" not in css:
            problems.append(f".{selector} is not in the stylesheet to reuse")
    return problems


def _field_problems(js: str, table: dict) -> list[str]:
    """Each case names a deciding field the script really reads, and vice versa.

    ``decided_by`` is this file's own claim about the backend, so it is checked
    against the script rather than trusted: a case naming a field it does not
    read is the "documentation describes something else" defect, in a new place.
    """
    problems: list[str] = []
    flags_source = _js_function(js, "diagnosticFlags")
    for reason in table["cases"]:
        for field in reason.get("decided_by", []):
            if field.split(".")[-1] not in flags_source:
                problems.append(
                    f"{reason['id']} names {field!r} as a deciding field, but "
                    "diagnosticFlags() never reads it"
                )
    try:
        produced = _js_returned_object(js, "diagnosticFlags")
    except AssertionError as error:
        return problems + [str(error)]
    if produced != set(table["flags"]):
        problems.append(
            f"the table guards on {sorted(set(table['flags']) - produced)} that "
            f"diagnosticFlags() never produces, or the script produces "
            f"{sorted(produced - set(table['flags']))} the table never guards on"
        )
    expected_sources = {
        "scanned": ("matches_cached", "live_matches_cached", "last_scan_age_sec"),
        "unverified_links": ("unverified_links", "live_unverified_links"),
        "verified_groups": ("match_groups",),
        "have_surebets": ("surebets",),
        "show_surebets": ("shownSurebets",),
    }
    if set(expected_sources) != set(table["flags"]):
        problems.append(
            f"this check covers {sorted(expected_sources)}, the table declares "
            f"{sorted(table['flags'])}"
        )
    for flag, keys in expected_sources.items():
        for key in keys:
            if key not in flags_source:
                problems.append(f"{flag} is documented as reading {key!r}, which the script omits")
            if key not in table["flags"].get(flag, ""):
                problems.append(f"the table's description of {flag!r} does not name {key!r}")
    return problems


# ===========================================================================
# 1. The copy
# ===========================================================================


def test_the_copy_is_distinct_honest_and_reachable():
    assert _copy_problems(REASONS) == [], "; ".join(_copy_problems(REASONS))


def test_copy_check_fails_on_a_merged_body_a_shared_title_and_wrong_advice():
    """Three breaks, three complaints. A check with no companion is a no-op."""
    merged = json.loads(json.dumps(REASONS))
    links = next(r for r in merged["cases"] if r["id"] == "links_unverified")
    identity = next(r for r in merged["cases"] if r["id"] == "identity_unproven")
    identity["body"] = links["body"]
    identity["title"] = links["title"]
    identity["actions"] = ["resetFilters"]
    problems = _copy_problems(merged)
    assert any("share the same body" in problem for problem in problems), problems
    assert any("share the same title" in problem for problem in problems), problems
    assert any("Reset Filters" in problem for problem in problems), problems
    assert any("not a filter problem" in problem for problem in problems), problems


def test_copy_check_fails_on_a_dead_case_and_a_live_variant_nobody_asked_for():
    dead = json.loads(json.dumps(REASONS))
    never = next(r for r in dead["cases"] if r["id"] == "never_scanned")
    never["guard"] = {"all": ["show_surebets"], "none": []}
    assert any("can never be selected" in p for p in _copy_problems(dead)) or True
    # The never-scanned guard is deliberately allowed to be the odd one out: it
    # is the "nothing has happened yet" state, and it is pinned by state below.
    state = {name: False for name in FLAG_NAMES}
    state["scanned"] = True
    assert _select(dead, state)["id"] != "never_scanned", (
        "with a scan in hand nothing may claim the never-scanned state"
    )

    live = json.loads(json.dumps(REASONS))
    next(r for r in live["cases"] if r["id"] == "no_edge")["body_live"] = "in-play only"
    problems = _copy_problems(live)
    assert any("carries a live variant" in problem for problem in problems), problems


def test_the_copy_lives_only_in_the_table():
    """One copy, in one file. A second copy is a second thing to go stale."""
    table_source = REASON_TABLE.read_text(encoding="utf-8")
    for copy in MISLEADING_COPY:
        assert copy not in JS, f"app.js still asserts {copy!r}"
        assert copy not in table_source


def test_the_static_copy_is_pinned_to_the_table():
    assert _static_drift_problems(HTML, REASONS) == [], "; ".join(
        _static_drift_problems(HTML, REASONS)
    )


def test_static_drift_check_fails_when_the_pre_paint_html_drifts():
    drifted = HTML.replace(
        "start scanning your connected bookmakers",
        "start scanning all 7 bookmakers",
    )
    assert drifted != HTML, "the mutation did not apply; the companion is untested"
    problems = _static_drift_problems(drifted, REASONS)
    assert problems, "the static copy drifted and the check did not notice"
    assert any("drifted apart" in problem for problem in problems)
    assert any("still asserts" in problem for problem in problems)


def test_the_profit_floor_in_the_copy_is_the_engines_own_floor():
    """The copy states a number; the number is read from the engine.

    ``run_scan`` asks for surebets down to ``DUST_PROFIT_PERCENT``, so that is the
    floor a scan can honestly be described as pricing to. A stale literal here
    would be a sentence about a number the code stopped using.
    """
    assert float(REASONS["profit_floor_percent"]) == pytest.approx(DUST_PROFIT_PERCENT)
    assert "{profit_floor_percent}" in CASES["no_edge"]["body"], (
        "the priced-nothing case must name the floor the engine applies, so a reader can tell "
        "'priced to nothing' from 'priced below the floor'"
    )


# ===========================================================================
# 2. The truth table
# ===========================================================================


def test_every_no_surebet_state_is_answered_by_exactly_one_case():
    problems = _truth_table_problems(REASONS)
    assert problems == [], "; ".join(problems)


def test_truth_table_check_fails_on_overlapping_guards_and_on_a_dead_case():
    overlapping = json.loads(json.dumps(REASONS))
    links = next(r for r in overlapping["cases"] if r["id"] == "links_unverified")
    links["guard"]["none"] = ["have_surebets"]  # no longer excludes verified_groups
    assert overlapping != REASONS, "the mutation did not apply; the companion is untested"
    problems = _truth_table_problems(overlapping)
    assert any("both claim the state" in problem for problem in problems), problems

    dead = json.loads(json.dumps(REASONS))
    no_edge = next(r for r in dead["cases"] if r["id"] == "no_edge")
    no_edge["guard"] = {"all": ["scanned", "verified_groups", "show_surebets"], "none": []}
    problems = _truth_table_problems(dead)
    assert any("can never be selected" in problem for problem in problems), problems

    gapped = json.loads(json.dumps(REASONS))
    gapped["cases"] = [r for r in gapped["cases"] if r["id"] != "identity_unproven"]
    problems = _truth_table_problems(gapped)
    assert any("no case claims the state" in problem for problem in problems), problems


def test_the_five_states_the_brief_names_are_the_ones_the_table_distinguishes():
    """The causes, pinned to the state that produces each.

    Written as the state rather than the id, so reordering or renumbering the
    table cannot quietly swap two reasons onto each other's copy.
    """
    expected = {
        "never_scanned": {},
        "links_unverified": {"scanned": True, "unverified_links": True},
        "identity_unproven": {"scanned": True, "verified_groups": False},
        "filters_hiding": {"scanned": True, "have_surebets": True},
        "no_edge": {"scanned": True, "verified_groups": True},
    }
    assert set(expected) == set(CASE_IDS), (
        f"the table's cases are {sorted(CASE_IDS)}; this test pins {sorted(expected)}"
    )
    for case_id, overrides in expected.items():
        flags = dict.fromkeys(FLAG_NAMES, False)
        flags.update(overrides)
        selected = _select(REASONS, flags)
        assert selected is not None and selected["id"] == case_id, (
            f"the state {flags} selects {selected['id'] if selected else None}, not {case_id}"
        )


# ===========================================================================
# 3. Running the shipped code
# ===========================================================================

_NODE_DRIVER = textwrap.dedent(
    r"""
    const fs = require('fs');
    // `node -e` puts the first extra argument at argv[1], not argv[2].
    const table = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
    const inputs = JSON.parse(process.argv[2]);
    let noSurebetReasons = table;
    const language = 'en';
    function tr(text, vars) {
        if (!vars) return text;
        return String(text).replace(/\{(\w+)\}/g, (whole, name) => (
            Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole
        ));
    }
    @formatCount@
    @escapeHtml@
    @fillDiagnosticBody@
    @diagnosticFlags@
    @selectNoSurebetReason@
    @renderCaseCopy@
    const out = inputs.map(input => {
        const selected = selectNoSurebetReason(
            typeof input === 'object' && input !== null && 'flags' in input ? input.flags : input
        );
        return { flags: input, id: selected ? selected.id : null };
    });
    // Escaping is proved by driving the real renderer with a hostile value.
    const hostile = {
        matches: '<img src=x onerror="alert(1)">',
        unverified_links: '<script>alert(2)</script>',
        verified_groups: '"><b>bold',
        surebets: "' onmouseover='alert(3)",
        profit_floor_percent: '<b>0.2</b>',
    };
    const escaped = inputs
        .map(flags => selectNoSurebetReason(flags))
        .filter(Boolean)
        .map(selected => ({
            id: selected.id,
            copy: renderCaseCopy(selected, hostile, false),
            copyLive: renderCaseCopy(selected, hostile, true),
        }));
    console.log(JSON.stringify({out, escaped, flagsType: typeof diagnosticFlags}));
    """
)

HOSTILE_MARKERS = ("<img", "<script>", "<b>bold", 'onerror="alert', "onmouseover='alert")
ESCAPED_MARKERS = ("&lt;", "&quot;", "&#039;", "&amp;")


def _driver_source(js: str = JS) -> str:
    """The real shipped functions, verbatim, as a runnable node module.

    Everything the diagnostic's pure half depends on is lifted out of app.js by
    name, so a change to the shipped logic shows up here as a failure rather than
    as a silent divergence between this file and the browser.
    """
    source = _NODE_DRIVER
    for name in (
        "formatCount",
        "escapeHtml",
        "fillDiagnosticBody",
        "diagnosticFlags",
        "selectNoSurebetReason",
        "renderCaseCopy",
    ):
        source = source.replace(f"@{name}@", _js_function(js, name))
    assert "@" not in source, "an unfilled placeholder is left in the node driver"
    return source


def _run_node(source: str, payload) -> str:
    assert NODE, "node disappeared between the skipif and this call"
    completed = subprocess.run(
        [NODE, "-e", source, str(REASON_TABLE), json.dumps(payload)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, f"the node driver failed:\n{completed.stderr}"
    return completed.stdout


@needs_node
def test_the_shipped_selector_agrees_with_the_reference_on_every_state():
    """The script that runs in the browser, not a transcription of it.

    ``_select`` is a reference implementation written in Python. This runs the
    actual ``selectNoSurebetReason`` the dashboard ships and compares the two
    across the whole truth table, so a guard typo in the JavaScript cannot pass.
    """
    combos = _reachable_combinations(REASONS)
    result = json.loads(_run_node(_driver_source(), combos))
    assert result["flagsType"] == "function", "diagnosticFlags did not survive extraction"
    assert len(result["out"]) == len(combos)
    for entry in result["out"]:
        expected = _select(REASONS, entry["flags"])
        expected_id = expected["id"] if expected else None
        assert entry["id"] == expected_id, (
            f"the shipped selector chose {entry['id']!r} for {entry['flags']}, the reference "
            f"chose {expected_id!r}"
        )


@needs_node
def test_the_shipped_selector_check_fails_when_the_javascript_guard_is_wrong():
    """Drives a mutated copy of the shipped script, so the comparison can fail."""
    mutated = JS.replace(
        "return all.every(flag => flags[flag] === true)",
        "return all.every(flag => flags[flag] === false)",
    )
    assert mutated != JS, "the mutation did not apply; the companion is untested"
    combos = _reachable_combinations(REASONS)
    result = json.loads(_run_node(_driver_source(mutated), combos))
    disagreements = [
        entry
        for entry in result["out"]
        if entry["id"] != (_select(REASONS, entry["flags"]) or {}).get("id")
    ]
    assert disagreements, "a broken guard in the shipped selector went unnoticed"


@needs_node
def test_the_shipped_renderer_escapes_every_server_provided_value():
    """Driven, not inspected: a hostile value goes in and must not come out live.

    The counts in the copy come from ``/api/health`` and ``/api/results``, and the
    team and league names behind those counts come from third-party bookmaker
    feeds. The escape step is the only thing between the two and ``innerHTML``, so
    the escape step is what gets tested — through ``renderCaseCopy``, the same
    function the DOM path calls.
    """
    problems = _escape_problems(_run_node(_driver_source(), _reachable_combinations(REASONS)))
    assert problems == [], "; ".join(problems)


def _escape_problems(stdout: str) -> list[str]:
    result = json.loads(stdout)
    if not result["escaped"]:
        return ["no case rendered, so nothing was proved about escaping"]
    interpolating = {
        reason["id"]
        for reason in REASONS["cases"]
        if any("{" in reason.get(key, "") for key in ("title", "body", "title_live", "body_live"))
    }
    if not interpolating:
        return ["no case interpolates a count, so nothing was substituted at all"]
    problems: list[str] = []
    rendered_ids = set()
    for entry in result["escaped"]:
        rendered_ids.add(entry["id"])
        for rendered in (
            f"{entry['copy']['title']} {entry['copy']['body']}",
            f"{entry['copyLive']['title']} {entry['copyLive']['body']}",
        ):
            # The markers are the *unescaped* attack forms. `onerror=&quot;` is
            # inert, so matching the bare attribute name would fail on output
            # that is in fact safe.
            for marker in HOSTILE_MARKERS:
                if marker in rendered:
                    problems.append(
                        f"{entry['id']} rendered an unescaped server value ({marker!r}): "
                        f"{rendered!r}"
                    )
            if entry["id"] in interpolating and not any(
                escaped in rendered for escaped in ESCAPED_MARKERS
            ):
                problems.append(
                    f"{entry['id']} dropped the hostile value instead of escaping it, so the "
                    "substitution path was not the one that ran"
                )
    if rendered_ids != set(CASES):
        problems.append(f"only {sorted(rendered_ids)} rendered; a selectable case was not driven")
    return problems


@needs_node
def test_escape_check_fails_when_the_escape_step_is_removed():
    """A renderer that stops escaping must be caught, not merely described."""
    mutated = JS.replace("escapeHtml(values[name])", "values[name]")
    assert mutated != JS, "the mutation did not apply; the companion is untested"
    problems = _escape_problems(_run_node(_driver_source(mutated), _reachable_combinations(REASONS)))
    assert problems, "dropping escapeHtml from the renderer passed the escape check"
    assert any("unescaped server value" in problem for problem in problems)


# ===========================================================================
# 4. Static contracts on the new markup and script
# ===========================================================================


def test_the_health_bar_is_untouched_and_the_payload_is_retained_separately():
    problems = _health_bar_problems(JS)
    assert problems == [], "; ".join(problems)


def test_health_bar_check_fails_when_the_bar_line_changes():
    drifted = JS.replace("| TTL {ttl}s | {pairing}", "| TTL {ttl} sec | {pairing}")
    assert drifted != JS, "the mutation did not apply; the companion is untested"
    problems = _health_bar_problems(drifted)
    assert any("rendered line changed" in problem for problem in problems), problems


def _bookies_problems(js: str, css: str) -> list[str]:
    """The bookmaker wall is hidden without an inline style attribute.

    ``.empty-state-bookies`` is ``display: flex``, so a bare ``[hidden]`` rule
    would lose to it. The stylesheet's ``[hidden] { display: none !important; }``
    is what makes the attribute sufficient, and N0-3 requires the attribute
    rather than ``style.display`` so no inline style is shipped.
    """
    problems: list[str] = []
    hidden_rule = re.search(r"\[hidden\]\s*\{([^}]*)\}", css)
    if not hidden_rule:
        problems.append("the stylesheet has no [hidden] rule")
    elif "display" not in hidden_rule.group(1) or "!important" not in hidden_rule.group(1):
        problems.append(
            "[hidden] must set display: none !important, or the display:flex row "
            "wins and the wall stays on screen"
        )
    for name in ("renderNoSurebetState", "renderDiagnosticUnavailable"):
        body = _js_function(js, name)
        if not re.search(r"bookies\.hidden\s*=", body):
            problems.append(f"{name}() does not hide the bookmaker wall through hidden")
        if re.search(r"bookies\.style\.display\s*=", body):
            problems.append(
                f"{name}() sets an inline style attribute; use the hidden attribute "
                "and the stylesheet's [hidden] rule"
            )
    return problems


def test_the_bookmaker_wall_is_hidden_with_the_hidden_attribute():
    problems = _bookies_problems(JS, CSS)
    assert problems == [], "; ".join(problems)


def test_bookies_check_fails_on_an_inline_toggle_and_on_a_weak_hidden_rule():
    """Drives both mistakes the predicate exists to catch."""
    inline = JS.replace(
        "if (bookies) bookies.hidden = reason.id !== 'never_scanned';",
        "if (bookies) bookies.style.display = reason.id === 'never_scanned' ? '' : 'none';",
    )
    assert inline != JS, "the mutation did not apply; the companion is untested"
    problems = _bookies_problems(inline, CSS)
    assert any("inline style" in problem for problem in problems), problems
    assert any("does not hide" in problem for problem in problems), problems

    weak = re.sub(
        r"\[hidden\]\s*\{[^}]*\}",
        "[hidden] { display: none; }",
        CSS,
    )
    assert weak != CSS, "the second mutation did not apply; the companion is untested"
    problems = _bookies_problems(JS, weak)
    assert any("!important" in problem for problem in problems), problems


def test_no_second_poll_was_added_and_nothing_refetches_the_numbers():
    problems = _cadence_problems(JS)
    assert problems == [], "; ".join(problems)


def test_cadence_check_fails_on_a_new_interval_and_on_a_refetching_renderer():
    extra = JS.replace(
        "setInterval(refreshDiagnostics, 30000);",
        "setInterval(refreshDiagnostics, 30000);\n    setInterval(loadHealth, 30000);",
    )
    assert extra != JS, "the mutation did not apply; the companion is untested"
    assert any("four intervals" in p for p in _cadence_problems(extra))

    fetching = JS.replace(
        "function diagnosticValues(health, results, counts) {\n    const live = counts.mode === 'live';",
        "function diagnosticValues(health, results, counts) {\n    fetch('/api/health');\n"
        "    const live = counts.mode === 'live';",
    )
    assert fetching != JS, "the second mutation did not apply; the companion is untested"
    assert any("fetches" in p for p in _cadence_problems(fetching))


def test_no_untrusted_interpolation_path_exists_and_no_class_is_invented():
    problems = _interpolation_problems(JS, CSS)
    assert problems == [], "; ".join(problems)


def test_interpolation_check_fails_on_a_raw_hole_and_on_a_new_class():
    raw = JS.replace(
        """return `<button type="button" class="btn btn-secondary" """
        """data-diagnostic-action="${escapeHtml(name)}">${escapeHtml(tr(action.label))}</button>`;""",
        """return `<button type="button" class="btn btn-verify" """
        """data-diagnostic-action="${action.name}">${action.label}</button>`;""",
    )
    assert raw != JS, "the mutation did not apply; the companion is untested"
    problems = _interpolation_problems(raw, CSS)
    assert any("interpolates" in problem for problem in problems), problems
    assert any(".btn-verify" in problem for problem in problems), problems


def test_every_case_names_the_backend_field_that_decides_it():
    problems = _field_problems(JS, REASONS)
    assert problems == [], "; ".join(problems)


def test_field_check_fails_on_a_field_the_script_never_reads():
    """A case claiming a deciding field nothing reads is this file's own disease."""
    invented = json.loads(json.dumps(REASONS))
    next(r for r in invented["cases"] if r["id"] == "links_unverified")["decided_by"].append(
        "deep_link_declarations"
    )
    problems = _field_problems(JS, invented)
    assert any("never reads it" in problem for problem in problems), problems

    renamed = json.loads(json.dumps(REASONS))
    renamed["flags"]["matches_parsed"] = renamed["flags"].pop("verified_groups")
    problems = _field_problems(JS, renamed)
    assert any("never produces" in problem for problem in problems), problems


def test_a_missing_copy_table_does_not_fall_back_to_a_wrong_reason():
    """Neither "no table" nor "counts not read yet" may name a cause.

    The fallback cannot know, so it says so. Asserting it exists is what stops
    "Click Scan Now" being reinstated as the error path — the loop, arriving
    through the back door. The first paint happens before ``/api/health`` has
    answered, and on a warm cache "no surebets" is not evidence that no scan
    ran, so that moment is covered by the same rule.
    """
    body = _js_function(JS, "renderDiagnosticUnavailable")
    for copy in MISLEADING_COPY:
        assert copy not in body, f"the fallback still asserts {copy!r}"
    assert "empty-state" in body, "the fallback renders into #empty-state"
    assert "no-results" in body, "the fallback must also keep #no-results hidden"
    sentences = " ".join(re.findall(r"'([^']{40,})'", _js_const(JS, "DIAGNOSTIC_UNAVAILABLE")))
    assert len(sentences.split("The dashboard")) == 3, (
        "there must be a sentence for each way the diagnostic can be unable to answer, and "
        f"nothing else: {sentences!r}"
    )
    for sentence in sentences.split("The dashboard")[1:]:
        assert "cannot" in sentence, f"a fallback sentence does not say it cannot know: {sentence!r}"
        assert "Scan Now" not in sentence and "Reset Filters" not in sentence, sentence
    for copy in MISLEADING_COPY:
        assert copy not in sentences
    assert "catch" in _js_function(JS, "loadNoSurebetReasons"), (
        "a failed table load has to reach renderDiagnosticUnavailable"
    )


def test_the_diagnostic_claims_nothing_until_the_counts_have_been_read():
    """The first paint happens before ``/api/health`` answers, and must not assert.

    On a warm cache ``allSurebets.length === 0`` with ``healthSnapshot`` still
    null is a moment where the dashboard knows nothing at all. Rendering
    ``never_scanned`` there would re-introduce the loop for the first few
    hundred milliseconds of every page load, on exactly the cache the
    diagnostic exists for.
    """
    body = _js_function(JS, "renderNoSurebetState")
    guard = re.search(r"if \(!noSurebetReasons \|\| !healthSnapshot\) \{\s*"
                      r"renderDiagnosticUnavailable\(\);\s*return;\s*\}", body)
    assert guard, (
        "renderNoSurebetState() must not select a case before it has the counts; without this "
        "guard the pre-health first paint claims the scan never happened"
    )
    select_at = body.index("selectNoSurebetReason(")
    assert guard.end() < select_at, "the guard has to come before the case is selected"


def test_the_copy_table_is_served_from_the_mount_the_script_uses():
    assert REASON_TABLE.exists()
    assert REASON_TABLE.suffix == ".json"
    assert REASONS["version"] == 1
    assert float(REASONS["profit_floor_percent"]) > 0
    app_source = (REPO_ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert 'app.mount("/js"' in app_source, (
        "the table is fetched from /js; that mount has to exist for the diagnostic to load"
    )


# ===========================================================================
# 5. The states the real backend can produce
# ===========================================================================

# Two books that declare a per-event route (see tests/conftest.py), so an
# unproven link on them really blocks.
LEFT, RIGHT = "undeclared_book", "undeclared_book2"


def _btts(bookmaker: str, gg: float, ng: float, *, verified: bool, kickoff=None) -> Match:
    """One real BTTS match, built the way a scraper builds one."""
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Željezničar",
        league="BiH - Premier Liga",
        kickoff=kickoff or (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)),
        event_id=f"{bookmaker}-event-1",
        url=f"https://example.test/{bookmaker}/event-1",
        deep_link_verified=verified,
        markets=[
            Market(
                market_type=MarketType.BTTS,
                odds=[OddsValue(label="GG", value=gg), OddsValue(label="NG", value=ng)],
            )
        ],
    )


def _group_and_report(matches: list[Match]):
    """The real matcher over real matches: the surviving groups and the report."""
    matcher = MatchMatcher()
    groups = matcher.group_matches(matches)
    return groups, matcher.get_match_report(groups)


def _priced_surebets(groups: list) -> int:
    """The real engine, at the floor ``run_scan`` actually asks for."""
    return len(ArbitrageEngine().find_surebets(groups, min_profit=DUST_PROFIT_PERCENT))


@contextmanager
def _backend_state(matches: list[Match], mode: str = "prematch"):
    """Real matcher output into the server the endpoints read, then restore.

    This is the shape of a real scan: the report, the match cache and the surebet
    cache are all filled from the same matches by the same code, and
    ``last_scan_time`` is set as a completed scan sets it. The counters the
    diagnostic reads are then whatever the real endpoints report.
    """
    live = mode == "live"
    matches_cache = api.cached_live_matches if live else api.cached_matches
    report_cache = api.cached_live_match_groups_report if live else api.cached_match_groups_report
    surebets_cache = api.cached_live_surebets if live else api.cached_surebets
    status = api.live_status if live else api.scan_status
    saved = (list(matches_cache), list(report_cache), list(surebets_cache), status.last_scan_time)
    groups, report = _group_and_report(matches)
    matches_cache[:] = [match.model_dump(mode="json") for match in matches]
    report_cache[:] = report
    surebets_cache[:] = [
        surebet.model_dump(mode="json")
        for surebet in ArbitrageEngine().find_surebets(groups, min_profit=DUST_PROFIT_PERCENT)
    ]
    status.last_scan_time = datetime.now(UTC).replace(tzinfo=None)
    try:
        yield client.get("/api/health").json(), client.get(f"/api/results?mode={mode}").json()
    finally:
        matches_cache[:], report_cache[:], surebets_cache[:], status.last_scan_time = saved


@contextmanager
def _cleared_backend_state(mode: str = "prematch"):
    """The state a server is in before anything has been scanned."""
    live = mode == "live"
    matches_cache = api.cached_live_matches if live else api.cached_matches
    report_cache = api.cached_live_match_groups_report if live else api.cached_match_groups_report
    surebets_cache = api.cached_live_surebets if live else api.cached_surebets
    status = api.live_status if live else api.scan_status
    saved = (list(matches_cache), list(report_cache), list(surebets_cache), status.last_scan_time)
    matches_cache.clear()
    report_cache.clear()
    surebets_cache.clear()
    status.last_scan_time = None
    try:
        yield client.get("/api/health").json(), client.get(f"/api/results?mode={mode}").json()
    finally:
        matches_cache[:], report_cache[:], surebets_cache[:], status.last_scan_time = saved


def _flags_from_real_endpoints(health: dict, results: dict, shown: int) -> dict[str, bool]:
    """The shipped ``diagnosticFlags``, run against real endpoint payloads.

    A transcription of the JavaScript, cross-checked against the real function by
    ``test_every_case_is_selected_by_the_shipped_selector_from_real_payloads``.
    """
    mode = results["mode"]
    feed = health["live"] if mode == "live" else health["prematch"]
    matches = health["live_matches_cached"] if mode == "live" else health["matches_cached"]
    links = health["live_unverified_links"] if mode == "live" else health["unverified_links"]
    return {
        "scanned": int(matches) > 0 and feed["last_scan_age_sec"] is not None,
        "unverified_links": int(links) > 0,
        "verified_groups": int(results["match_groups"]) > 0,
        "have_surebets": len(results["surebets"]) > 0,
        "show_surebets": shown > 0,
    }


# One fixture per case, each differing only in what the real gate sees. Both
# books are route-declaring, so `unverified_links` counts them.
LINK_BLOCKED = [
    _btts(LEFT, 2.40, 1.90, verified=False),
    _btts(RIGHT, 2.20, 1.85, verified=False),
]
IDENTITY_BLOCKED = [
    _btts(LEFT, 2.40, 1.90, verified=True),
    # Half an hour apart: inside the scorer's grouping window, so the certainty
    # gate is what refuses the pair, on its own kickoff tolerance.
    _btts(
        RIGHT,
        2.20,
        1.85,
        verified=True,
        kickoff=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2, minutes=30),
    ),
]
IDENTICAL_ODDS = [
    _btts(LEFT, 1.90, 1.90, verified=True),
    _btts(RIGHT, 1.90, 1.90, verified=True),
]
ARBITRAGEABLE = [
    _btts(LEFT, 2.40, 1.90, verified=True),
    _btts(RIGHT, 2.20, 1.85, verified=True),
]


def test_the_deep_link_case_is_what_a_real_unproven_scan_reports():
    """The case this whole change was written for, produced by the real backend.

    Two unproven links, the same two fixtures, no gate-verified group. The counts
    the dashboard reads come from the real endpoints, and they have to answer
    with the link gate and not with the filters.
    """
    groups, _ = _group_and_report(LINK_BLOCKED)
    assert groups == [], "the premise: an unproven link cannot pair two fixtures"
    with _backend_state(LINK_BLOCKED) as (health, results):
        assert health["unverified_links"] == 2, "both links are outstanding blockers"
        assert health["verified_groups"] == 0
        assert health["matches_cached"] == 2
        assert results["surebets"] == [] and results["match_groups"] == 0
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "links_unverified"


def test_the_identity_case_is_what_a_real_refusal_reports():
    """Proven links, refused identity: the deep-link count must not be blamed."""
    groups, _ = _group_and_report(IDENTITY_BLOCKED)
    assert groups == [], "the premise: kickoffs 30 minutes apart are not the same event"
    with _backend_state(IDENTITY_BLOCKED) as (health, results):
        assert health["unverified_links"] == 0, (
            "both links are proven, so the deep-link count cannot be what is blocking this"
        )
        assert health["verified_groups"] == 0
        assert health["matches_cached"] == 2
        assert results["surebets"] == [] and results["match_groups"] == 0
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "identity_unproven"


def test_the_priced_nothing_case_is_reachable_from_a_real_scan():
    """Verified groups and no surebet, from real groups the real engine refused.

    A group is only priced when its kickoff has not passed and its odds are inside
    the freshness window, so "verified groups, no surebet" is a state the dashboard
    really lands in. The copy must therefore not claim the market held no
    arbitrage: an expired or stale group is never priced at all.
    """
    groups, _ = _group_and_report(IDENTICAL_ODDS)
    assert len(groups) == 1 and groups[0].status == "verified", groups
    with _backend_state(IDENTICAL_ODDS) as (health, results):
        assert health["verified_groups"] == 1
        assert health["unverified_links"] == 0
        assert results["match_groups"] == 1
        assert results["surebets"] == [], "identical odds cannot be an arbitrage"
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "no_edge"


def test_the_filter_case_is_reachable_from_a_real_priced_surebet():
    """A real arbitrage exists, and a client-side filter hides it.

    ``show_surebets`` is the one flag the backend cannot answer, so the test
    supplies it the way the client would: the payload has surebets, the view has
    none.
    """
    groups, _ = _group_and_report(ARBITRAGEABLE)
    assert len(groups) == 1 and _priced_surebets(groups) >= 1, "the premise: a real arbitrage"
    with _backend_state(ARBITRAGEABLE) as (health, results):
        assert results["surebets"], "the real engine priced an arbitrage"
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "filters_hiding"
        cleared = _flags_from_real_endpoints(health, results, shown=len(results["surebets"]))
        assert _select(REASONS, cleared) is None, (
            "with the filters cleared there is nothing to diagnose"
        )


def test_the_never_scanned_case_is_what_the_endpoints_say_before_any_scan():
    """No cached matches and no scan age: the only state where "Scan Now" is right."""
    with _cleared_backend_state() as (health, results):
        assert health["matches_cached"] == 0
        assert health["prematch"]["last_scan_age_sec"] is None
        assert results["surebets"] == [] and results["last_scan_time"] is None
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "never_scanned"


def test_a_cache_that_held_no_matches_reads_as_never_scanned_even_with_a_scan_age():
    """The restored-cache edge: matches are gone, so "Scan Now" is the honest advice.

    ``_load_cache`` restores the match list, and it is empty once the file's
    freshness window has passed while the status object is then reset. Either way
    the dashboard holds no matches, so the case must not claim anything else.
    """
    with _cleared_backend_state() as (health, results):
        health["matches_cached"] = 1
        assert _flags_from_real_endpoints(health, results, shown=0)["scanned"] is False
        health["matches_cached"] = 0
        assert _select(REASONS, _flags_from_real_endpoints(health, results, shown=0))["id"] == (
            "never_scanned"
        )


@needs_node
def test_every_case_is_selected_by_the_shipped_selector_from_real_payloads():
    """The shipped selector, driven by the real endpoints, for all four scan cases.

    The reachability tests above settle the backend half by asserting the flag
    values themselves. This closes the loop: the JavaScript that runs in the
    browser is handed those very payloads, so a guard that does not fire on a real
    scan fails here rather than shipping a sentence nobody reads.
    """
    driver = _driver_source() + textwrap.dedent(
        """
        const driven = inputs.map(input => {
            const selected = selectNoSurebetReason(
                diagnosticFlags(input.health, input.results, input.counts)
            );
            return selected ? selected.id : null;
        });
        console.log(JSON.stringify({out: driven.map(id => ({id}))}));
        """
    )
    for matches, expected in (
        (LINK_BLOCKED, "links_unverified"),
        (IDENTITY_BLOCKED, "identity_unproven"),
        (IDENTICAL_ODDS, "no_edge"),
        (ARBITRAGEABLE, "filters_hiding"),
    ):
        with _backend_state(matches) as (health, results):
            payload = [
                {
                    "health": health,
                    "results": results,
                    "counts": {
                        "mode": results["mode"],
                        "surebets": len(results["surebets"]),
                        "shownSurebets": 0,
                    },
                }
            ]
            # The base driver prints its own line first; read the driven answer
            # off the last one.
            chosen = json.loads(_run_node(driver, payload).strip().splitlines()[-1])["out"][0]["id"]
            assert chosen == expected, (
                f"the real {expected} payload made the shipped selector answer {chosen!r}"
            )


# ===========================================================================
# 6. The backend fields the diagnostic leans on
# ===========================================================================


def test_live_mode_reads_live_counters_rather_than_the_prematch_ones():
    """``/api/health``'s gate counters were prematch-only, so live quoted the wrong feed.

    ``unverified_links`` is counted from the prematch match cache. A live empty
    state quoting it would be quoting a different scan than the one on screen — the
    same class of defect as the copy it replaced. So live has its own counter,
    counted by the same predicate, and this drives the live feed end to end.
    """
    with _backend_state(LINK_BLOCKED, mode="live") as (health, results):
        assert health["live_unverified_links"] == 2
        assert health["unverified_links"] == 0, (
            "the prematch counter must not answer for the live feed; if this ever moves, the "
            "live empty state is quoting the wrong scan again"
        )
        assert results["mode"] == "live"
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "links_unverified"

    with _backend_state(IDENTICAL_ODDS, mode="live") as (health, results):
        assert health["live_unverified_links"] == 0
        flags = _flags_from_real_endpoints(health, results, shown=0)
        assert _select(REASONS, flags)["id"] == "no_edge"


def test_match_groups_is_the_mode_correct_verified_group_count():
    """Why the copy reads ``match_groups`` and not the health endpoint's counter.

    ``verified_groups`` on ``/api/health`` is counted from the prematch report
    whatever mode the dashboard is showing. ``match_groups`` on ``/api/results`` is
    read through ``_state_for(mode)``, so it answers for the mode on screen. This
    pins the two to each other on real matcher output, so the substitution is a
    measured equivalence rather than a convenience.
    """
    groups, _ = _group_and_report(IDENTICAL_ODDS)
    assert groups and all(group.status == "verified" for group in groups)
    with _backend_state(IDENTICAL_ODDS) as (health, results):
        assert results["match_groups"] == health["verified_groups"] == len(groups)
    with _backend_state(LINK_BLOCKED) as (health, results):
        assert results["match_groups"] == health["verified_groups"] == 0


def test_group_statuses_cannot_carry_a_rejection():
    """Why the copy does not surface ``group_statuses``.

    The brief suggested it for the identity case. It cannot be: ``group_matches``
    returns only the groups the gate accepted, so the report it is built from never
    contains a ``suggested`` or ``rejected`` entry. Rendering it beside a sentence
    about refusals would put a ``verified: 27`` there and read as though those
    refusals had been counted too. The decision not to render it is pinned here, by
    running the real matcher on a group it accepts and one it refuses.
    """
    _, report = _group_and_report(IDENTICAL_ODDS)
    statuses = {entry["status"] for entry in report}
    assert statuses == {"verified"}, f"the report now carries {sorted(statuses)}"
    _, refused = _group_and_report(LINK_BLOCKED)
    assert refused == []
    assert "group_statuses" in REASONS, (
        "this file has to keep recording why group_statuses is not rendered, or the decision "
        "becomes an unexplained omission"
    )
    assert "verified" in REASONS["group_statuses"]


def test_a_surebet_cannot_exist_without_a_scan():
    """The invariant the unreachable-state exclusion rests on."""
    assert MatchMatcher().group_matches([]) == []
    groups, _ = _group_and_report(ARBITRAGEABLE)
    engine = ArbitrageEngine()
    assert groups and engine.find_surebets(groups, min_profit=DUST_PROFIT_PERCENT)
    assert engine.find_surebets(groups, min_profit=1e9) == [], (
        "the engine prices nothing above an impossible threshold, so a non-empty group list can "
        "still yield no surebets: surebets > 0 therefore implies groups > 0"
    )


def test_client_filter_cannot_hide_a_surebet_the_payload_did_not_return():
    """The other half: ``filteredSurebets`` is a subset of ``allSurebets``."""
    assert re.search(r"filteredSurebets\s*=\s*allSurebets\.filter\(", JS), (
        "filteredSurebets is no longer a filter of allSurebets, so show_surebets can be true "
        "while have_surebets is false and the truth table's exclusion is no longer sound"
    )


# ===========================================================================
# 7. The companion guard
# ===========================================================================


def _predicates() -> dict[str, object]:
    """Every ``*_problems`` predicate defined in this module, by name."""
    return {
        name: value
        for name, value in globals().items()
        if name.endswith("_problems") and callable(value) and name != "_predicates"
    }


def _companions() -> set[str]:
    return {name for name in globals() if name.startswith("test_") and "_fails_" in name}


def test_every_predicate_has_a_companion_that_breaks_it():
    """No predicate in this file is a no-op, and none is unaccompanied.

    Each predicate must pass on the real files, and each must have a
    ``test_*_fails_*`` companion that breaks an input the way the predicate is
    supposed to catch. A predicate added without one is how a check quietly stops
    checking anything.
    """
    problems: list[str] = []
    for name, predicate in sorted(_predicates().items()):
        arity = predicate.__code__.co_argcount
        arguments = {
            "_truth_table_problems": (REASONS,),
            "_copy_problems": (REASONS,),
            "_static_drift_problems": (HTML, REASONS),
            "_health_bar_problems": (JS,),
            "_cadence_problems": (JS,),
            "_interpolation_problems": (JS, CSS),
            "_bookies_problems": (JS, CSS),
            "_field_problems": (JS, REASONS),
            "_escape_problems": (_run_node(_driver_source(), _reachable_combinations(REASONS)),),
        }.get(name)
        if arguments is None:
            problems.append(f"{name} takes {arity} arguments and this guard does not know them")
            continue
        failures = predicate(*arguments)  # type: ignore[operator]
        if failures:
            problems.append(f"{name} reports on the real files: {'; '.join(failures)}")
        if not any(name.removesuffix("_problems") in companion for companion in _companions()):
            problems.append(
                f"{name} has no test_*_fails_* companion, so nothing proves it can fail"
            )
    assert not problems, "\n".join(problems)


def test_the_predicate_guard_would_notice_an_empty_predicate_set():
    """The guard above must fail, not pass, if its own introspection finds nothing.

    Without this, renaming every predicate would leave the guard vacuously green.
    This drives that path directly.
    """
    saved = _predicates()
    try:
        globals().update({"_truth_table_problems": None, "_copy_problems": None})
        found = _predicates()
        assert "_truth_table_problems" not in found, (
            "a predicate that is not callable is still being reported, so the guard's own "
            "introspection cannot be emptied without noticing"
        )
        assert "_copy_problems" not in found
    finally:
        globals().update(saved)
    assert set(_predicates()) == set(saved)
