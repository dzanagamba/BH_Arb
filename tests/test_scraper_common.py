"""Tests for shared scraper helpers."""

from datetime import datetime

from models.schemas import MarketType
from scrapers.common import normalize_outcome, parse_dt, parse_teams_from_name


def test_parse_dt_iso():
    dt = parse_dt("2026-08-15T18:00:00")
    assert dt == datetime(2026, 8, 15, 18, 0, 0)


def test_parse_dt_with_offset_converted_to_utc():
    dt = parse_dt("2026-08-15T18:00:00+02:00")
    assert dt == datetime(2026, 8, 15, 16, 0, 0)  # 18:00 +02:00 == 16:00 UTC


def test_parse_dt_zulu_suffix():
    dt = parse_dt("2026-08-15T18:00:00Z")
    assert dt == datetime(2026, 8, 15, 18, 0, 0)


def test_parse_dt_epoch_ms():
    dt = parse_dt(1_752_000_000_000)
    assert dt is not None
    assert dt.tzinfo is None  # naive UTC


def test_parse_dt_invalid():
    assert parse_dt("not-a-date") is None
    assert parse_dt(None) is None


def test_parse_teams_from_name():
    assert parse_teams_from_name("Sarajevo - Željezničar") == ("Sarajevo", "Željezničar")
    assert parse_teams_from_name("Sarajevo vs Željezničar") == ("Sarajevo", "Željezničar")
    assert parse_teams_from_name("") == ("", "")


def test_normalize_outcome_match_result():
    assert normalize_outcome("1", MarketType.MATCH_RESULT) == "1"
    assert normalize_outcome("neriješeno", MarketType.MATCH_RESULT) == "X"
    assert normalize_outcome("2", MarketType.MATCH_RESULT) == "2"


def test_normalize_outcome_over_under():
    assert normalize_outcome("više", MarketType.OVER_UNDER_2_5) == "Over 2.5"
    assert normalize_outcome("manje", MarketType.OVER_UNDER_2_5) == "Under 2.5"
    assert normalize_outcome("0-2", MarketType.OVER_UNDER_2_5) == "Under 2.5"


def test_normalize_outcome_btts_and_dc():
    assert normalize_outcome("gol-gol", MarketType.BTTS) == "GG"
    assert normalize_outcome("ng", MarketType.BTTS) == "NG"
    assert normalize_outcome("X2", MarketType.DOUBLE_CHANCE) == "X2"


def test_normalize_outcome_bosnian_home_away():
    assert normalize_outcome("Dom", MarketType.MATCH_RESULT) == "1"
    assert normalize_outcome("Gost", MarketType.MATCH_RESULT) == "2"


def test_mdshop_dedup_by_event_id():
    from scrapers.mdshop import MDShopScraper

    scraper = MDShopScraper()
    seen: set = set()
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
    ev1 = {"name": "Sarajevo - Zeljeznicar", "id": 111,
           "dateTime": "2026-08-15T18:00:00", "bets": bets}
    ev2 = {"name": "Sarajevo - Zeljeznicar", "id": 222,
           "dateTime": "2026-08-22T18:00:00", "bets": bets}

    # Same event ID twice → second occurrence must be dropped
    assert scraper._parse_event(ev1, "football", seen) is not None
    assert scraper._parse_event(ev1, "football", seen) is None
    # Same teams, different event ID (2nd meeting in the window) → kept
    assert scraper._parse_event(ev2, "football", seen) is not None
