import asyncio

from scrapers.base import fetch_pages


def _run(coro):
    return asyncio.run(coro)


def _pages(total_items: int, size: int, calls: list):
    async def fetch_page(i: int):
        calls.append(i)
        chunk = list(range(i * size, min((i + 1) * size, total_items)))
        return chunk

    return fetch_page


def test_matches_sequential_walk_and_stops_on_short_page():
    calls: list[int] = []
    out = _run(fetch_pages(_pages(250, 100, calls), page_size=100, max_pages=50))
    assert out == list(range(250))


def test_exact_multiple_ends_on_empty_page():
    out = _run(fetch_pages(_pages(200, 100, []), page_size=100, max_pages=50))
    assert out == list(range(200))


def test_failed_page_keeps_earlier_pages_only():
    async def fetch_page(i):
        return None if i == 2 else [i] * 10

    out = _run(fetch_pages(fetch_page, page_size=10, max_pages=10, batch=4))
    assert out == [0] * 10 + [1] * 10


def test_max_pages_cap_and_first_page_offset():
    calls: list[int] = []
    out = _run(fetch_pages(_pages(10_000, 10, calls), page_size=10, max_pages=5, first_page=1))
    assert sorted(calls) == [1, 2, 3, 4, 5]
    assert len(out) == 50
