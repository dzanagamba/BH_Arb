"""Raw-price and stake-rounding invariants (P1-7).

The dashboard must be recomputable from the odds the API served. This module is
the one place that derives the implied sum and the difference between exact and
realized profit, so the engine, the recalculate endpoint and tests cannot drift
into three subtly different formulas.

It is a consistency layer, not a new pricing model: the stake split and the
arbitrage decision still belong to ``engine.arbitrage``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

RoundingMode = Literal["exact", "1", "5"]


def implied_sum(odds: Sequence[float]) -> float:
    """Exact ``sum(1/odds)`` for the served legs."""
    return sum(1.0 / float(value) for value in odds)


def exact_profit_percent(odds: Sequence[float]) -> float:
    """Profit percent implied by the served odds, before stake rounding."""
    margin = implied_sum(odds)
    if margin <= 0:
        return 0.0
    return (1.0 / margin - 1.0) * 100.0


def round_stake(value: float, rounding: RoundingMode | str = "exact") -> float:
    """Round a stake with the same three modes the dashboard offers."""
    if rounding == "1":
        return float(round(value))
    if rounding == "5":
        return float(round(value / 5.0) * 5)
    return round(value, 2)


def rounding_summary(
    stakes: Sequence[Mapping[str, Any]],
    *,
    investment: float | None = None,
    rounding: RoundingMode | str = "exact",
) -> dict[str, float | str]:
    """Describe exact and realized profit for the served stake rows.

    ``exact`` is the return if the requested investment were split
    proportionally with no rounding. ``realized`` is the worst actual return of
    the rounded stakes, minus what those stakes cost. ``rounding_loss`` is the
    difference; it can be negative when rounding happens to help.
    """
    rows = [row for row in stakes if float(row.get("odds") or 0) > 0]
    odds = [float(row["odds"]) for row in rows]
    amounts = [float(row.get("stake") or 0) for row in rows]
    margin = implied_sum(odds) if odds else 0.0
    stake_total = sum(amounts)
    exact_base = float(investment) if investment is not None else stake_total
    exact_return = exact_base / margin if margin > 0 else 0.0
    exact_profit = exact_return - exact_base
    exact_percent = (exact_return / exact_base - 1.0) * 100.0 if exact_base else 0.0
    worst_return = (
        min(amount * odds[index] for index, amount in enumerate(amounts))
        if amounts
        else 0.0
    )
    realized_profit = worst_return - stake_total
    realized_percent = (
        (worst_return / stake_total - 1.0) * 100.0 if stake_total else 0.0
    )
    return {
        "stake_total": round(stake_total, 2),
        "exact_return": round(exact_return, 2),
        "exact_profit": round(exact_profit, 2),
        "exact_profit_percent": round(exact_percent, 4),
        "worst_case_return": round(worst_return, 2),
        "realized_profit": round(realized_profit, 2),
        "realized_profit_percent": round(realized_percent, 4),
        "rounding_loss": round(exact_profit - realized_profit, 2),
        "rounding": str(rounding),
    }


def margin_from_served_stakes(stakes: Sequence[Mapping[str, Any]]) -> float:
    """Convenience for the API invariant test and the frontend hand-check."""
    return implied_sum([float(row["odds"]) for row in stakes])
