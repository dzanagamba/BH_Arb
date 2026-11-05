"""N3-1: property-based checks for identity and admissibility.

The fixed fixtures in ``test_certainty.py`` and ``test_identity_edge_cases.py``
cover the known cases. These generators vary the inputs around the same rules
to prove none of them is a special case:

* sport is the outermost hard gate, for every pair of sports;
* a matcher run never returns a group holding two sports or one book twice;
* a settlement difference is never priced as if it were the same bet;
* a name marker (youth/reserve/women/colour) is a veto, not a fuzzy penalty;
* a kickoff at the window boundary is decided deterministically;
* a fuzzy score alone never produces ``verified``.

None of these tests writes a mapping, an allowlist or a ledger claim. They read
the same deterministic gate the scanner uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine import name_identity
from engine.arbitrage import ArbitrageEngine, _dominant_settlement
from engine.certainty import CertaintyGate
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

SPORTS = ["football", "basketball", "tennis", "ice_hockey"]
MARKERS = [
    "academy",
    "junior",
    "youth",
    "women",
    "reserve",
    "ii",
    "u21",
    "gc",
]
COLOURS = ["blue", "white", "red", "black", "green", "yellow", "orange"]
BASE_NAMES = ["Sarajevo", "Zeljeznicar", "Arsenal", "Chelsea", "Barcelona"]


def _match(
    bookmaker: str,
    *,
    sport: str = "football",
    home: str = "Sarajevo",
    away: str = "Zeljeznicar",
    league: str = "Premier Liga",
    kickoff: datetime = datetime(2030, 1, 1, 18, 0),
) -> Match:
    """A listing whose link is settled and whose raw names are lossless."""
    return Match(
        bookmaker=bookmaker,
        sport=sport,
        home_team=home,
        away_team=away,
        home_team_normalized=home.casefold(),
        away_team_normalized=away.casefold(),
        league=league,
        league_normalized=league.casefold().replace(" ", "_"),
        kickoff=kickoff,
        deep_link_verified=True,
        markets=[],
    )


@given(
    left=st.sampled_from(SPORTS),
    right=st.sampled_from(SPORTS),
)
@settings(max_examples=30, deadline=None)
def test_a_different_sport_can_never_verify(left: str, right: str) -> None:
    if left == right:
        return
    result = CertaintyGate().evaluate_pair(
        _match("mbet", sport=left), _match("wwin", sport=right)
    )

    assert result.status == "rejected"
    assert result.reasons == ["sport_mismatch"]


@given(
    high=st.floats(
        min_value=2.02, max_value=2.15, allow_nan=False, allow_infinity=False
    ),
    low=st.floats(
        min_value=1.50, max_value=1.90, allow_nan=False, allow_infinity=False
    ),
    odd_settlement=st.sampled_from(
        ["regulation", "full_time", "full_time_incl_ot"]
    ),
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_surebet_never_pairs_two_settlements(
    high: float, low: float, odd_settlement: str
) -> None:
    kickoff = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
    rows = [
        ("mbet", high, low, "regulation"),
        ("wwin", low, high, "regulation"),
        ("mozzartbet", high, low, odd_settlement),
    ]
    matches = [
        Match(
            bookmaker=bookmaker,
            home_team="Sarajevo",
            away_team="Zeljeznicar",
            league="Premier Liga",
            kickoff=kickoff,
            markets=[
                Market(
                    market_type=MarketType.BTTS,
                    settlement=settlement,
                    odds=[
                        OddsValue(label="GG", value=gg),
                        OddsValue(label="NG", value=ng),
                    ],
                )
            ],
        )
        for bookmaker, gg, ng, settlement in rows
    ]
    group = MatchGroup(
        status="verified",
        canonical_home="Sarajevo",
        canonical_away="Zeljeznicar",
        league="premier_liga",
        kickoff=kickoff,
        matches=matches,
    )

    dominant = _dominant_settlement(
        [(match.bookmaker, market) for match in matches for market in match.markets]
    )
    by_book = {match.bookmaker: match.markets[0].settlement for match in matches}
    surebets = ArbitrageEngine().find_surebets([group], min_profit=0.1, investment=100.0)

    assert surebets
    for surebet in surebets:
        assert len({stake.bookmaker for stake in surebet.stakes}) == len(surebet.stakes)
        assert all(by_book[stake.bookmaker] == dominant for stake in surebet.stakes)


@given(
    base=st.datetimes(
        min_value=datetime(2030, 1, 1, 0, 0),
        max_value=datetime(2030, 1, 2, 23, 0),
    ).map(lambda value: value.replace(microsecond=0)),
    seconds=st.integers(min_value=-7200, max_value=7200),
)
@settings(max_examples=60, deadline=None)
def test_the_kickoff_boundary_is_decided_consistently(
    base: datetime, seconds: int
) -> None:
    result = CertaintyGate().evaluate_pair(
        _match("mbet", kickoff=base),
        _match("wwin", kickoff=base + timedelta(seconds=seconds)),
    )

    inside = abs(seconds) <= 15 * 60
    assert result.status == ("verified" if inside else "suggested")
    assert ("kickoff_delta" in result.reasons) is (not inside)
    assert "kickoff_missing" not in result.reasons


@given(marker=st.sampled_from(MARKERS), base=st.sampled_from(BASE_NAMES))
@settings(max_examples=40, deadline=None)
def test_a_name_marker_difference_is_a_veto_not_a_penalty(
    marker: str, base: str
) -> None:
    assert name_identity.similarity(f"{base} {marker}", base) == 0.0
    assert name_identity.similarity(base, f"{base} {marker}") == 0.0


@given(colour=st.sampled_from(COLOURS), base=st.sampled_from(BASE_NAMES))
@settings(max_examples=50, deadline=None)
def test_a_one_sided_colour_is_a_veto(colour: str, base: str) -> None:
    assert name_identity.similarity(f"{base} {colour}", base) == 0.0


@given(
    words=st.lists(
        st.sampled_from(
            ["real", "madrid", "manchester", "united", "city", "bayern", "munich"]
        ),
        min_size=1,
        max_size=3,
    )
)
@settings(max_examples=80, deadline=None)
def test_name_similarity_is_symmetric_and_bounded(words: list[str]) -> None:
    left = " ".join(words)
    right = " ".join(reversed(words))

    forward = name_identity.similarity(left, right)
    backward = name_identity.similarity(right, left)

    assert 0.0 <= forward <= 1.0
    assert forward == pytest.approx(backward, abs=1e-12)


def test_a_multi_sport_scan_never_groups_two_sports() -> None:
    matches = [
        _match(bookmaker, sport=sport)
        for sport in SPORTS
        for bookmaker in ("mbet", "wwin")
    ]

    groups = MatchMatcher().group_matches(matches)

    assert groups
    for group in groups:
        assert len({match.sport for match in group.matches}) == 1
        assert len({match.bookmaker for match in group.matches}) == len(group.matches)
    assert {group.sport for group in groups} == set(SPORTS)


@given(
    left=st.sampled_from(
        [
            "Arsenal",
            "Chelsea",
            "Sarajevo",
            "Zeljeznicar",
            "Real Madrid",
            "Barcelona",
            "Bayern Munich",
            "Borussia Dortmund",
        ]
    ),
    right=st.sampled_from(
        [
            "Arsenal",
            "Chelsea",
            "Sarajevo",
            "Zeljeznicar",
            "Real Madrid",
            "Barcelona",
            "Bayern Munich",
            "Borussia Dortmund",
        ]
    ),
)
@settings(max_examples=40, deadline=None)
def test_a_fuzzy_score_alone_never_verifies_a_pair(left: str, right: str) -> None:
    if left == right:
        return
    result = CertaintyGate().evaluate_pair(
        _match("mbet", home=left), _match("wwin", home=right)
    )

    assert result.status != "verified"


def test_a_high_similarity_pair_is_still_not_an_identity_proof() -> None:
    """The fixed case behind the property: Manchester is not enough."""
    left = "Manchester United"
    right = "Manchester City"

    assert name_identity.similarity(left, right) > 0.5
    assert (
        CertaintyGate()
        .evaluate_pair(_match("mbet", home=left), _match("wwin", home=right))
        .status
        != "verified"
    )


def test_an_initialism_is_an_identity_rule_and_is_pinned() -> None:
    """The smallest positive case: an acronym of the full token list."""
    assert name_identity.similarity("MU", "Manchester United") == 1.0
    assert name_identity.similarity("Manchester United", "MU") == 1.0
