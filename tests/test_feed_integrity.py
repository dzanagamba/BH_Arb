"""P0-7: feed-integrity scorecard and stale-book quarantine.

Quarantine is a price-source restriction, not a certainty verdict. These tests
build synthetic books with real complete sets, score them, and prove the priced
legs can no longer come from a quarantined book.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from engine.arbitrage import ArbitrageEngine
from engine.feed_integrity import (
    compute_feed_integrity,
    priceable_groups,
    quarantined_books,
)
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

BOOKMAKERS = {"mbet": "MBet", "wwin": "WWIN"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _match(
    bookmaker: str,
    gg: float,
    ng: float,
    *,
    fetched_at: datetime | None = None,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="Premijer Liga BiH",
        kickoff=_now() + timedelta(hours=3),
        fetched_at=fetched_at or _now(),
        markets=[
            Market(
                market_type=MarketType.BTTS,
                odds=[OddsValue(label="GG", value=gg), OddsValue(label="NG", value=ng)],
            )
        ],
    )


def _group(
    matches: list[Match],
    status: Literal["verified", "suggested", "rejected"] = "verified",
) -> MatchGroup:
    return MatchGroup(
        status=status,
        canonical_home="sarajevo",
        canonical_away="zeljeznicar",
        league="premier_liga_bih",
        kickoff=_now() + timedelta(hours=3),
        matches=matches,
    )


def _score(
    matches: list[Match],
    groups: list[MatchGroup],
    *,
    previous: dict[str, dict] | None = None,
    now: datetime | None = None,
) -> dict[str, dict]:
    return compute_feed_integrity(
        mode="prematch",
        bookmakers=BOOKMAKERS,
        matches=matches,
        groups=groups,
        progress={book: "done" for book in BOOKMAKERS},
        counts={book: sum(1 for m in matches if m.bookmaker == book) for book in BOOKMAKERS},
        errors=[],
        previous=previous or {},
        now=now or _now(),
        ttl_sec=600,
    )


def test_stale_book_is_quarantined_and_cannot_supply_a_priced_leg():
    stale = _match("mbet", 2.10, 1.90, fetched_at=_now() - timedelta(minutes=30))
    fresh = _match("wwin", 1.90, 2.10)
    group = _group([stale, fresh])

    # The same prices with a fresh fetch do cross; removing the stale book
    # leaves no arb. The control keeps the negative from being vacuous.
    control = _group([stale.model_copy(update={"fetched_at": _now()}), fresh])
    assert ArbitrageEngine().find_surebets([control], min_profit=0.5), (
        "the fixture must produce a surebet before quarantine, or the negative is vacuous"
    )
    scorecard = _score([stale, fresh], [group])

    assert scorecard["mbet"]["state"] == "quarantined"
    assert "stale_prices" in scorecard["mbet"]["reasons"]
    assert scorecard["wwin"]["state"] == "healthy"
    assert quarantined_books(scorecard) == {"mbet"}

    priced_groups = priceable_groups([group], quarantined_books(scorecard))
    assert all(m.bookmaker != "mbet" for g in priced_groups for m in g.matches)
    assert ArbitrageEngine().find_surebets(priced_groups, min_profit=0.5) == []


def test_a_complete_set_below_one_is_quarantined():
    broken = _match("mbet", 2.10, 2.10)  # 1/2.10 + 1/2.10 = 0.952
    peer = _match("wwin", 1.90, 1.90)
    group = _group([broken, peer])

    scorecard = _score([broken, peer], [group])

    assert scorecard["mbet"]["metrics"]["own_margin_violations"] == 1
    assert scorecard["mbet"]["state"] == "quarantined"
    assert "own_margin_below_one" in scorecard["mbet"]["reasons"]
    assert scorecard["wwin"]["state"] == "healthy"


def test_recovery_needs_consecutive_clean_scans_not_one_lucky_scan():
    healthy = _match("mbet", 1.90, 1.90)
    group = _group([healthy])
    previous = {
        "mbet": {
            "state": "quarantined",
            "consecutive_healthy_scans": 0,
            "consecutive_unhealthy_scans": 2,
        }
    }
    now = _now()

    first = _score([healthy], [group], previous=previous, now=now)
    assert first["mbet"]["state"] == "quarantined"
    assert first["mbet"]["consecutive_healthy_scans"] == 1
    assert "recovering" in first["mbet"]["reasons"]

    second = _score([healthy], [group], previous=first, now=now + timedelta(minutes=1))
    assert second["mbet"]["state"] == "quarantined"
    assert second["mbet"]["consecutive_healthy_scans"] == 2

    third = _score([healthy], [group], previous=second, now=now + timedelta(minutes=2))
    assert third["mbet"]["state"] == "healthy"
    assert third["mbet"]["consecutive_healthy_scans"] == 3
    assert third["mbet"]["reasons"] == []


def test_quarantine_does_not_change_the_certainty_group():
    stale = _match("mbet", 2.10, 1.90, fetched_at=_now() - timedelta(minutes=30))
    fresh = _match("wwin", 1.90, 2.10)
    group = _group([stale, fresh], status="verified")
    before = group.model_copy(deep=True)

    scorecard = _score([stale, fresh], [group])
    priced = priceable_groups([group], quarantined_books(scorecard))

    assert group == before, "scoring and leg filtering must not mutate the gate's group"
    assert group.status == "verified"
    assert len(priced[0].matches) == 1
    assert priced[0].status == "verified"


def test_every_enabled_book_has_a_state_and_a_reason():
    matches = [_match("mbet", 1.90, 1.90)]
    group = _group(matches)

    scorecard = _score(matches, [group])

    assert set(scorecard) == set(BOOKMAKERS)
    for entry in scorecard.values():
        assert entry["state"] in {"healthy", "degraded", "quarantined"}
        assert "reason" in entry
        assert "metrics" in entry
        assert "history" in entry


def test_results_and_health_expose_the_scorecard(monkeypatch):
    from fastapi.testclient import TestClient

    from server import api
    from server.app import app

    entry = {
        "bookmaker": "mbet",
        "name": "MBet",
        "state": "quarantined",
        "reasons": ["stale_prices"],
        "reason": "stale_prices",
        "scan_time": "2026-11-04T12:00:00",
    }
    saved = {mode: dict(books) for mode, books in api._feed_integrity.items()}
    api._feed_integrity["prematch"] = {"mbet": entry}
    try:
        client = TestClient(app)
        results = client.get("/api/results?mode=prematch").json()
        health = client.get("/api/health").json()

        assert results["feed_integrity"]["quarantined"] == ["mbet"]
        assert results["feed_integrity"]["books"]["mbet"]["reasons"] == ["stale_prices"]
        assert health["feed_integrity"]["prematch"]["quarantined"] == ["mbet"]
    finally:
        api._feed_integrity["prematch"] = saved["prematch"]
