"""Tests for the match grouping engine (league/date gates, swap detection)."""

from datetime import datetime, timedelta

from rapidfuzz import fuzz

from engine.matcher import TEAM_MATCH_RATIO, MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue


def _match(bookmaker, home, away, league, kickoff, odds=None):
    if odds is None:
        odds = [
            OddsValue(label="1", value=2.0),
            OddsValue(label="X", value=3.0),
            OddsValue(label="2", value=4.0),
        ]
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        event_id=f"{bookmaker}-{home}",
        deep_link_verified=True,
        url=f"https://example.test/{bookmaker}",
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=odds)],
    )


def _kickoff(hour=18, minute=0, day_offset=0):
    return datetime(2026, 8, 15, hour, minute) + timedelta(days=day_offset)


def test_same_match_groups_across_bookmakers():
    m1 = _match("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", _kickoff())
    m2 = _match("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", _kickoff())
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 1
    assert groups[0].status == "verified"
    assert len(groups[0].matches) == 2


def test_league_gate_rejects_different_leagues():
    m1 = _match("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga", _kickoff())
    m2 = _match("mbet", "Sarajevo", "Zeljeznicar", "Engleska - Premier liga", _kickoff())
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 0


def test_kickoff_gate_rejects_big_time_gap():
    m1 = _match("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga", _kickoff())
    m2 = _match("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH",
                _kickoff() + timedelta(hours=3))
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 0


def test_home_away_swap_detection():
    m1 = _match("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga", _kickoff())
    m2 = _match("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", _kickoff(),
                odds=[
                    OddsValue(label="1", value=2.0),
                    OddsValue(label="X", value=3.0),
                    OddsValue(label="2", value=4.0),
                ])
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 1
    assert groups[0].status == "verified"
    swapped = next(m for m in groups[0].matches if m.bookmaker == "mbet")
    assert swapped.is_swapped is True
    # After swap, bookmaker B's "1" (2.0) must now be labelled "2"
    odds_by_label = {o.label: o.value for o in swapped.markets[0].odds}
    assert odds_by_label["2"] == 2.0
    assert odds_by_label["1"] == 4.0


def test_no_group_when_only_one_bookmaker():
    m1 = _match("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga", _kickoff())
    groups = MatchMatcher().group_matches([m1])
    assert len(groups) == 0


def test_u21_does_not_match_senior_team():
    m1 = _match("mdshop", "Sarajevo U21", "Zeljeznicar U21", "BiH - Premier Liga", _kickoff())
    m2 = _match("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", _kickoff())
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 0


def test_women_does_not_match_men():
    m1 = _match("mdshop", "Sarajevo", "Željezničar", "Ženski Premijer Liga", _kickoff())
    m2 = _match("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", _kickoff())
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 0


def test_allowlisted_alias_below_the_surface_floor_still_groups():
    """An approved alias must reach the gate even when the spellings score low.

    "Urawa Red Diamonds" / "Urawa Reds" is an entry in the shipped allowlist,
    but scores 0.67 — under the scorer's per-team floor. The scorer used to
    prune the pair before the certainty gate (which verifies it) ever saw it,
    so approving the candidate could not clear it from the review queue.
    """
    assert fuzz.token_set_ratio("Urawa Red Diamonds", "Urawa Reds") / 100 < TEAM_MATCH_RATIO

    m1 = _match("mbet", "Kashiwa Reysol", "Urawa Red Diamonds", "Japan - J.Liga", _kickoff())
    m2 = _match("wwin", "Kashiwa", "Urawa Reds", "JAPAN - 1.LIGA", _kickoff())
    groups = MatchMatcher().group_matches([m1, m2])
    assert len(groups) == 1
    assert {m.bookmaker for m in groups[0].matches} == {"mbet", "wwin"}


def test_without_the_allowlist_the_surface_floor_still_applies():
    matcher = MatchMatcher()
    matcher._alias_allowlist.clear()
    matcher.gate.alias_allowlist = set()

    m1 = _match("mbet", "Kashiwa Reysol", "Urawa Red Diamonds", "Japan - J.Liga", _kickoff())
    m2 = _match("wwin", "Kashiwa", "Urawa Reds", "JAPAN - 1.LIGA", _kickoff())
    assert matcher.group_matches([m1, m2]) == []
