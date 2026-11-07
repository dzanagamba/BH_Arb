"""SR2-6: the per-book circuit breaker and the kinds that open it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scrapers.breaker import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    BookCircuitBreaker,
    breaker_for,
    reset_breakers,
)
from scrapers.errors import ScrapeKind
from server import api
from server.app import app
from server.observability import metrics


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _breaker(
    *,
    failure_threshold: int = 3,
    open_seconds: float = 300.0,
    max_open_seconds: float = 3600.0,
) -> tuple[BookCircuitBreaker, FakeClock]:
    clock = FakeClock()
    return (
        BookCircuitBreaker(
            "prematch",
            "mbet",
            clock=clock,
            failure_threshold=failure_threshold,
            open_seconds=open_seconds,
            max_open_seconds=max_open_seconds,
        ),
        clock,
    )


def test_a_soft_failure_streak_opens_at_the_threshold_and_recovers_on_a_probe():
    breaker, clock = _breaker()

    for _ in range(2):
        breaker.record(ScrapeKind.TIMEOUT)
    assert breaker.snapshot()["state"] == CLOSED
    assert breaker.allow() is True

    breaker.record(ScrapeKind.TRANSPORT)
    snapshot = breaker.snapshot()
    assert snapshot["state"] == OPEN
    assert snapshot["consecutive_failures"] == 3
    assert snapshot["cooldown_remaining_seconds"] == pytest.approx(300.0)
    assert breaker.allow() is False

    # The cooldown ends: exactly one probe is allowed.
    clock.advance(300.5)
    assert breaker.snapshot()["state"] == HALF_OPEN
    assert breaker.allow() is True
    assert breaker.allow() is False

    breaker.record(ScrapeKind.OK)
    assert breaker.snapshot()["state"] == CLOSED
    assert breaker.snapshot()["consecutive_failures"] == 0
    assert breaker.allow() is True


def test_a_dead_probe_reopens_with_a_longer_cooldown():
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record(ScrapeKind.EMPTY)
    assert breaker.snapshot()["opens"] == 1

    clock.advance(301)
    assert breaker.allow() is True  # the probe
    breaker.record(ScrapeKind.UPSTREAM_5XX)

    snapshot = breaker.snapshot()
    assert snapshot["state"] == OPEN
    assert snapshot["opens"] == 2
    assert snapshot["cooldown_remaining_seconds"] == pytest.approx(600.0)


@pytest.mark.parametrize("kind", [ScrapeKind.BLOCKED, ScrapeKind.RATE_LIMITED])
def test_a_site_refusal_opens_immediately_and_for_longer(kind):
    breaker, _clock = _breaker()

    breaker.record(kind)

    snapshot = breaker.snapshot()
    assert snapshot["state"] == OPEN
    # One failure is enough, and the cooldown is twice a soft failure's.
    assert snapshot["consecutive_failures"] == 1
    assert snapshot["cooldown_remaining_seconds"] == pytest.approx(600.0)


@pytest.mark.parametrize(
    "kind", [ScrapeKind.PARSE_ERROR, ScrapeKind.SCHEMA_DRIFT, ScrapeKind.SKIPPED]
)
def test_our_own_failures_never_open_the_breaker(kind):
    breaker, _clock = _breaker(failure_threshold=1)

    for _ in range(10):
        breaker.record(kind)

    snapshot = breaker.snapshot()
    assert snapshot["state"] == CLOSED
    assert snapshot["consecutive_failures"] == 0
    assert snapshot["opens"] == 0
    assert snapshot["last_kind"] == kind.value


def test_a_neutral_outcome_releases_the_half_open_probe():
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record(ScrapeKind.TIMEOUT)
    clock.advance(301)
    assert breaker.allow() is True  # the probe starts
    assert breaker.allow() is False  # only one in flight

    breaker.record(ScrapeKind.PARSE_ERROR)  # our bug: not the site refusing us
    assert breaker.snapshot()["state"] == HALF_OPEN
    assert breaker.allow() is True  # the probe slot is free again


def test_success_resets_the_escalation():
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record(ScrapeKind.TIMEOUT)
    clock.advance(301)
    breaker.allow()
    breaker.record(ScrapeKind.TIMEOUT)  # the probe failed: second open
    assert breaker.snapshot()["opens"] == 2

    clock.advance(601)
    breaker.allow()
    breaker.record(ScrapeKind.OK)
    assert breaker.snapshot()["opens"] == 0

    # A fresh streak starts from the base cooldown again.
    for _ in range(3):
        breaker.record(ScrapeKind.TIMEOUT)
    assert breaker.snapshot()["cooldown_remaining_seconds"] == pytest.approx(300.0)


def test_the_cooldown_is_capped():
    breaker, clock = _breaker(failure_threshold=1, open_seconds=300.0, max_open_seconds=900.0)

    for _ in range(8):
        breaker.record(ScrapeKind.TIMEOUT)
        clock.advance(10_000)
        breaker.allow()  # the half-open probe
    breaker.record(ScrapeKind.TIMEOUT)  # the last probe failed: re-open

    snapshot = breaker.snapshot()
    assert snapshot["state"] == OPEN
    assert 0 < snapshot["cooldown_remaining_seconds"] <= 900.0


def test_the_snapshot_carries_no_payload_and_a_live_cooldown():
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record(ScrapeKind.TIMEOUT)
    clock.advance(100)

    snapshot = breaker.snapshot()

    assert set(snapshot) == {
        "bookmaker",
        "state",
        "consecutive_failures",
        "opens",
        "cooldown_remaining_seconds",
        "last_kind",
    }
    assert snapshot["cooldown_remaining_seconds"] == pytest.approx(200.0)
    assert snapshot["last_kind"] == "timeout"


def test_invalid_configuration_is_refused():
    with pytest.raises(ValueError):
        BookCircuitBreaker("prematch", "mbet", failure_threshold=0)
    with pytest.raises(ValueError):
        BookCircuitBreaker("prematch", "mbet", open_seconds=0)


def test_the_registry_keeps_one_breaker_per_book_and_feed():
    reset_breakers()
    try:
        first = breaker_for("prematch", "mbet", failure_threshold=1)
        assert first is breaker_for("prematch", "mbet", failure_threshold=9)
        assert first is not breaker_for("live", "mbet")
        assert first is not breaker_for("prematch", "mdshop")
        # Creation options win; a later call cannot retune a live breaker.
        first.record(ScrapeKind.BLOCKED)
        assert breaker_for("prematch", "mbet", failure_threshold=9).state == OPEN

        reset_breakers()
        assert breaker_for("prematch", "mbet") is not first
    finally:
        reset_breakers()


def test_health_reports_one_breaker_for_every_book_and_feed():
    reset_breakers()
    try:
        payload = TestClient(app).get("/api/health").json()
        breakers = payload["scheduler"]["breakers"]
        expected = {
            f"{mode}/{book}"
            for mode in ("prematch", "live")
            for book in api.BOOKMAKERS
        }
        assert set(breakers) == expected
        assert breakers["prematch/mbet"]["state"] == CLOSED
        assert breakers["prematch/mbet"]["consecutive_failures"] == 0
    finally:
        reset_breakers()


def test_metrics_expose_the_state_failures_and_cooldown():
    reset_breakers()
    metrics.reset_values()
    try:
        api._record_book_result("prematch", "mbet", ScrapeKind.BLOCKED)
        api._record_breaker_metrics("prematch")

        text = metrics.render()
        assert 'bh_book_breaker_state{book="mbet",mode="prematch",state="open"} 1' in text
        assert 'bh_book_breaker_state{book="mbet",mode="prematch",state="closed"} 0' in text
        assert 'bh_book_breaker_state{book="mdshop",mode="prematch",state="closed"} 1' in text
        assert 'bh_book_breaker_failures{book="mbet",mode="prematch"} 1' in text
        assert 'bh_book_breaker_cooldown_seconds{book="mbet",mode="prematch"} 600' in text
    finally:
        reset_breakers()
        metrics.reset_values()
