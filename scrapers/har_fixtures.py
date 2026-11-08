"""SR4-8: scrubbed, trimmed HAR fixtures for the browser books.

The three browser adapters fetch their JSON from inside the page (SR4-8a), so
Playwright's HAR machinery covers them. This module owns the fixture rules:
which entries are kept, what is scrubbed, and how the committed file is named
and described. ``scripts/capture_har.py`` records a live HAR and applies these
rules; ``tests/test_har_fixtures.py`` (normal suite) proves the committed files
are scrubbed and consistent, and ``tests/test_browser_har_replay.py`` (opt-in,
``BH_ARB_TEST_BROWSER=1``) replays them through the real scrape.

A HAR is not a market fixture: it is a transport recording. Its payloads are
the full API responses Chromium served, which is why the files are gzipped and
why ``mozzartbet`` keeps a bounded number of per-event offers (its full offer is
one response per event).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

CAPTURE_TOOL_VERSION = "1"

HAR_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "har"

#: The API calls a replay must carry: a book's JSON endpoints live under one of
#: these prefixes. The page document (any HTML response) is kept as well, so
#: ``goto`` can establish the origin the adapter fetches from.
REPLAY_PREFIXES: dict[str, tuple[str, ...]] = {
    "admiralbet": ("https://bihoffer.admiralbet.ba/",),
    "wwin": ("https://wwin.ba/content/sport-livecontent/api/",),
    "mozzartbet": ("https://www.mozzartbet.ba/betting/",),
}

#: How many per-event offer responses a replayed book keeps. ``mozzartbet``
#: needs one request per event (677 in the 2026-11-08 scan); a full HAR is ~72 MB
#: of bodies. The offers that are not kept abort during the replay and the
#: adapter keeps that event's list odds, which is its documented fallback.
MAX_REPLAY_OFFERS: dict[str, int | None] = {
    "admiralbet": None,
    "wwin": None,
    "mozzartbet": 30,
}

#: Headers that must never reach a committed file.
SECRET_HEADERS = frozenset(
    {"cookie", "set-cookie", "authorization", "proxy-authorization"}
)


def har_path(book: str, directory: Path | None = None) -> Path:
    """The committed file for one book."""
    return (directory or HAR_DIR) / f"{book}.har.gz"


def meta_path(book: str, directory: Path | None = None) -> Path:
    """The sidecar that says when and how the file was captured."""
    return (directory or HAR_DIR) / f"{book}.meta.json"


def _content_type(entry: dict[str, Any]) -> str:
    for header in entry.get("response", {}).get("headers", []):
        if str(header.get("name", "")).lower() == "content-type":
            return str(header.get("value", "")).lower()
    return ""


def is_document(entry: dict[str, Any]) -> bool:
    """The page document (or a frame document), not a tracking pixel.

    Playwright records ``_resourceType`` on every entry, so a 302 from an
    analytics pixel is excluded even when it answers with HTML. Synthetic HARs
    without the field fall back to the content type.
    """
    resource_type = entry.get("_resourceType")
    if resource_type:
        return resource_type == "document"
    status = int(entry.get("response", {}).get("status") or 0)
    if 300 <= status < 400:
        return True
    return _content_type(entry).startswith("text/html")


def scrub(har: dict[str, Any]) -> dict[str, Any]:
    """Drop the browser's credentials from a HAR; returns a new document.

    Request and response headers lose every name in ``SECRET_HEADERS`` (the
    browser's session and Cloudflare clearance cookies, any bearer token), and
    the HAR's own cookie jar is emptied. Odds payloads are data, not secrets,
    and are kept — the parser needs them.
    """
    payload = json.loads(json.dumps(har))
    log = payload.setdefault("log", {})
    log["cookies"] = []
    for entry in log.get("entries", []):
        for side in ("request", "response"):
            headers = entry.get(side, {}).get("headers") or []
            entry[side]["headers"] = [
                header
                for header in headers
                if str(header.get("name", "")).lower() not in SECRET_HEADERS
            ]
    return payload


def trim(
    har: dict[str, Any],
    *,
    book: str,
    max_offers: int | None = None,
) -> dict[str, Any]:
    """Keep the page document and the book's API calls, then scrub.

    Everything else — analytics, chat widgets, images, fonts, JS bundles — is
    dropped: a replay aborts what is not in the file, and the adapters need none
    of it. ``max_offers`` bounds the per-event offer entries of a book whose full
    offer is one request per event.
    """
    prefixes = REPLAY_PREFIXES[book]
    payload = json.loads(json.dumps(har))
    log = payload.setdefault("log", {})
    kept: list[dict[str, Any]] = []
    offers = 0
    for entry in log.get("entries", []):
        url = str(entry.get("request", {}).get("url", ""))
        if not (url.startswith(prefixes) or is_document(entry)):
            continue
        if max_offers is not None and "/betting/match/" in url:
            if offers >= max_offers:
                continue
            offers += 1
        kept.append(entry)
    log["entries"] = kept
    log["pages"] = []
    return scrub(payload)


def to_json_bytes(har: dict[str, Any]) -> bytes:
    """Plain (uncompressed) HAR bytes, the form ``route_from_har`` reads."""
    return json.dumps(har, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def dumps(har: dict[str, Any]) -> bytes:
    """The bytes that go into the committed ``.har.gz``: compact JSON, gzipped."""
    return gzip.compress(to_json_bytes(har), compresslevel=9)


def loads(path: Path) -> dict[str, Any]:
    """Read a committed ``.har.gz`` back into a HAR document."""
    return json.loads(gzip.decompress(path.read_bytes()))


def write_fixture(har: dict[str, Any], book: str, directory: Path | None = None) -> Path:
    """Write the committed file and return its path."""
    target = har_path(book, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(dumps(har))
    return target


def write_meta(
    book: str,
    *,
    scan_time: str,
    recorded_at: str,
    entries: int,
    replay: dict[str, int],
    directory: Path | None = None,
) -> Path:
    """Write the sidecar next to the HAR: provenance and the verified output."""
    target = meta_path(book, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "bookmaker": book,
        "mode": "prematch",
        "scan_time": scan_time,
        "recorded_at": recorded_at,
        "capture_tool_version": CAPTURE_TOOL_VERSION,
        "entries": entries,
        "max_offers": MAX_REPLAY_OFFERS.get(book),
        "replay": replay,
        "payload_kind": "har",
        "provenance": (
            "Playwright HAR recorded through the real adapter; scrubbed of "
            "cookie/authorization headers and trimmed to the page document plus "
            "the book's API calls"
        ),
    }
    target.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


__all__ = [
    "CAPTURE_TOOL_VERSION",
    "HAR_DIR",
    "MAX_REPLAY_OFFERS",
    "REPLAY_PREFIXES",
    "SECRET_HEADERS",
    "dumps",
    "har_path",
    "is_document",
    "loads",
    "meta_path",
    "scrub",
    "to_json_bytes",
    "trim",
    "write_fixture",
    "write_meta",
]
