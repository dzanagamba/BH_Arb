"""SR4-8: the committed HAR fixtures are scrubbed, trimmed and described.

WHAT THESE TESTS PROVE
----------------------
Every browser book has a committed ``tests/fixtures/har/<book>.har.gz`` plus a
sidecar, the file carries only the page document and that book's API calls,
**no entry carries a `cookie`/`authorization` header and the HAR's cookie jar is
empty**, and the trimming/scrubbing functions behave on synthetic input (so a
new capture cannot ship credentials). They run in the normal suite: no browser
and no network.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not replay anything. ``tests/test_browser_har_replay.py`` (opt-in,
``BH_ARB_TEST_BROWSER=1``) runs the real ``scrape()`` from these files, and
their asserted output is the sidecar's recorded ``replay`` block.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from config.bookmakers import BROWSER_BOOKMAKERS
from scrapers import har_fixtures

BOOKS = sorted(BROWSER_BOOKMAKERS)


def _entry(
    url: str,
    *,
    status: int = 200,
    content_type: str = "application/json",
    request_headers: list[dict[str, str]] | None = None,
    response_headers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "request": {
            "method": "GET",
            "url": url,
            "headers": request_headers
            or [
                {"name": "Accept", "value": "application/json"},
                {"name": "Cookie", "value": "session=abc123"},
            ],
        },
        "response": {
            "status": status,
            "headers": response_headers
            or [
                {"name": "content-type", "value": content_type},
                {"name": "set-cookie", "value": "cf_clearance=xyz"},
            ],
            "content": {"mimeType": content_type, "text": '{"ok": true}'},
        },
    }


def _har(*entries: dict[str, Any]) -> dict[str, Any]:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "Playwright", "version": "1.64.1"},
            "pages": [{"startedDateTime": "2026-11-08T17:30:00Z"}],
            "entries": list(entries),
            "cookies": [{"name": "session", "value": "abc123"}],
        }
    }


def test_every_browser_book_commits_a_scrubbed_har():
    assert BOOKS == ["admiralbet", "mozzartbet", "wwin"]

    for book in BOOKS:
        path = har_fixtures.har_path(book)
        assert path.is_file(), book
        har = har_fixtures.loads(path)
        entries = har["log"]["entries"]
        assert entries, book
        prefixes = har_fixtures.REPLAY_PREFIXES[book]
        for entry in entries:
            url = entry["request"]["url"]
            assert url.startswith(prefixes) or har_fixtures.is_document(entry), (
                book,
                url,
            )

        meta = json.loads(har_fixtures.meta_path(book).read_text(encoding="utf-8"))
        assert meta["bookmaker"] == book
        assert meta["mode"] == "prematch"
        assert meta["capture_tool_version"] == har_fixtures.CAPTURE_TOOL_VERSION
        assert meta["entries"] == len(entries)
        assert meta["payload_kind"] == "har"
        assert datetime.fromisoformat(meta["scan_time"]).tzinfo is not None
        assert meta["replay"]["matches"] > 0
        assert meta["replay"]["markets"] > 0


def test_no_committed_har_carries_cookie_or_authorization_headers():
    for book in BOOKS:
        har = har_fixtures.loads(har_fixtures.har_path(book))
        assert har["log"]["cookies"] == [], book
        for entry in har["log"]["entries"]:
            for side in ("request", "response"):
                names = {
                    str(header.get("name", "")).lower()
                    for header in entry[side].get("headers", [])
                }
                assert not (names & har_fixtures.SECRET_HEADERS), (book, side, names)


def test_scrub_drops_credentials_and_keeps_data():
    har = _har(_entry("https://bihoffer.admiralbet.ba/api/offer"))

    cleaned = har_fixtures.scrub(har)

    cleaned_entry = cleaned["log"]["entries"][0]
    request_names = {header["name"].lower() for header in cleaned_entry["request"]["headers"]}
    response_names = {
        header["name"].lower() for header in cleaned_entry["response"]["headers"]
    }
    assert request_names == {"accept"}
    assert response_names == {"content-type"}
    assert cleaned["log"]["cookies"] == []
    assert cleaned_entry["response"]["content"]["text"] == '{"ok": true}'
    # The original document is untouched (scrub returns a copy).
    assert har["log"]["cookies"] != []


def test_trim_keeps_the_document_and_the_api_and_drops_the_rest():
    har = _har(
        _entry("https://bihoffer.admiralbet.ba/api/offer"),
        _entry("https://www.admiralbet.ba/sport-prematch", content_type="text/html"),
        _entry("https://sentry.admiralbet.rs/api/4/envelope/"),
        _entry("https://www.admiralbet.ba/app.js", content_type="text/javascript"),
    )

    trimmed = har_fixtures.trim(har, book="admiralbet")

    urls = [entry["request"]["url"] for entry in trimmed["log"]["entries"]]
    assert urls == [
        "https://bihoffer.admiralbet.ba/api/offer",
        "https://www.admiralbet.ba/sport-prematch",
    ]
    assert trimmed["log"]["pages"] == []


def test_trim_bounds_the_per_event_offers():
    har = _har(
        _entry("https://www.mozzartbet.ba/betting/matches", status=200),
        *(
            _entry(f"https://www.mozzartbet.ba/betting/match/{event}")
            for event in (101, 102, 103, 104, 105)
        ),
    )

    trimmed = har_fixtures.trim(har, book="mozzartbet", max_offers=2)

    urls = [entry["request"]["url"] for entry in trimmed["log"]["entries"]]
    assert urls == [
        "https://www.mozzartbet.ba/betting/matches",
        "https://www.mozzartbet.ba/betting/match/101",
        "https://www.mozzartbet.ba/betting/match/102",
    ]


def test_the_committed_file_is_already_trimmed_and_scrubbed():
    for book in BOOKS:
        loaded = har_fixtures.loads(har_fixtures.har_path(book))
        again = har_fixtures.trim(
            loaded, book=book, max_offers=har_fixtures.MAX_REPLAY_OFFERS[book]
        )
        assert again == loaded, book


def test_the_gzip_is_small_enough_to_commit():
    for book in BOOKS:
        size = har_fixtures.har_path(book).stat().st_size
        # A full mozzartbet capture is ~72 MB of bodies; the bounded replay keeps
        # the committed set under a couple of megabytes.
        assert size < 1_500_000, (book, size)


def test_a_missing_fixture_is_a_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        har_fixtures.loads(har_fixtures.har_path("wwin", tmp_path))
