"""P1-7: the served margin must be recomputable from the served odds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.arbitrage import ArbitrageEngine
from engine.pricing_invariant import implied_sum, rounding_summary
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from server import api
from server.app import app

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def _group() -> MatchGroup:
    kickoff = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
    matches = []
    for bookie, (gg, ng) in {
        "mdshop": (2.40, 1.90),
        "mbet": (2.20, 1.85),
    }.items():
        matches.append(
            Match(
                bookmaker=bookie,
                home_team="Sarajevo",
                away_team="Zeljeznicar",
                league="Premijer Liga BiH",
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


def _surebet():
    surebets = ArbitrageEngine().find_surebets(
        [_group()], min_profit=0.5, investment=100.0
    )
    assert len(surebets) == 1
    return surebets[0]


def test_every_surebet_margin_is_recomputable_from_its_served_odds():
    surebet = _surebet()

    served_margin = implied_sum([stake.odds for stake in surebet.stakes])

    assert abs(sum(1 / stake.odds for stake in surebet.stakes) - served_margin) < 1e-12
    # total_margin keeps its four-decimal display form; raw_margin is exact.
    assert round(served_margin, 4) == surebet.total_margin
    assert abs(served_margin - surebet.raw_margin) < 1e-6
    assert (
        abs((1 / served_margin - 1) * 100 - surebet.profit_percent) < 0.01
    )


def test_realized_block_is_the_rounded_stakes_not_the_exact_margin():
    surebet = _surebet()
    realized = surebet.realized

    assert realized is not None
    stake_total = sum(stake.stake for stake in surebet.stakes)
    worst_return = min(
        stake.stake * stake.odds for stake in surebet.stakes
    )

    assert realized.stake_total == pytest.approx(stake_total, abs=0.01)
    assert realized.worst_case_return == pytest.approx(worst_return, abs=0.01)
    assert realized.realized_profit == pytest.approx(worst_return - stake_total, abs=0.02)
    assert realized.exact_profit_percent == pytest.approx(
        surebet.profit_percent, abs=0.01
    )
    assert realized.rounding_loss == pytest.approx(
        realized.exact_profit - realized.realized_profit, abs=0.02
    )


def test_a_changed_margin_fails_the_invariant_without_changing_the_odds():
    surebet = _surebet()
    served_margin = implied_sum([stake.odds for stake in surebet.stakes])

    tampered = surebet.model_copy(
        update={"total_margin": surebet.total_margin + 0.01}
    )

    assert round(served_margin, 4) == surebet.total_margin
    assert abs(served_margin - tampered.total_margin) > 1e-4


def test_recalculate_returns_exact_and_realized_profit(monkeypatch):
    surebet = _surebet()
    monkeypatch.setattr(
        api, "cached_surebets", [surebet.model_dump(mode="json")]
    )

    response = TestClient(app).post(
        "/api/recalculate",
        json={
            "surebet_id": surebet.id,
            "investment": 100,
            "rounding": "1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_margin"] == pytest.approx(payload["implied_sum"])
    assert abs(
        sum(1 / stake["odds"] for stake in payload["stakes"])
        - payload["raw_margin"]
    ) < 1e-9
    assert all(float(stake["stake"]).is_integer() for stake in payload["stakes"])
    assert payload["realized"]["rounding"] == "1"
    assert payload["realized"]["rounding_loss"] == pytest.approx(
        payload["exact"]["profit"] - payload["realized"]["realized_profit"],
        abs=0.02,
    )
    # The legacy fields are the exact values, not the realized ones.
    assert payload["guaranteed_return"] == payload["exact"]["return"]
    assert payload["guaranteed_profit"] == payload["exact"]["profit"]


def test_rounding_summary_uses_the_requested_investment_as_the_exact_base():
    rows = [
        {"odds": 2.0, "stake": 50.0},
        {"odds": 2.0, "stake": 50.0},
    ]
    summary = rounding_summary(rows, investment=100.0, rounding="exact")

    assert summary["stake_total"] == 100.0
    assert summary["exact_profit"] == 0.0
    assert summary["realized_profit"] == 0.0


def test_the_slip_labels_exact_and_realized_profit_and_checks_the_payload():
    assert "function servedMargin" in JS
    assert "function servedProfitPercent" in JS
    assert "sb.raw_margin ?? sb.total_margin" in JS
    assert "The served odds do not reproduce the payload margin" in JS
    assert "Exact profit" in JS
    assert "Realized profit" in JS
    assert "Rounding effect" in JS
