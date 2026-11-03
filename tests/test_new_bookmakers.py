"""Tests for the two new bookmakers: WWIN and Premier Kladionica.

Fixtures are reconstructed verbatim from live API responses captured on
2026-08-15 (verified against the sites' own payloads).
"""

from models.schemas import MarketType
from scrapers.premier_kladionica import (
    PremierKladionicaScraper,
    _norm_name,
    _parse_line,
)
from scrapers.wwin import WWINScraper, _build_markets_from_bets

# ─── WWIN ─────────────────────────────────────────────────────────────────────

def test_wwin_market_ids_map_correctly():
    event = {"id": 4384005, "hname": "Arsenal", "aname": "Man.City", "bets": [
        {"idBt": 95, "spec": "", "odds": [
            {"va": 2.56, "t": "1", "isv": 1}, {"va": 3.25, "t": "X", "isv": 1}, {"va": 2.7, "t": "2", "isv": 1},
        ]},
        {"idBt": 6, "spec": "", "odds": [
            {"va": 1.33, "t": "12", "isv": 1}, {"va": 1.48, "t": "X2", "isv": 1}, {"va": 1.44, "t": "1X", "isv": 1},
        ]},
        {"idBt": 3, "spec": "", "odds": [
            {"va": 1.72, "t": "Yes", "isv": 1}, {"va": 2.14, "t": "No", "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=2,5", "odds": [
            {"va": 1.9, "t": "Over", "isv": 1}, {"va": 1.91, "t": "Under", "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=1,5", "odds": [
            {"va": 1.29, "t": "Over", "isv": 1}, {"va": 3.65, "t": "Under", "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=3,5", "odds": [
            {"va": 3.2, "t": "Over", "isv": 1}, {"va": 1.36, "t": "Under", "isv": 1},
        ]},
    ]}
    markets = _build_markets_from_bets(event.get('bets', []))
    by_type = {m.market_type: m for m in markets}
    assert set(by_type) == {
        MarketType.MATCH_RESULT,
        MarketType.DOUBLE_CHANCE,
        MarketType.BTTS,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
    }
    assert {o.label for o in by_type[MarketType.BTTS].odds} == {"GG", "NG"}
    assert {o.label for o in by_type[MarketType.OVER_UNDER_2_5].odds} == {"Over 2.5", "Under 2.5"}


def test_wwin_advance_handicap_and_period_markets_rejected():
    event = {"id": 1, "hname": "A", "aname": "B", "bets": [
        {"idBt": 7, "spec": "", "odds": [{"va": 1.79, "t": "1", "isv": 1}, {"va": 1.88, "t": "2", "isv": 1}]},
        {"idBt": 10, "spec": "hcp=0:1", "odds": [{"va": 5.0, "t": "1", "isv": 1}, {"va": 4.3, "t": "X", "isv": 1}, {"va": 1.48, "t": "2", "isv": 1}]},
        {"idBt": 4, "spec": "", "odds": [{"va": 4.1, "t": "1/1", "isv": 1}, {"va": 5.1, "t": "X/X", "isv": 1}, {"va": 4.4, "t": "2/2", "isv": 1}]},
        {"idBt": 476, "spec": "", "odds": [{"va": 1.4, "t": "1", "isv": 1}, {"va": 2.8, "t": "2", "isv": 1}]},
        {"idBt": 443, "spec": "total=2,25", "odds": [{"va": 1.67, "t": "Over", "isv": 1}, {"va": 2.22, "t": "Under", "isv": 1}]},
        {"idBt": 11, "spec": "total=2,75", "odds": [{"va": 2.14, "t": "Over", "isv": 1}, {"va": 1.72, "t": "Under", "isv": 1}]},
    ]}
    assert _build_markets_from_bets(event.get('bets', [])) == []


def test_wwin_ignores_suspended_odds():
    event = {"id": 1, "hname": "A", "aname": "B", "bets": [
        {"idBt": 95, "spec": "", "odds": [
            {"va": 0.0, "t": "1", "isv": 0}, {"va": 7.5, "t": "X", "isv": 1}, {"va": 20.0, "t": "2", "isv": 1},
        ]},
    ]}
    assert _build_markets_from_bets(event.get('bets', [])) == []


def test_wwin_scraper_exports_expected_api():
    scraper = WWINScraper()
    assert hasattr(scraper, "scrape")
    assert callable(scraper.fetch_and_parse)


# ─── Premier Kladionica ───────────────────────────────────────────────────────

def test_pk_norm_and_line_parsing():
    assert _norm_name("  OBA   DAJU GOL ") == "OBA DAJU GOL"
    assert _norm_name("LIVE - UTAKMICA") == "LIVE - UTAKMICA"
    assert _parse_line("(-2,5+)") == "2.5"
    assert _parse_line("(-1,5+)") == "1.5"
    assert _parse_line("(-3,5+)") == "3.5"
    assert _parse_line("") is None
    assert _parse_line("(-0,5+)") is None  # unsupported line


def test_pk_markets_classified_correctly():
    """Reconstruct a real event's odds: UTAKMICA 1X2+DC, OBA DAJU GOL, ZBROJ GOLOVA."""
    scraper = PremierKladionicaScraper()
    set_tip = {
        (2, 1546): "UTAKMICA",
        (2, 1452): "OBA DAJU GOL",
        (2, 1442): "ZBROJ GOLOVA",
        (2, 1440): "HENDIKEP",
        (2, 1437): "KLAĐENJE NA POBJEDU",
    }
    set_tip_var = {
        (2, 1546, 1): "",
        (2, 1452, 1): "",
        (2, 1442, 3): "(-2,5+)",
        (2, 1442, 4): "(-3,5+)",
        (2, 1440, 1): "(0:1)",
    }
    set_tip_tip = {
        (2, 1546, 1): "1", (2, 1546, 2): "X", (2, 1546, 3): "2",
        (2, 1546, 4): "1X", (2, 1546, 5): "X2", (2, 1546, 6): "12",
        (2, 1452, 1): "o-da", (2, 1452, 2): "o-ne",
        (2, 1442, 1): "m", (2, 1442, 2): "v",
        (2, 1440, 1): "hc1", (2, 1440, 2): "hcX", (2, 1440, 3): "hc2",
        (2, 1437, 1): "kp1", (2, 1437, 2): "kp2",
    }
    rows = [
        # dogID, grupaTipID, setTipID, varID, tipID, koef, naPon, dobitni, koef1
        [4432174, 2, 1546, 1, 1, 2.05, 1, 0, 1],
        [4432174, 2, 1546, 1, 2, 3.40, 1, 0, 1],
        [4432174, 2, 1546, 1, 3, 3.85, 1, 0, 1],
        [4432174, 2, 1546, 1, 4, 1.28, 1, 0, 1],
        [4432174, 2, 1546, 1, 5, 1.75, 1, 0, 1],
        [4432174, 2, 1546, 1, 6, 1.34, 1, 0, 1],
        [4432174, 2, 1452, 1, 1, 1.95, 1, 0, 1],
        [4432174, 2, 1452, 1, 2, 1.90, 1, 0, 1],
        [4432174, 2, 1442, 3, 1, 1.75, 1, 0, 1],
        [4432174, 2, 1442, 3, 2, 2.15, 1, 0, 1],
        [4432174, 2, 1442, 4, 1, 1.28, 1, 0, 1],
        [4432174, 2, 1442, 4, 2, 3.90, 1, 0, 1],
        [4432174, 2, 1440, 1, 1, 3.80, 1, 0, 1],
        [4432174, 2, 1440, 1, 2, 3.80, 1, 0, 1],
        [4432174, 2, 1440, 1, 3, 1.75, 1, 0, 1],
        [4432174, 2, 1437, 1, 1, 1.50, 1, 0, 1],
        [4432174, 2, 1437, 1, 2, 2.70, 1, 0, 1],
    ]
    markets = scraper._build_markets(rows, set_tip, set_tip_var, set_tip_tip, live=False)
    by_type = {m.market_type: m for m in markets}
    assert set(by_type) == {
        MarketType.MATCH_RESULT,
        MarketType.DOUBLE_CHANCE,
        MarketType.BTTS,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
    }
    mr = by_type[MarketType.MATCH_RESULT]
    assert {o.label for o in mr.odds} == {"1", "X", "2"}
    assert {o.label for o in by_type[MarketType.DOUBLE_CHANCE].odds} == {"1X", "X2", "12"}
    assert {o.label for o in by_type[MarketType.BTTS].odds} == {"GG", "NG"}
    assert {o.label for o in by_type[MarketType.OVER_UNDER_2_5].odds} == {"Over 2.5", "Under 2.5"}
    assert {o.label for o in by_type[MarketType.OVER_UNDER_3_5].odds} == {"Over 3.5", "Under 3.5"}


def test_pk_live_markets_require_live_prefix():
    scraper = PremierKladionicaScraper()
    set_tip = {(2, 2338): "LIVE - UTAKMICA", (2, 1546): "UTAKMICA"}
    set_tip_var = {}
    set_tip_tip = {
        (2, 2338, 1): "1", (2, 2338, 2): "X", (2, 2338, 3): "2",
        (2, 1546, 1): "1", (2, 1546, 2): "X", (2, 1546, 3): "2",
    }
    rows = [
        [1, 2, 2338, 1, 1, 1.55, 1, 0, 1],
        [1, 2, 2338, 1, 2, 3.40, 1, 0, 1],
        [1, 2, 2338, 1, 3, 7.60, 1, 0, 1],
        [1, 2, 1546, 1, 1, 2.05, 1, 0, 1],
        [1, 2, 1546, 1, 2, 3.40, 1, 0, 1],
        [1, 2, 1546, 1, 3, 3.85, 1, 0, 1],
    ]
    live_markets = scraper._build_markets(rows, set_tip, set_tip_var, set_tip_tip, live=True)
    assert [m.market_type for m in live_markets] == [MarketType.MATCH_RESULT]
    prematch_markets = scraper._build_markets(rows, set_tip, set_tip_var, set_tip_tip, live=False)
    assert [m.market_type for m in prematch_markets] == [MarketType.MATCH_RESULT]


def test_pk_advance_market_rejected():
    scraper = PremierKladionicaScraper()
    set_tip = {(2, 1435): "NAČIN PROLAZA"}
    set_tip_var = {}
    set_tip_tip = {
        (2, 1435, 1, 10): "1", (2, 1435, 1, 20): "2",
    }
    rows = [
        [1, 2, 1435, 1, 10, 1.40, 1, 0, 1],
        [1, 2, 1435, 1, 20, 2.80, 1, 0, 1],
    ]
    assert scraper._build_markets(rows, set_tip, set_tip_var, set_tip_tip, live=False) == []
