"""End-to-end pipeline test: scraped-style fixtures → normalize → match → arbitrage."""

from datetime import UTC, datetime, timedelta

from engine.arbitrage import ArbitrageEngine
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue


def _match(bookmaker, home, away, league, kickoff, odds, country=""):
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=league,
        country=country,
        kickoff=kickoff,
        event_id=f"{bookmaker}-{home}-{away}",
        deep_link_verified=True,
        url=f"https://example.test/{bookmaker}",
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=odds[0]),
            OddsValue(label="X", value=odds[1]),
            OddsValue(label="2", value=odds[2]),
        ])],
        match_code=f"{bookmaker}-{home}-{away}",
    )


def _future_kickoff():
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)


def test_full_pipeline_finds_surebet():
    kickoff = _future_kickoff()
    fixtures = [
        # Same real-world match listed by 3 bookmakers with name variations
        _match("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", kickoff, (3.50, 4.00, 2.15)),
        _match("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", kickoff, (3.40, 4.20, 1.95)),
        _match("sportplus", "Zeljeznicar", "Sarajevo", "Premijer Liga BiH", kickoff, (3.60, 3.90, 2.10)),
        # Unrelated match (different teams + league) — must stay in its own group
        _match("mdshop", "Borac BL", "Sloboda", "Prva Liga RS", kickoff, (2.10, 3.10, 3.40)),
        _match("mbet", "Borac Banja Luka", "Sloboda Tuzla", "Prva Liga RS", kickoff, (2.05, 3.15, 3.50)),
        # Same teams but 3h later — kickoff gate must keep it out of the main group
        _match("evlbet", "Željezničar", "Sarajevo", "BiH - Premier Liga", kickoff + timedelta(hours=3),
               (3.55, 4.10, 2.05)),
    ]

    groups = MatchMatcher().group_matches(fixtures)
    surebets = ArbitrageEngine().find_surebets(groups, min_profit=0.5, investment=100.0)

    # The main 3-bookmaker group exists with all three bookmakers
    main = next(g for g in groups if "zeljeznicar" in g.canonical_home)
    assert len(main.matches) == 3
    assert {m.bookmaker for m in main.matches} == {"mdshop", "mbet", "sportplus"}

    # The unrelated Borac group is separate
    borac = next(g for g in groups if "borac" in g.canonical_home)
    assert len(borac.matches) == 2

    # The late-kickoff EVLBet match must NOT join the main group
    assert all(m.bookmaker != "evlbet" for m in main.matches)

    # 1X2 surebet detected with the expected profit (>1% margin)
    ones = [s for s in surebets if s.market_type == MarketType.MATCH_RESULT]
    assert len(ones) >= 1
    assert ones[0].profit_percent > 1.0
    assert len(ones[0].stakes) == 3
    assert len({s.bookmaker for s in ones[0].stakes}) == 3
