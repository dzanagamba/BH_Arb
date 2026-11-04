"""Opportunity-rate measurements and crossing lifetimes (P0-6).

The engine prices boards; this module counts what that pricing path saw without
recomputing a second arb formula. A board is one priced market instance for one
event: the best cross-book combination for a market type, line, period and
settlement. `find_surebets` appends a `BoardObservation` for every board it
evaluates, and the server turns those observations into a compact per-scan
summary.

Only aggregates and crossing keys are persisted. The full board set stays in
the scan cache that already holds it.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from models.schemas import MatchGroup

# Bounded storage. A 7-day retention plus a hard key cap keeps the lifetime
# store small even after many scans; the cap is far above a normal day's
# crossings and only drops the oldest disappeared keys first.
LIFETIME_RETENTION = timedelta(days=7)
LIFETIME_MAX_KEYS = 5_000


@dataclass(frozen=True)
class BoardObservation:
    """One board the engine actually evaluated, before display filters."""

    event_key: str
    market_type: str
    line: str
    period: str
    settlement: str
    margin: float
    profit_percent: float
    bookmakers: tuple[str, ...]


@dataclass
class ScanMetrics:
    """Mutable collector passed through one `find_surebets` call."""

    groups_total: int = 0
    groups_verified: int = 0
    groups_stale: int = 0
    groups_expired: int = 0
    groups_unverified: int = 0
    boards: list[BoardObservation] = field(default_factory=list)


def event_identity(group: MatchGroup) -> str:
    """A stable identity for an event across scans.

    A Betradar id is the strongest key and is used when any member carries one.
    Otherwise the canonical fixture plus kickoff minute is the fallback; the
    minute is stable across scans while still separating same-day doubleheaders
    better than a date alone.
    """
    ids = sorted({m.betradar_id for m in group.matches if m.betradar_id})
    if ids:
        return f"betradar:{ids[0]}"
    kickoff = group.kickoff.isoformat(timespec="minutes") if group.kickoff else ""
    return "|".join(
        (group.sport, group.canonical_home, group.canonical_away, group.league, kickoff)
    )


def board_key(observation: BoardObservation) -> str:
    """Stable key: event + market + line + period + settlement."""
    return "|".join(
        (
            observation.event_key,
            observation.market_type,
            observation.line,
            observation.period,
            observation.settlement,
        )
    )


def _rate_percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 2)


def _zero_result_reason(
    metrics: ScanMetrics,
    boards: int,
    crossed: int,
    crossed_above_floor: int,
    actionable: int,
) -> str:
    if actionable > 0:
        return "actionable"
    if boards == 0:
        if metrics.groups_stale > 0:
            return "stale_data"
        if metrics.groups_expired > 0:
            return "expired_data"
        if metrics.groups_total > 0 and metrics.groups_unverified == metrics.groups_total:
            return "unverified_data"
        return "no_priced_boards"
    if crossed == 0:
        return "no_crossing"
    if crossed_above_floor == 0:
        return "crossing_below_floor"
    return "crossing_guarded"


def summarize_scan(
    metrics: ScanMetrics,
    surebets: list[Any],
    price_dropped: list[Any],
    *,
    mode: str,
    scan_time: datetime,
    floor_profit_percent: float,
) -> dict[str, Any]:
    """Turn one scan's board observations into the compact denominator report."""
    boards = metrics.boards
    margins = [board.margin for board in boards]
    profits = [board.profit_percent for board in boards]
    crossed = sum(1 for profit in profits if profit > 0)
    crossed_above_floor = sum(1 for profit in profits if profit >= floor_profit_percent)
    actionable = len(surebets)

    summary: dict[str, Any] = {
        "mode": mode,
        "scan_time": scan_time.isoformat(),
        "floor_profit_percent": floor_profit_percent,
        "groups": {
            "total": metrics.groups_total,
            "verified": metrics.groups_verified,
            "stale": metrics.groups_stale,
            "expired": metrics.groups_expired,
            "unverified": metrics.groups_unverified,
        },
        "boards": len(boards),
        "crossed": crossed,
        "crossed_above_floor": crossed_above_floor,
        "actionable": actionable,
        "price_guard_dropped": len(price_dropped),
        "crossing_rate_percent": _rate_percent(crossed, len(boards)),
        "floor_crossing_rate_percent": _rate_percent(crossed_above_floor, len(boards)),
        "actionable_rate_percent": _rate_percent(actionable, len(boards)),
        "median_margin": round(statistics.median(margins), 4) if margins else None,
        "best_margin": round(min(margins), 4) if margins else None,
        "median_profit_percent": round(statistics.median(profits), 2) if profits else None,
        "best_profit_percent": round(max(profits), 2) if profits else None,
    }
    summary["zero_result_reason"] = _zero_result_reason(
        metrics, len(boards), crossed, crossed_above_floor, actionable
    )
    return summary


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def update_lifetimes(
    tracked: dict[str, dict[str, Any]],
    boards: list[BoardObservation],
    now: datetime,
    *,
    retention: timedelta = LIFETIME_RETENTION,
    max_keys: int = LIFETIME_MAX_KEYS,
) -> dict[str, dict[str, Any]]:
    """Update first/last crossing and disappearance times for this scan.

    A key enters the store only when it crossed (profit > 0). A tracked key that
    is present but no longer crosses, or is absent entirely, gets a
    `disappeared_at` timestamp; the first one is kept so a later reappearance
    does not rewrite history.
    """
    now_iso = now.isoformat()
    seen = {board_key(board): board for board in boards}
    current_crossed = {
        key: board for key, board in seen.items() if board.profit_percent > 0
    }

    for key in seen:
        record = tracked.get(key)
        if record is not None:
            record["last_seen_at"] = now_iso

    for key, board in current_crossed.items():
        record = tracked.get(key)
        if record is None:
            record = {
                "first_crossed_at": now_iso,
                "last_crossed_at": now_iso,
                "last_seen_at": now_iso,
                "disappeared_at": None,
                "market_type": board.market_type,
                "line": board.line,
                "period": board.period,
                "settlement": board.settlement,
            }
            tracked[key] = record
        record["last_crossed_at"] = now_iso
        record["last_seen_at"] = now_iso
        record["disappeared_at"] = None
        record["last_margin"] = round(board.margin, 4)
        record["last_profit_percent"] = round(board.profit_percent, 2)

    for key, record in tracked.items():
        if key not in current_crossed and record.get("disappeared_at") is None:
            record["disappeared_at"] = now_iso

    cutoff = (now - retention).isoformat()
    expired = [
        key
        for key, record in tracked.items()
        if record.get("disappeared_at") and record["disappeared_at"] < cutoff
    ]
    for key in expired:
        tracked.pop(key, None)

    if len(tracked) > max_keys:
        keep = sorted(
            tracked.items(),
            key=lambda item: item[1].get("last_seen_at") or "",
            reverse=True,
        )[:max_keys]
        tracked.clear()
        tracked.update(keep)
    return tracked


def lifetime_distribution(
    tracked: dict[str, dict[str, Any]], now: datetime
) -> dict[str, Any]:
    """p50/p90 lifetime over the bounded crossing-key store.

    A still-live crossing contributes the time it has survived so far. A
    disappeared one stops at `disappeared_at`. Samples and the alive count are
    reported so a percentile is never read without its denominator.
    """
    lifetimes: list[float] = []
    alive = 0
    for record in tracked.values():
        try:
            first = datetime.fromisoformat(record["first_crossed_at"])
            end = (
                datetime.fromisoformat(record["disappeared_at"])
                if record.get("disappeared_at")
                else now
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not record.get("disappeared_at"):
            alive += 1
        lifetimes.append(max(0.0, (end - first).total_seconds()))

    return {
        "samples": len(lifetimes),
        "alive": alive,
        "p50_sec": _percentile(lifetimes, 0.50),
        "p90_sec": _percentile(lifetimes, 0.90),
        "max_sec": max(lifetimes) if lifetimes else None,
    }
