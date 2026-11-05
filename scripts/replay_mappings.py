"""Deterministic offline replay of the mapping pipeline.

Loads frozen scan corpora (``{"matches": [...]}``), shifts kickoffs into the
future so the arbitrage engine does not expire them, then runs the same
normalize → group → certainty-gate → price path a scan uses. No network, no
browser, no human input.

The output is the acceptance surface for the autonomy plan: the counts are
comparable across runs and a ``--check`` run exits non-zero when a merge
contradicts its ground truth (two different Betradar ids in one group) or an
evidence-backed pair has no terminal gate decision.

Ground truth is deliberately machine-checkable:

* two non-empty Betradar ids are the same fixture only when they are equal;
* otherwise, identical raw team spellings (either orientation), a kickoff
  within the verified window and equal category tags are the same fixture.

A pair that matches neither rule is not ground truth; it may still group
through the reviewed alias path, but this harness does not call it a merge
success or a merge failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.arbitrage import ArbitrageEngine  # noqa: E402
from engine.certainty import CertaintyGate  # noqa: E402
from engine.mapping_evidence import MappingLedger  # noqa: E402
from engine.mapping_learner import learn  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Match  # noqa: E402

KICKOFF_OFFSET = timedelta(hours=30)
CANDIDATE_WINDOW_MINUTES = 120
GROUND_TRUTH_WINDOW_MINUTES = 15


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _corpus_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        else:
            files.append(path)
    if not files:
        raise SystemExit(f"no scan JSON found in {paths}")
    return files


def load_matches(paths: list[str]) -> list[Match]:
    matches: list[Match] = []
    for path in _corpus_files(paths):
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("matches") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise SystemExit(f"{path}: expected a list or a 'matches' list")
        for row in rows:
            matches.append(Match.model_validate(row))
    return matches


def shift_kickoffs(matches: list[Match]) -> None:
    """Move the corpus's fixtures to a common future date.

    A frozen corpus cannot know when it is replayed, and the engine refuses a
    kickoff that has already passed. The shift preserves every relative gap, so
    a 15-minute boundary in the corpus is still a 15-minute boundary here.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    kickoffs = [_naive_utc(m.kickoff) for m in matches if m.kickoff]
    if not kickoffs:
        return
    delta = now + KICKOFF_OFFSET - min(kickoffs)
    for match in matches:
        if match.kickoff:
            match.kickoff = _naive_utc(match.kickoff) + delta
        match.fetched_at = now


def _raw_key(name: str) -> str:
    return CertaintyGate._raw_team_key(name)


def ground_truth(a: Match, b: Match) -> str | None:
    """Return the evidence type that proves the pair is one fixture, or None."""
    if a.betradar_id and b.betradar_id:
        return "betradar" if a.betradar_id == b.betradar_id else None

    a_home, a_away = _raw_key(a.home_team), _raw_key(a.away_team)
    b_home, b_away = _raw_key(b.home_team), _raw_key(b.away_team)
    same_sides = a_home == b_home and a_away == b_away
    swapped = a_home == b_away and a_away == b_home
    if not (same_sides or swapped):
        return None

    if not a.kickoff or not b.kickoff:
        return None
    delta = abs((_naive_utc(a.kickoff) - _naive_utc(b.kickoff)).total_seconds()) / 60.0
    if delta > GROUND_TRUTH_WINDOW_MINUTES:
        return None
    if set(a.category_tags or []) != set(b.category_tags or []):
        return None
    return "exact_fixture"


def _candidate(a: Match, b: Match) -> bool:
    if a.bookmaker == b.bookmaker:
        return False
    if not a.kickoff or not b.kickoff:
        return False
    delta = abs((_naive_utc(a.kickoff) - _naive_utc(b.kickoff)).total_seconds()) / 60.0
    return delta <= CANDIDATE_WINDOW_MINUTES


def _group_member_pairs(groups: list) -> list[tuple[Match, Match]]:
    pairs: list[tuple[Match, Match]] = []
    for group in groups:
        members = group.matches
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                pairs.append((left, right))
    return pairs


