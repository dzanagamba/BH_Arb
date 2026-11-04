"""P3-2: the manual bet log, partial stakes and realized P/L."""

from __future__ import annotations

import csv
import io

from server.bets import BetStore


def _payload(**overrides):
    payload = {
        "surebet_id": "sb-1",
        "mode": "prematch",
        "home_team": "Sarajevo",
        "away_team": "Zeljeznicar",
        "market_type": "btts",
        "investment": 100.0,
        "notes": "",
        "legs": [
            {
                "bookmaker": "mbet",
                "outcome_label": "GG",
                "odds": 2.10,
                "stake": 51.0,
                "accepted_odds": 2.10,
                "accepted_stake": 50.0,
            },
            {
                "bookmaker": "wwin",
                "outcome_label": "NG",
                "odds": 1.95,
                "stake": 49.0,
                "accepted_odds": 1.95,
                "accepted_stake": 49.0,
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_a_bet_is_created_open_and_listed(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()

    created = store.create(_payload())

    assert created["status"] == "open"
    assert created["id"]
    assert store.list_bets()[0]["home_team"] == "Sarajevo"


def test_settlement_uses_accepted_stake_and_odds(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(_payload())

    settled = store.settle(
        created["id"],
        [
            {"outcome_label": "GG", "result": "won"},
            {"outcome_label": "NG", "result": "lost"},
        ],
    )

    assert settled is not None
    assert settled["status"] == "settled"
    assert settled["staked"] == 99.0
    assert settled["payout"] == 105.0
    assert settled["profit"] == 6.0


def test_a_missing_leg_result_leaves_the_bet_open(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(_payload())

    result = store.settle(created["id"], [{"outcome_label": "GG", "result": "won"}])

    assert result is not None
    assert result["status"] == "open"
    assert store.get(created["id"])["status"] == "open"


def test_a_void_leg_returns_its_stake(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(_payload())

    settled = store.settle(
        created["id"],
        [
            {"outcome_label": "GG", "result": "void"},
            {"outcome_label": "NG", "result": "lost"},
        ],
    )

    assert settled is not None
    assert settled["payout"] == 50.0
    assert settled["profit"] == -49.0


def test_csv_export_round_trips_the_leg_rows(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(_payload())

    rows = list(csv.DictReader(io.StringIO(store.export_csv())))

    assert len(rows) == 2
    assert {row["bet_id"] for row in rows} == {created["id"]}
    assert {row["outcome_label"] for row in rows} == {"GG", "NG"}
    assert {row["accepted_stake"] for row in rows} == {"50.0", "49.0"}


def test_the_api_logs_lists_settles_and_exports(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from server import api
    from server.app import app

    store = BetStore(str(tmp_path / "api-bets.sqlite3"))
    store.initialize()
    monkeypatch.setattr(api, "_bet_store", store)
    client = TestClient(app)

    created = client.post("/api/bets", json=_payload())
    assert created.status_code == 200
    bet_id = created.json()["id"]
    assert client.get("/api/bets").json()["bets"][0]["id"] == bet_id

    settled = client.post(
        f"/api/bets/{bet_id}/settle",
        json={
            "legs": [
                {"outcome_label": "GG", "result": "won"},
                {"outcome_label": "NG", "result": "lost"},
            ]
        },
    )
    assert settled.status_code == 200
    assert settled.json()["profit"] == 6.0

    exported = client.get("/api/bets/export.csv")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "GG" in exported.text and "NG" in exported.text


def test_the_slip_has_a_log_bet_action():
    from pathlib import Path

    js = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert "data-action=\"log-bet\"" in js
    assert "async function logBet" in js
    assert "/api/bets" in js
