"""Ranked, proposal-only remediation for the review queue and strict misses.

Two different records feed the reviewer's attention:

* a **candidate** is a pair the certainty gate refused (a possible same event),
  and the question is which mapping, if any, a human could still supply;
* a **strict miss** is an offer the matcher left ungrouped even though another
  book listed the same fixture, and the question is which recurring pair,
  league and spelling pattern produces the misses.

Nothing in this module can approve, apply or verify anything. Every proposal
carries ``proposal_only=True``/``applied=False`` and the exact gate codes; the
allowlist, the evidence ledger and any candidate's status are read-only inputs.
The one hypothetical evaluation lives in ``server.api`` because it needs the
same gate the scan decides with, and it is discarded immediately.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from engine.mapping_evidence import (
    MappingLedger,
    league_equivalence_key,
    team_alias_key,
)
from models.schemas import (
    CandidateReview,
    RemediationProposal,
)

LINK_REJECTION_REASONS = frozenset({"link_unverified", "no_event_link"})
CLOSEABLE_ACTIONS = frozenset({"alias", "league", "alias+league"})
MAX_BLOCKER_GROUPS = 25
PROPOSAL_NOTE = (
    "Proposal only: nothing here writes an alias, the ledger or a gate verdict."
)


def _ledger_block(ledger: MappingLedger | None, kind: str, key: str) -> dict[str, Any]:
    """Return the ledger's verdict on one proposed entry, without changing it."""
    claim = ledger.get(kind, key) if ledger is not None else None
    if claim is None:
        return {
            "status": "absent",
            "confidence": 0.0,
            "evidence": [],
        }
    return {
        "status": claim.status,
        "confidence": round(claim.confidence, 4),
        "evidence": sorted({item.type for item in claim.evidence})[:5],
    }


def _proposal(
    *,
    kind: Literal["team_alias", "league_equivalence"],
    entry: str,
    left: str,
    right: str,
    ledger: MappingLedger | None,
    claim_key: str,
    confidence: float,
) -> RemediationProposal:
    block = _ledger_block(ledger, kind, claim_key)
    # The ledger's confidence is evidence, not a trust upgrade: it ranks the
    # proposal for a reviewer and never changes `applied` or the gate.
    return RemediationProposal(
        kind=kind,
        entry=entry,
        left=left,
        right=right,
        confidence=round(
            max(0.0, min(1.0, max(float(confidence), float(block["confidence"])))), 4
        ),
        ledger_status=str(block["status"]),
        ledger_confidence=float(block["confidence"]),
        ledger_evidence=[str(item) for item in block["evidence"]],
        proposal_only=True,
        applied=False,
    )


def alias_proposals(
    entries: Sequence[str],
    ledger: MappingLedger | None,
    confidence: float = 0.0,
) -> list[RemediationProposal]:
    """Turn reviewed-alias entries into inert proposals.

    ``entries`` are the same ``"raw A|raw B"`` strings an approval would write,
    so a proposal cannot name an entry the approval path would not. The raw
    spellings are what a reviewer recognises; the ledger key normalises them
    exactly as the gate does.
    """
    proposals: list[RemediationProposal] = []
    for entry in entries:
        if entry.count("|") != 1:
            continue
        left, right = (part.strip() for part in entry.split("|", 1))
        if not left or not right:
            continue
        proposals.append(
            _proposal(
                kind="team_alias",
                entry=entry,
                left=left,
                right=right,
                ledger=ledger,
                claim_key=team_alias_key(left, right),
                confidence=confidence,
            )
        )
    return proposals


def league_proposal(
    left: str,
    right: str,
    ledger: MappingLedger | None,
    *,
    normalized_left: str = "",
    normalized_right: str = "",
    confidence: float = 0.0,
) -> RemediationProposal | None:
    """Propose a league equivalence for the two labels, or ``None``.

    The entry is built from the gate's normalized labels — the form the ledger
    and ``league_equivalences.json`` actually compare — while the raw labels are
    kept for display. A generic or missing label is not proposal-worthy.
    """
    left_norm = (normalized_left or left).strip()
    right_norm = (normalized_right or right).strip()
    if not left_norm or not right_norm or left_norm == right_norm:
        return None
    return _proposal(
        kind="league_equivalence",
        entry=league_equivalence_key(left_norm, right_norm),
        left=left.strip() or left_norm,
        right=right.strip() or right_norm,
        ledger=ledger,
        claim_key=league_equivalence_key(left_norm, right_norm),
        confidence=confidence,
    )


