"""N2-5: the Bosnian catalog covers every string the UI can render.

The catalog is gettext-style: keys are the English source strings, `bs` holds
the Bosnian copy and `tr()` falls back to the key. These tests fail when a
`data-i18n` / `tr()` key has no Bosnian entry, when a placeholder is lost in
translation, or when a shipped HTML text node is English chrome outside the
catalog.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
CATALOG = (ROOT / "frontend/js/i18n.js").read_text(encoding="utf-8")
REASONS = json.loads(
    (ROOT / "frontend/js/no-surebet-reasons.json").read_text(encoding="utf-8")
)


def _catalog() -> dict[str, str]:
    body = CATALOG.split("window.I18N =", 1)[1].strip().rstrip(";")
    return json.loads(body)["bs"]


def _data_i18n_keys() -> set[str]:
    keys: set[str] = set()
    for match in re.finditer(r'data-i18n(?:-[a-z-]+)?="([^"]*)"', HTML):
        value = (
            match.group(1)
            .replace("&quot;", '"')
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
        )
        if value != "true":
            keys.add(value)
    return keys


def _tr_keys() -> set[str]:
    keys: set[str] = set()
    for match in re.finditer(r"\btr\(\s*(['\"])(.*?)\1", JS, re.S):
        keys.add(match.group(2).replace("\\'", "'").replace('\\"', '"'))
    for match in re.finditer(
        r"\btr\([^)]*\?\s*(['\"])(.*?)\1\s*:\s*(['\"])(.*?)\3", JS
    ):
        keys.add(match.group(2).replace("\\'", "'"))
        keys.add(match.group(4).replace("\\'", "'"))
    return keys


def _placeholders(value: str) -> set[str]:
    return set(re.findall(r"\{([a-z_]+)\}", value))


def test_every_used_key_has_a_bosnian_translation():
    catalog = _catalog()
    used = _data_i18n_keys() | _tr_keys()
    missing = sorted(key for key in used if key not in catalog)
    assert missing == [], f"missing Bosnian copy for: {missing}"


def test_no_bosnian_translation_is_empty_or_a_placeholder():
    catalog = _catalog()
    empty = sorted(key for key, value in catalog.items() if not str(value).strip())
    assert empty == []
    assert len(catalog) > 250, "the catalog should cover the shipped UI chrome"


def test_placeholders_survive_translation():
    catalog = _catalog()
    broken = []
    for key, value in catalog.items():
        if _placeholders(key) != _placeholders(str(value)):
            broken.append((key, sorted(_placeholders(key)), sorted(_placeholders(str(value)))))
    assert broken == [], f"placeholder mismatch: {broken}"


def test_the_reason_copy_table_has_bosnian_fields_for_every_case():
    missing = []
    for case in REASONS["cases"]:
        for field in ("title", "body", "title_live", "body_live"):
            if case.get(field):
                if not case.get(f"{field}_bs"):
                    missing.append(f"{case['id']}.{field}_bs")
    assert missing == [], f"reason cases without Bosnian copy: {missing}"


class _TextAudit(HTMLParser):
    """Collect visible text nodes with no data-i18n ancestor."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, bool, bool]] = []
        self.untranslated: list[str] = []
        self.missing_attrs: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        inherited = (
            any(flag for _tag, flag, _embedded in self.stack)
            or values.get("data-i18n-html") == "true"
        )
        embedded = tag in ("script", "style")
        self.stack.append((tag, bool(values.get("data-i18n")) or inherited, embedded))
        for name in ("aria-label", "title", "placeholder"):
            value = values.get(name)
            if value and f"data-i18n-{name}" not in values:
                self.missing_attrs.append((tag, name, value))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if any(flag for _tag, flag, _embedded in self.stack):
            return
        if any(embedded for _tag, _flag, embedded in self.stack):
            return
        self.untranslated.append(text)


# Data, brand and keycap glyphs are not UI chrome. Everything else has to be in
# the catalog.
TEXT_ALLOWLIST = {
    "Surebet",
    "Surebet BiH",
    "BiH",
    "Bosanski",
    "English",
    "0",
    "%",
    ".",
    "—",
    "✕",
}


def test_no_shipped_html_text_stays_outside_the_catalog():
    audit = _TextAudit()
    audit.feed(HTML)
    leaked = [text for text in audit.untranslated if text not in TEXT_ALLOWLIST]
    assert leaked == [], f"untranslated HTML text: {sorted(set(leaked))}"


def test_no_shipped_accessible_attribute_stays_outside_the_catalog():
    audit = _TextAudit()
    audit.feed(HTML)
    leaked = [
        (tag, name, value)
        for tag, name, value in audit.missing_attrs
        if not (name == "title" and value.startswith("Theme:"))
    ]
    assert leaked == [], f"untranslated attributes: {sorted(set(leaked))}"


def test_language_switch_repaints_generated_views_and_attributes():
    assert "function applyLanguage" in JS
    assert "translateElement" in JS
    assert "[data-i18n-aria-label]" in JS
    assert "data-i18n-html" in HTML
    assert "refreshLocalizedViews" in JS
    assert "loadCandidates" in JS[JS.index("function refreshLocalizedViews"):]
    assert "document.documentElement.lang = language" in JS


def test_the_catalog_is_loaded_before_the_app_script():
    i18n_tag = HTML.index('src="/js/i18n.js"')
    app_tag = HTML.index('src="/js/app.js')
    assert i18n_tag < app_tag
    assert "'/js/i18n.js'" in (ROOT / "frontend/sw.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["Scan now", "Surebets", "Settings", "Paper"])
def test_core_labels_have_a_real_bosnian_word(key):
    catalog = _catalog()
    assert catalog[key] != key, f"{key} was copied through untranslated"
