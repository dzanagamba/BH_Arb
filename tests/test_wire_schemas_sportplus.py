"""SR4-3f: strict wire schemas, SportPlus sixth.

WHAT THESE TESTS PROVE
----------------------
SportPlus is plain HTTP.  The dated fixtures freeze one match's ``markets[]``
array, where each block is ``{"id", "name", "odds": [{"alias", "value"}, ...]}``.
The prematch envelope is ``{"matches": [...]}`` (sometimes double-serialised as
a JSON string) and the live one is ``{"sports": [{"name", "matches": [...]}]}``.
The raw JSON is validated before the parser sees it.

* Both dated fixtures (prematch and live) satisfy the market schema with no
  unknown keys.
* A renamed price field and a string price are ``schema_drift``: the real
  ``scrape()`` raises ``ScrapeError`` and contributes no legs.
* An unknown key is kept (``extra="allow"``) and counted in
  ``bh_wire_unknown_keys_total`` and the log, never fatal.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The match *shell* (sport name, competitors, kickoff, league) has no dated
capture, so it stays unmodelled: its keys are neither rejected nor counted.  A
renamed team field still drops that match silently; SR4-4/SR5-1 own the
structural drift alarm.
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
    validate_sportplus_live,
    validate_sportplus_markets,
    validate_sportplus_prematch,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
PREMATCH_URL = "https://www.sportplus.ba/api/v1/prematch/offer"
LIVE_URL = "https://www.sportplus.ba/api/v1/live/offer"
MODES = ("prematch", "live")


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"sportplus_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _prematch_page(markets: Any) -> dict[str, Any]:
    return {
        "matches": [
            {
                "id": 3308085,
                "sportName": "NOGOMET",
                "sportId": 1,
                "competitors": "Home FC - Away FC",
                "matchDate": "2030-01-01T18:00:00",
                "leagueName": "Test League",
                "countryName": "",
                "betRadarId": None,
                "markets": markets,
            }
        ]
    }


def _live_page(markets: Any) -> dict[str, Any]:
    return {
        "date": "2026-11-08",
        "sports": [
            {
                "id": 1,
                "name": "NOGOMET",
                "matches": [
                    {
                        "id": "73577166",
                        "home": "Home FC",
                        "away": "Away FC",
                        "leagueName": "Test League",
                        "betting": True,
                        "betRadarId": None,
                        "markets": markets,
                    }
                ],
            }
        ],
    }


def _scrape(payload: Any, *, live: bool = False, double_serialised: bool = False):
    """Run the real ``scrape()`` against a mocked SportPlus endpoint."""
    from scrapers.sportplus import SportPlusScraper

    url = LIVE_URL if live else PREMATCH_URL
    if double_serialised:
        content = json.dumps(json.dumps(payload)).encode()
        response = httpx.Response(200, content=content)
    else:
        response = httpx.Response(200, json=payload)

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(url).mock(return_value=response)
            return await SportPlusScraper().scrape(live=live)

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_sportplus_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    markets = validate_sportplus_markets(capture["bets"])

    assert len(markets) == len(capture["bets"])
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_the_prematch_envelope_accepts_the_captured_markets():
    capture = _capture()

    page = validate_sportplus_prematch(_prematch_page(capture["bets"]))

    assert page.matches[0]["id"] == 3308085
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_the_live_envelope_accepts_the_captured_markets():
    capture = _capture("live")

    page = validate_sportplus_live(_live_page(capture["bets"]))

    assert len(page.sports) == 1
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_a_renamed_price_field_is_schema_drift():
    capture = _capture()
    odd = capture["bets"][0]["odds"][0]
    odd["price"] = odd.pop("value")

    with pytest.raises(ScrapeError) as caught:
        validate_sportplus_markets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "value" in str(caught.value)


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"][0]["odds"][0]["value"] = "1.6"

    with pytest.raises(ScrapeError) as caught:
        validate_sportplus_markets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_an_integer_price_is_accepted_without_becoming_a_string():
    markets = validate_sportplus_markets(
        [{"id": 1, "name": "NOGOMET", "odds": [{"alias": "1", "value": 2}]}]
    )

    assert markets[0].odds is not None
    assert markets[0].odds[0].value == 2.0


def test_a_market_block_without_odds_is_allowed():
    markets = validate_sportplus_markets([{"id": 1, "name": "NOGOMET", "odds": None}])

    assert markets[0].odds is None


def test_unknown_keys_are_kept_counted_and_logged(caplog):
    capture = _capture()
    capture["bets"][0]["brandNewMarketField"] = 1
    capture["bets"][0]["odds"][0]["brandNewOddField"] = "x"
    payload = _prematch_page(capture["bets"])
    payload["brandNewRootField"] = True

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        validate_sportplus_prematch(payload)

    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="sportplus",field="brandNewMarketField",'
        'level="market"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="sportplus",field="brandNewOddField",'
        'level="odd"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="sportplus",field="brandNewRootField",'
        'level="root"} 1' in text
    )
    assert "brandNewMarketField" in caplog.text


def test_the_real_prematch_scrape_emits_the_families_the_capture_declares():
    capture = _capture()

    matches = _scrape(_prematch_page(capture["bets"]))

    assert [match.bookmaker for match in matches] == ["sportplus"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_the_real_prematch_scrape_accepts_a_double_serialised_body():
    capture = _capture()

    matches = _scrape(_prematch_page(capture["bets"]), double_serialised=True)

    assert [match.bookmaker for match in matches] == ["sportplus"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_the_real_live_scrape_emits_the_families_the_capture_declares():
    capture = _capture("live")

    matches = _scrape(_live_page(capture["bets"]), live=True)

    assert [match.bookmaker for match in matches] == ["sportplus"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_unknown_keys_do_not_drop_the_book_from_a_scrape():
    capture = _capture()
    capture["bets"][0]["brandNewMarketField"] = 1

    matches = _scrape(_prematch_page(capture["bets"]))

    assert matches
    assert (
        'bh_wire_unknown_keys_total{book="sportplus",field="brandNewMarketField",'
        'level="market"} 1' in metrics.render()
    )


@pytest.mark.parametrize("mode", MODES)
def test_schema_drift_drops_the_book_and_contributes_zero_legs(mode):
    capture = _capture(mode)
    capture["bets"][0]["odds"][0]["value"] = "1.6"
    payload = _live_page(capture["bets"]) if mode == "live" else _prematch_page(
        capture["bets"]
    )

    with pytest.raises(ScrapeError) as caught:
        _scrape(payload, live=(mode == "live"))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_renamed_matches_key_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_sportplus_prematch({"events": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "matches" in str(caught.value)


def test_a_renamed_sports_key_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_sportplus_live({"matches": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "sports" in str(caught.value)


def test_a_non_json_body_is_schema_drift():
    from scrapers.sportplus import SportPlusScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(PREMATCH_URL).mock(
                return_value=httpx.Response(200, content=b"<html>not json</html>")
            )
            with pytest.raises(ScrapeError) as caught:
                await SportPlusScraper().scrape()
            return caught.value

    error = asyncio.run(scenario())

    assert error.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_metric_name_is_the_documented_one():
    validate_sportplus_markets(
        [{"id": 1, "name": "NOGOMET", "odds": [], "brandNew": 1}]
    )

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
