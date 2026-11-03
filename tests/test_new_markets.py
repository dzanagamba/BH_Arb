"""Tests for the experimental markets: first-half 1X2, first-half O/U, Asian handicap."""

from datetime import UTC, datetime, timedelta

from engine.arbitrage import ArbitrageEngine
from engine.matcher import swap_match_teams_and_odds
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from scrapers.common import ah_label, flip_ah_label, parse_ah_label
from scrapers.mbet import _resolve_mbet_market
from scrapers.premier_kladionica import PremierKladionicaScraper
from scrapers.sportplus import SportPlusScraper
from scrapers.wwin import _build_markets_from_bets

KICKOFF = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1, hours=2)


def _group(matches_by_bookie: dict[str, list[Market]]) -> MatchGroup:
    matches = [
        Match(
            bookmaker=bookie,
            home_team="Sarajevo",
            away_team="Željezničar",
            league="BiH - Premier Liga",
            kickoff=KICKOFF,
            markets=markets,
        )
        for bookie, markets in matches_by_bookie.items()
    ]
    return MatchGroup(
        status="verified",
        canonical_home="Sarajevo",
        canonical_away="Zeljeznicar",
        league="premier_liga_bih",
        kickoff=KICKOFF,
        matches=matches,
    )


def _fh1x2(odds: dict[str, float]) -> Market:
    return Market(
        market_type=MarketType.FIRST_HALF_1X2,
        odds=[OddsValue(label=k, value=v) for k, v in odds.items()],
    )


def _ah(odds: list[tuple[str, float]]) -> Market:
    return Market(
        market_type=MarketType.ASIAN_HANDICAP,
        odds=[OddsValue(label=k, value=v) for k, v in odds],
    )


# ─── Engine: first-half 1X2 ────────────────────────────────────────────────

def test_first_half_1x2_detected_and_gated():
    group = _group({
        "mbet": [_fh1x2({"1": 3.50, "X": 3.00, "2": 2.60})],
        "wwin": [_fh1x2({"1": 3.10, "X": 3.30, "2": 2.90})],
        "sportplus": [_fh1x2({"1": 3.00, "X": 2.80, "2": 3.10})],
    })
    engine = ArbitrageEngine()

    # Gated OFF (default): market must not be detected
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"1x2"})
    assert not any(s.market_type == MarketType.FIRST_HALF_1X2 for s in surebets)

    # Gated ON: detected
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"first_half_1x2"})
    fh = [s for s in surebets if s.market_type == MarketType.FIRST_HALF_1X2]
    assert len(fh) == 1
    assert fh[0].profit_percent > 0.5
    assert {s.bookmaker for s in fh[0].stakes} == {"mbet", "wwin", "sportplus"}


def test_first_half_1x2_needs_three_bookmakers():
    group = _group({
        "mbet": [_fh1x2({"1": 3.20, "X": 2.60, "2": 2.30})],
        "wwin": [_fh1x2({"1": 2.90, "X": 2.80, "2": 2.40})],
    })
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"first_half_1x2"})
    assert not any(s.market_type == MarketType.FIRST_HALF_1X2 for s in surebets)


# ─── Engine: Asian handicap ────────────────────────────────────────────────

def test_asian_handicap_same_line_arb():
    # Both books quote the -0.5 home line; implied sum must be < 1
    group = _group({
        "mbet": [_ah([("1 -0.5", 2.10), ("2 +0.5", 1.95)])],
        "sportplus": [_ah([("1 -0.5", 2.30), ("2 +0.5", 1.80)])],
    })
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"asian_handicap"})
    ah = [s for s in surebets if s.market_type == MarketType.ASIAN_HANDICAP]
    assert len(ah) == 1
    assert ah[0].profit_percent > 0.5
    labels = {s.outcome_label for s in ah[0].stakes}
    assert labels == {"1 -0.5", "2 +0.5"}


def test_asian_handicap_mixed_lines_no_arb():
    # Different lines (0.5 vs 1.0) must NOT combine
    group = _group({
        "mbet": [_ah([("1 -0.5", 2.10), ("2 +0.5", 1.95)])],
        "sportplus": [_ah([("1 -1", 2.90), ("2 +1", 1.40)])],
    })
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"asian_handicap"})
    assert not any(s.market_type == MarketType.ASIAN_HANDICAP for s in surebets)


