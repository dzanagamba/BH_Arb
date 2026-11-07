"""Frozen-price quarantine (N0-2).

``fetched_at`` answers "when did we collect this row?". This module answers a
different question: "does the book's own feed show that this price is still
moving?" A book can serve a frozen market with a perfectly fresh ``fetched_at``;
that is the classic phantom-arbitrage source.

Two rules can refuse a row, and neither is a trust decision:

* the feed publishes ``source_updated_at`` and it is older than the mode's
  freshness budget; or
* the price has not moved for ``STALE_PRICE_UNCHANGED_SCANS`` scans while at
  least one independent peer (a different price source) did move.

A missing source timestamp never makes a row look fresh. It simply leaves the
existing ``fetched_at`` TTL in charge. A market whose prices and peers are both
stable is normal and is never quarantined.

The per-book observation store is bounded and keyed by event, market, line,
settlement and outcome. It is runtime state, not a trust record: losing it only
means the frozen rule needs a few scans to re-establish its baseline.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from config.settings import (
    STALE_PRICE_MAX_ROWS,
    STALE_PRICE_RETENTION_SECONDS,
    STALE_PRICE_UNCHANGED_SCANS,
    price_source,
)
from engine.opportunity_metrics import event_identity
from models.schemas import Market, Match, MatchGroup, OddsValue

REASON_SOURCE_TIMESTAMP = "source_timestamp_stale"
REASON_FROZEN = "frozen_while_peers_moved"
REASON_LABEL = "price frozen"
PRICE_EPSILON = 1e-9


@dataclass
class StalePriceResult:
    """One scan's observation update and the rows it refused."""

    store: dict[str, dict[str, Any]]
    evidence: list[dict[str, Any]]
    by_book: dict[str, int]
    checked_at: datetime


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _iso(value: datetime | None) -> str:
    return _naive(value).isoformat() if value is not None else ""


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _naive(parsed)


