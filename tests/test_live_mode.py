"""Live mode tests: in-play feed parsing and past-kickoff arbitrage handling."""

from datetime import UTC, datetime, timedelta

from engine.arbitrage import ArbitrageEngine
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from scrapers.common import parse_nsoft_live_bets
from scrapers.mbet import _resolve_mbet_live_market
from scrapers.sportplus import SportPlusScraper


def _live_bet(btid, outcomes, sbv=None):
    bet = {"betTypeId": btid, "betOutcomes": [{"name": n, "odd": o} for n, o in outcomes]}
    if sbv is not None:
        bet["sbv"] = sbv
    return bet


# ─── NSoft live parsing ───────────────────────────────────────────────────────

def test_nsoft_live_1x2_with_score_specifier():
    bets = [_live_bet(6, [("1", 2.1), ("X", 3.2), ("2", 3.5)], sbv="0:0")]
    markets = parse_nsoft_live_bets(bets)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.MATCH_RESULT
    assert {o.label for o in markets[0].odds} == {"1", "X", "2"}


def test_nsoft_live_double_chance_ids():
    for btid in (18, 42):
        markets = parse_nsoft_live_bets([_live_bet(btid, [("1X", 1.4), ("12", 1.3), ("X2", 1.5)])])
        assert len(markets) == 1
        assert markets[0].market_type == MarketType.DOUBLE_CHANCE


def test_nsoft_live_btts():
    markets = parse_nsoft_live_bets([_live_bet(995, [("GG", 2.1), ("NG", 1.7)], sbv="1:0")])
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.BTTS


def test_nsoft_live_ou_lines():
    for btid, sbv, expected in (
        (22, "1.5", MarketType.OVER_UNDER_1_5),
        (28, "2.5", MarketType.OVER_UNDER_2_5),
        (22, "3.5", MarketType.OVER_UNDER_3_5),
    ):
        markets = parse_nsoft_live_bets([_live_bet(btid, [("Manje", 1.9), ("Vise", 1.9)], sbv=sbv)])
        assert len(markets) == 1, f"id={btid} sbv={sbv}"
        assert markets[0].market_type == expected


def test_nsoft_live_dead_ou_side_dropped():
    """Late-game totals have dead sides absent — the market must be dropped."""
    assert parse_nsoft_live_bets([_live_bet(22, [("Vise", 1.2)], sbv="2.5")]) == []


def test_nsoft_live_unmapped_ids_rejected():
    """Handicap, correct score, period and combo IDs never map to supported markets."""
    rejected = [
        _live_bet(1, [("1", 1.5), ("2", 2.4)], sbv="-0.5"),
        _live_bet(14, [("1", 2.0), ("X", 3.0), ("2", 3.5)], sbv="1:0"),
        _live_bet(17, [("1", 1.8), ("2", 2.0)], sbv="0.5"),
        _live_bet(24, [("0:0", 5.0), ("1:0", 6.0), ("ostali rezultati", 3.0)]),
        _live_bet(261, [("1-1", 5.0), ("X-X", 6.0), ("2-2", 7.0)]),
        _live_bet(56, [("1", 2.0), ("X", 3.0), ("2", 3.5)]),
        _live_bet(41, [("1", 1.5), ("2", 2.4)]),
        _live_bet(1064, [("1 & GG", 4.0), ("X & GG", 5.0), ("2 & NG", 3.0)]),
    ]
    for bets in rejected:
        assert parse_nsoft_live_bets([bets]) == []


def test_nsoft_live_prematch_ids_not_used():
    """Prematch IDs (135/152/151) must not leak into the live parser."""
    assert parse_nsoft_live_bets([_live_bet(135, [("1", 2.1), ("X", 3.2), ("2", 3.5)])]) == []
    assert parse_nsoft_live_bets([_live_bet(152, [("1X", 1.4), ("12", 1.3), ("X2", 1.5)])]) == []


# ─── MBet live parsing ────────────────────────────────────────────────────────

def test_mbet_live_markets():
    odds = {
        "lfb:ft:1": 2.1, "lfb:ft:X": 3.2, "lfb:ft:2": 3.5,
        "lfb:dc:1X": 1.4, "lfb:dc:12": 1.3, "lfb:dc:X2": 1.5,
        "lfb:bttsny:Yes": 2.0, "lfb:bttsny:No": 1.8,
        "lfb:tg:over|1.5": 1.6, "lfb:tg:under|1.5": 2.2,
        "lfb:tg:over|2.5": 1.9, "lfb:tg:under|2.5": 1.9,
        "lfb:tg:over|3.5": 2.5, "lfb:tg:under|3.5": 1.5,
        "lfb:tg1sth:over|1.5": 2.0, "lfb:tg1sth:under|1.5": 1.7,
    }
    markets = _resolve_mbet_live_market(odds)
    assert "1X2" in markets and "DC" in markets and "BTTS" in markets
    assert {o.label for o in markets["BTTS"]} == {"GG", "NG"}
    assert "over_under_1_5" in markets
    assert "over_under_2_5" in markets
    assert "over_under_3_5" in markets
    assert "over_under_1_5" not in {k for k in markets if "tg1sth" in k}


