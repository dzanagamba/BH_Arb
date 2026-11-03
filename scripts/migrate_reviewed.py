"""Migrate the human-reviewed alias file into the evidence ledger.

The reviewed file is legacy input, not a trust source. Every approved pair is
written as a ``quarantined`` claim with ``legacy_review`` evidence: it is visible,
auditable, and can be corroborated by a later scan, but it cannot authorize a
pairing on its own. Rejected entries are counted and left alone; a human
rejection is not machine evidence either.

Usage:
    python scripts/migrate_reviewed.py --report migration.json
    python scripts/migrate_reviewed.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.mapping_evidence import (  # noqa: E402
    DEFAULT_PATH,
    Evidence,
    MappingLedger,
    team_alias_key,
)

DEFAULT_INPUT = REPO_ROOT / "config" / "team_alias_reviewed.json"


def migrate(input_path: Path, ledger: MappingLedger) -> dict:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    approved = data.get("approved") if isinstance(data, dict) else None
    rejected = data.get("rejected") if isinstance(data, dict) else None
    if not isinstance(approved, list):
        raise SystemExit(f"{input_path}: approved must be a list")

    imported: list[str] = []
    kept: list[str] = []
    skipped: list[str] = []
    for entry in approved:
        if not isinstance(entry, dict):
            continue
        alias = entry.get("alias")
        if not isinstance(alias, str) or alias.count("|") != 1:
            continue
        left, right = (part.strip() for part in alias.split("|", 1))
        if not left or not right:
            continue
        key = team_alias_key(left, right)
        existing = ledger.get("team_alias", key)
        if existing is not None and existing.status == "accepted":
            kept.append(key)
            continue
        evidence = Evidence(
            type="legacy_review",
            detail={
                "alias": alias,
                "reviewed_at": data.get("reviewed_at", ""),
                "fixtures": entry.get("evidence", entry.get("fixtures", [])),
            },
            scan="migrate_reviewed",
            books=(),
            observed_at=str(data.get("reviewed_at") or ""),
        )
        ledger.quarantine(
            "team_alias",
            key,
            [evidence],
            "legacy_review_needs_corroboration",
        )
        imported.append(key)

    return {
        "input": str(input_path),
        "approved_total": len(approved),
        "rejected_total": len(rejected) if isinstance(rejected, list) else 0,
        "imported_quarantined": imported,
        "kept_accepted": kept,
        "skipped": skipped,
        "counts": {
            "imported": len(imported),
            "kept": len(kept),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--ledger", default=str(DEFAULT_PATH))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    ledger = MappingLedger(args.ledger).load()
    report = migrate(Path(args.input), ledger)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.apply:
        ledger.save()
        print(f"wrote {args.ledger}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
