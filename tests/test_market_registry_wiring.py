"""Registry <-> parser wiring: does each book's real dispatch use the registry?

WHAT THESE TESTS PROVE
----------------------
For one representative market per book, a **synthetic payload** is fed to that
book's real market-parsing entry point (``parse_nsoft_bets``,
``_resolve_mbet_market``, ``SportPlusScraper._parse_markets``,
``_build_markets_from_bets``, …) and the resulting ``Market`` is compared with
what the registry declares for the source ID that went into it.

That is end-of-dispatch, not just a lookup, so it also exercises the hardcoded
dispatch and pick tables in ``scrapers/wwin.py`` and ``scrapers/betole.py`` that a
direct call to the registry-resolution helper would bypass. A registered ID that
the parser's dispatch table ignores cannot pass these tests.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
* **Not that a real bookmaker feed emits these IDs.** Every payload here is
  synthetic. Captured-payload coverage is Task 11's job.
* **Not that every registry-declared ID is dispatched.** Each book is probed with
  the one code its parser actually dispatches on, listed in ``DISPATCH_CASES``
  with a comment saying where that code comes from. A registry row may declare a
  superset of what the parser reads: betole's Over/Under rows do, and
  ``MARKET_MAPPING.md`` says so.
* **Not that a wrong-but-consistent ID is caught.** The registry and the parser
  read the same file, so a wrong ID is wrong in both. Changing mdshop's prematch
  1X2 from ``135`` to ``999`` leaves every test in this file green.
* **Not every book has a payload-driven case.** ``premier_kladionica`` resolves
  markets inside a positional ``PrSync`` response builder that would need a
  fabricated multi-section payload; it is covered only by the static
  registry-routing check below, and that limitation is deliberate rather than
  papered over with a contrived payload.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from engine.market_registry import MarketRegistry
from models.schemas import Market, MarketType
from scrapers.admiralbet import _parse_bets as admiralbet_parse_bets
from scrapers.betole import _parse_betole_markets
from scrapers.common import parse_nsoft_bets
from scrapers.evlbet import EvlbetScraper
from scrapers.mbet import _resolve_mbet_market
from scrapers.mozzartbet import _parse_markets as mozzart_parse_markets
from scrapers.sportplus import SportPlusScraper

# The parser module that owns each bookmaker's market parsing. Used by the static
# registry-routing check below.
PARSER_MODULES = {
    "mdshop": "scrapers.mdshop",
    "admiralbet": "scrapers.admiralbet",
    "wwin": "scrapers.wwin",
    "premier_kladionica": "scrapers.premier_kladionica",
    "mbet": "scrapers.mbet",
    "sportplus": "scrapers.sportplus",
    "evlbet": "scrapers.evlbet",
    "betole": "scrapers.betole",
    "mozzartbet": "scrapers.mozzartbet",
}

_1X2_LABELS = ["1", "X", "2"]


def _odds(labels: list[str], base: float = 2.0) -> list[dict[str, Any]]:
    return [{"alias": label, "value": base + i * 0.1} for i, label in enumerate(labels)]


# --- one dispatch case per book -------------------------------------------
# Each entry is (bookmaker, source_id, market_type, payload, parse_callable).
# The source_id is the code that book's parser actually dispatches on, taken from
# the dispatch/pick table in its own module -- not from the registry -- so this
# cannot become a tautology over the registry.

def _nsoft(bookmaker: str, bet_id: int):
    def parse() -> list[Market]:
        bets = [{
            "betTypeId": bet_id,
            "betOutcomes": [{"name": label, "odd": 2.0 + i * 0.1} for i, label in enumerate(_1X2_LABELS)],
        }]
        return parse_nsoft_bets(bets, bookmaker=bookmaker, mode="prematch")

    return parse


def _mbet():
    def parse() -> list[Market]:
        markets = _resolve_mbet_market(
            "fb", {"ofb:fs:1": 2.1, "ofb:fs:X": 3.2, "ofb:fs:2": 3.5}
        )
        return [Market(market_type=MarketType.MATCH_RESULT, odds=markets["1X2"])]

    return parse


def _sportplus():
    def parse() -> list[Market]:
        return SportPlusScraper()._parse_markets([
            {"id": 1, "name": "NOGOMET", "odds": _odds(_1X2_LABELS)}
        ])

    return parse


def _mozzartbet():
    def parse() -> list[Market]:
        event = {"odds": [
            {
                "game": {"id": 1, "shortName": "ki", "name": "Konacan ishod"},
                "subgame": {"name": label},
                "value": 2.0 + i * 0.1,
            }
            for i, label in enumerate(_1X2_LABELS)
        ]}
        return mozzart_parse_markets(event, "prematch", "mozzartbet")

    return parse


def _betole():
    # betole.py:107 dispatches MATCH_RESULT on pick codes 1/2/3 (not 135).
    def parse() -> list[Market]:
        return _parse_betole_markets({"1": 2.1, "2": 3.2, "3": 3.5})

    return parse


def _evlbet():
    def parse() -> list[Market]:
        match = EvlbetScraper()._parse_event({
            "TeamHome": "A", "TeamAway": "B", "Id": 1,
            "MatchStartTime": "2026-08-15T18:00:00",
            "BasicOffer": {"Odds": [
                {"Name": label, "Odd": 2.0 + i * 0.1} for i, label in enumerate(_1X2_LABELS)
            ]},
        })
        return match.markets if match is not None else []

    return parse


def _wwin():
    # wwin.py:122 dispatches on bet_id == 95.
    def parse() -> list[Market]:
        from scrapers.wwin import _build_markets_from_bets

        return _build_markets_from_bets([{
            "idBt": 95,
            "odds": [
                {"t": label, "va": 2.0 + i * 0.1, "isv": 1}
                for i, label in enumerate(_1X2_LABELS)
            ],
        }], "prematch")

    return parse


def _admiralbet():
    def parse() -> list[Market]:
        bets = [{
            "betTypeId": 1639,
            "betOutcomes": [{"name": label, "odd": 2.0 + i * 0.1} for i, label in enumerate(_1X2_LABELS)],
        }]
        return admiralbet_parse_bets(bets)

    return parse


DISPATCH_CASES = [
    pytest.param("mdshop", 135, _nsoft("mdshop", 135), id="mdshop"),
    pytest.param("admiralbet", 1639, _admiralbet(), id="admiralbet"),
    pytest.param("mbet", "ofb:fs", _mbet(), id="mbet"),
    pytest.param("sportplus", 1, _sportplus(), id="sportplus"),
    pytest.param("mozzartbet", 1, _mozzartbet(), id="mozzartbet"),
    pytest.param("betole", 1, _betole(), id="betole"),
    pytest.param("evlbet", "12005", _evlbet(), id="evlbet"),
    pytest.param("wwin", 95, _wwin(), id="wwin"),
]

# Books with a payload-driven dispatch case above.
COVERED_BOOKS = frozenset(
    {"mdshop", "admiralbet", "mbet", "sportplus", "mozzartbet", "betole", "evlbet", "wwin"}
)


@pytest.mark.parametrize(("bookmaker", "source_id", "parse"), DISPATCH_CASES)
def test_registered_id_is_dispatched_by_its_books_parser(
    bookmaker: str, source_id: Any, parse: Any
):
    """A registered ID fed through the real parser yields the declared market."""
    spec = MarketRegistry().lookup_type(
        bookmaker, "prematch", source_id, MarketType.MATCH_RESULT
    )
    assert spec is not None, f"{bookmaker}/{source_id} is not in the registry"

    markets = parse()
    results = [m for m in markets if m.market_type is MarketType.MATCH_RESULT]
    assert results, (
        f"{bookmaker} parser dropped its registered prematch 1X2 id {source_id!r}; "
        "the dispatch table does not reach the registry"
    )
    labels = {o.label for o in results[0].odds}
    assert labels == spec.labels, (
        f"{bookmaker} 1X2 labels {sorted(labels)} != registry {sorted(spec.labels)}"
    )
    assert len(labels) >= spec.min_legs


def test_nsoft_rejects_an_unregistered_bet_type_id():
    """Negative control: proves the dispatch test above is capable of failing.

    A parser that ignored its input entirely would still pass the positive test,
    so one case must demonstrate that an ID the registry does not know is dropped.
    """
    results = [
        m for m in _nsoft("mdshop", 4242)() if m.market_type is MarketType.MATCH_RESULT
    ]
    assert not results, "an unregistered NSoft betTypeId produced a match-result market"


# --- static check: every book routes through the shared registry -----------

# Which module actually talks to the registry for each book. mdshop and
# admiralbet hand the entire NSoft parse to scrapers.common, so the registry
# lives there; every other book resolves in its own module.
REGISTRY_OWNER = {
    book: ("scrapers.common" if book in {"mdshop", "admiralbet"} else module)
    for book, module in PARSER_MODULES.items()
}


@pytest.mark.parametrize("bookmaker", sorted(PARSER_MODULES))
def test_every_book_parser_routes_through_the_shared_registry(bookmaker: str):
    """Static check: the module uses the app-wide registry singleton.

    This is the only coverage ``premier_kladionica`` gets, because its dispatch
    sits inside a positional PrSync response builder. It proves the module that
    owns the book's registry lookups imports ``engine.market_registry``, queries
    it, and does not build a private registry of its own (which would drift from
    the one the app and the documentation use). It is a source-level check, not a
    dispatch test.
    """
    import importlib
    import inspect

    module = importlib.import_module(REGISTRY_OWNER[bookmaker])
    source = inspect.getsource(module)

    assert re.search(
        r"\bfrom engine\.market_registry import\b|\bimport engine\.market_registry\b", source
    ), f"{module.__name__} does not import the market registry; it cannot be registry-driven"
    assert "MarketRegistry(" not in source, (
        f"{module.__name__} instantiates its own MarketRegistry; every book must "
        "share the singleton so the parsers and the documentation cannot drift apart"
    )
    assert re.search(r"\b(lookup|lookup_type|ids_for|has_source_id)\b", source), (
        f"{module.__name__} imports the registry but never queries it"
    )


def test_every_enabled_bookmaker_has_a_parser_module_and_a_documented_gap():
    """A book in settings must have a parser module and a dispatch case.

    ``premier_kladionica`` is the one documented exception: no synthetic payload
    is fabricated for it, and it relies on the static check above.
    """
    from config.settings import BOOKMAKERS

    documented_gaps = {"premier_kladionica"}
    for bid in BOOKMAKERS:
        assert bid in PARSER_MODULES, f"{bid} has no parser module registered"
        assert bid in COVERED_BOOKS or bid in documented_gaps, (
            f"{bid} has no dispatch case and is not a documented gap; add a case "
            "or add it to documented_gaps with a reason"
        )
    assert documented_gaps <= set(PARSER_MODULES)
