"""SR7-1: full-offer fetches and the market families they add."""

from __future__ import annotations

import asyncio

from scrapers import betole as betole_module
from scrapers import mozzartbet as mozzart_module
from scrapers.betole import _desk_candidate, _fetch_full_offers, _parse_betole_markets
from scrapers.mozzartbet import _parse_markets


def _betole_full_offer() -> dict[str, float]:
    """One event's full-offer odds, shaped like the live by-ids response."""
    return {
        "1": 1.47, "2": 4.1, "3": 6.25,          # 1X2
        "4": 1.97, "5": 2.27, "6": 6.0,          # first-half 1X2
        "7": 1.08, "8": 1.19, "9": 2.47,         # double chance
        "272": 1.9, "273": 1.77,                 # BTTS
        "242": 1.19, "21": 4.1,                  # O/U 1.5
        "24": 1.67, "22": 2.05,                  # O/U 2.5
        "25": 2.8, "219": 1.38,                  # O/U 3.5
        "27": 5.35, "453": 1.11,                 # O/U 4.5
        "223": 11.25, "266": 1.01,               # O/U 5.5
        "284": 1.35,                             # excluded combination
    }


def test_betole_full_offer_emits_every_supported_family():
    markets = _parse_betole_markets(_betole_full_offer(), mode="prematch")

    emitted = {market.market_type.value for market in markets}
    assert emitted == {
        "1x2",
        "double_chance",
        "btts",
        "first_half_1x2",
        "over_under_1_5",
        "over_under_2_5",
        "over_under_3_5",
        "over_under_4_5",
        "over_under_5_5",
    }
    totals = {m.market_type.value: m for m in markets}
    assert {o.label for o in totals["over_under_4_5"].odds} == {
        "Over 4.5",
        "Under 4.5",
    }
    assert {o.label for o in totals["over_under_5_5"].odds} == {
        "Over 5.5",
        "Under 5.5",
    }


def test_betole_keeps_the_desk_odds_when_a_leg_is_missing():
    partial = {"1": 2.0, "2": 3.4, "3": 3.6, "24": 1.9, "22": 2.1, "272": 1.8, "273": 2.0}

    emitted = {m.market_type.value for m in _parse_betole_markets(partial, "prematch")}

    # No double chance, no 1.5/3.5/4.5/5.5: the market needs both legs.
    assert emitted == {"1x2", "btts", "over_under_2_5"}


def test_betole_fetches_full_offers_in_batches(monkeypatch):
    calls: list[dict] = []

    class Response:
        def __init__(self, rows):
            self._rows = rows

        def json(self):
            return self._rows

    async def fake_fetch(client, url, headers=None, params=None):
        calls.append(params)
        ids = params["matchIdsToken"].split(",")
        return Response(
            [{"id": int(mid), "odds": {"1": 2.0, "2": 3.4, "3": 3.6}} for mid in ids]
        )

    monkeypatch.setattr(betole_module, "fetch_with_retry", fake_fetch)
    events = [{"id": 1000 + index} for index in range(45)]

    offers = asyncio.run(_fetch_full_offers(object(), events, live=False))

    assert [len(call["matchIdsToken"].split(",")) for call in calls] == [40, 5]
    assert all(call["annex"] == "0" for call in calls)
    assert set(offers) == {str(1000 + index) for index in range(45)}


def test_a_failed_batch_leaves_those_events_on_their_desk_odds(monkeypatch):
    class Response:
        def json(self):
            return [{"id": 99, "odds": {"1": 2.0}}]

    calls = {"n": 0}

    async def fake_fetch(client, url, headers=None, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("batch down")
        return Response()

    monkeypatch.setattr(betole_module, "fetch_with_retry", fake_fetch)
    events = [{"id": index} for index in range(40)] + [{"id": 99}]

    offers = asyncio.run(_fetch_full_offers(object(), events, live=False))

    # The failed batch's 40 events keep the desk odds; the next batch still runs.
    assert offers == {"99": {"1": 2.0}}
    assert calls["n"] == 2


def _mozzart_row(game_id: int, subgame: str, value: float | None, short: str = "") -> dict:
    names = {1: "Konačan ishod", 2: "Dupla šansa", 3: "Ukupno golova", 4: "Prvo poluvreme",
             130: "Oba tima daju gol", 297: "Dupla šansa prvo poluvreme"}
    return {
        "game": {"id": game_id, "name": names.get(game_id, ""), "shortName": short},
        "subgame": {"name": subgame},
        "value": value,
    }


def test_mozzart_full_offer_emits_first_half_and_every_complete_total():
    rows = [
        _mozzart_row(1, "1", 2.2), _mozzart_row(1, "X", 3.7), _mozzart_row(1, "2", 3.1),
        _mozzart_row(2, "1X", 1.35), _mozzart_row(2, "12", 1.3), _mozzart_row(2, "X2", 1.63),
        _mozzart_row(4, "1", 2.65), _mozzart_row(4, "X", 2.15), _mozzart_row(4, "2", 3.45),
        _mozzart_row(130, "gg", 1.67), _mozzart_row(130, "ng", 2.05),
        _mozzart_row(3, "0-1", 3.6), _mozzart_row(3, "2+", 1.22),
        _mozzart_row(3, "0-2", 2.0), _mozzart_row(3, "3+", 1.7),
        _mozzart_row(3, "0-3", 1.38), _mozzart_row(3, "4+", 2.7),
        _mozzart_row(3, "0-4", 1.1), _mozzart_row(3, "5+", 4.6),
    ]

    markets = _parse_markets({"odds": rows}, mode="prematch")
    emitted = {market.market_type.value for market in markets}

    assert emitted == {
        "1x2",
        "double_chance",
        "btts",
        "first_half_1x2",
        "over_under_1_5",
        "over_under_2_5",
        "over_under_3_5",
        "over_under_4_5",
    }
    ht = next(m for m in markets if m.market_type.value == "first_half_1x2")
    assert {(o.label, o.value) for o in ht.odds} == {("1", 2.65), ("X", 2.15), ("2", 3.45)}


def test_mozzart_does_not_emit_an_incomplete_first_half_market():
    rows = [_mozzart_row(4, "1", 2.65), _mozzart_row(4, "2", 3.45)]

    emitted = {m.market_type.value for m in _parse_markets({"odds": rows}, mode="prematch")}

    assert "first_half_1x2" not in emitted


def test_mozzart_full_offer_failure_keeps_the_list_odds(monkeypatch):
    calls: list[str] = []

    async def fake_retry_call(send, **kwargs):
        calls.append(kwargs.get("label", ""))

        class Boom:
            async def json(self):
                raise RuntimeError("expired session")

        return Boom()

    monkeypatch.setattr(mozzart_module, "retry_call", fake_retry_call)
    monkeypatch.setattr(
        mozzart_module, "measured_api_post", lambda page, url, **kw: url
    )

    async def scenario():
        return await mozzart_module.MozzartbetScraper()._complete_offer(
            object(), 10095288, "prematch"
        )

    assert asyncio.run(scenario()) is None
    assert calls == ["mozzartbet offer 10095288"]


def test_betole_filters_events_before_the_full_offer_fetch():
    prematch = {"home": "A", "away": "B", "live": False, "blocked": False}
    assert _desk_candidate(prematch, live=False) is True
    assert _desk_candidate({**prematch, "live": True}, live=False) is False
    assert _desk_candidate({**prematch, "blocked": True}, live=False) is False
    assert _desk_candidate({**prematch, "home": " "}, live=False) is False
    assert _desk_candidate({"live": True, "home": "A", "away": "B"}, live=True) is True
