"""SR4-3h: strict wire schemas, Premier Kladionica seventh.

WHAT THESE TESTS PROVE
----------------------
Premier Kladionica's PrSync is positional: the response is ``[sections]``, each
section a list of rows, and a column's meaning is its index.  The dated
fixtures freeze two of those tables — the dogTipK odds rows (``bets``) and the
setTip/setTipVar/setTipTip definition rows (``lookup``) — so those are what the
schema types and what the real ``scrape()`` is driven with.

* Both fixtures' odds rows pass the strict schema with every column type right.
* A string price, a truncated row (the price column gone), a non-string line
  specifier and a non-string outcome code are ``schema_drift``: the real
  ``scrape()`` raises ``ScrapeError`` and contributes no legs.
* A section slot past the fifteen the parser documents is counted in
  ``bh_wire_unknown_keys_total`` (positional data has no field names to count).

WHAT THESE TESTS DO NOT PROVE
-----------------------------
The event, sports, competition-group and execRes sections have no dated capture
and stay unmodelled; their keys are neither checked nor counted.  A renamed
team column still drops that event silently; SR4-4/SR5-1 own the structural
drift alarm.
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
    validate_premier_lookup,
    validate_premier_odds,
    validate_premier_sync,
)
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
WIRE_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "wire"
SYNC_URL = "https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx"
MODES = ("prematch", "live")
FUTURE_MS = 1_900_000_000_000
PAST_MS = 1_000_000


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"premier_kladionica_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _delta_capture() -> dict[str, Any]:
    path = WIRE_FIXTURE_DIR / "premier_kladionica_delta.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _full_sync(capture: dict[str, Any], *, live: bool = False) -> list:
    """A 15-slot full-sync `sections` list around the capture's lookup rows."""
    sections: list = [None] * 15
    dog_id = capture["bets"][0][0]
    kickoff = PAST_MS if live else FUTURE_MS
    sections[0] = [[0, 0, 0, 0, 1304349777]]
    sections[2] = [[2, 0, "Fudbal"]]
    sections[3] = [[10, 0, 2, 0, 0, "Test League"]]
    sections[5] = [
        [
            dog_id,
            10,
            0,
            0,
            0,
            0,
            "",
            "Home FC",
            "Away FC",
            0,  # not blocked
            1,  # on offer
            None,
            None,
            kickoff,
            0,
        ]
    ]
    sections[7] = capture["lookup"]["set_tip"]
    sections[8] = capture["lookup"]["set_tip_var"]
    sections[9] = capture["lookup"]["set_tip_tip"]
    return sections


def _delta_sync(capture: dict[str, Any], rows: Any = None) -> list:
    # The live delta response is five sections and omits the empty ones; the
    # odds (dogTipK) table is third. SR4-13: its index is not identification.
    sections: list = [None] * 5
    sections[0] = [[0, "", 1_794_139_866_830, 4, 1_308_505_019]]
    sections[2] = capture["bets"] if rows is None else rows
    return sections


def _scrape(
    capture: dict[str, Any],
    *,
    live: bool = False,
    full: list | None = None,
    rows: Any = None,
    raw: bytes | None = None,
):
    """Run the real ``scrape()`` against a mocked PrSync endpoint."""
    from scrapers.premier_kladionica import PremierKladionicaScraper

    full_sections = full if full is not None else _full_sync(capture, live=live)
    delta_sections = _delta_sync(capture, rows)

    def side_effect(request: httpx.Request) -> httpx.Response:
        if raw is not None:
            return httpx.Response(200, content=raw)
        payload = json.loads(request.content)[0][2]
        sections = (
            full_sections if payload.get("dogadjajIDs") == "" else delta_sections
        )
        return httpx.Response(200, json=[sections])

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.post(SYNC_URL).mock(side_effect=side_effect)
            return await PremierKladionicaScraper().scrape(live=live)

    return asyncio.run(scenario())


@pytest.mark.parametrize("mode", MODES)
def test_every_premier_fixture_satisfies_the_strict_schema(mode):
    capture = _capture(mode)

    odds = validate_premier_odds(capture["bets"])
    set_tip, set_tip_var, set_tip_tip = validate_premier_lookup(**capture["lookup"])

    assert len(odds) == len(capture["bets"])
    assert len(set_tip) == len(capture["lookup"]["set_tip"])
    assert len(set_tip_var) == len(capture["lookup"]["set_tip_var"])
    assert len(set_tip_tip) == len(capture["lookup"]["set_tip_tip"])


@pytest.mark.parametrize("mode", MODES)
def test_the_envelopes_accept_the_captured_tables(mode):
    capture = _capture(mode)

    full = validate_premier_sync([_full_sync(capture, live=(mode == "live"))], kind="full")
    delta = validate_premier_sync([_delta_sync(capture)], kind="delta")

    assert len(full) == 15
    assert delta[2] == capture["bets"]
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_a_string_price_is_never_coerced():
    rows = [row[:] for row in _capture()["bets"]]
    rows[0][5] = "3.55"

    with pytest.raises(ScrapeError) as caught:
        validate_premier_odds(rows)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_truncated_row_loses_the_price_column_and_is_drift():
    rows = [row[:] for row in _capture()["bets"]]
    rows[0] = rows[0][:8]  # the price (column 5) and later columns are gone

    with pytest.raises(ScrapeError) as caught:
        validate_premier_odds(rows)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "8" in str(caught.value)


