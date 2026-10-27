"""Reviewed aliases: accepted below the allowlist's similarity floor, nothing else waived.

``config/team_alias_reviewed.json`` holds team spellings a person reviewed from
shared-fixture evidence. "Man.Utd" and "Manchester United" score about 60, under
the 90 floor every ``config/team_alias_allowlist.json`` entry is held to, and are
still one club. The gate accepts a reviewed pair without the floor; league,
kickoff, category and link checks apply to it exactly as to any alias.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from engine.certainty import CertaintyGate
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue

REVIEWED_FILE = Path(__file__).parents[1] / "config" / "team_alias_reviewed.json"
K = datetime(2026, 10, 21, 16, 45)
PAIR = "Man.Utd|Manchester United"


def _m(book, home, away, league="Engleska 1", kickoff=K, tags=None, event_id="1"):
    return Match(
        bookmaker=book,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        home_team_normalized=home.lower(),
        away_team_normalized=away.lower(),
        category_tags=tags or [],
        event_id=event_id,
        deep_link_verified=True,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0),
            OddsValue(label="X", value=3.4),
            OddsValue(label="2", value=3.6),
        ])],
    )


def _gate(reviewed=frozenset({PAIR}), allowlist=frozenset()):
    gate = CertaintyGate(alias_allowlist=set(allowlist), reviewed_aliases=set(reviewed))
    return gate


def test_a_reviewed_pair_below_the_floor_verifies():
    gate = _gate()
    a, b = _m("mbet", "Como", "Manchester United"), _m("wwin", "Como", "Man.Utd")
    gate.normalize([a, b])
    result = gate.evaluate_pair(a, b)
    assert result.status == "verified", result.reasons
    team = next(e for e in result.evidence if e.rule == "team_identity")
    assert team.source == "allowlist"


def test_the_same_pair_only_in_the_allowlist_still_needs_the_floor():
    gate = _gate(reviewed=frozenset(), allowlist={PAIR})
    a, b = _m("mbet", "Como", "Manchester United"), _m("wwin", "Como", "Man.Utd")
    gate.normalize([a, b])
    assert "team_unresolved" in gate.evaluate_pair(a, b).reasons


def test_a_reviewed_pair_still_needs_the_kickoff():
    gate = _gate()
    a = _m("mbet", "Como", "Manchester United")
    b = _m("wwin", "Como", "Man.Utd", kickoff=K + timedelta(minutes=60))
    gate.normalize([a, b])
    result = gate.evaluate_pair(a, b)
    assert result.status != "verified"
    assert {"kickoff_delta", "team_unresolved"} <= set(result.reasons)


def test_a_reviewed_pair_still_needs_the_category():
    gate = _gate()
    a = _m("mbet", "Como", "Manchester United", tags=["U21"])
    b = _m("wwin", "Como", "Man.Utd")
    gate.normalize([a, b])
    assert gate.evaluate_pair(a, b).status == "rejected"


def test_a_reviewed_pair_still_needs_the_league():
    gate = _gate()
    a = _m("mbet", "Como", "Manchester United", league="Engleska 1")
    b = _m("wwin", "Como", "Man.Utd", league="Italija 1")
    gate.normalize([a, b])
    result = gate.evaluate_pair(a, b)
    assert result.status == "rejected"
    assert "league_mismatch" in result.reasons


def test_a_reviewed_pair_is_unordered_and_spelling_tolerant():
    gate = _gate(reviewed={"Manchester United|Man.Utd"})
    assert gate._is_reviewed("man utd", "MANCHESTER UNITED")
    assert not gate._is_reviewed("Man.Utd", "Manchester City")


def test_the_matcher_groups_on_a_reviewed_pair_and_its_youth_side():
    matcher = MatchMatcher()
    matcher._reviewed_aliases.clear()
    matcher._reviewed_partners.clear()
    matcher._reviewed_aliases.add("Testclub FC|TCF Testville")
    key = CertaintyGate._raw_team_key
    matcher._reviewed_partners[key("Testclub FC")] = {"TCF Testville"}
    matcher._reviewed_partners[key("TCF Testville")] = {"Testclub FC"}

    senior = matcher.group_matches([
        _m("mbet", "Testclub FC", "Opponent", league="ENGLAND 3", event_id="1"),
        _m("wwin", "TCF Testville", "Opponent", league="Engleska 3", event_id="2"),
    ])
    assert len(senior) == 1

    youth = matcher.group_matches([
        _m("mbet", "Testclub FC U19", "Opponent U19", league="UEFA Youth League - League phase", event_id="3"),
        _m("sportplus", "ML/TCF Testville", "Opponent", league="UEFA - LIGA MLADIH", event_id="4"),
    ])
    assert len(youth) == 1
    assert "Testclub FC U19|TCF Testville U19" in matcher._reviewed_aliases


# --- the shipped file -------------------------------------------------------

@pytest.fixture(scope="module")
def reviewed() -> dict:
    return json.loads(REVIEWED_FILE.read_text(encoding="utf-8"))


def test_the_shipped_file_says_what_it_is(reviewed):
    assert "90" in reviewed["_about"] and reviewed["reviewed_at"]


def test_every_entry_is_one_pair_and_no_pair_is_both_approved_and_rejected(reviewed):
    approved = [e["alias"] for e in reviewed["approved"]]
    rejected = [e["alias"] for e in reviewed["rejected"]]
    for alias in approved + rejected:
        left, right = alias.split("|")
        assert left.strip() and right.strip() and alias.count("|") == 1, alias
    key = CertaintyGate._raw_team_key
    as_sets = lambda aliases: {frozenset(key(p) for p in a.split("|")) for a in aliases}  # noqa: E731
    assert not as_sets(approved) & as_sets(rejected)
    assert all(e.get("reason") for e in reviewed["rejected"]), "a rejection needs its reason"


@pytest.mark.parametrize("generic", ["Independiente", "Deportivo", "Lokomotiv", "Wanderers"])
def test_no_approved_pair_rests_on_a_generic_club_name(reviewed, generic):
    """A bare generic name would alias every club that shares it."""
    for entry in reviewed["approved"]:
        assert generic not in entry["alias"].split("|"), entry["alias"]


def test_the_matcher_loads_the_shipped_file(reviewed):
    matcher = MatchMatcher()
    assert len(matcher._reviewed_aliases) == len(reviewed["approved"])
    assert matcher.gate.reviewed_aliases is matcher._reviewed_aliases
