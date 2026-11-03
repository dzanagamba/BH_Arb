"""A real scan learns before matching; tiny scans do not rewrite the ledger."""

from __future__ import annotations

from datetime import datetime

from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key
from models.schemas import Market, MarketType, Match, OddsValue
from server.api import learn_scan_mappings

K = datetime(2026, 11, 7, 18, 0)


def _m(book: str, home: str, away: str, event_id: str) -> Match:
    return Match(
        bookmaker=book,
        home_team=home,
        away_team=away,
        league="Test League",
        kickoff=K,
        event_id=event_id,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[OddsValue(label="1", value=2.0)],
            )
        ],
    )


def test_the_scan_helper_persists_the_learned_ledger(tmp_path):
    path = tmp_path / "evidence.json"
    matches = [
        _m("mdshop", "Alpha", "Beta United", "1"),
        _m("mbet", "Alpha", "Beta Utd", "2"),
    ]
    report = learn_scan_mappings(matches, "scan-1", str(path))
    assert report["counts"]["accepted"] >= 1
    loaded = MappingLedger(path).load()
    claim = loaded.get("team_alias", team_alias_key("Beta United", "Beta Utd"))
    assert claim is not None
    assert claim.status == "accepted"


def test_prune_keeps_the_strongest_evidence(tmp_path):
    ledger = MappingLedger(tmp_path / "evidence.json")
    key = team_alias_key("A", "B")
    for index in range(10):
        ledger.accept(
            "team_alias",
            key,
            [
                Evidence(
                    type="similarity" if index % 2 else "exact_shared_fixture",
                    scan=f"s{index}",
                    observed_at=f"2026-11-0{index % 9 + 1}T00:00:00",
                )
            ],
            "test",
        )
    assert ledger.prune(max_evidence=3) > 0
    claim = ledger.get("team_alias", key)
    assert len(claim.evidence) <= 3
    assert any(item.type == "exact_shared_fixture" for item in claim.evidence)


def test_prune_keeps_a_league_fingerprint_union(tmp_path):
    ledger = MappingLedger(tmp_path / "evidence.json")
    ledger.accept(
        "league_fingerprint",
        "test league",
        [Evidence(type="league_fingerprint", detail={"teams": ["a", "b"]})],
    )
    ledger.accept(
        "league_fingerprint",
        "test league",
        [Evidence(type="league_fingerprint", detail={"teams": ["c", "d"]})],
    )
    ledger.prune()
    claim = ledger.get("league_fingerprint", "test league")
    assert len(claim.evidence) == 1
    assert claim.evidence[0].detail["teams"] == ["a", "b", "c", "d"]
