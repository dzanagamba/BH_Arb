"""Ambiguous league names are resolved per fixture by their team sets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from engine.certainty import CertaintyGate
from engine.league_resolver import LeagueResolver
from engine.mapping_evidence import MappingLedger
from engine.mapping_learner import learn
from models.schemas import Market, MarketType, Match, OddsValue

K = datetime(2026, 11, 7, 18, 0)


def _m(book: str, home: str, away: str, league: str, event_id: str) -> Match:
    return Match(
        bookmaker=book,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=K,
        event_id=event_id,
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


def _corpus() -> list[Match]:
    return [
        _m("mdshop", "Alpha", "Beta", "Serija A", "1"),
        _m("mbet", "Alpha", "Beta", "Italy 1", "2"),
        _m("mdshop", "Gamma", "Delta", "Serija A", "3"),
        _m("mbet", "Gamma", "Delta", "Italy 1", "4"),
        _m("mdshop", "Epsilon", "Zeta", "Serija A", "5"),
        _m("mbet", "Epsilon", "Zeta", "Brazil 1", "6"),
        _m("mdshop", "Eta", "Theta", "Serija A", "7"),
        _m("mbet", "Eta", "Theta", "Brazil 1", "8"),
    ]


def _ledger(tmp_path: Path) -> MappingLedger:
    ledger = MappingLedger(tmp_path / "evidence.json")
    learn(_corpus(), ledger, scan="s1")
    return ledger


def test_fingerprints_are_recorded(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.get("league_fingerprint", "serija a") is not None
    assert ledger.get("league_fingerprint", "serie_a") is not None
    assert ledger.get("league_fingerprint", "brazil_serie_a") is not None


def test_the_specific_league_wins_for_an_italian_fixture(tmp_path):
    ledger = _ledger(tmp_path)
    resolver = LeagueResolver(ledger)
    assert resolver.same_competition("serija a", "serie_a", "Alpha", "Beta")
    assert not resolver.same_competition("serija a", "brazil_serie_a", "Alpha", "Beta")


def test_the_specific_league_wins_for_a_brazilian_fixture(tmp_path):
    ledger = _ledger(tmp_path)
    resolver = LeagueResolver(ledger)
    assert resolver.same_competition("serija a", "brazil_serie_a", "Epsilon", "Zeta")
    assert not resolver.same_competition("serija a", "serie_a", "Epsilon", "Zeta")


def test_the_gate_accepts_a_fingerprint_league(tmp_path):
    from engine.mapping_evidence import Evidence

    ledger = MappingLedger(tmp_path / "manual.json")
    ledger.accept(
        "league_fingerprint",
        "europa_league",
        [Evidence(type="league_fingerprint", detail={"teams": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]})],
    )
    ledger.accept(
        "league_fingerprint",
        "conference_league",
        [Evidence(type="league_fingerprint", detail={"teams": ["alpha", "beta", "gamma", "delta"]})],
    )
    gate = CertaintyGate(evidence=ledger)
    a = _m("mdshop", "Alpha", "Beta", "Liga Evrope", "1")
    b = _m("mbet", "Alpha", "Beta", "Liga Konferencija", "2")
    gate.normalize([a, b])
    result = gate.evaluate_pair(a, b)
    assert result.status == "verified", result.reasons
    league = next(e for e in result.evidence if e.rule == "league_identity")
    assert league.reason == "league_fingerprint"


def test_a_generic_name_is_resolved_by_its_fixture(tmp_path):
    corpus = [
        _m("mdshop", "Mainz", "Bayern Munich", "Bundesliga", "1"),
        _m("betole", "Mainz", "Bayern Munich", "Germany, Bundesliga", "2"),
        _m("mdshop", "Dortmund", "Leipzig", "Bundesliga", "3"),
        _m("betole", "Dortmund", "Leipzig", "Germany, Bundesliga", "4"),
        _m("mdshop", "Stuttgart", "Werder", "Bundesliga", "5"),
        _m("betole", "Stuttgart", "Werder", "Germany, Bundesliga", "6"),
    ]
    ledger = MappingLedger(tmp_path / "generic.json")
    learn(corpus, ledger, scan="s1")

    assert ledger.get("league_fingerprint", "bundesliga") is not None
    resolver = LeagueResolver(ledger)
    assert resolver.same_competition(
        "bundesliga", "germany, bundesliga", "Mainz", "Bayern Munich"
    )
    assert not resolver.same_competition(
        "bundesliga", "germany, bundesliga", "Alpha", "Beta"
    )


def test_unrelated_sets_do_not_match(tmp_path):
    ledger = _ledger(tmp_path)
    resolver = LeagueResolver(ledger)
    assert not resolver.same_competition("serie_a", "brazil_serie_a", "Alpha", "Beta")
