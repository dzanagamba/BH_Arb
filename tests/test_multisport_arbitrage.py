"""Pricing for the non-football market families, and settlement safety."""

from __future__ import annotations

from datetime import UTC, datetime

from engine.arbitrage import ArbitrageEngine
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

KICKOFF = datetime(2030, 1, 1, 18, 0, tzinfo=UTC)


def _match(book: str, sport: str, markets: list[Market]) -> Match:
    return Match(
        bookmaker=book,
        sport=sport,
        home_team="Home",
        away_team="Away",
        league="League",
        kickoff=KICKOFF,
        deep_link_verified=True,
        markets=markets,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _group(sport: str, matches: list[Match]) -> MatchGroup:
    return MatchGroup(
        canonical_home="Home",
        canonical_away="Away",
        sport=sport,
        league="League",
        kickoff=KICKOFF,
        matches=matches,
        status="verified",
    )


def _market(market_type: MarketType, labels: list[tuple[str, float]], settlement: str) -> Market:
    return Market(
        market_type=market_type,
        odds=[OddsValue(label=label, value=value) for label, value in labels],
        settlement=settlement,
    )


def test_basketball_moneyline_prices_a_two_way_surebet():
    group = _group("basketball", [
        _match("sportplus", "basketball", [
            _market(MarketType.MONEYLINE, [("1", 2.10), ("2", 1.80)], "full_time_incl_ot")
        ]),
        _match("maxbet", "basketball", [
            _market(MarketType.MONEYLINE, [("1", 1.85), ("2", 2.15)], "full_time_incl_ot")
        ]),
    ])
    [surebet] = ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"moneyline"}
    )
    assert surebet.sport == "basketball"
    assert surebet.market_type == MarketType.MONEYLINE
    assert {stake.outcome_label for stake in surebet.stakes} == {"1", "2"}
    assert len({stake.bookmaker for stake in surebet.stakes}) == 2


def test_tennis_total_pairs_the_same_line_across_books():
    group = _group("tennis", [
        _match("sportplus", "tennis", [
            _market(MarketType.TOTAL, [("Over 22.5", 2.10), ("Under 22.5", 1.80)], "full_match")
        ]),
        _match("mbet", "tennis", [
            _market(MarketType.TOTAL, [("Over 22.5", 1.85), ("Under 22.5", 2.15)], "full_match")
        ]),
    ])
    [surebet] = ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"total"}
    )
    assert {stake.outcome_label for stake in surebet.stakes} == {"Over 22.5", "Under 22.5"}


def test_handicap_pairs_complementary_signed_labels():
    group = _group("tennis", [
        _match("sportplus", "tennis", [
            _market(MarketType.HANDICAP, [("1 -2.5", 2.10), ("2 +2.5", 1.80)], "full_match")
        ]),
        _match("maxbet", "tennis", [
            _market(MarketType.HANDICAP, [("1 -2.5", 1.85), ("2 +2.5", 2.15)], "full_match")
        ]),
    ])
    [surebet] = ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"handicap"}
    )
    assert {stake.outcome_label for stake in surebet.stakes} == {"1 -2.5", "2 +2.5"}


def test_a_settlement_mismatch_is_never_paired():
    """Regular time and including-overtime are different bets at the same label."""
    group = _group("basketball", [
        _match("sportplus", "basketball", [
            _market(MarketType.MONEYLINE, [("1", 2.10), ("2", 1.80)], "full_time_incl_ot")
        ]),
        _match("maxbet", "basketball", [
            _market(MarketType.MONEYLINE, [("1", 1.85), ("2", 2.15)], "regulation")
        ]),
    ])
    assert ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"moneyline"}
    ) == []


def test_a_suggested_group_is_never_priced():
    group = _group("tennis", [
        _match("sportplus", "tennis", [
            _market(MarketType.MONEYLINE, [("1", 2.10), ("2", 1.80)], "full_match")
        ]),
        _match("mbet", "tennis", [
            _market(MarketType.MONEYLINE, [("1", 1.85), ("2", 2.15)], "full_match")
        ]),
    ])
    group.status = "suggested"
    assert ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"moneyline"}
    ) == []


def test_a_huge_two_source_edge_is_rejected_as_stale():
    group = _group("football", [
        _match("maxbet", "football", [
            _market(MarketType.BTTS, [("GG", 6.75), ("NG", 1.10)], "full_time")
        ]),
        _match("betole", "football", [
            _market(MarketType.BTTS, [("GG", 1.60), ("NG", 2.40)], "full_time")
        ]),
    ])
    assert ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"btts"}
    ) == []

    group = _group("football", [
        _match("maxbet", "football", [
            _market(MarketType.OVER_UNDER_4_5, [("Over 4.5", 2.10), ("Under 4.5", 1.80)], "full_time")
        ]),
        _match("mbet", "football", [
            _market(MarketType.OVER_UNDER_4_5, [("Over 4.5", 1.85), ("Under 4.5", 2.15)], "full_time")
        ]),
    ])
    [surebet] = ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"over_under_4_5"}
    )
    assert surebet.market_type == MarketType.OVER_UNDER_4_5


def test_nonfootball_edge_counts_only_plausible_complete_sets():
    """A dropped stale set must not lend the edge a third price source."""
    group = _group("basketball", [
        _match("mdshop", "basketball", [
            _market(
                MarketType.HANDICAP,
                [("1 -3.5", 2.522), ("2 +3.5", 1.455)],
                "regulation",
            ),
            _market(
                MarketType.HANDICAP,
                [("1 +3.5", 1.7512), ("2 -3.5", 2.0696)],
                "regulation",
            ),
        ]),
        _match("sportplus", "basketball", [
            _market(
                MarketType.HANDICAP,
                [("1 -3.5", 1.75), ("2 +3.5", 2.05)],
                "regulation",
            ),
        ]),
        _match("mbet", "basketball", [
            # This book's own -3.5 / +3.5 set implies 0.879 (< 1.0) and is
            # dropped as stale; it cannot count as a supporting source.
            _market(
                MarketType.HANDICAP,
                [("1 -3.5", 2.60), ("2 +3.5", 2.02)],
                "regulation",
            ),
        ]),
    ])
    assert ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"handicap"}
    ) == []



def test_a_book_with_one_outlier_side_cannot_support_an_edge():
    """A skewed two-way line must not create a surebet from its better side."""
    group = _group("basketball", [
        _match("mdshop", "basketball", [
            _market(
                MarketType.HANDICAP,
                [("1 -2.5", 2.522), ("2 +2.5", 1.54)],
                "regulation",
            ),
        ]),
        _match("sportplus", "basketball", [
            _market(
                MarketType.HANDICAP,
                [("1 -2.5", 1.85), ("2 +2.5", 1.80)],
                "regulation",
            ),
        ]),
        _match("mbet", "basketball", [
            # Its own set is already an arbitrage (0.938) and is dropped too.
            _market(
                MarketType.HANDICAP,
                [("1 -2.5", 2.40), ("2 +2.5", 1.92)],
                "regulation",
            ),
        ]),
    ])
    assert ArbitrageEngine().find_surebets(
        [group], min_profit=0.0, enabled_markets={"handicap"}
    ) == []
