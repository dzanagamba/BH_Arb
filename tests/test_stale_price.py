"""N0-2: a frozen price is refused without touching the certainty gate.

``fetched_at`` says when we collected a row. ``source_updated_at`` says when the
book last moved it. These tests cover the two refusal rules (feed timestamp past
the budget, unchanged while an independent peer moved), the false-positive
guards, the bounded observation store, and the served evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from config.settings import ODDS_TTL_SECONDS
from engine.arbitrage import ArbitrageEngine
from engine.feed_integrity import compute_feed_integrity
from engine.stale_price import (
    REASON_FROZEN,
    REASON_LABEL,
    REASON_SOURCE_TIMESTAMP,
    _prune,
    evaluate_stale_prices,
)
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from scrapers.maxbet import parse_maxbet_odds
from server import api
from server.app import app

NOW = datetime.now(UTC).replace(tzinfo=None)
KICKOFF = NOW + timedelta(hours=3)
FETCHED = NOW - timedelta(seconds=20)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _match(
    bookmaker: str,
    prices: dict[str, float],
    *,
    source_updated_at: datetime | None = None,
    fetched_at: datetime | None = FETCHED,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="Premijer Liga BiH",
        kickoff=KICKOFF,
        fetched_at=fetched_at,
        source_updated_at=source_updated_at,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(
                        label=label,
                        value=value,
                        source_updated_at=source_updated_at,
                    )
                    for label, value in prices.items()
                ],
            )
        ],
    )


def _group(matches: list[Match]) -> MatchGroup:
    return MatchGroup(
        status="verified",
        canonical_home="sarajevo",
        canonical_away="zeljeznicar",
        league="premier_liga_bih",
        kickoff=KICKOFF,
        matches=matches,
    )


def _scan(
    prices_by_book: dict[str, dict[str, float]],
    previous: dict | None = None,
    *,
    threshold: int = 3,
    ttl_sec: int = ODDS_TTL_SECONDS,
    now: datetime = NOW,
    source_updated_at: datetime | None = None,
):
    matches = [
        _match(book, prices, source_updated_at=source_updated_at)
        for book, prices in prices_by_book.items()
    ]
    group = _group(matches)
    result = evaluate_stale_prices(
        [group],
        previous or {},
        mode="prematch",
        now=now,
        ttl_sec=ttl_sec,
        unchanged_scans=threshold,
    )
    return result, group


def test_a_fresh_feed_timestamp_is_not_stale():
    result, group = _scan(
        {"mbet": {"1": 2.0, "X": 3.5, "2": 4.0}},
        source_updated_at=NOW - timedelta(seconds=5),
    )

    assert result.evidence == []
    assert group.matches[0].markets[0].stale_price is False


def test_a_feed_timestamp_older_than_the_budget_is_stale():
    result, group = _scan(
        {"mbet": {"1": 2.0, "X": 3.5, "2": 4.0}},
        source_updated_at=NOW - timedelta(seconds=ODDS_TTL_SECONDS + 60),
    )

    assert {row["reason"] for row in result.evidence} == {REASON_SOURCE_TIMESTAMP}
    assert result.evidence[0]["reason_label"] == REASON_LABEL == "price frozen"
    assert group.matches[0].markets[0].stale_price is True
    assert all(odd.stale_price for odd in group.matches[0].markets[0].odds)


def test_a_missing_feed_timestamp_is_not_invented_and_does_not_look_fresh():
    """No timestamp means the existing fetched_at TTL stays in charge."""
    result, group = _scan({"mbet": {"1": 2.0, "X": 3.5, "2": 4.0}})

    assert result.evidence == []
    assert group.matches[0].markets[0].stale_price is False
    assert group.matches[0].source_updated_at is None

    # The fail-safe is the existing fetch-time TTL: a missing source timestamp
    # does not make an old row priceable.
    old = _group(
        [
            _match("mbet", {"1": 2.0, "X": 3.5, "2": 4.0},
                   fetched_at=NOW - timedelta(seconds=ODDS_TTL_SECONDS + 60)),
            _match("wwin", {"1": 2.2, "X": 3.4, "2": 3.9}),
            _match("sportplus", {"1": 2.3, "X": 3.3, "2": 3.8}),
        ]
    )
    assert ArbitrageEngine().find_surebets([old], min_profit=0.0) == [], (
        "a missing source timestamp must fail safe to the fetched_at TTL"
    )


def test_a_stable_market_with_no_peer_movement_is_never_stale():
    prices = {
        "mbet": {"1": 2.0, "X": 3.5, "2": 4.0},
        "wwin": {"1": 2.1, "X": 3.4, "2": 3.9},
        "sportplus": {"1": 2.2, "X": 3.3, "2": 3.8},
    }
    store: dict = {}
    for _ in range(5):
        result, group = _scan(prices, store)
        store = result.store
        assert result.evidence == [], "a stable market with stable peers is normal"
        assert group.matches[0].markets[0].stale_price is False


def test_unchanged_while_a_peer_moves_is_stale_after_the_threshold():
    first, _ = _scan(
        {
            "mbet": {"1": 2.0, "X": 3.5, "2": 4.0},
            "wwin": {"1": 2.1, "X": 3.4, "2": 3.9},
            "sportplus": {"1": 2.2, "X": 3.3, "2": 3.8},
        }
    )
    store = first.store

    # Two more scans with wwin moving and mbet frozen: still below threshold.
    for step, wwin_price in enumerate((2.2, 2.3), start=1):
        result, _ = _scan(
            {
                "mbet": {"1": 2.0, "X": 3.5, "2": 4.0},
                "wwin": {"1": wwin_price, "X": 3.4, "2": 3.9},
                "sportplus": {"1": 2.2, "X": 3.3, "2": 3.8},
            },
            store,
        )
        store = result.store
        assert not [row for row in result.evidence if row["bookmaker"] == "mbet"], (
            f"mbet has only {step} unchanged scan(s); the threshold is 3"
        )

    # Fourth scan: mbet has now been unchanged for three comparisons and an
    # independent peer moved in each of them.
    result, group = _scan(
        {
            "mbet": {"1": 2.0, "X": 3.5, "2": 4.0},
            "wwin": {"1": 2.4, "X": 3.4, "2": 3.9},
            "sportplus": {"1": 2.2, "X": 3.3, "2": 3.8},
        },
        store,
    )

    frozen = [row for row in result.evidence if row["bookmaker"] == "mbet"]
    assert frozen, "mbet was frozen for three scans while wwin moved"
    assert frozen[0]["reason"] == REASON_FROZEN
    assert frozen[0]["peer_moved"] is True
    assert frozen[0]["unchanged_scans"] >= 3
    assert result.by_book["mbet"] >= 1
    assert group.matches[0].markets[0].stale_price is True


def test_a_changed_price_resets_the_unchanged_counter():
    first, _ = _scan(
        {
            "mbet": {"1": 2.0, "X": 3.5, "2": 4.0},
            "wwin": {"1": 2.1, "X": 3.4, "2": 3.9},
        }
    )
    store = first.store

    # mbet moves on every scan, so it can never accumulate an unchanged run.
    for price in (2.05, 2.10, 2.15, 2.20):
        result, _ = _scan(
            {
                "mbet": {"1": price, "X": 3.5, "2": 4.0},
                "wwin": {"1": price + 0.5, "X": 3.4, "2": 3.9},
            },
            store,
        )
        store = result.store
        assert not [row for row in result.evidence if row["bookmaker"] == "mbet"]


def test_a_stale_market_cannot_supply_a_priced_leg():
    prices = {
        "mbet": {"1": 2.2, "X": 4.0, "2": 4.0},
        "wwin": {"1": 2.0, "X": 4.2, "2": 4.2},
        "sportplus": {"1": 2.0, "X": 4.2, "2": 4.2},
    }
    control = _group([_match(book, legs) for book, legs in prices.items()])
    assert ArbitrageEngine().find_surebets([control], min_profit=0.0), (
        "the control must price before the stale flag is applied"
    )

    frozen = _group([_match(book, legs) for book, legs in prices.items()])
    frozen.matches[0].markets[0].stale_price = True
    priced = ArbitrageEngine().find_surebets([frozen], min_profit=0.0)

    assert priced == [], (
        "with one book's 1X2 market refused, a three-way market has no leg set"
    )


def test_the_observation_store_is_bounded():
    prices = {f"book{i}": {"1": 2.0 + i / 10} for i in range(4)}
    matches = [
        _match(book, legs, fetched_at=FETCHED)
        for book, legs in prices.items()
    ]
    result = evaluate_stale_prices(
        [_group(matches)],
        {},
        mode="prematch",
        now=NOW,
        ttl_sec=ODDS_TTL_SECONDS,
        max_rows=2,
    )

    assert len(result.store) == 2


def test_a_new_board_survives_the_cap_and_evicts_an_unobserved_old_row():
    def previous_row(book: str, board: str, seen: datetime) -> dict:
        return {
            "bookmaker": book,
            "price_source": book,
            "event": "ev",
            "match": "Sarajevo - Zeljeznicar",
            "market": "1x2",
            "settlement": "full_time",
            "period": "full_time",
            "label": "1",
            "board": board,
            "last_price": 2.0,
            "last_seen_at": seen.isoformat(),
        }

    previous = {
        f"old{index}|board{index}": previous_row(
            f"old{index}", f"board{index}", NOW - timedelta(minutes=30 - index * 10)
        )
        for index in range(3)
    }
    result = evaluate_stale_prices(
        [_group([_match("newbook", {"1": 2.0})])],
        previous,
        mode="prematch",
        now=NOW,
        ttl_sec=ODDS_TTL_SECONDS,
        max_rows=2,
    )

    assert len(result.store) == 2
    assert any(key.startswith("newbook|") for key in result.store), (
        "a board observed by this scan must keep its baseline at the cap"
    )
    assert "old0|board0" not in result.store, (
        "the oldest row this scan did not observe must be the one evicted"
    )


def test_prune_keeps_a_new_key_when_every_row_shares_one_timestamp():
    rows = {
        f"old{index}": {"last_seen_at": NOW.isoformat()} for index in range(3)
    }
    rows["new"] = {"last_seen_at": NOW.isoformat()}

    kept = _prune(
        rows,
        NOW,
        max_rows=3,
        retention_seconds=3600,
        observed_keys=set(rows),
        new_keys={"new"},
    )

    assert "new" in kept, "stable sort must not drop the newly observed board"


def test_a_new_board_survives_when_old_rows_share_the_scan_timestamp():
    def previous_row(book: str, board: str) -> dict:
        return {
            "bookmaker": book,
            "price_source": book,
            "event": "ev",
            "match": "Sarajevo - Zeljeznicar",
            "market": "1x2",
            "settlement": "full_time",
            "period": "full_time",
            "label": "1",
            "board": board,
            "last_price": 2.0,
            # Every row observed in one scan shares this second-resolution stamp.
            "last_seen_at": NOW.isoformat(),
        }

    previous = {
        f"old{index}|board{index}": previous_row(f"old{index}", f"board{index}")
        for index in range(3)
    }
    result = evaluate_stale_prices(
        [_group([_match("newbook", {"1": 2.0})])],
        previous,
        mode="prematch",
        now=NOW,
        ttl_sec=ODDS_TTL_SECONDS,
        max_rows=2,
    )

    assert len(result.store) == 2
    assert any(key.startswith("newbook|") for key in result.store), (
        "a new board must outrank restored rows that share the scan timestamp"
    )


def test_source_updated_at_is_served_distinct_from_fetched_at():
    match = _match(
        "mbet",
        {"1": 2.0, "X": 3.5, "2": 4.0},
        source_updated_at=NOW - timedelta(seconds=5),
        fetched_at=NOW,
    )
    dumped = match.model_dump(mode="json")
    assert dumped["fetched_at"] != dumped["source_updated_at"]
    assert dumped["source_updated_at"] is not None
    assert dumped["markets"][0]["odds"][0]["source_updated_at"] is not None

    # A served leg carries both clocks, so a fresh collection of a frozen price
    # is visible as such.
    group = _group(
        [
            _match("mbet", {"1": 2.0, "X": 3.5, "2": 4.0},
                   source_updated_at=NOW - timedelta(seconds=5), fetched_at=NOW),
            _match("wwin", {"1": 2.2, "X": 3.4, "2": 3.9},
                   source_updated_at=NOW - timedelta(seconds=6), fetched_at=NOW),
            _match("sportplus", {"1": 2.3, "X": 3.3, "2": 3.8},
                   source_updated_at=NOW - timedelta(seconds=7), fetched_at=NOW),
        ]
    )
    surebet = ArbitrageEngine().find_surebets([group], min_profit=0.0)[0]
    stake = surebet.stakes[0]
    assert stake.fetched_at == NOW
    assert stake.source_updated_at is not None
    assert stake.fetched_at != stake.source_updated_at
    assert surebet.odds_source_updated_at is not None


def test_maxbet_parses_its_per_outcome_update_timestamp():
    odds = [
        {
            "id": 1,
            "outcomes": [
                {
                    "outcome": "1",
                    "outcomeId": "1001",
                    "status": 0,
                    "oddValue": 2.0,
                    "updateDate": "2026-11-05T11:55:00Z",
                },
                {
                    "outcome": "X",
                    "outcomeId": "1002",
                    "status": 0,
                    "oddValue": 3.5,
                    "updateDate": "2026-11-05T11:56:00Z",
                },
                {
                    "outcome": "2",
                    "outcomeId": "1003",
                    "status": 0,
                    "oddValue": 4.0,
                },
            ],
        }
    ]

    market = parse_maxbet_odds(odds)[0]
    by_label = {odd.label: odd for odd in market.odds}

    assert by_label["1"].source_updated_at == datetime(2026, 11, 5, 11, 55)
    assert by_label["X"].source_updated_at == datetime(2026, 11, 5, 11, 56)
    assert by_label["2"].source_updated_at is None, (
        "a missing update time must stay missing, never be filled from the clock"
    )


def test_feed_integrity_carries_the_stale_row_count():
    match = _match("mbet", {"1": 2.0, "X": 3.5, "2": 4.0})
    group = _group([match])
    scorecard = compute_feed_integrity(
        mode="prematch",
        bookmakers={"mbet": "MBet"},
        matches=[match],
        groups=[group],
        progress={"mbet": "done"},
        counts={"mbet": 1},
        errors=[],
        previous={},
        now=NOW,
        ttl_sec=ODDS_TTL_SECONDS,
        stale_price_rows={"mbet": 2},
    )

    assert scorecard["mbet"]["stale_price_rows"] == 2


def test_results_and_health_expose_the_frozen_price_evidence(monkeypatch):
    row = {
        "bookmaker": "mbet",
        "event": "betradar:1",
        "match": "sarajevo - zeljeznicar",
        "market": "1x2",
        "label": "1",
        "price": 2.0,
        "reason": REASON_FROZEN,
        "reasons": [REASON_FROZEN],
        "reason_label": REASON_LABEL,
        "unchanged_scans": 3,
        "peer_moved": True,
    }
    monkeypatch.setattr(api, "_stale_price_evidence", {"prematch": [row], "live": []})
    monkeypatch.setattr(
        api,
        "_stale_price_checked_at",
        {"prematch": _now().isoformat(), "live": ""},
    )

    client = TestClient(app)
    results = client.get("/api/results?mode=prematch").json()
    assert results["stale_prices"]["count"] == 1
    assert results["stale_prices"]["rows"][0]["reason_label"] == "price frozen"
    assert results["feed_integrity"]["stale_prices"]["count"] == 1

    health = client.get("/api/health").json()
    assert health["stale_prices"]["prematch"]["count"] == 1
    assert "rows" not in health["stale_prices"]["prematch"], (
        "health keeps the bounded counts; the full evidence belongs to /api/results"
    )
