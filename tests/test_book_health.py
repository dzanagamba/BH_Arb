"""SR5-2: the per-book health state machine and its /api/health surface.

One test per state, plus the priority rules (a disabled book stays disabled even
when its last attempt was blocked, a blocked attempt is reported as blocked
rather than as the breaker it tripped) and the endpoint wiring for both feeds.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from scrapers.errors import ScrapeKind
from server import api
from server.app import app
from server.book_health import (
    BLOCKED,
    DEGRADED,
    DISABLED,
    DRIFTED,
    HEALTHY,
    OPEN,
    build_book_health,
    derive_state,
)


def _state(**overrides: Any) -> str:
    facts: dict[str, Any] = {
        "enabled": True,
        "breaker_state": "closed",
        "last_kind": ScrapeKind.OK.value,
        "failure_rate": 0.0,
        "has_scan": True,
    }
    facts.update(overrides)
    return derive_state(**facts)[0]


def test_healthy_when_the_last_attempt_returned_matches():
    assert _state() == HEALTHY


def test_degraded_when_the_last_attempt_failed():
    assert _state(last_kind=ScrapeKind.TIMEOUT.value) == DEGRADED
    assert _state(last_kind=ScrapeKind.EMPTY.value) == DEGRADED
    assert _state(last_kind=ScrapeKind.PARSE_ERROR.value) == DEGRADED


def test_degraded_when_no_scan_has_been_recorded():
    assert _state(last_kind=None, has_scan=False) == DEGRADED


def test_degraded_when_the_recent_window_is_mostly_failures():
    assert _state(failure_rate=0.6) == DEGRADED


def test_open_when_the_breaker_is_open():
    assert _state(last_kind=ScrapeKind.TIMEOUT.value, breaker_state="open") == OPEN


def test_degraded_when_the_breaker_is_half_open():
    assert (
        _state(last_kind=ScrapeKind.TRANSPORT.value, breaker_state="half_open")
        == DEGRADED
    )


def test_blocked_when_the_site_refused_the_attempt():
    assert _state(last_kind=ScrapeKind.BLOCKED.value) == BLOCKED


def test_drifted_when_the_payload_was_rejected():
    assert _state(last_kind=ScrapeKind.SCHEMA_DRIFT.value) == DRIFTED


def test_disabled_wins_over_every_other_fact():
    assert (
        _state(
            enabled=False,
            breaker_state="open",
            last_kind=ScrapeKind.BLOCKED.value,
        )
        == DISABLED
    )


def test_a_blocked_attempt_is_not_hidden_by_the_breaker_it_tripped():
    assert (
        _state(
            last_kind=ScrapeKind.BLOCKED.value,
            breaker_state="open",
        )
        == BLOCKED
    )


def test_build_reads_the_last_scan_record_and_its_outcome_fallback():
    health = build_book_health(
        "prematch",
        bookmakers={"a": {"enabled": True}, "b": {"enabled": True}},
        enabled={"a": True, "b": True},
        breakers={"a": {"state": "closed"}, "b": {"state": "closed"}},
        scan_cost={
            "books": {
                "a": {"kind": "ok", "matches": 12, "wall_seconds": 1.5},
                # A record written before the SR2-1 kind existed.
                "b": {"outcome": "blocked", "matches": 0},
            }
        },
        failure_rates={"a": 0.0},
    )

    assert health["a"]["state"] == HEALTHY
    assert health["a"]["matches"] == 12
    assert health["b"]["state"] == BLOCKED
    assert health["b"]["last_kind"] == "blocked"
    assert health["a"]["failure_rate"] == 0.0


def test_the_health_endpoint_reports_every_state_per_feed(monkeypatch):
    kinds = {
        "admiralbet": "blocked",
        "mbet": "schema_drift",
        "mozzartbet": "ok",
        "mdshop": "disabled",
        "sportplus": "timeout",
        "maxbet": "timeout",
    }
    scan_cost = {
        "books": {
            book: {"kind": kind, "matches": 3, "wall_seconds": 1.0}
            for book, kind in kinds.items()
        }
    }
    monkeypatch.setattr(api, "_scan_cost", {"prematch": scan_cost, "live": {}})
    monkeypatch.setattr(api, "_scan_cost_history", [])
    monkeypatch.setattr(
        api,
        "_bookmaker_enabled",
        {
            book: book not in ("mdshop", "evlbet")
            for book in api.BOOKMAKERS
        },
    )

    breaker_state = {
        "prematch": {
            book: {
                "state": "open" if book == "maxbet" else "closed",
                "consecutive_failures": 3 if book == "maxbet" else 0,
            }
            for book in api.BOOKMAKERS
        }
    }
    monkeypatch.setattr(
        api, "_breaker_snapshots", lambda mode: breaker_state.get(mode, {
            book: {"state": "closed"} for book in api.BOOKMAKERS
        })
    )

    body = TestClient(app).get("/api/health").json()
    prematch = body["book_health"]["prematch"]

    assert set(prematch) == set(api.BOOKMAKERS)
    assert prematch["mozzartbet"]["state"] == HEALTHY
    assert prematch["sportplus"]["state"] == DEGRADED
    assert prematch["admiralbet"]["state"] == BLOCKED
    assert prematch["mbet"]["state"] == DRIFTED
    assert prematch["mdshop"]["state"] == DISABLED
    assert prematch["maxbet"]["state"] == OPEN
    # evlbet has no scan record and its config toggle is off.
    assert prematch["evlbet"]["state"] == DISABLED
    # The live feed has no scan cost entry, so every enabled book is unproven.
    assert body["book_health"]["live"]["mozzartbet"]["state"] == DEGRADED
