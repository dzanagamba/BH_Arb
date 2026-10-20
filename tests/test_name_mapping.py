"""Book naming schemes: qualified league names, Betradar ids, unmapped leagues."""

import sys
from datetime import datetime
from pathlib import Path

from engine.matcher import MatchMatcher
from engine.normalizer import TeamNormalizer
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.admiralbet import _league_name
from scrapers.common import betradar_id, qualify_league
from scrapers.wwin import _country, _remember_countries

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from derive_mappings import side_markers  # noqa: E402

K = datetime(2026, 10, 20, 19, 0)


def _m(bookmaker, home, away, league, event_id):
    return Match(
        bookmaker=bookmaker, home_team=home, away_team=away, league=league,
        kickoff=K, event_id=event_id, deep_link_verified=True,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0),
            OddsValue(label="2", value=3.5),
        ])],
    )


def test_league_is_qualified_by_country_unless_it_carries_it():
    assert qualify_league("Serija A", "Brazil") == "Brazil - Serija A"
    assert qualify_league("Engleska 1", "Engleska") == "Engleska 1"
    assert qualify_league("CHAMPIONSHIP", "ENGLESKA") == "ENGLESKA - CHAMPIONSHIP"
    assert qualify_league("", "Iran") == "Iran"
    assert qualify_league("MLS", "-") == "MLS"


def test_admiralbet_names_the_country_the_feed_sends_separately():
    assert _league_name({"competitionName": "Serija A", "regionName": "Italija"}) == (
        "Italija - Serija A"
    )
    assert _league_name({"competitionName": "Serija A", "regionName": "Brazil"}) == (
        "Brazil - Serija A"
    )


def test_wwin_country_comes_from_the_categories_list():
    countries: dict = {}
    _remember_countries({"categories": [{"id": 163, "cname": "Indonezija"}]}, countries)
    assert _country({"idc": 163}, countries) == "Indonezija"
    assert _country({"idc": 999}, countries) == ""


def test_betradar_id_reads_both_spellings():
    assert betradar_id("74235704") == "74235704"
    assert betradar_id(None, "sr:match:72221350") == "72221350"
    assert betradar_id("sr:season:140756") == ""
    assert betradar_id(0, "") == ""


def test_afc_competition_is_not_cleaned_into_uefa_one():
    normalizer = TeamNormalizer()
    assert normalizer.normalize_league("AFC Champions League") != (
        normalizer.normalize_league("UEFA Champions League")
    )


def test_a_near_miss_league_name_is_not_guessed():
    # "Liga Prvaka" once fuzzed to Slovenia's "Prva Liga" at a score of 90.
    assert TeamNormalizer().normalize_league("Xyz Liga Prvaka Q") == "xyz liga prvaka q"


def test_unmapped_league_listing_joins_the_group_of_its_exact_fixture():
    mapped_a = _m("mdshop", "Porto", "PSV", "Liga šampiona", "1")
    mapped_b = _m("mbet", "Porto", "PSV", "UEFA Champions League", "2")
    unmapped = _m("sportplus", "Porto", "PSV", "Nepoznata Liga Prvaka", "3")
    groups = MatchMatcher().group_matches([unmapped, mapped_a, mapped_b])
    assert len(groups) == 1
    assert {m.bookmaker for m in groups[0].matches} == {"mdshop", "mbet", "sportplus"}


def test_alias_side_markers_separate_first_teams_from_youth_and_reserves():
    assert side_markers("Barcelona") != side_markers("Barcelona U19")
    assert side_markers("Barcelona") != side_markers("Barcelona/19")
    assert side_markers("Roma") != side_markers("ML/Roma")
    assert side_markers("Rapid [B]") == side_markers("Rapid II")
    assert side_markers("Burton A") == side_markers("Burton")
