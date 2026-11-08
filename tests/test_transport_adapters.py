"""SR4-1: drive every HTTP adapter's ``scrape()`` through a fake transport.

WHAT THESE TESTS PROVE
----------------------
Until this module, the parser-contract suite (``test_market_fixtures.py``) fed
the captured ``bets``/``odds`` payloads straight to a parser, and the transport
suite (``test_transport.py``, ``test_retry.py``) exercised the shared client and
retry policy with synthetic callables.  Nothing joined the two, so a wrong URL,
a dropped query parameter, a missing page header or a JSON envelope the parser
no longer understands could pass every test.

Each case here re-inserts the *captured* payload into the response envelope the
adapter actually requests, serves it through ``respx`` and runs the real
``scrape()``.  The assertion is the same one the parser-contract suite makes:
the market families the capture declares are exactly the families the scrape
returns.  The error matrix then proves each adapter surfaces the shared
``ScrapeError`` kinds (SR2-1) instead of swallowing a failure and returning an
empty scan.

EVLBet is covered at the transport boundary only: its live flat-offer endpoint
was captured returning an empty list and no market fixture exists (declared in
``tests/test_market_fixtures.py::BOOKS_WITHOUT_FIXTURES``).  The test pins that
an empty feed is read as empty, not as an error; a payload test follows SR6-3.

WHAT THESE TESTS DO NOT PROVE
------------------------------
* They do not prove the capture is representative of the live feed; that is
  ``test_market_fixtures.py`` and the dated fixtures.
* They do not exercise a real socket.  ``tests/conftest.py`` blocks real
  network connections for the whole suite, and one test here proves the guard
  itself and that an unmocked request fails loudly.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from scrapers import errors
from scrapers.transport import POLICIES, policy_for

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "markets"

# Adapter classes are imported lazily inside the cases: engine/scrapers stay
# light at import time (AGENTS.md) and a syntax error in one adapter should not
# break collection of the whole module.
ADAPTER_CASES = (
    "mdshop",
    "mbet",
    "maxbet",
    "sportplus",
    "betole",
    "premier_kladionica",
)


def _capture(book: str, mode: str = "prematch") -> dict[str, Any]:
    """The trimmed live capture for one book and feed."""
    path = FIXTURE_DIR / f"{book}_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _scraper(book: str):
    """Instantiate the adapter by module path, keeping imports lazy."""
    from importlib import import_module

    modules = {
        "mdshop": ("scrapers.mdshop", "MDShopScraper"),
        "mbet": ("scrapers.mbet", "MBetScraper"),
        "maxbet": ("scrapers.maxbet", "MaxBetScraper"),
        "sportplus": ("scrapers.sportplus", "SportPlusScraper"),
        "betole": ("scrapers.betole", "BetoleScraper"),
        "premier_kladionica": (
            "scrapers.premier_kladionica",
            "PremierKladionicaScraper",
        ),
        "evlbet": ("scrapers.evlbet", "EvlbetScraper"),
    }
    module_name, class_name = modules[book]
    return getattr(import_module(module_name), class_name)()


# ---------------------------------------------------------------------------
# Response envelopes: the captured payload inside the shape the adapter asks for
# ---------------------------------------------------------------------------

def _mock_mdshop(mock: respx.MockRouter, capture: dict[str, Any]) -> respx.Route:
    body = {
        "events": [
            {
                "id": 6917979,
                "name": "Home FC - Away FC",
                "dateTime": "2030-01-01T18:00:00",
                "sportId": 1,
                "competitionName": "Test League",
                "regionName": "Test Region",
                "isInOffer": True,
                "bets": capture["bets"],
            }
        ]
    }
    return mock.get(
        url__startswith="https://mdoffer.mdshop.ba/api/offer/getwebevents"
    ).mock(return_value=httpx.Response(200, json=body))


def _mock_mbet(mock: respx.MockRouter, capture: dict[str, Any]) -> respx.Route:
    page = {
        "events": [
            {
                "id": "e:fb:test:0000",
                "id_sport": "fb",
                "competitors": [{"name": "Home FC"}, {"name": "Away FC"}],
                "utc_scheduled": "2030-01-01T18:00:00Z",
                "tournament": {"name": "Test League"},
                "odds": capture["bets"],
            }
        ]
    }

    def side_effect(request: httpx.Request) -> httpx.Response:
        # fetch_pages asks for four offsets at once; only offset 0 has data, so
        # the walk stops exactly as it does against the real short feed.
        if request.url.params.get("offset") == "0":
            return httpx.Response(200, json=page)
        return httpx.Response(200, json={"events": []})

    return mock.get(
        url__startswith="https://api.mbet.ba/events_cached"
    ).mock(side_effect=side_effect)


def _mock_maxbet(mock: respx.MockRouter, capture: dict[str, Any]) -> respx.Route:
    body = [
        {
            "id": 985993,
            "eventType": "Match",
            "antepost": False,
            "sportId": 1,
            "status": 1,
            "name": "Home FC v Away FC",
            "startDate": "2030-01-01T18:00:00",
            "leagueName": "Test League",
            "categoryName": "",
            "odds": capture["bets"],
            "externalIds": {},
        }
    ]
    return mock.get(
        url__startswith="https://sportsbook.maxbet.ba/sportsbook/rest/v2/matches"
    ).mock(return_value=httpx.Response(200, json=body))


def _mock_sportplus(mock: respx.MockRouter, capture: dict[str, Any]) -> respx.Route:
    body = {
        "matches": [
            {
                "id": 3308085,
                "sportName": "NOGOMET",
                "sportId": 1,
                "competitors": "Home FC - Away FC",
                "matchDate": "2030-01-01T18:00:00",
                "leagueName": "Test League",
                "countryName": "",
                "markets": capture["bets"],
                "betRadarId": None,
            }
        ]
    }
    return mock.get("https://www.sportplus.ba/api/v1/prematch/offer").mock(
        return_value=httpx.Response(200, json=body)
    )


def _mock_betole(mock: respx.MockRouter, capture: dict[str, Any]) -> respx.Route:
    event = {
        "id": 91393484,
        "matchCode": "91393484",
        "home": "San Carlos",
        "away": "Zeledon",
        "leagueName": "Test League",
        "kickOffTime": "2030-01-01T18:00:00Z",
        "live": False,
        "blocked": False,
        "brMatchId": "",
        "odds": {},
    }
    mock.get("https://www.betole.ba/restapi/offer/ba/sport/S/desk").mock(
        return_value=httpx.Response(200, json={"esMatches": [event]})
    )
    return mock.get(
        url__startswith="https://www.betole.ba/restapi/offer/ba/matches/by-ids"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 91393484, "odds": capture["bets"]}]
        )
    )


def _premier_sections(capture: dict[str, Any]) -> tuple[list, list]:
    """The full-sync and delta-sync section lists the capture fits into.

    PrSync is positional (see ``scrapers/premier_kladionica.py``): the event and
    its lookup rows live in sections 2/3/5/7/8/9 and the odds in section 12 of
    the delta response.  The capture stores exactly those rows.
    """
    lookup = capture["lookup"]
    kickoff_ms = int(datetime(2030, 1, 1, 18, tzinfo=UTC).timestamp() * 1000)
    dog_id = capture["bets"][0][0]
    full: list[list] = [[] for _ in range(16)]
    full[0] = [[0, 0, 0, 0, 1304349777]]
    full[2] = [[2, 0, "Fudbal"]]
    full[3] = [[10, 0, 2, 0, 0, "Test League"]]
    full[5] = [
        [
            dog_id,
            10,
            0,
            0,
            0,
            0,
            "",
            "Home FC",
            "Away FC",
            0,  # not blocked
            1,  # on offer
            None,
            None,
            kickoff_ms,
            0,
        ]
    ]
    full[7] = lookup["set_tip"]
    full[8] = lookup["set_tip_var"]
    full[9] = lookup["set_tip_tip"]
    delta: list[list] = [[] for _ in range(16)]
    delta[12] = capture["bets"]
    return full, delta


def _mock_premier(
    mock: respx.MockRouter, capture: dict[str, Any]
) -> respx.Route:
    full, delta = _premier_sections(capture)

    def side_effect(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)[0][2]
        sections = full if payload.get("dogadjajIDs") == "" else delta
        return httpx.Response(200, json=[sections])

    return mock.post(
        "https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx"
    ).mock(side_effect=side_effect)


ENVELOPES = {
    "mdshop": _mock_mdshop,
    "mbet": _mock_mbet,
    "maxbet": _mock_maxbet,
    "sportplus": _mock_sportplus,
    "betole": _mock_betole,
    "premier_kladionica": _mock_premier,
}

# The one URL each adapter must hit first, used by the error matrix.  Adapters
# that make a second call only reach it once the first succeeds, so the first
# response decides the whole scrape.
FIRST_REQUEST = {
    "mdshop": ("get", "https://mdoffer.mdshop.ba/api/offer/getwebevents"),
    "mbet": ("get", "https://api.mbet.ba/events_cached"),
    "maxbet": ("get", "https://sportsbook.maxbet.ba/sportsbook/rest/v2/matches"),
    "sportplus": ("get", "https://www.sportplus.ba/api/v1/prematch/offer"),
    "betole": ("get", "https://www.betole.ba/restapi/offer/ba/sport/S/desk"),
    "premier_kladionica": (
        "post",
        "https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx",
    ),
    "evlbet": (
        "get",
        "https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat",
    ),
}


# ---------------------------------------------------------------------------
# Happy path: capture -> real HTTP stack -> real scrape()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("book", ADAPTER_CASES)
def test_each_http_adapter_reads_its_capture_through_the_real_http_stack(book):
    """The captured payload must survive the adapter's own request path.

    The expectation is the fixture's own declaration (plus the families it
    marks experimental), so this test fails when an adapter stops requesting
    the endpoint, renames a query parameter, or changes the envelope key the
    parser reads.
    """
    capture = _capture(book)
    expected = set(capture["expected_markets"]) | set(
        capture.get("experimental_markets") or []
    )

    async def scenario() -> tuple[list, respx.Route]:
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            route = ENVELOPES[book](mock, capture)
            matches = await _scraper(book).scrape()
            return matches, route

    matches, route = asyncio.run(scenario())

    assert route.call_count > 0, f"{book}: the adapter never requested its feed"
    assert matches, f"{book}: the capture produced no matches"
    assert {match.bookmaker for match in matches} == {book}
    emitted = {
        market.market_type.value for match in matches for market in match.markets
    }
    assert emitted == expected, (
        f"{book}: scrape() emitted {sorted(emitted)} but the capture declares "
        f"{sorted(expected)}"
    )


def test_evlbet_reads_its_recorded_empty_feed_as_empty_not_error():
    """EVLBet's live flat offer answered with an empty list (SR6-3).

    No market capture exists for it, so this pins the recorded transport
    behaviour: a 200 with an empty ``Response`` yields no matches and no
    exception, which is what the scan's ``empty`` kind relies on.
    """

    async def scenario() -> tuple[list, respx.Route]:
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            route = mock.get(
                url__startswith=(
                    "https://sportapis.evlbet.com/SportsOfferApi/api/sport/"
                    "offer/v3/matches/flat"
                )
            ).mock(return_value=httpx.Response(200, json={"Response": []}))
            matches = await _scraper("evlbet").scrape()
            return matches, route

    matches, route = asyncio.run(scenario())

    assert route.call_count >= 1
    assert matches == []


# ---------------------------------------------------------------------------
# Error matrix: every adapter surfaces the shared kind, never an empty scan
# ---------------------------------------------------------------------------

def _install_quiet_policy(monkeypatch, book: str) -> None:
    """Replace the book's prematch policy with a zero-wait copy.

    The retry *policy* itself is covered by ``test_retry.py``; here the point is
    which kind reaches the caller, so zero jitter and no rate slot keep the
    matrix fast without changing any classification.
    """
    active = policy_for(book, "prematch")
    quiet = replace(active, retry_backoff_base=0.0, requests_per_second=None)
    monkeypatch.setitem(POLICIES, (book, "prematch"), quiet)


@pytest.mark.parametrize("book", FIRST_REQUEST)
@pytest.mark.parametrize(
    ("response", "expected_kind"),
    [
        (httpx.Response(403), errors.ScrapeKind.BLOCKED),
        (
            httpx.Response(429, headers={"Retry-After": "0"}),
            errors.ScrapeKind.RATE_LIMITED,
        ),
        (httpx.Response(503), errors.ScrapeKind.UPSTREAM_5XX),
        (httpx.ConnectTimeout("simulated timeout"), errors.ScrapeKind.TIMEOUT),
    ],
    ids=["403-blocked", "429-rate-limited", "503-upstream", "timeout"],
)
def test_each_adapter_surfaces_the_shared_failure_kind(
    book, response, expected_kind, monkeypatch
):
    """A refused feed raises ``ScrapeError`` with its SR2-1 kind.

    The adapter must not log an error and return an empty list: an empty scan
    result is indistinguishable from a book with no events, which is the
    fail-open behaviour SR2-1 exists to remove.
    """
    _install_quiet_policy(monkeypatch, book)

    method, url = FIRST_REQUEST[book]

    async def scenario() -> None:
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            route = getattr(mock, method)(url__startswith=url)
            if isinstance(response, BaseException):
                route.mock(side_effect=response)
            else:
                route.mock(return_value=response)
            with pytest.raises(errors.ScrapeError) as caught:
                await _scraper(book).scrape()
            assert caught.value.kind is expected_kind
            assert route.call_count >= 1

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# The suite itself never reaches the internet
# ---------------------------------------------------------------------------

def test_an_unmocked_request_fails_loudly():
    """respx refuses an unmocked host instead of letting it out."""

    async def scenario() -> None:
        with respx.mock(assert_all_mocked=True):
            async with httpx.AsyncClient(timeout=1.0) as client:
                with pytest.raises(respx.models.AllMockedAssertionError):
                    await client.get("https://example.org/not-mocked")

    asyncio.run(scenario())


def test_the_session_guard_blocks_a_real_socket():
    """The conftest guard is the second layer, for code that skips respx."""
    import socket

    with pytest.raises(AssertionError, match="real network"):
        socket.create_connection(("example.org", 443), timeout=0.1)

    # A local test server is not the traffic this guard is about: the opt-in
    # Chromium audit serves the dashboard from 127.0.0.1.
    assert socket.getaddrinfo("127.0.0.1", 0)[0][0] == socket.AF_INET
