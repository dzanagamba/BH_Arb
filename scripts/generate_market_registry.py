"""Write the machine-proven market registry from the evidence ledger.

Only accepted ``market_mapping`` claims are written. A claim carries the book,
mode, market type, source id, labels and line that were proven by the classifier
and cross-book price consensus. ``--check`` fails when the file is stale, so CI
can keep it in sync.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.mapping_evidence import DEFAULT_PATH, MappingLedger  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "config" / "generated" / "bookmaker_markets.json"


def build_registry(ledger: MappingLedger) -> dict[str, Any]:
    registry: dict[str, Any] = {}
    for claim in ledger.claims.values():
        if claim.kind != "market_mapping" or not claim.is_authoritative():
            continue
        detail = claim.evidence[-1].detail if claim.evidence else {}
        bookmaker = str(detail.get("bookmaker") or "")
        mode = str(detail.get("mode") or "prematch")
        market_type = str(detail.get("market_type") or "")
        source_id = str(detail.get("source_id") or "")
        if not (bookmaker and market_type and source_id):
            continue
        labels = detail.get("labels")
        row: dict[str, Any] = {
            "ids": [int(source_id) if source_id.isdigit() else source_id],
            "labels": [str(label) for label in labels] if isinstance(labels, list) else [],
            "min_legs": int(detail.get("min_legs", 3)),
            "settlement": str(detail.get("settlement", "full_time")),
            "_provenance": {
                "status": claim.status,
                "claim": claim.key,
                "reason": claim.reason,
                "evidence": sorted({item.type for item in claim.evidence}),
                "last_seen": claim.last_seen,
            },
        }
        line = detail.get("line")
        if line is not None:
            row["line"] = float(line)
        registry.setdefault(bookmaker, {}).setdefault(mode, {})[market_type] = row
    return registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=str(DEFAULT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    ledger = MappingLedger(args.ledger).load()
    registry = build_registry(ledger)
    text = json.dumps(registry, indent=2, sort_keys=True) + "\n"
    output = Path(args.output)
    if args.check:
        current = output.read_text(encoding="utf-8") if output.exists() else ""
        if current != text:
            print(f"{output} is stale; run scripts/generate_market_registry.py", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
