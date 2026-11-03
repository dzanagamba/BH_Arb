"""Betole's event adapter keeps the kickoff and the Betradar match id."""

from __future__ import annotations

from scrapers.betole import _event_to_match


def _event(**overrides):
    event = {
        "id": 91356290,
        "matchCode": 36049,
        "home": "Toyama",
        "away": "Vegalta Sendai",
        "leagueName": "Japan, J2 League",
        "kickOffTime": 1793681700000,
        "brMatchId": 72151316,
        "live": False,
        "blocked": False,
        "odds": {
            "1": 2.0,
            "2": 3.4,
            "3": 3.6,
            "4": 2.1,
            "5": 3.2,
            "6": 3.3,
            "22": 1.9,
            "24": 1.9,
            "272": 1.8,
            "273": 2.0,
        },
    }
    event.update(overrides)
    return event


def test_the_event_adapter_keeps_kickoff_and_betradar_id():
    match = _event_to_match(_event(), live=False)
    assert match is not None
    assert match.bookmaker == "betole"
    assert match.home_team == "Toyama"
    assert match.kickoff is not None
    assert match.betradar_id == "72151316"
    assert {market.market_type.value for market in match.markets} >= {
        "1x2",
        "over_under_2_5",
        "btts",
        "first_half_1x2",
    }


def test_a_live_event_is_not_returned_as_prematch():
    assert _event_to_match(_event(live=True), live=False) is None


def test_a_blocked_event_is_not_returned():
    assert _event_to_match(_event(blocked=True), live=False) is None
