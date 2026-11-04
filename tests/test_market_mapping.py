"""Regression tests: bet types must map to the CORRECT markets.

These encode the structures verified against the live catalogs (2026-08):
- NSoft 136 = "Ide dalje" advance market (2-way, knockout games only) — must NEVER
  become 1X2/DC (this was the Admiralbet bug).
- NSoft 148/149 = half-time 1X2s; 140 = HT/FT; 153/154/166/174 = DNB/handicap/
  combos; 143/144/161/162 = half totals — all excluded.
- 1X2 markets are only accepted with ALL of 1/X/2 present.
"""

from models.schemas import MarketType
from scrapers.admiralbet import _parse_bets as admiralbet_parse_bets
from scrapers.betole import _parse_betole_markets
from scrapers.common import parse_nsoft_bets
from scrapers.evlbet import EvlbetScraper
from scrapers.mbet import MBetScraper, _resolve_mbet_market
from scrapers.mozzartbet import _parse_markets as mozzart_parse_markets
from scrapers.sportplus import SportPlusScraper


def _bet(btid, outcomes, sbv=None):
    bet = {"betTypeId": btid, "betOutcomes": [{"name": n, "odd": o} for n, o in outcomes]}
    if sbv is not None:
        bet["sBV"] = sbv
    return bet


def test_nsoft_136_advance_market_is_rejected():
    """'Ide dalje' (advance) — 2-way 1/2 — must produce NO markets."""
    bets = [_bet(136, [("1", 1.30), ("2", 3.40)])]
    assert parse_nsoft_bets(bets) == []
    assert admiralbet_parse_bets(bets) == []


def test_nsoft_incomplete_1x2_is_rejected():
    """A '1X2' with only 1/2 present (handicap-style) must be rejected."""
    bets = [_bet(135, [("1", 2.10), ("2", 1.80)])]
    assert parse_nsoft_bets(bets) == []


def test_nsoft_full_1x2_accepted():
    bets = [_bet(135, [("1", 2.10), ("X", 3.20), ("2", 3.50)])]
    markets = parse_nsoft_bets(bets)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.MATCH_RESULT
    assert {o.label for o in markets[0].odds} == {"1", "X", "2"}


def test_nsoft_half_time_1x2s_rejected():
    """148/149 (HT / 2nd half 1X2) are 3-way but NOT full-time result."""
    for btid in (148, 149):
        bets = [_bet(btid, [("1", 2.4), ("X", 2.0), ("2", 3.1)])]
        assert parse_nsoft_bets(bets) == [], f"betTypeId {btid} must be excluded"


def test_nsoft_all_1x2_shaped_non_result_types_rejected():
    """Every live 1/X/2-shaped NSoft side market stays out of full-time 1X2."""
    excluded = (136, 140, 148, 149, 153, 154, 166, 174)
    for btid in excluded:
        outcomes = [("1", 2.4), ("X", 2.0), ("2", 3.1)]
        if btid in (136, 153, 154, 174):
            outcomes = [("1", 2.4), ("2", 3.1)]
        if btid == 166:
            outcomes = [("1", 2.4), ("bez golova", 4.0), ("2", 3.1)]
        if btid == 140:
            outcomes = [("1-1", 5.0), ("X-X", 6.0), ("2-2", 7.0)]
        assert parse_nsoft_bets([_bet(btid, outcomes)]) == [], f"betTypeId {btid} must be excluded"


def test_nsoft_double_chance_accepted():
    bets = [_bet(152, [("1X", 1.40), ("12", 1.30), ("X2", 1.60)])]
    markets = parse_nsoft_bets(bets)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.DOUBLE_CHANCE


def test_nsoft_btts_accepted():
    bets = [_bet(151, [("GG", 2.10), ("NG", 1.70)])]
    markets = parse_nsoft_bets(bets)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.BTTS


def test_nsoft_ou_by_sbv():
    bets = [_bet(137, [("Manje", 1.90), ("Vise", 1.90)], sbv=2.5)]
    markets = parse_nsoft_bets(bets)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.OVER_UNDER_2_5
    assert {o.label for o in markets[0].odds} == {"Over 2.5", "Under 2.5"}


def test_nsoft_unsupported_ou_line_rejected():
    bets = [_bet(137, [("Manje", 1.90), ("Vise", 1.90)], sbv=6.5)]
    assert parse_nsoft_bets(bets) == []


