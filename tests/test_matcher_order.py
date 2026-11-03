"""Matcher grouping is a function of the input set, not of its order.

The first match in a group is its anchor, and the certainty gate judges every
later listing against that anchor. When the processing order was the input
order, the same cached scan yielded 16 / 34 / 106 verified groups depending only
on how the list happened to be arranged (docs/HANDOFF.md §4). These tests pin
the two halves of the fix: a total processing order, and a refusal of the best
candidate falling through to the next one instead of orphaning the listing.
"""

import random
from datetime import datetime, timedelta

import pytest

from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

K = datetime(2026, 9, 25, 18, 0)


def _m(
    bookmaker: str,
    home: str,
    away: str,
    league: str,
    kickoff: datetime = K,
    event_id: str = "",
    link_ok: bool = True,
) -> Match:
    event_id = event_id or f"{bookmaker}:{home}:{away}:{kickoff:%H%M}"
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        url=f"https://example.test/{bookmaker}/{event_id}",
        event_id=event_id,
        deep_link_verified=link_ok,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=2.0),
                    OddsValue(label="X", value=3.0),
                    OddsValue(label="2", value=4.0),
                ],
            )
        ],
    )


def _scan() -> list[Match]:
    """A small multi-book scan with the shapes a real one has.

    Alias spellings, a book publishing the fixture reversed, declared league
    equivalence, a generic league, a listing whose link is unproven (the
    order-sensitive case: whenever it anchored a group, every later listing of
    that fixture was orphaned), and same-name traps that must stay apart.
    """
    return [
        # Sarajevo vs Željezničar — an undeclared book with an unproven link.
        _m("undeclared_book", "Sarajevo", "Željezničar", "BiH - Premier Liga",
           event_id="un-1", link_ok=False),
        _m("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga", event_id="md-1"),
        _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", event_id="mb-1"),
        _m("sportplus", "Sarajevo", "Željezničar", "BiH - Premier Liga",
           kickoff=K + timedelta(minutes=5), event_id="sp-1"),
        # Traps for the same names: three hours later, and the U21 sides.
        _m("wwin", "Sarajevo", "Željezničar", "BiH - Premier Liga",
           kickoff=K + timedelta(hours=3), event_id="ww-late"),
        _m("admiralbet", "Sarajevo U21", "Željezničar U21", "BiH - Premier Liga",
           event_id="adm-u21"),
        # Europa / Conference: merged only through the declared equivalence.
        _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="md-2"),
        _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="mb-2"),
        _m("sportplus", "Midtjylland", "Rijeka", "Liga Evrope",
           kickoff=K + timedelta(minutes=10), event_id="sp-2"),
        # A generic league on both sides.
        _m("wwin", "Velez", "Borac", "Prijateljske utakmice",
           kickoff=K - timedelta(hours=4), event_id="ww-3"),
        _m("admiralbet", "Velez", "Borac", "Prijateljske utakmice",
           kickoff=K - timedelta(hours=4), event_id="adm-3"),
        # Unrelated fixtures the scorer must keep apart.
        _m("mdshop", "Alpha FC", "Beta United", "BiH - Premier Liga",
           kickoff=K + timedelta(hours=1), event_id="md-4"),
        _m("mbet", "Gamma SC", "Delta Club", "Premijer Liga BiH",
           kickoff=K + timedelta(hours=1), event_id="mb-4"),
    ]


Signature = frozenset[frozenset[tuple[str, str, str]]]


def _signature(matches: list[Match]) -> Signature:
    """Verified groups as (book, event, canonical home) per member.

    The canonical home is part of the claim: the same members anchored the
    other way round would price 1 and 2 against different teams.
    """
    groups = MatchMatcher().group_matches(matches)
    assert all(g.status == "verified" for g in groups)
    return frozenset(
        frozenset((m.bookmaker, m.event_id, m.home_team_normalized) for m in g.matches)
        for g in groups
    )


