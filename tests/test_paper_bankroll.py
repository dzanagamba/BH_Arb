"""P3-7: paper positions track a virtual bankroll without placing a bet."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from models.schemas import MarketType, Surebet, SurebetStake
from server import api
from server.app import app
from server.paper import PaperStore

NOW = datetime.now(UTC).replace(tzinfo=None)
KICKOFF = NOW + timedelta(hours=6)
FIRST_SCAN = NOW - timedelta(minutes=1)


def _surebet(odds: tuple[float, float, float] = (2.2, 4.0, 4.0)) -> Surebet:
    labels = (("mbet", "1"), ("wwin", "X"), ("sportplus", "2"))
    margin = sum(1.0 / value for value in odds)
    stakes = []
    for (bookmaker, label), value in zip(labels, odds, strict=True):
        stake = round(100.0 * (1.0 / value) / margin, 2)
        stakes.append(
            SurebetStake(
                bookmaker=bookmaker,
                outcome_label=label,
                odds=value,
                stake=stake,
                potential_return=round(stake * value, 2),
                market_type="1x2",
                selection=label,
            )
        )
    return Surebet(
        id="sb-paper-1",
        sport="football",
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="BiH - Premier Liga",
        kickoff=KICKOFF,
        market_type=MarketType.MATCH_RESULT,
        profit_percent=round((1.0 / margin - 1.0) * 100.0, 2),
        total_margin=round(margin, 4),
        raw_margin=round(margin, 6),
        stakes=stakes,
        found_at=NOW,
    )


def _store(tmp_path) -> PaperStore:
    store = PaperStore(str(tmp_path / "paper.sqlite3"), bankroll_start=1000.0)
    store.initialize()
    return store


def test_a_paper_scan_opens_one_virtual_position_per_key(tmp_path):
    store = _store(tmp_path)
    scan = FIRST_SCAN
    records = store.record_opportunities(
        [_surebet()], feed_mode="prematch", run_mode="paper", scan_time=scan
    )
    result = store.open_positions_from_scan(records, scan_time=scan)

    assert result == {"opened": 1, "marked": 0, "disappeared": 0}
    positions = store.list_positions()
    assert len(positions) == 1
    position = positions[0]
    assert position["status"] == "open"
    assert position["stake"] == 100.0
    assert position["entry_margin"] < 1.0
    assert position["simulated_profit"] > 0
    assert "no bet was placed" in position["disclaimer"].lower()

    # A second observation of the same key marks the position, never clones it.
    records = store.record_opportunities(
        [_surebet((2.1, 3.9, 3.9))],
        feed_mode="prematch",
        run_mode="paper",
        scan_time=scan + timedelta(minutes=5),
    )
    result = store.open_positions_from_scan(
        records, scan_time=scan + timedelta(minutes=5)
    )
    assert result == {"opened": 0, "marked": 1, "disappeared": 0}
    assert len(store.list_positions()) == 1


def test_the_next_scan_marks_availability_and_clv(tmp_path):
    store = _store(tmp_path)
    first = FIRST_SCAN
    records = store.record_opportunities(
        [_surebet((2.2, 4.0, 4.0))],
        feed_mode="prematch",
        run_mode="paper",
        scan_time=first,
    )
    store.open_positions_from_scan(records, scan_time=first)

    # Every entry leg is still quoted, at worse prices, so the mark is available
    # and the entry-over-current CLV is positive.
    second = first + timedelta(minutes=5)
    records = store.record_opportunities(
        [_surebet((2.0, 3.8, 3.8))],
        feed_mode="prematch",
        run_mode="paper",
        scan_time=second,
    )
    store.open_positions_from_scan(records, scan_time=second)

    position = store.list_positions()[0]
    assert position["mark"]["available"] is True
    assert position["mark"]["matched_legs"] == 3
    assert position["mark"]["clv"] is not None
    summary = store.summary()
    assert summary["hit_rate"] == 1.0
    assert summary["hit_rate_positions"] == 1
    assert summary["clv_legs"] == 3
    assert summary["clv"] is not None


def test_a_disappeared_opportunity_is_marked_unavailable_not_settled(tmp_path):
    store = _store(tmp_path)
    first = FIRST_SCAN
    records = store.record_opportunities(
        [_surebet()], feed_mode="prematch", run_mode="paper", scan_time=first
    )
    store.open_positions_from_scan(records, scan_time=first)

    result = store.open_positions_from_scan(
        [], scan_time=first + timedelta(minutes=5)
    )
    assert result["disappeared"] == 1
    position = store.list_positions()[0]
    assert position["status"] == "open"
    assert position["mark"]["available"] is False
    assert position["mark"]["disappeared_at"]
    summary = store.summary()
    assert summary["hit_rate"] == 0.0
    assert summary["settled_positions"] == 0


def test_roi_and_bankroll_use_settled_paper_positions_only(tmp_path):
    store = _store(tmp_path)
    first = FIRST_SCAN
    records = store.record_opportunities(
        [_surebet()], feed_mode="prematch", run_mode="paper", scan_time=first
    )
    store.open_positions_from_scan(records, scan_time=first)
    position = store.list_positions()[0]

    # `1` wins; the other two lose. The profit comes from the stored paper stakes.
    settled = store.settle(
        position["id"],
        [
            {"outcome_label": "1", "result": "won"},
            {"outcome_label": "X", "result": "lost"},
            {"outcome_label": "2", "result": "lost"},
        ],
    )
    assert settled is not None
    assert settled["status"] == "settled"
    assert isinstance(settled["realized_profit"], float)

    summary = store.summary()
    assert summary["no_bet_placed"] is True
    assert summary["settled_positions"] == 1
    assert summary["open_positions"] == 0
    assert summary["staked"] == settled["staked"]
    assert summary["profit"] == settled["realized_profit"]
    assert summary["bankroll"] == round(1000.0 + settled["realized_profit"], 2)
    assert summary["denominators"]["roi"] == "settled paper positions only"
    assert summary["clv"] is None
    assert summary["clv_legs"] == 0


def test_a_missing_leg_result_leaves_the_paper_position_open(tmp_path):
    store = _store(tmp_path)
    first = FIRST_SCAN
    records = store.record_opportunities(
        [_surebet()], feed_mode="prematch", run_mode="paper", scan_time=first
    )
    store.open_positions_from_scan(records, scan_time=first)
    position = store.list_positions()[0]

    result = store.settle(
        position["id"], [{"outcome_label": "1", "result": "won"}]
    )
    assert result is not None
    assert result["status"] == "open"
    assert store.summary()["roi"] is None


def test_the_paper_api_reports_its_denominators_and_disclaimer(tmp_path, monkeypatch):
    store = _store(tmp_path)
    first = FIRST_SCAN
    records = store.record_opportunities(
        [_surebet()], feed_mode="prematch", run_mode="paper", scan_time=first
    )
    store.open_positions_from_scan(records, scan_time=first)
    monkeypatch.setattr(api, "_paper_store", store)
    client = TestClient(app)

    summary = client.get("/api/paper/summary").json()
    assert summary["no_bet_placed"] is True
    assert "No bet was placed" in summary["disclaimer"]
    assert summary["denominators"]["clv"].startswith("entry stake weighted")

    positions = client.get("/api/paper/positions").json()
    assert positions["no_bet_placed"] is True
    assert len(positions["positions"]) == 1

    opportunities = client.get("/api/paper/opportunities").json()
    assert opportunities["no_bet_placed"] is True
    assert opportunities["opportunities"][0]["gate_verdict"] == "verified"