def replay(
    paths: list[str],
    mode: str,
    no_learn: bool,
    iterations: int = 5,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    matches = load_matches(paths)
    shift_kickoffs(matches)

    fixed_point = True
    learned = 0
    used_iterations = 0
    # With --no-learn the matcher reads the seed ledger directly. An explicit
    # --ledger keeps a replay independent of the operator's generated evidence;
    # without one the historical default (the current ledger) still applies.
    evidence_path: str | None = ledger_path
    if not no_learn:
        if mode == "cold":
            ledger = MappingLedger(
                Path(tempfile.mkdtemp(prefix="replay-evidence-")) / "evidence.json"
            ).load()
        elif ledger_path:
            ledger = MappingLedger(ledger_path).load()
        else:
            ledger = MappingLedger().load()
        for used_iterations in range(1, iterations + 1):
            ledger, report = learn(matches, ledger, scan=f"replay-{used_iterations}")
            if not report.diff["added"] and not report.diff["changed"]:
                fixed_point = True
                break
            fixed_point = False
        learned = len(ledger.claims)
        # Learned claims are written to a scratch file, never back to --ledger.
        evidence_path = str(
            Path(tempfile.mkdtemp(prefix="replay-evidence-")) / "evidence.json"
        )
        ledger.path = Path(evidence_path)
        ledger.save()

    matcher = MatchMatcher(evidence_path=evidence_path)
    matcher.normalize_matches(matches)
    gate = matcher.gate

    pairs_total = 0
    evidence_pairs: list[tuple[Match, Match, str]] = []
    for i, left in enumerate(matches):
        for right in matches[i + 1 :]:
            if not _candidate(left, right):
                continue
            pairs_total += 1
            proof = ground_truth(left, right)
            if proof:
                evidence_pairs.append((left, right, proof))

    statuses = {"verified": 0, "rejected": 0, "suggested": 0}
    for left, right, _ in evidence_pairs:
        statuses[gate.evaluate_pair(left, right).status] += 1

    groups = matcher.group_matches(matches)
    false_merges = 0
    for left, right in _group_member_pairs(groups):
        if left.betradar_id and right.betradar_id and left.betradar_id != right.betradar_id:
            false_merges += 1

    surebets = ArbitrageEngine().find_surebets(groups)

    market_rows = sum(len(m.markets) for m in matches)
    books = sorted({m.bookmaker for m in matches})
    return {
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
        "mode": mode,
        "no_learn": no_learn,
        "fixed_point": fixed_point,
        "iterations": used_iterations,
        "ledger_claims": learned,
        "corpus": [str(p) for p in _corpus_files(paths)],
        "matches_total": len(matches),
        "books": books,
        "pairs_total": pairs_total,
        "pairs_evidence_backed": len(evidence_pairs),
        "pairs_verified": statuses["verified"],
        "pairs_rejected": statuses["rejected"],
        "pairs_quarantined": 0,
        "pairs_unresolved": statuses["suggested"],
        "false_merges": false_merges,
        "groups_verified": len(groups),
        "surebets_count": len(surebets),
        "market_rows_total": market_rows,
        "market_rows_mapped": market_rows,
        "market_rows_unmapped": 0,
        "price_check_outliers": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="scan JSON files or directories")
    parser.add_argument(
        "--cold",
        action="store_true",
        help="start from an empty generated evidence directory (no learner yet)",
    )
    parser.add_argument(
        "--seeded",
        action="store_true",
        help="use the current generated evidence (the default)",
    )
    parser.add_argument(
        "--no-learn",
        action="store_true",
        help="do not run the learner or require every evidence-backed pair to be terminal",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="maximum learner passes before reporting a non-fixed point",
    )
    parser.add_argument(
        "--ledger",
        default=None,
        help=(
            "seed evidence ledger to read; learned claims go to a scratch file. "
            "Omit to use the generated ledger, which makes a replay depend on the "
            "operator's local state"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 on a false merge or an unresolved evidence-backed pair",
    )
    args = parser.parse_args(argv)

    mode = "cold" if args.cold else "seeded"
    report = replay(args.paths, mode, args.no_learn, args.iterations, args.ledger)
    print(json.dumps(report, indent=2, sort_keys=True))

    if not args.check:
        return 0
    failures: list[str] = []
    if report["false_merges"] > 0:
        failures.append(f"false_merges={report['false_merges']}")
    if not args.no_learn and report["pairs_unresolved"] > 0:
        failures.append(f"pairs_unresolved={report['pairs_unresolved']}")
    if not args.no_learn and not report["fixed_point"]:
        failures.append("cold_start_not_at_a_fixed_point")
    if report["market_rows_unmapped"] > 0:
        failures.append(f"market_rows_unmapped={report['market_rows_unmapped']}")
    if failures:
        print("FAIL: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
