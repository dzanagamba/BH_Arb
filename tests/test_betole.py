"""Tests for the Betole ExeFeed reference-based payload resolver."""

import asyncio

from scrapers.betole import BetoleScraper, _resolve_exefeed_events


def _nsoft_bets():
    return [{
        "betTypeId": 135,
        "betOutcomes": [
            {"name": "1", "odd": 2.10},
            {"name": "X", "odd": 3.20},
            {"name": "2", "odd": 3.50},
        ],
    }]


def test_exefeed_reference_resolution():
    """betPages[] references must resolve through the betMap lookup table."""
    payload = {
        "betPages": [
            {"items": [{"eventId": "E1"}, {"eventId": "E2"}]}
        ],
        "betMap": {
            "E1": {"name": "Sarajevo - Zeljeznicar", "dateTime": "2026-08-15T18:00:00", "bets": _nsoft_bets()},
            "E2": {"name": "Borac BL - Sloboda", "dateTime": "2026-08-15T19:00:00", "bets": _nsoft_bets()},
        },
    }
    events = _resolve_exefeed_events(payload)
    assert len(events) == 2
    names = {e["name"] for e in events}
    assert "Sarajevo - Zeljeznicar" in names
    assert "Borac BL - Sloboda" in names


def test_exefeed_fallback_for_flat_payload():
    """Flat (non-reference) payloads must still resolve via recursion."""
    payload = {
        "offerEvents": [
            {"name": "Velez - Siroki", "dateTime": "2026-08-15T18:00:00", "bets": _nsoft_bets()},
        ]
    }
    events = _resolve_exefeed_events(payload)
    assert len(events) == 1
    assert events[0]["name"] == "Velez - Siroki"


def test_exefeed_extract_matches_produces_match_objects():
    """End-to-end: resolved events must parse into Match objects with markets."""
    payload = {
        "betPages": [{"items": [{"eventId": "E1"}]}],
        "betMap": {
            "E1": {"name": "Sarajevo - Zeljeznicar", "dateTime": "2026-08-15T18:00:00", "bets": _nsoft_bets()},
        },
    }
    scraper = BetoleScraper()
    scraper.captured_json_payloads = [{"url": "https://api.betole.ba/x", "data": payload}]

    matches = asyncio.run(scraper.extract_matches(None))
    assert len(matches) == 1
    m = matches[0]
    assert m.home_team == "Sarajevo"
    assert m.away_team == "Zeljeznicar"
    assert m.kickoff is not None
    assert len(m.markets) == 1
    assert len(m.markets[0].odds) == 3