def test_admiralbet_1639_is_1x2():
    bets = [_bet(1639, [("1", 2.1), ("X", 3.2), ("2", 3.5)])]
    markets = admiralbet_parse_bets(bets)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.MATCH_RESULT


def test_sportplus_advance_market_rejected():
    scraper = SportPlusScraper()
    markets = scraper._parse_markets([
        {"id": 1285, "name": "NAČIN PROLAZA", "odds": [
            {"alias": "1", "value": 1.5}, {"alias": "X", "value": 2.0}, {"alias": "2", "value": 2.5},
        ]},
    ])
    assert markets == []


def test_sportplus_incomplete_1x2_rejected():
    scraper = SportPlusScraper()
    markets = scraper._parse_markets([
        {"id": 1, "name": "NOGOMET", "odds": [
            {"alias": "1", "value": 2.1}, {"alias": "2", "value": 1.8},
        ]},
    ])
    assert markets == []


def test_sportplus_non_full_time_1x2_shaped_markets_rejected():
    scraper = SportPlusScraper()
    # 4 (PRVO POLUVRIJEME) and 25 (AZIJSKI HENDIKEP) are now supported
    # experimental markets — see tests/test_new_markets.py.
    for market_id, name in (
        (5, "TKO DA PRVI GOL"),
        (178, "POLUVRIJEME ILI KRAJ"),
        (308, "HENDIKEP"),
        (1285, "NAČIN PROLAZA"),
    ):
        assert scraper._parse_markets([{
            "id": market_id,
            "name": name,
            "odds": [
                {"alias": "1", "value": 2.0},
                {"alias": "X", "value": 3.0},
                {"alias": "2", "value": 4.0},
            ],
        }]) == [], f"SportPlus market {market_id} must be excluded"


def test_sportplus_goal_range_duplicate_is_one_canonical_market():
    scraper = SportPlusScraper()
    markets = scraper._parse_markets([
        {"id": 768, "name": "ZBROJ GOLOVA 2,5", "odds": [
            {"alias": "Manje", "value": 1.90}, {"alias": "Vise", "value": 1.80},
        ]},
        {"id": 800, "name": "RASPON GOLOVA", "odds": [
            {"alias": "01", "value": 3.30}, {"alias": "02", "value": 1.90},
            {"alias": "3+", "value": 1.80}, {"alias": "4+", "value": 3.20},
        ]},
        {"id": 802, "name": "RASPON GOLOVA", "odds": [
            {"alias": "2+", "value": 1.25}, {"alias": "03", "value": 1.30},
        ]},
    ])
    assert [m.market_type for m in markets] == [
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_3_5,
    ]
    assert len([m for m in markets if m.market_type == MarketType.OVER_UNDER_2_5]) == 1
    assert {o.label for o in markets[0].odds} == {"Over 2.5", "Under 2.5"}


def test_mozzart_advance_game_rejected():
    event = {"odds": [
        {"game": {"id": 99, "shortName": "kd", "name": "Ko ide dalje"},
         "subgame": {"name": "1"}, "value": 1.4},
        {"game": {"id": 99, "shortName": "kd", "name": "Ko ide dalje"},
         "subgame": {"name": "2"}, "value": 2.8},
    ]}
    assert mozzart_parse_markets(event) == []


def test_mozzart_full_1x2_accepted():
    event = {"odds": [
        {"game": {"id": 1, "shortName": "ki", "name": "Konačan ishod"},
         "subgame": {"name": "1"}, "value": 2.1},
        {"game": {"id": 1, "shortName": "ki", "name": "Konačan ishod"},
         "subgame": {"name": "X"}, "value": 3.2},
        {"game": {"id": 1, "shortName": "ki", "name": "Konačan ishod"},
         "subgame": {"name": "2"}, "value": 3.5},
    ]}
    markets = mozzart_parse_markets(event)
    assert len(markets) == 1
    assert markets[0].market_type == MarketType.MATCH_RESULT


def test_mozzart_live_supported_games_map_to_expected_markets():
    event = {"odds": [
        {"game": {"id": 1, "shortName": "ki", "name": "Konačan ishod"},
         "subgame": {"name": label}, "value": 2.0}
        for label in ("1", "X", "2")
    ] + [
        {"game": {"id": 2, "shortName": "ds", "name": "Dupla šansa"},
         "subgame": {"name": label}, "value": 1.4}
        for label in ("1X", "12", "X2")
    ] + [
        {"game": {"id": 3, "shortName": "ug", "name": "Ukupno golova"},
         "subgame": {"name": label}, "value": 1.9}
        for label in ("3+", "0-2")
    ] + [
        {"game": {"id": 130, "shortName": "tgg", "name": "Oba tima daju gol"},
         "subgame": {"name": label}, "value": 1.9}
        for label in ("gg", "ng")
    ]}
    assert {m.market_type for m in mozzart_parse_markets(event)} == {
        MarketType.MATCH_RESULT,
        MarketType.DOUBLE_CHANCE,
        MarketType.OVER_UNDER_2_5,
        MarketType.BTTS,
    }


