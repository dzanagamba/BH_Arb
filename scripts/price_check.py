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
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import price_source  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import MarketType, Match  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")

# Label sets that make a complete market, and how many of them win a bet.
# Double chance pays on two of three outcomes, so its implied sum is 2.
_COMPLETE: dict[MarketType, tuple[frozenset[str], int]] = {
    MarketType.MATCH_RESULT: (frozenset({"1", "X", "2"}), 1),
    MarketType.DOUBLE_CHANCE: (frozenset({"1X", "12", "X2"}), 2),
    MarketType.BTTS: (frozenset({"GG", "NG"}), 1),
    MarketType.OVER_UNDER_1_5: (frozenset({"Over 1.5", "Under 1.5"}), 1),
    MarketType.OVER_UNDER_2_5: (frozenset({"Over 2.5", "Under 2.5"}), 1),
    MarketType.OVER_UNDER_3_5: (frozenset({"Over 3.5", "Under 3.5"}), 1),
}


def devigged(market_type: MarketType, odds: dict[str, float]) -> dict[str, float] | None:
    """True probability per outcome, or None when the set is not complete."""
    spec = _COMPLETE.get(market_type)
    if spec is None:
        return None
    labels, winners = spec
    if set(odds) != labels or any(v < 1.01 for v in odds.values()):
        return None
    total = sum(1 / v for v in odds.values())
    return {label: (1 / v) / total * winners for label, v in odds.items()}


def find_outliers(groups, threshold: float) -> tuple[list[dict], int]:
    """Return (outliers, number of group/market comparisons made)."""
    outliers: list[dict] = []
    compared = 0
    for group in groups:
        by_market: dict[MarketType, dict[str, dict[str, float]]] = defaultdict(dict)
        names: dict[str, list[str]] = defaultdict(list)
        for match in group.matches:
            if match.bookmaker not in names[price_source(match.bookmaker)]:
                names[price_source(match.bookmaker)].append(match.bookmaker)
        for match in group.matches:
            for market in match.markets:
                probs = devigged(market.market_type, {o.label: o.value for o in market.odds})
                if probs is not None:
                    # Books on one feed quote one price: count that source once.
                    by_market[market.market_type].setdefault(price_source(match.bookmaker), probs)
        for market_type, per_book in by_market.items():
            if len(per_book) < 3:  # a median of one other book is no reference
                continue
            compared += 1
            for book, probs in per_book.items():
                for label, p in probs.items():
                    others = [q[label] for b, q in per_book.items() if b != book]
                    gap = p - statistics.median(others)
                    if abs(gap) > threshold:
                        outliers.append(
                            {
                                "match": f"{group.canonical_home} - {group.canonical_away}",
                                "league": group.league,
                                "market": market_type.value,
                                "bookmaker": "+".join(names[book]),
                                "label": label,
                                "prob": round(p, 3),
                                "median_others": round(statistics.median(others), 3),
                                "gap": round(gap, 3),
                            }
                        )
    return outliers, compared


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
