"""One scan, one audit: coverage, false merges, price agreement and the best margin.

This is the production report an operator (or a scheduled job) reads after every
scan. It never changes a mapping; it only measures what the scan decided.

    python scripts/scan_quality.py
    python scripts/scan_quality.py --file cache/last_scan.json --evidence /tmp/evidence.json
    python scripts/scan_quality.py --check

``--check`` exits 1 on a false merge (two different Betradar ids in one group) or
a price outlier. A zero surebet count is not a failure: a scan can be correct and
still contain no arbitrage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import price_source  # noqa: E402
from engine.arbitrage import ArbitrageEngine  # noqa: E402
from engine.mapping_evidence import MappingLedger  # noqa: E402
from engine.market_consensus import complete_market_spec, find_outliers  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import MarketType, Match  # noqa: E402


def _best_margins(groups) -> list[tuple[float, str, str, str]]:
    best: list[tuple[float, str, str, str]] = []
    for group in groups:
        for market_type in MarketType:
            spec = complete_market_spec(market_type)
            if spec is None:
                continue
            labels = spec[0]
            legs: list[dict[str, float]] = []
            seen: set[str] = set()
            for match in group.matches:
                source = price_source(match.bookmaker)
                if source in seen:
                    continue
                for market in match.markets:
                    if market.market_type != market_type:
                        continue
                    odds = {item.label: item.value for item in market.odds}
                    if set(odds) != labels:
                        continue
                    legs.append(odds)
                    seen.add(source)
                    break
            if len(legs) < 2:
                continue
            implied = sum(1 / max(leg[label] for leg in legs) for label in labels)
            best.append(
                (implied, market_type.value, group.canonical_home, group.canonical_away)
            )
    return sorted(best)


def build_report(
    matches: list[Match],
    groups,
    *,
    evidence_path: str | None = None,
    threshold: float = 0.10,
) -> dict[str, Any]:
    per_book = Counter(match.bookmaker for match in matches)
    false_merges = 0
    for group in groups:
        ids = {match.betradar_id for match in group.matches if match.betradar_id}
        if len(ids) > 1:
            false_merges += 1
    outliers, compared = find_outliers(groups, threshold)
    best = _best_margins(groups)
    ledger = MappingLedger(evidence_path).load() if evidence_path else MappingLedger().load()
    claims = Counter(claim.status for claim in ledger.claims.values())
    surebets = ArbitrageEngine().find_surebets(
        [group.model_copy(deep=True) for group in groups]
    )
    return {
        "matches": len(matches),
        "books": dict(sorted(per_book.items())),
        "groups": len(groups),
        "listings_in_groups": sum(len(group.matches) for group in groups),
        "group_price_sources": dict(
            sorted(
                Counter(
                    len({price_source(m.bookmaker) for m in group.matches})
                    for group in groups
                ).items()
            )
        ),
        "false_merges": false_merges,
        "price_comparisons": compared,
        "price_outliers": len(outliers),
        "outlier_rows": outliers[:20],
        "best_margins": [
            {
                "implied_sum": round(implied, 5),
                "market": market,
                "home": home,
                "away": away,
            }
            for implied, market, home, away in best[:10]
        ],
        "surebets": len(surebets),
        "ledger_claims": dict(sorted(claims.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="cache/last_scan.json")
    parser.add_argument("--evidence", help="mapping evidence ledger path")
    parser.add_argument("--threshold", type=float, default=0.10)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    data: Any = json.loads(Path(args.file).read_text(encoding="utf-8"))
    matches = [Match.model_validate(row) for row in data.get("matches", [])]
    groups = MatchMatcher(evidence_path=args.evidence).group_matches(
        [match.model_copy(deep=True) for match in matches]
    )
    report = build_report(
        matches,
        groups,
        evidence_path=args.evidence,
        threshold=args.threshold,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.check and (report["false_merges"] or report["price_outliers"]):
        print(
            f"FAIL: false_merges={report['false_merges']} "
            f"price_outliers={report['price_outliers']}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
