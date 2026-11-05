"""Automatic closing-line capture for logged bets (N0-4).

A closing line is the last price available for a leg before its event starts. It
is a measurement, not a settlement: the scanner never places a bet and never
infers a result. This module matches an open bet's event, market, line,
settlement and outcome against the scan's verified groups, and returns the
payload updates the bet store writes.

The matching is deliberately exact. A missing price, a different settlement, a
different line, a book that is no longer in the scan, or an event that has
already kicked off all leave CLV null and record a reason. A manual closing
entry is never overwritten by a scan.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from engine.destinations import selection_line
from engine.opportunity_metrics import event_identity
from models.schemas import Market, Match, MatchGroup

REASON_NO_KICKOFF = "no_kickoff"
REASON_AFTER_CUTOFF = "after_kickoff"
REASON_EVENT_NOT_FOUND = "event_not_in_scan"
REASON_BOOK_NOT_FOUND = "book_not_in_scan"
REASON_BOOK_QUARANTINED = "book_quarantined"
REASON_MARKET_NOT_OFFERED = "market_not_offered"
REASON_SETTLEMENT_MISMATCH = "settlement_mismatch"
REASON_LINE_MISMATCH = "line_mismatch"
REASON_OUTCOME_NOT_OFFERED = "outcome_not_offered"
REASON_STALE_PRICE = "stale_price"
DEFAULT_SETTLEMENT = "full_time"


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _parse_kickoff(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _naive(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _naive(parsed)


def _market_types(bet_market: str, leg_market: str) -> tuple[str, ...]:
    market_type = (leg_market or bet_market or "").strip().lower()
    if not market_type:
        return ()
    if market_type == "double_chance":
        # A cross-market DC surebet may take a leg from the book's 1X2 market.
        return ("double_chance", "1x2")
    return (market_type,)


def _event_matches(bet: dict[str, Any], group: MatchGroup) -> bool:
    if group.status != "verified":
        return False
    event_key = str(bet.get("event_key") or "")
    if event_key:
        return event_identity(group) == event_key
    sport = str(bet.get("sport") or "football")
    if sport != group.sport:
        return False
    kickoff = _parse_kickoff(bet.get("kickoff"))
    if kickoff is None or group.kickoff is None or kickoff != _naive(group.kickoff):
        return False
    home = str(bet.get("home_team") or "").strip().casefold()
    away = str(bet.get("away_team") or "").strip().casefold()
    return (
        home == group.canonical_home.strip().casefold()
        and away == group.canonical_away.strip().casefold()
    )


def _find_market(
    match: Match,
    market_types: tuple[str, ...],
    label: str,
    settlement: str,
) -> tuple[Market | None, str]:
    """Return (market, reason). The reason is empty when a market was found."""
    saw_type = False
    saw_label = False
    saw_settlement = False
    saw_stale = False
    for market in match.markets:
        if market.market_type.value not in market_types:
            continue
        saw_type = True
        market_settlement = market.settlement or DEFAULT_SETTLEMENT
        if market_settlement != settlement:
            saw_settlement = True
            continue
        if market.stale_price:
            saw_stale = True
            continue
        if not any(odd.label == label and odd.value > 1.0 for odd in market.odds):
            continue
        saw_label = True
        return market, ""
    if saw_settlement:
        return None, REASON_SETTLEMENT_MISMATCH
    if saw_stale:
        return None, REASON_STALE_PRICE
    if saw_type and not saw_label:
        return None, REASON_OUTCOME_NOT_OFFERED
    return None, REASON_MARKET_NOT_OFFERED


def _capture_leg(
    bet: dict[str, Any],
    leg: dict[str, Any],
    group: MatchGroup | None,
    *,
    excluded_books: set[str],
) -> tuple[float | None, str]:
    """Return (closing price, reason). A non-empty reason means no price."""
    if str(leg.get("closing_source") or "") == "manual":
        return None, ""
    bookmaker = str(leg.get("bookmaker") or "")
    if bookmaker in excluded_books:
        return None, REASON_BOOK_QUARANTINED
    if group is None:
        return None, REASON_EVENT_NOT_FOUND
    match = next((item for item in group.matches if item.bookmaker == bookmaker), None)
    if match is None:
        return None, REASON_BOOK_NOT_FOUND

    label = str(leg.get("outcome_label") or "")
    settlement = str(leg.get("settlement") or DEFAULT_SETTLEMENT)
    market_types = _market_types(
        str(bet.get("market_type") or ""), str(leg.get("market_type") or "")
    )
    if not market_types:
        return None, REASON_MARKET_NOT_OFFERED

    market, reason = _find_market(match, market_types, label, settlement)
    if market is None:
        return None, reason

    line = str(leg.get("line") or "")
    if line:
        actual_line = selection_line(label)
        if actual_line != line:
            return None, REASON_LINE_MISMATCH

    for odd in market.odds:
        if odd.label == label and odd.value > 1.0:
            return float(odd.value), ""
    return None, REASON_OUTCOME_NOT_OFFERED


def capture_bet_closing(
    bet: dict[str, Any],
    groups: list[MatchGroup],
    *,
    now: datetime,
    mode: str = "prematch",
    cutoff_minutes: int = 0,
    excluded_books: set[str] | None = None,
) -> tuple[dict[str, Any], bool, dict[str, int]]:
    """Return (payload, changed, stats) for one bet.

    A settled bet is never touched: a closing price cannot be inferred after
    settlement. A manual closing entry is left as-is and labelled ``manual``.
    """
    stats = {"legs_total": 0, "legs_captured": 0, "legs_missing": 0}
    payload = dict(bet)
    legs = payload.get("legs") or []
    stats["legs_total"] = len(legs)
    if str(payload.get("status") or "open") != "open":
        return payload, False, stats
    if str(payload.get("mode") or "prematch") != mode:
        return payload, False, stats

    excluded = excluded_books or set()
    reference = _naive(now)
    kickoff = _parse_kickoff(payload.get("kickoff"))
    group: MatchGroup | None = None
    if kickoff is not None:
        deadline = kickoff - timedelta(minutes=max(0, cutoff_minutes))
        if reference > deadline:
            group = None
        else:
            group = next(
                (item for item in groups if _event_matches(payload, item)),
                None,
            )
    after_cutoff = kickoff is not None and reference > (
        kickoff - timedelta(minutes=max(0, cutoff_minutes))
    )

    changed = False
    new_legs: list[dict[str, Any]] = []
    for leg in legs:
        current = dict(leg)
        price: float | None = None
        if kickoff is None:
            reason = REASON_NO_KICKOFF
        elif after_cutoff:
            reason = REASON_AFTER_CUTOFF
        else:
            price, reason = _capture_leg(
                payload, current, group, excluded_books=excluded
            )
        if price is not None:
            current["closing_odds"] = price
            current["closing_source"] = "scan"
            current["closing_captured_at"] = reference.isoformat(timespec="seconds")
            current["closing_scan_time"] = reference.isoformat(timespec="seconds")
            current["closing_reason"] = ""
            stats["legs_captured"] += 1
            changed = changed or current != leg
        else:
            if current.get("closing_odds") is None:
                stats["legs_missing"] += 1
                if reason:
                    current["closing_reason"] = reason
                    changed = changed or current != leg
            # An existing scan closing is frozen; keep it and its empty reason.
        new_legs.append(current)
    if new_legs:
        payload["legs"] = new_legs
    return payload, changed, stats


def capture_closing(
    bets: list[dict[str, Any]],
    groups: list[MatchGroup],
    *,
    now: datetime,
    mode: str = "prematch",
    cutoff_minutes: int = 0,
    excluded_books: set[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Capture closing lines for every open bet of one mode.

    Returns (payload updates keyed by bet id, aggregate stats). Bets of the
    other mode and settled bets are skipped, so a live scan cannot rewrite a
    prematch bet's closing line.
    """
    updates: dict[str, dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    stats: dict[str, Any] = {
        "bets_checked": 0,
        "bets_updated": 0,
        "legs_total": 0,
        "legs_captured": 0,
        "legs_missing": 0,
        "reasons": {},
    }
    for bet in bets:
        if str(bet.get("status") or "open") != "open":
            continue
        if str(bet.get("mode") or "prematch") != mode:
            continue
        stats["bets_checked"] += 1
        payload, changed, leg_stats = capture_bet_closing(
            bet,
            groups,
            now=now,
            mode=mode,
            cutoff_minutes=cutoff_minutes,
            excluded_books=excluded_books,
        )
        for key in ("legs_total", "legs_captured", "legs_missing"):
            stats[key] += leg_stats[key]
        for leg in payload.get("legs") or []:
            reason = str(leg.get("closing_reason") or "")
            if reason and leg.get("closing_odds") is None:
                reasons[reason] += 1
        if changed:
            bet_id = str(payload.get("id") or "")
            if bet_id:
                updates[bet_id] = payload
                stats["bets_updated"] += 1
    stats["reasons"] = dict(sorted(reasons.items()))
    return updates, stats
