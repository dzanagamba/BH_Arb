#!/usr/bin/env python
"""Per-book scan cost report (N1-3).

Reads the bounded `cache/scan_cost.json` history and prints the per-book table
with explicit scan and book denominators. It only reads durations, request
counts, response sizes and outcome labels; no URL, header or payload is stored
or printed.

    python scripts/scan_cost.py --days 7
    python scripts/scan_cost.py --days 7 --mode prematch --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import settings  # noqa: E402
from server.scan_cost import aggregate, load_history  # noqa: E402


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _mb(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) / (1024 * 1024):.2f}"


def render_table(report: dict) -> str:
    totals = report["totals"]
    lines = [
        f"Scan cost — last {report['days']} day(s), mode={report['mode']}",
        (
            f"Denominators: {report['scans']} scan(s), {report['books']} book(s), "
            f"{totals['matches']} match(es), {totals['markets']} market row(s)"
        ),
        "",
        f"{'book':<20} {'scans':>5} {'ok':>4} {'empty':>5} {'parse':>5} "
        f"{'block':>5} {'wall_s':>8} {'browser_s':>9} {'req':>6} {'MB':>7} "
        f"{'matches':>7} {'s/match':>8} {'fail%':>6}",
    ]
    for book, entry in report["per_book"].items():
        failure = (
            f"{entry['failure_rate'] * 100:.1f}"
            if entry["failure_rate"] is not None
            else "n/a"
        )
        lines.append(
            f"{book:<20} {entry['scans']:>5} {entry['success']:>4} "
            f"{entry['empty']:>5} {entry['parse_error']:>5} {entry['blocked']:>5} "
            f"{_fmt(entry['wall_seconds']):>8} {_fmt(entry['browser_seconds']):>9} "
            f"{_fmt(entry['requests'], 0):>6} {_mb(entry['bytes']):>7} "
            f"{entry['matches']:>7} {_fmt(entry['seconds_per_match'], 3):>8} "
            f"{failure:>6}"
        )
    lines.append(
        f"{'TOTAL':<20} {totals['scans']:>5} {totals['success']:>4} "
        f"{totals['empty']:>5} {totals['parse_error']:>5} {totals['blocked']:>5} "
        f"{_fmt(totals['wall_seconds']):>8} {_fmt(totals['browser_seconds']):>9} "
        f"{_fmt(totals['requests'], 0):>6} {_mb(totals['bytes']):>7} "
        f"{totals['matches']:>7} {_fmt(totals['seconds_per_match'], 3):>8} "
        f"{'':>6}"
    )
    lines.append("")
    lines.append(
        "Cost/coverage: "
        f"{_fmt(totals['seconds_per_match'], 3)} s/match, "
        f"{_fmt(totals['requests_per_match'], 3)} requests/match, "
        f"{_fmt(totals['bytes_per_match'], 2)} bytes/match."
    )
    missing = [
        f"{book}: {', '.join(entry['missing'])}"
        for book, entry in report["per_book"].items()
        if entry["missing"]
    ]
    if missing:
        lines.append("Not measurable: " + " | ".join(missing))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the per-book cost of recent scans."
    )
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--mode", choices=("prematch", "live"), default="")
    parser.add_argument(
        "--file",
        default=str(Path(settings.CACHE_DIR) / "scan_cost.json"),
        help="scan-cost history file",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead")
    args = parser.parse_args(argv)

    history = load_history(args.file)
    report = aggregate(history, days=args.days, mode=args.mode)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_table(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
