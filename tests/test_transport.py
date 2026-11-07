"""SR2-2: per-book transport policy and one client per book per scan."""

from __future__ import annotations

import asyncio

import pytest

from scrapers.transport import (
    POLICIES,
    TransportPool,
    policy_for,
    transport_client,
    transport_pool,
)

# The frozen timeout each direct-API adapter used before the policy existed.
HTTP_BOOKS = {
    "betole": (30.0, 30.0),
    "evlbet": (20.0, 20.0),
    "maxbet": (60.0, 60.0),
    "mbet": (30.0, 30.0),
    "mdshop": (30.0, 30.0),
    "premier_kladionica": (60.0, 60.0),
    "sportplus": (120.0, 60.0),
}


@pytest.mark.parametrize(("book", "timeouts"), sorted(HTTP_BOOKS.items()))
def test_every_http_book_keeps_its_old_timeout(book, timeouts):
    for mode, expected in zip(("prematch", "live"), timeouts, strict=True):
        policy = policy_for(book, mode)
        timeout = policy.timeout()
        assert policy.total_timeout == expected
        assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
            expected,
            expected,
            expected,
            expected,
        )


@pytest.mark.parametrize("book", sorted(HTTP_BOOKS))
def test_every_http_book_has_both_policies(book):
    assert (book, "prematch") in POLICIES
    assert (book, "live") in POLICIES


def test_the_policy_has_explicit_limits_and_a_rate():
    policy = policy_for("mbet", "prematch")
    limits = policy.limits()

    assert limits.max_connections == 10
    assert limits.max_keepalive_connections == 5
    assert policy.retry_budget == 3
    assert policy.requests_per_second == 5.0
    assert policy.bookmaker == "mbet"
    assert isinstance(policy.verify, bool)


def test_the_pool_shares_one_client_per_book_and_mode():
    async def scenario():
        pool = TransportPool()
        first = pool.client("mbet", "prematch")
        second = pool.client("mbet", "prematch")
        other_book = pool.client("mdshop", "prematch")
        other_mode = pool.client("mbet", "live")

        assert first is second
        assert first is not other_book
        assert first is not other_mode
        assert pool.books == {
            ("mbet", "prematch"),
            ("mdshop", "prematch"),
            ("mbet", "live"),
        }

        await pool.aclose()
        assert first.is_closed
        assert other_book.is_closed
        assert other_mode.is_closed

    asyncio.run(scenario())


def test_a_scan_pool_shares_and_closes_clients():
    async def scenario():
        async with transport_pool():
            async with transport_client("mbet", "prematch") as first:
                async with transport_client("mbet", "prematch") as second:
                    assert first is second
                    assert not first.is_closed
            assert not first.is_closed  # the scan owns the client
        assert first.is_closed

    asyncio.run(scenario())


def test_a_standalone_client_is_private_and_closed():
    async def scenario():
        async with transport_client("mbet", "prematch") as first:
            async with transport_client("mbet", "prematch") as second:
                assert first is not second
        assert first.is_closed
        assert second.is_closed

    asyncio.run(scenario())


def test_extra_kwargs_are_used_only_when_the_client_is_created():
    async def scenario():
        pool = TransportPool()
        first = pool.client("evlbet", "prematch", headers={"X-Test": "1"})
        second = pool.client("evlbet", "prematch")

        assert first is second
        assert first.headers["X-Test"] == "1"
        await pool.aclose()

    asyncio.run(scenario())
