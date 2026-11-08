"""SR4-3e: strict wire schemas, MBet fifth.

WHAT THESE TESTS PROVE
----------------------
MBet is plain HTTP on the Alea platform.  Its envelope is
``{"events": [...]}``, but an event's ``odds`` is a map whose keys are oddtype
keys (data, like Betole's pick codes) and whose values are either a typed entry
object or a bare number.  The raw JSON is validated before the parser sees it.

* Both dated fixtures (prematch and live) satisfy the entry schema with no
  unknown keys.
* A renamed ``value`` and a string price are ``schema_drift``: the real
  ``scrape()`` raises ``ScrapeError`` and contributes no legs.
* An unknown key is kept (``extra="allow"``) and counted in
  ``bh_wire_unknown_keys_total`` and the log, never fatal.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The event *shell* (sport id, competitors, kickoff, tournament) has no dated
capture, so it stays unmodelled: its keys are neither rejected nor counted.  A
renamed team field still drops that event silently; SR4-4/SR5-1 own the
structural drift alarm.  The oddtype keys inside the odds map are data, not an
allow-list, so an unknown key is not a wire-drift signal
(``record_unmapped`` already tracks the families the parser cannot price).
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
    validate_mbet_odds,
    validate_mbet_response,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
API_PREFIX = "https://api.mbet.ba/events_cached"
MODES = ("prematch", "live")


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"mbet_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _event(odds: Any) -> dict[str, Any]:
    return {
        "id": "e:fb:test:0000",
        "id_sport": "fb",
        "competitors": [{"name": "Home FC"}, {"name": "Away FC"}],
        "utc_scheduled": "2030-01-01T18:00:00Z",
        "tournament": {"name": "Test League"},
        "odds": odds,
    }


def _entry(key: str, value: Any) -> dict[str, Any]:
    return {
        "value": value,
        "market_key": ":".join(key.split(":")[:2]),
        "oddtype_key": key,
        "market_status": "ACTIVE",
        "oddtype_status": 1,
    }


def _scrape(events: Any = None, *, live: bool = False, raw: bytes | None = None):
    """Run the real ``scrape()`` against a mocked ``events_cached`` endpoint."""
    from scrapers.mbet import MBetScraper

    def side_effect(request: httpx.Request) -> httpx.Response:
        if raw is not None:
            return httpx.Response(200, content=raw)
        if request.url.params.get("offset") == "0":
            return httpx.Response(200, json={"events": events})
        return httpx.Response(200, json={"events": []})

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(url__startswith=API_PREFIX).mock(side_effect=side_effect)
            return await MBetScraper().scrape(live=live)

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_mbet_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    odds = validate_mbet_odds(capture["bets"])

    assert len(odds) == len(capture["bets"])
    assert all(not isinstance(entry, float) for entry in odds.values())
    response = validate_mbet_response({"events": [_event(capture["bets"])]})
    assert len(response.events) == 1


def test_a_renamed_value_field_is_schema_drift():
    capture = _capture()
    entry = capture["bets"]["ofb:fs:1"]
    entry["price"] = entry.pop("value")

    with pytest.raises(ScrapeError) as caught:
        validate_mbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "value" in str(caught.value)


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"]["ofb:fs:1"]["value"] = "5"

    with pytest.raises(ScrapeError) as caught:
        validate_mbet_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_an_integer_price_is_accepted_without_becoming_a_string():
    odds = validate_mbet_odds({"ofb:fs:1": _entry("ofb:fs:1", 5)})

    entry = odds["ofb:fs:1"]
    assert not isinstance(entry, float)
    assert entry.value == 5.0


def test_a_bare_number_entry_is_accepted():
    """The parser reads a scalar entry as the price; the schema keeps that."""
    odds = validate_mbet_odds({"ofb:fs:1": 5, "ofb:fs:2": 1.33, "ofb:fs:X": None})

    assert odds == {"ofb:fs:1": 5.0, "ofb:fs:2": 1.33, "ofb:fs:X": None}


def test_a_null_value_is_allowed():
    odds = validate_mbet_odds({"ofb:fs:1": _entry("ofb:fs:1", None)})

    entry = odds["ofb:fs:1"]
    assert not isinstance(entry, float)
    assert entry.value is None


def test_unknown_keys_are_kept_counted_and_logged(caplog):
    capture = _capture()
    capture["bets"]["ofb:fs:1"]["brandNewOddField"] = 1
    payload = {"events": [_event(capture["bets"])], "brandNewRootField": True}

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        validate_mbet_response(payload)

    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="mbet",field="brandNewOddField",'
        'level="odd"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="mbet",field="brandNewRootField",'
        'level="root"} 1' in text
    )
    assert "brandNewOddField" in caplog.text


@pytest.mark.parametrize("mode", MODES)
def test_the_real_scrape_emits_the_families_the_capture_declares(mode):
    capture = _capture(mode)

    matches = _scrape([_event(capture["bets"])], live=(mode == "live"))

    assert [match.bookmaker for match in matches] == ["mbet"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


def test_unknown_keys_do_not_drop_the_book_from_a_scrape():
    capture = _capture()
    capture["bets"]["ofb:fs:1"]["brandNewOddField"] = 1

    matches = _scrape([_event(capture["bets"])])

    assert matches
    assert (
        'bh_wire_unknown_keys_total{book="mbet",field="brandNewOddField",'
        'level="odd"} 1' in metrics.render()
    )


@pytest.mark.parametrize("mode", MODES)
def test_schema_drift_drops_the_book_and_contributes_zero_legs(mode):
    capture = _capture(mode)
    key = "ofb:fs:1" if mode == "prematch" else "lfb:ft:1"
    capture["bets"][key]["value"] = "5"

    with pytest.raises(ScrapeError) as caught:
        _scrape([_event(capture["bets"])], live=(mode == "live"))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_renamed_events_key_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_mbet_response({"items": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "events" in str(caught.value)


def test_a_non_json_page_is_schema_drift():
    with pytest.raises(ScrapeError) as caught:
        _scrape(raw=b"<html>not json</html>")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_metric_name_is_the_documented_one():
    validate_mbet_odds({"ofb:fs:1": {**_entry("ofb:fs:1", 5), "brandNew": 1}})

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