def test_mbet_only_fs_is_full_time_result():
    odds = {
        "ofb:fs:1": 2.1, "ofb:fs:X": 3.2, "ofb:fs:2": 3.5,
        "ofb:fts:1": 2.0, "ofb:fts:X": 8.0, "ofb:fts:2": 2.2,
        "ofb:fi:1": 1.5, "ofb:fi:X": 3.0, "ofb:fi:2": 4.0,
        "ofb:ht:1": 2.2, "ofb:ht:X": 3.1, "ofb:ht:2": 3.4,
        "ofb:sh:1": 2.3, "ofb:sh:X": 3.0, "ofb:sh:2": 3.2,
        "ofb:dc:1X": 1.4, "ofb:dc:12": 1.3, "ofb:dc:X2": 1.5,
        "ofb:gg:GG": 2.1, "ofb:gg:NG": 1.7,
        "ofb:tg:2+": 1.9, "ofb:tg:0-1": 1.9,
        "ofb:tg:3+": 2.1, "ofb:tg:0-2": 1.7,
        "ofb:tg:4+": 2.5, "ofb:tg:0-3": 1.5,
    }
    assert "1X2" not in _resolve_mbet_market("fb", {
        key: value for key, value in odds.items() if ":fi:" in key
    })
    event = {
        "id_sport": "fb", "id": "event-1",
        "competitors": [{"name": "Home"}, {"name": "Away"}],
        "utc_scheduled": "2026-08-15T18:00:00Z", "odds": odds,
    }
    match = MBetScraper()._parse_event(event, set())
    assert match is not None
    assert {m.market_type for m in match.markets} == {
        MarketType.MATCH_RESULT,
        MarketType.DOUBLE_CHANCE,
        MarketType.BTTS,
        MarketType.FIRST_HALF_1X2,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
    }


def test_betole_pick_codes_map_only_verified_full_time_markets():
    odds = {
        "1": 2.1, "2": 3.2, "3": 3.5,
        "7": 1.4, "8": 1.3, "9": 1.5,
        "272": 2.0, "273": 1.8,
        "242": 1.6, "21": 2.2,
        "24": 1.9, "22": 1.9,
        "25": 2.5, "219": 1.5,
        # First-half 1X2 (codes 4/5/6) is a supported experimental market;
        # advance and combination picks must still not be inferred.
        "4": 2.0, "5": 3.0, "6": 4.0, "335": 1.4, "336": 2.8,
    }
    markets = _parse_betole_markets(odds)
    assert {m.market_type for m in markets} == {
        MarketType.MATCH_RESULT,
        MarketType.DOUBLE_CHANCE,
        MarketType.BTTS,
        MarketType.FIRST_HALF_1X2,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
    }
    assert {o.label for o in next(m for m in markets if m.market_type == MarketType.MATCH_RESULT).odds} == {"1", "X", "2"}


def test_betole_advance_picks_do_not_become_double_chance():
    assert _parse_betole_markets({"335": 1.4, "336": 2.8}) == []


def test_evlbet_skips_non_1x2_basic_offer():
    scraper = EvlbetScraper()
    ev = {
        "TeamHome": "A", "TeamAway": "B", "Id": 1, "MatchStartTime": "2026-08-15T18:00:00",
        "BasicOffer": {"HasSbv": True, "Sbv": 2.5, "Odds": [{"Name": "1", "Odd": 2.0}, {"Name": "2", "Odd": 1.8}]},
    }
    assert scraper._parse_event(ev) is None


def test_evlbet_requires_all_three_outcomes():
    scraper = EvlbetScraper()
    ev = {
        "TeamHome": "A", "TeamAway": "B", "Id": 1, "MatchStartTime": "2026-08-15T18:00:00",
        "BasicOffer": {"Odds": [{"Name": "1", "Odd": 2.0}, {"Name": "2", "Odd": 1.8}]},
    }
    assert scraper._parse_event(ev) is None
