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


def push_history(
    history: list[dict[str, int]],
    current: dict[str, int],
    *,
    max_scans: int = HISTORY_SCANS,
) -> list[dict[str, int]]:
    history.append(dict(current))
    return history[-max_scans:]
