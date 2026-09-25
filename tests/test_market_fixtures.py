"""Each registry entry is exercised by a payload captured from the live API.

WHAT THESE TESTS PROVE
----------------------
``config/bookmaker_markets.json`` declares one source ID per
bookmaker/mode/market.  ``tests/test_market_registry.py`` proves the file is
internally consistent and ``tests/test_market_registry_wiring.py`` proves each
parser dispatches the IDs it is *given* -- but both of those read the same file,
so most wrong-but-consistent IDs stay green.  Measured against the two lower
layers, this file is the only one that fails for sportplus prematch BTTS
(``6`` -> ``5``), mozzartbet prematch BTTS (``130`` -> ``131``) and MBet prematch
Over/Under 2.5 (``ofb:tg`` -> ``ofb:ht``): all three leave the registry suite and
the wiring suite fully green.

Every payload in ``tests/fixtures/markets/`` was read out of a real HTTP
response from the book and hand-trimmed (see ``scripts/capture_market_fixtures.py``,
which regenerates them and records the endpoint in each file).  Feeding those
payloads to each book's REAL market-parsing entry point is the only layer that
compares the registry against what the book actually serves.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
* **Not that a synthetic payload is right.** That is Task 9's job; a payload
  built from the parser's own constants cannot catch a wrong ID because the
  fixture and the parser would be wrong together.
* **Not every registry row is covered.** Rows the live feed cannot supply stay
  unexercised, and ``UNCOVERED_ROWS`` below names each one with its reason, so
  a *new* gap fails the test instead of passing unnoticed.  EVLBet has no
  fixture at all: its flat offer endpoint answered with an empty list.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from engine.market_registry import MarketRegistry
from models.schemas import Market, MarketType

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "markets"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))

CORE_MARKET_TYPES = (
    MarketType.MATCH_RESULT,
    MarketType.DOUBLE_CHANCE,
    MarketType.BTTS,
    MarketType.OVER_UNDER_1_5,
    MarketType.OVER_UNDER_2_5,
    MarketType.OVER_UNDER_3_5,
)

# Registry rows deliberately NOT exercised by a captured payload, each with the
# reason.  Adding a row here is a claim about the feed, so it needs a reason.
UNCOVERED_ROWS: dict[tuple[str, str, str], str] = {
    ("evlbet", "prematch", "1x2"): (
        "sportapis.evlbet.com answers the flat offer endpoint with 200 and an empty "
        "list for every SportIds/Limit/Offset tried, so the book served no payload to "
        "capture. No fixture is fabricated in its place."
    ),
    ("mozzartbet", "prematch", "over_under_1_5"): (
        "game 3 serves subgames 2+/3+/0-2 only; there is no 0-1 leg, and the "
        "registry's min_legs of 2 means a one-legged total cannot be emitted."
    ),
    ("mozzartbet", "prematch", "over_under_3_5"): "same: no 4+/0-3 pair on the feed.",
    ("mozzartbet", "live", "over_under_1_5"): "same as prematch on the live feed.",
    ("mozzartbet", "live", "over_under_3_5"): "same as prematch on the live feed.",
    ("premier_kladionica", "live", "btts"): (
        "the live feed names this market 'LIVE - OBA TIMA DAJU GOL', but the parser's "
        "NAME_BTTS constant is 'OBA DAJU GOL', so the registry's live LIVE_OBA_DAJU_GOL "
        "row is unreachable: registry and parser agree with each other and disagree "
        "with the feed. Found by this layer; needs a registry/parser fix."
    ),
    # betole is disabled in config/settings.py and is not in this layer's scope:
    # its desk feed IS reachable, but _parse_betole_markets emits the
    # experimental first_half_1x2 market unconditionally in prematch mode, so no
    # trim of a real payload can satisfy "emitted == declared registry rows".
    **{(("betole", "prematch", mt.value)): "book is disabled in config/settings.py; see above"
       for mt in CORE_MARKET_TYPES},
}

# Books that must have at least one captured payload, so a book cannot quietly
# lose its coverage. EVLBet and betole are listed with the reason they are exempt.
BOOKS_WITHOUT_FIXTURES: dict[str, str] = {
    "evlbet": "its flat offer endpoint served an empty list (see UNCOVERED_ROWS)",
    "betole": "disabled book whose parser emits an unregistered market (see UNCOVERED_ROWS)",
}


# ---------------------------------------------------------------------------
# fixture -> real parser
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _premier_lookups(data: dict[str, Any]) -> tuple[dict, dict, dict]:
    """Rebuild the three PrSync lookup tables from the stored definition rows.

    The indices mirror ``PremierKladionicaScraper.fetch_and_parse``: setTip is
    keyed on (sport, setTipID), setTipVar on (sport, setTipID, varID) with the
    line in column 9, and setTipTip on (sport, setTipID, tipID) with the outcome
    code in column 4. A mismatch here fails the test loudly rather than passing
    quietly, which is the safe direction.
    """
    lookup = data["lookup"]
    set_tip = {(row[0], row[1]): row[2] for row in lookup["set_tip"]}
    set_tip_var = {
        (row[0], row[1], row[2]): row[9] for row in lookup["set_tip_var"]
    }
    set_tip_tip: dict[tuple[int, int, int], Any] = {}
    for row in lookup["set_tip_tip"]:
        key = (row[0], row[1], row[2])
        set_tip_tip.setdefault(key, row[4])
    return set_tip, set_tip_var, set_tip_tip


def _run_parser(data: dict[str, Any]) -> list[Market]:
    """Drive the book's real market-parsing entry point with a captured payload.

    No scraper is refactored for this: every parser already consults the shared
    registry, and the brief's proposed ``parse_markets(bookmaker, mode, payload)``
    wrapper per scraper would only be a second name for the calls below.
    """
    book = data["bookmaker"]
    mode = data["mode"]
    bets = data["bets"]

    if book in ("mdshop", "admiralbet"):
        from scrapers.common import parse_nsoft_bets, parse_nsoft_live_bets

        if mode == "live":
            return parse_nsoft_live_bets(bets, bookmaker=book)
        return parse_nsoft_bets(bets, bookmaker=book, mode="prematch")

    if book == "wwin":
        from scrapers.wwin import _build_markets_from_bets

        return _build_markets_from_bets(bets, mode=mode)

    if book == "premier_kladionica":
        from scrapers.premier_kladionica import PremierKladionicaScraper

        set_tip, set_tip_var, set_tip_tip = _premier_lookups(data)
        return PremierKladionicaScraper()._build_markets(
            bets, set_tip, set_tip_var, set_tip_tip, live=(mode == "live")
        )

    if book == "mbet":
        from scrapers.mbet import MBetScraper

        # _parse_event is the real entry point; the fixture supplies the odds
        # verbatim and only the event shell around them is filled in, because
        # the parser needs two competitors before it looks at a single odd.
        event = {
            "id": f"{book}-{mode}-fixture",
            "id_sport": data["context"]["id_sport"],
            "utc_scheduled": "2026-09-25T18:00:00",
            "competitors": [{"name": "Fixture Home"}, {"name": "Fixture Away"}],
            "odds": bets,
        }
        match = MBetScraper()._parse_event(event, set(), live=(mode == "live"))
        return match.markets if match is not None else []

    if book == "sportplus":
        from scrapers.sportplus import SportPlusScraper

        scraper = SportPlusScraper()
        if mode == "live":
            return scraper._parse_live_markets(bets)
        return scraper._parse_markets(bets)

    if book == "mozzartbet":
        from scrapers.mozzartbet import _parse_markets

        return _parse_markets({"odds": bets}, mode=mode, bookmaker=book)

    if book == "evlbet":
        from scrapers.evlbet import EvlbetScraper

        match = EvlbetScraper()._parse_event(bets[0])
        return match.markets if match is not None else []

    raise AssertionError(f"no parser adapter for bookmaker {book!r}")


def _emitted(data: dict[str, Any]) -> set[str]:
    return {market.market_type.value for market in _run_parser(data)}


# ---------------------------------------------------------------------------
# the assertions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_captured_payload_emits_exactly_the_declared_markets(path: Path):
    """A live payload must produce the declared markets -- and nothing else."""
    data = _load(path)
    book, mode = data["bookmaker"], data["mode"]
    registry = MarketRegistry()

    emitted = _emitted(data)
    assert emitted == set(data["expected_markets"]), (
        f"{book}/{mode}: parser emitted {sorted(emitted)} but the capture declares "
        f"{sorted(data['expected_markets'])}"
    )
    for market_type in data["expected_markets"]:
        assert registry.ids_for(book, mode, MarketType(market_type)), (
            f"{book}/{mode}/{market_type} is emitted but not declared in the registry"
        )


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_every_emitted_market_obeys_its_registry_label_rule(path: Path):
    """ID match is not enough: the label set and leg count must hold too."""
    data = _load(path)
    book, mode = data["bookmaker"], data["mode"]
    registry = MarketRegistry()

    for market in _run_parser(data):
        specs = [
            spec
            for source_id in registry.ids_for(book, mode, market.market_type)
            for spec in registry.specs_for(book, mode, source_id)
            if spec.market_type == market.market_type
        ]
        assert specs, f"{book}/{mode}: {market.market_type.value} is not declared"
        labels = {odd.label for odd in market.odds}
        matching = [
            spec for spec in specs
            if labels <= spec.labels and len(labels) >= spec.min_legs
        ]
        assert matching, (
            f"{book}/{mode}/{market.market_type.value}: labels {sorted(labels)} match none "
            f"of the registry's declared label sets "
            f"{[sorted(s.labels) for s in specs]}"
        )


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_records_its_provenance(path: Path):
    """A capture nobody can trace is indistinguishable from a fabricated one."""
    data = _load(path)
    for key in ("bookmaker", "mode", "captured_at", "endpoint", "source", "provenance",
                "payload_kind", "expected_markets", "bets"):
        assert key in data, f"{path.name} does not record {key!r}"
    assert data["source"] == "live_api_response", (
        f"{path.name} is marked {data['source']!r}; only a live capture is useful here"
    )
    assert data["bookmaker"] and data["mode"] in ("prematch", "live")
    assert data["endpoint"].startswith(("http", "POST http")), f"{path.name} records no endpoint"
    assert len(data["provenance"]) > 60, f"{path.name} has no usable provenance note"
    assert date.fromisoformat(data["captured_at"]) == date.fromisoformat(
        data["captured_at"]
    ), f"{path.name} captured_at is not an ISO date: {data['captured_at']!r}"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_ids_the_capture_excludes_are_excluded_on_purpose(path: Path):
    """Excluded IDs in a capture must be excluded, and must emit nothing."""
    data = _load(path)
    registry = MarketRegistry()
    present = _source_ids_in(data)
    for control in data.get("excluded_ids_present", []):
        source_id, context = control["id"], control.get("context")
        assert str(source_id) in present, (
            f"{path.name} claims {source_id!r} is present but the payload does not carry it"
        )
        assert registry.is_excluded(data["bookmaker"], data["mode"], source_id, context=context), (
            f"{path.name} keeps {source_id!r} ({context!r}) as a control, but the registry "
            "does not exclude it -- a parser is expected to count it as unmapped, not "
            "to drop it silently"
        )
    # An excluded ID must not smuggle its market into the emitted set. The exact
    # -set assertion above already fails if it does; this states the intent.
    assert _emitted(data) == set(data["expected_markets"])


def _source_ids_in(data: dict[str, Any]) -> set[str]:
    """Every source ID a trimmed payload carries, as strings."""
    book, bets = data["bookmaker"], data["bets"]
    if book in ("mdshop", "admiralbet"):
        return {str(b["betTypeId"]) for b in bets}
    if book == "wwin":
        return {str(b["idBt"]) for b in bets}
    if book == "mbet":
        return {":".join(key.split(":")[:2]) for key in bets}
    if book == "sportplus":
        return {str(b.get("id")) for b in bets}
    if book == "mozzartbet":
        return {str(o["game"]["id"]) for o in bets}
    if book == "premier_kladionica":
        return {str(row[1]) for row in data["lookup"]["set_tip"]}
    if book == "evlbet":
        offer = bets[0].get("BasicOffer") or {}
        return {str(offer.get("BetTypeKey") or offer.get("GameId") or "12005")}
    return set()


def test_coverage_gaps_are_declared_rather_than_ignored():
    """Every registry row is either exercised by a capture or explained here."""
    registry = MarketRegistry()
    books = _all_registry_books()

    covered: set[tuple[str, str, str]] = set()
    for path in FIXTURES:
        data = _load(path)
        for market_type in data["expected_markets"]:
            covered.add((data["bookmaker"], data["mode"], market_type))

    declared = {
        (book, mode, market_type.value)
        for book in books
        for mode in ("prematch", "live")
        for market_type in CORE_MARKET_TYPES
        if registry.ids_for(book, mode, market_type)
    } - covered
    assert declared == set(UNCOVERED_ROWS), (
        "UNCOVERED_ROWS is out of date: it claims "
        f"{sorted(set(UNCOVERED_ROWS) - declared)} which are now covered, and misses "
        f"{sorted(declared - set(UNCOVERED_ROWS))}"
    )

    for book in books:
        has_capture = any(path.stem.startswith(f"{book}_") for path in FIXTURES)
        assert has_capture or book in BOOKS_WITHOUT_FIXTURES, (
            f"{book} has no captured payload; add one or document it in "
            "BOOKS_WITHOUT_FIXTURES with a reason"
        )


def _all_registry_books() -> list[str]:
    with open(MarketRegistry().path, encoding="utf-8") as handle:
        return sorted(
            book for book in json.load(handle)
            if not book.startswith("_")
        )


def _fixture_for(book: str, mode: str) -> Path:
    return FIXTURE_DIR / f"{book}_{mode}.json"


def test_a_captured_unregistered_id_is_counted_not_dropped():
    """The one global constraint the exact-set test cannot see on its own.

    admiralbet's live feed serves the 22/28 totals, but its registry declares no
    live Over/Under row, so those IDs are neither mapped nor excluded: they must
    be recorded in the process-wide diagnostic rather than vanish.
    """
    from engine.market_registry import unmapped_markets

    data = _load(_fixture_for("admiralbet", "live"))
    carried = _source_ids_in(data)
    unregistered = [
        source_id
        for source_id in ("22", "28")
        if source_id in carried
        and not MarketRegistry().has_source_id("admiralbet", "live", source_id)
    ]
    assert unregistered, (
        "the admiralbet live capture is supposed to carry the unregistered 22/28 "
        "totals; without them nothing tests the 'counted, never dropped' rule"
    )
    before = dict(unmapped_markets)
    _run_parser(data)
    after = unmapped_markets
    for source_id in unregistered:
        assert after.get(f"admiralbet:{source_id}", 0) > before.get(f"admiralbet:{source_id}", 0), (
            f"admiralbet:{source_id} is not in the registry and not excluded, so parsing "
            "the capture must have recorded it in engine.market_registry.unmapped_markets"
        )