def _members(signature: Signature) -> frozenset[frozenset[str]]:
    return frozenset(frozenset(event_id for _, event_id, _ in g) for g in signature)


EXPECTED_MEMBERS = frozenset(
    {
        frozenset({"md-1", "mb-1", "sp-1"}),
        frozenset({"md-2", "mb-2", "sp-2"}),
        frozenset({"ww-3", "adm-3"}),
    }
)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 7, 42, 1234, 99991])
def test_shuffled_input_yields_the_same_verified_groups(seed: int) -> None:
    reference = _signature(_scan())
    assert _members(reference) == EXPECTED_MEMBERS
    # Every member of a group shares one canonical orientation.
    for group in reference:
        assert len({home for _, _, home in group}) == 1

    matches = _scan()
    random.Random(seed).shuffle(matches)
    assert _signature(matches) == reference


def test_input_order_and_its_reverse_agree() -> None:
    forward = _scan()
    backward = list(reversed(_scan()))
    assert _signature(forward) == _signature(backward)


def test_refused_best_group_falls_through_to_a_valid_second_best() -> None:
    """The gate refuses the highest-scoring group; the next one is verified.

    MBet opens a group 10 minutes before the others. MDShop's listing scores
    against it but its own link is unproven, so the gate refuses and MDShop
    opens a second group at the exact kickoff. SportPlus then scores the MDShop
    group highest (same minute) — and the gate refuses it, because its anchor's
    link is unproven. The MBet group scores lower (10 minutes apart) but is
    inside the 15-minute verified window with both links proven, so that is
    where SportPlus belongs. Before the fallback it was orphaned instead, and
    the scan lost the pairing.
    """
    mbet = _m("mbet", "Sarajevo", "Željezničar", "BiH - Premier Liga",
              kickoff=K - timedelta(minutes=10), event_id="mb")
    mdshop = _m("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga",
                event_id="md", link_ok=False)
    sportplus = _m("sportplus", "Sarajevo", "Željezničar", "BiH - Premier Liga",
                   event_id="sp")

    matcher = MatchMatcher()
    matcher.normalize_matches([mbet, mdshop, sportplus])
    mbet_group_conf, _ = matcher._calculate_confidence(
        sportplus, _group_of(mbet)
    )
    mdshop_group_conf, _ = matcher._calculate_confidence(
        sportplus, _group_of(mdshop)
    )
    assert mdshop_group_conf > mbet_group_conf, "the refused group must be the best-scoring"
    assert matcher.gate.evaluate(sportplus, _group_of(mdshop)).status != "verified"
    assert matcher.gate.evaluate(sportplus, _group_of(mbet)).status == "verified"

    groups = MatchMatcher().group_matches([mbet, mdshop, sportplus])
    assert len(groups) == 1
    assert {(m.bookmaker, m.event_id) for m in groups[0].matches} == {
        ("mbet", "mb"),
        ("sportplus", "sp"),
    }
    assert groups[0].status == "verified"


def test_fallback_never_admits_a_listing_the_gate_refuses_everywhere() -> None:
    """Trying more candidates does not loosen the gate: no verified group, no join."""
    mbet = _m("mbet", "Sarajevo", "Željezničar", "BiH - Premier Liga",
              kickoff=K - timedelta(minutes=10), event_id="mb")
    mdshop = _m("mdshop", "Sarajevo", "Željezničar", "BiH - Premier Liga",
                event_id="md", link_ok=False)
    # AdmiralBet declares a per-event route it has not proven here, so its own
    # link blocks against every candidate group.
    admiralbet = _m("admiralbet", "Sarajevo", "Željezničar", "BiH - Premier Liga",
                    event_id="adm", link_ok=False)
    assert MatchMatcher().group_matches([mbet, mdshop, admiralbet]) == []


def _group_of(match: Match) -> MatchGroup:
    return MatchGroup(
        canonical_home=match.home_team_normalized,
        canonical_away=match.away_team_normalized,
        league=match.league_normalized,
        kickoff=match.kickoff,
        matches=[match],
        status="suggested",
    )
