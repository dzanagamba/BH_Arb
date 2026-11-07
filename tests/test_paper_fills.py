"""N2-2: paper fills reject/partially fill deterministically, never invent cash."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

from models.schemas import MarketType, Surebet, SurebetStake
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
        id="sb-fill-1",
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


def _store(tmp_path, **kwargs) -> PaperStore:
    store = PaperStore(str(tmp_path / "paper.sqlite3"), bankroll_start=1000.0, **kwargs)
    store.initialize()
    return store


def _open(store: PaperStore, odds: tuple[float, float, float] = (2.2, 4.0, 4.0)):
    records = store.record_opportunities(
        [_surebet(odds)],
        feed_mode="prematch",
        run_mode="paper",
        scan_time=FIRST_SCAN,
    )
    store.open_positions_from_scan(records, scan_time=FIRST_SCAN)
    return store.list_positions()[0]


def _mark(store: PaperStore, odds: tuple[float, float, float] = (2.2, 4.0, 4.0)):
    scan = FIRST_SCAN + timedelta(minutes=5)
    records = store.record_opportunities(
        [_surebet(odds)],
        feed_mode="prematch",
        run_mode="paper",
        scan_time=scan,
    )
    store.open_positions_from_scan(records, scan_time=scan)
    return store.list_positions()[0]


def test_a_fully_filled_position_has_a_positive_worst_case_and_execution_roi(tmp_path):
    store = _store(tmp_path, book_caps={book: 1000 for book in ("mbet", "wwin", "sportplus")})
    _open(store)
    position = _mark(store)

    mark = position["mark"]
    assert mark["fill_complete"] is True
    assert {fill["status"] for fill in mark["fills"]} == {"filled"}
    assert mark["filled_stake"] == mark["planned_stake"]
    assert mark["worst_case_profit"] > 0

    summary = store.summary()
    execution = summary["execution_adjusted"]
    assert execution["positions"] == 1
    assert execution["roi"] is not None and execution["roi"] > 0
    assert execution["denominator"].startswith("open positions with every leg")
    assert summary["simulated_open"]["label"].startswith("optimistic:")


def test_a_per_book_cap_partially_fills_a_leg_and_stays_execution_complete(tmp_path):
    store = _store(
        tmp_path,
        book_caps={"mbet": 10, "wwin": 1000, "sportplus": 1000},
    )
    _open(store)
    position = _mark(store)

    fills = {fill["bookmaker"]: fill for fill in position["mark"]["fills"]}
    assert fills["mbet"]["status"] == "partial"
    assert fills["mbet"]["filled_stake"] == 10
    assert fills["wwin"]["status"] == "filled"
    assert position["mark"]["fill_complete"] is True
    assert position["mark"]["filled_stake"] < position["mark"]["planned_stake"]
    assert store.summary()["execution_adjusted"]["positions"] == 1


def test_a_moved_price_rejects_the_leg_and_is_not_called_profitable(tmp_path):
    store = _store(tmp_path, book_caps={book: 1000 for book in ("mbet", "wwin", "sportplus")})
    _open(store)
    position = _mark(store, odds=(2.1, 3.9, 3.9))

    assert position["mark"]["fill_complete"] is False
    assert {fill["status"] for fill in position["mark"]["fills"]} == {"rejected"}
    assert position["mark"]["worst_case_profit"] is None

    summary = store.summary()
    assert summary["execution_adjusted"]["positions"] == 0
    assert summary["execution_adjusted"]["roi"] is None
    assert summary["execution_adjusted"]["incomplete_positions"] == 1
    # The optimistic number is still available, but explicitly labelled.
    assert summary["simulated_open"]["roi_if_all_filled"] is not None
    assert "optimistic" in summary["simulated_open"]["label"]


def test_a_partial_rejection_has_a_negative_worst_case(tmp_path):
    store = _store(tmp_path, book_caps={book: 1000 for book in ("mbet", "wwin", "sportplus")})
    _open(store)
    # Only the last leg moved; the other two filled. The unfilled outcome can
    # return 0, so the worst case is the negative filled stake.
    position = _mark(store, odds=(2.2, 4.0, 3.9))

    fills = {fill["bookmaker"]: fill for fill in position["mark"]["fills"]}
    assert fills["sportplus"]["status"] == "rejected"
    assert fills["mbet"]["status"] == "filled"
    assert position["mark"]["fill_complete"] is False
    assert position["mark"]["worst_case_profit"] < 0
    assert store.summary()["execution_adjusted"]["positions"] == 0


def test_a_disappeared_leg_is_missing_and_incomplete(tmp_path):
    store = _store(tmp_path)
    _open(store)
    store.open_positions_from_scan([], scan_time=FIRST_SCAN + timedelta(minutes=5))

    position = store.list_positions()[0]
    assert position["mark"]["fill_complete"] is False
    assert {fill["status"] for fill in position["mark"]["fills"]} == {"missing"}
    assert position["mark"]["worst_case_profit"] is None
    summary = store.summary()
    assert summary["execution_adjusted"]["positions"] == 0
    assert summary["execution_adjusted"]["incomplete_positions"] == 1


def test_price_tolerance_is_configurable_and_fill_disabled_keeps_old_behavior(tmp_path):
    tolerant = _store(
        tmp_path / "tolerant",
        price_tolerance=0.01,
        book_caps={book: 1000 for book in ("mbet", "wwin", "sportplus")},
    )
    _open(tolerant)
    # A 0.5% move is inside a 1% tolerance.
    position = _mark(tolerant, odds=(2.21, 4.02, 4.02))
    assert {fill["status"] for fill in position["mark"]["fills"]} == {"filled"}

    disabled = _store(tmp_path / "disabled", fill_enabled=False)
    _open(disabled)
    position = _mark(disabled, odds=(2.1, 3.9, 3.9))
    assert {fill["status"] for fill in position["mark"]["fills"]} == {"filled"}
    assert position["mark"]["fill_complete"] is True


def test_settlement_uses_the_filled_stake_not_the_planned_stake(tmp_path):
    store = _store(
        tmp_path,
        book_caps={"mbet": 10, "wwin": 1000, "sportplus": 1000},
    )
    _open(store)
    position = _mark(store)

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
    assert settled["staked"] == position["mark"]["filled_stake"]
    assert settled["staked"] < position["mark"]["planned_stake"]
    assert settled["settled_fill_complete"] is True


def test_csv_export_carries_the_fill_record(tmp_path):
    store = _store(
        tmp_path,
        book_caps={"mbet": 10, "wwin": 1000, "sportplus": 1000},
    )
    _open(store)
    _mark(store)

    rows = list(csv.DictReader(io.StringIO(store.export_csv(days=30))))
    position_row = next(row for row in rows if row["kind"] == "position")

    assert position_row["fill_complete"] == "True"
    assert float(position_row["filled_stake"]) < float(position_row["planned_stake"])
    fills = json.loads(position_row["fills_json"])
    assert {fill["status"] for fill in fills} == {"partial", "filled"}


def test_csv_export_escapes_formula_leading_feed_text(tmp_path):
    store = _store(tmp_path, book_caps={"mbet": 10, "wwin": 1000, "sportplus": 1000})
    surebet = _surebet().model_copy(
        update={"home_team": "=1+1", "away_team": "@SUM(A1)", "league": "-BiH"}
    )
    records = store.record_opportunities(
        [surebet], feed_mode="prematch", run_mode="paper", scan_time=FIRST_SCAN
    )
    store.open_positions_from_scan(records, scan_time=FIRST_SCAN)

    rows = list(csv.DictReader(io.StringIO(store.export_csv(days=30))))
    position_row = next(row for row in rows if row["kind"] == "position")

    assert position_row["home_team"] == "'=1+1"
    assert position_row["away_team"] == "'@SUM(A1)"
    assert position_row["league"] == "'-BiH"
