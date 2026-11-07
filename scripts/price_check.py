"""Cross-book price check: flag a wrong market or a swapped label by its price.

A mapping mistake (the registry reads the wrong source id, or a book's outcome
labels are swapped) does not raise an error; it makes one book's odds disagree
with everyone else's for the same real match. This script finds those gaps.

For every group the matcher certifies as ``verified`` it takes each book's
complete outcome set per market, removes the bookmaker margin (normalises the
implied probabilities to the true total), and compares each book with the
median of the others. A gap above ``--threshold`` is an outlier.

    python scripts/price_check.py                       # cache/last_scan.json
    python scripts/price_check.py --live                # cache/last_live_scan.json
    python scripts/price_check.py --threshold 0.08 --status verified,suggested

It reads a scan file, so it works on any stored scan and needs no network.
Exit code is 1 when an outlier is found, so it can gate a check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.market_consensus import find_outliers  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Match  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def main() -> int:
    ap = argparse.ArgumentParser(description="Flag odds that disagree with the other books")
    ap.add_argument("--live", action="store_true", help="read the live scan cache")
    ap.add_argument("--file", help="scan file to read (overrides --live)")
    ap.add_argument("--threshold", type=float, default=0.10, help="absolute probability gap")
    ap.add_argument("--status", default="verified", help="comma-separated group statuses")
    ap.add_argument(
        "--evidence",
        help="mapping evidence ledger to use (default: the shipped generated ledger)",
    )
    args = ap.parse_args()

    path = args.file or os.path.join(
        CACHE_DIR, "last_live_scan.json" if args.live else "last_scan.json"
    )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    matches = [Match(**m) for m in data.get("matches", [])]
    groups = MatchMatcher(evidence_path=args.evidence).group_matches(matches)
    wanted = set(args.status.split(","))
    groups = [g for g in groups if g.status in wanted]
    outliers, compared = find_outliers(groups, args.threshold)

    print(f"{path}  scan_time={data.get('scan_time')}  matches={len(matches)}")
    print(f"groups with status {sorted(wanted)}: {len(groups)}; market comparisons: {compared}")
    by_book: dict[str, int] = defaultdict(int)
    for o in outliers:
        by_book[f"{o['bookmaker']}/{o['market']}"] += 1
    for key, n in sorted(by_book.items(), key=lambda kv: -kv[1]):
        print(f"  {key}: {n}")
    for o in sorted(outliers, key=lambda o: -abs(o["gap"]))[:25]:
        print(
            f"  {o['bookmaker']:<18} {o['market']:<15} {o['label']:<9} "
            f"p={o['prob']} vs median {o['median_others']} (gap {o['gap']:+}) "
            f"{o['match']} [{o['league']}]"
        )
    print(f"outliers: {len(outliers)}")
    return 1 if outliers else 0


if __name__ == "__main__":
    sys.exit(main())
