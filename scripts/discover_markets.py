"""Prove market mappings from a scan, without editing the registry by hand.

For every market in every verified group, the classifier must agree with the
market type the parser chose, and the other books on the same fixture must agree
on its de-vigged price. An accepted pair becomes a ``market_mapping`` claim in
the evidence ledger; an outlier is quarantined with its gaps. The generated
registry is written separately by ``scripts/generate_market_registry.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.mapping_evidence import (  # noqa: E402
    DEFAULT_PATH,
    Evidence,
    MappingLedger,
    market_mapping_key,
)
from engine.market_consensus import compare  # noqa: E402
from engine.market_discovery import classify  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Market, Match  # noqa: E402


def _load(paths: list[str]) -> list[Match]:
    matches: list[Match] = []
    for raw in paths:
        path = Path(raw)
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        for file in files:
            data: Any = json.loads(file.read_text(encoding="utf-8"))
            rows = data.get("matches") if isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise SystemExit(f"{file}: expected a list or a 'matches' list")
            matches.extend(Match.model_validate(row) for row in rows)
    return matches


def _others(group, match: Match, market: Market) -> list[Market]:
    return [
        other_market
        for other in group.matches
        if other.bookmaker != match.bookmaker
        for other_market in other.markets
        if other_market.market_type == market.market_type
    ]


def discover(matches: list[Match], ledger: MappingLedger, *, scan: str) -> dict[str, int]:
    groups = MatchMatcher().group_matches(matches)
    counts = {"accepted": 0, "quarantined": 0, "insufficient": 0, "skipped": 0}
    for group in groups:
        for match in group.matches:
            for market in match.markets:
                classification = classify([item.label for item in market.odds])
                if classification is None or classification.market_type != market.market_type:
                    counts["skipped"] += 1
                    continue
                result = compare(market, _others(group, match, market))
                if result.status == "insufficient_evidence":
                    counts["insufficient"] += 1
                    continue
                source_id = market.source_id or market.market_type.value
                key = market_mapping_key(
                    match.bookmaker,
                    "prematch",
                    source_id,
                    [item.label for item in market.odds],
                )
                evidence = Evidence(
                    type="cross_book_price",
                    detail={
                        "bookmaker": match.bookmaker,
                        "mode": "prematch",
                        "market_type": market.market_type.value,
                        "source_id": source_id,
                        "labels": [item.label for item in market.odds],
                        "line": classification.line,
                        "fixture": f"{group.canonical_home} - {group.canonical_away}",
                        "gaps": result.gaps,
                    },
                    scan=scan,
                    books=(match.bookmaker,),
                    observed_at=datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
                )
                if result.status == "accepted":
                    ledger.accept("market_mapping", key, [evidence], result.evidence)
                    counts["accepted"] += 1
                else:
                    ledger.quarantine("market_mapping", key, [evidence], result.evidence)
                    counts["quarantined"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--ledger", default=str(DEFAULT_PATH))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scan-id", default="")
    args = parser.parse_args(argv)

    scan = args.scan_id or datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    ledger = MappingLedger(args.ledger).load()
    counts = discover(_load(args.paths), ledger, scan=scan)
    print(json.dumps(counts, indent=2, sort_keys=True))
    if args.apply:
        ledger.save()
        print(f"wrote {args.ledger}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
