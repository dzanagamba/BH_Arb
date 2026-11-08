"""SR4-3: strict wire schemas, MDShop first.

WHAT THESE TESTS PROVE
----------------------
The parser-contract suite feeds a captured ``bets`` array straight to the
parser, so a payload whose price field was renamed or served as a string could
still parse into *something*.  These tests put the schema at the transport
boundary instead: the raw JSON is validated with pydantic ``strict=True`` before
any parser sees it.

* Both MDShop fixtures satisfy the schema with no unknown keys.
* A renamed price field and a string price are ``schema_drift``: ``scrape()``
  raises ``ScrapeError`` and contributes no legs.
* An unknown key is kept (``extra="allow"``) and counted in
  ``bh_wire_unknown_keys_total`` and the log, never fatal.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove the model covers every field the live feed can send.  Unknown
keys are telemetry for exactly that gap; a new *consumed* field needs the model
and its allow-list updated here.
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
    unknown_key_counts,
    validate_bets,
    validate_response,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
MODES = ("prematch", "live")


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"mdshop_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _envelope(bets: Any) -> dict[str, Any]:
    """The captured bets inside the event shell the adapter requests."""
    return {
        "events": [
            {
                "id": 6917979,
                "name": "Home FC - Away FC",
                "dateTime": "2030-01-01T18:00:00",
                "sportId": 1,
                "competitionName": "Test League",
                "regionName": "Test Region",
                "isInOffer": True,
                "bets": bets,
            }
        ]
    }


def _scrape_with(payload: Any):
    from scrapers.mdshop import MDShopScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            route = mock.get(
                url__startswith="https://mdoffer.mdshop.ba/api/offer/getwebevents"
            ).mock(return_value=httpx.Response(200, json=payload))
            matches = await MDShopScraper().scrape()
            return matches, route

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_mdshop_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    bets = validate_bets(capture["bets"])

    assert len(bets) == len(capture["bets"])
    assert unknown_key_counts(_envelope(capture["bets"])) == {}


def test_the_response_envelope_accepts_the_captured_event_shell():
    capture = _capture()

    response = validate_response(_envelope(capture["bets"]))

    assert len(response.events) == 1
    assert len(response.events[0].bets) == len(capture["bets"])


def test_a_renamed_price_field_is_schema_drift():
    capture = _capture()
    outcome = capture["bets"][0]["betOutcomes"][0]
    outcome["price"] = outcome.pop("odd")

    with pytest.raises(ScrapeError) as caught:
        validate_bets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "odd" in str(caught.value)


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"][0]["betOutcomes"][0]["odd"] = "1.85"

    with pytest.raises(ScrapeError) as caught:
        validate_bets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "odd" in str(caught.value)


def test_an_integer_price_is_accepted_without_becoming_a_string():
    """NSoft sometimes sends ``2`` rather than ``2.0``; that is still a number."""
    capture = _capture()
    capture["bets"][0]["betOutcomes"][0]["odd"] = 2

    bets = validate_bets(capture["bets"])

    assert bets[0].betOutcomes[0].odd == 2.0


def test_unknown_keys_are_kept_counted_and_logged(caplog):
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1
    capture["bets"][0]["betOutcomes"][0]["brandNewOutcomeField"] = "x"

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        bets = validate_bets(capture["bets"])

    assert len(bets) == len(capture["bets"])
    assert bets[0].model_extra["brandNewBetField"] == 1
    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="mdshop",field="brandNewBetField",level="bet"} 1'
        in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="mdshop",field="brandNewOutcomeField",'
        'level="outcome"} 1' in text
    )
    assert "brandNewBetField" in caplog.text


def test_an_unknown_event_key_is_counted_too():
    capture = _capture()
    payload = _envelope(capture["bets"])
    payload["events"][0]["brandNewEventField"] = True

    validate_response(payload)

    assert (
        'bh_wire_unknown_keys_total{book="mdshop",field="brandNewEventField",'
        'level="event"} 1' in metrics.render()
    )


def test_unknown_keys_do_not_drop_the_book_from_a_scrape():
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1

    matches, route = _scrape_with(_envelope(capture["bets"]))

    assert route.call_count == 1
    assert matches
    assert any(market.odds for match in matches for market in match.markets)


@pytest.mark.parametrize("mode", MODES)
def test_schema_drift_drops_the_book_and_contributes_zero_legs(mode):
    capture = _capture(mode)
    capture["bets"][0]["betOutcomes"][0]["price"] = capture["bets"][0][
        "betOutcomes"
    ][0].pop("odd")

    with pytest.raises(ScrapeError) as caught:
        _scrape_with(_envelope(capture["bets"]))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_json_response_is_schema_drift():
    from scrapers.mdshop import MDShopScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(
                url__startswith="https://mdoffer.mdshop.ba/api/offer/getwebevents"
            ).mock(return_value=httpx.Response(200, content=b"<html>not json</html>"))
            with pytest.raises(ScrapeError) as caught:
                await MDShopScraper().scrape()
            return caught.value

    error = asyncio.run(scenario())

    assert error.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_metric_name_is_the_documented_one():
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1

    validate_bets(capture["bets"])

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
