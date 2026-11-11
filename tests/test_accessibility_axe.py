"""N2-5: machine-checked accessibility for the main tabs and the slip.

The offline checks parse the shipped HTML and app source, so they run in CI
without a browser. The browser audit (``scripts/a11y_audit.py``) adds the live
DOM and optional axe-core; set ``BH_ARB_TEST_BROWSER=1`` to run it in the suite
where Chromium is installed.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts/a11y_audit.py").read_text(encoding="utf-8")

INTERACTIVE = {"button", "a", "input", "select", "textarea"}


class _Audit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.elements: list[dict] = []
        self.stack: list[str] = []
        self.label_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if "id" in values:
            self.ids.append(values["id"])
        tabindex = values.get("tabindex", "")
        if tabindex.lstrip("-").isdigit() and int(tabindex) > 0:
            self.elements.append({"tag": tag, "issue": "positive-tabindex"})
        if tag == "label":
            self.label_depth += 1
        if tag in INTERACTIVE:
            self.elements.append(
                {
                    "tag": tag,
                    "type": values.get("type", ""),
                    "aria-label": values.get("aria-label", ""),
                    "aria-labelledby": values.get("aria-labelledby", ""),
                    "title": values.get("title", ""),
                    "text": "",
                    "in_label": self.label_depth > 0,
                    "role": values.get("role", ""),
                    "aria-selected": values.get("aria-selected", ""),
                    "aria-controls": values.get("aria-controls", ""),
                }
            )
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"):
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self.label_depth:
            self.label_depth -= 1
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text and self.elements:
            self.elements[-1]["text"] = (self.elements[-1].get("text", "") + " " + text).strip()


def _audit() -> _Audit:
    audit = _Audit()
    audit.feed(HTML)
    return audit


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


def test_main_landmarks_and_live_regions_exist():
    assert "<header" in HTML
    assert '<main class="main" id="main" tabindex="-1">' in HTML
    assert '<nav class="results-tabs" role="tablist"' in HTML
    assert 'aria-label="Dashboard views"' in HTML
    assert '<aside class="slip-pane" id="slip" aria-label="Bet slip"' in HTML
    assert 'id="slip-status"' in HTML
    assert 'role="status" aria-live="polite"' in HTML
    assert 'class="skip-link"' in HTML
    assert HTML.count('aria-live="polite"') >= 2
    assert 'role="alert"' in HTML


def test_every_tab_exposes_its_state_and_panel():
    tabs = 0
    for tab in ("surebets", "review", "paper", "history", "evidence", "other"):
        assert f'data-tab="{tab}"' in HTML
        tabs += 1
    assert tabs == 6
    # Six view tabs plus the two feed-mode tabs in the top bar.
    assert HTML.count('role="tab"') == 8
    assert HTML.count("aria-selected=") >= 8
    assert HTML.count("aria-controls=") >= 8
    assert HTML.count('role="tabpanel"') == 6


def test_the_feed_mode_tabs_control_their_panel_with_a_roving_tabindex():
    """The top-bar tabs had aria-selected but no aria-controls or roving tabindex."""
    for mode, tabindex in (("prematch", "0"), ("live", "-1")):
        tag = re.search(rf'<button[^>]*id="mode-{mode}"[^>]*>', HTML, re.S)
        assert tag is not None, mode
        assert 'aria-controls="surebets-panel"' in tag.group(0), mode
        assert f'tabindex="{tabindex}"' in tag.group(0), mode
        assert 'data-action="switch-mode"' in tag.group(0), mode
    assert "handleModeTabKeydown" in JS
    assert "button.tabIndex = currentMode === mode ? 0 : -1" in JS


def test_every_control_has_a_programmatic_name():
    missing = []
    for element in _audit().elements:
        if element.get("issue"):
            continue
        if element["tag"] not in INTERACTIVE:
            continue
        if element["tag"] == "input" and element["type"] == "hidden":
            continue
        if element["tag"] == "a":
            if element["text"] or element["aria-label"] or element["title"]:
                continue
            missing.append(element)
            continue
        if (
            element["aria-label"]
            or element["aria-labelledby"]
            or element.get("in_label")
            or (element["tag"] == "button" and (element["text"] or element["title"]))
        ):
            continue
        missing.append(element)
    assert missing == [], f"controls without a name: {missing}"


def test_no_duplicate_ids_and_no_positive_tabindex():
    audit = _audit()
    duplicates = sorted({value for value in audit.ids if audit.ids.count(value) > 1})
    assert duplicates == []
    assert [row for row in audit.elements if row.get("issue") == "positive-tabindex"] == []


def test_keyboard_path_handlers_exist():
    # Tabs: roving tabindex, arrows, Home/End.
    assert "function handleTabKeydown" in JS
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in JS
    # List: J/K, Escape closes the slip or the drawer.
    assert "event.key !== 'j' && event.key !== 'k'" in JS
    assert "document.body.classList.contains('slip-open')" in JS
    assert "function closeSlip" in JS
    # Slip: focusable inputs and explicit copy/mark buttons.
    assert "data-placed-odds" in JS
    assert "data-placed-stake" in JS
    assert "data-action=\"mark-placed\"" in JS
    assert "data-action=\"copy-surebet\"" in JS


def test_settings_drawer_discloses_itself_and_manages_focus():
    gear = re.search(r'<button[^>]*id="settings-btn"[^>]*>', HTML)
    assert gear, "the Settings gear is missing"
    tag = gear.group(0)
    assert 'aria-expanded="false"' in tag
    assert 'aria-controls="settings-drawer"' in tag

    body = _js_function(JS, "toggleSettings")
    assert "aria-expanded" in body
    assert "querySelector('select, input, button, a, [tabindex]')" in body
    assert "button.focus()" in body


def test_slip_options_expose_selection_and_the_placeholder_has_a_back_control():
    assert "setAttribute('aria-selected', 'false')" in _js_function(JS, "buildSurebetRow")
    assert 'data-action="close-slip"' in _js_function(JS, "renderSlip")


def test_accessibility_runner_covers_tabs_and_slip_and_has_an_allowlist():
    assert "axe" in SCRIPT.lower()
    assert "ALLOWLIST" in SCRIPT
    for tab in ("surebets", "review", "paper", "history", "evidence", "other"):
        assert tab in SCRIPT
    assert "slip" in SCRIPT
    assert "axe.run" in SCRIPT
    assert "resultTypes" in SCRIPT


@pytest.mark.skipif(
    os.getenv("BH_ARB_TEST_BROWSER") != "1",
    reason="needs Chromium; set BH_ARB_TEST_BROWSER=1 to run the live audit",
)
def test_live_browser_audit_passes_for_every_tab_and_the_slip():
    from scripts.a11y_audit import FRONTEND, _axe_path, _serve, audit

    server, url = _serve(FRONTEND)
    try:
        report = audit(url, _axe_path(""))
    finally:
        server.shutdown()

    assert report["checked_tabs"] == [
        "surebets",
        "review",
        "paper",
        "history",
        "evidence",
        "other",
    ]
    assert report["slip"] is True
    assert report["issues"] == []


@pytest.mark.skipif(
    os.getenv("BH_ARB_TEST_BROWSER") != "1",
    reason="needs Chromium; set BH_ARB_TEST_BROWSER=1 to run the keyboard path",
)
def test_keyboard_only_path_works_in_both_languages():
    """scan → filter → open slip → copy stake → close, no mouse events."""
    from playwright.sync_api import sync_playwright

    from scripts.a11y_audit import FRONTEND, SLIP_FIXTURE, _serve

    server, url = _serve(FRONTEND)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(250)
            page.evaluate(SLIP_FIXTURE)
            page.focus("#settings-btn")
            page.keyboard.press("Enter")
            for language in ("en", "bs"):
                page.select_option("#filter-language", language)
                page.wait_for_timeout(150)
                assert page.evaluate("document.documentElement.lang") == language
                expected = "Sigurni dobici" if language == "bs" else "Surebets"
                assert expected in page.inner_text("#surebets-tab")
            page.keyboard.press("Escape")
            page.wait_for_timeout(100)

            for language in ("en", "bs"):
                page.focus("#settings-btn")
                page.keyboard.press("Enter")
                page.select_option("#filter-language", language)
                page.keyboard.press("Escape")
                page.evaluate(SLIP_FIXTURE)
                page.wait_for_timeout(100)

                page.focus("#filter-search")
                page.keyboard.type("sarajevo")
                assert page.eval_on_selector("#filter-search", "el => el.value") == "sarajevo"
                page.evaluate("document.getElementById('filter-search').value = ''")
                page.evaluate(SLIP_FIXTURE)

                page.focus("#scan-btn")
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)

                page.focus(".sb-row")
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)
                assert page.evaluate("document.body.classList.contains('slip-open')")

                page.focus(".stake-copy")
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)
                copied = page.evaluate("navigator.clipboard.readText()")
                assert copied and copied.replace(".", "").isdigit()

                page.keyboard.press("Escape")
                assert not page.evaluate("document.body.classList.contains('slip-open')")
            context.close()
            browser.close()
    finally:
        server.shutdown()

