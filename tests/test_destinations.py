"""Destination coverage: URL construction, the honest ladder, and proof gating.

The record in ``config/bookmaker_destinations.json`` is the only thing that may
call a link a ticket or a match page. These tests build destinations from that
record and from deliberately broken copies of it, so a label that is not backed
by a recorded spot check fails here rather than on the dashboard.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime

import pytest

from config.settings import BOOKMAKERS
from engine.destinations import (
    LADDER,
    build_destination,
    clear_cache,
    coverage_gaps,
    selection_line,
)
from models.schemas import (
    LegDestination,
    Market,
    MarketType,
    Match,
    MatchGroup,
    OddsValue,
    Surebet,
    SurebetStake,
)

REAL_CONFIG = "config/bookmaker_destinations.json"
ENABLED_FOOTBALL = set(BOOKMAKERS) - {"evlbet"}


@pytest.fixture(autouse=True)
def _fresh_config():
    clear_cache()
    yield
    clear_cache()


def _config() -> dict:
    with open(REAL_CONFIG, encoding="utf-8") as file:
        return json.load(file)


def _nsoft_match(
    bookmaker: str = "mdshop",
    event_id: str = "6971587",
    *,
    with_ticket_ids: bool = True,
) -> Match:
    context = {
        "sport_id": "1",
        "region_id": "104",
        "competition_id": "764",
        "region_name": "Međunarodne klupske",
        "competition_name": "Liga šampiona",
        "event_name": "Shakhtar Donetsk - Sporting",
    }
    market_context = dict(context)
    market_context["event_id"] = event_id
    if with_ticket_ids:
        market_context["bet_id"] = "633141222"
    market = Market(
        market_type=MarketType.MATCH_RESULT,
        odds=[
            OddsValue(label="1", value=3.42),
            OddsValue(label="X", value=3.69),
            OddsValue(label="2", value=2.10),
        ],
        source_id="135",
        source_context=market_context,
        outcome_ids={"1": "1990033033", "X": "1990033034", "2": "1990033035"},
    )
    return Match(
        bookmaker=bookmaker,
        home_team="Shakhtar Donetsk",
        away_team="Sporting",
        league="Liga šampiona",
        kickoff=datetime(2026, 11, 3, 17, 45),
        event_id=event_id,
        match_code=event_id,
        source_context=context,
        markets=[market],
    )


def _maxbet_match(*, with_outcome_ids: bool = True) -> Match:
    """The 2026-11-11 MaxBet fixture, with the row ids its feed carries."""
    from scrapers.maxbet import parse_maxbet_odds

    outcomes = [
        {"outcome": label, "outcomeId": type_id, "status": 0, "oddValue": value,
         "marketAvailableForBetting": True}
        for label, type_id, value in (("1", "1001", 1.55), ("X", "1002", 3.90), ("2", "1003", 4.80))
    ]
    if with_outcome_ids:
        for row, row_id in zip(outcomes, (147294305, 147294306, 147294307), strict=True):
            row["id"] = row_id
    return Match(
        bookmaker="maxbet",
        home_team="CD Universitario",
        away_team="Herrera FC",
        league="Panama 1",
        event_id="1027619",
        markets=parse_maxbet_odds([{"id": 1, "name": "Konačan ishod", "outcomes": outcomes}]),
    )


def _stake(label: str = "1", bookmaker: str = "mdshop") -> SurebetStake:
    return SurebetStake(
        bookmaker=bookmaker,
        outcome_label=label,
        odds=3.42,
        stake=10.0,
        potential_return=34.2,
    )


def _destination(match: Match, stake: SurebetStake, market_type=MarketType.MATCH_RESULT):
    return build_destination(match, stake, market_type, mode="prematch")


# ─── The dated coverage record ───────────────────────────────────────────────


def test_coverage_names_every_enabled_football_book_and_excludes_evlbet():
    config = _config()
    assert set(config["books"]) == ENABLED_FOOTBALL
    assert "evlbet" not in config["books"]
    for book, spec in config["books"].items():
        assert set(spec["modes"]) == {"prematch", "live"}, book
        assert spec["modes"]["prematch"]["routes"], book
        assert spec["modes"]["live"]["routes"], book


def test_every_route_carries_a_dated_proof_or_recorded_attempts():
    config = _config()
    for book, spec in config["books"].items():
        for mode, mode_spec in spec["modes"].items():
            for route in mode_spec["routes"]:
                proof = route.get("proof")
                assert isinstance(proof, dict), f"{book}/{mode}/{route['kind']} has no proof"
                # Dated ISO check, never older than the first coverage record
                # (2026-11-03); SR9-1 re-checks move it forward.
                checked_at = str(proof.get("checked_at") or "")
                assert len(checked_at) == 10 and checked_at >= "2026-11-03", (
                    f"{book}/{mode}/{route['kind']} has no dated check"
                )
                date.fromisoformat(checked_at)
                assert proof.get("result") in {"confirmed", "failed", "unavailable"}
                if proof.get("result") == "failed":
                    assert route.get("attempts"), (
                        f"{book}/{mode}/{route['kind']} failed without recording attempts"
                    )


def test_coverage_has_no_route_gaps():
    assert coverage_gaps(_config()) == []


def test_the_coverage_record_stores_no_credentials():
    forbidden = {"password", "passwd", "token", "cookie", "cookies", "secret", "api_key", "username"}

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key.lower() not in forbidden, f"{path}.{key} looks like a credential"
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(_config())


# ─── URL construction ────────────────────────────────────────────────────────


def test_nsoft_ticket_url_is_built_from_the_parser_ids():
    destination = _destination(_nsoft_match(), _stake())
    assert destination.kind == "ticket_filled"
    assert "ticketItems=%5B%5B1%2C104%2C764%2C6971587%2C633141222%2C1990033033%5D%5D" in destination.url
    assert destination.identifier_source == "nsoft_ticket_items"
    assert destination.selection == "1"


def test_nsoft_parser_carries_the_ids_the_ticket_url_needs():
    from scrapers.common import parse_nsoft_bets

    bets = [
        {
            "id": 633141222,
            "betTypeId": 135,
            "isPlayable": True,
            "isInOffer": True,
            "betOutcomes": [
                {"id": 1990033033, "name": "1", "odd": 3.42, "isPlayable": True, "isInOffer": True},
                {"id": 1990033034, "name": "X", "odd": 3.69, "isPlayable": True, "isInOffer": True},
                {"id": 1990033035, "name": "2", "odd": 2.10, "isPlayable": True, "isInOffer": True},
            ],
        }
    ]
    markets = parse_nsoft_bets(
        bets,
        bookmaker="mdshop",
        mode="prematch",
        source_context={
            "sport_id": "1",
            "region_id": "104",
            "competition_id": "764",
            "event_id": "6971587",
        },
    )
    assert len(markets) == 1
    market = markets[0]
    assert market.source_context["bet_id"] == "633141222"
    assert market.outcome_ids == {
        "1": "1990033033",
        "X": "1990033034",
        "2": "1990033035",
    }


def test_cross_market_double_chance_can_still_fill_the_1x2_leg():
    match = _nsoft_match()
    stake = _stake("1")
    destination = build_destination(
        match, stake, MarketType.DOUBLE_CHANCE, mode="prematch"
    )
    assert destination.kind == "ticket_filled"
    assert destination.market == "1X2 + DC"
    assert "ticketItems" in destination.url


def test_nsoft_ticket_without_the_bet_id_falls_to_the_match_page():
    match = _nsoft_match(with_ticket_ids=False)
    destination = _destination(match, _stake())
    assert destination.kind == "match_page"
    assert "ticketItems" not in destination.url
    assert "event=6971587" in destination.url
    assert destination.fallback_reason


def test_match_page_url_uses_the_event_id_and_book_context():
    match = _nsoft_match()
    config = _config()
    # Remove the ticket route so the match page is the best rung.
    config["books"]["mdshop"]["modes"]["prematch"]["routes"] = [
        route
        for route in config["books"]["mdshop"]["modes"]["prematch"]["routes"]
        if route["kind"] != "ticket_filled"
    ]
    destination = build_destination(
        match, _stake(), MarketType.MATCH_RESULT, coverage=config
    )
    assert destination.kind == "match_page"
    assert "event=6971587" in destination.url
    assert "competitionId=1-104-764" in destination.url


def test_mozzartbet_match_page_is_per_event():
    match = Match(
        bookmaker="mozzartbet",
        home_team="Shakhtar",
        away_team="Sporting",
        event_id="10088115",
    )
    destination = _destination(match, _stake(bookmaker="mozzartbet"))
    assert destination.kind == "match_page"
    assert destination.url == (
        "https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/10088115"
    )


def test_wwin_prematch_match_page_is_confirmed_by_the_operator():
    """SR9-1: the operator's browser opened #/top-bets/match/<id> (panel shows a shell)."""
    match = Match(bookmaker="wwin", home_team="America MG", away_team="Avai SC", event_id="4730200")
    destination = _destination(match, _stake(bookmaker="wwin"))
    assert destination.kind == "match_page"
    assert destination.url == "https://wwin.ba/kladjenje/#/top-bets/match/4730200"


