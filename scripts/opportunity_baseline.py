"""Render the last N days of opportunity-rate aggregates as a Markdown report.

The scanner persists one compact aggregate row per completed scan in
``cache/opportunity_metrics.json``. This script only reads that file: it never
loads the full scan cache and never recomputes an arb.

Usage:
    python scripts/opportunity_baseline.py --days 7
    python scripts/opportunity_baseline.py --days 7 --out docs/evidence/...
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_METRICS = REPO_ROOT / "cache" / "opportunity_metrics.json"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 2) if denominator else None


def _load_rows(path: Path, days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(data, dict):
        return [], {}
    history = data.get("history")
    if not isinstance(history, list):
        return [], data if isinstance(data.get("last"), dict) else {}
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        scan_time = _parse_time(row.get("scan_time"))
        if scan_time is not None and scan_time >= cutoff:
            rows.append(row)
    return rows, data


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    boards = sum(int(row.get("boards") or 0) for row in rows)
    crossed = sum(int(row.get("crossed") or 0) for row in rows)
    above = sum(int(row.get("crossed_above_floor") or 0) for row in rows)
    actionable = sum(int(row.get("actionable") or 0) for row in rows)
    dropped = sum(int(row.get("price_guard_dropped") or 0) for row in rows)
    margins = [
        float(row["median_margin"])
        for row in rows
        if isinstance(row.get("median_margin"), int | float)
    ]
    profits = [
        float(row["best_profit_percent"])
        for row in rows
        if isinstance(row.get("best_profit_percent"), int | float)
    ]
    return {
        "scans": len(rows),
        "boards": boards,
        "crossed": crossed,
        "crossed_above_floor": above,
        "actionable": actionable,
        "price_guard_dropped": dropped,
        "crossing_rate_percent": _rate(crossed, boards),
        "floor_crossing_rate_percent": _rate(above, boards),
        "actionable_rate_percent": _rate(actionable, boards),
        "median_scan_margin": round(statistics.median(margins), 4) if margins else None,
        "best_margin": round(min(margins), 4) if margins else None,
        "best_profit_percent": round(max(profits), 2) if profits else None,
    }


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render(rows: list[dict[str, Any]], data: dict[str, Any], days: int) -> str:
    now = datetime.now(UTC).replace(tzinfo=None)
    lines = [
        f"# Opportunity-rate baseline — last {days} days",
        "",
        f"Generated: {now.isoformat(timespec='seconds')}Z",
        "",
    ]
    if not rows:
        lines += [
            "No completed scans are recorded in this window yet. Run scheduled scans,",
            "then rerun `python scripts/opportunity_baseline.py --days 7`.",
            "",
            "The public reference measurement is **1.34%** of 115,583 boards crossing,",
            "with **26** of 1,553 crossings actionable after gates. Use it as a sanity",
            "range, not as this instance's result.",
            "",
        ]
        return "\n".join(lines)

    by_mode: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        mode = str(row.get("mode") or "prematch")
        by_mode.setdefault(mode, []).append(row)

    lines += [
        "| Mode | Scans | Boards | Crossed | Above floor | Actionable | Crossing rate | Floor crossing | Actionable rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in sorted(by_mode):
        agg = _aggregate(by_mode[mode])
        lines.append(
            f"| {mode} | {agg['scans']} | {agg['boards']} | {agg['crossed']} | "
            f"{agg['crossed_above_floor']} | {agg['actionable']} | "
            f"{_fmt(agg['crossing_rate_percent'])}% | "
            f"{_fmt(agg['floor_crossing_rate_percent'])}% | "
            f"{_fmt(agg['actionable_rate_percent'])}% |"
        )
    overall = _aggregate(rows)
    lines += [
        f"| **all** | {overall['scans']} | {overall['boards']} | {overall['crossed']} | "
        f"{overall['crossed_above_floor']} | {overall['actionable']} | "
        f"{_fmt(overall['crossing_rate_percent'])}% | "
        f"{_fmt(overall['floor_crossing_rate_percent'])}% | "
        f"{_fmt(overall['actionable_rate_percent'])}% |",
        "",
        f"- Median per-scan board margin: **{_fmt(overall['median_scan_margin'])}**",
        f"- Best margin seen: **{_fmt(overall['best_margin'])}**",
        f"- Best profit seen: **{_fmt(overall['best_profit_percent'])}%**",
        f"- Price-guard drops: **{overall['price_guard_dropped']}**",
        "",
        "| Mode | p50 lifetime | p90 lifetime | Samples | Alive |",
        "|---|---:|---:|---:|---:|",
    ]
    last_raw = data.get("last")
    last: dict[str, Any] = last_raw if isinstance(last_raw, dict) else {}
    for mode in sorted(by_mode):
        mode_data = last.get(mode)
        lifetime_raw = mode_data.get("lifetime") if isinstance(mode_data, dict) else None
        lifetime: dict[str, Any] = lifetime_raw if isinstance(lifetime_raw, dict) else {}
        lines.append(
            f"| {mode} | {_fmt(lifetime.get('p50_sec'))}s | "
            f"{_fmt(lifetime.get('p90_sec'))}s | {_fmt(lifetime.get('samples'))} | "
            f"{_fmt(lifetime.get('alive'))} |"
        )
    lines += [
        "",
        "A crossing is a board with an implied sum below 1.0. The floor is the scan's",
        "minimum profit (`DUST_PROFIT_PERCENT`, 0.2%); actionable means the scan kept",
        "the surebet after the price guard. Lifetime is measured from first crossing to",
        "disappearance, or to now for a still-live crossing.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rows, data = _load_rows(args.metrics, max(1, args.days))
    report = render(rows, data, max(1, args.days))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
