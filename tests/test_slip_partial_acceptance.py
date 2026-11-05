"""P3-3: the advisory slip re-plans from accepted amounts and warns."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def test_every_book_exposes_an_advisory_stake_limit():
    body = TestClient(app).get("/api/config").json()

    assert body["bookmakers"]["mbet"]["max_stake"] == 500
    assert all("max_stake" in book for book in body["bookmakers"].values())


def test_partial_acceptance_replans_the_remaining_legs():
    assert "function planStakes" in JS
    assert "const target = Math.max(...placedLegs.map" in JS
    assert "const raw = target / s.odds;" in JS
    assert "placed[s.outcome_label]" in JS


def test_a_negative_worst_case_tells_the_operator_to_stop_or_hedge():
    assert "With these stakes the worst outcome loses {loss} KM." in JS
    assert "stopping or hedging rather than placing the rest" in JS


def test_the_slip_warns_above_the_advisory_book_limit():
    assert "Above the advisory book limit" in JS
    assert "bookmakersConfig?.[leg.bookmaker]?.max_stake" in JS


def test_the_slip_never_places_a_bet():
    assert "Log bet" in JS
    assert "/api/bets" in JS
    assert "placeBet" not in JS
    assert "login" not in JS.lower().split("logBet")[0]
