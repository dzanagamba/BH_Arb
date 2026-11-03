"""Cross-book price consensus for a candidate market mapping.

A wrong market id or a swapped label does not raise an error; it makes one
book's odds disagree with the others for the same real match. This module is the
reusable half of ``scripts/price_check.py``: remove each book's margin, compare
the candidate with the median of at least two other books, and accept only when
every outcome is inside the threshold.

It is evidence, not a vote: one outlier on one fixture is a warning; a mapping is
rejected only when the caller sees the pattern across its sample.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Literal

from models.schemas import Market, MarketType

_COMPLETE: dict[MarketType, tuple[frozenset[str], int]] = {
    MarketType.MATCH_RESULT: (frozenset({"1", "X", "2"}), 1),
    MarketType.DOUBLE_CHANCE: (frozenset({"1X", "12", "X2"}), 2),
    MarketType.BTTS: (frozenset({"GG", "NG"}), 1),
    MarketType.OVER_UNDER_1_5: (frozenset({"Over 1.5", "Under 1.5"}), 1),
    MarketType.OVER_UNDER_2_5: (frozenset({"Over 2.5", "Under 2.5"}), 1),
    MarketType.OVER_UNDER_3_5: (frozenset({"Over 3.5", "Under 3.5"}), 1),
    MarketType.FIRST_HALF_1X2: (frozenset({"1", "X", "2"}), 1),
    MarketType.FIRST_HALF_OU: (frozenset({"Over 2.5", "Under 2.5"}), 1),
}


def devigged(market: Market) -> dict[str, float] | None:
    """True probability per outcome, or None when the set is not complete."""
    spec = _COMPLETE.get(market.market_type)
    if spec is None:
        return None
    labels, winners = spec
    odds = {item.label: item.value for item in market.odds}
    if set(odds) != labels or any(value < 1.01 for value in odds.values()):
        return None
    total = sum(1 / value for value in odds.values())
    return {label: (1 / value) / total * winners for label, value in odds.items()}


@dataclass
class ConsensusResult:
    status: Literal["accepted", "outlier", "insufficient_evidence"]
    market_type: MarketType
    compared_books: int = 0
    gaps: list[dict[str, float | str]] = field(default_factory=list)
    evidence: str = ""


def compare(
    candidate: Market,
    others: list[Market],
    *,
    threshold: float = 0.10,
    min_other_books: int = 2,
) -> ConsensusResult:
    """Compare one candidate market with other books' mappings of the same bet."""
    candidate_probs = devigged(candidate)
    if candidate_probs is None:
        return ConsensusResult(
            "insufficient_evidence", candidate.market_type, 0, [], "candidate set incomplete"
        )

    reference: list[dict[str, float]] = []
    for market in others:
        if market.market_type != candidate.market_type:
            continue
        probs = devigged(market)
        if probs is not None and set(probs) == set(candidate_probs):
            reference.append(probs)
    if len(reference) < min_other_books:
        return ConsensusResult(
            "insufficient_evidence",
            candidate.market_type,
            len(reference),
            [],
            f"needs {min_other_books} other books, has {len(reference)}",
        )

    gaps: list[dict[str, float | str]] = []
    for label, probability in candidate_probs.items():
        median = statistics.median(item[label] for item in reference)
        gap = probability - median
        if abs(gap) > threshold:
            gaps.append(
                {
                    "label": label,
                    "prob": round(probability, 4),
                    "median_others": round(median, 4),
                    "gap": round(gap, 4),
                }
            )
    if gaps:
        return ConsensusResult(
            "outlier",
            candidate.market_type,
            len(reference),
            gaps,
            f"{len(gaps)} outcome(s) outside {threshold}",
        )
    return ConsensusResult(
        "accepted",
        candidate.market_type,
        len(reference),
        [],
        f"all outcomes within {threshold} of {len(reference)} books",
    )
