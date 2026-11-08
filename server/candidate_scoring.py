"""Pure candidate scoring for the review queue (M3-1 stage 1).

These helpers decide nothing about trust: they score how close two raw fixtures
are, give a pair its stable review id, and order a queue so a reviewer sees the
pairs they can act on first. They hold no module state and perform no I/O, so
``server.api._build_candidates`` can run the whole walk in a scan worker thread.

The gate calls and the remediation proposals stay in ``server.api``; only the
pure, reusable scoring lives here. Moving a helper here must not change a
score, an id or an order, and the queue tests compare the two directly.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from typing import NamedTuple

from rapidfuzz import fuzz

from models.schemas import CandidateReview, Match

# Pairs are bucketed by kickoff so the walk compares only neighbours. Kept here
# with the scoring code; the candidate window itself stays in ``server.api``.
CANDIDATE_BUCKET_SECONDS = 1800


class TeamTokens(NamedTuple):
    """Pre-computed team strings and their token sets for the cheap prefilter."""

    home: str
    away: str
    home_tokens: frozenset[str]
    away_tokens: frozenset[str]
    all_tokens: frozenset[str]
    home_bigrams: frozenset[str]
    away_bigrams: frozenset[str]
    all_bigrams: frozenset[str]

    @classmethod
    def of(cls, match: Match) -> TeamTokens:
        home = match.home_team_normalized or match.home_team
        away = match.away_team_normalized or match.away_team
        home_tokens, away_tokens = frozenset(home.split()), frozenset(away.split())
        home_bigrams, away_bigrams = bigrams(home), bigrams(away)
        return cls(
            home, away, home_tokens, away_tokens, home_tokens | away_tokens,
            home_bigrams, away_bigrams, home_bigrams | away_bigrams,
        )


class FoundPair(NamedTuple):
    """A queued candidate plus the evidence used to rank it."""

    candidate: CandidateReview
    alias_actionable: bool
    closeable: bool
    human_blockers: int
    kickoff_delta_minutes: float
    team_similarity: float
    left: Match
    right: Match


def kickoff_bucket(match: Match) -> int | None:
    """Return the kickoff bucket a match belongs to, or None when it has no kickoff."""
    kickoff = match.kickoff
    if not kickoff:
        return None
    if kickoff.tzinfo is None:  # naive kickoffs are UTC wall-clock
        kickoff = kickoff.replace(tzinfo=UTC)
    return int(kickoff.timestamp() // CANDIDATE_BUCKET_SECONDS)


def match_event_ref(match: Match) -> str:
    """Return the book's own identifier for a fixture."""
    return match.match_code or match.event_id


def match_side_key(match: Match) -> str:
    """Identify one book's fixture inside a pair or a match group."""
    return f"{match.bookmaker}|{match_event_ref(match)}"


def kickoff_delta_minutes(left: Match, right: Match) -> float:
    """Return the absolute kickoff gap used to rank candidates."""
    if not left.kickoff or not right.kickoff:
        return float("inf")
    first = left.kickoff if left.kickoff.tzinfo else left.kickoff.replace(tzinfo=UTC)
    second = right.kickoff if right.kickoff.tzinfo else right.kickoff.replace(tzinfo=UTC)
    return abs((first - second).total_seconds()) / 60.0


def bigrams(text: str) -> frozenset[str]:
    """Return the character bigrams of a team string."""
    padded = f" {text} "
    return frozenset(padded[index:index + 2] for index in range(len(padded) - 1))


def shares_any_signal(left: TeamTokens, right: TeamTokens) -> bool:
    """Cheap "this pair is not hopeless" test, run before the fuzzy scorer.

    True when the two fixtures share a token, one team name contains the other,
    or they share a character bigram. It exists only to skip the ~730k fuzzy
    calls of a 7k-match scan; the decision itself is still the fuzzy rule in
    `team_similarity`, so this test must never admit-or-veto on its own. The
    bigram clause is what keeps a pure typo ("Millonarios" vs "Millionarios")
    in the queue — it shares no token at all, and a token-only gate drops it.
    """
    return bool(
        left.all_tokens & right.all_tokens
        or left.all_bigrams & right.all_bigrams
        or token_run_shared(left, right)
    )


def team_similarity(left: TeamTokens, right: TeamTokens) -> float:
    """The brief's plausibility rule: best token-set overlap over both orders.

    The inner gate applies the *same* test as `shares_any_signal`, per team
    slot, so it can only skip a slot the outer gate already ruled hopeless. The
    two therefore agree exactly, and the returned score is the plain
    ``max(token_set_ratio(...))`` over the four combinations whenever the pair
    is not hopeless at all.
    """
    if not shares_any_signal(left, right):
        return 0.0
    best = 0.0
    for first, second, first_tokens, second_tokens, first_bigrams, second_bigrams in (
        (left.home, right.home, left.home_tokens, right.home_tokens,
         left.home_bigrams, right.home_bigrams),
        (left.home, right.away, left.home_tokens, right.away_tokens,
         left.home_bigrams, right.away_bigrams),
        (left.away, right.home, left.away_tokens, right.home_tokens,
         left.away_bigrams, right.home_bigrams),
        (left.away, right.away, left.away_tokens, right.away_tokens,
         left.away_bigrams, right.away_bigrams),
    ):
        if not (
            first_tokens & second_tokens
            or first_bigrams & second_bigrams
            or first in second
            or second in first
        ):
            continue
        score = fuzz.token_set_ratio(first, second)
        if score > best:
            best = score
            if best == 100.0:  # the scorer cannot return more
                break
    return best


def token_run_shared(left: TeamTokens, right: TeamTokens) -> bool:
    """Return whether one team string is a prefix/substring of the other's."""
    return (
        left.home in right.home or right.home in left.home
        or left.home in right.away or right.away in left.home
        or left.away in right.home or right.home in left.away
        or left.away in right.away or right.away in left.away
    )


def canonical_pair_key(left: Match, right: Match) -> str:
    """Return the order-independent identity of a pair from both raw claims."""
    def side(match: Match) -> str:
        return f"{match_side_key(match)}|{match.home_team}|{match.away_team}"

    return "||".join(sorted((side(left), side(right))))


def candidate_id(canonical_key: str) -> str:
    """Return a stable id for a pair so a re-scan does not churn the queue.

    The queue is keyed by this id and the review UI approves by it, so it has to
    be reproducible from the pair itself and free of truncation collisions.
    """
    # Not used for security: the id only needs to be stable and collision-free
    # for a bounded review queue, so the cheaper digest is deliberate.
    return hashlib.sha1(
        canonical_key.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:16]


def pair_priority(pair: FoundPair) -> tuple:
    """The review order: what a human can act on first, then the closest pair.

    One definition for the transient trim and the final cut (M2-4), so the two
    cannot disagree about which pairs survive the cap.
    """
    return (
        not pair.closeable,
        not pair.alias_actionable,
        pair.human_blockers,
        pair.kickoff_delta_minutes,
        -pair.team_similarity,
        pair.candidate.id,
    )
