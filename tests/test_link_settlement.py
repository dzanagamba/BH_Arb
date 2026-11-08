"""One link-settled predicate for the gate, the cache restore and the counter.

`engine.deeplinks.settle_link` is the single answer to "is this leg's per-event
link settled?". The gate reads the match's ``deep_link_verified`` flag as its
proof; a cache restore reads the deep-link store itself, because a restored flag
is a snapshot that outlives its proof. Everything else is shared, so the three
callers cannot drift on the cases that decide whether a group is `verified`.

These cases are the four gate cases plus the stale-proof variant: proof, route
pattern, declares-no-route, declared-but-unproven, silence with an id, silence
with a URL, silence with nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine import deeplinks
from engine.certainty import CertaintyGate
from engine.deeplinks import LinkSettlement, settle_link
from models.schemas import Match
from server import api

# Synthetic declarations, injected through the store's documented cache seam:
# the shipped config has no declared-but-unproven book, and this test is about
# the predicate, not about which book is in that state today.
NO_ROUTE = "test_no_route"
ROUTE_PATTERN = "test_route_pattern"
DECLARED_UNPROVEN = "test_declared_unproven"
SILENT = "test_silent"

DECLARATIONS = {
    NO_ROUTE: {"supports_event_id": False},
    ROUTE_PATTERN: {"supports_event_id": True, "route_pattern_verified": True},
    DECLARED_UNPROVEN: {"supports_event_id": True},
}

FRESH = "fresh"
STALE = "stale"

_one_hour_ago = timedelta(hours=1)
_beyond_ttl = timedelta(seconds=api.DEEP_LINK_VERIFICATION_TTL_SECONDS + 60)


CASES = [
    pytest.param(
        "proof",
        DECLARED_UNPROVEN,
        "42",
        "",
        True,
        FRESH,
        LinkSettlement(True, "verified_link"),
        id="cached-flag-and-fresh-store-proof",
    ),
    pytest.param(
        "route pattern",
        ROUTE_PATTERN,
        "42",
        "",
        False,
        None,
        LinkSettlement(True, "route_pattern_verified"),
        id="dated-route-pattern",
    ),
    pytest.param(
        "declares no route",
        NO_ROUTE,
        "",
        "",
        False,
        None,
        LinkSettlement(True, "no_event_link"),
        id="declares-no-event-route",
    ),
    pytest.param(
        "declares no route but carries an id",
        NO_ROUTE,
        "42",
        "",
        False,
        None,
        LinkSettlement(True, "no_event_link"),
        id="declares-no-event-route-with-id",
    ),
    pytest.param(
        "declared route, unproven",
        DECLARED_UNPROVEN,
        "42",
        "",
        False,
        None,
        LinkSettlement(False, "link_unverified"),
        id="declared-unproven-with-id",
    ),
    pytest.param(
        "declared route, no capture",
        DECLARED_UNPROVEN,
        "",
        "",
        False,
        None,
        LinkSettlement(False, "link_unverified"),
        id="declared-unproven-without-capture",
    ),
    pytest.param(
        "silence with an id",
        SILENT,
        "42",
        "",
        False,
        None,
        LinkSettlement(False, "link_unverified"),
        id="silent-with-id",
    ),
    pytest.param(
        "silence with a url",
        SILENT,
        "",
        "https://example.test/event/42",
        False,
        None,
        LinkSettlement(False, "link_unverified"),
        id="silent-with-url",
    ),
    pytest.param(
        "silence with nothing",
        SILENT,
        "",
        "",
        False,
        None,
        LinkSettlement(False, "no_event_link"),
        id="silent-with-nothing",
    ),
    pytest.param(
        "stale store proof",
        DECLARED_UNPROVEN,
        "42",
        "",
        False,
        STALE,
        LinkSettlement(False, "link_unverified"),
        id="stale-store-proof-does-not-settle",
    ),
]


@pytest.fixture(autouse=True)
def _declarations(monkeypatch):
    monkeypatch.setattr(deeplinks, "_deeplink_cache", dict(DECLARATIONS))
    # A non-None cache with no load time is the store's injected-cache seam: the
    # loader returns it without touching the file.
    monkeypatch.setattr(deeplinks, "_deeplink_loaded_at", None)


def _store_record(age: str | None) -> dict | None:
    if age is None:
        return None
    delta = _one_hour_ago if age == FRESH else _beyond_ttl
    return {
        "verified": True,
        "checked_at": (datetime.now(UTC) - delta).isoformat(),
        "url": "https://example.test/event/42",
    }


def _gate_settlement(bookmaker: str, event_id: str, url: str, flag: bool) -> LinkSettlement:
    evidence, settled = CertaintyGate._link_evidence(
        Match(
            bookmaker=bookmaker,
            home_team="Home",
            away_team="Away",
            event_id=event_id,
            url=url,
            deep_link_verified=flag,
        )
    )
    return LinkSettlement(settled, evidence.reason)


def _restore_kept(monkeypatch, bookmaker: str, event_id: str, record: dict | None) -> bool:
    entries = {api._deep_link_key(bookmaker, event_id): record} if record else {}
    monkeypatch.setattr(api, "_deep_link_verifications", {"prematch": entries})
    report = [
        {
            "status": "verified",
            "canonical_match": "Home vs Away",
            "bookmakers": [{"bookmaker": bookmaker, "event_id": event_id}],
        }
    ]
    return api._restorable_match_groups(report, "prematch") == report


@pytest.mark.parametrize(
    "name,bookmaker,event_id,url,flag,age,expected",
    CASES,
)
def test_gate_uses_the_shared_predicate(
    name, bookmaker, event_id, url, flag, age, expected
):
    assert settle_link(
        bookmaker, event_id=event_id, url=url, proof=flag
    ) == expected
    assert _gate_settlement(bookmaker, event_id, url, flag) == expected, name


@pytest.mark.parametrize(
    "name,bookmaker,event_id,url,flag,age,expected",
    CASES,
)
def test_cache_restore_uses_the_shared_predicate(
    monkeypatch, name, bookmaker, event_id, url, flag, age, expected
):
    record = _store_record(age)
    # Restore's proof is the store, never the cached flag.
    store_settlement = settle_link(
        bookmaker,
        event_id=event_id,
        proof=api._deep_link_record_is_fresh(record),
    )
    assert _restore_kept(monkeypatch, bookmaker, event_id, record) is store_settlement.settled, (
        name
    )


@pytest.mark.parametrize(
    "name,bookmaker,event_id,url,flag,age,expected",
    CASES,
)
def test_unverified_counter_uses_the_shared_predicate(
    name, bookmaker, event_id, url, flag, age, expected
):
    row = {
        "bookmaker": bookmaker,
        "event_id": event_id,
        "url": url,
        "deep_link_verified": flag,
    }
    settled = settle_link(
        bookmaker, event_id=event_id, url=url, proof=flag
    ).settled
    # The counter answers for rows whose link a check could target, so it only
    # counts an unsettled leg that carries an event id.
    assert api._unverified_link_count([row]) == (
        1 if event_id and not settled else 0
    ), name


def test_a_stale_store_proof_cannot_restore_a_verified_group(monkeypatch):
    """The concrete drift this task removes: both sides must refuse it."""
    bookmaker, event_id = DECLARED_UNPROVEN, "42"
    record = _store_record(STALE)

    assert not settle_link(
        bookmaker, event_id=event_id, proof=False
    ).settled
    assert not _restore_kept(monkeypatch, bookmaker, event_id, record)
