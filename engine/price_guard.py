"""Drop a surebet whose leg is a price outlier against the other books.

A mapping mistake, a swapped label or a book's genuinely broken line can make a
surebet look real. The engine already refuses implausible margins; this guard
checks each leg against the other books' de-vigged price for the same market and
drops the opportunity when the leg is an outlier. The scan reports the drop
instead of showing a bet that cannot be placed.
"""

from __future__ import annotations

from engine.market_consensus import find_outliers


def filter_price_outliers(surebets, groups, threshold: float = 0.10):
    """Return (kept, dropped) where dropped carries the outlier row."""
    outliers, _ = find_outliers(groups, threshold)
    if not outliers:
        return list(surebets), []

    kept = []
    dropped = []
    for surebet in surebets:
        match = f"{surebet.home_team} - {surebet.away_team}"
        reason = None
        for row in outliers:
            if row["match"] != match or row["market"] != surebet.market_type.value:
                continue
            for stake in surebet.stakes:
                if (
                    stake.outcome_label == row["label"]
                    and stake.bookmaker in str(row["bookmaker"]).split("+")
                ):
                    reason = row
                    break
            if reason:
                break
        if reason:
            dropped.append({"surebet": surebet, "outlier": reason})
        else:
            kept.append(surebet)
    return kept, dropped
