"""CertaintyGate — deterministic proofs that two matches are the same event.

The rule stage of the mapping pipeline. Produces ``verified`` only when league,
kickoff, category, team identity, orientation, and link evidence all hold.
Ambiguous pairs get ``suggested`` with explicit reasons; ``rejected`` when a
hard gate contradicts the claim.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from rapidfuzz import fuzz

from config.settings import VERIFIED_KICKOFF_WINDOW_MINUTES
from engine.normalizer import TeamNormalizer
from models.schemas import Match, MatchEventStatus, MatchEvidence, MatchGroup

HARD_REJECT_REASONS = frozenset({"league_mismatch", "category_mismatch", "orientation_unresolved"})


@dataclass
class GateResult:
    """The deterministic gate result for a candidate pair."""

    status: MatchEventStatus
    reasons: list[str] = field(default_factory=list)
    evidence: list[MatchEvidence] = field(default_factory=list)
    is_swapped: bool = False


class CertaintyGate:
    """Evaluate candidate same-event pairs against hard, deterministic gates."""

    def __init__(
        self,
        kickoff_window_minutes: int = VERIFIED_KICKOFF_WINDOW_MINUTES,
        alias_allowlist: set[str] | None = None,
        league_equivalences: set[tuple[str, str]] | None = None,
    ) -> None:
        self.normalizer = TeamNormalizer()
        self.kickoff_window_minutes = kickoff_window_minutes
        self.alias_allowlist = alias_allowlist or set()
        self.league_equivalences = league_equivalences or set()

    def normalize(self, matches: list[Match]) -> list[Match]:
        """Populate normalized fields for matches that do not already have them."""
        for m in matches:
            m.league_normalized = m.league_normalized or self.normalizer.normalize_league(m.league)
            m.home_team_normalized = m.home_team_normalized or self.normalizer.normalize_team(
                m.home_team
            )
            m.away_team_normalized = m.away_team_normalized or self.normalizer.normalize_team(
                m.away_team
            )
            m.category_tags = m.category_tags or self.normalizer.detect_special_category(
                f"{m.home_team} {m.away_team} {m.league}"
            )
        return matches

    def _league_ok(self, a_league: str, b_league: str) -> bool:
        """Return whether two normalized league IDs are the same or equivalent."""
        if not a_league or not b_league:
            return False
        if a_league == b_league:
            return True
        return (
            (a_league, b_league) in self.league_equivalences
            or (b_league, a_league) in self.league_equivalences
        )

    @staticmethod
    def _as_naive_utc(dt: datetime) -> datetime:
        """Represent both aware and naive kickoffs in a common naive UTC form."""
        return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt

    def _kickoff_delta_minutes(self, a: Match, b: Match) -> float | None:
        """Return the absolute kickoff difference, or ``None`` if either is missing."""
        if not a.kickoff or not b.kickoff:
            return None
        return abs(
            (self._as_naive_utc(a.kickoff) - self._as_naive_utc(b.kickoff)).total_seconds()
        ) / 60.0

    @staticmethod
    def _raw_team_key(name: str) -> str:
        """Make only lossless superficial raw-name comparisons.

        This deliberately does not call the normalizer's fuzzy fallback. Team
        identity decisions that see different raw forms must go through the
        explicit alias allowlist.
        """
        return " ".join(name.strip().casefold().split()).rstrip(".")

    def _team_pair_details(
        self,
        left_raw: str,
        left_normalized: str,
        right_raw: str,
        right_normalized: str,
    ) -> tuple[bool, bool]:
        """Return ``(ok, allowlist_used)`` for one raw/canonical team pair."""
        if not (left_raw and left_normalized and right_raw and right_normalized):
            return False, False

        left_key = self._raw_team_key(left_raw)
        right_key = self._raw_team_key(right_raw)
        if left_key and left_key == right_key:
            return left_normalized == right_normalized, False

        # A canonical collision alone is never enough. If the raw forms differ,
        # the pair is an alias candidate and must be explicitly reviewed.
        allowlisted = self._is_allowlisted(left_raw, right_raw) or self._is_allowlisted(
            left_normalized, right_normalized
        )
        if not allowlisted:
            return False, False

        fuzzy_score = max(
            fuzz.token_set_ratio(left_key, right_key),
            fuzz.partial_ratio(left_key, right_key),
        )
        return fuzzy_score >= 90, True

    def _team_pair_ok(self, left: str, right: str) -> bool:
        """Backward-compatible helper for matching two already-normalized names."""
        ok, _ = self._team_pair_details(left, left, right, right)
        return ok

    def _team_pair_uses_allowlist(self, left: str, right: str) -> bool:
        """Return whether two normalized names use the reviewed alias path."""
        _, used = self._team_pair_details(left, left, right, right)
        return used

    def _teams_match_details(self, a: Match, b: Match) -> tuple[bool, bool, bool]:
        """Return ``(ok, is_swapped, allowlist_used)`` for raw/canonical teams."""
        ah, aa = a.home_team_normalized, a.away_team_normalized
        bh, ba = b.home_team_normalized, b.away_team_normalized
        if not (ah and aa and bh and ba):
            return False, False, False

        if (
            self._raw_team_key(a.home_team) == self._raw_team_key(b.home_team)
            and self._raw_team_key(a.away_team) == self._raw_team_key(b.away_team)
            and ah == bh
            and aa == ba
        ):
            return True, False, False
        if (
            self._raw_team_key(a.home_team) == self._raw_team_key(b.away_team)
            and self._raw_team_key(a.away_team) == self._raw_team_key(b.home_team)
            and ah == ba
            and aa == bh
        ):
            return True, True, False

        direct_home_ok, direct_home_alias = self._team_pair_details(
            a.home_team, ah, b.home_team, bh
        )
        direct_away_ok, direct_away_alias = self._team_pair_details(
            a.away_team, aa, b.away_team, ba
        )
        if direct_home_ok and direct_away_ok:
            return True, False, direct_home_alias or direct_away_alias

        swapped_home_ok, swapped_home_alias = self._team_pair_details(
            a.home_team, ah, b.away_team, ba
        )
        swapped_away_ok, swapped_away_alias = self._team_pair_details(
            a.away_team, aa, b.home_team, bh
        )
        if swapped_home_ok and swapped_away_ok:
            return True, True, swapped_home_alias or swapped_away_alias

        return False, False, False

    def _teams_ok(self, a: Match, b: Match) -> tuple[bool, bool, str]:
        """Return ``(ok, is_swapped, reason)`` for normalized team identities.

        A fuzzy alias is accepted only as part of a complete home/away
        orientation. In particular, a single cross-side fuzzy hit is not enough
        to claim a swap.
        """
        ok, is_swapped, _ = self._teams_match_details(a, b)
        return ok, is_swapped, "" if ok else "team_unresolved"

    def _teams_use_allowlist(self, a: Match, b: Match) -> bool:
        """Return whether a successful team result relies on a fuzzy alias."""
        _, _, allowlist_used = self._teams_match_details(a, b)
        return allowlist_used

    def _is_allowlisted(self, left: str, right: str) -> bool:
        """Return whether the unordered raw/canonical pair is explicitly reviewed."""
        if not self.alias_allowlist:
            return False
        pair = {self._raw_team_key(left), self._raw_team_key(right)}
        return any(entry == pair for entry in self.alias_allowlist_entries)

    @property
    def alias_allowlist_entries(self) -> list[set[str]]:
        """Return normalized unordered sets parsed from pipe-delimited allowlist entries."""
        entries: list[set[str]] = []
        for entry in self.alias_allowlist:
            parts = {self._raw_team_key(part) for part in entry.split("|") if part.strip()}
            if len(parts) == 2:
                entries.append(parts)
        return entries

    @staticmethod
    def _link_evidence(m: Match) -> MatchEvidence:
        if m.deep_link_verified:
            return MatchEvidence(
                rule="link_evidence",
                source="rule",
                confidence=1.0,
                reason="verified_link",
            )
        if m.event_id or m.url:
            return MatchEvidence(
                rule="link_evidence",
                source="rule",
                confidence=0.0,
                reason="link_unverified",
            )
        return MatchEvidence(
            rule="link_evidence",
            source="rule",
            confidence=0.5,
            reason="no_event_link",
        )

    def evaluate_pair(self, a: Match, b: Match) -> GateResult:
        """Evaluate a pair and return a deterministic status plus evidence."""
        reasons: list[str] = []
        evidence: list[MatchEvidence] = []

        # League identity.
        a_league, b_league = a.league_normalized or "", b.league_normalized or ""
        league_ok = self._league_ok(a_league, b_league)
        if not league_ok:
            reasons.append("league_mismatch")
        evidence.append(
            MatchEvidence(
                rule="league_identity",
                source="rule",
                confidence=1.0 if league_ok else 0.0,
                league_pair=[a_league, b_league],
            )
        )

        # Kickoff.
        delta = self._kickoff_delta_minutes(a, b)
        kickoff_ok = delta is not None and delta <= self.kickoff_window_minutes
        if delta is None:
            reasons.append("kickoff_missing")
        elif not kickoff_ok:
            reasons.append("kickoff_delta")
        evidence.append(
            MatchEvidence(
                rule="kickoff",
                source="rule",
                confidence=(
                    1.0
                    if delta is not None and delta <= 5
                    else (0.8 if delta is not None else 0.0)
                ),
                kickoff_delta_minutes=delta,
            )
        )

        # Category identity.
        a_tags, b_tags = set(a.category_tags or []), set(b.category_tags or [])
        category_ok = a_tags == b_tags
        if not category_ok:
            reasons.append("category_mismatch")

        # Team identity and orientation.
        teams_ok, is_swapped, team_reason = self._teams_ok(a, b)
        allowlist_used = teams_ok and self._teams_use_allowlist(a, b)
        if allowlist_used and not (league_ok and kickoff_ok and category_ok):
            teams_ok = False
            team_reason = "team_unresolved"

        exact_teams = (
            a.home_team_normalized == b.home_team_normalized
            and a.away_team_normalized == b.away_team_normalized
        )
        if not teams_ok:
            team_source: Literal["rule", "allowlist"] = "rule"
            team_confidence = 0.0
            team_evidence_reason = team_reason or "team_unresolved"
        elif allowlist_used:
            team_source = "allowlist"
            team_confidence = 1.0
            team_evidence_reason = "swapped" if is_swapped else "allowlisted_alias"
        elif exact_teams:
            team_source = "rule"
            team_confidence = 1.0
            team_evidence_reason = "exact"
        else:
            team_source = "rule"
            team_confidence = 1.0
            team_evidence_reason = "swapped" if is_swapped else "exact"

        if not teams_ok:
            reasons.append(team_evidence_reason)
        evidence.append(
            MatchEvidence(
                rule="team_identity",
                source=team_source,
                confidence=team_confidence,
                reason=team_evidence_reason,
                allowlist_entries=(
                    sorted(self.alias_allowlist) if team_source == "allowlist" else []
                ),
            )
        )

        # Link evidence. A pair is verified only when both sides are proven.
        link_reasons: set[str] = set()
        for m in (a, b):
            link_evidence = self._link_evidence(m)
            evidence.append(link_evidence)
            if link_evidence.reason == "link_unverified":
                link_reasons.add("link_unverified")
            elif link_evidence.reason == "no_event_link":
                link_reasons.add("no_event_link")
        reasons.extend(sorted(link_reasons))

        if reasons:
            hard = [reason for reason in reasons if reason in HARD_REJECT_REASONS]
            status: MatchEventStatus = "rejected" if hard else "suggested"
        else:
            status = "verified"
        return GateResult(
            status=status,
            reasons=reasons,
            evidence=evidence,
            is_swapped=is_swapped,
        )

    def _group_team_orientation(self, match: Match, group: MatchGroup) -> tuple[bool, bool] | None:
        """Check a candidate against the group's canonical team fields."""
        if not group.canonical_home or not group.canonical_away:
            return None
        if not (match.home_team_normalized and match.away_team_normalized):
            return False, False

        home_values = {
            group.canonical_home,
            self.normalizer.normalize_team(group.canonical_home),
            self._raw_team_key(group.canonical_home),
        }
        away_values = {
            group.canonical_away,
            self.normalizer.normalize_team(group.canonical_away),
            self._raw_team_key(group.canonical_away),
        }
        if (
            match.home_team_normalized in home_values
            and match.away_team_normalized in away_values
        ):
            return True, False
        if (
            match.home_team_normalized in away_values
            and match.away_team_normalized in home_values
        ):
            return True, True
        return False, False

    def _group_kickoff_reason(self, match: Match, group: MatchGroup) -> str | None:
        """Return an additional kickoff reason for the group's canonical time."""
        if group.kickoff is None:
            return None
        if match.kickoff is None:
            return "kickoff_missing"
        delta = abs(
            (self._as_naive_utc(match.kickoff) - self._as_naive_utc(group.kickoff)).total_seconds()
        ) / 60.0
        if delta > self.kickoff_window_minutes:
            return "kickoff_delta"
        return None

    def evaluate(self, match: Match, group: MatchGroup) -> GateResult:
        """Evaluate a match against the canonical fields of an existing group."""
        if not group.matches:
            return GateResult(status="rejected", reasons=["team_unresolved"])

        anchor = group.matches[0]
        result = self.evaluate_pair(match, anchor)

        group_teams = self._group_team_orientation(match, group)
        if group_teams is not None:
            group_teams_ok, group_is_swapped = group_teams
            if group_teams_ok:
                result.is_swapped = result.is_swapped or group_is_swapped
            elif "team_unresolved" not in result.reasons:
                result.reasons.append("team_unresolved")

        group_kickoff_reason = self._group_kickoff_reason(match, group)
        if group_kickoff_reason and group_kickoff_reason not in result.reasons:
            result.reasons.append(group_kickoff_reason)

        if group.league:
            match_league = match.league_normalized or ""
            if match_league and match_league != group.league and not self._league_ok(
                match_league, group.league
            ):
                if "league_mismatch" not in result.reasons:
                    result.reasons.append("league_mismatch")

        hard = [reason for reason in result.reasons if reason in HARD_REJECT_REASONS]
        if hard:
            result.status = "rejected"
        elif result.reasons:
            result.status = "suggested"
        else:
            result.status = "verified"
        return result