def _age_seconds(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    return (now - _naive(value)).total_seconds()


def _board_key(
    event: str,
    market: str,
    settlement: str,
    period: str,
    label: str,
) -> str:
    return "|".join((event, market, settlement, period, label))


def _row_key(bookmaker: str, board: str) -> str:
    return f"{bookmaker}|{board}"


def _source_updated_at(match: Match, market: Market, odd: OddsValue) -> datetime | None:
    """The feed's own timestamp, most specific source first.

    An outcome timestamp wins over a market timestamp, which wins over a match
    timestamp. Empty stays empty: the scan clock is never used as a substitute.
    """
    return (
        odd.source_updated_at
        or market.source_updated_at
        or match.source_updated_at
    )


def _prune(
    rows: dict[str, dict[str, Any]],
    now: datetime,
    *,
    max_rows: int,
    retention_seconds: int,
    observed_keys: set[str] | None = None,
    new_keys: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    cutoff = now - timedelta(seconds=max(1, retention_seconds))
    kept: dict[str, dict[str, Any]] = {}
    for key, row in rows.items():
        seen = _parse_iso(row.get("last_seen_at"))
        if seen is None or seen < cutoff:
            continue
        kept[key] = row
    if len(kept) <= max_rows:
        return kept
    # A row observed by the current scan must keep its baseline: it is either
    # new (and the frozen rule needs it) or the row whose history is being
    # updated. A brand-new board outranks a known one because every row seen in
    # this scan shares one second-resolution timestamp; without the extra rank
    # stable sort would keep the restored insertion order and drop the new key.
    # Rows this scan did not see are evicted oldest first.
    observed = observed_keys or set()
    new = new_keys or set()
    newest = sorted(
        kept.items(),
        key=lambda item: (
            item[0] in observed,
            item[0] in new,
            str(item[1].get("last_seen_at") or ""),
        ),
        reverse=True,
    )[:max_rows]
    return dict(newest)


def _mark_stale(
    odd: OddsValue,
    market: Market,
    reasons: list[str],
) -> None:
    reason_text = ",".join(reasons)
    odd.stale_price = True
    odd.stale_reason = reason_text
    market.stale_price = True
    existing = [item for item in market.stale_reason.split(",") if item]
    market.stale_reason = ",".join(dict.fromkeys([*existing, *reasons]))


def evaluate_stale_prices(
    groups: list[MatchGroup],
    previous: dict[str, dict[str, Any]] | None = None,
    *,
    mode: str = "prematch",
    now: datetime | None = None,
    ttl_sec: int,
    unchanged_scans: int | None = None,
    max_rows: int | None = None,
    retention_seconds: int | None = None,
) -> StalePriceResult:
    """Update the per-book observation store and mark refused rows.

    The caller must price only markets whose ``stale_price`` is false. The
    returned evidence is the diagnostic surface for ``/api/results``,
    ``/api/health`` and feed integrity.
    """
    reference = _naive(now or datetime.now(UTC))
    threshold = max(
        1, unchanged_scans if unchanged_scans is not None else STALE_PRICE_UNCHANGED_SCANS
    )
    row_cap = max(1, max_rows if max_rows is not None else STALE_PRICE_MAX_ROWS)
    retention = (
        retention_seconds
        if retention_seconds is not None
        else STALE_PRICE_RETENTION_SECONDS
    )
    previous = previous or {}

    # Previous board prices, one entry per price source. Two books on one feed
    # are one price: a twin moving is not independent peer movement.
    previous_board: dict[str, dict[str, float]] = defaultdict(dict)
    for row in previous.values():
        if not isinstance(row, dict):
            continue
        board = row.get("board")
        source = row.get("price_source") or row.get("bookmaker")
        price = row.get("last_price")
        if isinstance(board, str) and isinstance(source, str) and isinstance(price, int | float):
            previous_board[board][source] = float(price)

    observations: list[dict[str, Any]] = []
    current_board: dict[str, dict[str, float]] = defaultdict(dict)
    for group in groups:
        event = event_identity(group)
        match_name = f"{group.canonical_home} - {group.canonical_away}"
        for match in group.matches:
            for market in match.markets:
                settlement = market.settlement or "full_time"
                period = market.period or "full_time"
                for odd in market.odds:
                    if odd.value <= 1.0:
                        continue
                    board = _board_key(
                        event,
                        market.market_type.value,
                        settlement,
                        period,
                        odd.label,
                    )
                    source = price_source(match.bookmaker)
                    current_board[board][source] = float(odd.value)
                    observations.append(
                        {
                            "match": match,
                            "market": market,
                            "odd": odd,
                            "board": board,
                            "bookmaker": match.bookmaker,
                            "price_source": source,
                            "event": event,
                            "match_name": match_name,
                            "market_type": market.market_type.value,
                            "settlement": settlement,
                            "period": period,
                            "label": odd.label,
                            "price": float(odd.value),
                            "source_updated_at": _source_updated_at(match, market, odd),
                            "fetched_at": match.fetched_at,
                        }
                    )

    moved_sources: dict[str, set[str]] = {
        board: {
            source
            for source, price in prices.items()
            if source in previous_board.get(board, {})
            and abs(price - previous_board[board][source]) > PRICE_EPSILON
        }
        for board, prices in current_board.items()
    }

    rows: dict[str, dict[str, Any]] = {
        key: dict(row) for key, row in previous.items() if isinstance(row, dict)
    }
    observed_keys: set[str] = set()
    evidence: list[dict[str, Any]] = []
    by_book: dict[str, int] = defaultdict(int)

    for item in observations:
        board = item["board"]
        key = _row_key(item["bookmaker"], board)
        observed_keys.add(key)
        price = item["price"]
        old = previous.get(key)
        if (
            isinstance(old, dict)
            and isinstance(old.get("last_price"), int | float)
            and abs(price - float(old["last_price"])) <= PRICE_EPSILON
        ):
            unchanged = int(old.get("unchanged_scans") or 0) + 1
            unchanged_since = old.get("unchanged_since") or _iso(reference)
            last_changed_at = old.get("last_changed_at") or _iso(reference)
        else:
            unchanged = 0
            unchanged_since = _iso(reference)
            last_changed_at = _iso(reference)

        source_age = _age_seconds(item["source_updated_at"], reference)
        source_stale = source_age is not None and source_age > ttl_sec
        peer_moved = any(
            source != item["price_source"]
            for source in moved_sources.get(board, set())
        )
        frozen = unchanged >= threshold and peer_moved

        reasons: list[str] = []
        if source_stale:
            reasons.append(REASON_SOURCE_TIMESTAMP)
        if frozen:
            reasons.append(REASON_FROZEN)
        stale = bool(reasons)

        rows[key] = {
            "bookmaker": item["bookmaker"],
            "price_source": item["price_source"],
            "event": item["event"],
            "match": item["match_name"],
            "market": item["market_type"],
            "settlement": item["settlement"],
            "period": item["period"],
            "label": item["label"],
            "board": board,
            "last_price": price,
            "unchanged_scans": unchanged,
            "unchanged_since": unchanged_since,
            "last_changed_at": last_changed_at,
            "last_seen_at": _iso(reference),
            "source_updated_at": _iso(item["source_updated_at"]),
            "fetched_at": _iso(item["fetched_at"]),
        }

        if not stale:
            continue

        _mark_stale(item["odd"], item["market"], reasons)
        by_book[item["bookmaker"]] += 1
        evidence.append(
            {
                "bookmaker": item["bookmaker"],
                "event": item["event"],
                "match": item["match_name"],
                "market": item["market_type"],
                "settlement": item["settlement"],
                "period": item["period"],
                "label": item["label"],
                "price": price,
                "reason": reasons[0],
                "reasons": reasons,
                "reason_label": REASON_LABEL,
                "unchanged_scans": unchanged,
                "unchanged_since": unchanged_since,
                "last_changed_at": last_changed_at,
                "source_updated_at": _iso(item["source_updated_at"]),
                "fetched_at": _iso(item["fetched_at"]),
                "source_age_sec": round(source_age, 1) if source_age is not None else None,
                "peer_moved": peer_moved,
                "threshold_scans": threshold,
                "ttl_sec": ttl_sec,
                "mode": mode,
            }
        )

    return StalePriceResult(
        store=_prune(
            rows,
            reference,
            max_rows=row_cap,
            retention_seconds=retention,
            observed_keys=observed_keys,
            new_keys=observed_keys - set(previous),
        ),
        evidence=evidence,
        by_book=dict(by_book),
        checked_at=reference,
    )
