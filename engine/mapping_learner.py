"""Learn team aliases and league equivalences from shared fixtures.

This is the machine replacement for the human review queue. It reads one or more
scan payloads and writes claims into :mod:`engine.mapping_evidence`:

* two books with the same non-empty Betradar id are the same fixture;
* one team slot matching exactly (raw spelling, either orientation), with the
  other differing, a kickoff inside the verified window and equal category tags,
  proves the differing slot is one club under two spellings;
* two books naming the same fixture prove their league names are equivalent.

Nothing here is fuzzy-guessed. Similarity is recorded as a weak observation and
can never accept a claim; a pair with only similarity is quarantined. A pair
whose names appear as opponents is rejected with ``opponent_contradiction``.
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from engine import name_identity
from engine.certainty import CertaintyGate
from engine.mapping_evidence import (
    Evidence,
    MappingLedger,
    league_equivalence_key,
    team_alias_key,
)
from engine.matcher import GENERIC_LEAGUES, MatchMatcher
from engine.team_resolver import revoke_contradictions
from models.schemas import Match

# Auto-accept window for a durable alias. Production measurements put 90% of
# real cross-book matches within five minutes; repeated games of one pairing are
# about fifteen minutes apart, so a wider window starts merging the wrong game.
ALIAS_WINDOW_MINUTES = 5
SIMILARITY_FLOOR = 90


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _raw(name: str) -> str:
    return CertaintyGate._raw_team_key(name)


def _delta_minutes(a: Match, b: Match) -> float | None:
    if not a.kickoff or not b.kickoff:
        return None
    return abs((_naive(a.kickoff) - _naive(b.kickoff)).total_seconds()) / 60.0


def _source_name(match: Match, side: str) -> str:
    return (getattr(match, f"{side}_team_source") or getattr(match, f"{side}_team")).strip()


def _observation(
    evidence_type: str,
    *,
    scan: str,
    books: tuple[str, ...],
    detail: dict[str, Any],
) -> Evidence:
    return Evidence(
        type=evidence_type,
        detail=detail,
        scan=scan,
        books=books,
        observed_at=datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
    )


@dataclass
class LearningReport:
    scan: str
    matches: int = 0
    pairs_considered: int = 0
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    diff: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan": self.scan,
            "matches": self.matches,
            "pairs_considered": self.pairs_considered,
            "accepted": sorted(self.accepted),
            "rejected": sorted(self.rejected),
            "quarantined": sorted(self.quarantined),
            "counts": {
                "accepted": len(self.accepted),
                "rejected": len(self.rejected),
                "quarantined": len(self.quarantined),
            },
            "diff": self.diff,
        }


def _opponent_pairs(matches: list[Match]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for match in matches:
        home, away = _raw(_source_name(match, "home")), _raw(_source_name(match, "away"))
        if home and away:
            pairs.add(frozenset((home, away)))
    return pairs


def _choose_orientation(a: Match, b: Match) -> bool:
    """Return True when b's home/away should be read reversed against a."""
    a_home = a.home_team_normalized or _raw(_source_name(a, "home"))
    a_away = a.away_team_normalized or _raw(_source_name(a, "away"))
    b_home = b.home_team_normalized or _raw(_source_name(b, "home"))
    b_away = b.away_team_normalized or _raw(_source_name(b, "away"))
    direct = fuzz.token_set_ratio(a_home, b_home) + fuzz.token_set_ratio(a_away, b_away)
    swapped = fuzz.token_set_ratio(a_home, b_away) + fuzz.token_set_ratio(a_away, b_home)
    return swapped > direct


def _fixture_detail(a: Match, b: Match, **extra: Any) -> dict[str, Any]:
    return {
        "a": {"book": a.bookmaker, "event": a.event_id, "home": _source_name(a, "home"), "away": _source_name(a, "away")},
        "b": {"book": b.bookmaker, "event": b.event_id, "home": _source_name(b, "home"), "away": _source_name(b, "away")},
        "kickoff": _naive(a.kickoff).isoformat() if a.kickoff else "",
        "league_pair": [a.league, b.league],
        "category": sorted(a.category_tags or []),
        **extra,
    }


def _needs_corroboration(left: str, right: str) -> bool:
    """Whether one shared fixture is too weak to accept this alias.

    A single-token name against a longer name is the dangerous shape:
    "Yokohama" and "Yokohama FC" are different clubs, but one book may use the
    bare city for either. A low-similarity pair is equally unsafe. Both need a
    second independent observation (or a Betradar id) before they authorize a
    pairing.
    """
    left_tokens = name_identity.tokens(left)
    right_tokens = name_identity.tokens(right)
    if not left_tokens or not right_tokens:
        return True
    if (len(left_tokens) == 1) != (len(right_tokens) == 1):
        return True
    return name_identity.similarity(left, right) < 0.7


