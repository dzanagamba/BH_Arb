"""Sport identity, per-book normalization, and non-football market parsing."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from engine import sports
from engine.certainty import CertaintyGate
from engine.matcher import MatchMatcher, swap_match_teams_and_odds
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.common import parse_nsoft_bets
from scrapers.maxbet import parse_sport_odds
from scrapers.mbet import _resolve_mbet_sport_market
from scrapers.sportplus import SportPlusScraper

FIXTURE = Path(__file__).parent / "fixtures" / "sports" / "normalization.json"


def _match(bookmaker: str, sport: str, home: str, away: str, league: str, kickoff: datetime) -> Match:
    return Match(
        bookmaker=bookmaker,
        sport=sport,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MONEYLINE,
                odds=[OddsValue(label="1", value=2.0), OddsValue(label="2", value=1.9)],
                settlement=sports.settlement_for(sport, MarketType.MONEYLINE),
            )
        ],
    )


def _normalized(sport: str, book: str, values: dict, kickoff: datetime) -> Match:
    match = _match(book, sport, values["home"], values["away"], values["league"], kickoff)
    MatchMatcher().normalize_matches([match])
    return match


def test_sport_mismatch_is_a_hard_rejection():
    kickoff = datetime(2026, 11, 4, 18, 0)
    football = _match("sportplus", "football", "Same", "Names", "Same League", kickoff)
    basketball = _match("mdshop", "basketball", "Same", "Names", "Same League", kickoff)
    result = CertaintyGate().evaluate_pair(football, basketball)
    assert result.status == "rejected"
    assert "sport_mismatch" in result.reasons


def test_matcher_never_merges_two_sports_even_with_identical_names():
    kickoff = datetime(2026, 11, 4, 18, 0)
    matches = [
        _match("sportplus", "football", "Tigers", "Bears", "League", kickoff),
        _match("mbet", "football", "Tigers", "Bears", "League", kickoff),
        _match("mdshop", "basketball", "Tigers", "Bears", "League", kickoff),
        _match("maxbet", "basketball", "Tigers", "Bears", "League", kickoff),
    ]
    groups = MatchMatcher().group_matches(matches)
    assert len(groups) == 2
    for group in groups:
        assert {match.sport for match in group.matches} == {group.sport}
    assert {group.sport for group in groups} == {"football", "basketball"}


def test_swap_preserves_sport_and_flips_moneyline_labels():
    match = _match(
        "sportplus", "basketball", "Home", "Away", "League", datetime(2026, 11, 4, 18, 0)
    )
    swapped = swap_match_teams_and_odds(match)
    assert swapped.sport == "basketball"
    assert swapped.home_team == "Away"
    assert swapped.markets[0].settlement == match.markets[0].settlement
    assert {odd.label for odd in swapped.markets[0].odds} == {"1", "2"}


@pytest.mark.parametrize("sport", ["basketball", "tennis"])
def test_every_implemented_book_normalizes_to_one_fixture(sport):
    values = json.loads(FIXTURE.read_text(encoding="utf-8"))[sport]
    kickoff = datetime(2026, 11, 4, 18, 0)
    reference = _normalized(sport, "sportplus", values["sportplus"], kickoff)
    gate = CertaintyGate()
    for book, listing in values.items():
        candidate = _normalized(sport, book, listing, kickoff)
        result = gate.evaluate_pair(candidate, reference)
        assert result.status == "verified", (book, result.reasons)
        assert result.is_swapped is False


def test_league_tokens_accept_country_prefixes_but_not_different_leagues():
    assert sports.league_tokens_compatible("nba", "sad nba")
    assert not sports.league_tokens_compatible("nba", "wnba")
    assert not sports.league_tokens_compatible("aba liga", "aba liga 2")
    assert not sports.league_tokens_compatible(
        "Eurokup (M) - Grupa A", "Eurokup (M) - Grupa B"
    )


def test_tennis_surname_initial_is_identity_but_two_initials_are_not():
    gate = CertaintyGate()
    assert gate._team_pair_details(
        "Zverev A.", "zverev a", "Zverev, Alexander", "zverev alexander", "tennis"
    )[0]
    assert not gate._team_pair_details(
        "Zverev M.", "zverev m", "Zverev, Alexander", "zverev alexander", "tennis"
    )[0]


# ---------------------------------------------------------------------------
# SportPlus
# ---------------------------------------------------------------------------

def test_sportplus_basketball_moneyline_handicap_and_total():
    scraper = SportPlusScraper()
    markets = scraper._parse_markets(
        [
            {
                "id": 210,
                "name": "POBJEDNIK",
                "odds": [
                    {"alias": "1", "value": 2.1, "description": "uključujući produžetke"},
                    {"alias": "2", "value": 1.65, "description": "uključujući produžetke"},
                ],
            },
            {
                "id": 1157,
                "name": "HENDIKEP",
                "competitors": "h/Rigas Zelli(+1,5)-Le Mans",
                "odds": [{"alias": "1", "value": 2.0}, {"alias": "2", "value": 1.75}],
            },
            {
                "id": 55,
                "name": "ZBROJ KOŠEVA",
                "competitors": "z/Rigas Zelli-Le Mans (-162,5+)",
                "odds": [{"alias": "Manje", "value": 1.55}, {"alias": "Više", "value": 2.3}],
            },
        ],
        "basketball",
    )
    by_type = {market.market_type: market for market in markets}
    assert set(by_type) == {MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL}
    assert by_type[MarketType.MONEYLINE].settlement == "full_time_incl_ot"
    assert {(o.label, o.value) for o in by_type[MarketType.HANDICAP].odds} == {
        ("1 -1.5", 2.0),
        ("2 +1.5", 1.75),
    }
    assert {(o.label, o.value) for o in by_type[MarketType.TOTAL].odds} == {
        ("Over 162.5", 2.3),
        ("Under 162.5", 1.55),
    }


def test_sportplus_tennis_market_families():
    scraper = SportPlusScraper()
    markets = scraper._parse_markets(
        [
            {"id": 71, "name": "Osnovno", "odds": [
                {"alias": "1", "value": 1.4}, {"alias": "2", "value": 2.9},
            ]},
            {"id": 73, "name": "HENDIKEP GEMOVA",
             "competitors": "(h/)Zverev A. - Musetti L. (+2,5)",
             "odds": [{"alias": "1", "value": 1.75}, {"alias": "2", "value": 2.0}]},
            {"id": 74, "name": "ZBROJ GEMOVA",
             "competitors": "(z/)Zverev A. - Musetti L. (-22,5+)",
             "odds": [{"alias": "Manje", "value": 1.9}, {"alias": "Više", "value": 1.8}]},
        ],
        "tennis",
    )
    assert {m.market_type for m in markets} == {
        MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL
    }
    assert all(m.settlement == "full_match" for m in markets)


# ---------------------------------------------------------------------------
# MBet
# ---------------------------------------------------------------------------

def test_mbet_basketball_keys_and_settlements():
    odds = {
        "obb:fsot:1": 1.82,
        "obb:fsot:2": 2.05,
        "obb:hc:H1|-6.5": 2.42,
        "obb:hc:H2|6.5": 1.52,
        "obb:p:(+)|221.5": 2.27,
        "obb:p:(-)|221.5": 1.59,
    }
    resolved = _resolve_mbet_sport_market("bb", odds)
    assert set(resolved) == {"moneyline", "handicap", "total"}
    assert resolved["moneyline"][0][2] == "full_time_incl_ot"
    assert {(o.label, o.value) for o in resolved["handicap"][0][1]} == {
        ("1 -6.5", 2.42), ("2 +6.5", 1.52)
    }


def test_mbet_tennis_game_handicap_uses_the_opponent_line():
    resolved = _resolve_mbet_sport_market(
        "tn",
        {"otn:fs:1": 1.4, "otn:fs:2": 2.9,
         "otn:hg:1|-2.5": 1.8, "otn:hg:2|2.5": 1.91,
         "otn:g:(+)|22.5": 1.86, "otn:g:(-)|22.5": 1.95},
    )
    handicap = dict((o.label, o.value) for o in resolved["handicap"][0][1])
    assert handicap == {"1 -2.5": 1.8, "2 +2.5": 1.91}


# ---------------------------------------------------------------------------
# NSoft (MDShop + Admiralbet)
# ---------------------------------------------------------------------------

def _nsoft_bet(btid, sbv, outcomes):
    return {
        "betTypeId": btid,
        "sbv": sbv,
        "betOutcomes": [{"name": name, "odd": value} for name, value in outcomes],
    }


def test_nsoft_basketball_three_families_and_sbv_orientation():
    markets = parse_nsoft_bets(
        [
            _nsoft_bet(186, None, [("1", 1.73), ("2", 2.12)]),
            _nsoft_bet(191, "-6.5", [("1", 2.42), ("2", 1.519)]),
            _nsoft_bet(213, "221.5", [("Manje", 1.59), ("Vise", 2.27)]),
        ],
        sport="basketball",
    )
    by_type = {market.market_type: market for market in markets}
    assert set(by_type) == {MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL}
    assert {(o.label, o.value) for o in by_type[MarketType.HANDICAP].odds} == {
        ("1 -6.5", 2.42), ("2 +6.5", 1.519)
    }
    assert by_type[MarketType.MONEYLINE].settlement == "full_time_incl_ot"


def test_nsoft_tennis_uses_220_not_the_set_handicap_210():
    markets = parse_nsoft_bets(
        [
            _nsoft_bet(1723, None, [("1", 1.4), ("2", 3.0)]),
            _nsoft_bet(220, "-2.5", [("1", 1.86), ("2", 1.95)]),
            _nsoft_bet(210, "-1.5", [("1", 1.94), ("2", 1.8)]),
            _nsoft_bet(187, "22.5", [("Manje", 1.95), ("Vise", 1.86)]),
        ],
        sport="tennis",
    )
    assert {m.market_type for m in markets} == {
        MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL
    }
    handicap = next(m for m in markets if m.market_type == MarketType.HANDICAP)
    assert {(o.label, o.value) for o in handicap.odds} == {
        ("1 -2.5", 1.86), ("2 +2.5", 1.95)
    }
    assert all(m.source_id != "210" for m in markets)


def test_admiralbet_basketball_winner_override():
    markets = parse_nsoft_bets(
        [_nsoft_bet(1640, None, [("1", 1.7), ("2", 2.1)])],
        sport="basketball",
        bookmaker="admiralbet",
    )
    assert [m.market_type for m in markets] == [MarketType.MONEYLINE]


# ---------------------------------------------------------------------------
# MaxBet
# ---------------------------------------------------------------------------

def test_maxbet_basketball_and_tennis_odd_types():
    basketball = parse_sport_odds(
        [
            {"id": 175, "outcomes": [{"outcome": "1", "oddValue": 1.82, "status": 0},
                                     {"outcome": "2", "oddValue": 2.05, "status": 0}]},
            {"id": 16, "specifiers": {"hcp": "-6.5"},
             "outcomes": [{"outcome": "H1", "oddValue": 2.42, "status": 0},
                          {"outcome": "H2", "oddValue": 1.52, "status": 0}]},
            {"id": 224, "specifiers": {"total": "221.5"},
             "outcomes": [{"outcome": "UP- {total}", "oddValue": 1.59, "status": 0},
                          {"outcome": "UP+ {total}", "oddValue": 2.27, "status": 0}]},
        ],
        "basketball",
    )
    assert {m.market_type for m in basketball} == {
        MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL
    }
    assert basketball[1].settlement == "regulation"

    tennis = parse_sport_odds(
        [
            {"id": 175, "outcomes": [{"outcome": "1", "oddValue": 1.4, "status": 0},
                                     {"outcome": "2", "oddValue": 2.9, "status": 0}]},
            {"id": 176, "specifiers": {"hcp": "-4.5"},
             "outcomes": [{"outcome": "HG1", "oddValue": 1.8, "status": 0},
                          {"outcome": "HG2", "oddValue": 1.9, "status": 0}]},
            {"id": 178, "specifiers": {"total": "20.5"},
             "outcomes": [{"outcome": "Manje {total}", "oddValue": 1.83, "status": 0},
                          {"outcome": "Više {total}", "oddValue": 1.91, "status": 0}]},
        ],
        "tennis",
    )
    assert {m.market_type for m in tennis} == {
        MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL
    }
    assert next(m for m in tennis if m.market_type == MarketType.HANDICAP).odds[0].label == "1 -4.5"


def test_nonfootball_team_cleaning_removes_book_noise_not_identity():
    assert sports.clean_team("basketball", "ŽKK Crvena Zvezda W") == "Crvena Zvezda"
    assert sports.clean_team("basketball", "KK Spartak Subotica") == "Spartak Subotica"
    assert sports.clean_team("basketball", "TFT Basketball Club") == "TFT"
    assert sports.clean_team("basketball", "Rotterdam City Basketball") == "Rotterdam City"
    assert sports.clean_team("tennis", "Zverev, Alexander") == "Zverev Alexander"
    assert sports.clean_team("tennis", "(SRB) Zverev A.") == "Zverev A"


def test_tennis_compound_surnames_and_doubles_match():
    from engine.name_identity import tokens

    def same(left: str, right: str) -> bool:
        return sports.tennis_name_match(left, right, tokens(left), tokens(right))

    assert same("De Minaur A.", "Alex De Minaur")
    assert same("Auger Aliassime F.", "Felix Auger-Aliassime")
    assert same("Romero Gormaz L.", "Leyre Romero Gormaz")
    assert same("Rajeshwaran Revathi M.", "Maaya Rajeshwaran Revathi")
    assert same("Haverlag I / Udvardy P", "Haverlag Udvardy")
    assert not same("Zverev M.", "Zverev A.")
    assert not same("Zverev A.", "Zverev")


def test_women_markers_from_every_implemented_book_agree():
    normalizer = __import__(
        "engine.normalizer", fromlist=["TeamNormalizer"]
    ).TeamNormalizer()
    for text in (
        "Evrokup Ž",
        "Košarka EuroCup Women",
        "Alba Berlin Wom",
        "ITF W50 Heraklion GRE",
        "WTA 125 Cali",
    ):
        assert "Women" in normalizer.detect_special_category(text), text


def test_nonfootball_league_names_do_not_veto_a_proven_fixture():
    kickoff = datetime(2026, 11, 4, 18, 0)
    reference = _normalized(
        "basketball",
        "sportplus",
        {"home": "Liepaja", "away": "Keila Coolbet", "league": "1. LIGA"},
        kickoff,
    )
    candidate = _normalized(
        "basketball",
        "mbet",
        {"home": "BK Liepaja", "away": "Keila Basket", "league": "LATVIA-ESTONIAN LEAGUE"},
        kickoff,
    )
    result = CertaintyGate().evaluate_pair(candidate, reference)
    assert result.status == "verified", result.reasons


def test_nonfootball_league_names_do_not_merge_unproven_teams():
    kickoff = datetime(2026, 11, 4, 18, 0)
    reference = _normalized(
        "basketball",
        "sportplus",
        {"home": "Liepaja", "away": "Keila Coolbet", "league": "1. LIGA"},
        kickoff,
    )
    candidate = _normalized(
        "basketball",
        "mbet",
        {"home": "Ventspils", "away": "Keila Basket", "league": "LATVIA-ESTONIAN LEAGUE"},
        kickoff,
    )
    result = CertaintyGate().evaluate_pair(candidate, reference)
    assert result.status != "verified"
    assert "team_unresolved" in result.reasons


def test_womens_basketball_side_is_not_merged_with_the_mens_side():
    kickoff = datetime(2026, 11, 4, 18, 0)
    men = _normalized(
        "basketball",
        "sportplus",
        {"home": "Alba Berlin", "away": "Panathinaikos", "league": "GRUPA C"},
        kickoff,
    )
    women = _normalized(
        "basketball",
        "mdshop",
        {"home": "Alba Berlin W", "away": "Panathinaikos W", "league": "Evrokup Ž"},
        kickoff,
    )
    result = CertaintyGate().evaluate_pair(men, women)
    assert result.status != "verified"
    assert "category_mismatch" in result.reasons


def test_same_provider_id_may_bridge_a_missing_womens_marker():
    kickoff = datetime(2026, 11, 4, 18, 0)
    men_like = _match("sportplus", "basketball", "Alba Berlin", "Panathinaikos", "GRUPA C", kickoff)
    women = _match("mdshop", "basketball", "Alba Berlin W", "Panathinaikos W", "Evrokup Ž", kickoff)
    men_like.betradar_id = women.betradar_id = "75214250"
    MatchMatcher().normalize_matches([men_like, women])
    result = CertaintyGate().evaluate_pair(men_like, women)
    assert result.status == "verified", result.reasons
