"""MaxBet: which events and odds reach the matcher, and in what shape.

Payload shapes are the ones the live /sportsbook/rest/v2/matches feed served on
2026-10-27 (see tests/fixtures/markets/maxbet_*.json for captured ones).
"""

from datetime import datetime

from models.schemas import MarketType
from scrapers.maxbet import MaxBetScraper, parse_maxbet_odds


def _outcome(outcome_id: str, label: str, value: float, status: int = 0) -> dict:
    return {"outcome": label, "outcomeId": outcome_id, "status": status,
            "oddValue": value, "marketAvailableForBetting": True}


def _total(line: str, over: float, under: float, over_status: int = 0) -> dict:
    return {"id": 17, "name": "Ukupno golova", "specifiers": {"total": line}, "outcomes": [
        _outcome("17002", "Manje {total}", under),
        _outcome("17001", "Više {total}", over, status=over_status),
    ]}


def _1x2(home: float = 2.1, draw: float = 3.3, away: float = 3.4) -> dict:
    return {"id": 1, "name": "Konačan ishod", "outcomes": [
        _outcome("1001", "1", home), _outcome("1002", "X", draw), _outcome("1003", "2", away),
    ]}


def _event(**overrides) -> dict:
    event = {
        "id": 914594,
        "name": "Bochum v Mainz",
        "startDate": "2026-10-27T17:00:00.000+0000",
        "status": 1,
        "eventType": "Match",
        "sportId": 1,
        "categoryName": "Germany",
        "leagueName": "Germany DFB Pokal",
        "competitors": [{"name": "Bochum"}, {"name": "Mainz"}],
        "odds": [_1x2(), _total("2.5", 1.8, 2.0)],
        "externalIds": {"betradarUnified": "sr:match:74374512", "shortCode": "10059"},
        "antepost": False,
    }
    event.update(overrides)
    return event


def test_totals_are_read_at_the_registered_lines_only():
    markets = parse_maxbet_odds(
        [_total("0.5", 1.02, 10.0), _total("2.5", 1.8, 2.0), _total("4.5", 5.5, 1.1)]
    )
    assert [(m.market_type, {o.label: o.value for o in m.odds}) for m in markets] == [
        (MarketType.OVER_UNDER_2_5, {"Over 2.5": 1.8, "Under 2.5": 2.0}),
    ]


def test_a_suspended_outcome_is_dropped_and_its_market_with_it():
    assert parse_maxbet_odds([_total("2.5", 1.8, 2.0, over_status=1)]) == []


def test_an_outcome_whose_text_contradicts_its_id_is_not_trusted():
    swapped = _1x2()
    swapped["outcomes"][0]["outcome"] = "2"
    assert parse_maxbet_odds([swapped]) == []


def test_parse_events_builds_a_match_with_identity_and_link_fields():
    [match] = MaxBetScraper().parse_events([_event()])
    assert (match.home_team, match.away_team) == ("Bochum", "Mainz")
    assert match.league == "Germany DFB Pokal"
    assert match.country == ""
    assert match.kickoff == datetime(2026, 10, 27, 17, 0)
    assert match.event_id == "914594"
    assert match.betradar_id == "74374512"
    assert match.url == "https://sportsbook.maxbet.ba/match/914594"
    assert match.deep_link_verified is False
    assert {m.market_type for m in match.markets} == {
        MarketType.MATCH_RESULT, MarketType.OVER_UNDER_2_5,
    }


def test_the_event_name_spelling_wins_over_abbreviated_competitors():
    [match] = MaxBetScraper().parse_events([_event(
        name="Boston River v Torque",
        competitors=[{"name": "Boston River"}, {"name": "Montevideo C."}],
    )])
    assert match.away_team == "Torque"


def test_competitors_are_used_when_the_name_cannot_be_split():
    [match] = MaxBetScraper().parse_events([_event(name="Bochum vs Mainz")])
    assert (match.home_team, match.away_team) == ("Bochum", "Mainz")


def test_league_gains_the_country_when_it_lacks_it():
    [match] = MaxBetScraper().parse_events([_event(leagueName="Cup", categoryName="Paraguay")])
    assert match.league == "Paraguay - Cup"


def test_outrights_live_games_and_other_sports_are_not_prematch_listings():
    events = [
        _event(id=1, eventType="Tournament"),
        _event(id=2, status=3),
        _event(id=3, sportId=2),
        _event(id=4, antepost=True),
        _event(id=5, odds=[]),
        _event(id=6),
        _event(id=6),
    ]
    assert [m.event_id for m in MaxBetScraper().parse_events(events)] == ["6"]
    assert [m.event_id for m in MaxBetScraper().parse_events(events, live=True)] == ["2"]