def test_mbet_live_ignores_closed_markets():
    odds = {
        "lfb:ft:1": {"value": 41.0, "market_status": "CLOSED", "oddtype_status": -1},
        "lfb:ft:X": {"value": 31.0, "market_status": "CLOSED", "oddtype_status": -1},
        "lfb:ft:2": {"value": 1.02, "market_status": "CLOSED", "oddtype_status": -1},
    }
    assert _resolve_mbet_live_market(odds) == {}


# ─── SportPlus live parsing ───────────────────────────────────────────────────

def test_sportplus_live_markets():
    scraper = SportPlusScraper()
    markets = scraper._parse_live_markets([
        {"id": 1, "name": "Pobjednik", "odds": [
            {"alias": "1", "value": 4.4}, {"alias": "X", "value": 3.3}, {"alias": "2", "value": 1.8},
        ]},
        {"id": 9, "name": "Dvostruka Prilika (1X - 12 - X2)", "odds": [
            {"alias": "1X", "value": 1.9}, {"alias": "X2", "value": 1.16}, {"alias": "12", "value": 1.27},
        ]},
        {"id": 2, "name": "Zbroj golova 2.5", "odds": [
            {"alias": "1(M)", "value": 1.6}, {"alias": "2(V)", "value": 2.2},
        ]},
        {"id": 2, "name": "Zbroj golova 3.5", "odds": [
            {"alias": "1(M)", "value": 1.2}, {"alias": "2(V)", "value": 4.0},
        ]},
        {"id": 6, "name": "Oba daju gol", "odds": [
            {"alias": "1(D)", "value": 2.05}, {"alias": "2(N)", "value": 1.7},
        ]},
    ])
    by_type = {m.market_type: m for m in markets}
    assert MarketType.MATCH_RESULT in by_type
    assert MarketType.DOUBLE_CHANCE in by_type
    assert MarketType.OVER_UNDER_2_5 in by_type
    assert MarketType.OVER_UNDER_3_5 in by_type
    assert MarketType.BTTS in by_type
    assert {o.label for o in by_type[MarketType.BTTS].odds} == {"GG", "NG"}
    assert {o.label for o in by_type[MarketType.OVER_UNDER_2_5].odds} == {"Over 2.5", "Under 2.5"}


def test_sportplus_live_skips_suspended_and_other_markets():
    scraper = SportPlusScraper()
    markets = scraper._parse_live_markets([
        {"id": 1, "name": "Pobjednik", "odds": [
            {"alias": "1", "value": 0.0}, {"alias": "X", "value": 7.5}, {"alias": "2", "value": 20.0},
        ]},
        {"id": 3, "name": "Hendikep 0:4", "odds": [
            {"alias": "1", "value": 20.0}, {"alias": "X", "value": 9.5}, {"alias": "2", "value": 0.0},
        ]},
        {"id": 5, "name": "Azijski hendikep", "odds": [
            {"alias": "1", "value": 5.9}, {"alias": "2", "value": 1.07},
        ]},
        {"id": 8, "name": "Sljedeći gol 4", "odds": [
            {"alias": "1", "value": 6.75}, {"alias": "X", "value": 1.18}, {"alias": "2", "value": 8.75},
        ]},
        {"id": 20, "name": "Par/Nepar golovi", "odds": [
            {"alias": "1(P)", "value": 4.25}, {"alias": "2(N)", "value": 1.16},
        ]},
    ])
    assert markets == []


# ─── Arbitrage: past-kickoff handling ─────────────────────────────────────────

def _past_kickoff() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=45)


def _group_with_past_kickoff():
    kickoff = _past_kickoff()
    m1 = Match(
        bookmaker="mdshop", home_team="Sarajevo", away_team="Zeljeznicar",
        league="Premijer Liga", kickoff=kickoff,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.40), OddsValue(label="X", value=3.20), OddsValue(label="2", value=3.10),
        ])],
        is_live=True,
    )
    m2 = Match(
        bookmaker="mbet", home_team="Sarajevo", away_team="Zeljeznicar",
        league="Premijer Liga", kickoff=kickoff,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.80), OddsValue(label="X", value=3.60), OddsValue(label="2", value=3.40),
        ])],
        is_live=True,
    )
    m3 = Match(
        bookmaker="sportplus", home_team="Sarajevo", away_team="Zeljeznicar",
        league="Premijer Liga", kickoff=kickoff,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.20), OddsValue(label="X", value=3.40), OddsValue(label="2", value=2.90),
        ])],
        is_live=True,
    )
    group = MatchGroup(canonical_home="Sarajevo", canonical_away="Zeljeznicar",
                       league="Premijer Liga", kickoff=kickoff, matches=[m1, m2, m3])
    return group


def test_live_mode_keeps_past_kickoff_groups():
    group = _group_with_past_kickoff()
    engine = ArbitrageEngine()
    assert engine.find_surebets([group], min_profit=0.0, allow_past_kickoffs=True) != []


def test_prematch_mode_drops_past_kickoff_groups():
    group = _group_with_past_kickoff()
    engine = ArbitrageEngine()
    assert engine.find_surebets([group], min_profit=0.0, allow_past_kickoffs=False) == []
