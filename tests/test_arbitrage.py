"""Tests for arbitrage detection math and the one-bet-per-bookmaker rule."""

from datetime import UTC, datetime, timedelta

from engine.arbitrage import ArbitrageEngine
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue


def _future_kickoff():
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)

def _group(bookie_odds, kickoff=None):
    """Build a MatchGroup where each bookmaker provides a BTTS (GG/NG) market."""
    kickoff = kickoff or _future_kickoff()
    matches = []
    for bookie, (gg, ng) in bookie_odds.items():
        matches.append(Match(
            bookmaker=bookie,
            home_team="Sarajevo",
            away_team="Željezničar",
            league="BiH - Premier Liga",
            kickoff=kickoff,
            markets=[Market(
                market_type=MarketType.BTTS,
                odds=[OddsValue(label="GG", value=gg), OddsValue(label="NG", value=ng)],
            )],
        ))
    return MatchGroup(
        status="verified",
        canonical_home="Sarajevo",
        canonical_away="Zeljeznicar",
        league="premier_liga_bih",
        kickoff=kickoff,
        matches=matches,
    )


def test_surebet_detected():
    group = _group({"mdshop": (2.40, 1.90), "mbet": (2.20, 1.85)})
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    assert len(surebets) == 1
    assert surebets[0].profit_percent > 0.5


def test_no_surebet_when_implied_ge_one():
    group = _group({"mdshop": (1.90, 1.90), "mbet": (1.85, 1.95)})
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    assert len(surebets) == 0


def test_min_profit_threshold():
    # Tiny margin (profit ~0.49%) — below the 0.5% floor
    group = _group({"mdshop": (2.03, 1.97), "mbet": (2.01, 1.99)})
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    assert len(surebets) == 0


def test_stake_calculation_equal_return():
    group = _group({"mdshop": (2.40, 1.90), "mbet": (2.20, 1.85)})
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    sb = surebets[0]
    returns = [s.potential_return for s in sb.stakes]
    assert max(returns) - min(returns) < 0.5  # equalized returns
    assert abs(sum(s.stake for s in sb.stakes) - 100.0) < 1.0


def test_one_bet_per_bookmaker_rule():
    # Best odds for BOTH outcomes sit at bookie A — same-bookie arb must be rejected
    group = _group({"mdshop": (2.50, 2.00), "mbet": (1.80, 1.60)})
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    assert len(surebets) == 0


def test_books_on_one_feed_are_one_price_source():
    # mdshop and admiralbet both run on NSoft: GG at one and NG at the other is
    # not two independent prices, however good it looks.
    group = _group({"mdshop": (2.40, 1.50), "admiralbet": (1.50, 2.40)})
    engine = ArbitrageEngine()
    assert engine.find_surebets([group], min_profit=0.5, investment=100.0) == []


def test_a_nsoft_book_still_pairs_with_an_independent_book():
    group = _group({"mdshop": (2.40, 1.50), "admiralbet": (2.40, 1.50), "mbet": (1.50, 2.40)})
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    assert len(surebets) == 1
    assert {s.bookmaker for s in surebets[0].stakes} in ({"mdshop", "mbet"}, {"admiralbet", "mbet"})


def test_expired_match_skipped():
    past = datetime(2020, 1, 1, 12, 0)
    group = _group({"mdshop": (2.40, 1.90), "mbet": (2.20, 1.85)}, kickoff=past)
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    assert len(surebets) == 0


def test_expiry_uses_utc_not_local_time():
    # Naive-UTC kickoff 90 minutes from now must NOT be expired on any machine,
    # even one whose local clock is ahead of UTC (old code expired it ~2h early).
    kickoff = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=90)
    assert ArbitrageEngine._is_expired(kickoff) is False
    # But a kickoff 2h in the past must be expired
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    assert ArbitrageEngine._is_expired(past) is True


def _dc_group():
    """1X2 from bookie A, Double Chance from bookie B — same real-world match."""
    kickoff = _future_kickoff()
    m_a = Match(
        bookmaker="mdshop", home_team="Sarajevo", away_team="Željezničar",
        league="BiH - Premier Liga", kickoff=kickoff,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.90),
            OddsValue(label="X", value=3.10),
            OddsValue(label="2", value=2.60),
        ])],
    )
    m_b = Match(
        bookmaker="mbet", home_team="Sarajevo", away_team="Zeljeznicar",
        league="Premijer Liga BiH", kickoff=kickoff,
        markets=[Market(market_type=MarketType.DOUBLE_CHANCE, odds=[
            OddsValue(label="1X", value=1.40),
            OddsValue(label="12", value=1.35),
            OddsValue(label="X2", value=1.60),
        ])],
    )
    return MatchGroup(
        status="verified",
        canonical_home="Sarajevo", canonical_away="Zeljeznicar",
        league="premier_liga_bih", kickoff=kickoff, matches=[m_a, m_b],
    )


