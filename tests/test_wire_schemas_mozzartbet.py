"""SR4-3b: strict wire schemas, Mozzartbet second.

WHAT THESE TESTS PROVE
----------------------
Mozzartbet is a Playwright hybrid: the adapter reads the ``betting/matches``
list envelope and one ``betting/match/{id}`` response per event.  Before this
schema a renamed ``value`` or a price served as a string reached the parser,
which produced zero legs and looked like an empty feed.  The raw JSON is now
validated with pydantic ``strict=True`` before any parser sees it.

* Both dated fixtures (prematch and live ``bets``) satisfy the odds schema with
  no unknown keys, inside the offer envelope the adapter requests.
* A renamed price field and a string price are ``schema_drift``: the real
  adapter raises ``ScrapeError`` and contributes no legs.
* An unknown key is kept (``extra="allow"``) and counted in
  ``bh_wire_unknown_keys_total`` and the log, never fatal.
* A per-event error payload keeps that event on its list odds: no match is
  returned, but the book is not dropped.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The list *item* shell (teams, kickoff, competition) has no dated capture, so it
is not modelled and its keys are neither rejected nor counted.  A renamed team
field still drops that event silently; SR4-4/SR5-1 own structural drift alarm
and per-book health.  ``docs/WIRE_SCHEMAS.md`` records the gap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from models.schemas import MarketType
from scrapers import mozzartbet as mozzart_module
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.wire_schemas import (
    METRIC_UNKNOWN_KEYS,
    validate_mozzart_odds,
    validate_mozzart_offer,
    validate_mozzart_page,
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
    path = FIXTURE_DIR / f"mozzartbet_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _offer(rows: Any) -> dict[str, Any]:
    """The captured odds array inside the per-event envelope."""
    return {"match": {"odds": rows}}


def _row(game_id: int, subgame: str, value: float | None, name: str = "Test") -> dict:
    return {
        "game": {"id": game_id, "name": name, "shortName": ""},
        "subgame": {"name": subgame},
        "value": value,
    }


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def json(self) -> Any:
        return self._payload


def _with_offer(monkeypatch, payload: Any):
    """Run the real ``_complete_offer`` against a fake response payload."""

    async def fake_retry_call(send, **kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr(mozzart_module, "retry_call", fake_retry_call)
    monkeypatch.setattr(mozzart_module, "measured_api_post", lambda *a, **k: object())

    async def scenario():
        return await mozzart_module.MozzartbetScraper()._complete_offer(
            object(), 10095288, "prematch"
        )

    return asyncio.run(scenario())


def _with_build(monkeypatch, payload: Any):
    """Run the real ``_build_matches`` with one event and a fake offer payload."""

    async def fake_retry_call(send, **kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr(mozzart_module, "retry_call", fake_retry_call)
    monkeypatch.setattr(mozzart_module, "measured_api_post", lambda *a, **k: object())
    items = [{"id": 10095288, "home": "Home FC", "visitor": "Away FC"}]

    async def scenario():
        return await mozzart_module.MozzartbetScraper()._build_matches(
            object(), items, False, "prematch"
        )

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_mozzartbet_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    rows = validate_mozzart_odds(capture["bets"])
    offer = validate_mozzart_offer(_offer(capture["bets"]))

    assert len(rows) == len(capture["bets"])
    assert offer.match is not None
    assert len(offer.match.odds) == len(capture["bets"])
    assert offer.match.model_dump(exclude={"odds"}) == {}


def test_a_null_value_is_allowed_and_a_number_stays_a_number():
    rows = [
        _row(3, "0-5", None),
        _row(3, "5+", 4.6),
    ]

    validated = validate_mozzart_odds(rows)

    assert validated[0].value is None
    assert validated[1].value == 4.6


def test_an_integer_price_is_accepted_without_becoming_a_string():
    rows = [_row(3, "7+", 25)]

    validated = validate_mozzart_odds(rows)

    assert validated[0].value == 25.0


def test_a_renamed_price_field_on_the_list_page_is_schema_drift():
    capture = _capture()
    for row in capture["bets"]:
        if "value" in row:
            row["price"] = row.pop("value")
    page = {"items": [{"id": 10095288, "odds": capture["bets"]}]}

    with pytest.raises(ScrapeError) as caught:
        validate_mozzart_page(page)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "value" in str(caught.value)


def test_a_row_without_a_value_is_accepted_as_unpriced():
    """SR4-10: the live feed omits ``value`` on a suspended pick."""
    row = _row(3, "0-5", None)
    del row["value"]

    validated = validate_mozzart_odds([row])

    assert validated[0].value is None


def test_a_list_page_may_mix_unpriced_and_priced_rows():
    unpriced = _row(3, "0-5", None)
    del unpriced["value"]
    page = {"items": [{"id": 1, "odds": [unpriced, _row(1, "1", 2.2)]}]}

    assert validate_mozzart_page(page).items


def test_a_page_where_no_row_carries_a_price_is_schema_drift():
    unpriced = _row(3, "0-5", None)
    del unpriced["value"]
    page = {
        "items": [
            {"id": 1, "odds": [unpriced]},
            {"id": 2, "odds": [dict(unpriced)]},
        ]
    }

    with pytest.raises(ScrapeError) as caught:
        validate_mozzart_page(page)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "no odds row carries a value" in str(caught.value)


def test_an_unpriced_offer_row_yields_no_leg_and_does_not_drop_the_event(monkeypatch):
    capture = _capture()
    for row in capture["bets"]:
        if (row.get("game") or {}).get("id") == 1:
            row.pop("value", None)

    offer = _with_offer(monkeypatch, _offer(capture["bets"]))
    matches = _with_build(monkeypatch, _offer(capture["bets"]))

    assert offer is not None
    assert matches
    types = {market.market_type for match in matches for market in match.markets}
    assert MarketType.MATCH_RESULT not in types
    assert types


def test_a_string_price_is_never_coerced():
    capture = _capture()
    capture["bets"][0]["value"] = "2.2"

    with pytest.raises(ScrapeError) as caught:
        validate_mozzart_odds(capture["bets"])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "value" in str(caught.value)


def test_an_unknown_key_is_kept_counted_and_logged(caplog):
    capture = _capture()
    capture["bets"][0]["brandNewOddField"] = 1
    capture["bets"][0]["game"]["brandNewGameField"] = "x"
    capture["bets"][0]["subgame"]["brandNewSubgameField"] = "y"

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        rows = validate_mozzart_odds(capture["bets"])

    assert len(rows) == len(capture["bets"])
    assert rows[0].model_extra["brandNewOddField"] == 1
    text = metrics.render()
    assert (
        'bh_wire_unknown_keys_total{book="mozzartbet",field="brandNewOddField",'
        'level="odd"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="mozzartbet",field="brandNewGameField",'
        'level="game"} 1' in text
    )
    assert (
        'bh_wire_unknown_keys_total{book="mozzartbet",field="brandNewSubgameField",'
        'level="subgame"} 1' in text
    )
    assert "brandNewOddField" in caplog.text


def test_unknown_keys_do_not_drop_the_book_from_a_scrape(monkeypatch):
    capture = _capture()
    capture["bets"][0]["brandNewOddField"] = 1

    offer = _with_offer(monkeypatch, _offer(capture["bets"]))
    matches = _with_build(monkeypatch, _offer(capture["bets"]))

    assert offer is not None
    assert len(offer) == len(capture["bets"])
    assert matches
    assert any(market.odds for match in matches for market in match.markets)


def test_the_offer_envelope_is_validated_too():
    payload = {"match": {"odds": "not a list"}}

    with pytest.raises(ScrapeError) as caught:
        validate_mozzart_offer(payload)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "odds" in str(caught.value)


def test_a_per_event_error_payload_keeps_the_list_odds(monkeypatch):
    payload = {"error": "Not found. Sorry."}

    assert _with_offer(monkeypatch, payload) is None
    assert (
        'bh_wire_unknown_keys_total{book="mozzartbet",field="error",level="root"} 1'
        in metrics.render()
    )


def test_a_non_json_offer_body_is_schema_drift(monkeypatch):
    class NotJson:
        async def json(self):
            raise json.JSONDecodeError("Expecting value", "<html>", 0)

    async def fake_retry_call(send, **kwargs):
        return NotJson()

    monkeypatch.setattr(mozzart_module, "retry_call", fake_retry_call)
    monkeypatch.setattr(mozzart_module, "measured_api_post", lambda *a, **k: object())

    async def scenario():
        await mozzart_module.MozzartbetScraper()._complete_offer(
            object(), 10095288, "prematch"
        )

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(scenario())

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


@pytest.mark.parametrize("mode", MODES)
def test_a_string_price_drops_the_book_and_contributes_zero_legs(monkeypatch, mode):
    capture = _capture(mode)
    capture["bets"][0]["value"] = "2.2"

    with pytest.raises(ScrapeError) as caught:
        _with_build(monkeypatch, _offer(capture["bets"]))

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_matches_page_validates_the_envelope_and_every_odds_array():
    capture = _capture()
    payload = {
        "items": [{"id": 10095288, "odds": capture["bets"]}],
        "totalPages": 3,
        "matchCount": 15,
    }

    page = validate_mozzart_page(payload)

    assert page.totalPages == 3
    assert page.items[0]["id"] == 10095288
    assert (
        'bh_wire_unknown_keys_total{book="mozzartbet",field="matchCount",'
        'level="root"} 1' in metrics.render()
    )


def test_a_drifted_page_odds_array_is_schema_drift():
    capture = _capture()
    capture["bets"][0]["value"] = "2.2"
    payload = {"items": [{"id": 10095288, "odds": capture["bets"]}]}

    with pytest.raises(ScrapeError) as caught:
        validate_mozzart_page(payload)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_item_shell_is_not_modelled_yet():
    """A key the item shell carries is neither rejected nor counted."""
    payload = {"items": [{"id": 1, "home": {"name": "A"}, "startTime": 1}]}

    page = validate_mozzart_page(payload)

    assert page.items == payload["items"]
    assert metrics.render().count("bh_wire_unknown_keys_total") == 0


def test_the_metric_name_is_the_documented_one():
    validate_mozzart_odds(
        [_row(1, "1", 2.0, name="Konačan ishod") | {"newField": 1}]
    )

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters
