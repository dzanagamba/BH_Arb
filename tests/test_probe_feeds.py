"""The feed probe reports counts and never crashes on a broken scraper."""

from __future__ import annotations

import asyncio

from models.schemas import Market, MarketType, Match, OddsValue
from scripts.probe_feeds import probe_one


class _GoodScraper:
    async def scrape(self, live: bool = False):
        return [
            Match(
                bookmaker="testbook",
                home_team="A",
                away_team="B",
                markets=[
                    Market(
                        market_type=MarketType.MATCH_RESULT,
                        odds=[OddsValue(label="1", value=2.0)],
                    )
                ],
            )
        ]


class _BrokenScraper:
    async def scrape(self, live: bool = False):
        raise RuntimeError("feed gone")


def test_a_good_feed_reports_matches_and_markets():
    result = asyncio.run(probe_one("testbook", _GoodScraper, live=False, timeout=5))
    assert result["matches"] == 1
    assert result["markets"] == {"1x2": 1}
    assert result["error"] == ""


def test_a_broken_feed_is_reported_not_raised():
    result = asyncio.run(probe_one("testbook", _BrokenScraper, live=False, timeout=5))
    assert result["matches"] == 0
    assert "feed gone" in result["error"]
