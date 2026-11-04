"""P0-4: runtime freshness is a state, not a startup-only cache check.

The API keeps serving cached rows so an operator can still diagnose a bad feed,
but a scan past its TTL must say so explicitly and must refuse to present the
result as current. These tests exercise the real `/api/results` payload with
controlled scan and per-book timestamps, not a separate freshness model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from config.settings import LIVE_ODDS_TTL_SECONDS, ODDS_TTL_SECONDS
from engine.arbitrage import ArbitrageEngine
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from server import api
from server.app import app

client = TestClient(app)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _row(bookmaker: str, age_sec: float) -> dict:
    return {
        "bookmaker": bookmaker,
        "fetched_at": (_now() - timedelta(seconds=age_sec)).isoformat(),
    }


def _set_scan(
    mode: str,
    *,
    scan_age_sec: float | None,
    rows: list[dict],
) -> None:
    status = api.live_status if mode == "live" else api.scan_status
    matches = api.cached_live_matches if mode == "live" else api.cached_matches
    status.last_scan_time = (
        None if scan_age_sec is None else _now() - timedelta(seconds=scan_age_sec)
    )
    matches[:] = rows


@pytest.fixture(autouse=True)
def restore_state():
    saved = {
        "prematch_time": api.scan_status.last_scan_time,
        "live_time": api.live_status.last_scan_time,
        "matches": list(api.cached_matches),
        "live_matches": list(api.cached_live_matches),
        "surebets": list(api.cached_surebets),
        "live_surebets": list(api.cached_live_surebets),
    }
    api.cached_surebets.clear()
    api.cached_live_surebets.clear()
    yield
    api.scan_status.last_scan_time = saved["prematch_time"]
    api.live_status.last_scan_time = saved["live_time"]
    api.cached_matches[:] = saved["matches"]
    api.cached_live_matches[:] = saved["live_matches"]
    api.cached_surebets[:] = saved["surebets"]
    api.cached_live_surebets[:] = saved["live_surebets"]


def _results(mode: str = "prematch") -> dict:
    response = client.get(f"/api/results?mode={mode}")
    assert response.status_code == 200, response.text
    return response.json()


def test_fresh_scan_reports_age_ttl_and_per_book_freshness():
    _set_scan("prematch", scan_age_sec=30, rows=[_row("mdshop", 25), _row("wwin", 10)])

    freshness = _results()["freshness"]

    assert freshness["mode"] == "prematch"
    assert freshness["ttl_sec"] == ODDS_TTL_SECONDS
    assert freshness["stale"] is False
    assert freshness["state"] == "fresh"
    assert freshness["stale_books"] == []
    assert 25 <= freshness["age_sec"] <= 35
    assert freshness["scan_time"] is not None

    assert freshness["per_book"]["mdshop"]["stale"] is False
    assert freshness["per_book"]["mdshop"]["oldest_fetched_at"] is not None
    assert freshness["per_book"]["mdshop"]["newest_fetched_at"] is not None
    assert 20 <= freshness["per_book"]["mdshop"]["oldest_age_sec"] <= 35
    assert freshness["per_book"]["wwin"]["stale"] is False


def test_near_expiry_is_fresh_and_one_second_past_the_ttl_is_stale():
    _set_scan(
        "prematch",
        scan_age_sec=ODDS_TTL_SECONDS - 5,
        rows=[_row("mdshop", ODDS_TTL_SECONDS - 5)],
    )
    near = _results()["freshness"]
    assert near["stale"] is False
    assert near["state"] == "fresh"

    _set_scan(
        "prematch",
        scan_age_sec=ODDS_TTL_SECONDS + 5,
        rows=[_row("mdshop", ODDS_TTL_SECONDS + 5)],
    )
    stale = _results()["freshness"]
    assert stale["stale"] is True
    assert stale["state"] == "scan_older_than_ttl"
    assert stale["age_sec"] > stale["ttl_sec"]


def test_stale_rows_remain_visible_but_are_labelled_historical():
    _set_scan("prematch", scan_age_sec=ODDS_TTL_SECONDS + 60, rows=[_row("mdshop", 10)])
    api.cached_surebets.append({"id": "historical", "profit_percent": 4.2})

    body = _results()

    assert [s["id"] for s in body["surebets"]] == ["historical"], (
        "stale data is kept for diagnosis; the fix is labelling and action-gating"
    )
    assert body["freshness"]["stale"] is True


def test_a_single_stale_book_makes_the_feed_stale():
    """A fresh scan is not enough if one supplied book is older than the budget."""
    _set_scan(
        "prematch",
        scan_age_sec=10,
        rows=[_row("mdshop", 10), _row("wwin", ODDS_TTL_SECONDS + 100)],
    )

    freshness = _results()["freshness"]

    assert freshness["stale"] is True
    assert freshness["state"] == "book_older_than_ttl"
    assert freshness["stale_books"] == ["wwin"]
    assert freshness["per_book"]["mdshop"]["stale"] is False
    assert freshness["per_book"]["wwin"]["stale"] is True


def test_live_uses_the_tighter_sixty_second_budget():
    _set_scan("live", scan_age_sec=30, rows=[_row("mbet", 30)])
    assert _results("live")["freshness"]["ttl_sec"] == LIVE_ODDS_TTL_SECONDS
    assert _results("live")["freshness"]["stale"] is False

    _set_scan("live", scan_age_sec=LIVE_ODDS_TTL_SECONDS + 10, rows=[_row("mbet", 70)])
    stale = _results("live")["freshness"]
    assert stale["stale"] is True
    assert stale["ttl_sec"] == LIVE_ODDS_TTL_SECONDS


def test_never_scanned_is_explicit_and_not_current():
    _set_scan("prematch", scan_age_sec=None, rows=[])

    freshness = _results()["freshness"]

    assert freshness["stale"] is True
    assert freshness["state"] == "never_scanned"
    assert freshness["age_sec"] is None
    assert freshness["scan_time"] is None


def test_a_book_without_a_fetch_time_is_not_assumed_fresh():
    _set_scan("prematch", scan_age_sec=5, rows=[{"bookmaker": "mdshop"}])

    freshness = _results()["freshness"]

    assert freshness["per_book"]["mdshop"]["missing_fetched_at"] == 1
    assert freshness["per_book"]["mdshop"]["stale"] is True
    assert freshness["stale_books"] == ["mdshop"]


def test_each_priced_leg_carries_its_own_fetch_time():
    """The summary is per book; the leg a reviewer places carries its own age."""
    kickoff = _now() + timedelta(hours=3)
    fetched = _now() - timedelta(seconds=20)
    matches = [
        Match(
            bookmaker=bookmaker,
            home_team="Sarajevo",
            away_team="Zeljeznicar",
            league="Premijer Liga BiH",
            kickoff=kickoff,
            fetched_at=fetched,
            markets=[
                Market(
                    market_type=MarketType.BTTS,
                    odds=[
                        OddsValue(label="GG", value=gg),
                        OddsValue(label="NG", value=ng),
                    ],
                )
            ],
        )
        for bookmaker, (gg, ng) in {
            "mdshop": (2.40, 1.90),
            "mbet": (2.20, 1.85),
        }.items()
    ]
    group = MatchGroup(
        status="verified",
        canonical_home="sarajevo",
        canonical_away="zeljeznicar",
        league="premier_liga_bih",
        kickoff=kickoff,
        matches=matches,
    )

    surebets = ArbitrageEngine().find_surebets([group], min_profit=0.5)

    assert surebets
    assert {stake.fetched_at for stake in surebets[0].stakes} == {fetched}
