"""N0-4: automatic closing-line capture for logged bets.

A closing line is a measurement, not a settlement. These tests pin the exact
matching rules: same event, market, line, settlement and outcome; no price after
kickoff; no result inferred after settlement; manual entry wins and is labelled.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from engine.closing_line import (
    REASON_AFTER_CUTOFF,
    REASON_BOOK_NOT_FOUND,
    REASON_LINE_MISMATCH,
    REASON_NO_KICKOFF,
    REASON_OUTCOME_NOT_OFFERED,
    REASON_SETTLEMENT_MISMATCH,
)
from engine.opportunity_metrics import event_identity
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from server import api
from server.app import app
from server.bets import BetStore

NOW = datetime.now(UTC).replace(tzinfo=None)
KICKOFF = NOW + timedelta(hours=3)
BOOK = "mbet"
LABEL = "GG"


def _match(
    *,
    bookmaker: str = BOOK,
    market_type: MarketType = MarketType.BTTS,
    settlement: str = "full_time",
    label: str = LABEL,
    value: float = 2.1,
    kickoff: datetime = KICKOFF,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="Premijer Liga BiH",
        kickoff=kickoff,
        markets=[
            Market(
                market_type=market_type,
                settlement=settlement,
                odds=[OddsValue(label=label, value=value)],
            )
        ],
    )


def _group(match: Match | None = None) -> MatchGroup:
    return MatchGroup(
        status="verified",
        canonical_home="sarajevo",
        canonical_away="zeljeznicar",
        league="premier_liga_bih",
        kickoff=KICKOFF,
        matches=[match or _match()],
    )


def _bet_payload(
    *,
    kickoff: datetime | None = KICKOFF,
    event_key: str | None = None,
    settlement: str = "full_time",
    line: str = "",
    market_type: str = "btts",
    bookmaker: str = BOOK,
    label: str = LABEL,
) -> dict:
    return {
        "surebet_id": "sb-1",
        "mode": "prematch",
        "home_team": "sarajevo",
        "away_team": "zeljeznicar",
        "market_type": market_type,
        "investment": 100.0,
        "event_key": event_key if event_key is not None else event_identity(_group()),
        "kickoff": kickoff.isoformat() if kickoff is not None else "",
        "league": "premier_liga_bih",
        "sport": "football",
        "legs": [
            {
                "bookmaker": bookmaker,
                "outcome_label": label,
                "odds": 2.0,
                "stake": 50.0,
                "accepted_odds": 2.0,
                "accepted_stake": 50.0,
                "market_type": market_type,
                "line": line,
                "settlement": settlement,
                "period": "full_time",
                "result": "",
            }
        ],
    }


def _store(tmp_path) -> BetStore:
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()
    return store


def test_a_pre_kickoff_scan_captures_the_latest_matching_price(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload())

    stats = store.capture_closing(
        [_group()],
        now=KICKOFF - timedelta(hours=1),
        mode="prematch",
    )

    assert stats["legs_captured"] == 1
    leg = store.get(bet["id"])["legs"][0]
    assert leg["closing_odds"] == 2.1
    assert leg["closing_source"] == "scan"
    assert leg["closing_reason"] == ""
    assert leg["closing_captured_at"]


def test_a_missing_price_leaves_clv_null_and_records_the_reason(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload())
    # The book offers NG, not the GG leg the bet logged.
    group = _group(_match(label="NG", value=1.8))

    stats = store.capture_closing(
        [group],
        now=KICKOFF - timedelta(hours=1),
        mode="prematch",
    )

    assert stats["legs_captured"] == 0
    leg = store.get(bet["id"])["legs"][0]
    assert "closing_odds" not in leg or leg["closing_odds"] is None
    assert leg["closing_reason"] == REASON_OUTCOME_NOT_OFFERED
    summary = store.summary()
    assert summary["clv"] is None
    assert summary["closing_capture"]["reasons"][REASON_OUTCOME_NOT_OFFERED] == 1


def test_a_wrong_settlement_is_not_captured(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload(settlement="regulation"))
    group = _group(_match(settlement="full_time"))

    store.capture_closing([group], now=KICKOFF - timedelta(hours=1), mode="prematch")

    leg = store.get(bet["id"])["legs"][0]
    assert leg.get("closing_odds") is None
    assert leg["closing_reason"] == REASON_SETTLEMENT_MISMATCH


def test_a_line_mismatch_is_not_captured(tmp_path):
    store = _store(tmp_path)
    bet = store.create(
        _bet_payload(
            market_type="over_under_2_5",
            label="Over 2.5",
            line="3.5",
        )
    )
    group = _group(
        _match(
            market_type=MarketType.OVER_UNDER_2_5,
            label="Over 2.5",
            value=1.9,
        )
    )

    store.capture_closing([group], now=KICKOFF - timedelta(hours=1), mode="prematch")

    leg = store.get(bet["id"])["legs"][0]
    assert leg.get("closing_odds") is None
    assert leg["closing_reason"] == REASON_LINE_MISMATCH


def test_a_book_that_is_no_longer_in_the_scan_is_reported(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload(bookmaker="wwin"))
    group = _group(_match(bookmaker="mbet"))

    store.capture_closing([group], now=KICKOFF - timedelta(hours=1), mode="prematch")

    leg = store.get(bet["id"])["legs"][0]
    assert leg.get("closing_odds") is None
    assert leg["closing_reason"] == REASON_BOOK_NOT_FOUND


def test_manual_closing_wins_and_is_labelled(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload())
    store.capture_closing([_group()], now=KICKOFF - timedelta(hours=1), mode="prematch")
    store.set_closing(bet["id"], [{"outcome_label": LABEL, "closing_odds": 2.3}])

    # A later scan must not overwrite the manual measurement.
    store.capture_closing(
        [_group(_match(value=2.05))],
        now=KICKOFF - timedelta(minutes=30),
        mode="prematch",
    )

    leg = store.get(bet["id"])["legs"][0]
    assert leg["closing_odds"] == 2.3
    assert leg["closing_source"] == "manual"
    assert store.summary()["closing_sources"] == {"manual": 1}


def test_a_bet_without_kickoff_is_not_captured(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload(kickoff=None))

    store.capture_closing([_group()], now=NOW, mode="prematch")

    leg = store.get(bet["id"])["legs"][0]
    assert leg.get("closing_odds") is None
    assert leg["closing_reason"] == REASON_NO_KICKOFF


def test_no_price_is_captured_after_kickoff(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload())

    store.capture_closing(
        [_group()],
        now=KICKOFF + timedelta(minutes=1),
        mode="prematch",
    )

    leg = store.get(bet["id"])["legs"][0]
    assert leg.get("closing_odds") is None
    assert leg["closing_reason"] == REASON_AFTER_CUTOFF


def test_a_settled_bet_is_never_touched(tmp_path):
    store = _store(tmp_path)
    bet = store.create(_bet_payload())
    store.settle(bet["id"], [{"outcome_label": LABEL, "result": "won"}])

    store.capture_closing([_group()], now=KICKOFF - timedelta(hours=1), mode="prematch")

    leg = store.get(bet["id"])["legs"][0]
    assert leg.get("closing_odds") is None, (
        "a closing price cannot be inferred after settlement"
    )


def test_summary_reports_each_closing_source_and_denominator(tmp_path):
    store = _store(tmp_path)
    scanned = store.create(_bet_payload())
    manual = store.create(_bet_payload())
    store.capture_closing([_group()], now=KICKOFF - timedelta(hours=1), mode="prematch")
    store.set_closing(manual["id"], [{"outcome_label": LABEL, "closing_odds": 2.2}])

    summary = store.summary()

    assert summary["closing_legs"] == 2
    assert summary["closing_sources"] == {"manual": 1, "scan": 1}
    assert summary["closing_capture"] == {
        "legs_total": 2,
        "legs_with_closing": 2,
        "legs_missing": 0,
        "by_source": {"manual": 1, "scan": 1},
        "reasons": {},
    }
    assert summary["denominators"]["closing_capture"].startswith(
        "legs with a closing source"
    )
    assert store.get(scanned["id"])["legs"][0]["closing_source"] == "scan"


def test_the_api_summary_exposes_the_last_capture(monkeypatch, tmp_path):
    store = _store(tmp_path)
    monkeypatch.setattr(api, "_bet_store", store)
    monkeypatch.setattr(
        api,
        "_closing_capture",
        {
            "prematch": {
                "bets_checked": 1,
                "legs_total": 2,
                "legs_captured": 1,
                "legs_missing": 1,
            },
            "live": {},
        },
    )

    body = TestClient(app).get("/api/bets/summary?days=30").json()

    assert body["closing_capture"]["legs_total"] == 0
    assert body["last_capture"]["prematch"]["legs_captured"] == 1


def test_a_scan_passes_its_verified_groups_to_the_capture(monkeypatch):
    calls: list[dict] = []

    class FakeStore:
        def capture_closing(self, groups, **kwargs):
            calls.append({"groups": groups, **kwargs})
            return {"bets_checked": 0, "legs_total": 0, "legs_captured": 0}

    monkeypatch.setattr(api, "_bet_store", FakeStore())
    monkeypatch.setattr(
        api,
        "_bookmaker_enabled",
        {book: False for book in api.BOOKMAKERS},
    )

    asyncio.run(api.run_scan("prematch"))

    assert calls, "run_scan must capture closing lines even when no bet exists"
    assert calls[0]["groups"] == []
    assert calls[0]["mode"] == "prematch"
    assert calls[0]["excluded_books"] == set()
