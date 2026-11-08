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


# ---- SR4-5: event/market cardinality floors --------------------------------
#
# The row-level budget above asks "did a market family disappear?". This asks
# "did the whole feed thin out?", per book and sport: how many events it
# published and how many markets those events carried. The floor reuses the
# same rolling-median history shape and, on a flag, the scan quarantines the
# book through the existing feed-integrity state machine (not a second gate).

CARDINALITY_HISTORY_SCANS = 20
# A baseline thinner than this is too small to call a drop.
CARDINALITY_MIN_BASELINE_EVENTS = 10
CARDINALITY_DROP_RATIO = 0.50
CARDINALITY_DROP_ABSOLUTE = 5
# Markets per event is a ratio, so it needs its own absolute guard.
CARDINALITY_MARKET_RATIO = 0.50
CARDINALITY_MARKET_ABSOLUTE = 2.0


def cardinality_snapshot(matches: list[Match]) -> dict[str, dict[str, int]]:
    """Events and market rows per ``book|sport`` for one scan."""
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"events": 0, "markets": 0}
    )
    for match in matches:
        key = f"{match.bookmaker}|{match.sport}"
        counts[key]["events"] += 1
        counts[key]["markets"] += len(match.markets)
    return {key: dict(value) for key, value in counts.items()}


def _cardinality_median(
    history: list[dict[str, dict[str, int]]], key: str, field: str
) -> float:
    return _median([int(sample.get(key, {}).get(field, 0)) for sample in history])


def evaluate_cardinality(
    current: dict[str, dict[str, int]],
    history: list[dict[str, dict[str, int]]],
    *,
    min_baseline_events: int = CARDINALITY_MIN_BASELINE_EVENTS,
    drop_ratio: float = CARDINALITY_DROP_RATIO,
    drop_absolute: int = CARDINALITY_DROP_ABSOLUTE,
    market_ratio: float = CARDINALITY_MARKET_RATIO,
    market_absolute: float = CARDINALITY_MARKET_ABSOLUTE,
) -> dict[str, Any]:
    """Compare one scan's event/market counts with the rolling median.

    A drop is only called when a peer book still publishes that sport in the
    same scan, so a shared calendar dip (or an off-season night) is not a
    broken feed. A thin market set is flagged separately from a thin event
    list, because losing half the markets per event still prices a feed.
    """
    keys = sorted({key for sample in history for key in sample} | set(current))
    books_by_sport: dict[str, dict[str, int]] = defaultdict(dict)
    for key in keys:
        book, _, sport = key.partition("|")
        books_by_sport[sport][book] = int(
            current.get(key, {}).get("events", 0)
        )

    def peer_events_for(book: str, sport: str) -> int:
        """Current events from peers that are themselves near their baseline.

        A peer that dropped with the book is a shared calendar dip, not
        evidence that the book alone is broken. A peer with no usable baseline
        counts when it still returns events.
        """
        total = 0
        for other, observed in books_by_sport.get(sport, {}).items():
            if other == book or observed <= 0:
                continue
            peer_baseline = _cardinality_median(
                history, f"{other}|{sport}", "events"
            )
            if peer_baseline >= min_baseline_events and observed < (
                peer_baseline * drop_ratio
            ):
                continue
            total += observed
        return total

    flags: list[dict[str, Any]] = []
    for key in keys:
        book, _, sport = key.partition("|")
        baseline_events = _cardinality_median(history, key, "events")
        baseline_markets = _cardinality_median(history, key, "markets")
        observed_events = int(current.get(key, {}).get("events", 0))
        observed_markets = int(current.get(key, {}).get("markets", 0))
        if baseline_events < min_baseline_events:
            continue
        peer_events = peer_events_for(book, sport)
        if not peer_events:
            continue
        if (
            observed_events < baseline_events * drop_ratio
            and baseline_events - observed_events >= drop_absolute
        ):
            flags.append(
                {
                    "bookmaker": book,
                    "sport": sport,
                    "kind": "event_drop",
                    "observed": observed_events,
                    "baseline": round(baseline_events, 1),
                    "drop_ratio": round(
                        1 - observed_events / baseline_events, 4
                    ),
                    "peer_events": peer_events,
                }
            )
            continue
        if observed_events == 0 or baseline_markets <= 0:
            continue
        baseline_per_event = baseline_markets / baseline_events
        observed_per_event = observed_markets / observed_events
        if (
            observed_per_event < baseline_per_event * market_ratio
            and baseline_per_event - observed_per_event >= market_absolute
        ):
            flags.append(
                {
                    "bookmaker": book,
                    "sport": sport,
                    "kind": "market_thin",
                    "observed": observed_markets,
                    "observed_per_event": round(observed_per_event, 2),
                    "baseline_per_event": round(baseline_per_event, 2),
                    "peer_events": peer_events,
                }
            )
    return {
        "flags": flags,
        "flag_count": len(flags),
        "baseline_scans": len(history),
        "min_baseline_events": min_baseline_events,
        "drop_ratio": drop_ratio,
        "drop_absolute": drop_absolute,
        "market_ratio": market_ratio,
        "market_absolute": market_absolute,
        "counts": current,
    }


def push_cardinality_history(
    history: list[dict[str, dict[str, int]]],
    current: dict[str, dict[str, int]],
    *,
    max_scans: int = CARDINALITY_HISTORY_SCANS,
) -> list[dict[str, dict[str, int]]]:
    history.append({key: dict(value) for key, value in current.items()})
    return history[-max_scans:]


def cardinality_book_reasons(report: dict[str, Any]) -> dict[str, list[str]]:
    """The quarantine reason per flagged book, for feed integrity.

    One reason covers both kinds: a book below its event or market floor is
    not a usable price source this scan, and the existing recovery streak
    decides when it may return.
    """
    reasons: dict[str, list[str]] = defaultdict(list)
    for flag in report.get("flags") or []:
        book = str(flag.get("bookmaker") or "")
        if book and "cardinality_drop" not in reasons[book]:
            reasons[book].append("cardinality_drop")
    return dict(reasons)
