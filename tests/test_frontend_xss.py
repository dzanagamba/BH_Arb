"""Shipped dashboard markup never turns a scraped name into executable markup."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "frontend" / "index.html"
JS_PATH = REPO_ROOT / "frontend" / "js" / "app.js"
HTML = HTML_PATH.read_text(encoding="utf-8")
JS = JS_PATH.read_text(encoding="utf-8")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on this machine")

HOSTILE = 'O\'Brien "X" <img src=x onerror=alert(1)>'


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


def _run_js(expression: str) -> dict:
    """Execute the shipped helpers in Node and return their JSON output."""
    assert NODE, "node disappeared between the skipif and this call"
    driver = "\n".join(
        [
            _js_function(JS, "escapeHtml"),
            _js_function(JS, "capitalizeWords"),
            _js_function(JS, "formatTeamName"),
            _js_function(JS, "copyAttributes"),
            expression,
        ]
    )
    completed = subprocess.run(
        [NODE, "-e", driver],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


class _ButtonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "button":
            self.attributes = attrs


def test_shipped_html_and_js_have_no_inline_event_handlers():
    assert re.findall(r"\bon[a-z]+\s*=", HTML) == []
    assert re.findall(r"\bon[a-z]+\s*=", JS) == []


def test_index_scripts_are_nonce_stamped():
    assert '<script nonce="__CSP_NONCE__">' in HTML
    assert 'src="/js/app.js?v=8" nonce="__CSP_NONCE__"' in HTML


def test_copy_handler_reads_the_dataset_not_a_javascript_string():
    assert "function copyAttributes(" in JS
    assert 'data-copy="${escapeHtml(value)}"' in JS
    assert "copyText(element.dataset.copy, element.dataset.copyMessage)" in JS
    # JSON belongs in a fetch body, never in an HTML attribute. The four uses
    # are the verify request, the link-sweep report, the bet log and the paper
    # position settle.
    assert JS.count("JSON.stringify") == 4
    assert "${JSON.stringify(" not in JS


@needs_node
def test_hostile_team_name_renders_as_text_and_keeps_a_usable_copy_button():
    result = _run_js(
        "const hostile = " + json.dumps(HOSTILE) + ";\n"
        "process.stdout.write(JSON.stringify({"
        "rendered: escapeHtml(formatTeamName(hostile)),"
        "attributes: copyAttributes(hostile, 'Copied')"
        "}));"
    )

    rendered = result["rendered"]
    assert "<img" not in rendered.lower()
    assert "&lt;img" in rendered.lower()
    assert "&quot;" in rendered
    assert "&#039;" in rendered

    markup = f"<button {result['attributes']}></button>"
    parser = _ButtonParser()
    parser.feed(markup)
    attrs = dict(parser.attributes)

    # The browser parses only a button: the hostile string stayed inside one
    # attribute value, and the copy handler can read it back exactly.
    assert parser.tags == ["button"]
    assert attrs["data-action"] == "copy-text"
    assert attrs["data-copy"] == HOSTILE
    assert attrs["data-copy-message"] == "Copied"
    assert not [name for name in attrs if name.startswith("on")]
