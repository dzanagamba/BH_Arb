"""Measure cross-book pairing quality from a saved scan.

The audit itself lives in `server/pairing_audit.py`, so `/api/health` and
coverage both use one implementation. This module is the CLI wrapper.

    python scripts/pairing_audit.py
    python scripts/pairing_audit.py --cache cache/last_scan.json --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.pairing_audit import DEFAULT_MAX_MISS_RATE, audit  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="cache/last_scan.json")
    parser.add_argument("--max-miss-rate", type=float, default=DEFAULT_MAX_MISS_RATE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    report = audit(cache)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not args.check:
        return 0
    problems = []
    if report["strict_miss_rate"] > args.max_miss_rate:
        problems.append(
            f"strict miss rate {report['strict_miss_rate']:.2%} exceeds {args.max_miss_rate:.2%}"
        )
    if report["duplicate_book_groups"]:
        problems.append(f"{len(report['duplicate_book_groups'])} group(s) repeat a bookmaker")
    if problems:
        print("\nFAIL: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