def test_an_integer_price_is_accepted_without_becoming_a_string():
    odds = validate_premier_odds([[1, 2, 3, 4, 5, 2, 1, 0, 0]])

    assert odds[0].koef == 2.0


def test_a_non_string_line_specifier_is_drift():
    capture = _capture()
    set_tip_var = [row[:] for row in capture["lookup"]["set_tip_var"]]
    set_tip_var[0][9] = 2.5

    with pytest.raises(ScrapeError) as caught:
        validate_premier_lookup(
            capture["lookup"]["set_tip"], set_tip_var, capture["lookup"]["set_tip_tip"]
        )

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_string_outcome_code_is_drift():
    capture = _capture()
    set_tip_tip = [row[:] for row in capture["lookup"]["set_tip_tip"]]
    set_tip_tip[0][4] = 1

    with pytest.raises(ScrapeError) as caught:
        validate_premier_lookup(
            capture["lookup"]["set_tip"],
            capture["lookup"]["set_tip_var"],
            set_tip_tip,
        )

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_short_set_tip_row_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_premier_lookup([["2", 1440]], [], [])

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_an_unknown_section_slot_is_counted_and_logged(caplog):
    capture = _capture()
    sections = _full_sync(capture)
    sections.append([])  # slot 15, past the fifteen the parser documents

    with caplog.at_level(logging.INFO, logger="scrapers.wire_schemas"):
        validate_premier_sync([sections], kind="full")

    assert (
        'bh_wire_unknown_keys_total{book="premier_kladionica",field="15",'
        'level="section"} 1' in metrics.render()
    )
    assert "section.15" in caplog.text


def test_a_full_sync_with_too_few_sections_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_premier_sync([[]], kind="full")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "sections" in str(caught.value)


def test_a_non_sections_envelope_is_drift():
    with pytest.raises(ScrapeError) as caught:
        validate_premier_sync({"sections": []}, kind="full")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


@pytest.mark.parametrize("mode", MODES)
def test_the_real_scrape_emits_the_families_the_capture_declares(mode):
    capture = _capture(mode)

    matches = _scrape(capture, live=(mode == "live"))

    assert [match.bookmaker for match in matches] == ["premier_kladionica"]
    emitted = {market.market_type.value for market in matches[0].markets}
    assert emitted == set(capture["expected_markets"])


@pytest.mark.parametrize("mode", MODES)
def test_a_string_price_in_the_delta_drops_the_book_and_yields_no_legs(mode):
    capture = _capture(mode)
    rows = [row[:] for row in capture["bets"]]
    rows[0][5] = "3.55"

    with pytest.raises(ScrapeError) as caught:
        _scrape(capture, live=(mode == "live"), rows=rows)

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_a_non_json_sync_response_is_drift():
    with pytest.raises(ScrapeError) as caught:
        _scrape(_capture(), raw=b"<html>not json</html>")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_the_metric_name_is_the_documented_one():
    capture = _capture()
    sections = _full_sync(capture)
    sections.append([])

    validate_premier_sync([sections], kind="full")

    counters, _gauges = metrics.snapshot()
    assert METRIC_UNKNOWN_KEYS in counters


# ─── SR4-13: the delta envelope's control and auxiliary sections ────────────


def test_the_real_delta_envelope_validates_with_its_control_sections():
    sections = _delta_capture()["sections"]

    validated = validate_premier_sync([sections], kind="delta")

    assert len(validated) == 5
    # execRes (5 columns), dogVar (14), odds (9), dogLiveScore (43), scalars.
    assert validated[0] == [[0, "", 1_794_139_866_830, 4, 1_308_505_019]]
    assert validated[2][0][5] == 1.0
    assert "bh_wire_unknown_keys_total" not in metrics.render()


def test_the_five_column_execres_row_is_not_validated_as_odds():
    """The exact row that dropped the book in the 2026-11-08 baseline."""
    row = [0, "", 1_794_138_522_410, 4, 1_308_500_813]

    sections = validate_premier_sync([[[row]]], kind="delta")

    assert sections == [[row]]


def test_a_truncated_row_in_a_recognised_odds_section_still_drifts():
    rows = [row[:] for row in _capture()["bets"]]
    valid = next(row for row in rows if len(row) == 9)
    truncated = valid[:5]  # price and result columns gone

    with pytest.raises(ScrapeError) as caught:
        validate_premier_sync([[[valid, truncated]]], kind="delta")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "5 columns" in str(caught.value)


def test_a_mistyped_price_in_a_recognised_odds_section_still_drifts():
    row = [4_490_799, 2, 1546, 1, 1, 2.05, 1, 0, 0]
    bad = row[:]
    bad[5] = "2.05"

    with pytest.raises(ScrapeError) as caught:
        validate_premier_sync([[[row, bad]]], kind="delta")

    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT


def test_an_auxiliary_section_alone_is_left_unmodelled():
    dog_var = [3_841_952, 2, 2338, 1, 0, 0, "", "", "", "", "X", None, None, 49]

    sections = validate_premier_sync([[[dog_var]]], kind="delta")

    assert sections == [[dog_var]]
