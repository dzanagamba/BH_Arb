"""SR6-1: one per-book declaration, with every other list derived from it.

WHAT THESE TESTS PROVE
----------------------
``config/bookmakers.py`` is the only place a book is declared. ``BOOKMAKERS``,
the lazy ``SCRAPERS`` registry, ``PLAYWRIGHT_BOOKIES`` and the transport
policies are projections of it, and an adapter module that nobody declared
fails the suite instead of failing at scan time with ``no scraper registered``.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove a new book's live feed works or that its markets are
admissible; a declaration only wires the adapter, and the market registry and
the certainty gate still decide what can be priced. The market-registry JSON
stays curated data, so the test checks its book set, not its rows.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from config.bookmakers import BROWSER_BOOKMAKERS, DECLARATIONS
from config.settings import BOOKMAKERS
from scrapers.registry import SCRAPERS
from scrapers.transport import policy_for
from server.api import PLAYWRIGHT_BOOKIES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRAPERS_DIR = REPO_ROOT / "scrapers"
MARKET_REGISTRY = REPO_ROOT / "config" / "bookmaker_markets.json"


def _adapter_modules() -> set[str]:
    """Modules under ``scrapers/`` that define an async ``scrape`` entry point."""
    found: set[str] = set()
    for path in sorted(SCRAPERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.AsyncFunctionDef) and node.name == "scrape"
            for node in ast.walk(tree)
        ):
            found.add(f"scrapers.{path.stem}")
    return found


def test_every_adapter_module_has_exactly_one_declaration():
    declared = [spec.module for spec in DECLARATIONS.values()]

    assert len(declared) == len(set(declared))
    assert set(declared) == _adapter_modules()


def test_every_declaration_resolves_to_an_adapter_class():
    class_names = [spec.class_name for spec in DECLARATIONS.values()]
    assert len(class_names) == len(set(class_names))
    for book, spec in DECLARATIONS.items():
        path = REPO_ROOT / Path(*spec.module.split(".")).with_suffix(".py")
        assert path.is_file(), f"{book}: {spec.module} does not exist"
        adapter = SCRAPERS[book]
        assert adapter.__name__ == spec.class_name
        assert callable(getattr(adapter, "scrape", None)), book


def test_the_package_exports_are_derived_too():
    import scrapers

    assert set(scrapers.__all__) == {
        spec.class_name for spec in DECLARATIONS.values()
    }
    # The two books the old hand-written export list had missed are included.
    assert "PremierKladionicaScraper" in scrapers.__all__
    assert "WWINScraper" in scrapers.__all__


def test_the_three_lists_are_derived_from_the_declaration():
    assert list(BOOKMAKERS) == list(DECLARATIONS)
    assert set(SCRAPERS) == set(DECLARATIONS)
    assert PLAYWRIGHT_BOOKIES == set(BROWSER_BOOKMAKERS)
    assert PLAYWRIGHT_BOOKIES == {
        book for book, spec in DECLARATIONS.items() if spec.transport == "browser"
    }
    for book, spec in DECLARATIONS.items():
        assert BOOKMAKERS[book]["name"] == spec.name
        assert BOOKMAKERS[book]["enabled"] is spec.enabled
        assert BOOKMAKERS[book]["base_url"] == spec.base_url


def test_the_market_registry_covers_exactly_the_declared_books():
    registry = json.loads(MARKET_REGISTRY.read_text(encoding="utf-8"))
    books = {book for book in registry if book != "_excluded"}

    assert books == set(DECLARATIONS)
    assert set(registry.get("_excluded") or {}) <= set(DECLARATIONS)


def test_the_transport_policy_timeouts_come_from_the_declaration():
    for book, spec in DECLARATIONS.items():
        for mode, timeout in spec.timeouts.items():
            assert policy_for(book, mode).total_timeout == timeout, (book, mode)


def test_the_registry_is_lazy_until_a_book_is_read():
    code = (
        "import sys\n"
        "import server.api\n"
        f"books = {sorted(_adapter_modules())!r}\n"
        "loaded = sorted(name for name in books if name in sys.modules)\n"
        "raise SystemExit(1 if loaded else 0)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr


def test_an_unknown_book_is_a_key_error_and_get_returns_none():
    with pytest.raises(KeyError):
        SCRAPERS["not_a_book"]
    assert SCRAPERS.get("not_a_book") is None
    assert "not_a_book" not in SCRAPERS
    assert SCRAPERS.declared == set(DECLARATIONS)


def test_a_read_resolves_and_caches_the_declared_class():
    first = SCRAPERS["mbet"]
    second = SCRAPERS["mbet"]

    assert first is second
    assert first.__name__ == DECLARATIONS["mbet"].class_name
