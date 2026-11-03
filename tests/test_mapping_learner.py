"""The learner turns shared fixtures into evidence, never into guesses."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from engine.mapping_evidence import MappingLedger, league_equivalence_key, team_alias_key
from engine.mapping_learner import learn
from models.schemas import Market, MarketType, Match, OddsValue

K = datetime(2026, 11, 7, 18, 0)


def _m(
    book: str,
    home: str,
    away: str,
    league: str,
    *,
    kickoff: datetime = K,
    betradar_id: str = "",
    event_id: str = "1",
) -> Match:
    return Match(
        bookmaker=book,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        event_id=event_id,
        betradar_id=betradar_id,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=2.0),
                    OddsValue(label="X", value=3.0),
                    OddsValue(label="2", value=3.0),
                ],
            )
        ],
    )


def _ledger(tmp_path: Path) -> MappingLedger:
    return MappingLedger(tmp_path / "evidence.json")


def test_shared_betradar_id_accepts_aliases_and_league(tmp_path):
    a = _m("mdshop", "Man. City", "Arsenal", "Liga Evrope", betradar_id="111")
    b = _m("wwin", "Manchester City FC", "Arsenal London", "Liga Konferencija", betradar_id="111")
    ledger, report = learn([a, b], _ledger(tmp_path), scan="s1")

    for left, right in (("Man. City", "Manchester City FC"), ("Arsenal", "Arsenal London")):
        claim = ledger.get("team_alias", team_alias_key(left, right))
        assert claim is not None
        assert claim.status == "accepted", (left, right, claim.reason)
        assert claim.evidence[0].type == "betradar_shared_id"

    league = ledger.get("league_equivalence", league_equivalence_key("europa_league", "conference_league"))
    assert league is not None
    assert league.status == "accepted"
    assert report.accepted


def test_exact_shared_fixture_accepts_the_differing_slot(tmp_path):
    a = _m("mdshop", "Alpha", "Beta United", "Liga Evrope")
    b = _m("mbet", "Alpha", "Beta Utd", "Liga Konferencija")
    ledger, _ = learn([a, b], _ledger(tmp_path), scan="s1")

    claim = ledger.get("team_alias", team_alias_key("Beta United", "Beta Utd"))
    assert claim is not None
    assert claim.status == "accepted"
    assert claim.evidence[0].type == "exact_shared_fixture"
    assert claim.evidence[0].detail["other_slot_exact"] is True

    league = ledger.get("league_equivalence", league_equivalence_key("europa_league", "conference_league"))
    assert league is not None
    assert league.status == "accepted"


def test_similarity_alone_is_quarantined(tmp_path):
    a = _m("mdshop", "Manchester United", "Arsenal", "England 1")
    b = _m("wwin", "Man United", "Arsenal FC", "Premier League")
    ledger, _ = learn([a, b], _ledger(tmp_path), scan="s1")

    claim = ledger.get("team_alias", team_alias_key("Manchester United", "Man United"))
    assert claim is not None
    assert claim.status == "quarantined"
    assert claim.reason == "similarity_only"
    assert not ledger.is_accepted("team_alias", team_alias_key("Manchester United", "Man United"))


def test_an_opponent_pair_cannot_become_an_alias(tmp_path):
    a = _m("mdshop", "Alpha", "Beta", "Test League")
    b = _m("mbet", "Alpha", "Gamma", "Test League")
    c = _m("wwin", "Beta", "Gamma", "Test League")
    ledger, report = learn([a, b, c], _ledger(tmp_path), scan="s1")

    claim = ledger.get("team_alias", team_alias_key("Beta", "Gamma"))
    assert claim is not None
    assert claim.status == "rejected"
    assert "opponent_contradiction" in claim.contradictions
    assert any("team_alias" in key for key in report.rejected)


def test_an_ambiguous_league_name_is_quarantined(tmp_path):
    a = _m("mdshop", "Alpha", "Beta", "Serija A")
    b = _m("mbet", "Alpha", "Beta", "Italy 1")
    c = _m("mdshop", "Gamma", "Delta", "Serija A")
    d = _m("mbet", "Gamma", "Delta", "Brazil 1")
    ledger, _ = learn([a, b, c, d], _ledger(tmp_path), scan="s1")

    first = ledger.get("league_equivalence", league_equivalence_key("serija a", "serie_a"))
    second = ledger.get("league_equivalence", league_equivalence_key("serija a", "brazil_serie_a"))
    assert first is not None and first.status == "quarantined"
    assert second is not None and second.status == "quarantined"
    assert first.reason == "ambiguous_league_name"


def test_generic_leagues_are_not_mapped(tmp_path):
    a = _m("mdshop", "Alpha", "Beta", "Football")
    b = _m("mbet", "Alpha", "Beta", "Premier League")
    ledger, _ = learn([a, b], _ledger(tmp_path), scan="s1")
    assert not any(
        claim.kind == "league_equivalence" for claim in ledger.claims.values()
    )


def test_evidence_carries_scan_and_books(tmp_path):
    a = _m("mdshop", "Alpha", "Beta United", "Test League")
    b = _m("mbet", "Alpha", "Beta Utd", "Test League")
    ledger, _ = learn([a, b], _ledger(tmp_path), scan="scan-42")
    claim = ledger.get("team_alias", team_alias_key("Beta United", "Beta Utd"))
    evidence = claim.evidence[0]
    assert evidence.scan == "scan-42"
    assert evidence.books == ("mdshop", "mbet")
    assert evidence.detail["kickoff"]


def test_a_repeated_scan_merges_evidence(tmp_path):
    a = _m("mdshop", "Alpha", "Beta United", "Test League")
    b = _m("mbet", "Alpha", "Beta Utd", "Test League")
    ledger = _ledger(tmp_path)
    learn([a, b], ledger, scan="s1")
    learn([a, b], ledger, scan="s2")
    claim = ledger.get("team_alias", team_alias_key("Beta United", "Beta Utd"))
    assert len(claim.evidence) == 2


def test_different_betradar_ids_learn_nothing(tmp_path):
    a = _m("mdshop", "Man. City", "Arsenal", "England 1", betradar_id="111")
    b = _m("wwin", "Manchester City FC", "Arsenal London", "Premier League", betradar_id="222")
    ledger, report = learn([a, b], _ledger(tmp_path), scan="s1")
    assert not ledger.claims
    assert report.pairs_considered == 1


def test_a_kickoff_outside_the_window_learns_nothing(tmp_path):
    a = _m("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga")
    b = _m(
        "mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH",
        kickoff=K + timedelta(minutes=16),
    )
    ledger, _ = learn([a, b], _ledger(tmp_path), scan="s1")
    assert not ledger.claims