def candidate_class(candidate: CandidateReview) -> str:
    """The cheap class of what would move this candidate.

    Kept identical to the review tab's existing classification: alias work
    first, then a league mapping, then the machine link check, then anything no
    human action moves.
    """
    if candidate.alias_actionable:
        return "alias"
    blockers = [
        reason
        for reason in candidate.rule_rejections
        if reason not in LINK_REJECTION_REASONS
    ]
    if any("league" in reason for reason in blockers):
        return "league"
    if candidate.link_blocked:
        return "link"
    return "other"


def candidate_action(candidate: CandidateReview) -> str:
    """The proposal action, falling back to the cheap class when unassessed."""
    if candidate.remediation is not None:
        return candidate.remediation.action
    return {
        "alias": "alias",
        "league": "league",
        "link": "system_link",
        "other": "none",
    }[candidate_class(candidate)]


def blocker_counts(candidates: Iterable[CandidateReview]) -> dict[str, int]:
    """Count candidates by the cheap blocker class reported in health."""
    counts = {"alias": 0, "league": 0, "link": 0, "other": 0}
    for candidate in candidates:
        counts[candidate_class(candidate)] += 1
    return counts


def remediation_counts(candidates: Iterable[CandidateReview]) -> dict[str, int]:
    """Count what a reviewer can close, with the queue size as the denominator.

    ``system_link`` is deliberately separate from ``none``: an unproven link is
    a machine check that can close the pair with no human action, so folding it
    into "nothing can be done" would be wrong.
    """
    counts = {
        "alias": 0,
        "league": 0,
        "alias+league": 0,
        "none": 0,
        "system_link": 0,
    }
    for candidate in candidates:
        action = candidate_action(candidate)
        if action in counts:
            counts[action] += 1
        else:  # unknown action is reported as not closeable, never as progress
            counts["none"] += 1
    return counts


def group_candidates(
    candidates: Sequence[CandidateReview],
    limit: int = MAX_BLOCKER_GROUPS,
) -> list[dict[str, Any]]:
    """Group repeated blockers by book pair, league, action and exact reason.

    The denominator is the queue size for this feed, not the number of priced
    opportunities. It exists to rank review work, never to claim coverage.
    """
    total = len(candidates)
    groups: Counter[tuple[str, str, str, tuple[str, ...]]] = Counter()
    examples: dict[tuple[str, str, str, tuple[str, ...]], CandidateReview] = {}
    for candidate in candidates:
        action = candidate_action(candidate)
        book_pair = "|".join(sorted(set(candidate.bookmakers)))
        league = candidate.league or "unknown league"
        reasons = tuple(candidate.rule_rejections)
        key = (action, book_pair, league, reasons)
        groups[key] += 1
        examples.setdefault(key, candidate)

    rows: list[dict[str, Any]] = []
    for key, count in groups.items():
        action, book_pair, league, reasons = key
        example = examples[key]
        rows.append(
            {
                "action": action,
                "closeable": action in CLOSEABLE_ACTIONS,
                "book_pair": book_pair,
                "bookmakers": book_pair.split("|") if book_pair else [],
                "league": league,
                "reasons": list(reasons),
                "gate_reason": reasons[0] if reasons else "",
                "count": count,
                "share": round(count / total, 4) if total else 0.0,
                "example": {
                    "home_team": example.home_team,
                    "away_team": example.away_team,
                    "kickoff": example.kickoff.isoformat() if example.kickoff else None,
                },
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["action"], row["book_pair"], row["league"]))
    return rows[: max(1, limit)]


def remediation_summary(
    candidates: Sequence[CandidateReview],
    limit: int = MAX_BLOCKER_GROUPS,
) -> dict[str, Any]:
    """One bounded, denominator-carrying block for health and the dashboard."""
    counts = remediation_counts(candidates)
    closeable = sum(counts[action] for action in CLOSEABLE_ACTIONS)
    return {
        "total": len(candidates),
        "closeable": closeable,
        "counts": counts,
        "groups": group_candidates(candidates, limit),
        "note": (
            "Queue size is a diagnostic, not a coverage-progress claim. "
            + PROPOSAL_NOTE
        ),
    }