def test_asian_handicap_level_ball():
    group = _group({
        "sportplus": [_ah([("1 0", 2.60), ("2 0", 1.75)])],
        "mbet": [_ah([("1 0", 2.20), ("2 0", 1.70)])],
    })
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"asian_handicap"})
    ah = [s for s in surebets if s.market_type == MarketType.ASIAN_HANDICAP]
    assert len(ah) == 1


# ─── Engine: first-half O/U ────────────────────────────────────────────────

def test_first_half_ou_line_grouping():
    group = _group({
        "premier": [Market(
            market_type=MarketType.FIRST_HALF_OU,
            odds=[OddsValue(label="Over 1.5", value=1.80), OddsValue(label="Under 1.5", value=2.05)],
        )],
        "sportplus": [Market(
            market_type=MarketType.FIRST_HALF_OU,
            odds=[OddsValue(label="Over 1.5", value=2.20), OddsValue(label="Under 1.5", value=1.70)],
        )],
    })
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"first_half_ou"})
    fh = [s for s in surebets if s.market_type == MarketType.FIRST_HALF_OU]
    assert len(fh) == 1
    assert {s.outcome_label for s in fh[0].stakes} == {"Over 1.5", "Under 1.5"}


# ─── Matcher: swap flips ───────────────────────────────────────────────────

def test_swap_flips_ah_labels():
    match = Match(
        bookmaker="mbet", home_team="A", away_team="B",
        markets=[_ah([("1 -0.5", 2.10), ("2 +0.5", 1.95)])],
    )
    flipped = swap_match_teams_and_odds(match)
    labels = {o.label for m in flipped.markets for o in m.odds}
    assert labels == {"2 -0.5", "1 +0.5"}


def test_swap_flips_fh_1x2():
    match = Match(
        bookmaker="mbet", home_team="A", away_team="B",
        markets=[_fh1x2({"1": 3.0, "X": 2.7, "2": 2.4})],
    )
    flipped = swap_match_teams_and_odds(match)
    by_label = {o.label: o.value for m in flipped.markets for o in m.odds}
    assert by_label["1"] == 2.4 and by_label["2"] == 3.0


def test_ah_label_helpers():
    assert ah_label("1", -0.5) == "1 -0.5"
    assert ah_label("2", 0.5) == "2 +0.5"
    assert ah_label("1", 0) == "1 0"
    assert parse_ah_label("2 +0.5") == ("2", 0.5)
    assert parse_ah_label("garbage") is None
    assert flip_ah_label("1 -0.5") == "2 -0.5"


# ─── Scrapers ──────────────────────────────────────────────────────────────

