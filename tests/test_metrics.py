"""P1-2: Prometheus counters/gauges and the structured scan log."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from models.schemas import Match
from server import api
from server import app as app_module
from server.app import app
from server.observability import JsonLogFormatter, metrics


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


# ─── The registry and the endpoint ──────────────────────────────────────────


def test_registry_renders_prometheus_text():
    metrics.inc("bh_test_total", 2, mode="prematch")
    metrics.inc("bh_test_total", 3, mode="live")
    metrics.set_gauge("bh_test_gauge", 4.5, label='a"b\nc')

    text = metrics.render()

    assert "# TYPE bh_test_total counter" in text
    assert 'bh_test_total{mode="prematch"} 2' in text
    assert 'bh_test_total{mode="live"} 3' in text
    assert "# TYPE bh_test_gauge gauge" in text
    assert 'bh_test_gauge{label="a\\"b\\nc"} 4.5' in text


def test_metrics_endpoint_returns_text_without_a_live_server():
    metrics.inc("bh_scans_started_total", 3, mode="prematch")

    response = TestClient(app).get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'bh_scans_started_total{mode="prematch"} 3' in body
    assert "# TYPE bh_rss_bytes gauge" in body
    assert "bh_last_scan_age_seconds" in body
    assert "bh_cache_size_bytes" in body


def test_metrics_endpoint_is_protected_like_other_api_routes(monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret")
    client = TestClient(app)

    assert client.get("/api/metrics").status_code == 401
    allowed = client.get("/api/metrics", headers={"X-API-Key": "secret"})
    assert allowed.status_code == 200


# ─── A scan's counters and its one completion line ──────────────────────────


def _fake_match(bookmaker: str, scan_time: datetime | None) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="Premijer Liga BiH",
        kickoff=(scan_time or datetime.now(UTC).replace(tzinfo=None))
        + timedelta(hours=3),
        fetched_at=scan_time or datetime.now(UTC).replace(tzinfo=None),
        markets=[],
    )


@pytest.fixture
def isolated_scan(monkeypatch):
    """Run a scan without touching persisted state or any real scraper."""
    snapshot = {
        "enabled": dict(api._bookmaker_enabled),
        "status": api.scan_status.model_dump(),
        "surebets": list(api.cached_surebets),
        "matches": list(api.cached_matches),
        "report": list(api.cached_match_groups_report),
        "per_bookie": dict(api.cached_per_bookie),
        "candidates": dict(api.pending_candidates),
        "integrity": dict(api._feed_integrity.get("prematch") or {}),
        "opportunity": dict(api._opportunity_by_mode),
        "lifetimes": {k: dict(v) for k, v in api._crossing_lifetimes.items()},
        "history": list(api._opportunity_history),
        "pairing": dict(api._pairing_summary),
    }

    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "_save_opportunity_metrics", lambda *a, **k: None)
    monkeypatch.setattr(api, "_save_feed_integrity", lambda *a, **k: None)
    monkeypatch.setattr(api, "_append_history", lambda *a, **k: None)
    monkeypatch.setattr(api, "AUTO_LEARN_MAPPINGS", False)

    class FakeMatcher:
        def group_matches(self, matches):
            return []

        def get_match_report(self, groups):
            return []

    monkeypatch.setattr(api, "MatchMatcher", FakeMatcher)

    async def fake_collect(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(api, "_collect_candidates", fake_collect)

    class FakeScraper:
        def __init__(self, bookmaker: str):
            self.bookmaker = bookmaker

        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            return [_fake_match(self.bookmaker, scan_time)]

    for book in ("mbet", "mdshop"):
        monkeypatch.setitem(api.SCRAPERS, book, lambda b=book: FakeScraper(b))
    for book in api.BOOKMAKERS:
        api._bookmaker_enabled[book] = book in ("mbet", "mdshop")

    yield

    api._bookmaker_enabled.clear()
    api._bookmaker_enabled.update(snapshot["enabled"])
    for key, value in snapshot["status"].items():
        setattr(api.scan_status, key, value)
    api.cached_surebets[:] = snapshot["surebets"]
    api.cached_matches[:] = snapshot["matches"]
    api.cached_match_groups_report[:] = snapshot["report"]
    api.cached_per_bookie.clear()
    api.cached_per_bookie.update(snapshot["per_bookie"])
    api.pending_candidates.clear()
    api.pending_candidates.update(snapshot["candidates"])
    api._feed_integrity["prematch"] = snapshot["integrity"]
    api._opportunity_by_mode = snapshot["opportunity"]
    api._crossing_lifetimes = snapshot["lifetimes"]
    api._opportunity_history[:] = snapshot["history"]
    api._pairing_summary.clear()
    api._pairing_summary.update(snapshot["pairing"])


def test_a_scan_emits_one_structured_completion_log(isolated_scan, caplog):
    with caplog.at_level(logging.INFO):
        asyncio.run(api.run_scan("prematch"))

    completion = [r for r in caplog.records if r.getMessage() == "scan complete"]
    assert len(completion) == 1
    record = completion[0]
    assert record.mode == "prematch"
    assert record.duration_seconds >= 0
    assert record.books == 2
    assert record.books_total == 2
    assert record.groups == 0
    assert record.surebets == 0
    assert record.drops == 0
    assert isinstance(record.cache_bytes, int)
    assert record.scan_id and record.scan_id != "-"

    # The same line, as a log collector would see it, carries no odds payload.
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "scan complete"
    assert "odds" not in json.dumps(payload).lower()


def test_a_scan_increments_the_counters_and_gauges(isolated_scan):
    asyncio.run(api.run_scan("prematch"))

    text = metrics.render()

    assert 'bh_scans_started_total{mode="prematch"} 1' in text
    assert 'bh_scans_completed_total{mode="prematch"} 1' in text
    assert 'bh_scans_failed_total{mode="prematch"} 0' not in text
    assert 'bh_book_results_total{book="mbet",mode="prematch",outcome="success"} 1' in text
    assert 'bh_book_results_total{book="mdshop",mode="prematch",outcome="success"} 1' in text
    assert 'bh_book_kinds_total{book="mbet",kind="ok",mode="prematch"} 1' in text
    assert 'bh_book_last_success_timestamp_seconds{book="mbet",mode="prematch"}' in text
    assert 'bh_book_kinds_total{book="mdshop",kind="ok",mode="prematch"} 1' in text
    assert 'bh_surebets_found{mode="prematch"} 0' in text
    assert 'bh_surebets_found_total{mode="prematch"} 0' in text
    assert 'bh_candidate_queue_size{mode="prematch"} 0' in text
    assert 'bh_scan_duration_seconds{mode="prematch"}' in text
    assert "bh_cache_size_bytes" in text
    # These two books are not Playwright books, so no browser slot was taken.
    assert "bh_browser_slots_in_use" not in text


def test_empty_and_failed_books_are_counted_separately(isolated_scan, monkeypatch):
    class EmptyScraper:
        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            return []

    class BrokenScraper:
        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            raise RuntimeError("feed down")

    monkeypatch.setitem(api.SCRAPERS, "mbet", lambda: EmptyScraper())
    monkeypatch.setitem(api.SCRAPERS, "mdshop", lambda: BrokenScraper())

    asyncio.run(api.run_scan("prematch"))

    text = metrics.render()
    assert 'bh_book_results_total{book="mbet",mode="prematch",outcome="empty"} 1' in text
    assert 'bh_book_results_total{book="mdshop",mode="prematch",outcome="error"} 1' in text
    assert 'bh_book_kinds_total{book="mbet",kind="empty",mode="prematch"} 1' in text
    assert 'bh_book_kinds_total{book="mdshop",kind="parse_error",mode="prematch"} 1' in text


def test_a_timeout_book_is_recorded_with_the_timeout_kind(isolated_scan, monkeypatch):
    class TimeoutScraper:
        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            raise httpx.ReadTimeout("feed did not answer")

    monkeypatch.setitem(api.SCRAPERS, "mbet", lambda: TimeoutScraper())

    asyncio.run(api.run_scan("prematch"))

    record = api._scan_cost["prematch"]["books"]["mbet"]
    assert record["kind"] == "timeout"
    assert record["outcome"] == "blocked"
    text = metrics.render()
    assert 'bh_book_kinds_total{book="mbet",kind="timeout",mode="prematch"} 1' in text
    # The historical metric label is unchanged for an exception.
    assert 'bh_book_results_total{book="mbet",mode="prematch",outcome="error"} 1' in text


def test_a_scan_shares_one_transport_client_and_closes_it(isolated_scan, monkeypatch):
    from scrapers.transport import transport_client

    clients = []

    class ClientScraper:
        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            async with transport_client("mbet", "prematch") as first:
                async with transport_client("mbet", "prematch") as second:
                    assert first is second
                    clients.append(first)
            return [_fake_match("mbet", scan_time)]

    monkeypatch.setitem(api.SCRAPERS, "mbet", lambda: ClientScraper())

    asyncio.run(api.run_scan("prematch"))

    assert clients
    assert all(client.is_closed for client in clients)


def test_a_failed_scan_is_counted_and_logged(isolated_scan, monkeypatch, caplog):
    class Boom:
        def group_matches(self, matches):
            raise RuntimeError("boom")

        def get_match_report(self, groups):
            return []

    monkeypatch.setattr(api, "MatchMatcher", Boom)

    with caplog.at_level(logging.ERROR):
        asyncio.run(api.run_scan("prematch"))

    text = metrics.render()
    assert 'bh_scans_failed_total{mode="prematch"} 1' in text
    failed = [r for r in caplog.records if r.getMessage() == "scan failed"]
    assert len(failed) == 1
    assert failed[0].mode == "prematch"
    assert failed[0].scan_id and failed[0].scan_id != "-"
