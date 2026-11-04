"""P2-7: a measured twin cannot manufacture an arb between its own books."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from config.settings import price_source, reset_measured_price_sources
from engine.arbitrage import ArbitrageEngine
from engine.skin_detection import (
    apply_measured_twins,
    declared_twin_warnings,
    measure_price_agreement,
)
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue


@pytest.fixture(autouse=True)
def _reset_twins():
    reset_measured_price_sources()
    yield
    reset_measured_price_sources()


def _group(left: str, right: str, left_odds, right_odds) -> MatchGroup:
    kickoff = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
    matches = []
    for book, (gg, ng) in [(left, left_odds), (right, right_odds)]:
        matches.append(
            Match(
                bookmaker=book,
                home_team="Sarajevo",
                away_team="Zeljeznicar",
                league="Premier Liga",
                kickoff=kickoff,
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
        )
    return MatchGroup(
        status="verified",
        canonical_home="Sarajevo",
        canonical_away="Zeljeznicar",
        league="premier_liga_bih",
        kickoff=kickoff,
        matches=matches,
    )


def test_identical_prices_are_a_twin_when_the_sample_is_enough():
    matrix = measure_price_agreement(
        [_group("maxbet", "wwin", (2.40, 1.90), (2.40, 1.90))], min_shared=2
    )

    row = matrix["maxbet|wwin"]
    assert row["classification"] == "twin"
    assert row["shared_outcomes"] == 2
    assert row["identical_rate"] == 1.0


def test_different_prices_are_independent():
    matrix = measure_price_agreement(
        [_group("maxbet", "wwin", (2.40, 1.90), (1.90, 2.40))], min_shared=2
    )

    assert matrix["maxbet|wwin"]["classification"] == "independent"


def test_too_little_shared_data_is_not_silently_independent():
    matrix = measure_price_agreement(
        [_group("maxbet", "wwin", (2.40, 1.90), (2.40, 1.90))], min_shared=200
    )

    assert matrix["maxbet|wwin"]["classification"] == "insufficient_data"
    assert matrix["maxbet|wwin"]["shared_outcomes"] == 2


def test_a_measured_twin_is_one_price_source_and_cannot_price_an_arb():
    group = _group("maxbet", "wwin", (2.40, 1.90), (2.40, 1.90))
    engine = ArbitrageEngine()
    assert engine.find_surebets([group], min_profit=0.5, investment=100.0)

    matrix = measure_price_agreement([group], min_shared=2)
    registered = apply_measured_twins(matrix)

    assert registered == [("maxbet", "wwin")]
    assert price_source("maxbet") == price_source("wwin")
    assert engine.find_surebets([group], min_profit=0.5, investment=100.0) == []


def test_a_declared_twin_that_measures_independent_gets_a_warning():
    matrix = measure_price_agreement(
        [_group("mdshop", "admiralbet", (2.40, 1.90), (1.90, 2.40))],
        min_shared=2,
    )

    warnings = declared_twin_warnings(matrix)

    assert any(
        row["left"] == "admiralbet"
        and row["right"] == "mdshop"
        and row["measured"] == "independent"
        for row in warnings
    )


def test_health_exposes_the_measured_matrix(monkeypatch):
    from fastapi.testclient import TestClient

    from server import api
    from server.app import app

    matrix = {"maxbet|wwin": {"left": "maxbet", "right": "wwin", "classification": "twin"}}
    monkeypatch.setattr(
        api,
        "_skin_detection",
        {
            "prematch": {"matrix": matrix, "summary": {"twin": 1}, "warnings": [], "new_twins": []},
            "live": {},
        },
    )

    body = TestClient(app).get("/api/health").json()

    assert body["skin_detection"]["prematch"]["matrix"] == matrix