def test_cross_market_dc_surebet():
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([_dc_group()], min_profit=0.5, investment=100.0)
    dc = [s for s in surebets if s.market_type == MarketType.DOUBLE_CHANCE]
    assert len(dc) == 1
    assert {s.outcome_label for s in dc[0].stakes} == {"1", "X2"}
    # Distinct bookmakers — never both legs with the same bookmaker
    assert len({s.bookmaker for s in dc[0].stakes}) == 2
    assert dc[0].profit_percent > 0.5


def test_cross_market_dc_rejects_same_bookmaker_both_legs():
    kickoff = _future_kickoff()
    # Bookie A holds the BEST odds for BOTH "1" and "X2" — same-bookie combo must be rejected
    m_a = Match(
        bookmaker="mdshop", home_team="Sarajevo", away_team="Željezničar",
        league="BiH - Premier Liga", kickoff=kickoff,
        markets=[
            Market(market_type=MarketType.MATCH_RESULT, odds=[
                OddsValue(label="1", value=2.90),
                OddsValue(label="X", value=3.10),
                OddsValue(label="2", value=2.60),
            ]),
            Market(market_type=MarketType.DOUBLE_CHANCE, odds=[
                OddsValue(label="1X", value=1.40),
                OddsValue(label="12", value=1.35),
                OddsValue(label="X2", value=1.60),
            ]),
        ],
    )
    m_b = Match(
        bookmaker="mbet", home_team="Sarajevo", away_team="Zeljeznicar",
        league="Premijer Liga BiH", kickoff=kickoff,
        markets=[
            Market(market_type=MarketType.MATCH_RESULT, odds=[
                OddsValue(label="1", value=2.20),
                OddsValue(label="X", value=3.00),
                OddsValue(label="2", value=2.80),
            ]),
            Market(market_type=MarketType.DOUBLE_CHANCE, odds=[
                OddsValue(label="1X", value=1.45),
                OddsValue(label="12", value=1.30),
                OddsValue(label="X2", value=1.55),
            ]),
        ],
    )
    group = MatchGroup(
        status="verified",
        canonical_home="Sarajevo", canonical_away="Zeljeznicar",
        league="premier_liga_bih", kickoff=kickoff, matches=[m_a, m_b],
    )
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0)
    dc = [s for s in surebets if s.market_type == MarketType.DOUBLE_CHANCE]
    assert dc, "expected a cross-market surebet via distinct bookmakers"
    assert len({s.bookmaker for s in dc[0].stakes}) == 2
    # The optimal-but-forbidden A+A combo (margin 0.9698) must not be used
    assert dc[0].total_margin >= 0.99


def test_an_unverified_group_is_never_priced():
    """The engine enforces the gate itself: only `verified` groups are priced."""
    group = _group({"mdshop": (2.40, 1.90), "mbet": (2.20, 1.85)})
    engine = ArbitrageEngine()
    assert engine.find_surebets([group], min_profit=0.0)
    assert engine.evaluate_market(group, MarketType.BTTS) is not None
    for status in ("suggested", "rejected"):
        unproven = group.model_copy(update={"status": status})
        assert engine.find_surebets([unproven], min_profit=0.0) == []
        assert engine.evaluate_market(unproven, MarketType.BTTS) is None


def _ou(over, under):
    return Market(
        market_type=MarketType.OVER_UNDER_2_5,
        odds=[OddsValue(label="Over 2.5", value=over), OddsValue(label="Under 2.5", value=under)],
    )


def test_a_market_type_quoted_twice_in_one_listing_is_not_priced():
    """The 2026-10-19 live fake: NSoft sent the match total and the home team's
    total both as O/U 2.5, and the better of the two made a 13.2% "surebet"."""
    group = _group({"mdshop": (2.0, 1.8), "mbet": (1.9, 1.9)})
    mdshop, mbet = group.matches
    mdshop.markets = [_ou(3.05, 1.34), _ou(1.83, 1.91)]
    mbet.markets = [_ou(1.88, 1.80)]
    engine = ArbitrageEngine()

    assert engine.find_surebets([group], min_profit=0.0, investment=100.0) == []
    assert engine.evaluate_market(group, MarketType.OVER_UNDER_2_5) is None
    assert engine.evaluate_market(
        group, MarketType.OVER_UNDER_2_5, labels=["Over 2.5", "Under 2.5"]
    ) is None


def test_the_duplicate_guard_leaves_other_market_types_priced():
    group = _group({"mdshop": (2.40, 1.90), "mbet": (2.20, 1.85)})
    mdshop = group.matches[0]
    mdshop.markets = [*mdshop.markets, _ou(3.05, 1.34), _ou(1.83, 1.91)]
    surebets = ArbitrageEngine().find_surebets([group], min_profit=0.5, investment=100.0)
    assert [s.market_type for s in surebets] == [MarketType.BTTS]
