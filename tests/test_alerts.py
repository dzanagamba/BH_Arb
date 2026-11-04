"""P1-5: alert builders, dedupe, retry and the null default."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from server import api
from server.alerts import (
    Alert,
    AlertManager,
    NullTransport,
    WebhookTransport,
    book_failure_alert,
    feed_alerts,
    quarantine_alerts,
    resource_alerts,
    surebet_alert,
    surebet_signature,
)
from server.app import app


class FakeTransport:
    name = "fake"

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.attempts: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.attempts.append(alert)
        if len(self.attempts) <= self.failures:
            raise RuntimeError("token=SUPERSECRET")


def _surebet(profit: float = 4.2) -> dict:
    return {
        "home_team": "Sarajevo",
        "away_team": "Zeljeznicar",
        "league": "Premijer Liga BiH",
        "kickoff": "2030-01-01T18:00:00",
        "market_type": "btts",
        "profit_percent": profit,
        "stakes": [
            {"bookmaker": "mbet", "outcome_label": "GG", "odds": 2.20, "line": ""},
            {"bookmaker": "mdshop", "outcome_label": "NG", "odds": 1.90, "line": ""},
        ],
    }


def _manager(transport: FakeTransport, *, retries: int = 3) -> AlertManager:
    return AlertManager(
        [transport],
        dedupe_minutes=60,
        retry_attempts=retries,
        retry_base_seconds=0,
    )


def test_the_default_is_a_null_transport():
    manager = AlertManager()

    assert manager.enabled is False
    assert manager.notify(Alert("surebet", "sig", "title", "body")) is False
    assert manager.snapshot()["transports"] == ["null"]
    assert manager.snapshot()["sent"] == 0


def test_a_repeated_alert_is_suppressed_inside_the_dedupe_window():
    clock = [1000.0]
    transport = FakeTransport()
    manager = AlertManager(
        [transport],
        dedupe_minutes=60,
        retry_base_seconds=0,
        clock=lambda: clock[0],
    )
    alert = Alert("surebet", "same-signature", "title", "body")

    assert manager.notify(alert) is True
    assert manager.wait_idle()
    clock[0] += 59 * 60
    assert manager.notify(alert) is False
    assert manager.wait_idle()
    assert len(transport.attempts) == 1

    clock[0] += 2 * 60
    assert manager.notify(alert) is True
    assert manager.wait_idle()
    assert len(transport.attempts) == 2

    snapshot = manager.snapshot()
    assert snapshot["sent"] == 2
    assert snapshot["suppressed"] == 1


def test_a_failed_delivery_retries_counts_and_does_not_log_the_transport_error(
    caplog,
):
    transport = FakeTransport(failures=99)
    manager = _manager(transport, retries=3)

    with caplog.at_level(logging.WARNING):
        assert manager.notify(Alert("surebet", "sig-fail", "title", "body")) is True
        assert manager.wait_idle()

    assert len(transport.attempts) == 3
    snapshot = manager.snapshot()
    assert snapshot["failed"] == 1
    assert snapshot["sent"] == 0
    assert "SUPERSECRET" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_a_transient_failure_retries_then_succeeds():
    transport = FakeTransport(failures=1)
    manager = _manager(transport, retries=3)

    assert manager.notify(Alert("surebet", "sig-retry", "title", "body")) is True
    assert manager.wait_idle()

    assert len(transport.attempts) == 2
    snapshot = manager.snapshot()
    assert snapshot["sent"] == 1
    assert snapshot["failed"] == 0


def test_signature_is_stable_inside_a_profit_bucket_and_changes_with_legs():
    base = _surebet(profit=4.2)
    moved_within_bucket = _surebet(profit=4.9)
    moved_across_bucket = _surebet(profit=5.1)
    different_leg = _surebet(profit=4.2)
    different_leg["stakes"][0]["bookmaker"] = "sportplus"

    assert surebet_signature(base) == surebet_signature(moved_within_bucket)
    assert surebet_signature(base) != surebet_signature(moved_across_bucket)
    assert surebet_signature(base) != surebet_signature(different_leg)


def test_surebet_alert_respects_the_threshold_and_uses_dashboard_labels():
    assert surebet_alert(_surebet(2.9), mode="prematch", min_profit_percent=3.0) is None

    alert = surebet_alert(_surebet(4.2), mode="prematch", min_profit_percent=3.0)
    assert alert is not None
    assert alert.kind == "surebet"
    assert alert.mode == "prematch"
    assert "Sarajevo - Zeljeznicar" in alert.title
    assert "mbet: GG @ 2.20" in alert.body
    assert "api_key" not in alert.body.lower()
    assert "x-api-key" not in alert.body.lower()


def test_feed_alerts_name_each_stale_book_and_ignore_never_scanned():
    assert feed_alerts("prematch", {"stale": True, "state": "never_scanned"}) == []

    alerts = feed_alerts(
        "prematch",
        {
            "stale": True,
            "state": "book_older_than_ttl",
            "stale_books": ["mbet", "mdshop"],
            "per_book": {
                "mbet": {"oldest_age_sec": 900},
                "mdshop": {"oldest_age_sec": 1200},
            },
        },
    )

    assert {alert.title for alert in alerts} == {
        "prematch feed stale: mbet",
        "prematch feed stale: mdshop",
    }
    assert all(alert.kind == "feed_stale" for alert in alerts)


def test_feed_state_alerts_cover_quarantine_and_degraded_books():
    alerts = quarantine_alerts(
        "live",
        {
            "mbet": {
                "state": "quarantined",
                "name": "MBet",
                "reasons": ["stale_prices", "outlier_rate"],
            },
            "maxbet": {
                "state": "degraded",
                "name": "MaxBet",
                "reasons": ["missing_markets"],
            },
            "mdshop": {"state": "healthy", "reasons": []},
        },
    )

    by_kind = {alert.kind: alert for alert in alerts}
    assert set(by_kind) == {"book_quarantined", "book_degraded"}
    assert "stale_prices" in by_kind["book_quarantined"].body
    assert "missing_markets" in by_kind["book_degraded"].body


def test_a_book_failure_alert_waits_for_the_backoff_threshold():
    assert book_failure_alert("prematch", "mbet", 2, 3) is None
    alert = book_failure_alert("prematch", "mbet", 3, 3)
    assert alert is not None
    assert alert.kind == "book_failing"


def test_resource_alerts_fire_only_over_budget():
    assert resource_alerts(
        "prematch",
        cache_bytes=10,
        cache_budget_bytes=20,
        rss_mb=900,
        rss_budget_mb=1024,
    ) == []

    alerts = resource_alerts(
        "prematch",
        cache_bytes=30,
        cache_budget_bytes=20,
        rss_mb=1100,
        rss_budget_mb=1024,
    )
    assert {alert.kind for alert in alerts} == {"cache_budget", "rss_budget"}


def test_health_reports_alert_counters_without_transport_secrets(monkeypatch):
    monkeypatch.setattr(
        api,
        "alert_manager",
        AlertManager([WebhookTransport("https://example.invalid/hook?token=SECRET")]),
    )

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["alerts"]["enabled"] is True
    assert payload["alerts"]["transports"] == ["webhook"]
    assert payload["alerts"]["sent"] == 0
    assert "SECRET" not in response.text
    assert "memory" in payload
    assert isinstance(payload["memory"]["over_budget"], bool)


def test_a_completed_scan_queues_only_above_threshold_surebets(monkeypatch):
    transport = FakeTransport()
    manager = _manager(transport)
    monkeypatch.setattr(api, "alert_manager", manager)
    monkeypatch.setattr(api, "_feed_integrity", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_book_failures", {})
    status = api.ScanStatus(
        last_scan_time=datetime.now(UTC).replace(tzinfo=None)
    )

    api._notify_scan_alerts(
        "prematch", [_surebet(4.2), _surebet(0.3)], status, [], cache_bytes=1
    )
    assert manager.wait_idle()

    assert [alert.kind for alert in transport.attempts] == ["surebet"]


def test_alert_evaluation_cannot_fail_a_scan(monkeypatch):
    class ExplodingManager:
        enabled = True
        min_profit_percent = 3.0

        def notify(self, alert):
            raise RuntimeError("alert builder broke")

    monkeypatch.setattr(api, "alert_manager", ExplodingManager())
    status = api.ScanStatus(
        last_scan_time=datetime.now(UTC).replace(tzinfo=None)
    )

    # The helper is the scan's boundary: it must swallow its own diagnostics.
    api._notify_scan_alerts("prematch", [_surebet(4.2)], status, [], cache_bytes=1)


def test_null_transport_accepts_a_message_without_side_effects():
    NullTransport().send(Alert("surebet", "sig", "title", "body"))
