"""Coverage diagnostics are read-only and count the ledger honestly."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key
from models.schemas import Market, MarketType, Match, OddsValue
from server import api
from server.app import app
from server.mapping_coverage import build_coverage


def _match(book: str, home: str, away: str) -> Match:
    return Match(
        bookmaker=book,
        home_team=home,
        away_team=away,
        league="Test League",
        kickoff=datetime(2026, 11, 7, 18, 0),
        event_id="1",
        deep_link_verified=True,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[OddsValue(label="1", value=2.0)])],
    )


def _ledger(tmp_path: Path) -> MappingLedger:
    ledger = MappingLedger(tmp_path / "evidence.json")
    ledger.accept(
        "team_alias",
        team_alias_key("A", "B"),
        [Evidence(type="betradar_shared_id", scan="s1")],
        "proven",
    )
    ledger.quarantine(
        "team_alias",
        team_alias_key("C", "D"),
        [Evidence(type="similarity", scan="s1")],
        "similarity_only",
    )
    return ledger


def test_coverage_counts_books_claims_and_quarantine(tmp_path):
    report = build_coverage(
        _ledger(tmp_path),
        [_match("mbet", "A", "B"), _match("wwin", "A", "B")],
        [{"status": "verified"}],
        mode="prematch",
        unmapped_markets={"mbet:999": 2},
    )
    assert report["books"]["mbet"]["matches"] == 1
    assert report["books"]["mbet"]["markets"] == 1
    assert report["groups"] == {"total": 1, "verified": 1}
    assert report["claims"]["by_status"] == {"accepted": 1, "quarantined": 1}
    assert report["quarantined"][0]["reason"] == "similarity_only"
    assert report["unmapped_markets"] == {"mbet:999": 2}


def test_the_route_is_read_only_and_served():
    client = TestClient(app)
    response = client.get("/api/mapping/coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "prematch"
    assert "claims" in body and "quarantined" in body
    assert client.post("/api/mapping/coverage").status_code == 405


def test_cached_dict_rows_are_counted(monkeypatch):
    """The live cache holds JSON dicts, not Match models."""
    monkeypatch.setattr(
        api,
        "cached_matches",
        [
            {"bookmaker": "mbet", "markets": [{"market_type": "1x2"}, {"market_type": "btts"}]},
            {"bookmaker": "wwin", "markets": []},
        ],
    )
    monkeypatch.setattr(api, "cached_match_groups_report", [{"status": "verified"}])

    response = TestClient(app).get("/api/mapping/coverage")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["books"] == {
        "mbet": {"matches": 1, "markets": 2},
        "wwin": {"matches": 1, "markets": 0},
    }
    assert body["groups"] == {"total": 1, "verified": 1}
