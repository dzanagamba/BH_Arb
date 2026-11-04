"""The 0.5 / 4.5 / 5.5 football totals parse and price end to end."""

from __future__ import annotations

from datetime import datetime

from engine.arbitrage import ArbitrageEngine
from engine.market_registry import MarketRegistry
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from scrapers.common import parse_nsoft_bets
from scrapers.wwin import _build_markets_from_bets

NEW_LINES = (
    MarketType.OVER_UNDER_0_5,
    MarketType.OVER_UNDER_4_5,
    MarketType.OVER_UNDER_5_5,
)
LINE = {
    MarketType.OVER_UNDER_0_5: 0.5,
    MarketType.OVER_UNDER_4_5: 4.5,
    MarketType.OVER_UNDER_5_5: 5.5,
}


def _nsoft_ou(line: float, over: float = 2.0, under: float = 2.0) -> list[Market]:
    return parse_nsoft_bets([{
        "betTypeId": 137,
        "sBV": line,
        "betOutcomes": [
            {"name": "Vise", "odd": over},
            {"name": "Manje", "odd": under},
        ],
    }])


def test_nsoft_parses_every_admitted_football_line():
    registry = MarketRegistry()
    for market_type in NEW_LINES:
        line = LINE[market_type]
        markets = _nsoft_ou(line)
        assert len(markets) == 1, line
        assert markets[0].market_type is market_type
        assert {odd.label for odd in markets[0].odds} == {
            f"Over {line:g}", f"Under {line:g}"
        }
        spec = registry.lookup("mdshop", "prematch", 137, line=line)
        assert spec is not None
        assert spec.market_type is market_type


def test_nsoft_still_rejects_a_line_the_registry_does_not_price():
    assert _nsoft_ou(6.5) == []


def test_wwin_parses_the_three_extra_lines_and_rejects_quarter_lines():
    bets = [
        {"idBt": 11, "spec": "total=0,5", "odds": [
            {"t": "Over", "va": 1.10, "isv": 1},
            {"t": "Under", "va": 7.0, "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=4,5", "odds": [
            {"t": "Over", "va": 2.1, "isv": 1},
            {"t": "Under", "va": 1.6, "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=5,5", "odds": [
            {"t": "Over", "va": 3.2, "isv": 1},
            {"t": "Under", "va": 1.25, "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=4,25", "odds": [
            {"t": "Over", "va": 1.9, "isv": 1},
            {"t": "Under", "va": 1.9, "isv": 1},
        ]},
    ]
    markets = _build_markets_from_bets(bets)
    assert {market.market_type for market in markets} == set(NEW_LINES)
    by_type = {market.market_type: market for market in markets}
    assert {odd.label for odd in by_type[MarketType.OVER_UNDER_0_5].odds} == {
        "Over 0.5", "Under 0.5"
    }
    assert {odd.label for odd in by_type[MarketType.OVER_UNDER_4_5].odds} == {
        "Over 4.5", "Under 4.5"
    }
    assert {odd.label for odd in by_type[MarketType.OVER_UNDER_5_5].odds} == {
        "Over 5.5", "Under 5.5"
    }


def test_every_new_line_is_registered_where_the_feed_offers_it():
    registry = MarketRegistry()
    expected = {
        "mdshop": ("prematch", "live"),
        "admiralbet": ("prematch", "live"),
        "wwin": ("prematch", "live"),
        "maxbet": ("prematch", "live"),
        "premier_kladionica": ("prematch", "live"),
    }
    for book, modes in expected.items():
        for mode in modes:
            for market_type in NEW_LINES:
                assert registry.ids_for(book, mode, market_type), (book, mode, market_type)
    # MBet's goal-range feed has no 0.5 partition; the other two are measured.
    for market_type in (MarketType.OVER_UNDER_4_5, MarketType.OVER_UNDER_5_5):
        assert registry.ids_for("mbet", "prematch", market_type)


def _group(market_type: MarketType, left: tuple[float, float], right: tuple[float, float]) -> Match:
    line = LINE[market_type]
    return Match(
        bookmaker="",
        home_team="Home",
        away_team="Away",
        league="League",
        kickoff=datetime(2026, 11, 4, 18, 0),
        markets=[
            Market(
                market_type=market_type,
                odds=[
                    OddsValue(label=f"Over {line}", value=left[0]),
                    OddsValue(label=f"Under {line}", value=left[1]),
                ],
            )
        ],
    )


def test_each_new_line_prices_with_the_existing_two_way_math():
    for market_type in NEW_LINES:
        home = _group(market_type, (2.10, 1.90), (2.00, 1.95))
        away = _group(market_type, (2.00, 1.95), (2.10, 1.90))
        home.bookmaker = "mbet"
        away.bookmaker = "premier_kladionica"
        # Both complete sets have a negative margin, so best-of-book is a
        # surebet on every new line.
        group = MatchGroup(
            canonical_home="Home",
            canonical_away="Away",
            league="League",
            kickoff=home.kickoff,
            matches=[home, away],
            status="verified",
        )
        surebets = ArbitrageEngine().find_surebets(
            [group],
            min_profit=0.0,
            enabled_markets={market_type.value},
        )
        assert surebets, market_type
        assert surebets[0].market_type is market_type


def test_mozzart_goal_ranges_map_to_the_extra_lines():
    from scrapers.mozzartbet import _parse_markets

    def odd(subgame: str, value: float) -> dict:
        return {
            "value": value,
            "game": {"id": 3, "shortName": "ug", "name": "Ukupno golova"},
            "subgame": {"name": subgame},
        }

    markets = _parse_markets({
        "odds": [
            odd("5+", 2.10), odd("0-4", 1.70),
            odd("6+", 3.20), odd("0-5", 1.30),
            odd("7+", 9.0), odd("0-6", 1.04),
        ]
    })
    by_type = {market.market_type: market for market in markets}
    assert set(by_type) == {
        MarketType.OVER_UNDER_4_5, MarketType.OVER_UNDER_5_5
    }
    assert {o.label for o in by_type[MarketType.OVER_UNDER_4_5].odds} == {
        "Over 4.5", "Under 4.5"
    }
    assert {o.label for o in by_type[MarketType.OVER_UNDER_5_5].odds} == {
        "Over 5.5", "Under 5.5"
    }