def test_mbet_parses_fh_and_ah():
    odds = {
        "ofb:fs:1": {"value": 2.4, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:fs:X": {"value": 3.1, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:fs:2": {"value": 2.9, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:ht:1": {"value": 3.2, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:ht:X": {"value": 2.6, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:ht:2": {"value": 2.3, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:hc:H1|0.5": {"value": 2.05, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:hc:H2|0.5": {"value": 1.95, "market_status": "ACTIVE", "oddtype_status": 1},
    }
    markets = _resolve_mbet_market("fb", odds)
    assert "first_half_1x2" in markets
    assert {o.label for o in markets["first_half_1x2"]} == {"1", "X", "2"}
    ah = markets["asian_handicap"]
    labels = {o.label for o in ah}
    # home 2.05 > away 1.95 → away favoured → home is +0.5
    assert labels == {"1 +0.5", "2 -0.5"}


def test_mbet_ah_suspended_skipped():
    odds = {
        "ofb:hc:H1|1.0": {"value": 2.31, "market_status": "ACTIVE", "oddtype_status": 1},
        "ofb:hc:H2|1.0": {"value": 1.48, "market_status": "SUSPENDED", "oddtype_status": 0},
    }
    markets = _resolve_mbet_market("fb", odds)
    assert "asian_handicap" not in markets


def test_sportplus_parses_fh_and_ah0():
    scraper = SportPlusScraper()
    markets = scraper._parse_markets([
        {"id": 4, "name": "PRVO POLUVRIJEME", "odds": [
            {"alias": "1", "value": 3.8}, {"alias": "X", "value": 2.25}, {"alias": "2", "value": 2.9},
        ]},
        {"id": 25, "name": "AZIJSKI HENDIKEP", "odds": [
            {"alias": "1", "value": 2.3}, {"alias": "2", "value": 1.5},
        ]},
    ])
    by_type = {m.market_type: m for m in markets}
    assert MarketType.FIRST_HALF_1X2 in by_type
    assert {o.label for o in by_type[MarketType.FIRST_HALF_1X2].odds} == {"1", "X", "2"}
    assert MarketType.ASIAN_HANDICAP in by_type
    assert {o.label for o in by_type[MarketType.ASIAN_HANDICAP].odds} == {"1 0", "2 0"}


def test_wwin_parses_half_time_1x2():
    markets = _build_markets_from_bets([
        {"idBt": 2, "odds": [
            {"t": "1", "va": 3.4}, {"t": "X", "va": 2.7}, {"t": "2", "va": 2.5},
        ]},
    ])
    fh = [m for m in markets if m.market_type == MarketType.FIRST_HALF_1X2]
    assert len(fh) == 1
    assert {o.label for o in fh[0].odds} == {"1", "X", "2"}


def test_premier_parses_fh_1x2():
    scraper = PremierKladionicaScraper()
    # setTip: (sport=2, setTipID=1) -> "1. POLUVRIJEME"
    # setTipTip: (2, 1, tipID) -> kod "1"/"X"/"2"
    markets = scraper._build_markets(
        rows=[
            [0, 0, 1, 10, 1, 3.2, 1, 0, 0],
            [0, 0, 1, 10, 2, 2.6, 1, 0, 0],
            [0, 0, 1, 10, 3, 2.3, 1, 0, 0],
        ],
        set_tip={(2, 1): "1. POLUVRIJEME"},
        set_tip_var={(2, 1, 10): ""},
        set_tip_tip={(2, 1, 1): "1", (2, 1, 2): "X", (2, 1, 3): "2"},
        live=False,
    )
    fh = [m for m in markets if m.market_type == MarketType.FIRST_HALF_1X2]
    assert len(fh) == 1
    assert {o.label for o in fh[0].odds} == {"1", "X", "2"}


def test_premier_parses_fh_ou():
    scraper = PremierKladionicaScraper()
    markets = scraper._build_markets(
        rows=[
            [0, 0, 1, 10, 1, 1.85, 1, 0, 0],
            [0, 0, 1, 10, 2, 1.95, 1, 0, 0],
        ],
        set_tip={(2, 1): "1. POLUVRIJEME - ZBROJ GOLOVA (-1,5+)"},
        set_tip_var={(2, 1, 10): "(-1,5+)"},
        set_tip_tip={(2, 1, 1): "v", (2, 1, 2): "m"},
        live=False,
    )
    fh = [m for m in markets if m.market_type == MarketType.FIRST_HALF_OU]
    assert len(fh) == 1
    assert {o.label for o in fh[0].odds} == {"Over 1.5", "Under 1.5"}


def test_premier_excludes_parity_variant():
    scraper = PremierKladionicaScraper()
    markets = scraper._build_markets(
        rows=[[0, 0, 1, 10, 1, 1.9, 1, 0, 0], [0, 0, 1, 10, 2, 1.9, 1, 0, 0]],
        set_tip={(2, 1): "1. POLUVRIJEME - ZBROJ GOLOVA - PAR/NEPAR"},
        set_tip_var={(2, 1, 10): "(-0,5+)"},
        set_tip_tip={(2, 1, 1): "v", (2, 1, 2): "m"},
        live=False,
    )
    assert not any(m.market_type == MarketType.FIRST_HALF_OU for m in markets)


def test_default_scan_still_works_with_gating():
    """Existing markets keep working when the gate is applied (server default)."""
    group = _group({
        "mdshop": [Market(market_type=MarketType.BTTS, odds=[OddsValue(label="GG", value=2.4), OddsValue(label="NG", value=1.9)])],
        "mbet": [Market(market_type=MarketType.BTTS, odds=[OddsValue(label="GG", value=2.2), OddsValue(label="NG", value=1.85)])],
    })
    engine = ArbitrageEngine()
    surebets = engine.find_surebets([group], min_profit=0.5, investment=100.0,
                                    enabled_markets={"btts"})
    assert len(surebets) == 1
    assert surebets[0].market_type == MarketType.BTTS
