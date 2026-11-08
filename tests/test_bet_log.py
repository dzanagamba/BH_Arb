"""P3-2: the manual bet log, partial stakes and realized P/L."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from server import api
from server.app import app
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


def _api_client(tmp_path, monkeypatch) -> tuple[TestClient, BetStore]:
    store = BetStore(str(tmp_path / "api-bets.sqlite3"))
    store.initialize()
    monkeypatch.setattr(api, "_bet_store", store)
    return TestClient(app), store


def _bad_leg(**overrides) -> dict:
    leg = {
        "bookmaker": "mbet",
        "outcome_label": "GG",
        "odds": 2.10,
        "stake": 50.0,
    }
    leg.update(overrides)
    return leg


def test_non_finite_investment_is_rejected_before_a_row_is_written(tmp_path, monkeypatch):
    client, store = _api_client(tmp_path, monkeypatch)
    leg = _bad_leg()

    for literal in ("1e400", "NaN", "Infinity", "-Infinity"):
        body = '{"investment": ' + literal + ', "legs": [' + json.dumps(leg) + "]}"
        response = client.post(
            "/api/bets",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422, (literal, response.text)

    assert store.list_bets() == []
    assert client.get("/api/bets").status_code == 200


def test_out_of_range_investment_is_rejected(tmp_path, monkeypatch):
    client, store = _api_client(tmp_path, monkeypatch)

    for investment in (-1.0, 0.0, 1_000_001.0):
        response = client.post("/api/bets", json=_payload(investment=investment))
        assert response.status_code == 422, (investment, response.text)

    assert store.list_bets() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"odds": float("inf")},
        {"odds": float("nan")},
        {"odds": 1.0},
        {"stake": float("nan")},
        {"stake": -1.0},
        {"accepted_odds": float("inf")},
        {"accepted_stake": float("nan")},
        {"closing_odds": float("inf")},
        {"odds": 1001.0},
        {"accepted_odds": 1001.0},
        {"stake": 1_000_000_001.0},
    ],
)
def test_non_finite_or_out_of_range_leg_numbers_are_rejected(
    tmp_path, monkeypatch, overrides
):
    client, store = _api_client(tmp_path, monkeypatch)

    body = json.dumps(_payload(legs=[_bad_leg(**overrides)]))
    response = client.post(
        "/api/bets",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422, response.text
    assert store.list_bets() == []


def test_recalculate_rejects_non_finite_and_negative_investment(tmp_path, monkeypatch):
    client, _ = _api_client(tmp_path, monkeypatch)

    for investment in (float("nan"), float("inf"), float("-inf"), -1.0):
        body = json.dumps({"surebet_id": "missing", "investment": investment})
        response = client.post(
            "/api/recalculate",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422, (investment, response.text)


def test_closing_odds_are_validated_before_they_are_stored(tmp_path, monkeypatch):
    client, store = _api_client(tmp_path, monkeypatch)
    created = client.post("/api/bets", json=_payload()).json()

    for closing in (float("nan"), float("inf"), 1.0, -2.0):
        body = json.dumps({"legs": [{"outcome_label": "GG", "closing_odds": closing}]})
        response = client.post(
            f"/api/bets/{created['id']}/closing",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422, (closing, response.text)

    stored = store.get(created["id"])
    assert stored is not None
    assert stored["legs"][0].get("closing_odds") is None


def test_days_above_the_window_is_rejected(tmp_path, monkeypatch):
    client, _ = _api_client(tmp_path, monkeypatch)

    for path in (
        "/api/history?days=999999",
        "/api/bets?days=999999",
        "/api/bets/summary?days=999999",
        "/api/paper/summary?days=999999",
    ):
        assert client.get(path).status_code == 422, path


def test_csv_cell_neutralises_whitespace_prefixed_formulas():
    from server.csv_export import csv_cell

    for value in ("\t=1+1", "\r@SUM(A1)", "\n-1x2"):
        assert csv_cell(value) == "'" + value


def test_a_zero_accepted_odds_is_the_not_placed_sentinel(tmp_path, monkeypatch):
    client, store = _api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/bets", json=_payload(legs=[_bad_leg(accepted_stake=0.0, accepted_odds=0.0)])
    )

    assert response.status_code == 200, response.text
    assert store.list_bets()[0]["legs"][0]["accepted_odds"] == 0.0


def test_a_positive_stake_at_zero_odds_is_rejected(tmp_path, monkeypatch):
    """M1-2: a stake the book accepted at no price is an impossible claim.

    It used to be silently neutralised at settle, so money the operator said the
    book took vanished from P/L with no warning. The "not placed" sentinel is a
    pair: both fields zero, or a real price with the stake.
    """
    client, store = _api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/bets",
        json=_payload(legs=[_bad_leg(accepted_stake=50.0, accepted_odds=0.0)]),
    )

    assert response.status_code == 422, response.text
    detail = response.text
    assert "accepted_stake" in detail and "accepted_odds" in detail, detail
    assert "not placed" in detail, detail
    assert store.list_bets() == [], "the refused row must not be written"


def test_missing_accepted_odds_still_falls_back_to_the_planned_price(
    tmp_path, monkeypatch
):
    """Only the zero-with-stake pair is refused; `null` still means "not typed"."""
    client, store = _api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/bets", json=_payload(legs=[_bad_leg(accepted_stake=50.0)])
    )

    assert response.status_code == 200, response.text
    assert store.list_bets()[0]["legs"][0]["accepted_odds"] is None


def test_a_zero_stake_with_a_real_price_is_still_accepted(tmp_path, monkeypatch):
    """The mirror case is coherent: the price is known, nothing was staked, so
    the leg is not placed and no money is at stake."""
    client, store = _api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/bets",
        json=_payload(legs=[_bad_leg(accepted_stake=0.0, accepted_odds=2.2)]),
    )

    assert response.status_code == 200, response.text
    created = store.list_bets()[0]
    settled = store.settle(created["id"], [{"outcome_label": "GG", "result": "won"}])
    assert settled["staked"] == 0.0
    assert settled["payout"] == 0.0


def test_a_stored_row_with_a_stake_at_zero_odds_still_settles_as_not_placed(
    tmp_path,
):
    """Existing data is never rejected or rewritten: settle keeps its leniency.

    The 422 is a create-time guard; a row written before it (or by hand) must
    still not book a phantom payout or a phantom stake.
    """
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(
        _payload(
            legs=[
                {
                    "bookmaker": "mbet",
                    "outcome_label": "GG",
                    "odds": 2.10,
                    "stake": 51.0,
                    "accepted_odds": 0.0,
                    "accepted_stake": 50.0,
                }
            ]
        )
    )

    settled = store.settle(created["id"], [{"outcome_label": "GG", "result": "won"}])

    assert settled["staked"] == 0.0
    assert settled["payout"] == 0.0
    assert settled["profit"] == 0.0


def test_a_zero_accepted_odds_is_not_placed_when_settled(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(
        _payload(
            legs=[
                {
                    "bookmaker": "mbet",
                    "outcome_label": "GG",
                    "odds": 2.10,
                    "stake": 51.0,
                    "accepted_odds": 0.0,
                }
            ]
        )
    )

    settled = store.settle(created["id"], [{"outcome_label": "GG", "result": "won"}])

    assert settled is not None
    assert settled["staked"] == 0.0
    assert settled["payout"] == 0.0
    assert settled["profit"] == 0.0


def test_csv_export_keeps_a_recorded_zero_accepted_stake(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    store.create(
        _payload(
            legs=[
                {
                    "bookmaker": "mbet",
                    "outcome_label": "GG",
                    "odds": 2.10,
                    "stake": 51.0,
                    "accepted_odds": 2.10,
                    "accepted_stake": 0.0,
                }
            ]
        )
    )

    rows = list(csv.DictReader(io.StringIO(store.export_csv())))

    assert rows[0]["accepted_stake"] == "0.0"


def test_csv_export_escapes_formula_leading_cells(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    store.create(
        _payload(
            home_team="=1+1",
            away_team="@SUM(A1)",
            market_type="-1x2",
        )
    )

    rows = list(csv.DictReader(io.StringIO(store.export_csv())))

    assert rows[0]["home_team"] == "'=1+1"
    assert rows[0]["away_team"] == "'@SUM(A1)"
    assert rows[0]["market_type"] == "'-1x2"


@pytest.mark.parametrize("result", ["won", "lost", "void"])
def test_a_recorded_zero_accepted_stake_stays_zero(tmp_path, result):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    created = store.create(
        _payload(
            legs=[
                {
                    "bookmaker": "mbet",
                    "outcome_label": "GG",
                    "odds": 2.10,
                    "stake": 51.0,
                    # The leg was not placed, so the accepted stake is zero.
                    "accepted_odds": 2.10,
                    "accepted_stake": 0.0,
                }
            ]
        )
    )

    settled = store.settle(created["id"], [{"outcome_label": "GG", "result": result}])

    assert settled is not None
    assert settled["staked"] == 0.0
    assert settled["payout"] == 0.0
    assert settled["profit"] == 0.0
