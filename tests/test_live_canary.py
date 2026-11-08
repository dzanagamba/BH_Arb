"""SR4-9: the daily live canary's report and comparison.

The canary probes each configured book once per day. These tests pin the two
things that make the report useful and safe: it never raises when a book fails,
and it compares with the previous dated report instead of inventing a baseline.
No test here reaches the network: the scraper registry is injected.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import scripts.live_canary as live_canary
from models.schemas import Market, MarketType, Match, OddsValue


def _market(market_type: MarketType, count: int = 1) -> list[Market]:
    if market_type == MarketType.BTTS:
        odds = [OddsValue(label="GG", value=2.0), OddsValue(label="NG", value=1.8)]
    else:
        odds = [
            OddsValue(label="1", value=2.1),
            OddsValue(label="X", value=3.2),
            OddsValue(label="2", value=2.9),
        ]
    return [Market(market_type=market_type, odds=odds) for _ in range(count)]


def _match(bookmaker: str, markets: list[Market]) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        kickoff=datetime.now(UTC).replace(tzinfo=None),
        markets=markets,
    )


def _scraper(matches: list[Match] | Exception):
    class FakeScraper:
        async def scrape(self, live: bool = False) -> list[Match]:
            if isinstance(matches, Exception):
                raise matches
            return matches

    return FakeScraper


def _registry(**books: Any) -> dict[str, Any]:
    return dict(books)


def _run(books: str, **kwargs: Any) -> tuple[dict[str, Any], Path]:
    return asyncio.run(live_canary.run(books, **kwargs))


def test_the_first_run_reports_counts_and_has_no_alarms(tmp_path: Path) -> None:
    registry = _registry(
        mbet=_scraper([_match("mbet", _market(MarketType.MATCH_RESULT, 3))]),
        mdshop=_scraper([_match("mdshop", _market(MarketType.BTTS))]),
    )

    report, path = _run(
        "all", scrapers=registry, report_dir=tmp_path, today="2026-11-08"
    )

    assert path == tmp_path / "2026-11-08.json"
    assert report["alarms"] == 0
    assert {entry["bookmaker"] for entry in report["books"]} == {"mbet", "mdshop"}
    mbet = next(entry for entry in report["books"] if entry["bookmaker"] == "mbet")
    assert mbet["matches"] == 1
    assert mbet["markets"] == {"1x2": 3}
    assert mbet["reasons"] == []
    assert json.loads(path.read_text(encoding="utf-8"))["books"] == report["books"]


def test_a_halved_book_and_family_raise_reasons_on_the_next_run(tmp_path: Path) -> None:
    busy = [_match("mbet", _market(MarketType.MATCH_RESULT, 2)) for _ in range(20)]
    quiet = [_match("mbet", _market(MarketType.MATCH_RESULT, 2)) for _ in range(4)]

    _run(
        "all",
        scrapers=_registry(mbet=_scraper(busy)),
        report_dir=tmp_path,
        today="2026-11-08",
    )
    report, _ = _run(
        "all",
        scrapers=_registry(mbet=_scraper(quiet)),
        report_dir=tmp_path,
        today="2026-11-09",
    )

    entry = report["books"][0]
    assert entry["reasons"] == ["matches 20 -> 4", "1x2 40 -> 8"]
    assert report["alarms"] == 2
    assert report["previous"] is not None


def test_an_erroring_book_is_reported_and_does_not_raise(tmp_path: Path) -> None:
    registry = _registry(mbet=_scraper(RuntimeError("connection reset")))

    report, _ = _run(
        "all", scrapers=registry, report_dir=tmp_path, today="2026-11-08"
    )

    entry = report["books"][0]
    assert entry["matches"] == 0
    assert entry["error"].startswith("RuntimeError")
    assert entry["reasons"] == ["error: RuntimeError: connection reset"]
    assert report["alarms"] == 1


def test_a_missing_scraper_is_reported_not_raised(tmp_path: Path) -> None:
    report, _ = _run(
        "ghost", scrapers=_registry(), report_dir=tmp_path, today="2026-11-08"
    )

    entry = report["books"][0]
    assert entry["error"] == "no scraper registered"
    assert entry["reasons"] == ["error: no scraper registered"]


def test_a_new_market_family_is_news_not_an_alarm(tmp_path: Path) -> None:
    _run(
        "all",
        scrapers=_registry(mbet=_scraper([_match("mbet", _market(MarketType.MATCH_RESULT))])),
        report_dir=tmp_path,
        today="2026-11-08",
    )
    report, _ = _run(
        "all",
        scrapers=_registry(
            mbet=_scraper(
                [
                    _match(
                        "mbet",
                        _market(MarketType.MATCH_RESULT) + _market(MarketType.BTTS),
                    )
                ]
            )
        ),
        report_dir=tmp_path,
        today="2026-11-09",
    )

    entry = report["books"][0]
    assert entry["new_market_types"] == ["btts"]
    assert entry["reasons"] == []
    assert report["alarms"] == 0


@pytest.mark.parametrize(
    ("previous_matches", "current_matches", "flagged"),
    [(10, 4, True), (10, 5, False), (9, 0, False), (100, 49, True), (100, 50, False)],
)
def test_the_match_drop_threshold_is_half_of_at_least_ten(
    previous_matches: int, current_matches: int, flagged: bool
) -> None:
    reasons = live_canary.compare(
        {"matches": previous_matches, "markets": {}},
        {"matches": current_matches, "markets": {}},
    )

    assert bool(reasons) is flagged


def test_the_canary_never_refreshes_a_fixture(tmp_path: Path) -> None:
    before = {
        path.name: path.stat().st_mtime_ns
        for path in Path("tests/fixtures/markets").glob("*.json")
    }

    _run(
        "all",
        scrapers=_registry(mbet=_scraper([_match("mbet", _market(MarketType.MATCH_RESULT))])),
        report_dir=tmp_path,
        today="2026-11-08",
    )

    after = {
        path.name: path.stat().st_mtime_ns
        for path in Path("tests/fixtures/markets").glob("*.json")
    }
    assert after == before


def test_strict_exits_nonzero_only_when_a_reason_fires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report: dict[str, Any] = {
        "generated_at": "2026-11-08T00:00:00",
        "live": False,
        "alarms": 1,
        "previous": None,
        "books": [],
    }
    async def fake_run(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], Path]:
        return report, tmp_path / "x.json"

    monkeypatch.setattr(live_canary, "run", fake_run)
    assert live_canary.main(["--books", "mbet", "--strict"]) == 1

    report["alarms"] = 0
    assert live_canary.main(["--books", "mbet", "--strict"]) == 0
