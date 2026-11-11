"""Tests for the scraped match-page URL each parser builds."""


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
