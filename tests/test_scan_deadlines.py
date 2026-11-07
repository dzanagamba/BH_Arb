"""SR2-5: one hung adapter is cut off and the rest of the scan still prices."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from config.settings import BROWSER_CONCURRENCY
from models.schemas import Match
from scrapers import transport
from scrapers.breaker import reset_breakers
from scrapers.errors import ScrapeKind
from server import api


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
    """Run a scan without persisted state, learning, alerts or real scrapers."""
    snapshot = {
        "enabled": dict(api._bookmaker_enabled),
        "status": api.scan_status.model_dump(),
        "surebets": list(api.cached_surebets),
        "matches": list(api.cached_matches),
        "report": list(api.cached_match_groups_report),
        "per_bookie": dict(api.cached_per_bookie),
        "candidates": dict(api.pending_candidates),
        "integrity": dict(api._feed_integrity.get("prematch") or {}),
        # A scan updates these too; leaving them behind would let one test's
        # zero-result streak decide another test's alert.
        "opportunity": dict(api._opportunity_by_mode),
        "lifetimes": {k: dict(v) for k, v in api._crossing_lifetimes.items()},
        "history": list(api._opportunity_history),
        "streaks": {k: dict(v) for k, v in api._zero_result_streaks.items()},
    }
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "_save_opportunity_metrics", lambda *a, **k: None)
    monkeypatch.setattr(api, "_save_feed_integrity", lambda *a, **k: None)
    monkeypatch.setattr(api, "_append_history", lambda *a, **k: None)
    monkeypatch.setattr(api, "AUTO_LEARN_MAPPINGS", False)

    async def fake_collect(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(api, "_collect_candidates", fake_collect)

    for book in api.BOOKMAKERS:
        api._bookmaker_enabled[book] = False

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
    api._opportunity_by_mode.clear()
    api._opportunity_by_mode.update(snapshot["opportunity"])
    api._crossing_lifetimes.clear()
    api._crossing_lifetimes.update(snapshot["lifetimes"])
    api._opportunity_history[:] = snapshot["history"]
    api._zero_result_streaks.clear()
    api._zero_result_streaks.update(snapshot["streaks"])


def _short_adapter_deadline(monkeypatch, book: str, seconds: float) -> None:
    """Give one book a deadline it cannot meet, without touching the others."""
    policy = replace(transport.policy_for(book, "prematch"), adapter_deadline=seconds)
    monkeypatch.setitem(transport.POLICIES, (book, "prematch"), policy)


class _HangingScraper:
    def __init__(self, name: str) -> None:
        self.name = name

    async def scrape(self, live=False, scan_time=None, sports_wanted=None):
        await asyncio.sleep(3600)
        return []  # pragma: no cover - the deadline always wins


class _FastScraper:
    async def scrape(self, live=False, scan_time=None, sports_wanted=None):
        await asyncio.sleep(0)
        return [_fake_match("mdshop", scan_time)]


def test_a_hung_book_is_cut_off_and_the_other_book_still_prices(
    isolated_scan, monkeypatch
):
    _short_adapter_deadline(monkeypatch, "mbet", 0.05)
    api._bookmaker_enabled["mbet"] = True
    api._bookmaker_enabled["mdshop"] = True
    monkeypatch.setitem(api.SCRAPERS, "mbet", lambda: _HangingScraper("mbet"))
    monkeypatch.setitem(api.SCRAPERS, "mdshop", lambda: _FastScraper())

    asyncio.run(api.run_scan("prematch"))

    # The hung book is reported as a timeout and is missing from the scan.
    record = api._scan_cost["prematch"]["books"]["mbet"]
    assert record["kind"] == "timeout"
    assert "adapter deadline" in record["note"]
    assert record["matches"] == 0

    # The other book completed and its price is served, so the scan priced.
    served = {row["bookmaker"] for row in api.cached_matches}
    assert served == {"mdshop"}
    fast = api._scan_cost["prematch"]["books"]["mdshop"]
    assert fast["kind"] == "ok"
    assert fast["matches"] == 1

    assert api.scan_status.is_scanning is False
    assert api.scan_status.current_bookmaker == ""
    assert any("adapter deadline" in error for error in api.scan_status.errors)


def test_a_scan_deadline_cancels_the_stragglers_and_keeps_finished_books(
    isolated_scan, monkeypatch
):
    monkeypatch.setattr(api, "SCRAPER_SCAN_TIMEOUT_SECONDS", 0.2)
    api._bookmaker_enabled["mbet"] = True
    api._bookmaker_enabled["mdshop"] = True
    monkeypatch.setitem(api.SCRAPERS, "mbet", lambda: _HangingScraper("mbet"))
    monkeypatch.setitem(api.SCRAPERS, "mdshop", lambda: _FastScraper())

    asyncio.run(api.run_scan("prematch"))

    record = api._scan_cost["prematch"]["books"]["mbet"]
    assert record["kind"] == "timeout"
    assert record["note"] == "cancelled at the scan deadline"

    # The book that finished before the deadline is still served.
    assert {row["bookmaker"] for row in api.cached_matches} == {"mdshop"}
    assert any("scan deadline" in error for error in api.scan_status.errors)
    assert not any("Scan error:" in error for error in api.scan_status.errors)
    assert api.scan_status.is_scanning is False


def test_cancellation_closes_a_browser_book_and_releases_its_slot(
    isolated_scan, monkeypatch
):
    monkeypatch.setattr(api, "SCRAPER_SCAN_TIMEOUT_SECONDS", 0.2)
    api._bookmaker_enabled["wwin"] = True

    class FakeResources:
        closed = False

        async def close(self) -> None:
            self.closed = True

    resources = FakeResources()

    class BrowserScraper:
        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            try:
                await asyncio.sleep(3600)
            finally:
                # The same shape as wwin/mozzartbet/admiralbet: cleanup in
                # ``finally``, which runs when the deadline cancels the task.
                await resources.close()

    monkeypatch.setitem(api.SCRAPERS, "wwin", lambda: BrowserScraper())

    asyncio.run(api.run_scan("prematch"))

    assert resources.closed is True
    assert api._browser_sem._value == BROWSER_CONCURRENCY
    assert api._scan_cost["prematch"]["books"]["wwin"]["kind"] == "timeout"


def test_a_scheduled_scan_skips_a_book_with_an_open_breaker(
    isolated_scan, monkeypatch
):
    reset_breakers()
    api._bookmaker_enabled["mbet"] = True
    calls: list[int] = []

    class WouldRun:
        async def scrape(self, live=False, scan_time=None, sports_wanted=None):
            calls.append(1)
            return []

    monkeypatch.setitem(api.SCRAPERS, "mbet", lambda: WouldRun())
    # One refusal is enough for the breaker to open (SR2-6).
    api._record_book_result("prematch", "mbet", ScrapeKind.BLOCKED)
    try:
        asyncio.run(api.run_scan("prematch", scheduled=True))
    finally:
        reset_breakers()

    assert calls == []  # the scraper was never constructed nor run
    record = api._scan_cost["prematch"]["books"]["mbet"]
    assert record["kind"] == "skipped"
    assert record["note"] == "circuit breaker open"
    assert any("circuit breaker open" in error for error in api.scan_status.errors)

    # A manual scan ignores the breaker: it is the operator asking for data.
    calls.clear()
    api._bookmaker_enabled["mbet"] = True
    asyncio.run(api.run_scan("prematch", scheduled=False))
    assert calls == [1]
