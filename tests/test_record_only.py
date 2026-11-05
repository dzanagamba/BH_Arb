"""P3-7: record-only scans store compact rows and publish no live surebet."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from models.schemas import Market, MarketType, Match, OddsValue, Surebet, SurebetStake
from server import api
from server.app import app
from server.paper import PaperStore, compact_opportunity, opportunity_key

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")

KICKOFF = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=6)
BOOKS = ("mbet", "wwin", "sportplus")
ODDS = {
    "mbet": {"1": 2.2, "X": 3.4, "2": 3.4},
    "wwin": {"1": 2.0, "X": 4.0, "2": 3.3},
    "sportplus": {"1": 2.0, "X": 3.5, "2": 4.0},
}


def _surebet() -> Surebet:
    legs = [("mbet", "1", 2.2), ("wwin", "X", 4.0), ("sportplus", "2", 4.0)]
    margin = sum(1.0 / odds for _, _, odds in legs)
    stakes = []
    for bookmaker, label, odds in legs:
        stake = round(100.0 * (1.0 / odds) / margin, 2)
        stakes.append(
            SurebetStake(
                bookmaker=bookmaker,
                outcome_label=label,
                odds=odds,
                stake=stake,
                potential_return=round(stake * odds, 2),
                market_type="1x2",
                selection=label,
            )
        )
    return Surebet(
        id="sb-record-1",
        sport="football",
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="BiH - Premier Liga",
        kickoff=KICKOFF,
        market_type=MarketType.MATCH_RESULT,
        profit_percent=round((1.0 / margin - 1.0) * 100.0, 2),
        total_margin=round(margin, 4),
        raw_margin=round(margin, 6),
        stakes=stakes,
        found_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _match(bookmaker: str) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="BiH - Premier Liga",
        kickoff=KICKOFF,
        event_id=f"event-{bookmaker}",
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label=label, value=odds)
                    for label, odds in ODDS[bookmaker].items()
                ],
            )
        ],
    )


@pytest.fixture
def scan_state(monkeypatch, tmp_path):
    """Keep the shared scan state, caches and ledger inside this test."""
    store = PaperStore(str(tmp_path / "paper.sqlite3"))
    store.initialize()
    monkeypatch.setattr(api, "_paper_store", store)
    monkeypatch.setattr(api, "_save_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_append_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_opportunity_metrics", lambda: None)
    monkeypatch.setattr(api, "_save_feed_integrity", lambda: None)
    monkeypatch.setattr(api, "_save_coverage_budget", lambda: None)
    monkeypatch.setattr(api, "PRICE_GUARD_ENABLED", False)

    class _Scraper:
        book: str = ""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def scrape(
            self, live: bool = False, scan_time: Any = None, sports_wanted: Any = None
        ) -> list[Match]:
            return [_match(book) for book in BOOKS if self.book == book]

    for book in api.BOOKMAKERS:
        monkeypatch.setitem(api._bookmaker_enabled, book, book in BOOKS)
        if book in BOOKS:
            monkeypatch.setitem(
                api.SCRAPERS,
                book,
                type(f"Scraper_{book}", (_Scraper,), {"book": book}),
            )

    snapshot = {
        "surebets": list(api.cached_surebets),
        "matches": list(api.cached_matches),
        "report": list(api.cached_match_groups_report),
        "status": api.scan_status.model_dump(),
        "run_mode": dict(api._last_run_mode),
        "counts": dict(api._recorded_counts),
    }
    api.cached_surebets.clear()
    try:
        yield store
    finally:
        api.cached_surebets[:] = snapshot["surebets"]
        api.cached_matches[:] = snapshot["matches"]
        api.cached_match_groups_report[:] = snapshot["report"]
        for key, value in snapshot["status"].items():
            setattr(api.scan_status, key, value)
        api._last_run_mode.clear()
        api._last_run_mode.update(snapshot["run_mode"])
        api._recorded_counts.clear()
        api._recorded_counts.update(snapshot["counts"])


def test_a_compact_snapshot_has_the_key_market_odds_book_and_verdict():
    surebet = _surebet()
    record = compact_opportunity(
        surebet,
        feed_mode="prematch",
        run_mode="record_only",
        scan_time=datetime(2026, 11, 5, 12, 0),
    )

    assert record["key"] == opportunity_key(surebet)
    assert record["gate_verdict"] == "verified"
    assert record["market_type"] == "1x2"
    assert record["best_odds"] == 4.0
    assert record["best_book"] == "wwin"
    assert record["recorded_at"] == "2026-11-05T12:00:00"
    assert {leg["bookmaker"] for leg in record["legs"]} == {
        "mbet",
        "wwin",
        "sportplus",
    }
    assert all(leg["odds"] > 1.0 for leg in record["legs"])


def test_record_only_scan_never_writes_a_live_surebet(scan_state):
    asyncio.run(api.run_scan("prematch", run_mode="record_only"))

    assert api.scan_status.errors == []
    assert api.scan_status.run_mode == "record_only"
    assert api.scan_status.recorded_opportunities >= 1
    assert api.cached_surebets == []
    body = asyncio.run(api.get_results("prematch"))
    assert body["surebets"] == []
    assert body["surebets_count"] == 0
    assert body["run_mode"] == "record_only"
    assert body["recorded_opportunities"] >= 1

    records = scan_state.list_opportunities()
    assert records
    assert all(record["gate_verdict"] == "verified" for record in records)
    assert scan_state.list_positions() == []


def test_advisory_scan_is_unchanged_after_a_record_only_run(scan_state):
    asyncio.run(api.run_scan("prematch", run_mode="record_only"))
    asyncio.run(api.run_scan("prematch"))

    assert api.scan_status.errors == []
    assert api.scan_status.run_mode == "advisory"
    assert api.cached_surebets
    body = asyncio.run(api.get_results("prematch"))
    assert body["run_mode"] == "advisory"
    assert body["recorded_opportunities"] == 0
    assert body["surebets_count"] == len(body["surebets"])


def test_the_scan_api_rejects_an_unknown_run_mode():
    client = TestClient(app)
    response = client.post("/api/scan?mode=prematch&run_mode=free_money")
    assert response.status_code == 400


def test_the_dashboard_exposes_the_run_mode_and_hides_live_surebets():
    assert 'id="filter-run-mode"' in HTML
    assert 'value="record_only"' in HTML
    assert 'value="paper"' in HTML
    assert "scanRunMode" in JS
    assert "run_mode=${encodeURIComponent(scanRunMode)}" in JS
    assert "function renderRunModeBanner" in JS
    assert "No live surebet is shown" in JS
