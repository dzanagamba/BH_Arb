"""M2-3: /api/health serves a cached summary, and its live fields stay live.

WHAT THESE TESTS PROVE
----------------------
The expensive blocks (parser contracts, the admissibility baseline, retention,
the cached-data walks) are built once per ``HEALTH_CACHE_SECONDS`` instead of on
every poll, the TTL and the disable switch behave, the payload's live fields
(scanning state, counters, breakers, book health) are recomputed per request,
the key set is unchanged apart from the new ``health_cache`` block, and a scan
drops the cache so a finished scan is visible on the next poll.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove the endpoint is fast on a populated scan (that is the measured
before/after in the execution log), and they say nothing about pricing: health
is a diagnostic and no gate reads it.
"""

from __future__ import annotations

import asyncio

import pytest

import server.api as api

#: The keys /api/health served before M2-3; the cache may add, never remove.
SHIPPED_KEYS = {
    "admissibility_audit",
    "ai_available",
    "alerts",
    "book_health",
    "cache",
    "candidate_blocker_trend",
    "candidate_blockers",
    "candidate_remediation",
    "cardinality_floor",
    "closing_capture",
    "coverage_budget",
    "coverage_slo",
    "coverage_trend",
    "deep_link_declaration_audit",
    "deep_link_declaration_source",
    "deep_link_declarations",
    "feed_integrity",
    "freshness",
    "live",
    "live_matches_cached",
    "live_pairing",
    "live_pending_candidates",
    "live_surebets_cached",
    "live_unverified_links",
    "mapping_coverage",
    "mapping_learning",
    "matches_cached",
    "memory",
    "odds_ttl_sec",
    "opportunity_metrics",
    "pairing",
    "pairing_trend",
    "parser_contracts",
    "pending_candidates",
    "prematch",
    "retention",
    "scan_cost",
    "scanning",
    "scheduler",
    "skin_detection",
    "stale_prices",
    "status",
    "suppressed_candidates",
    "surebets_cached",
    "unmapped_markets",
    "unmapped_markets_by_book",
    "unverified_links",
    "verified_groups",
    "zero_result_streaks",
}


class Clock:
    """A monotonic clock the tests advance by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(api, "_health_clock", clock)
    monkeypatch.setattr(api, "HEALTH_CACHE_SECONDS", 2.0)
    api._reset_health_cache()
    yield clock
    api._reset_health_cache()


@pytest.fixture
def builds(monkeypatch, clock):
    """Count each expensive builder, so a cache hit is a zero-count call."""
    counts = {"contracts": 0, "admissibility": 0, "retention": 0}
    real = {
        "contracts": api.contract_health,
        "admissibility": api.admissibility_health,
        "retention": api.retention_health,
    }

    def counting(name):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return real[name](*args, **kwargs)

        return wrapper

    monkeypatch.setattr(api, "contract_health", counting("contracts"))
    monkeypatch.setattr(api, "admissibility_health", counting("admissibility"))
    monkeypatch.setattr(api, "retention_health", counting("retention"))
    return counts


def _health() -> dict:
    return asyncio.run(api.health())


def test_a_cache_hit_does_not_rebuild_the_summary(builds, clock):
    first = _health()
    assert builds == {"contracts": 1, "admissibility": 1, "retention": 1}
    assert first["health_cache"]["age_seconds"] == 0.0

    clock.now += 0.5
    second = _health()

    assert builds == {"contracts": 1, "admissibility": 1, "retention": 1}
    assert second["health_cache"]["age_seconds"] == 0.5
    assert second["health_cache"]["generated_at"] == first["health_cache"]["generated_at"]
    assert second["parser_contracts"] == first["parser_contracts"]


def test_the_ttl_expiry_rebuilds(builds, clock):
    _health()
    clock.now += 2.5

    rebuilt = _health()

    assert builds == {"contracts": 2, "admissibility": 2, "retention": 2}
    assert rebuilt["health_cache"]["age_seconds"] == 0.0


def test_zero_seconds_disables_the_cache(builds, clock, monkeypatch):
    monkeypatch.setattr(api, "HEALTH_CACHE_SECONDS", 0.0)

    _health()
    _health()

    assert builds == {"contracts": 2, "admissibility": 2, "retention": 2}
    assert _health()["health_cache"]["ttl_seconds"] == 0.0


def test_live_fields_are_not_cached(clock, monkeypatch):
    monkeypatch.setattr(api.scan_status, "is_scanning", False)
    first = _health()
    assert first["scanning"] is False

    monkeypatch.setattr(api.scan_status, "is_scanning", True)
    api.cached_surebets.append({"probe": True})
    try:
        second = _health()
    finally:
        api.cached_surebets.pop()

    assert second["scanning"] is True
    assert second["surebets_cached"] == first["surebets_cached"] + 1


def test_the_payload_keeps_every_shipped_key(clock):
    body = _health()

    assert set(body) == SHIPPED_KEYS | {"health_cache"}
    assert set(body["health_cache"]) == {"ttl_seconds", "generated_at", "age_seconds"}
    assert body["health_cache"]["ttl_seconds"] == 2.0


def test_a_scan_drops_the_cached_summary(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(api, "_reset_health_cache", lambda: calls.append(1))
    for attribute in (
        "_save_cache",
        "_save_opportunity_metrics",
        "_save_feed_integrity",
        "_append_history",
    ):
        monkeypatch.setattr(api, attribute, lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "AUTO_LEARN_MAPPINGS", False)
    for book in api.BOOKMAKERS:
        monkeypatch.setitem(api._bookmaker_enabled, book, False)

    asyncio.run(api.run_scan("prematch"))

    # Once when the scan starts and once when it finishes: the next poll sees
    # the new state instead of the summary built before the scan.
    assert len(calls) == 2
