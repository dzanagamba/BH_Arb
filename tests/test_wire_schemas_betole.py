"""SR4-3d: strict wire schemas, Betole fourth.

WHAT THESE TESTS PROVE
----------------------
Betole is plain HTTP on the ExeFeed platform, but neither earlier shape fits:
its "price row" is a ``{pick_code: price}`` map and the two endpoints wrap it
differently — the desk listing is ``{"esMatches": [event, ...]}`` (each event
carries ``odds``) and the batched full offer is a list of
``{"id": ..., "odds": {...}}`` rows.  The raw JSON is validated before the
parser sees it.

* The dated capture's ``bets`` map satisfies the map schema, including prices
  that are strings only when they are numbers.
* A string price, a renamed ``odds`` envelope key and a renamed ``esMatches``
  key are ``schema_drift``: the real ``scrape()`` raises ``ScrapeError`` and
  contributes no legs.
* An unknown key is kept (``extra="allow"``) and counted in
  ``bh_wire_unknown_keys_total`` and the log, never fatal.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The desk *event* shell (teams, kickoff, live flags) has no dated capture, so it
stays unmodelled: its keys are neither rejected nor counted.  A renamed team
field still drops that event silently; SR4-4/SR5-1 own the structural drift
alarm.  The pick codes inside the odds map are data, not an allow-list, so an
unknown code is not a wire-drift signal (``record_unmapped`` already tracks the
codes the parser cannot price).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.wire_schemas import (
    METRIC_UNKNOWN_KEYS,
    validate_betole_desk,
    validate_betole_offer_map,
    validate_betole_offers,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"

DESK_URL = "https://www.betole.ba/restapi/offer/ba/sport/S/desk"
BULK_PREFIX = "https://www.betole.ba/restapi/offer/ba/matches/by-ids"


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture() -> dict[str, Any]:
    path = FIXTURE_DIR / "betole_prematch.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _desk_event(odds: Any, *, live: bool = False) -> dict[str, Any]:
    return {
        "id": 91393484,
        "matchCode": "91393484",
        "home": "San Carlos",
        "away": "Zeledon",
        "leagueName": "Test League",
        "kickOffTime": "2030-01-01T18:00:00Z",
        "live": live,
        "blocked": False,
        "brMatchId": "",
        "odds": odds,
    }


def _desk_page(odds: Any, *, live: bool = False) -> dict[str, Any]:
    return {"esMatches": [_desk_event(odds, live=live)]}


def _offer_rows(odds: Any) -> list[dict[str, Any]]:
    return [{"id": 91393484, "odds": odds}]


def _scrape(desk: Any = None, offer: Any = None, *, live: bool = False):
    """Run the real ``scrape()`` against mocked Betole endpoints."""
    from scrapers.betole import BetoleScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(DESK_URL).mock(return_value=httpx.Response(200, json=desk))
            mock.get(url__startswith=BULK_PREFIX).mock(
                return_value=httpx.Response(200, json=offer)
            )
            return await BetoleScraper().scrape(live=live)

    return asyncio.run(scenario())


def test_the_captured_odds_map_satisfies_the_strict_schema():
    capture = _capture()

    odds = validate_betole_offer_map(capture["bets"])

    assert odds == capture["bets"]
    assert odds["284"] == 1.35  # the unmapped control code is kept, not rejected


def test_an_integer_price_is_accepted_without_becoming_a_string():
    odds = validate_betole_offer_map({"1": 2, "2": 3.4})

    assert odds["1"] == 2.0


def test_a_null_pick_is_allowed_and_read_as_no_price():
    """The parser reads a null as "no price" instead of crashing; keep that."""
    odds = validate_betole_offer_map({"1": None, "2": 3.4})

    assert odds["1"] is None


def test_a_string_price_is_never_coerced():
    with pytest.raises(ScrapeError) as caught:
        validate_betole_offer_map({"1": "1.47"})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "1" in str(caught.value)


def test_a_renamed_es_matches_key_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_betole_desk({"matches": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "esMatches" in str(caught.value)


def test_the_desk_event_shell_is_not_modelled_yet():
    """A renamed shell key cannot be told from an event with no odds yet."""
    page = validate_betole_desk({"esMatches": [{"id": 1, "prices": {"1": 2.0}}]})

    assert page.esMatches == [{"id": 1, "prices": {"1": 2.0}}]


def test_an_offer_row_without_odds_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_betole_offers([{"id": 1, "prices": {"1": 2.0}}])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "odds" in str(caught.value)


def test_a_string_price_in_an_offer_row_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_betole_offers([{"id": 1, "odds": {"1": "2.0"}}])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_unknown_keys_are_kept_counted_and_logged(caplog):
    capture = _capture()
    desk = _desk_page(capture["bets"])
    desk["brandNewPageField"] = True
    rows = _offer_rows(capture["bets"])
    rows[0]["brandNewRowField"] = 1

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        validate_betole_desk(desk)
        validate_betole_offers(rows)

    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="betole",field="brandNewPageField",'
        'level="root"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="betole",field="brandNewRowField",'
        'level="row"} 1' in text
    )
    assert "brandNewRowField" in caplog.text


def test_the_real_scrape_emits_the_families_the_capture_declares():
    capture = _capture()

    matches = _scrape(
        desk=_desk_page({}),
        offer=_offer_rows(capture["bets"]),
    )

    assert [match.bookmaker for match in matches] == ["betole"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"]) | set(
        capture["experimental_markets"]
    )


def test_the_live_capture_parses_from_the_full_offer():
    """SR8-1: a live desk event prices the proven live codes from its full offer."""
    capture = json.loads(
        (FIXTURE_DIR / "betole_live.json").read_text(encoding="utf-8")
    )

    matches = _scrape(
        desk=_desk_page({}, live=True),
        offer=_offer_rows(capture["bets"]),
        live=True,
    )

    assert [match.bookmaker for match in matches] == ["betole"]
    assert matches[0].is_live is True
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_unknown_keys_do_not_drop_the_book_from_a_scrape():
    capture = _capture()
    rows = _offer_rows(capture["bets"])
    rows[0]["brandNewRowField"] = 1

    matches = _scrape(desk=_desk_page({}), offer=rows)

    assert matches
    assert (
        'bh_wire_unknown_keys_total{book="betole",field="brandNewRowField",'
        'level="row"} 1' in metrics.render()
    )


def test_a_string_price_in_the_full_offer_drops_the_book_and_yields_no_legs():
    capture = _capture()
    odds = dict(capture["bets"])
    odds["1"] = "1.47"

    with pytest.raises(ScrapeError) as caught:
        _scrape(desk=_desk_page({}), offer=_offer_rows(odds))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_string_price_in_the_desk_odds_drops_the_book():
    capture = _capture()
    odds = dict(capture["bets"])
    odds["1"] = "1.47"

    with pytest.raises(ScrapeError) as caught:
        _scrape(desk=_desk_page(odds), offer=_offer_rows(capture["bets"]))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_json_desk_page_is_schema_drift():
    from scrapers.betole import BetoleScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(DESK_URL).mock(
                return_value=httpx.Response(200, content=b"<html>not json</html>")
            )
            with pytest.raises(ScrapeError) as caught:
                await BetoleScraper().scrape()
            return caught.value

    error = asyncio.run(scenario())

    assert error.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_json_full_offer_body_is_schema_drift():
    capture = _capture()
    from scrapers.betole import BetoleScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(DESK_URL).mock(
                return_value=httpx.Response(200, json=_desk_page({}))
            )
            mock.get(url__startswith=BULK_PREFIX).mock(
                return_value=httpx.Response(200, content=b"<html>not json</html>")
            )
            with pytest.raises(ScrapeError) as caught:
                await BetoleScraper().scrape()
            return caught.value

    error = asyncio.run(scenario())

    assert error.kind is ScrapeKind.SCHEMA_DRIFT
    assert capture["bets"]  # the fixture is the desk fallback that must not hide it


def test_the_metric_name_is_the_documented_one():
    validate_betole_offers([{"id": 1, "odds": {"1": 2.0}, "brandNew": 1}])

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
