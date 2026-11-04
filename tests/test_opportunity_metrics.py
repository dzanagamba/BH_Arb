"""P0-6: opportunity-rate denominators and crossing lifetimes.

The numbers must come from the same pricing path that emits surebets. These
tests drive the real engine with synthetic odds, then feed its board observations
through the summarizer, so a second arb formula cannot drift from the first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from engine.arbitrage import ArbitrageEngine
from engine.opportunity_metrics import (
    BoardObservation,
    ScanMetrics,
    board_key,
    lifetime_distribution,
    summarize_scan,
    update_lifetimes,
)
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

FLOOR = 0.5


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _group(
    gg_by_book: dict[str, float],
    ng_by_book: dict[str, float],
    *,
    fetched_at: datetime | None = None,
    status: Literal["verified", "suggested", "rejected"] = "verified",
) -> MatchGroup:
    kickoff = _now() + timedelta(hours=3)
    matches = [
        Match(
            bookmaker=book,
            home_team="Sarajevo",
            away_team="Zeljeznicar",
            league="Premijer Liga BiH",
            kickoff=kickoff,
            fetched_at=fetched_at or _now(),
            markets=[
                Market(
                    market_type=MarketType.BTTS,
                    odds=[
                        OddsValue(label="GG", value=gg_by_book[book]),
                        OddsValue(label="NG", value=ng_by_book[book]),
                    ],
                )
            ],
        )
        for book in gg_by_book
    ]
    return MatchGroup(
        status=status,
        canonical_home="sarajevo",
        canonical_away="zeljeznicar",
        league="premier_liga_bih",
        kickoff=kickoff,
        matches=matches,
    )


def _scan(groups: list[MatchGroup], min_profit: float = FLOOR):
    metrics = ScanMetrics()
    surebets = ArbitrageEngine().find_surebets(
        groups,
        min_profit=min_profit,
        enabled_markets={"btts"},
        metrics=metrics,
    )
    return metrics, surebets


def _summary(metrics: ScanMetrics, surebets: list) -> dict:
    return summarize_scan(
        metrics,
        surebets,
        [],
        mode="prematch",
        scan_time=_now(),
        floor_profit_percent=FLOOR,
    )


def test_no_crossing_is_not_the_same_as_no_boards():
    group = _group({"mdshop": 1.90, "mbet": 1.90}, {"mdshop": 1.90, "mbet": 1.90})
    metrics, surebets = _scan([group])

    summary = _summary(metrics, surebets)

    assert summary["boards"] == 1
    assert summary["crossed"] == 0
    assert summary["actionable"] == 0
    assert summary["zero_result_reason"] == "no_crossing"
    assert summary["crossing_rate_percent"] == 0.0


def test_a_crossing_below_the_floor_is_reported_as_such():
    # 1/2.002 + 1/2.002 = 0.9990, about +0.10%: a crossing, below the 0.5% floor.
    group = _group({"mdshop": 2.002, "mbet": 2.002}, {"mdshop": 2.002, "mbet": 2.002})
    metrics, surebets = _scan([group])

    summary = _summary(metrics, surebets)

    assert summary["boards"] == 1
    assert summary["crossed"] == 1
    assert summary["crossed_above_floor"] == 0
    assert summary["actionable"] == 0
    assert summary["zero_result_reason"] == "crossing_below_floor"


def test_a_crossing_above_the_floor_is_actionable_and_counted_from_the_odds():
    group = _group({"mdshop": 2.10, "mbet": 2.10}, {"mdshop": 2.10, "mbet": 2.10})
    metrics, surebets = _scan([group])

    summary = _summary(metrics, surebets)

    assert summary["boards"] == 1
    assert summary["crossed"] == 1
    assert summary["crossed_above_floor"] == 1
    assert summary["actionable"] == 1
    assert summary["zero_result_reason"] == "actionable"
    assert summary["crossing_rate_percent"] == 100.0
    assert summary["actionable_rate_percent"] == 100.0
    assert summary["best_margin"] < 1.0
    assert summary["best_profit_percent"] > FLOOR


def test_a_stale_group_produces_a_stale_data_reason_not_a_false_no_crossing():
    group = _group(
        {"mdshop": 2.10, "mbet": 2.10},
        {"mdshop": 2.10, "mbet": 2.10},
        fetched_at=_now() - timedelta(hours=2),
    )
    metrics, surebets = _scan([group])

    summary = _summary(metrics, surebets)

    assert metrics.groups_total == 1
    assert metrics.groups_stale == 1
    assert summary["boards"] == 0
    assert summary["actionable"] == 0
    assert summary["zero_result_reason"] == "stale_data"


def test_lifetime_records_first_last_and_disappearance():
    now = _now()
    board = BoardObservation(
        event_key="betradar:1",
        market_type="btts",
        line="",
        period="full_time",
        settlement="full_time",
        margin=0.99,
        profit_percent=1.01,
        bookmakers=("mbet", "wwin"),
    )
    tracked: dict[str, dict] = {}

    update_lifetimes(tracked, [board], now)
    record = tracked[board_key(board)]
    assert record["first_crossed_at"] == now.isoformat()
    assert record["last_crossed_at"] == now.isoformat()
    assert record["disappeared_at"] is None

    later = now + timedelta(minutes=5)
    update_lifetimes(tracked, [], later)
    record = tracked[board_key(board)]
    assert record["disappeared_at"] == later.isoformat()

    distribution = lifetime_distribution(tracked, later)
    assert distribution["samples"] == 1
    assert distribution["alive"] == 0
    assert distribution["p50_sec"] == 300.0
    assert distribution["p90_sec"] == 300.0


def test_lifetime_store_is_bounded_by_its_key_cap():
    now = _now()
    tracked: dict[str, dict] = {}
    boards = [
        BoardObservation(
            event_key=f"event:{index}",
            market_type="btts",
            line="",
            period="full_time",
            settlement="full_time",
            margin=0.99,
            profit_percent=1.0,
            bookmakers=("mbet",),
        )
        for index in range(5)
    ]

    update_lifetimes(tracked, boards, now, max_keys=2)

    assert len(tracked) == 2


def test_results_and_health_expose_the_same_metrics(monkeypatch):
    from fastapi.testclient import TestClient

    from server import api
    from server.app import app

    saved = dict(api._opportunity_by_mode)
    api._opportunity_by_mode["prematch"] = {
        "mode": "prematch",
        "boards": 10,
        "crossed": 2,
        "crossed_above_floor": 1,
        "actionable": 1,
        "crossing_rate_percent": 20.0,
        "zero_result_reason": "actionable",
    }
    try:
        client = TestClient(app)
        results = client.get("/api/results?mode=prematch").json()
        health = client.get("/api/health").json()

        assert results["opportunity_metrics"]["boards"] == 10
        assert results["opportunity_metrics"]["crossed"] == 2
        assert health["opportunity_metrics"]["prematch"]["actionable"] == 1
        assert health["opportunity_metrics"]["live"] == {}
    finally:
        api._opportunity_by_mode.clear()
        api._opportunity_by_mode.update(saved)


def test_metrics_store_persists_only_aggregates_and_crossing_keys(tmp_path, monkeypatch):
    from server import api

    path = tmp_path / "opportunity_metrics.json"
    monkeypatch.setattr(api, "_OPPORTUNITY_METRICS_FILE", str(path))
    saved_summary = dict(api._opportunity_by_mode)
    saved_lifetimes = {mode: dict(v) for mode, v in api._crossing_lifetimes.items()}
    api._opportunity_by_mode = {"prematch": {"boards": 3, "crossed": 1}}
    api._crossing_lifetimes = {
        "prematch": {"event|btts||full_time|full_time": {"first_crossed_at": "x"}},
        "live": {},
    }

    try:
        api._save_opportunity_metrics()
        payload = path.read_text(encoding="utf-8")
        assert '"boards":3' in payload
        assert "event|btts" in payload
        assert "matches" not in payload

        api._opportunity_by_mode = {}
        api._crossing_lifetimes = {"prematch": {}, "live": {}}
        api._load_opportunity_metrics()

        assert api._opportunity_by_mode["prematch"]["boards"] == 3
        assert "event|btts||full_time|full_time" in api._crossing_lifetimes["prematch"]
    finally:
        api._opportunity_by_mode = saved_summary
        api._crossing_lifetimes = saved_lifetimes
