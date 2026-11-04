"""Measured identical-feed ("skin") detection (P2-7).

Two brands can be one price source. The NSoft pair (MDShop/Admiralbet) is
declared in config; this module measures the rest from a scan instead of adding
another hardcoded guess.

A pair is compared only on the same event, market type, settlement, period and
line. The conclusion needs a minimum number of shared outcomes; a pair with too
little data is ``insufficient_data``, never silently ``independent``. A measured
twin is registered as one price source, so the engine's one-leg-per-source rule
applies to it exactly as it does to NSoft.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from config.settings import (
    PRICE_SOURCES,
    price_source,
    register_price_source_twin,
)
from models.schemas import Match, MatchGroup

MIN_SHARED_OUTCOMES = 200
TWIN_RATE = 0.99
SUSPICIOUS_RATE = 0.95


def _market_key(market: Any) -> tuple[Any, str, str, str]:
    return (
        market.market_type,
        str(market.settlement),
        str(market.period),
        str(market.line if hasattr(market, "line") else ""),
    )


def _odds_map(market: Any) -> dict[str, float]:
    return {str(odd.label): float(odd.value) for odd in market.odds}


def measure_price_agreement(
    groups: list[MatchGroup],
    *,
    min_shared: int = MIN_SHARED_OUTCOMES,
) -> dict[str, dict[str, Any]]:
    """Return one row per book pair, with shared/identical counts and a class."""
    shared: dict[tuple[str, str], int] = defaultdict(int)
    identical: dict[tuple[str, str], int] = defaultdict(int)

    for group in groups:
        for left_match, right_match in combinations(group.matches, 2):
            for left_market in left_match.markets:
                key = _market_key(left_market)
                right_market = next(
                    (
                        market
                        for market in right_match.markets
                        if _market_key(market) == key
                    ),
                    None,
                )
                if right_market is None:
                    continue
                right_odds = _odds_map(right_market)
                left_book, right_book = sorted(
                    (left_match.bookmaker, right_match.bookmaker)
                )
                pair = (left_book, right_book)
                for label, left_value in _odds_map(left_market).items():
                    right_value = right_odds.get(label)
                    if right_value is None:
                        continue
                    shared[pair] += 1
                    if abs(left_value - right_value) <= 0.001:
                        identical[pair] += 1

    matrix: dict[str, dict[str, Any]] = {}
    for pair in sorted(set(shared) | set(identical)):
        left, right = pair[0], pair[1]
        count = shared.get(pair, 0)
        same = identical.get(pair, 0)
        rate = same / count if count else None
        if count < min_shared:
            classification = "insufficient_data"
        elif rate is not None and rate >= TWIN_RATE:
            classification = "twin"
        elif rate is not None and rate >= SUSPICIOUS_RATE:
            classification = "suspicious"
        else:
            classification = "independent"
        matrix[f"{left}|{right}"] = {
            "left": left,
            "right": right,
            "shared_outcomes": count,
            "identical_outcomes": same,
            "identical_rate": round(rate, 4) if rate is not None else None,
            "min_shared": min_shared,
            "classification": classification,
        }
    return matrix


def apply_measured_twins(matrix: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Register every measured twin as one price source; return the new pairs."""
    registered: list[tuple[str, str]] = []
    for row in matrix.values():
        if row["classification"] != "twin":
            continue
        left, right = str(row["left"]), str(row["right"])
        if price_source(left) == price_source(right):
            continue
        register_price_source_twin(left, right)
        registered.append((left, right))
    return registered


def declared_twin_warnings(
    matrix: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    """Warn when a config-declared twin is measured as separate.

    ``insufficient_data`` is not a warning: the measurement did not have enough
    shared outcomes to disagree. A measured ``independent`` or ``suspicious``
    pair is a real mismatch worth showing.
    """
    by_source: dict[str, list[str]] = defaultdict(list)
    for book, source in PRICE_SOURCES.items():
        by_source[source].append(book)
    warnings: list[dict[str, str]] = []
    for source, books in by_source.items():
        if len(books) < 2:
            continue
        for left, right in combinations(sorted(books), 2):
            row = matrix.get(f"{left}|{right}") or matrix.get(f"{right}|{left}")
            if row and row["classification"] in {"independent", "suspicious"}:
                warnings.append(
                    {
                        "declared_source": source,
                        "left": left,
                        "right": right,
                        "measured": str(row["classification"]),
                        "shared_outcomes": str(row["shared_outcomes"]),
                    }
                )
    return warnings


def summary(matrix: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {
        "twin": 0,
        "suspicious": 0,
        "independent": 0,
        "insufficient_data": 0,
    }
    for row in matrix.values():
        counts[str(row["classification"])] += 1
    return counts


def match_pair_key(match: Match) -> str:
    """Small helper for callers that need a stable book identity in reports."""
    return f"{match.bookmaker}|{match.event_id or match.home_team + '|' + match.away_team}"
