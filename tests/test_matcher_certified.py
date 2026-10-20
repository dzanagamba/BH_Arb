"""Matcher integration: only gate-passing groups are returned."""

from datetime import datetime, timedelta

from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue

K = datetime(2026, 9, 25, 18, 0)


def _m(bookmaker, home, away, league, kickoff=K, event_id="", link_ok=True):
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        url=f"https://example.test/{bookmaker}/{event_id}" if event_id else "",
        event_id=event_id,
        deep_link_verified=link_ok,
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


def test_verified_group_returned_with_evidence():
    a = _m("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 1
    assert groups[0].status == "verified"
    assert any(e.rule == "team_identity" for e in groups[0].evidence)


def test_group_with_unresolved_team_is_not_returned():
    a = _m("mdshop", "Alpha FC", "Beta United", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Gamma SC", "Delta Club", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 0


def test_europa_conference_merge_only_via_declared_equivalence():
    a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
    b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
    import engine.matcher as matcher_mod

    assert not hasattr(matcher_mod, "EUROPEAN_COMPATIBLE_LEAGUES"), (
        "blanket European merging must be removed"
    )
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 1
    group = groups[0]
    assert group.status == "verified"
    league_evidence = next(e for e in group.evidence if e.rule == "league_identity")
    assert set(league_evidence.league_pair) == {"europa_league", "conference_league"}


def test_kickoff_gap_of_16_minutes_is_not_verified():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m(
        "mbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        kickoff=K + timedelta(minutes=16),
        event_id="2",
    )
    groups = MatchMatcher().group_matches([a, b])
    assert groups == []


def test_same_teams_three_hours_apart_never_group():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m(
        "mbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        kickoff=K + timedelta(hours=3),
        event_id="2",
    )
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 0


def test_unverified_link_yields_suggested_or_dropped_not_verified():
    a = _m(
        "mdshop",
        "Sarajevo",
        "Zeljeznicar",
        "BiH - Premier Liga",
        event_id="1",
        link_ok=False,
    )
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert groups == []


def test_unreviewed_mapping_variation_is_not_verified():
    a = _m("mdshop", "Sporting", "Alverca", "Primeira Liga", event_id="1")
    b = _m("mbet", "Sporting CP", "Alverca", "Liga Portugal", event_id="2")
    matcher = MatchMatcher()
    # The shipped allowlist may hold this pair (derived from shared fixtures);
    # the rule under test is about a pair nobody has reviewed.
    matcher.gate.alias_allowlist = set()
    groups = matcher.group_matches([a, b])
    assert groups == []


def test_gate_rejected_singleton_cannot_later_merge_into_wrong_group():
    anchor = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    # Admiralbet, not a book that declares `supports_event_id: false`: this test
    # needs a match the gate actually refuses, and a book that has declared it
    # has no per-event route is accepted with that declaration as evidence.
    rejected = _m(
        "admiralbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        event_id="2",
        link_ok=False,
    )
    later = _m("sportplus", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="3")

    groups = MatchMatcher().group_matches([anchor, rejected, later])

    assert len(groups) == 1
    assert {m.bookmaker for m in groups[0].matches} == {"mdshop", "sportplus"}
    assert all(m.bookmaker != "admiralbet" for m in groups[0].matches)
