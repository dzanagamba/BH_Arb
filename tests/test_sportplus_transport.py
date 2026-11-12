"""SR8-5: a blank SportPlus body is a transport failure, not schema drift.

On 2026-11-12 the prematch scan lost SportPlus after two `httpx.ReadError`
attempts and a third `HTTP 200` whose body was only CRLF whitespace; the scan
reported it as `schema_drift` ("response is not JSON ... char 4"). These tests
run the adapter's own fetch path over a mock transport with the real transport
policy, so the attempt cap, the time budget and the rate limiter are the
production ones.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scrapers import sportplus
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.transport import transport_client

FIXTURE = Path(__file__).parent / "fixtures" / "markets" / "sportplus_prematch.json"
HTML_BODY = b"<html><body>maintenance</body></html>"


def _offer() -> bytes:
    """The real envelope shape: a JSON *string* holding the offer (doubled)."""
    markets = json.loads(FIXTURE.read_text(encoding="utf-8"))["bets"]
    envelope = {
        "matches": [
            {
                "id": 3308085,
                "sportName": "NOGOMET",
                "competitors": "FK Sarajevo - Zeljeznicar",
                "leagueName": "Premijer liga",
                "countryName": "Bosna i Hercegovina",
                "matchDate": "2026-11-20 18:00",
                "markets": markets,
            }
        ]
    }
    return json.dumps(envelope).encode()


class _Feed:
    """Answer with ``blanks`` empty bodies, then with ``body``."""

    def __init__(
        self, blanks: int, body: bytes | None = None, content_type: str = "application/json"
    ) -> None:
        self.blanks = blanks
        self.body = body if body is not None else _offer()
        self.content_type = content_type
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.blanks:
            # Exactly what the live endpoint sent: 200, JSON content type, CRLF.
            return httpx.Response(
                200,
                content=b"\r\n\r\n",
                headers={"content-type": "application/json; charset=utf-8"},
            )
        return httpx.Response(
            200,
            content=self.body,
            headers={"content-type": self.content_type},
        )


def _patch(monkeypatch, feed) -> None:
    """Keep the real transport policy, mock only the socket."""
    transport = httpx.MockTransport(feed)

    def factory(bookmaker: str, mode: str) -> Any:
        return transport_client(bookmaker, mode, transport=transport)

    monkeypatch.setattr(sportplus, "transport_client", factory)


def _scrape(live: bool = False):
    return asyncio.run(sportplus.SportPlusScraper().fetch_and_parse(live=live))


def test_a_blank_body_is_retried_and_the_next_offer_parses(monkeypatch):
    feed = _Feed(blanks=1)
    _patch(monkeypatch, feed)

    matches = _scrape()

    assert feed.calls == 2, "the blank 200 must spend an attempt, not the book"
    assert [match.home_team for match in matches] == ["FK Sarajevo"]
    assert matches[0].bookmaker == "sportplus"
    assert matches[0].markets, "the retried attempt's real markets are parsed"


def test_a_book_that_only_sends_blank_bodies_ends_as_transport(monkeypatch):
    feed = _Feed(blanks=99)
    _patch(monkeypatch, feed)

    with pytest.raises(ScrapeError) as caught:
        _scrape()

    assert caught.value.kind is ScrapeKind.TRANSPORT
    assert "empty body" in str(caught.value)
    assert feed.calls == 3, "the attempt cap is unchanged (3)"


def test_a_non_json_body_names_the_envelope(monkeypatch):
    feed = _Feed(blanks=0, body=HTML_BODY, content_type="text/html; charset=utf-8")
    _patch(monkeypatch, feed)

    with pytest.raises(ScrapeError) as caught:
        _scrape()

    message = str(caught.value)
    assert caught.value.kind is ScrapeKind.SCHEMA_DRIFT
    assert "HTTP 200" in message
    assert "text/html" in message
    assert f"{len(HTML_BODY)} bytes" in message
    assert "head=b'<html>" in message
    assert feed.calls == 1, "a non-JSON body is a real answer: one attempt"


def test_a_live_blank_body_is_retried_too(monkeypatch):
    feed = _Feed(blanks=1, body=json.dumps({"date": "", "sports": []}).encode())
    _patch(monkeypatch, feed)

    matches = _scrape(live=True)

    assert feed.calls == 2
    assert matches == []
