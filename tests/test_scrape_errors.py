"""SR2-1: one structural scrape-outcome taxonomy.

The old classifier searched an exception's message for markers such as "403",
"captcha" or "timeout". These tables pin the replacement: kind comes from the
exception type, the HTTP status and the challenge header, never from text.
"""

from __future__ import annotations

import httpx
import pydantic
import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scrapers.errors import (
    ScrapeError,
    ScrapeKind,
    classify_exception,
    classify_response,
    classify_scrape,
    is_failure_kind,
    kind_for_outcome,
    legacy_outcome,
)


class _Response:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/feed")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


def _validation_error() -> pydantic.ValidationError:
    with pytest.raises(pydantic.ValidationError) as caught:
        pydantic.TypeAdapter(int).validate_python("not-an-int")
    return caught.value


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (200, {}, ScrapeKind.OK),
        (204, {}, ScrapeKind.OK),
        (301, {}, ScrapeKind.OK),
        (401, {}, ScrapeKind.BLOCKED),
        (403, {}, ScrapeKind.BLOCKED),
        (407, {}, ScrapeKind.BLOCKED),
        (451, {}, ScrapeKind.BLOCKED),
        (200, {"cf-mitigated": "challenge"}, ScrapeKind.BLOCKED),
        (503, {"CF-Mitigated": "Challenge"}, ScrapeKind.BLOCKED),
        (429, {}, ScrapeKind.RATE_LIMITED),
        (500, {}, ScrapeKind.UPSTREAM_5XX),
        (502, {}, ScrapeKind.UPSTREAM_5XX),
        (503, {}, ScrapeKind.UPSTREAM_5XX),
        (400, {}, ScrapeKind.TRANSPORT),
        (404, {}, ScrapeKind.TRANSPORT),
    ],
    ids=lambda value: str(value) if isinstance(value, int) else "",
)
def test_status_codes_map_to_kinds(status, headers, expected):
    assert classify_response(_Response(status, headers)) is expected


def test_a_playwright_response_uses_the_same_classifier():
    class PlaywrightResponse:
        status = 403
        headers: dict[str, str] = {}

    assert classify_response(PlaywrightResponse()) is ScrapeKind.BLOCKED


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PlaywrightTimeoutError("Timeout 3000ms exceeded."), ScrapeKind.TIMEOUT),
        (httpx.ReadTimeout("slow feed"), ScrapeKind.TIMEOUT),
        (TimeoutError("slow feed"), ScrapeKind.TIMEOUT),
        (httpx.ConnectError("connection refused"), ScrapeKind.TRANSPORT),
        (httpx.ReadError("connection reset"), ScrapeKind.TRANSPORT),
        (PlaywrightError("target closed"), ScrapeKind.TRANSPORT),
        (_status_error(403), ScrapeKind.BLOCKED),
        (_status_error(429), ScrapeKind.RATE_LIMITED),
        (_status_error(503), ScrapeKind.UPSTREAM_5XX),
        (ValueError("unexpected JSON shape"), ScrapeKind.PARSE_ERROR),
        (KeyError("missing market"), ScrapeKind.PARSE_ERROR),
        (_validation_error(), ScrapeKind.SCHEMA_DRIFT),
        # The old text markers must no longer decide the kind.
        (RuntimeError("HTTP 403 Forbidden"), ScrapeKind.PARSE_ERROR),
        (RuntimeError("captcha challenge"), ScrapeKind.PARSE_ERROR),
        (RuntimeError("net::ERR_TIMED_OUT"), ScrapeKind.PARSE_ERROR),
    ],
    ids=lambda value: type(value).__name__,
)
def test_exceptions_map_to_kinds_without_text_matching(error, expected):
    assert classify_exception(error) is expected


def test_a_classified_error_keeps_its_kind():
    assert classify_exception(ScrapeError(ScrapeKind.BLOCKED)) is ScrapeKind.BLOCKED
    assert classify_exception(ScrapeError(ScrapeKind.TIMEOUT)) is ScrapeKind.TIMEOUT


def test_a_scrape_with_rows_is_ok_and_without_rows_is_empty():
    assert classify_scrape([object()]) is ScrapeKind.OK
    assert classify_scrape([]) is ScrapeKind.EMPTY
    assert classify_scrape(None) is ScrapeKind.EMPTY
    assert classify_scrape([], error=httpx.ReadTimeout("slow")) is ScrapeKind.TIMEOUT


@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        (ScrapeKind.OK, "success"),
        (ScrapeKind.EMPTY, "empty"),
        (ScrapeKind.BLOCKED, "blocked"),
        (ScrapeKind.RATE_LIMITED, "blocked"),
        (ScrapeKind.TIMEOUT, "blocked"),
        (ScrapeKind.TRANSPORT, "parse_error"),
        (ScrapeKind.UPSTREAM_5XX, "parse_error"),
        (ScrapeKind.PARSE_ERROR, "parse_error"),
        (ScrapeKind.SCHEMA_DRIFT, "parse_error"),
        (ScrapeKind.SKIPPED, "skipped"),
    ],
)
def test_every_kind_keeps_a_historical_outcome(kind, outcome):
    assert legacy_outcome(kind) == outcome


@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        ("success", ScrapeKind.OK),
        ("empty", ScrapeKind.EMPTY),
        ("blocked", ScrapeKind.BLOCKED),
        ("parse_error", ScrapeKind.PARSE_ERROR),
        ("error", ScrapeKind.PARSE_ERROR),
        ("skipped", ScrapeKind.SKIPPED),
    ],
)
def test_an_old_record_recovers_a_kind(outcome, kind):
    assert kind_for_outcome(outcome) is kind


def test_only_ok_empty_and_skipped_are_not_failures():
    non_failures = {ScrapeKind.OK, ScrapeKind.EMPTY, ScrapeKind.SKIPPED}
    for kind in ScrapeKind:
        assert is_failure_kind(kind) is (kind not in non_failures)