def _observation_count(ledger: MappingLedger, key: str, scan: str, books: tuple[str, str]) -> int:
    claim = ledger.get("team_alias", key)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    if claim is not None:
        for evidence in claim.evidence:
            if evidence.type in ("exact_shared_fixture", "betradar_shared_id"):
                seen.add((evidence.scan, tuple(sorted(evidence.books))))
    seen.add((scan, tuple(sorted(books))))
    return len(seen)


def _learn_pair(
    a: Match,
    b: Match,
    *,
    scan: str,
    ledger: MappingLedger,
    report: LearningReport,
    opponent_pairs: set[frozenset[str]],
    league_observations: dict[str, set[str]],
    league_claim_keys: dict[str, tuple[str, str]],
) -> None:
    if a.bookmaker == b.bookmaker:
        return
    delta = _delta_minutes(a, b)
    if delta is None or delta > ALIAS_WINDOW_MINUTES:
        return
    if set(a.category_tags or []) != set(b.category_tags or []):
        return

    report.pairs_considered += 1
    a_id, b_id = a.betradar_id or "", b.betradar_id or ""
    if a_id and b_id and a_id != b_id:
        # Two different provider ids are two different matches; nothing a name
        # says can make them one fixture.
        return

    same_id = bool(a_id and b_id and a_id == b_id)
    a_home, a_away = _raw(_source_name(a, "home")), _raw(_source_name(a, "away"))
    b_home, b_away = _raw(_source_name(b, "home")), _raw(_source_name(b, "away"))

    direct_home = a_home == b_home
    direct_away = a_away == b_away
    swapped_home = a_home == b_away
    swapped_away = a_away == b_home

    exact_direct = direct_home and direct_away
    exact_swapped = swapped_home and swapped_away
    # One exact slot is enough: the other slot is then the same club under a
    # different spelling. That is the rule `derive_mappings.py` already used.
    direct_one = direct_home != direct_away
    swapped_one = swapped_home != swapped_away
    if not (same_id or exact_direct or exact_swapped or direct_one or swapped_one):
        # No ground truth. Record a weak observation only when the names look
        # alike, so the pair is visible as quarantined rather than lost.
        score = max(
            fuzz.token_set_ratio(a_home, b_home),
            fuzz.token_set_ratio(a_away, b_away),
            fuzz.token_set_ratio(a_home, b_away),
            fuzz.token_set_ratio(a_away, b_home),
        )
        if score < SIMILARITY_FLOOR:
            return
        orientation = _choose_orientation(a, b)
        left_home, right_home = (a_home, b_away) if orientation else (a_home, b_home)
        left_away, right_away = (a_away, b_home) if orientation else (a_away, b_away)
        for left, right in ((left_home, right_home), (left_away, right_away)):
            if left == right:
                continue
            key = team_alias_key(left, right)
            claim = ledger.quarantine(
                "team_alias",
                key,
                [
                    _observation(
                        "similarity",
                        scan=scan,
                        books=(a.bookmaker, b.bookmaker),
                        detail=_fixture_detail(a, b, score=round(score, 1)),
                    )
                ],
                "similarity_only",
            )
            if claim.status == "quarantined":
                report.quarantined.append(f"team_alias:{key}")
        return

    # One exact slot plus one differing slot proves the differing slot's alias.
    if exact_swapped or (swapped_one and not direct_one):
        orientation_swapped = True
    elif exact_direct or (direct_one and not swapped_one):
        orientation_swapped = False
    else:
        orientation_swapped = _choose_orientation(a, b)

    pairs = (
        ((a_home, b_away), (a_away, b_home))
        if orientation_swapped
        else ((a_home, b_home), (a_away, b_away))
    )

    for left, right in pairs:
        if left == right:
            continue
        key = team_alias_key(left, right)
        if frozenset((left, right)) in opponent_pairs:
            ledger.reject(
                "team_alias",
                key,
                [
                    _observation(
                        "opponent_contradiction",
                        scan=scan,
                        books=(a.bookmaker, b.bookmaker),
                        detail=_fixture_detail(a, b),
                    )
                ],
                "opponent_contradiction",
                contradiction="opponent_contradiction",
            )
            report.rejected.append(f"team_alias:{key}")
            continue

        if same_id:
            evidence_type = "betradar_shared_id"
            detail = _fixture_detail(a, b, id=a_id)
        else:
            evidence_type = "exact_shared_fixture"
            detail = _fixture_detail(
                a,
                b,
                other_slot_exact=True,
                orientation="swapped" if orientation_swapped else "direct",
            )
        evidence = _observation(
            evidence_type,
            scan=scan,
            books=(a.bookmaker, b.bookmaker),
            detail=detail,
        )
        if not same_id and _needs_corroboration(left, right) and _observation_count(
            ledger, key, scan, (a.bookmaker, b.bookmaker)
        ) < 2:
            ledger.quarantine(
                "team_alias",
                key,
                [evidence],
                "needs_corroboration",
            )
            report.quarantined.append(f"team_alias:{key}")
            continue
        claim = ledger.accept(
            "team_alias",
            key,
            [evidence],
            "same Betradar id" if same_id else "one exact slot and one differing slot",
        )
        (report.accepted if claim.status == "accepted" else report.quarantined).append(
            f"team_alias:{key}"
        )

    # League equivalence, only when both names are real and differ.
    a_league = (a.league_normalized or "").strip()
    b_league = (b.league_normalized or "").strip()
    if (
        a_league
        and b_league
        and a_league != b_league
        and a_league not in GENERIC_LEAGUES
        and b_league not in GENERIC_LEAGUES
    ):
        key = league_equivalence_key(a_league, b_league)
        league_observations[a_league].add(b_league)
        league_observations[b_league].add(a_league)
        league_claim_keys[key] = (a_league, b_league)
        evidence_type = "betradar_shared_id" if same_id else "exact_shared_fixture"
        claim = ledger.accept(
            "league_equivalence",
            key,
            [
                _observation(
                    evidence_type,
                    scan=scan,
                    books=(a.bookmaker, b.bookmaker),
                    detail=_fixture_detail(a, b, leagues=[a_league, b_league]),
                )
            ],
            "same Betradar id" if same_id else "shared exact fixture",
        )
        (report.accepted if claim.status == "accepted" else report.quarantined).append(
            f"league_equivalence:{key}"
        )


