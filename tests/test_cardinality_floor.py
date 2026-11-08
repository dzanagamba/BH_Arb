"""SR4-5: event/market cardinality floors against a rolling baseline.

WHAT THESE TESTS PROVE
----------------------
A feed that keeps answering but publishes a tenth of its usual events is still
a broken price source. The cardinality floor compares each ``book|sport``
event and market count with its rolling median, and only flags a drop when a
peer book still publishes that sport in the same scan (so a shared calendar dip
is not a feed failure).

* A feed at 10 % of its baseline is flagged and quarantined through the
  existing feed-integrity state machine (`cardinality_drop`).
* A normal dip (75 % of baseline) is not flagged, and a peer-wide dip is not
  flagged either.
* A feed that keeps its events but loses most markets per event is flagged.
* The bounded history and the coverage-budget persistence carry the new series,
  and `/api/health` exposes the last report.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove seasonality over weeks; the history is an operator-time
rolling window. They also do not change any certainty verdict: a quarantined
book is removed from pricing by the existing `priceable_groups` path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from engine.coverage_budget import (
    cardinality_book_reasons,
    cardinality_snapshot,
    evaluate_cardinality,
    push_cardinality_history,
)
from engine.feed_integrity import compute_feed_integrity
from models.schemas import Market, MarketType, Match, OddsValue
from server import api
from server.app import app
from server.observability import metrics

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _match(book: str, index: int = 0, markets: int = 1) -> Match:
    return Match(
        bookmaker=book,
        home_team=f"Home {index}",
        away_team=f"Away {index}",
        markets=[
            Market(
                market_type=MarketType.BTTS,
                odds=[OddsValue(label="GG", value=2.0)],
            )
            for _ in range(markets)
        ],
        fetched_at=NOW.replace(tzinfo=None),
    )


def _sample(book: str, events: int, markets: int) -> dict[str, dict[str, int]]:
    return {f"{book}|football": {"events": events, "markets": markets}}


def _scorecard(cardinality_flags: dict[str, list[str]]) -> dict[str, dict]:
    return compute_feed_integrity(
        mode="prematch",
        bookmakers={"mbet": "MBet", "wwin": "WWin"},
        matches=[_match("mbet", index) for index in range(4)]
        + [_match("wwin", index) for index in range(40)],
        groups=[],
        progress={"mbet": "done", "wwin": "done"},
        counts={"mbet": 4, "wwin": 40},
        errors=[],
        previous={},
        now=NOW,
        ttl_sec=3600,
        cardinality_flags=cardinality_flags,
    )


def test_snapshot_counts_events_and_markets_per_book_and_sport():
    counts = cardinality_snapshot(
        [_match("mbet", 1, markets=2), _match("mbet", 2, markets=1)]
    )

    assert counts == {"mbet|football": {"events": 2, "markets": 3}}


def test_a_feed_at_ten_percent_of_baseline_is_flagged_and_quarantined():
    history = [
        {
            **_sample("mbet", 40, 200),
            **_sample("wwin", 40, 200),
        }
        for _ in range(3)
    ]
    current = {
        **_sample("mbet", 4, 20),
        **_sample("wwin", 40, 200),
    }

    report = evaluate_cardinality(current, history)

    assert report["flag_count"] == 1
    assert report["flags"][0]["kind"] == "event_drop"
    assert report["flags"][0]["bookmaker"] == "mbet"
    reasons = cardinality_book_reasons(report)
    assert reasons == {"mbet": ["cardinality_drop"]}

    card = _scorecard(reasons)["mbet"]

    assert card["state"] == "quarantined"
    assert "cardinality_drop" in card["reasons"]
    assert card["metrics"]["cardinality_flags"] == 1


def test_a_normal_dip_is_not_flagged_or_quarantined():
    history = [
        {**_sample("mbet", 40, 200), **_sample("wwin", 40, 200)}
        for _ in range(3)
    ]
    current = {**_sample("mbet", 30, 150), **_sample("wwin", 40, 200)}

    report = evaluate_cardinality(current, history)

    assert report["flag_count"] == 0
    assert _scorecard(cardinality_book_reasons(report))["mbet"]["state"] == "healthy"


def test_a_peer_wide_dip_is_a_calendar_dip_not_a_feed_failure():
    history = [
        {**_sample("mbet", 40, 200), **_sample("wwin", 40, 200)}
        for _ in range(3)
    ]
    current = {**_sample("mbet", 4, 20), **_sample("wwin", 5, 25)}

    assert evaluate_cardinality(current, history)["flag_count"] == 0


def test_a_feed_that_keeps_events_but_loses_markets_is_flagged():
    history = [
        {**_sample("mbet", 40, 200), **_sample("wwin", 40, 200)}
        for _ in range(3)
    ]
    current = {**_sample("mbet", 40, 80), **_sample("wwin", 40, 200)}

    report = evaluate_cardinality(current, history)

    assert report["flag_count"] == 1
    assert report["flags"][0]["kind"] == "market_thin"
    assert report["flags"][0]["baseline_per_event"] == 5.0
    assert report["flags"][0]["observed_per_event"] == 2.0


def test_a_short_baseline_is_not_enough_to_call_a_drop():
    history = [{**_sample("mbet", 4, 20), **_sample("wwin", 4, 20)}]
    current = {**_sample("mbet", 1, 5), **_sample("wwin", 4, 20)}

    assert evaluate_cardinality(current, history)["flag_count"] == 0


def test_the_history_is_bounded():
    history: list[dict[str, dict[str, int]]] = []
    for value in range(30):
        history = push_cardinality_history(
            history, _sample("mbet", value, value * 2)
        )

    assert len(history) == 20
    assert history[-1]["mbet|football"]["events"] == 29


def test_the_coverage_budget_file_round_trips_the_new_series():
    current = {**_sample("mbet", 4, 20), **_sample("wwin", 40, 200)}
    report = evaluate_cardinality(
        current,
        [
            {**_sample("mbet", 40, 200), **_sample("wwin", 40, 200)}
            for _ in range(3)
        ],
    )
    api._cardinality = {"prematch": report, "live": {}}
    api._cardinality_history = {"prematch": [current], "live": []}

    api._save_coverage_budget()
    api._cardinality = {"prematch": {}, "live": {}}
    api._cardinality_history = {"prematch": [], "live": []}
    api._load_coverage_budget()

    assert api._cardinality["prematch"]["flag_count"] == 1
    assert api._cardinality_history["prematch"] == [current]


def test_the_health_endpoint_exposes_the_cardinality_report():
    api._cardinality = {
        "prematch": {"flag_count": 1, "flags": [{"bookmaker": "mbet"}]},
        "live": {},
    }

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["cardinality_floor"]["prematch"]["flag_count"] == 1
