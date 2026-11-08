"""SR5-1: the per-book reliability metrics in the Prometheus output.

The retry path, the schema-drift counter, the browser-recycle counter and the
last-success gauge are exercised, then the text output of ``/api/metrics`` is
scraped and every new family is asserted there. The registry itself is covered
by ``tests/test_metrics.py``; this file pins the SR5-1 additions.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from scrapers.browser_pool import BrowserPool
from scrapers.errors import ScrapeError
from scrapers.retry import retry_call
from scrapers.transport import policy_for
from scrapers.wire_schemas import validate_mozzart_odds
from server.app import app
from server.observability import metrics


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


class _Response:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}


async def _no_sleep(_delay: float) -> None:
    return None


def _retry_then_succeed() -> None:
    calls = {"count": 0}

    async def send() -> _Response:
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ConnectError("boom")
        return _Response(200)

    asyncio.run(
        retry_call(
            send,
            policy=policy_for("mbet", "prematch"),
            label="sr5-1",
            account=False,
            sleep=_no_sleep,
            rand=lambda: 0.0,
        )
    )


def test_a_histogram_renders_cumulative_buckets():
    metrics.observe("bh_test_seconds", 0.07, book="mbet")
    metrics.observe("bh_test_seconds", 3.0, book="mbet")

    text = metrics.render()

    assert "# TYPE bh_test_seconds histogram" in text
    assert 'bh_test_seconds_bucket{book="mbet",le="0.05"} 0' in text
    assert 'bh_test_seconds_bucket{book="mbet",le="0.1"} 1' in text
    assert 'bh_test_seconds_bucket{book="mbet",le="2.5"} 1' in text
    assert 'bh_test_seconds_bucket{book="mbet",le="5"} 2' in text
    assert 'bh_test_seconds_bucket{book="mbet",le="+Inf"} 2' in text
    assert 'bh_test_seconds_sum{book="mbet"} 3.07' in text
    assert 'bh_test_seconds_count{book="mbet"} 2' in text


def test_the_retry_path_counts_attempts_retries_status_and_latency():
    _retry_then_succeed()

    text = metrics.render()

    assert 'bh_scraper_attempts_total{book="mbet"} 3' in text
    assert 'bh_scraper_retries_total{book="mbet"} 2' in text
    assert 'bh_http_status_total{book="mbet",status="200"} 1' in text
    assert 'bh_scraper_attempt_seconds_count{book="mbet"} 3' in text
    assert "# TYPE bh_scraper_attempt_seconds histogram" in text


def test_a_schema_rejection_counts_the_book():
    row = {
        "game": {"id": 1, "name": "Konačan ishod", "shortName": "ki"},
        "subgame": {"name": "1"},
        "value": "2.2",
    }

    with pytest.raises(ScrapeError):
        validate_mozzart_odds([row])

    assert 'bh_schema_drift_total{book="mozzartbet"} 1' in metrics.render()


class _Context:
    async def add_init_script(self, script: str) -> None:
        return None

    async def route(self, pattern: str, handler: Any) -> None:
        return None

    async def close(self) -> None:
        return None


class _Browser:
    def __init__(self) -> None:
        self.closed = False

    def is_connected(self) -> bool:
        return True

    async def new_context(self, **kwargs: Any) -> _Context:
        return _Context()

    async def close(self) -> None:
        self.closed = True


class _Playwright:
    async def stop(self) -> None:
        return None


def test_a_pool_recycle_is_counted_with_its_reason():
    async def launch() -> tuple[_Playwright, _Browser, _Context]:
        return _Playwright(), _Browser(), _Context()

    pool = BrowserPool(launch=launch, max_pages=1)

    async def scenario():
        async with pool.context():
            pass
        async with pool.context():
            pass
        await pool.aclose()

    asyncio.run(scenario())

    assert 'bh_browser_recycles_total{reason="pages"} 1' in metrics.render()


def test_the_endpoint_scrapes_every_reliability_family():
    _retry_then_succeed()
    metrics.set_gauge(
        "bh_book_last_success_timestamp_seconds",
        1_760_000_000,
        mode="prematch",
        book="mbet",
    )

    body = TestClient(app).get("/api/metrics").text

    assert 'bh_scraper_attempts_total{book="mbet"} 3' in body
    assert 'bh_scraper_retries_total{book="mbet"} 2' in body
    assert 'bh_http_status_total{book="mbet",status="200"} 1' in body
    assert "bh_scraper_attempt_seconds_bucket" in body
    assert (
        'bh_book_last_success_timestamp_seconds{book="mbet",mode="prematch"} '
        "1760000000" in body
    )
    assert "# TYPE bh_scraper_attempt_seconds histogram" in body
