"""SR4-3j: strict wire schemas, MaxBet ninth (the last follow-up row).

WHAT THESE TESTS PROVE
----------------------
MaxBet (Singular sportsbook) is plain HTTP and its matches response is a bare
``[event, ...]`` list.  The dated fixtures freeze one match's ``odds[]`` array,
where a market block is ``id``/``name``/``specifiers``/``outcomes`` and an
outcome is ``outcome``/``outcomeId``/``status``/``oddValue``/
``marketAvailableForBetting``.

* Both dated fixtures satisfy the odds schema with no unknown keys.
* A renamed price field, a string price and a missing outcome id are
  ``schema_drift``: the real ``scrape()`` raises ``ScrapeError`` and contributes
  no legs.
* An unknown market/outcome/specifier key is kept (``extra="allow"``) and
  counted in ``bh_wire_unknown_keys_total`` and the log, never fatal.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The event *shell* (teams, kickoff, league, status, external ids) has no dated
capture, so it stays unmodelled: its keys are neither rejected nor counted.  A
renamed team field still drops that event silently; SR4-4/SR5-1 own the
structural drift alarm.  ``specifiers`` is absent on line-less markets, so a
renamed specifier on a totals market degrades to "no line" rather than drift.
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
    validate_maxbet_events,
    validate_maxbet_odds,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
MATCHES_URL = "https://sportsbook.maxbet.ba/sportsbook/rest/v2/matches"
MODES = ("prematch", "live")


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"maxbet_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _matches_page(bets: Any, *, live: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "id": 985993,
            "eventType": "Match",
            "antepost": False,
            "sportId": 1,
            "status": 3 if live else 1,
            "name": "Home FC v Away FC",
            "startDate": "2030-01-01T18:00:00",
            "leagueName": "Test League",
            "categoryName": "",
            "odds": bets,
            "externalIds": {},
        }
    ]


def _scrape(payload: Any, *, live: bool = False, raw: bytes | None = None):
    """Run the real ``scrape()`` against a mocked MaxBet endpoint."""
    from scrapers.maxbet import MaxBetScraper

    response = (
        httpx.Response(200, content=raw)
        if raw is not None
        else httpx.Response(200, json=payload)
    )

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(url__startswith=MATCHES_URL).mock(return_value=response)
            return await MaxBetScraper().scrape(live=live)

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_maxbet_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    markets = validate_maxbet_odds(capture["bets"])

    assert len(markets) == len(capture["bets"])
    assert {market.id for market in markets} == {bet["id"] for bet in capture["bets"]}


@pytest.mark.parametrize("mode", MODES)
def test_the_matches_envelope_accepts_the_captured_odds(mode):
    capture = _capture(mode)

    events = validate_maxbet_events(_matches_page(capture["bets"], live=(mode == "live")))

    assert len(events) == 1
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_a_renamed_price_field_is_schema_drift():
    capture = _capture()
    outcome = capture["bets"][0]["outcomes"][0]
    outcome["price"] = outcome.pop("oddValue")

    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "oddValue" in str(caught.value)


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"][0]["outcomes"][0]["oddValue"] = "4.0"

    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "oddValue" in str(caught.value)


def test_a_null_price_is_accepted_because_the_parser_already_drops_it():
    capture = _capture()
    capture["bets"][0]["outcomes"][0]["oddValue"] = None

    markets = validate_maxbet_odds(capture["bets"])

    assert markets[0].outcomes[0].oddValue is None


def test_a_missing_outcome_id_is_schema_drift():
    capture = _capture()
    del capture["bets"][0]["outcomes"][0]["outcomeId"]

    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "outcomeId" in str(caught.value)


def test_a_string_status_is_schema_drift():
    capture = _capture()
    capture["bets"][0]["outcomes"][0]["status"] = "0"

    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "status" in str(caught.value)


def test_a_string_market_id_is_schema_drift():
    capture = _capture()
    capture["bets"][0]["id"] = "17"

    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "id" in str(caught.value)


def test_an_integer_price_is_accepted_without_becoming_a_string():
    markets = validate_maxbet_odds(
        [
            {
                "id": 1,
                "name": "Konačan ishod",
                "outcomes": [
                    {
                        "outcome": "1",
                        "outcomeId": "1001",
                        "status": 0,
                        "oddValue": 2,
                        "marketAvailableForBetting": True,
                    }
                ],
            }
        ]
    )

    assert markets[0].outcomes[0].oddValue == 2.0


def test_unknown_keys_are_kept_counted_and_logged(caplog):
    capture = _capture()
    capture["bets"][0]["brandNewMarketField"] = 1
    capture["bets"][0]["outcomes"][0]["brandNewOutcomeField"] = "x"
    capture["bets"][0]["specifiers"]["brandNewSpecifierField"] = "y"

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        markets = validate_maxbet_odds(capture["bets"])

    assert len(markets) == len(capture["bets"])
    assert markets[0].model_extra["brandNewMarketField"] == 1
    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="maxbet",field="brandNewMarketField",'
        'level="market"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="maxbet",field="brandNewOutcomeField",'
        'level="outcome"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="maxbet",field="brandNewSpecifierField",'
        'level="specifiers"} 1' in text
    )
    assert "brandNewMarketField" in caplog.text


def test_a_non_list_matches_response_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_events({"events": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_object_event_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_maxbet_events(["not-an-event"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_an_event_without_odds_is_allowed_as_an_empty_match():
    events = validate_maxbet_events([{"id": 1}])

    assert events == [{"id": 1}]


@pytest.mark.parametrize("mode", MODES)
def test_the_real_scrape_emits_the_families_the_capture_declares(mode):
    capture = _capture(mode)

    matches = _scrape(_matches_page(capture["bets"], live=(mode == "live")), live=(mode == "live"))

    assert [match.bookmaker for match in matches] == ["maxbet"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


@pytest.mark.parametrize("mode", MODES)
def test_a_string_price_in_the_real_scrape_drops_the_book(mode):
    capture = _capture(mode)
    bets = json.loads(json.dumps(capture["bets"]))
    bets[0]["outcomes"][0]["oddValue"] = "4.0"

    with pytest.raises(ScrapeError) as caught:
        _scrape(_matches_page(bets, live=(mode == "live")), live=(mode == "live"))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_list_body_in_the_real_scrape_is_drift():
    with pytest.raises(ScrapeError) as caught:
        _scrape({"events": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_json_body_in_the_real_scrape_is_drift():
    with pytest.raises(ScrapeError) as caught:
        _scrape(None, raw=b"<html>not json</html>")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_metric_name_is_the_documented_one():
    capture = _capture()
    capture["bets"][0]["brandNewMarketField"] = 1

    validate_maxbet_odds(capture["bets"])

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
