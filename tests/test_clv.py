"""P3-2: CLV and ROI expose their denominators."""

from __future__ import annotations

from server.bets import BetStore


def _payload():
    return {
        "surebet_id": "sb-1",
        "mode": "prematch",
        "home_team": "Sarajevo",
        "away_team": "Zeljeznicar",
        "market_type": "btts",
        "investment": 100.0,
        "legs": [
            {
                "bookmaker": "mbet",
                "outcome_label": "GG",
                "odds": 2.0,
                "stake": 50.0,
                "accepted_odds": 2.1,
                "accepted_stake": 50.0,
            },
            {
                "bookmaker": "wwin",
                "outcome_label": "NG",
                "odds": 2.0,
                "stake": 50.0,
                "accepted_odds": 1.9,
                "accepted_stake": 50.0,
            },
        ],
    }


def test_clv_is_accepted_over_closing_weighted_by_accepted_stake(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(_payload())
    store.set_closing(
        created["id"],
        [
            {"outcome_label": "GG", "closing_odds": 2.0},
            {"outcome_label": "NG", "closing_odds": 2.0},
        ],
    )

    summary = store.summary()

    # GG: 2.1/2.0 - 1 = +5%; NG: 1.9/2.0 - 1 = -5%; equal stakes -> 0.
    assert summary["clv"] == 0.0
    assert summary["clv_legs"] == 2
    assert summary["denominators"]["clv"].startswith("accepted-stake weighted")


def test_bankroll_and_roi_use_settled_bets_only(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"), bankroll_start=1000.0)
    store.initialize()
    won = store.create(_payload())
    store.settle(
        won["id"],
        [
            {"outcome_label": "GG", "result": "won"},
            {"outcome_label": "NG", "result": "lost"},
        ],
    )
    store.create(_payload())  # open bet must not affect ROI

    summary = store.summary()

    assert summary["settled_bets"] == 1
    assert summary["staked"] == 100.0
    assert summary["profit"] == 5.0
    assert summary["roi"] == 0.05
    assert summary["bankroll"] == 1005.0
    assert summary["denominators"]["staked"] == "settled bets only"