def learn(
    matches: list[Match],
    ledger: MappingLedger | None = None,
    *,
    scan: str = "",
) -> tuple[MappingLedger, LearningReport]:
    """Ingest one scan and return the updated ledger plus a diff report."""
    ledger = ledger if ledger is not None else MappingLedger()
    previous = MappingLedger(ledger.path)
    previous.claims = copy.deepcopy(ledger.claims)
    # A shallow snapshot is enough for diff: status and confidence are scalars.
    scan_id = scan or datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    report = LearningReport(scan=scan_id)

    normalized = MatchMatcher().normalize_matches([m.model_copy(deep=True) for m in matches])
    report.matches = len(normalized)
    opponents = _opponent_pairs(normalized)
    league_observations: dict[str, set[str]] = defaultdict(set)
    league_claim_keys: dict[str, tuple[str, str]] = {}

    for i, left in enumerate(normalized):
        for right in normalized[i + 1 :]:
            _learn_pair(
                left,
                right,
                scan=scan_id,
                ledger=ledger,
                report=report,
                opponent_pairs=opponents,
                league_observations=league_observations,
                league_claim_keys=league_claim_keys,
            )

    # Team-set fingerprints. A league name seen with at least three distinct
    # teams gets a fingerprint claim; the gate uses it to resolve an ambiguous
    # name per fixture. Two teams (one fixture) is too little to be a set.
    league_teams: dict[str, set[str]] = defaultdict(set)
    for match in normalized:
        league = (match.league_normalized or "").strip()
        if league and league not in GENERIC_LEAGUES:
            league_teams[league].update(
                {
                    _raw(_source_name(match, "home")),
                    _raw(_source_name(match, "away")),
                }
            )
    books = tuple(sorted({match.bookmaker for match in normalized}))
    for league, teams in league_teams.items():
        if len(teams) < 3:
            continue
        claim = ledger.accept(
            "league_fingerprint",
            league,
            [
                _observation(
                    "league_fingerprint",
                    scan=scan_id,
                    books=books,
                    detail={"teams": sorted(teams)},
                )
            ],
            "team set observed under this league name",
        )
        (report.accepted if claim.status == "accepted" else report.quarantined).append(
            f"league_fingerprint:{league}"
        )

    # A chain of aliases must not merge two clubs that are listed as opponents.
    # Revoke the weakest edge on each contradicting path, then re-check.
    for key in revoke_contradictions(ledger, opponents):
        report.rejected.append(f"team_alias:{key}")

    # A league name that one book uses for two different competitions is not
    # globally resolvable. Quarantine every claim that mentions it; the fixture
    # resolver (A1-5) may still resolve individual fixtures by their teams.
    ambiguous = {
        name for name, partners in league_observations.items() if len(partners) > 1
    }
    for key, (league_left, league_right) in league_claim_keys.items():
        if league_left in ambiguous or league_right in ambiguous:
            league_claim = ledger.get("league_equivalence", key)
            if league_claim is not None and league_claim.status != "rejected":
                ledger.quarantine(
                    "league_equivalence",
                    key,
                    list(league_claim.evidence),
                    "ambiguous_league_name",
                    force=True,
                )
                report.quarantined.append(f"league_equivalence:{key}")

    report.diff = ledger.diff(previous)
    return ledger, report


def load_matches(paths: list[str]) -> list[Match]:
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