def test_wwin_live_match_page_is_confirmed_by_the_operator():
    """SR9-2: the operator opened #/match/<live id> (the panel shows a shell)."""
    match = Match(
        bookmaker="wwin",
        home_team="Z.Podbrezova",
        away_team="Z.Moravce",
        event_id="4732588",
    )
    destination = build_destination(
        match, _stake(bookmaker="wwin"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.kind == "match_page"
    assert destination.url == "https://wwin.ba/kladjenje-uzivo/#/match/4732588"
    assert destination.proof_checked_at == "2026-11-11"


@pytest.mark.parametrize("mode", ["prematch", "live"])
def test_maxbet_match_page_uses_the_site_shell_path(mode):
    """SR9-1: /ba/sportsbook/match/<id> opens the fixture; the old hosts do not."""
    match = Match(
        bookmaker="maxbet", home_team="America MG", away_team="Avai", event_id="1024788"
    )
    destination = build_destination(
        match, _stake(bookmaker="maxbet"), MarketType.MATCH_RESULT, mode=mode
    )
    assert destination.kind == "match_page"
    assert destination.url == "https://www.maxbet.ba/ba/sportsbook/match/1024788"
    assert destination.proof_checked_at == "2026-11-11"


def test_maxbet_ticket_url_carries_the_outcome_row_id():
    """SR9-2: ?outcome=<outcomes[].id> put the leg's selection on MaxBet's slip."""
    destination = _destination(_maxbet_match(), _stake("1", "maxbet"))
    assert destination.kind == "ticket_filled"
    assert destination.url == (
        "https://www.maxbet.ba/ba/sportsbook/match/1027619?outcome=147294305"
    )
    assert destination.identifier == "1027619"
    assert destination.identifier_source == "event_id"
    assert destination.selection == "1"
    assert destination.ticket_stake_supported is False


def test_maxbet_ticket_without_the_outcome_row_id_falls_to_the_match_page():
    destination = _destination(_maxbet_match(with_outcome_ids=False), _stake("1", "maxbet"))
    assert destination.kind == "match_page"
    assert destination.url == "https://www.maxbet.ba/ba/sportsbook/match/1027619"
    assert "outcome=" not in destination.url
    assert destination.fallback_reason == "ticket parameters missing"


def test_maxbet_live_ticket_uses_the_live_row_id():
    """SR9-2: the live list response carries the same per-row id."""
    destination = build_destination(
        _maxbet_match(), _stake("1", "maxbet"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.kind == "ticket_filled"
    assert destination.url == (
        "https://www.maxbet.ba/ba/sportsbook/match/1027619?outcome=147294305"
    )
    assert destination.proof_checked_at == "2026-11-11"


def test_mbet_live_uses_the_live_query_route():
    """SR9-1: single-live?id= is a 404 now; the site navigates to /live?id=."""
    match = Match(
        bookmaker="mbet",
        home_team="Czech Republic U19",
        away_team="Netherlands U19",
        event_id="e:fb:cze-net:0001",
    )
    destination = build_destination(
        match, _stake(bookmaker="mbet"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.kind == "match_page"
    assert destination.url == "https://mbet.ba/live?id=e:fb:cze-net:0001"
    assert "single-live" not in destination.url


def test_mozzartbet_live_never_links_the_prematch_id_as_a_live_match():
    """SR9-1: the adapter's live rows carry the prematch id, which the live page cannot open."""
    match = Match(
        bookmaker="mozzartbet",
        home_team="Italy U19",
        away_team="Romania U19",
        event_id="10108850",
    )
    destination = build_destination(
        match, _stake(bookmaker="mozzartbet"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.kind == "competition"
    assert "10108850" not in (destination.url or "")


def test_sportplus_live_fallback_is_the_live_betting_page():
    match = Match(bookmaker="sportplus", home_team="Češka", away_team="Nizozemska", event_id="74723528")
    destination = build_destination(
        match, _stake(bookmaker="sportplus"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.url == "https://www.sportplus.ba/live/betting"


def test_betole_prematch_uses_the_desk_event_id_not_the_match_code():
    match = Match(
        bookmaker="betole",
        home_team="Sporting CP",
        away_team="Moreirense",
        event_id="91367737",
        match_code="493",
    )
    destination = _destination(match, _stake(bookmaker="betole"))
    assert destination.kind == "match_page"
    assert destination.url == "https://www.betole.ba/match-special/91367737"


def test_betole_live_failed_route_falls_to_competition():
    match = Match(
        bookmaker="betole",
        home_team="Shakhtar Donetsk",
        away_team="Sporting CP",
        event_id="91367387",
        match_code="116",
    )
    destination = build_destination(
        match, _stake(bookmaker="betole"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.kind == "search"
    assert destination.url == ""
    assert destination.search_text
    assert "ticket" not in destination.label.lower()
    assert "live-special" not in destination.url


def test_selection_line_is_extracted_for_line_markets():
    assert selection_line("Over 2.5") == "2.5"
    assert selection_line("Under 1.5") == "1.5"
    assert selection_line("1 -0.5") == "-0.5"
    assert selection_line("2 +1") == "+1"
    assert selection_line("X") == ""


# ─── Proof-gated labelling ──────────────────────────────────────────────────


def test_ticket_filled_requires_a_confirmed_populated_ticket():
    config = _config()
    for route in config["books"]["mdshop"]["modes"]["prematch"]["routes"]:
        if route["kind"] == "ticket_filled":
            route["proof"]["ticket_confirmed"] = False
            route["proof"]["result"] = "confirmed"
    destination = build_destination(
        _nsoft_match(), _stake(), MarketType.MATCH_RESULT, coverage=config
    )
    assert destination.kind != "ticket_filled"
    assert "ticket" not in destination.label.lower() or "set stake" not in destination.label.lower()
    assert destination.fallback_reason


def test_a_match_page_without_fixture_proof_is_not_labelled_match_page():
    config = _config()
    for route in config["books"]["mozzartbet"]["modes"]["prematch"]["routes"]:
        if route["kind"] == "match_page":
            route["proof"]["fixture_confirmed"] = False
            route["proof"]["result"] = "failed"
            route["attempts"] = [{"checked_at": "2026-11-03", "result": "failed"}]
    match = Match(
        bookmaker="mozzartbet",
        home_team="Shakhtar",
        away_team="Sporting",
        event_id="10088115",
    )
    destination = build_destination(
        match, _stake(bookmaker="mozzartbet"), MarketType.MATCH_RESULT, coverage=config
    )
    assert destination.kind == "competition"
    assert destination.search_text
    assert "match" not in destination.label.lower()
    assert "match/10088115" not in destination.url


def test_a_failed_ticket_route_never_fabricates_a_ticket_url():
    config = _config()
    for route in config["books"]["mdshop"]["modes"]["prematch"]["routes"]:
        if route["kind"] == "ticket_filled":
            route["proof"]["result"] = "failed"
            route["proof"]["ticket_confirmed"] = False
            route["attempts"] = [{"checked_at": "2026-11-03", "result": "failed"}]
    destination = build_destination(
        _nsoft_match(), _stake(), MarketType.MATCH_RESULT, coverage=config
    )
    assert destination.kind != "ticket_filled"
    assert "ticketItems" not in destination.url
    assert "ticket" not in destination.label.lower()


def test_missing_identifier_falls_back_visibly_instead_of_fabricating_a_url():
    match = Match(
        bookmaker="mozzartbet",
        home_team="Shakhtar",
        away_team="Sporting",
        event_id="",
    )
    destination = _destination(match, _stake(bookmaker="mozzartbet"))
    assert destination.kind in {"search", "competition"}
    assert "match/100" not in destination.url
    assert destination.label


def _sportplus_match(*, with_ids: bool = True) -> Match:
    context = {}
    if with_ids:
        context = {
            "sportplus_match_id": "3314715",
            "sportplus_sport_id": "29",
            "sportplus_match_date": "2026-11-03T18:45:00",
            "sportplus_market_code": "6450000202",
            "sportplus_market_id": "1",
            "sportplus_odd_aliases": '{"1": "1"}',
        }
    market = Market(
        market_type=MarketType.MATCH_RESULT,
        odds=[
            OddsValue(label="1", value=1.6),
            OddsValue(label="X", value=4.1),
            OddsValue(label="2", value=5.0),
        ],
        source_id="1",
        source_context=context,
    )
    return Match(
        bookmaker="sportplus",
        home_team="Shakhtar",
        away_team="Sporting L.",
        event_id="3314715",
        match_code="3314715",
        markets=[market],
    )


def test_sportplus_ticket_script_uses_the_parser_ids_and_planned_stake():
    match = _sportplus_match()
    stake = _stake("1", bookmaker="sportplus")
    stake.stake = 10.0
    destination = build_destination(
        match, stake, MarketType.MATCH_RESULT, mode="prematch"
    )
    assert destination.kind == "competition"
    assert destination.url == "https://www.sportplus.ba/prematch/betting"
    assert destination.ticket_script
    assert "localStorage.setItem('cn-prematch.ticket'" in destination.ticket_script
    assert "typeof data==='string'" in destination.ticket_script
    assert "'<string[^>]*>'" in destination.ticket_script or "<string[^>]*>" in destination.ticket_script
    assert '"3314715"' in destination.ticket_script
    assert '"6450000202"' in destination.ticket_script
    assert '"1"' in destination.ticket_script
    assert "stake:10.0" in destination.ticket_script
    assert "manual, not a link" in destination.ticket_script_label
    assert destination.kind != "ticket_filled"


def test_sportplus_ticket_script_is_prematch_only():
    match = _sportplus_match()
    destination = build_destination(
        match, _stake("1", bookmaker="sportplus"), MarketType.MATCH_RESULT, mode="live"
    )
    assert destination.kind == "competition"
    assert destination.ticket_script == ""


def test_sportplus_ticket_script_is_absent_without_the_ids():
    match = _sportplus_match(with_ids=False)
    destination = build_destination(
        match, _stake("1", bookmaker="sportplus"), MarketType.MATCH_RESULT
    )
    assert destination.kind == "competition"
    assert destination.ticket_script == ""


def test_sportplus_parser_carries_the_market_code_and_alias():
    from scrapers.sportplus import SportPlusScraper

    markets = SportPlusScraper()._parse_markets(
        [
            {
                "id": 1,
                "code": "6450000202",
                "name": "NOGOMET",
                "odds": [
                    {"alias": "1", "value": 1.6},
                    {"alias": "X", "value": 4.1},
                    {"alias": "2", "value": 5.0},
                    {"alias": "1X", "value": 1.15},
                    {"alias": "X2", "value": 2.05},
                    {"alias": "12", "value": 1.2},
                ],
            }
        ]
    )
    one_x_two = next(m for m in markets if m.market_type == MarketType.MATCH_RESULT)
    assert one_x_two.source_context["sportplus_market_code"] == "6450000202"
    assert json.loads(one_x_two.source_context["sportplus_odd_aliases"])["1"] == "1"


def test_search_fallback_uses_the_books_own_spelling():
    match = Match(
        bookmaker="sportplus",
        home_team="Shakhtar",
        away_team="Sporting L.",
        home_team_source="Shakhtar",
        away_team_source="Sporting L.",
        event_id="3314715",
    )
    destination = _destination(match, _stake(bookmaker="sportplus"))
    assert destination.kind in {"search", "competition"}
    assert "Shakhtar" in destination.search_text
    assert "Sporting L." in destination.search_text


# ─── Safety: no gate side effects ───────────────────────────────────────────


def test_building_a_destination_never_sets_deep_link_verified():
    match = _nsoft_match()
    assert match.deep_link_verified is False
    _destination(match, _stake())
    assert match.deep_link_verified is False


def test_attach_destinations_covers_every_stake_without_touching_group_status():
    match = _nsoft_match()
    group = MatchGroup(
        canonical_home="Shakhtar Donetsk",
        canonical_away="Sporting",
        matches=[match],
        status="verified",
    )
    surebet = Surebet(
        id="abc12345",
        home_team="Shakhtar Donetsk",
        away_team="Sporting",
        market_type=MarketType.MATCH_RESULT,
        profit_percent=1.0,
        total_margin=0.99,
        stakes=[
            SurebetStake(
                bookmaker="mdshop",
                outcome_label="1",
                odds=3.42,
                stake=10.0,
                potential_return=34.2,
            )
        ],
        found_at=datetime(2026, 11, 3, 13, 0),
    )
    from engine.destinations import attach_destinations

    assert attach_destinations(surebet, group) == 1
    assert isinstance(surebet.stakes[0].destination, LegDestination)
    assert surebet.stakes[0].destination.kind == "ticket_filled"
    assert group.status == "verified"
    assert match.deep_link_verified is False


def test_a_destination_cannot_price_an_unverified_group():
    from engine.arbitrage import ArbitrageEngine

    match = _nsoft_match()
    group = MatchGroup(
        canonical_home="Shakhtar Donetsk",
        canonical_away="Sporting",
        matches=[match],
        status="suggested",
    )
    assert ArbitrageEngine().find_surebets([group], min_profit=0.0) == []


def test_the_ladder_is_the_documented_order():
    assert LADDER == ("ticket_filled", "match_page", "search", "competition")


def test_a_ticket_route_is_preferred_over_a_match_page():
    config = copy.deepcopy(_config())
    match = _nsoft_match()
    destination = build_destination(
        match, _stake(), MarketType.MATCH_RESULT, coverage=config
    )
    assert destination.kind == "ticket_filled"


def test_the_dashboard_reads_the_destination_not_the_legacy_url_maps():
    with open("frontend/js/app.js", encoding="utf-8") as file:
        js = file.read()
    assert "const dest = leg.destination || {}" in js
    assert "dest.label" in js
    assert "dest.ticket_script" in js
    assert "escapeHtml(safeUrl(url))" in js
    assert "(sb.bet_urls && sb.bet_urls[leg.bookmaker]) ||" not in js


def test_the_real_config_can_build_a_destination_for_every_enabled_book():
    for book in sorted(ENABLED_FOOTBALL):
        match = Match(
            bookmaker=book,
            home_team="Home",
            away_team="Away",
            event_id="12345",
            match_code="12345",
        )
        destination = _destination(match, _stake(bookmaker=book))
        assert destination.kind in {"ticket_filled", "match_page", "search", "competition"}
        assert destination.label
