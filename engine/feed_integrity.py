"""Per-book feed integrity and stale-book quarantine (P0-7).

The certainty gate answers "are these the same event?". This module answers a
different question: "can this book's prices be used at all right now?" A feed
that is stale, empty, parsing errors, publishing a complete set below 1.0, or
disagreeing with the peer median is a bad price source, not a gift.

Quarantine is a temporary price-source restriction. It never changes a
certainty-gate verdict, and recovery requires several consecutive clean scans so
one lucky scan cannot re-admit a book that is still broken.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from config.settings import (
    FEED_INTEGRITY_HISTORY,
    FEED_INTEGRITY_MISSING_DEGRADED_RATE,
    FEED_INTEGRITY_OUTLIER_DEGRADED_RATE,
    FEED_INTEGRITY_OUTLIER_QUARANTINE_RATE,
    FEED_INTEGRITY_RECOVERY_SCANS,
    price_source,
)
from engine.market_consensus import complete_market_spec, find_outliers
from models.schemas import Match, MatchGroup


def _age_seconds(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    try:
        left = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
        right = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
        return (right - left).total_seconds()
    except (TypeError, ValueError):
        return None


def _own_margin_violations(matches: list[Match]) -> tuple[int, int]:
    """Count complete sets whose own implied sum is below 1.0.

    Returns (violations, complete_sets). An incomplete set is not evidence of a
    broken book and is ignored here; the missing-market metric covers it.
    """
    violations = 0
    complete = 0
    for match in matches:
        for market in match.markets:
            spec = complete_market_spec(market.market_type)
            if spec is None:
                continue
            labels, _winners = spec
            odds = {
                item.label: item.value
                for item in market.odds
                if item.value > 1.01
            }
            if set(odds) != labels:
                continue
            complete += 1
            if sum(1.0 / value for value in odds.values()) < 1.0:
                violations += 1
    return violations, complete


def _missing_and_expected(groups: list[MatchGroup]) -> tuple[dict[str, int], dict[str, int]]:
    """Missing/expected market instances per book, peer-relative.

    A market family is expected from a book when at least two distinct price
    sources in the same group publish it. This keeps a two-book fixture from
    making every absent family look like a missing feed.
    """
    missing: dict[str, int] = defaultdict(int)
    expected: dict[str, int] = defaultdict(int)
    for group in groups:
        by_type_sources: dict[Any, set[str]] = defaultdict(set)
        book_types: dict[str, set[Any]] = defaultdict(set)
        for match in group.matches:
            source = price_source(match.bookmaker)
            for market in match.markets:
                by_type_sources[market.market_type].add(source)
                book_types[match.bookmaker].add(market.market_type)
        expected_types = {
            market_type
            for market_type, sources in by_type_sources.items()
            if len(sources) >= 2
        }
        for match in group.matches:
            book = match.bookmaker
            expected[book] += len(expected_types)
            missing[book] += sum(
                1 for market_type in expected_types if market_type not in book_types[book]
            )
    return dict(missing), dict(expected)


def _outlier_counts(groups: list[MatchGroup]) -> tuple[dict[str, int], dict[str, int]]:
    """Outlier rows and comparable complete markets per book."""
    outliers, _comparisons = find_outliers(groups)
    counts: dict[str, int] = defaultdict(int)
    for row in outliers:
        for book in str(row.get("bookmaker") or "").split("+"):
            if book:
                counts[book] += 1

    comparable: dict[str, int] = defaultdict(int)
    for group in groups:
        sources_by_type: dict[Any, set[str]] = defaultdict(set)
        complete_by_book: dict[str, set[Any]] = defaultdict(set)
        for match in group.matches:
            for market in match.markets:
                spec = complete_market_spec(market.market_type)
                if spec is None:
                    continue
                labels, _winners = spec
                if {item.label for item in market.odds} == labels:
                    sources_by_type[market.market_type].add(price_source(match.bookmaker))
                    complete_by_book[match.bookmaker].add(market.market_type)
        for market_type, sources in sources_by_type.items():
            if len(sources) < 3:
                continue
            for book, types in complete_by_book.items():
                if market_type in types:
                    comparable[book] += 1
    return dict(counts), dict(comparable)


def _why(
    book: str,
    *,
    count: int,
    progress: str,
    errors: list[str],
    name: str,
    oldest_age_sec: float | None,
    ttl_sec: int,
    missing_rate: float | None,
    own_violations: int,
    outlier_rate: float | None,
    comparable_markets: int,
) -> tuple[list[str], list[str]]:
    """Return (critical reasons, warning reasons) for one book."""
    critical: list[str] = []
    warnings: list[str] = []
    error_text = " ".join(errors).lower()
    if progress == "error" or name.lower() in error_text:
        critical.append("parse_error")
    if count == 0:
        critical.append("skipped_backoff" if progress == "skipped" else "empty_feed")
    if count and (oldest_age_sec is None or oldest_age_sec > ttl_sec):
        critical.append("stale_prices")
    if own_violations:
        critical.append("own_margin_below_one")
    if outlier_rate is not None and outlier_rate > FEED_INTEGRITY_OUTLIER_QUARANTINE_RATE:
        # A three-book group has a median of two peers, so the book supplying a
        # genuine edge is always the "outlier". That is not a broken feed.
        # Quarantine only after enough comparisons to make the rate meaningful.
        if comparable_markets >= 10:
            critical.append("outlier_rate")
        else:
            warnings.append("outlier_rate")
    elif outlier_rate is not None and outlier_rate > FEED_INTEGRITY_OUTLIER_DEGRADED_RATE:
        warnings.append("outlier_rate")
    if missing_rate is not None and missing_rate > FEED_INTEGRITY_MISSING_DEGRADED_RATE:
        warnings.append("missing_markets")
    return critical, warnings


def compute_feed_integrity(
    *,
    mode: str,
    bookmakers: dict[str, str],
    matches: list[Match],
    groups: list[MatchGroup],
    progress: dict[str, str],
    counts: dict[str, int],
    errors: list[str],
    previous: dict[str, dict],
    now: datetime,
    ttl_sec: int,
    stale_price_rows: dict[str, int] | None = None,
) -> dict[str, dict]:
    """Build one scan's integrity scorecard for every enabled book."""
    missing, expected = _missing_and_expected(groups)
    outlier_counts, comparable = _outlier_counts(groups)
    stale_rows = stale_price_rows or {}
    result: dict[str, dict] = {}

    for bookmaker, name in bookmakers.items():
        book_matches = [match for match in matches if match.bookmaker == bookmaker]
        count = counts.get(bookmaker, len(book_matches))
        old = previous.get(bookmaker) or {}
        fetched = [match.fetched_at for match in book_matches if match.fetched_at]
        oldest = min(fetched) if fetched else None
        oldest_age = _age_seconds(oldest, now)
        own_violations, complete_sets = _own_margin_violations(book_matches)
        missing_count = missing.get(bookmaker, 0)
        expected_count = expected.get(bookmaker, 0)
        missing_rate = (
            missing_count / expected_count if expected_count else None
        )
        outlier_count = outlier_counts.get(bookmaker, 0)
        comparable_count = comparable.get(bookmaker, 0)
        outlier_rate = (
            outlier_count / comparable_count if comparable_count else None
        )
        book_progress = progress.get(bookmaker, "")
        critical, warnings = _why(
            bookmaker,
            count=count,
            progress=book_progress,
            errors=errors,
            name=name,
            oldest_age_sec=oldest_age,
            ttl_sec=ttl_sec,
            missing_rate=missing_rate,
            own_violations=own_violations,
            outlier_rate=outlier_rate,
            comparable_markets=comparable_count,
        )

        was_quarantined = old.get("state") == "quarantined"
        healthy_scan = not critical and not warnings
        previous_healthy = int(old.get("consecutive_healthy_scans") or 0)
        previous_unhealthy = int(old.get("consecutive_unhealthy_scans") or 0)
        reasons = critical + warnings

        if critical:
            state = "quarantined"
            healthy_streak = 0
            unhealthy_streak = previous_unhealthy + 1
        elif was_quarantined:
            healthy_streak = previous_healthy + 1 if healthy_scan else 0
            unhealthy_streak = 0
            if healthy_streak >= FEED_INTEGRITY_RECOVERY_SCANS:
                state = "healthy"
                reasons = []
            else:
                state = "quarantined"
                reasons = ["recovering", *warnings]
        else:
            healthy_streak = previous_healthy + 1 if healthy_scan else 0
            unhealthy_streak = 0
            state = "healthy" if healthy_scan else "degraded"

        last_successful = old.get("last_successful_scan")
        if count > 0 and "parse_error" not in critical and "empty_feed" not in critical:
            last_successful = now.isoformat()

        history = list(old.get("history") or [])
        history.append(
            {
                "scan_time": now.isoformat(),
                "state": state,
                "reasons": reasons,
                "matches": count,
                "oldest_age_sec": oldest_age,
                "own_margin_violations": own_violations,
                "outlier_rate": outlier_rate,
                "missing_rate": missing_rate,
            }
        )
        history = history[-FEED_INTEGRITY_HISTORY:]

        result[bookmaker] = {
            "bookmaker": bookmaker,
            "name": name,
            "mode": mode,
            "state": state,
            "reasons": reasons,
            "reason": ", ".join(reasons) if reasons else "healthy feed",
            "metrics": {
                "matches": count,
                "oldest_fetched_at": oldest.isoformat() if oldest else None,
                "oldest_age_sec": oldest_age,
                "ttl_sec": ttl_sec,
                "complete_sets": complete_sets,
                "own_margin_violations": own_violations,
                "missing_markets": missing_count,
                "expected_markets": expected_count,
                "missing_rate": round(missing_rate, 4) if missing_rate is not None else None,
                "outlier_markets": outlier_count,
                "comparable_markets": comparable_count,
                "outlier_rate": round(outlier_rate, 4) if outlier_rate is not None else None,
            },
            "consecutive_healthy_scans": healthy_streak,
            "consecutive_unhealthy_scans": unhealthy_streak,
            "stale_price_rows": int(stale_rows.get(bookmaker, 0)),
            "last_successful_scan": last_successful,
            "scan_time": now.isoformat(),
            "history": history,
        }
    return result


def quarantined_books(scorecard: dict[str, dict]) -> set[str]:
    """Book ids that must not contribute a priced leg in this scan."""
    return {
        bookmaker
        for bookmaker, entry in scorecard.items()
        if entry.get("state") == "quarantined"
    }


def priceable_groups(
    groups: list[MatchGroup], quarantined: set[str]
) -> list[MatchGroup]:
    """Remove quarantined legs from groups used for pricing.

    The original group and its evidence stay untouched for diagnostics. This
    copy only answers "what can be priced right now?"; the certainty gate has
    already proved the event, and a subset of a proved group is the same event.
    """
    if not quarantined:
        return list(groups)
    result: list[MatchGroup] = []
    for group in groups:
        remaining = [
            match for match in group.matches if match.bookmaker not in quarantined
        ]
        if remaining:
            result.append(group.model_copy(update={"matches": remaining}))
    return result
