"""N1-2: coverage and mapping alerts stay deduped and evidence-backed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from engine.coverage_budget import evaluate, mapping_coverage
from models.schemas import Market, MarketType, Match, OddsValue
from server import api
from server.alerts import (
    Alert,
    AlertManager,
    coverage_drop_alerts,
    mapping_coverage_alert,
    zero_result_alert,
)
from server.observability import metrics

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")


class FakeTransport:
    name = "fake"

    def __init__(self) -> None:
        self.attempts: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.attempts.append(alert)


def _manager(transport: FakeTransport) -> AlertManager:
    return AlertManager(
        [transport],
        dedupe_minutes=60,
        retry_attempts=1,
        retry_base_seconds=0,
    )


def _match(book: str, markets: int = 1) -> Match:
    return Match(
        bookmaker=book,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="Test League",
        kickoff=datetime(2026, 11, 7, 18, 0),
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[OddsValue(label="1", value=2.0)],
            )
            for _ in range(markets)
        ],
    )


def _silent_zero_report() -> dict:
    return evaluate(
        {"wwin|football|btts": 12},
        [{"mbet|football|btts": 10, "wwin|football|btts": 10}],
    )


def test_mapping_coverage_reports_its_numerator_and_denominator():
    report = mapping_coverage(
        [_match("mbet", markets=20)],
        {},
        {"mbet:999": 5},
        floor=0.95,
        min_rows=20,
    )

    assert report["numerator"] == 20
    assert report["denominator"] == 25
    assert report["unmapped_total"] == 5
    assert report["coverage"] == 0.8
    assert report["below_floor"] is True
    assert report["per_book"]["mbet"] == {
        "mapped": 20,
        "unmapped": 5,
        "total": 25,
        "coverage": 0.8,
        "below_floor": True,
    }


def test_mapping_coverage_uses_only_the_scan_delta_and_ignores_a_tiny_scan():
    report = mapping_coverage(
        [_match("mbet", markets=2)],
        {"mbet:999": 7},
        {"mbet:999": 8},
        floor=0.95,
        min_rows=20,
    )

    assert report["unmapped_total"] == 1
    assert report["denominator"] == 3
    assert report["coverage"] == round(2 / 3, 4)
    # A three-row scan is below the judging floor, so it cannot alert.
    assert report["below_floor"] is False


def test_a_legitimate_empty_feed_has_no_coverage_ratio_and_no_alert():
    report = mapping_coverage([], {}, {}, floor=0.95, min_rows=20)

    assert report["denominator"] == 0
    assert report["coverage"] is None
    assert report["below_floor"] is False
    assert mapping_coverage_alert("live", report) is None


def test_a_silent_zero_alert_carries_peer_evidence_and_the_baseline_count():
    alerts = coverage_drop_alerts("prematch", _silent_zero_report())

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.kind == "coverage_drop"
    assert alert.mode == "prematch"
    assert "silent zero" in alert.title
    assert "peer book(s)" in alert.body
    assert "row(s)" in alert.body
    assert "1 scan(s)" in alert.body
    assert "mbet" in alert.body and "btts" in alert.body


def test_mapping_coverage_alert_states_the_numerator_denominator_and_floor():
    report = mapping_coverage(
        [_match("mbet", markets=20)],
        {},
        {"mbet:999": 5},
        floor=0.95,
        min_rows=20,
    )

    alert = mapping_coverage_alert("prematch", report)

    assert alert is not None
    assert alert.kind == "mapping_coverage_low"
    assert "20/25" in alert.body
    assert "80.0%" in alert.body
    assert "floor 95.0%" in alert.body
    assert "Below floor: mbet 20/25" in alert.body
    assert mapping_coverage_alert(
        "prematch", {**report, "below_floor": False}
    ) is None


def test_zero_result_alert_waits_for_the_consecutive_threshold():
    summary = {"groups": {"total": 4, "verified": 0}, "boards": 0}

    assert zero_result_alert("prematch", "stale_data", 1, 2, summary) is None
    alert = zero_result_alert("prematch", "stale_data", 2, 2, summary)
    assert alert is not None
    assert alert.kind == "zero_result_reason"
    assert "2 consecutive scan(s)" in alert.body
    assert "4 total / 0 verified" in alert.body
    assert zero_result_alert("prematch", "no_crossing", 9, 2, summary) is None


def test_a_peer_populated_silent_zero_raises_one_deduped_alert(monkeypatch):
    transport = FakeTransport()
    manager = _manager(transport)
    monkeypatch.setattr(api, "alert_manager", manager)
    monkeypatch.setattr(
        api, "_coverage_budget", {"prematch": _silent_zero_report(), "live": {}}
    )
    monkeypatch.setattr(api, "_mapping_coverage", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_opportunity_by_mode", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_feed_integrity", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_book_failures", {})
    status = api.ScanStatus(last_scan_time=datetime.now(UTC).replace(tzinfo=None))

    api._notify_scan_alerts("prematch", [], status, [], cache_bytes=1)
    api._notify_scan_alerts("prematch", [], status, [], cache_bytes=1)
    assert manager.wait_idle()

    assert [alert.kind for alert in transport.attempts] == ["coverage_drop"]
    assert manager.snapshot()["suppressed"] == 1


def test_a_legitimate_empty_feed_queues_no_coverage_alert(monkeypatch):
    transport = FakeTransport()
    manager = _manager(transport)
    monkeypatch.setattr(api, "alert_manager", manager)
    monkeypatch.setattr(api, "_coverage_budget", {"prematch": {}, "live": {}})
    monkeypatch.setattr(
        api,
        "_mapping_coverage",
        {
            "prematch": mapping_coverage([], {}, {}, floor=0.95, min_rows=20),
            "live": {},
        },
    )
    monkeypatch.setattr(
        api,
        "_opportunity_by_mode",
        {
            "prematch": {
                "zero_result_reason": "no_priced_boards",
                "zero_result_streak": 0,
            },
            "live": {},
        },
    )
    monkeypatch.setattr(api, "_feed_integrity", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_book_failures", {})
    status = api.ScanStatus(last_scan_time=datetime.now(UTC).replace(tzinfo=None))

    api._notify_scan_alerts("prematch", [], status, [], cache_bytes=1)
    assert manager.wait_idle()

    assert transport.attempts == []


def test_health_exposes_mapping_coverage_and_the_trend(monkeypatch):
    mapping = mapping_coverage(
        [_match("mbet", markets=20)],
        {},
        {"mbet:999": 5},
        floor=0.95,
        min_rows=20,
    )
    trend = [
        {
            "scan_time": "2026-11-05T10:00:00",
            "flag_count": 1,
            "unmapped_rows": 5,
            "mapping_coverage": 0.8,
            "denominator": 25,
        }
    ]
    monkeypatch.setattr(api, "_mapping_coverage", {"prematch": mapping, "live": {}})
    monkeypatch.setattr(api, "_coverage_trend", {"prematch": trend, "live": []})
    monkeypatch.setattr(
        api, "_zero_result_streaks", {"prematch": {"stale_data": 2}, "live": {}}
    )

    body = asyncio.run(api.health())

    assert body["mapping_coverage"]["prematch"]["numerator"] == 20
    assert body["mapping_coverage"]["prematch"]["denominator"] == 25
    assert body["coverage_trend"]["prematch"] == trend
    assert body["zero_result_streaks"]["prematch"]["stale_data"] == 2
    assert body["coverage_slo"]["mapping_coverage_floor"] == 0.95


def test_coverage_metrics_publish_flags_and_unmapped_rows():
    metrics.reset_values()
    try:
        api._record_coverage_metrics(
            "prematch",
            {"flag_count": 2},
            {"coverage": 0.9, "unmapped_total": 3},
        )
        text = metrics.render()
    finally:
        metrics.reset_values()

    assert 'bh_coverage_flags{mode="prematch"} 2' in text
    assert 'bh_coverage_flags_total{mode="prematch"} 2' in text
    assert 'bh_mapping_coverage_ratio{mode="prematch"} 0.9' in text
    assert 'bh_unmapped_market_rows_total{mode="prematch"} 3' in text


def test_the_dashboard_has_a_coverage_trend_line():
    assert 'id="coverage-trend"' in HTML
    assert 'id="coverage-spark"' in HTML
    assert "renderCoverageTrend" in JS
    assert "coverage_trend" in JS
    assert "coverage-line-flags" in JS and "coverage-line-unmapped" in JS
