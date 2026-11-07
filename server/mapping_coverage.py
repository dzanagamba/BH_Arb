"""Read-only mapping coverage for the Diagnostics tab.

The report answers three questions a human no longer has to answer by clicking
through a review queue: what the ledger currently believes, what it has
quarantined and why, and which book/market rows are still unmapped. It never
changes a claim.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine import mapping_evidence
from engine.mapping_evidence import MappingLedger
from models.schemas import Match

# Parsing the 60 MB evidence ledger for every diagnostics request is wasted
# work when the file has not changed. Key the parsed ledger by path, mtime and
# size; a write or a different test path reloads it.
_LEDGER_CACHE: dict[str, tuple[tuple[str, int, int, int, int], MappingLedger]] = {}


def load_ledger(path: str | Path | None = None) -> MappingLedger:
    """Load the evidence ledger, reusing the last parse while the file is unchanged."""
    target = Path(path) if path is not None else mapping_evidence.DEFAULT_PATH
    try:
        stat = target.stat()
        stamp = (str(target), stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    except OSError:
        _LEDGER_CACHE.pop(str(target), None)
        return MappingLedger(target).load()
    cached = _LEDGER_CACHE.get(str(target))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    ledger = MappingLedger(target).load()
    _LEDGER_CACHE[str(target)] = (stamp, ledger)
    return ledger


def _field(row: Match | dict[str, Any], name: str) -> Any:
    """Read one field from a restored cache row or a live match model."""
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def build_coverage(
    ledger: MappingLedger,
    matches: list[Match | dict[str, Any]],
    groups: list[dict[str, Any]],
    *,
    mode: str,
    unmapped_markets: dict[str, int] | None = None,
) -> dict[str, Any]:
    per_book: dict[str, dict[str, int]] = {}
    for match in matches:
        bookmaker = _field(match, "bookmaker")
        markets = _field(match, "markets") or []
        book = per_book.setdefault(bookmaker, {"matches": 0, "markets": 0})
        book["matches"] += 1
        book["markets"] += len(markets)

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
