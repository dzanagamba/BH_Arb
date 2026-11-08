"""SR4-3i: strict wire schemas, WWin eighth.

WHAT THESE TESTS PROVE
----------------------
WWIN's dated fixtures freeze the ``bets[]`` array the parser reads (``idBt``,
``spec``, ``odds[]`` with ``t``/``va``/``isv``), so that array is what the
schema types. The same row arrives in three envelopes:

* prematch ``{"p": [...]}`` / ``{"events": [...]}``,
* live ``{"events": [...]}``,
* live ``headerBets`` ``{"bets": [{"<eventId>": bet}]}``.

``tests/fixtures/markets/wwin_{prematch,live}.json`` pass the strict schema.
A string price, a renamed price field, a bet without its ``spec`` and a missing
page key are ``schema_drift``: the real ``scrape()`` raises ``ScrapeError`` and
contributes no legs. An integer price is accepted, and unknown bet/odd keys are
counted in ``bh_wire_unknown_keys_total`` and still scraped.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The event shell (teams, kickoff, competition) has no dated capture and stays
unmodelled: its keys are neither rejected nor counted. A renamed team field
still drops that event silently; SR4-4/SR5-1 own the structural drift alarm.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import scrapers.wwin as wwin_module
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.wire_schemas import (
    METRIC_UNKNOWN_KEYS,
    validate_wwin_bets,
    validate_wwin_events,
    validate_wwin_header_bets,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
MODES = ("prematch", "live")
SCAN_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
EVENT_ID = "4680901"
PREMATCH_EVENT_ID = 4679952


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"wwin_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _prematch_event(bets: Any) -> dict[str, Any]:
    return {
        "id": PREMATCH_EVENT_ID,
        "hname": "Home FC",
        "aname": "Away FC",
        "tname": "Test League",
        "cname": "Testland",
        "startTime": int(SCAN_TIME.timestamp()) + 86_400,
        "brid": 12345,
        "bets": bets,
    }


def _live_events(bets: Any) -> dict[str, Any]:
    return {
        "categories": [{"id": 1, "cname": "Testland"}],
        "events": [
            {
                "ids": 2,
                "idEvent": EVENT_ID,
                "hname": "Home FC",
                "aname": "Away FC",
                "tname": "Test League",
                "startTime": int(SCAN_TIME.timestamp()),
                "brid": 12345,
                "bets": bets,
            },
            {"ids": 1, "idEvent": "other-sport"},
        ],
    }


def _header_bets(bets: Any) -> dict[str, Any]:
    return {"bets": [{EVENT_ID: bet} for bet in bets]}


def _prematch_tfrom0() -> str:
    day_start = SCAN_TIME.replace(hour=0, minute=0, second=0, microsecond=0)
    return str(int((day_start - timedelta(hours=1)).timestamp()))


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


def _scrape(monkeypatch, *, live: bool, payload: Any, header: Any = None):
    """Run the real ``scrape()`` against a fake browser and the given payloads."""
    response = _FakeResponse(payload)
    header_response = _FakeResponse(header)

    async def fake_launch_browser():
        return _FakePlaywright(), _FakeBrowser(), _FakeContext()

    async def fake_goto(page, url, **kwargs):
        return None

    async def fake_settle(page, max_ms):
        return None

    async def fake_retry_call(send, **kwargs):
        return await send()

    async def fake_measured_api_get(page, url, **kwargs):
        if live and url.endswith("/LiveEvents/headerBets"):
            return header_response
        if not live and kwargs.get("params", {}).get("tfrom") != _prematch_tfrom0():
            return _FakeResponse({"p": []})
        return response

    monkeypatch.setattr(wwin_module, "launch_browser", fake_launch_browser)
    monkeypatch.setattr(wwin_module, "goto", fake_goto)
    monkeypatch.setattr(wwin_module, "settle", fake_settle)
    monkeypatch.setattr(wwin_module, "retry_call", fake_retry_call)
    monkeypatch.setattr(wwin_module, "measured_api_get", fake_measured_api_get)

    async def scenario():
        return await wwin_module.WWINScraper().scrape(live=live, scan_time=SCAN_TIME)

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_wwin_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    bets = validate_wwin_bets(capture["bets"])

    assert len(bets) == len(capture["bets"])
    assert {bet.idBt for bet in bets} == {bet["idBt"] for bet in capture["bets"]}


@pytest.mark.parametrize("mode", MODES)
def test_every_wwin_envelope_accepts_the_captured_rows(mode):
    capture = _capture(mode)

    if mode == "prematch":
        page = {"p": [_prematch_event(capture["bets"])]}
    else:
        page = _live_events(capture["bets"])

    events = validate_wwin_events(page, live=(mode == "live"))
    header = validate_wwin_header_bets(_header_bets(capture["bets"]))

    assert events
    assert len(header) == len(capture["bets"])
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_the_legacy_prematch_events_key_is_accepted():
    capture = _capture()
    page = {"events": [_prematch_event(capture["bets"])]}

    events = validate_wwin_events(page)

    assert events[0]["id"] == PREMATCH_EVENT_ID


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"][0]["odds"][0]["va"] = "8.0"

    with pytest.raises(ScrapeError) as caught:
        validate_wwin_bets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "va" in str(caught.value)


def test_a_renamed_price_field_is_schema_drift():
    capture = _capture()
    odd = capture["bets"][0]["odds"][0]
    odd["price"] = odd.pop("va")

    with pytest.raises(ScrapeError) as caught:
        validate_wwin_bets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "va" in str(caught.value)


def test_a_bet_without_its_spec_is_schema_drift():
    capture = _capture()
    del capture["bets"][0]["spec"]

    with pytest.raises(ScrapeError) as caught:
        validate_wwin_bets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "spec" in str(caught.value)


def test_a_string_bet_id_is_schema_drift():
    capture = _capture()
    capture["bets"][0]["idBt"] = "95"

    with pytest.raises(ScrapeError) as caught:
        validate_wwin_bets(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "idBt" in str(caught.value)


def test_an_integer_price_is_accepted_without_becoming_a_string():
    bets = validate_wwin_bets(
        [{"idBt": 95, "spec": "", "odds": [{"t": "1", "va": 2, "isv": 1}]}]
    )

    assert bets[0].odds[0].va == 2.0


def test_unknown_keys_are_kept_counted_and_logged(caplog):
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1
    capture["bets"][0]["odds"][0]["brandNewOddField"] = "x"

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        bets = validate_wwin_bets(capture["bets"])

    assert len(bets) == len(capture["bets"])
    assert bets[0].model_extra["brandNewBetField"] == 1
    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="wwin",field="brandNewBetField",'
        'level="bet"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="wwin",field="brandNewOddField",'
        'level="odd"} 1' in text
    )
    assert "brandNewBetField" in caplog.text


def test_a_missing_prematch_page_key_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_wwin_events({"categories": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_missing_live_events_key_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_wwin_events({"p": []}, live=True)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_object_page_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_wwin_events([{"id": 1}])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_object_event_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_wwin_events({"p": ["not-an-event"]})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_header_bets_page_without_bets_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_wwin_header_bets({"rows": []})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_header_bets_item_that_is_not_an_event_map_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_wwin_header_bets({"bets": ["not-a-map"]})

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


@pytest.mark.parametrize("mode", MODES)
def test_the_real_scrape_emits_the_families_the_capture_declares(mode, monkeypatch):
    capture = _capture(mode)

    if mode == "prematch":
        matches = _scrape(
            monkeypatch, live=False, payload={"p": [_prematch_event(capture["bets"])]}
        )
    else:
        matches = _scrape(
            monkeypatch,
            live=True,
            payload=_live_events([]),
            header=_header_bets(capture["bets"]),
        )

    assert [match.bookmaker for match in matches] == ["wwin"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


@pytest.mark.parametrize("mode", MODES)
def test_a_string_price_in_the_real_scrape_drops_the_book(mode, monkeypatch):
    capture = _capture(mode)
    rows = [dict(bet) for bet in capture["bets"]]
    rows[0] = {**rows[0], "odds": [dict(odd) for odd in rows[0]["odds"]]}
    rows[0]["odds"][0]["va"] = "8.0"

    with pytest.raises(ScrapeError) as caught:
        if mode == "prematch":
            _scrape(monkeypatch, live=False, payload={"p": [_prematch_event(rows)]})
        else:
            _scrape(
                monkeypatch,
                live=True,
                payload=_live_events([]),
                header=_header_bets(rows),
            )

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


@pytest.mark.parametrize("mode", MODES)
def test_a_non_json_response_is_drift(mode, monkeypatch):
    with pytest.raises(ScrapeError) as caught:
        if mode == "prematch":
            _scrape(
                monkeypatch,
                live=False,
                payload=json.JSONDecodeError("bad", "", 0),
            )
        else:
            _scrape(
                monkeypatch,
                live=True,
                payload=json.JSONDecodeError("bad", "", 0),
            )

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_an_unknown_root_key_is_counted():
    capture = _capture()
    page = {"p": [_prematch_event(capture["bets"])], "brandNewRootField": 1}

    validate_wwin_events(page)

    assert (
        'bh_wire_unknown_keys_total{book="wwin",field="brandNewRootField",'
        'level="root"} 1' in metrics.render()
    )


def test_the_metric_name_is_the_documented_one():
    capture = _capture()
    capture["bets"][0]["brandNewBetField"] = 1

    validate_wwin_bets(capture["bets"])

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
