"""The extra football lines are admitted by measured evidence, not by label."""

from __future__ import annotations

import json
from pathlib import Path

from engine.market_registry import MarketRegistry
from models.schemas import MarketType

EVIDENCE = Path("docs/evidence/2026-11-04-football-lines.json")
NEW_LINES = (
    MarketType.OVER_UNDER_0_5,
    MarketType.OVER_UNDER_4_5,
    MarketType.OVER_UNDER_5_5,
)


def test_each_new_football_line_has_three_sources_and_no_outlier():
    report = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert report["outlier_count"] == 0
    assert report["compared_market_rows"] > 0
    for market_type in NEW_LINES:
        row = report["markets"][market_type.value]
        assert row["admitted"] is True, market_type
        assert row["rows"] > 0
        assert row["classified_rows"] == row["rows"]
        assert len(row["price_sources"]) >= 3


def test_every_new_line_is_registered_for_its_measured_books():
    registry = MarketRegistry()
    report = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    for market_type in NEW_LINES:
        for source in report["markets"][market_type.value]["price_sources"]:
            books = {
                "nsoft": ("mdshop", "admiralbet"),
                "maxbet": ("maxbet",),
                "mbet": ("mbet",),
                "premier_kladionica": ("premier_kladionica",),
                "wwin": ("wwin",),
            }[source]
            for book in books:
                assert registry.ids_for(book, "prematch", market_type), (book, market_type)
