"""The scan-quality report is a measurement, not a mutation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue
from scripts.scan_quality import build_report, main


def _match(book: str) -> Match:
    return Match(
        bookmaker=book,
        home_team="Alpha",
        away_team="Beta",
        league="Test League",
        kickoff=datetime(2026, 11, 7, 18, 0),
        event_id=book,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=2.0),
                    OddsValue(label="X", value=3.4),
                    OddsValue(label="2", value=3.6),
                ],
            )
        ],
    )


def _scan(path: Path) -> Path:
    matches = [_match(book) for book in ("mbet", "wwin", "sportplus")]
    path.write_text(
        json.dumps({"matches": [m.model_dump(mode="json") for m in matches]}),
        encoding="utf-8",
    )
    return path


def test_the_report_counts_books_groups_and_price_agreement(tmp_path):
    matches = [_match(book) for book in ("mbet", "wwin", "sportplus")]
    groups = MatchMatcher(evidence_path=tmp_path / "empty.json").group_matches(
        [match.model_copy(deep=True) for match in matches]
    )
    report = build_report(matches, groups, evidence_path=str(tmp_path / "empty.json"))
    assert report["matches"] == 3
    assert report["groups"] == 1
    assert report["false_merges"] == 0
    assert report["price_outliers"] == 0
    assert set(report["books"]) == {"mbet", "wwin", "sportplus"}
    assert report["best_margins"]


def test_check_mode_is_read_only_and_passes_on_consistent_prices(tmp_path):
    scan = _scan(tmp_path / "scan.json")
    before = sorted(tmp_path.iterdir())
    assert main(["--file", str(scan), "--check"]) == 0
    assert sorted(tmp_path.iterdir()) == before
