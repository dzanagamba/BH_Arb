"""Rank the review queue's closeable pairs and recurring blockers.

Reads the cached scan the dashboard serves (``cache/last_scan.json`` by
default), rebuilds the candidate queue with the product's own collector, and
prints the pairs a reviewer could close with a team alias or league mapping.

    python scripts/candidate_remediation.py
    python scripts/candidate_remediation.py --top 20
    python scripts/candidate_remediation.py --cache cache/last_scan.json --json out.json

This is a report, not a decision. It never calls an approve/reject path, never
writes the allowlist or the ledger, and every suggestion it prints is labelled
``proposal``. The queue size is a diagnostic denominator, not a claim that
coverage improved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.candidate_remediation import (  # noqa: E402
    PROPOSAL_NOTE,
    group_candidates,
    remediation_counts,
)
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import CandidateReview, Match  # noqa: E402
from server import api  # noqa: E402

DEFAULT_CACHE = REPO_ROOT / "cache" / "last_scan.json"
DERIVED_FIELDS = (
    "league_normalized",
    "country_normalized",
    "home_team_normalized",
    "away_team_normalized",
    "category_tags",
)


def load_matches(path: Path) -> list[Match]:
    """Load cached matches with derived fields cleared, as a fresh scrape is."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("matches") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a list or a 'matches' list")
    matches: list[Match] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        clean = {key: value for key, value in raw.items() if key not in DERIVED_FIELDS}
        try:
            matches.append(Match(**clean))
        except (TypeError, ValueError):
            continue
    return matches


def build_report(matches: list[Match], top: int = 20) -> dict[str, Any]:
    """Build the queue and its ranked remediation report, with no network call."""
    candidates: dict[str, CandidateReview] = asyncio.run(
        api._collect_candidates(matches, MatchMatcher(), rank_with_ai=False)
    )
    queue = list(candidates.values())
    counts = remediation_counts(queue)
    closeable = [candidate for candidate in queue if _closeable(candidate)]
    closeable.sort(key=lambda candidate: (
        _action(candidate),
        -_top_confidence(candidate),
        candidate.id,
    ))
    return {
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "matches": len(matches),
        "candidates": len(queue),
        "counts": counts,
        "closeable": len(closeable),
        "pairs": [_pair_row(candidate) for candidate in closeable[: max(1, top)]],
        "groups": group_candidates(queue, limit=max(1, top)),
        "note": (
            "Queue size and group counts are diagnostics, not a coverage-progress "
            "claim. " + PROPOSAL_NOTE
        ),
    }


def _closeable(candidate: CandidateReview) -> bool:
    return bool(candidate.remediation and candidate.remediation.closeable)


def _action(candidate: CandidateReview) -> str:
    return candidate.remediation.action if candidate.remediation else "none"


def _top_confidence(candidate: CandidateReview) -> float:
    if not candidate.remediation or not candidate.remediation.proposals:
        return 0.0
    return max(proposal.confidence for proposal in candidate.remediation.proposals)


def _pair_row(candidate: CandidateReview) -> dict[str, Any]:
    remediation = candidate.remediation
    return {
        "id": candidate.id,
        "action": remediation.action if remediation else "none",
        "home_team": candidate.home_team,
        "away_team": candidate.away_team,
        "league": candidate.league,
        "kickoff": candidate.kickoff.isoformat() if candidate.kickoff else None,
        "bookmakers": list(candidate.bookmakers),
        "gate_reasons": list(remediation.gate_reasons) if remediation else list(candidate.rule_rejections),
        "proposals": [
            {
                "kind": proposal.kind,
                "entry": proposal.entry,
                "confidence": proposal.confidence,
                "ledger_status": proposal.ledger_status,
                "ledger_confidence": proposal.ledger_confidence,
                "ledger_evidence": list(proposal.ledger_evidence),
                "applied": proposal.applied,
            }
            for proposal in (remediation.proposals if remediation else [])
        ],
        "notes": list(remediation.notes) if remediation else [],
        "proposal_only": True,
    }


def _print_report(report: dict[str, Any]) -> None:
    counts = report["counts"]
    print(
        f"Review queue: {report['candidates']} candidates from {report['matches']} matches · "
        f"{report['closeable']} closeable "
        f"(alias {counts['alias']}, league {counts['league']}, "
        f"alias+league {counts['alias+league']}, "
        f"system-link {counts['system_link']}, none {counts['none']})"
    )
    print(f"Note: {report['note']}")
    print()
    if not report["pairs"]:
        print("No pair in the queue can be closed by a team alias or league mapping.")
    else:
        print(f"Top {len(report['pairs'])} closeable pair(s):")
        for number, row in enumerate(report["pairs"], start=1):
            books = " / ".join(row["bookmakers"])
            reasons = ", ".join(row["gate_reasons"]) or "no reason recorded"
            print(
                f"{number:>2}. [{row['action']}] {row['home_team']} vs {row['away_team']} "
                f"— {row['league']} ({books})"
            )
            print(f"    gate: {reasons}")
            for proposal in row["proposals"]:
                ledger = proposal["ledger_status"]
                if proposal["ledger_status"] != "absent":
                    ledger += f" {proposal['ledger_confidence']:.2f}"
                print(
                    f"    proposal {proposal['kind']}: {proposal['entry']} "
                    f"(ledger {ledger}, applied={proposal['applied']})"
                )
    print()
    if report["groups"]:
        print("Top recurring blockers (count / queue total):")
        for row in report["groups"]:
            reasons = ", ".join(row["reasons"]) or "no reason recorded"
            print(
                f"  {row['count']:>5} · {row['action']} · {row['book_pair']} · "
                f"{row['league']} · {reasons}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--json", default="", help="write the full report here")
    args = parser.parse_args(argv)

    path = Path(args.cache)
    if not path.exists():
        print(
            f"No scan cache at {path}. Run a scan first; this report never invents "
            "a queue.",
            file=sys.stderr,
        )
        return 2
    matches = load_matches(path)
    report = build_report(matches, top=args.top)
    _print_report(report)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
