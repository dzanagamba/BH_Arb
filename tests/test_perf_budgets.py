"""N3-1: bounded load budgets for the matcher and the cache parser.

These are not micro-benchmarks and they do not assert a time on an idle machine
as a hard release number. They pin an order of magnitude: a material regression
(the matcher going quadratic on every candidate, or the cache validation
getting a per-row I/O step) trips the budget long before a live scan does.

They are marked ``slow`` and only run when ``BH_ARB_TEST_SLOW=1``. The normal
fast suite therefore keeps its runtime; CI runs this file as a separate step.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import pytest

from engine.matcher import MatchMatcher
from models.schemas import (
    Market,
    MarketType,
    Match,
    OddsValue,
    Surebet,
    SurebetStake,
)

SLOW_ENV = "BH_ARB_TEST_SLOW"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv(SLOW_ENV) != "1",
        reason=f"load budget is opt-in; set {SLOW_ENV}=1 to run it",
    ),
]

# Measured locally on 2026-11-05: 600 listings across 150 fixtures in ~1.3 s.
# The budget is ~8x that so a slow shared runner is not a failure, while a
# quadratic regression (minutes) is.
MATCHER_LISTINGS = 600
MATCHER_BUDGET_SECONDS = 10.0

# Measured locally: ~1.6 MB of cache and ~0.04 s of json+model validation for
# 1,500 rows. The budget covers a much larger scan and a cold CI runner.
CACHE_MATCH_ROWS = 2_000
CACHE_SUREBET_ROWS = 500
CACHE_BUDGET_SECONDS = 5.0


def _fixture_matches(bookmakers: list[str], fixtures: int) -> list[Match]:
    base = datetime(2030, 1, 1, 12, 0)
    matches: list[Match] = []
    for index in range(fixtures):
        home = f"Home United {index}"
        away = f"Away City {index}"
        kickoff = base + timedelta(minutes=3 * index)
        for bookmaker in bookmakers:
            matches.append(
                Match(
                    bookmaker=bookmaker,
                    home_team=home,
                    away_team=away,
                    league="Premier Liga BiH",
                    kickoff=kickoff,
                    event_id=f"{bookmaker}-{index}",
                    url=f"https://example.test/{bookmaker}/{index}",
                    deep_link_verified=True,
                    markets=[
                        Market(
                            market_type=MarketType.MATCH_RESULT,
                            odds=[
                                OddsValue(label="1", value=2.10),
                                OddsValue(label="X", value=3.20),
                                OddsValue(label="2", value=2.90),
                            ],
                        )
                    ],
                )
            )
    return matches


def test_the_matcher_stays_under_its_listing_budget() -> None:
    matches = _fixture_matches(["mbet", "wwin", "mozzartbet", "betole"], 150)
    assert len(matches) == MATCHER_LISTINGS

    started = time.perf_counter()
    groups = MatchMatcher().group_matches(matches)
    elapsed = time.perf_counter() - started

    assert len(groups) == 150
    assert all(group.status == "verified" for group in groups)
    assert elapsed < MATCHER_BUDGET_SECONDS, (
        f"matcher took {elapsed:.2f}s for {MATCHER_LISTINGS} listings; "
        f"budget is {MATCHER_BUDGET_SECONDS:.1f}s"
    )


def _cache_payload() -> str:
    base = datetime(2030, 1, 1, 12, 0)
    matches = [
        Match(
            bookmaker=f"book{index % 8}",
            home_team=f"Home {index}",
            away_team=f"Away {index}",
            league="Premier Liga",
            kickoff=base + timedelta(minutes=index),
            event_id=str(index),
            markets=[
                Market(
                    market_type=MarketType.MATCH_RESULT,
                    odds=[
                        OddsValue(label="1", value=2.10),
                        OddsValue(label="X", value=3.20),
                        OddsValue(label="2", value=2.90),
                    ],
                )
            ],
        ).model_dump(mode="json")
        for index in range(CACHE_MATCH_ROWS)
    ]
    surebets = [
        Surebet(
            id=f"sb{index}",
            home_team=f"Home {index}",
            away_team=f"Away {index}",
            market_type=MarketType.MATCH_RESULT,
            profit_percent=2.5,
            total_margin=0.98,
            raw_margin=0.98,
            stakes=[
                SurebetStake(
                    bookmaker="mbet",
                    outcome_label="1",
                    odds=2.1,
                    stake=50.0,
                    potential_return=105.0,
                ),
                SurebetStake(
                    bookmaker="wwin",
                    outcome_label="X",
                    odds=3.2,
                    stake=32.0,
                    potential_return=102.4,
                ),
            ],
            found_at=base,
        ).model_dump(mode="json")
        for index in range(CACHE_SUREBET_ROWS)
    ]
    return json.dumps(
        {
            "scan_time": base.isoformat(),
            "matches": matches,
            "surebets": surebets,
            "match_groups": [],
        }
    )


def test_the_cache_parse_stays_under_its_budget() -> None:
    payload = _cache_payload()
    assert len(payload.encode("utf-8")) > 1_000_000

    started = time.perf_counter()
    data = json.loads(payload)
    restored_matches = [Match.model_validate(row) for row in data["matches"]]
    restored_surebets = [Surebet.model_validate(row) for row in data["surebets"]]
    elapsed = time.perf_counter() - started

    assert len(restored_matches) == CACHE_MATCH_ROWS
    assert len(restored_surebets) == CACHE_SUREBET_ROWS
    assert elapsed < CACHE_BUDGET_SECONDS, (
        f"cache parse took {elapsed:.2f}s for {CACHE_MATCH_ROWS} matches and "
        f"{CACHE_SUREBET_ROWS} surebets; budget is {CACHE_BUDGET_SECONDS:.1f}s"
    )
