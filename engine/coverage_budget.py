"""Silent-drop coverage budget (P2-9).

The pairing audit asks "did we miss a pair?". This asks "did we miss a whole
feed?". Counts are compared with a rolling median per book/sport/market, but a
drop is only a failure when peer books still publish that market. A night with
no live games is legitimately empty and must not page anyone.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from models.schemas import Match

MIN_BASELINE_ROWS = 3
DROP_RATIO = 0.50
DROP_ABSOLUTE = 5
HISTORY_SCANS = 20


def snapshot(matches: list[Match]) -> dict[str, int]:
    """Count market rows per book/sport/market family for one scan."""
    counts: dict[str, int] = defaultdict(int)
    for match in matches:
        for market in match.markets:
            key = f"{match.bookmaker}|{match.sport}|{market.market_type.value}"
            counts[key] += 1
    return dict(counts)


def _median(values: list[int]) -> float:
    return float(statistics.median(values)) if values else 0.0


def evaluate(
    current: dict[str, int],
    history: list[dict[str, int]],
    *,
    min_baseline_rows: int = MIN_BASELINE_ROWS,
    drop_ratio: float = DROP_RATIO,
    drop_absolute: int = DROP_ABSOLUTE,
) -> dict[str, Any]:
    """Compare one scan with the rolling median and flag material drops."""
    keys = sorted({key for sample in history for key in sample} | set(current))
    baselines = {
        key: _median([sample.get(key, 0) for sample in history]) for key in keys
    }
    flags: list[dict[str, Any]] = []
    for key in keys:
        book, sport, market = key.split("|", 2)
        baseline = baselines.get(key, 0.0)
        observed = current.get(key, 0)
        if baseline < min_baseline_rows:
            continue
        peers = [
            current.get(f"{other}|{sport}|{market}", 0)
            for other in {
                key.split("|", 1)[0] for sample in history for key in sample
            }
            if other != book
        ]
        peers_populated = any(value > 0 for value in peers)
        peer_rows = sum(peers)
        peer_books = sum(1 for value in peers if value > 0)
        if observed == 0 and peers_populated:
            flags.append(
                {
                    "bookmaker": book,
                    "sport": sport,
                    "market": market,
                    "kind": "silent_zero",
                    "observed": 0,
                    "baseline": round(baseline, 1),
                    "peers_populated": True,
                    "peer_rows": peer_rows,
                    "peer_books": peer_books,
                }
            )
            continue
        if (
            peers_populated
            and observed < baseline * drop_ratio
            and baseline - observed >= drop_absolute
        ):
            flags.append(
                {
                    "bookmaker": book,
                    "sport": sport,
                    "market": market,
                    "kind": "material_drop",
                    "observed": observed,
                    "baseline": round(baseline, 1),
                    "drop_ratio": round(1 - observed / baseline, 4),
                    "peers_populated": True,
                    "peer_rows": peer_rows,
                    "peer_books": peer_books,
                }
            )
    return {
        "flags": flags,
        "flag_count": len(flags),
        "baseline_scans": len(history),
        "min_baseline_rows": min_baseline_rows,
        "drop_ratio": drop_ratio,
        "drop_absolute": drop_absolute,
        "counts": current,
    }


def mapping_coverage(
    matches: list[Match],
    unmapped_before: dict[str, int],
    unmapped_after: dict[str, int],
    *,
    floor: float = 0.95,
    min_rows: int = 20,
) -> dict[str, Any]:
    """Measure how many observed market rows resolved to a known mapping.

    ``unmapped_markets`` is a process-wide cumulative counter, so a scan's own
    unmapped rows are the positive delta between the before/after snapshots.
    The denominator is mapped rows plus those new unmapped rows; a small scan
    stays unjudged until it clears ``min_rows``. A legitimate empty feed has no
    rows and therefore no coverage ratio, not a zero.
    """
    mapped_by_book: dict[str, int] = defaultdict(int)
    for match in matches:
        mapped_by_book[match.bookmaker] += len(match.markets)

    unmapped_by_book: dict[str, int] = defaultdict(int)
    for key, count in unmapped_after.items():
        delta = int(count) - int(unmapped_before.get(key, 0))
        if delta <= 0:
            continue
        book = key.split(":", 1)[0] or "unknown"
        unmapped_by_book[book] += delta

    per_book: dict[str, dict[str, Any]] = {}
    for book in sorted(set(mapped_by_book) | set(unmapped_by_book)):
        mapped = int(mapped_by_book.get(book, 0))
        unmapped = int(unmapped_by_book.get(book, 0))
        total = mapped + unmapped
        ratio = round(mapped / total, 4) if total else None
        per_book[book] = {
            "mapped": mapped,
            "unmapped": unmapped,
            "total": total,
            "coverage": ratio,
            "below_floor": bool(
                total >= min_rows and ratio is not None and ratio < floor
            ),
        }

    numerator = sum(mapped_by_book.values())
    unmapped_total = sum(unmapped_by_book.values())
    denominator = numerator + unmapped_total
    ratio = round(numerator / denominator, 4) if denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "unmapped_total": unmapped_total,
        "coverage": ratio,
        "floor": floor,
        "min_rows": min_rows,
        "below_floor": bool(
            denominator >= min_rows and ratio is not None and ratio < floor
        ),
        "per_book": per_book,
        "unmapped_by_book": dict(sorted(unmapped_by_book.items())),
    }


def push_history(
    history: list[dict[str, int]],
    current: dict[str, int],
    *,
    max_scans: int = HISTORY_SCANS,
) -> list[dict[str, int]]:
    history.append(dict(current))
    return history[-max_scans:]
