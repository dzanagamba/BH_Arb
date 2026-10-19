"""POST /api/verify re-prices the exact bet a cached surebet was built on.

Each test builds the surebet with the real pipeline (matcher + engine), caches
it the way a scan does, and then serves "fresh" bookmaker data from fake
scrapers, so the endpoint is exercised end to end with no network.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import server.api as api
from engine.arbitrage import ArbitrageEngine
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue
from server.app import app

client = TestClient(app)
KICKOFF = (datetime.now(UTC) + timedelta(hours=3)).replace(tzinfo=None, second=0, microsecond=0)
LEAGUE = "Premijer Liga BiH"


def _match(bookmaker, home, away, markets, *, event_id="", verified=False):
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=LEAGUE,
        kickoff=KICKOFF,
        event_id=event_id,
        match_code=event_id,
        deep_link_verified=verified,
        markets=markets,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _x12(one, draw, two):
    return Market(market_type=MarketType.MATCH_RESULT, odds=[
        OddsValue(label="1", value=one),
        OddsValue(label="X", value=draw),
        OddsValue(label="2", value=two),
    ])


def _fh_ou(over, under):
    return Market(market_type=MarketType.FIRST_HALF_OU, odds=[
        OddsValue(label="Over 1.5", value=over),
        OddsValue(label="Under 1.5", value=under),
    ])


def _arb_books(first="mbet", second="sportplus", third="wwin"):
    """Three books whose best 1 / X / 2 legs form a ~5% arbitrage."""
    return [
        _match(first, "Zeljeznicar", "Sarajevo", [_x12(2.40, 3.00, 2.60)]),
        _match(second, "Zeljeznicar", "Sarajevo", [_x12(1.90, 3.90, 2.60)]),
        _match(third, "Zeljeznicar", "Sarajevo", [_x12(1.90, 3.00, 3.60)]),
    ]


class _FakeScraper:
    feeds: dict[str, list[Match]] = {}

    def __init__(self, book: str):
        self.book = book

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return [m.model_copy(deep=True) for m in self.feeds.get(self.book, [])]


@pytest.fixture
def harness(monkeypatch):
    feeds: dict[str, list[Match]] = {}
    for book in api.BOOKMAKERS:
        monkeypatch.setitem(api.SCRAPERS, book, lambda book=book: _FakeScraper(book))
        monkeypatch.setitem(api._bookmaker_enabled, book, True)
    monkeypatch.setattr(_FakeScraper, "feeds", feeds)
    saved_surebets = list(api.cached_surebets)
    saved_proofs = {mode: dict(v) for mode, v in api._deep_link_verifications.items()}
    api.cached_surebets.clear()
    api._deep_link_verifications.clear()
    yield feeds
    api.cached_surebets[:] = saved_surebets
    api._deep_link_verifications.clear()
    api._deep_link_verifications.update(saved_proofs)


def _cache_surebet(matches: list[Match], market: MarketType) -> dict:
    """Run the real pipeline over `matches` and cache its surebet for `market`."""
    groups = MatchMatcher().group_matches([m.model_copy(deep=True) for m in matches])
    surebets = ArbitrageEngine().find_surebets(groups, min_profit=0.0)
    found = [s for s in surebets if s.market_type == market]
    assert found, f"the fixture did not produce a {market.value} surebet"
    cached = found[0].model_dump(mode="json")
    api.cached_surebets.append(cached)
    return cached


def _verify(surebet_id: str) -> dict:
    response = client.post("/api/verify", json={"surebet_id": surebet_id, "mode": "prematch"})
    assert response.status_code == 200, response.text
    return response.json()


def test_unchanged_odds_are_still_an_arbitrage(harness):
    books = _arb_books()
    cached = _cache_surebet(books, MarketType.MATCH_RESULT)
    for match in books:
        harness[match.bookmaker] = [match]

    body = _verify(cached["id"])

    assert body["still_profitable"] is True
    assert body["current"]["profit_percent"] == cached["profit_percent"]
    assert not any(leg["changed"] for leg in body["drift"].values())


def test_a_moved_leg_is_reported_as_no_longer_profitable(harness):
    books = _arb_books()
    cached = _cache_surebet(books, MarketType.MATCH_RESULT)
    for match in books:
        harness[match.bookmaker] = [match]
    harness["sportplus"] = [_match("sportplus", "Zeljeznicar", "Sarajevo", [_x12(1.90, 3.00, 2.60)])]

    body = _verify(cached["id"])

    assert body["still_profitable"] is False
    assert body["drift"]["X"]["changed"] is True


def test_a_leg_on_a_proven_route_is_found_once_the_proof_is_applied(harness):
    """A book that declares a per-event route only verifies on a stored proof.

    The scan applies that proof before grouping; verify must too, or every
    surebet with such a leg reads "not found" no matter what the odds do.
    """
    books = _arb_books(first="mozzartbet")
    books[0] = books[0].model_copy(update={"event_id": "ev-1", "match_code": "ev-1"})
    proven = [books[0].model_copy(update={"deep_link_verified": True}), *books[1:]]
    cached = _cache_surebet(proven, MarketType.MATCH_RESULT)
    for match in books:  # scrapers always emit deep_link_verified=False
        harness[match.bookmaker] = [match]
    api._deep_link_verifications["prematch"] = {
        "mozzartbet|ev-1": {
            "verified": True,
            "checked_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "url": "https://www.mozzartbet.ba/x",
        }
    }

    body = _verify(cached["id"])

    assert body["still_profitable"] is True, body


def test_without_a_proof_the_route_book_leg_stays_unverified(harness):
    books = _arb_books(first="mozzartbet")
    books[0] = books[0].model_copy(update={"event_id": "ev-1", "match_code": "ev-1"})
    proven = [books[0].model_copy(update={"deep_link_verified": True}), *books[1:]]
    cached = _cache_surebet(proven, MarketType.MATCH_RESULT)
    for match in books:
        harness[match.bookmaker] = [match]

    body = _verify(cached["id"])

    # The unproven Mozzartbet listing cannot join the fixture, but SportPlus
    # and WWIN still verify with each other (the matcher tries the next-best
    # group when the gate refuses the best one). Verify then finds that
    # two-book group and re-prices without the Mozzartbet leg, so the answer
    # is False, or None if no group verifies — never a claim of profit.
    assert body["still_profitable"] is not True


def test_a_fixture_that_comes_back_reversed_is_priced_in_the_cached_frame(harness):
    books = _arb_books()
    cached = _cache_surebet(books, MarketType.MATCH_RESULT)
    # Every book now lists the fixture away-first, with 1 and 2 swapped to match.
    for match in books:
        one, draw, two = (o.value for o in match.markets[0].odds)
        harness[match.bookmaker] = [
            _match(match.bookmaker, "Sarajevo", "Zeljeznicar", [_x12(two, draw, one)])
        ]

    body = _verify(cached["id"])

    assert body["still_profitable"] is True
    for stake in cached["stakes"]:
        leg = body["drift"][stake["outcome_label"]]
        assert leg["new_odds"] == stake["odds"], (stake["outcome_label"], leg)
        assert leg["new_bookmaker"] == stake["bookmaker"]


def test_a_line_market_surebet_can_be_verified(harness):
    books = [
        _match("mbet", "Zeljeznicar", "Sarajevo", [_fh_ou(2.20, 1.60)]),
        _match("sportplus", "Zeljeznicar", "Sarajevo", [_fh_ou(1.70, 2.10)]),
    ]
    cached = _cache_surebet(books, MarketType.FIRST_HALF_OU)
    for match in books:
        harness[match.bookmaker] = [match]

    body = _verify(cached["id"])

    assert body["still_profitable"] is True, body
    assert set(body["drift"]) == {"Over 1.5", "Under 1.5"}


def test_a_dust_surebet_is_still_profitable_below_the_headline_threshold(harness):
    books = [
        _match("mbet", "Zeljeznicar", "Sarajevo", [_x12(2.01, 3.00, 2.60)]),
        _match("sportplus", "Zeljeznicar", "Sarajevo", [_x12(1.90, 4.00, 2.60)]),
        _match("wwin", "Zeljeznicar", "Sarajevo", [_x12(1.90, 3.00, 4.00)]),
    ]
    cached = _cache_surebet(books, MarketType.MATCH_RESULT)
    assert 0 < cached["profit_percent"] < api.MIN_PROFIT_PERCENT
    for match in books:
        harness[match.bookmaker] = [match]

    body = _verify(cached["id"])

    assert body["still_profitable"] is True
    assert body["meets_min_profit"] is False
