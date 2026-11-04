"""P2-8: identical names are not an identity proof for a second fixture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.certainty import CertaintyGate
from engine.matcher import MatchMatcher
from models.schemas import Match


def _kickoff(minutes: int = 120) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=minutes)


def _match(book: str, *, kickoff=None, **updates) -> Match:
    match = Match(
        bookmaker=book,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        home_team_normalized="sarajevo",
        away_team_normalized="zeljeznicar",
        league="Premier Liga",
        league_normalized="premier_liga",
        kickoff=kickoff or _kickoff(),
        deep_link_verified=True,
        markets=[],
    )
    return match.model_copy(update=updates) if updates else match


def test_a_feed_declared_leg_mismatch_is_a_hard_reject():
    left = _match("mbet", leg="1")
    right = _match("wwin", leg="2")

    result = CertaintyGate().evaluate_pair(left, right)

    assert result.status == "rejected"
    assert "leg_mismatch" in result.reasons


def test_the_same_declared_leg_can_still_group():
    left = _match("mbet", leg="1")
    right = _match("wwin", leg="1")

    assert CertaintyGate().evaluate_pair(left, right).status == "verified"


def test_different_provider_ids_reject_a_doubleheader_without_a_leg():
    left = _match("mbet", betradar_id="9001")
    right = _match("wwin", betradar_id="9002")

    result = CertaintyGate().evaluate_pair(left, right)

    assert result.status == "rejected"
    assert "betradar_mismatch" in result.reasons


def test_a_shared_provider_id_and_leg_still_verifies():
    left = _match("mbet", betradar_id="9001", leg="1")
    right = _match("wwin", betradar_id="9001", leg="1")

    assert CertaintyGate().evaluate_pair(left, right).status == "verified"


def test_a_rematch_hours_later_is_not_the_same_event():
    left = _match("mbet", kickoff=_kickoff(120))
    right = _match("wwin", kickoff=_kickoff(240))

    result = CertaintyGate().evaluate_pair(left, right)

    assert result.status != "verified"
    assert "kickoff_delta" in result.reasons


def test_a_kickoff_across_midnight_inside_the_window_still_verifies():
    day = datetime(2030, 1, 1, 23, 55)
    left = _match("mbet", kickoff=day)
    right = _match("wwin", kickoff=datetime(2030, 1, 2, 0, 5))

    assert CertaintyGate().evaluate_pair(left, right).status == "verified"


def test_different_competitions_with_the_same_names_are_rejected():
    left = _match("mbet", league="Premier Liga", league_normalized="premier_liga_bih")
    right = _match("wwin", league="Regional Cup", league_normalized="premier_league")

    result = CertaintyGate().evaluate_pair(left, right)

    assert result.status == "rejected"
    assert "league_mismatch" in result.reasons


def test_the_matcher_does_not_verify_a_group_with_two_different_legs():
    groups = MatchMatcher().group_matches(
        [_match("mbet", leg="1"), _match("wwin", leg="2")]
    )

    assert all(group.status != "verified" for group in groups)
