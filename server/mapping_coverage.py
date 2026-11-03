"""Read-only mapping coverage for the Diagnostics tab.

The report answers three questions a human no longer has to answer by clicking
through a review queue: what the ledger currently believes, what it has
quarantined and why, and which book/market rows are still unmapped. It never
changes a claim.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from engine.mapping_evidence import MappingLedger
from models.schemas import Match


def build_coverage(
    ledger: MappingLedger,
    matches: list[Match],
    groups: list[dict[str, Any]],
    *,
    mode: str,
    unmapped_markets: dict[str, int] | None = None,
) -> dict[str, Any]:
    per_book: dict[str, dict[str, int]] = {}
    for match in matches:
        book = per_book.setdefault(match.bookmaker, {"matches": 0, "markets": 0})
        book["matches"] += 1
        book["markets"] += len(match.markets)

    status_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    quarantined: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for claim in ledger.claims.values():
        status_counts[claim.status] += 1
        kind_counts[claim.kind] += 1
        if claim.status == "quarantined":
            quarantined.append(
                {
                    "kind": claim.kind,
                    "key": claim.key,
                    "reason": claim.reason,
                    "evidence_types": sorted({item.type for item in claim.evidence}),
                }
            )
        elif claim.status == "accepted" and claim.is_stale():
            stale.append({"kind": claim.kind, "key": claim.key, "last_seen": claim.last_seen})

    return {
        "mode": mode,
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "books": per_book,
        "groups": {
            "total": len(groups),
            "verified": sum(1 for group in groups if group.get("status") == "verified"),
        },
        "claims": {
            "total": len(ledger.claims),
            "by_status": dict(sorted(status_counts.items())),
            "by_kind": dict(sorted(kind_counts.items())),
        },
        "quarantined": sorted(quarantined, key=lambda item: (item["kind"], item["key"])),
        "stale": sorted(stale, key=lambda item: (item["kind"], item["key"])),
        "unmapped_markets": dict(sorted((unmapped_markets or {}).items())),
    }
