"""Tests for match page URLs and bet-slip prefill URL plumbing."""

from datetime import datetime

from config.settings import MATCH_URL_TEMPLATES
from engine.arbitrage import _collect_bet_urls, _collect_match_urls
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue


def _match(bookmaker, *, url="", bet_url=""):
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="BiH - Premier Liga",
        kickoff=datetime(2026, 8, 20, 18, 0),
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0),
            OddsValue(label="X", value=3.2),
            OddsValue(label="2", value=3.5),
        ])],
        url=url,
        bet_url=bet_url,
    )


def test_match_url_falls_back_to_template():
    group = MatchGroup(
        canonical_home="Sarajevo", canonical_away="Zeljeznicar",
        matches=[_match("mdshop")],
    )
    urls = _collect_match_urls(group)
    assert urls["mdshop"] == MATCH_URL_TEMPLATES["mdshop"]


def test_per_match_url_overrides_template():
    group = MatchGroup(
        canonical_home="Sarajevo", canonical_away="Zeljeznicar",
        matches=[_match("mdshop", url="https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=999")],
    )
    urls = _collect_match_urls(group)
    assert urls["mdshop"] == "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=999"


def test_bet_urls_collected_per_bookmaker():
    group = MatchGroup(
        canonical_home="Sarajevo", canonical_away="Zeljeznicar",
        matches=[
            _match("mdshop", bet_url="https://www.mdshop.ba/sport-prematch?sport=Fudbal&ticketItems=x"),
            _match("wwin"),  # no prefill support → empty value
        ],
    )
    urls = _collect_bet_urls(group)
    assert urls["mdshop"] == "https://www.mdshop.ba/sport-prematch?sport=Fudbal&ticketItems=x"
    assert urls["wwin"] == ""


def test_bet_urls_empty_when_unsupported():
    group = MatchGroup(
        canonical_home="Sarajevo", canonical_away="Zeljeznicar",
        matches=[_match("wwin")],
    )
    assert _collect_bet_urls(group) == {"wwin": ""}



def test_mdshop_parse_event_builds_event_deep_link():
    from scrapers.mdshop import MDShopScraper

    scraper = MDShopScraper()
    bets = [
        {
            "betTypeId": 135,
            "betOutcomes": [
                {"name": "1", "odd": 2.1},
                {"name": "X", "odd": 3.2},
                {"name": "2", "odd": 3.5},
            ],
        }
    ]
    match = scraper._parse_event(
        {"name": "Sarajevo - Zeljeznicar", "id": 111,
         "dateTime": "2026-08-15T18:00:00", "bets": bets},
        "football", set(),
    )
    assert match is not None
    assert match.url == "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=111"
    assert match.bet_url == ""


def test_mozzartbet_sport_page_url():
    from scrapers.mozzartbet import _event_to_match

    match = _event_to_match(
        {
            "id": 55,
            "startTime": 1_752_000_000_000,
            "home": "Sarajevo",
            "guest": "Zeljeznicar",
            "leagueName": "Premijer Liga BiH",
            "odds": [
                {"game": {"id": 1, "shortName": "ki"}, "subgame": {"name": "1"}, "value": 2.1},
                {"game": {"id": 1, "shortName": "ki"}, "subgame": {"name": "X"}, "value": 3.2},
                {"game": {"id": 1, "shortName": "ki"}, "subgame": {"name": "2"}, "value": 3.5},
            ],
        },
        set(),
    )
    assert match is not None
    assert match.url == "https://www.mozzartbet.ba/sr/kladjenje/sport/1"
