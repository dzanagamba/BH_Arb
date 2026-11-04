#!/usr/bin/env python3
"""Print deep-link declarations older than the audit policy (P2-2).

    python scripts/audit_deeplinks.py
    python scripts/audit_deeplinks.py --check   # exit 1 when any is stale

A no-event declaration is a human trust decision. This script does not re-check
the book; it makes the date visible and fails CI when the review is overdue.
"""

from __future__ import annotations

import argparse
import json
import sys

from config.settings import BOOKMAKERS, DEEPLINK_DECLARATION_MAX_AGE_DAYS
from scrapers.common import declaration_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEEPLINK_DECLARATION_MAX_AGE_DAYS,
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    rows = declaration_audit(BOOKMAKERS, args.max_age_days)
    print(json.dumps(rows, indent=2, sort_keys=True))
    stale = [row["bookmaker"] for row in rows if row["stale"]]
    if stale:
        print(
            "STALE: " + ", ".join(stale) + f" (older than {args.max_age_days} days)",
            file=sys.stderr,
        )
        return 1 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
