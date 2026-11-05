#!/usr/bin/env python
"""Bounded retention, vacuum and backup for the runtime stores (N1-1).

Examples::

    python scripts/maintenance.py --dry-run
    python scripts/maintenance.py
    python scripts/maintenance.py --vacuum --backup cache/backups

The report is JSON on stdout so an operator or a scheduled task can log it.
Bets are never deleted; old settled bets are copied to a dated archive file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.maintenance import run_maintenance  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply bounded retention to the scanner's runtime stores."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be pruned, archived or backed up; change nothing.",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Checkpoint the WAL and VACUUM after pruning (skipped by --dry-run).",
    )
    parser.add_argument(
        "--backup",
        metavar="DIR",
        help="Write a consistent SQLite backup and a copy of the mapping ledger.",
    )
    args = parser.parse_args(argv)

    report = run_maintenance(
        dry_run=args.dry_run,
        vacuum=args.vacuum,
        backup_dir=args.backup,
    )
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
