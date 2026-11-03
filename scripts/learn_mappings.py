"""Learn mapping claims from scan payloads without a human in the loop.

Usage:
    python scripts/learn_mappings.py cache/last_scan.json --report proposals.json
    python scripts/learn_mappings.py cache/last_scan.json --apply
    python scripts/learn_mappings.py tests/fixtures/replay/2026-11-03 --apply

Without ``--apply`` the ledger is not written; the report still shows what would
change. A claim is accepted only when its evidence carries it: a shared Betradar
id, an exact shared fixture, or a corroborated league fingerprint. Similarity
alone is quarantined.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.mapping_evidence import DEFAULT_PATH, MappingLedger  # noqa: E402
from engine.mapping_learner import learn, load_matches  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="scan JSON files or directories")
    parser.add_argument("--apply", action="store_true", help="write the ledger")
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_PATH),
        help=f"ledger path (default: {DEFAULT_PATH})",
    )
    parser.add_argument("--report", help="write the JSON report to this path")
    parser.add_argument("--scan-id", default="", help="identifier stored on every observation")
    args = parser.parse_args(argv)

    matches = load_matches(args.paths)
    ledger = MappingLedger(args.ledger).load()
    ledger, report = learn(matches, ledger, scan=args.scan_id)
    payload = report.to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))

    if args.report:
        Path(args.report).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.apply:
        ledger.save()
        print(f"wrote {args.ledger}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
