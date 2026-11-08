"""SR4-3c: strict wire schemas, Admiralbet third.

WHAT THESE TESTS PROVE
----------------------
Admiralbet is a Playwright hybrid that serves the same NSoft ``getwebevents``
envelope as MDShop, so the NSoft models are **reused**, not rewritten.  That is
only allowed because this file pins the reuse against Admiralbet's own dated
captures: both ``bets`` arrays (prematch and live) satisfy the strict schema
with no unknown keys, and the real ``scrape()`` reads them into the market
families each capture declares.

* A renamed price field and a string price are ``schema_drift``: the real
  adapter raises ``ScrapeError`` and contributes no legs.
* An unknown key is kept (``extra="allow"``) and counted in
  ``bh_wire_unknown_keys_total`` and the log, never fatal.
* The adapter's historical bare-list form (no ``{"events": ...}`` envelope) is
  wrapped so the same schema applies to it.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The list *event* shell is validated only through the fields MDShop's capture
proved.  Admiralbet's parser also reads fallback keys (``home``/``guest``,
``dateFrom``/``kickoff``, ``leagueName``) that have no dated capture; if the
live shell carries them they are counted as unknown event keys.  A renamed team
field therefore still drops that event silently; SR4-4/SR5-1 own structural
drift alarm and per-book health.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from scrapers import admiralbet as admiralbet_module
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
    path = FIXTURE_DIR / f"admiralbet_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _event(bets: Any) -> dict[str, Any]:
    """One event shell carrying the captured odds, as the adapter requests it."""
    return {
        "id": 6917979,
        "name": "Home FC - Away FC",
        "dateTime": "2030-01-01T18:00:00",
        "sportId": 1,
        "competitionName": "Test League",
        "regionName": "Test Region",
        "isInOffer": True,
        "bets": bets,
    }


def _envelope(bets: Any) -> dict[str, Any]:
    return {"events": [_event(bets)]}


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def json(self) -> Any:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class _FakeBrowser:
    async def close(self) -> None:
        return None


class _FakePlaywright:
    async def stop(self) -> None:
        return None


class _FakeContext:
    async def new_page(self) -> object:
        return object()


def _scrape_with(monkeypatch, payload: Any, *, live: bool = False):
    """Run the real ``scrape()`` against a fake browser and one payload."""
    response = _FakeResponse(payload)

    async def fake_launch_browser():
        return _FakePlaywright(), _FakeBrowser(), _FakeContext()

    async def fake_goto(page, url, **kwargs):
        return None

    async def fake_settle(page, max_ms):
        return None

    async def fake_retry_call(send, **kwargs):
        return await send()

    async def fake_measured_api_get(page, url, **kwargs):
        return response

    monkeypatch.setattr(admiralbet_module, "launch_browser", fake_launch_browser)
    monkeypatch.setattr(admiralbet_module, "goto", fake_goto)
    monkeypatch.setattr(admiralbet_module, "settle", fake_settle)
    monkeypatch.setattr(admiralbet_module, "retry_call", fake_retry_call)
    monkeypatch.setattr(admiralbet_module, "measured_api_get", fake_measured_api_get)

    async def scenario():
        return await admiralbet_module.AdmiralbetScraper().scrape(live=live)

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_admiralbet_fixture_satisfies_the_shared_nsoft_schema(mode):
    capture = _capture(mode)

    bets = validate_bets(capture["bets"], book="admiralbet")

    assert len(bets) == len(capture["bets"])
    assert unknown_key_counts(_envelope(capture["bets"])) == {}


def test_the_response_envelope_accepts_the_captured_event_shell():
    capture = _capture()

    response = validate_response(_envelope(capture["bets"]), book="admiralbet")

    assert len(response.events) == 1
    assert len(response.events[0].bets) == len(capture["bets"])


def test_a_renamed_price_field_is_schema_drift():
    capture = _capture()
    outcome = capture["bets"][0]["betOutcomes"][0]
    outcome["price"] = outcome.pop("odd")

    with pytest.raises(ScrapeError) as caught:
        validate_bets(capture["bets"], book="admiralbet")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "odd" in str(caught.value)


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"][0]["betOutcomes"][0]["odd"] = "2.81"

    with pytest.raises(ScrapeError) as caught:
        validate_bets(capture["bets"], book="admiralbet")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "odd" in str(caught.value)


def test_an_integer_price_is_accepted_without_becoming_a_string():
    capture = _capture()
    capture["bets"][0]["betOutcomes"][0]["odd"] = 2

    bets = validate_bets(capture["bets"], book="admiralbet")

    assert bets[0].betOutcomes[0].odd == 2.0


def test_unknown_keys_are_kept_counted_and_logged_for_admiralbet(caplog):
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1
    capture["bets"][0]["betOutcomes"][0]["brandNewOutcomeField"] = "x"

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        bets = validate_bets(capture["bets"], book="admiralbet")

    assert len(bets) == len(capture["bets"])
    assert bets[0].model_extra["brandNewBetField"] == 1
    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="admiralbet",field="brandNewBetField",'
        'level="bet"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="admiralbet",field="brandNewOutcomeField",'
        'level="outcome"} 1' in text
    )
    assert "brandNewBetField" in caplog.text


@pytest.mark.parametrize("mode", MODES)
def test_the_real_scrape_emits_the_families_the_capture_declares(monkeypatch, mode):
    capture = _capture(mode)

    matches = _scrape_with(
        monkeypatch, _envelope(capture["bets"]), live=(mode == "live")
    )

    assert [match.bookmaker for match in matches] == ["admiralbet"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_unknown_keys_do_not_drop_the_book_from_a_scrape(monkeypatch):
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1

    matches = _scrape_with(monkeypatch, _envelope(capture["bets"]))

    assert matches
    assert any(market.odds for match in matches for market in match.markets)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("rename", [True, False])
def test_schema_drift_drops_the_book_and_contributes_zero_legs(
    monkeypatch, mode, rename
):
    capture = _capture(mode)
    outcome = capture["bets"][0]["betOutcomes"][0]
    if rename:
        outcome["price"] = outcome.pop("odd")
    else:
        outcome["odd"] = "2.81"

    with pytest.raises(ScrapeError) as caught:
        _scrape_with(monkeypatch, _envelope(capture["bets"]), live=(mode == "live"))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_json_response_is_schema_drift(monkeypatch):
    payload = json.JSONDecodeError("Expecting value", "<html>", 0)

    with pytest.raises(ScrapeError) as caught:
        _scrape_with(monkeypatch, payload)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_bare_list_form_gets_the_same_schema(monkeypatch):
    capture = _capture()

    matches = _scrape_with(monkeypatch, [_event(capture["bets"])])

    assert matches
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_a_drifted_bare_list_is_schema_drift(monkeypatch):
    capture = _capture()
    capture["bets"][0]["betOutcomes"][0]["odd"] = "2.81"

    with pytest.raises(ScrapeError) as caught:
        _scrape_with(monkeypatch, [_event(capture["bets"])])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_metric_name_is_the_documented_one():
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1

    validate_bets(capture["bets"], book="admiralbet")

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
