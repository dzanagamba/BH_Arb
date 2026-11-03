"""Resolve a new book's raw offers into typed markets.

The adapter emits ``RawOffer`` records with the book's own keys and labels. This
module classifies each offer and, when reference markets from other books are
available, checks the result against their de-vigged prices. An offer with an
unknown label set, or one that disagrees with every other book, is dropped and
reported by the caller as a gap — never guessed into a market.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.market_consensus import compare
from engine.market_discovery import classify
from models.schemas import Market, RawOffer


@dataclass
class ResolvedOffer:
    offer: RawOffer
    market: Market | None
    reason: str
    gaps: list[dict[str, float | str]] = field(default_factory=list)


def resolve_offers(
    offers: list[RawOffer],
    references: list[Market] | None = None,
) -> list[ResolvedOffer]:
    resolved: list[ResolvedOffer] = []
    for offer in offers:
        classification = classify(
            offer.labels,
            line=offer.line,
            period=offer.period,
            market_key=offer.market_key,
        )
        if classification is None:
            resolved.append(ResolvedOffer(offer, None, "unclassified_labels"))
            continue
        market = Market(
            market_type=classification.market_type,
            odds=list(offer.odds),
            source_id=offer.source_id,
        )
        if references:
            result = compare(market, references)
            if result.status == "insufficient_evidence":
                resolved.append(ResolvedOffer(offer, None, "insufficient_evidence"))
                continue
            if result.status == "outlier":
                resolved.append(ResolvedOffer(offer, None, "price_outlier", result.gaps))
                continue
        resolved.append(ResolvedOffer(offer, market, "accepted"))
    return resolved
