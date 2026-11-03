"""CertaintyGate — deterministic proofs that two matches are the same event.

The rule stage of the mapping pipeline. Produces ``verified`` only when league,
kickoff, category, team identity, orientation, and link evidence all hold.
Ambiguous pairs get ``suggested`` with explicit reasons; ``rejected`` when a
hard gate contradicts the claim.

"Link evidence holds" means one of two proven things per book, never a
presumption: a browser check opened that book's per-event URL and found the
event, or the bookmaker's own declaration in ``config/bookmaker_deeplinks.json``
says it has no per-event route, so there is no URL to open. A book that has
declared neither is not accepted — see :meth:`CertaintyGate._link_evidence`.
"""

import functools
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from rapidfuzz import fuzz

from config.settings import VERIFIED_KICKOFF_WINDOW_MINUTES
from engine import name_identity
from engine.league_resolver import LeagueResolver
from engine.mapping_evidence import (
    MappingLedger,
    league_equivalence_key,
    team_alias_key,
)
from engine.normalizer import CLUB_DESIGNATORS, TeamNormalizer
from models.schemas import Match, MatchEventStatus, MatchEvidence, MatchGroup
from scrapers.common import (
    declares_no_event_id,
    declares_route_pattern_verified,
    supports_event_id,
)

# Characters a bookmaker uses as separators in a team name ("Bodo/Glimt",
# "St. Mirren", "Paris-SG"); they never distinguish two clubs.
_TEAM_PUNCTUATION = re.compile(r"[./\\\-\&'’`,()]+")
# Letters NFKD does not decompose.
_LETTER_FOLDS = str.maketrans({"đ": "dj", "ø": "o", "æ": "ae", "ß": "ss", "ł": "l"})

# Evidence note (not a reason) on a league accepted by `_league_settled_by_teams`.
LEAGUE_UNMAPPED_TEAMS_EXACT = "league_unmapped_teams_exact"

# Club-type tokens that may be dropped without changing which club a name
# denotes. Words such as "atletico" and "deportivo" are excluded: they are part
# of a club's identity, not a designator.
_DESIGNATOR_TOKENS = frozenset(CLUB_DESIGNATORS - {"atletico", "deportivo"})

# Whole-token abbreviations that are not prefixes of the word they stand for.
_TOKEN_SYNONYMS = {"utd": "united", "st": "saint"}

HARD_REJECT_REASONS = frozenset(
    {"league_mismatch", "category_mismatch", "betradar_mismatch", "orientation_unresolved"}
)


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
        reviewed_aliases: set[str] | None = None,
        evidence: MappingLedger | None = None,
    ) -> None:
        self.normalizer = TeamNormalizer()
        self.kickoff_window_minutes = kickoff_window_minutes
        self.alias_allowlist = alias_allowlist or set()
        # Pairs a person reviewed from fixture evidence (config/team_alias_reviewed.json).
        # Accepted without the allowlist's similarity floor: "Man.Utd" and
        # "Manchester United" score 60 and are still one club. Everything else
        # an alias needs - league, kickoff, category, link - still applies.
        # Deprecated by A1-6: the ledger is the new trust source.
        self.reviewed_aliases = reviewed_aliases or set()
        self.league_equivalences = league_equivalences or set()
        # Machine evidence. A claim authorizes only while it is accepted and
        # inside its TTL; the ledger is checked before the legacy files.
        self.evidence = evidence
        self.league_resolver = LeagueResolver(evidence) if evidence is not None else None
        self._canonical_leagues = set(self.normalizer.league_reverse_map.values())

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

    def _is_mapped_league(self, league: str) -> bool:
        return league in self._canonical_leagues

    def _league_settled_by_teams(self, a: Match, b: Match) -> bool:
        """Accept differently-named leagues when the fixture itself is unambiguous.

        Bookmakers name competitions inconsistently ("Liga Two", "ENGLAND 2",
        "OBOS Liga"), and a name no mapping covers normalizes to itself, so it
        could never equal anything. When at least one side's league is such an
        unmapped name, the pair is accepted on league only if everything else
        that identifies a fixture already agrees: both teams match exactly
        (raw spellings, no alias), the kickoff is inside the verified window and
        the categories are equal. Two *mapped* leagues that differ are a real
        contradiction and still reject.
        """
        a_league, b_league = a.league_normalized or "", b.league_normalized or ""
        if not a_league or not b_league:
            return False
        if self._is_mapped_league(a_league) and self._is_mapped_league(b_league):
            return False
        if set(a.category_tags or []) != set(b.category_tags or []):
            return False
        delta = self._kickoff_delta_minutes(a, b)
        if delta is None or delta > self.kickoff_window_minutes:
            return False
        return self._exact_raw_teams(a, b)

    def _exact_raw_teams(self, a: Match, b: Match) -> bool:
        """Both teams agree on raw spelling and canonical form, in either orientation."""
        ah, aa = a.home_team_normalized, a.away_team_normalized
        bh, ba = b.home_team_normalized, b.away_team_normalized
        if not (ah and aa and bh and ba):
            return False
        key = self._raw_team_key
        direct = (
            key(a.home_team) == key(b.home_team)
            and key(a.away_team) == key(b.away_team)
            and ah == bh
            and aa == ba
        )
        swapped = (
            key(a.home_team) == key(b.away_team)
            and key(a.away_team) == key(b.home_team)
            and ah == ba
            and aa == bh
        )
        return direct or swapped

    def _league_ok(self, a_league: str, b_league: str) -> bool:
        """Return whether two normalized league IDs are the same or equivalent."""
        if not a_league or not b_league:
            return False
        if a_league == b_league:
            return True
        if self.evidence is not None and self.evidence.is_accepted(
            "league_equivalence", league_equivalence_key(a_league, b_league)
        ):
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
    @functools.lru_cache(maxsize=65536)
    def _raw_team_key(name: str) -> str:
        """Make only lossless superficial raw-name comparisons.

        This deliberately does not call the normalizer's fuzzy fallback. Team
        identity decisions that see different raw forms must go through the
        explicit alias allowlist.

        The matcher asks for the same names thousands of times per scan (every
        team similarity check re-normalizes both sides), so the pure result is
        memoized. The cache is per process and never cleared by a caller: the
        function's output depends only on ``name``.
        """
        decomposed = unicodedata.normalize("NFKD", name.casefold().translate(_LETTER_FOLDS))
        plain = "".join(char for char in decomposed if not unicodedata.combining(char))
        return " ".join(_TEAM_PUNCTUATION.sub(" ", plain).split())

    @classmethod
    def _club_designator_key(cls, name: str) -> str:
        """Drop leading/trailing club-type tokens, keeping the club name."""
        words = cls._raw_team_key(name).split()
        while len(words) > 1 and words[0] in _DESIGNATOR_TOKENS:
            words = words[1:]
        while len(words) > 1 and words[-1] in _DESIGNATOR_TOKENS:
            words = words[:-1]
        return " ".join(words)

    @staticmethod
    def _token_abbreviation_match(left_raw: str, right_raw: str) -> bool:
        """Same tokens, each differing token an initial or ≥3-char prefix.

        ``Man Utd`` / ``Manchester Utd`` and ``Dynamo D`` / ``Dynamo Dresden``
        pass. ``Manchester Utd`` / ``Manchester City`` do not: the second
        token is neither an initial nor a prefix. A different token count is
        never accepted here (``Central Coast`` / ``Central Coast Mariners``).
        """
        left = name_identity.tokens(left_raw)
        right = name_identity.tokens(right_raw)
        if not left or len(left) != len(right):
            return False
        for a, b in zip(left, right, strict=True):
            a = _TOKEN_SYNONYMS.get(a, a)
            b = _TOKEN_SYNONYMS.get(b, b)
            if a == b:
                continue
            shorter = min(len(a), len(b))
            if not (a.startswith(b) or b.startswith(a)):
                return False
            if shorter != 1 and shorter < 3:
                return False
        return True

    @staticmethod
    def _surface_team_key(name: str) -> str:
        """Normalize lossless spelling differences for an allowlisted score."""
        key = " ".join(name.strip().casefold().split()).rstrip(".")
        decomposed = unicodedata.normalize("NFKD", key)
        return "".join(char for char in decomposed if not unicodedata.combining(char))

    def _team_pair_details(
        self,
        left_raw: str,
        left_normalized: str,
        right_raw: str,
        right_normalized: str,
    ) -> tuple[bool, str]:
        """Return ``(ok, alias_source)`` for one raw/canonical team pair.

        ``alias_source`` is ``""`` for an exact match, ``"ledger"`` for a
        machine-proven claim, ``"reviewed"`` for the deprecated human file, and
        ``"allowlist"`` for a legacy allowlisted fuzzy pair.
        """
        if not (left_raw and left_normalized and right_raw and right_normalized):
            return False, ""

        left_key = self._raw_team_key(left_raw)
        right_key = self._raw_team_key(right_raw)
        if left_key and left_key == right_key:
            return left_normalized == right_normalized, ""

        if self.evidence is not None and self.evidence.is_accepted(
            "team_alias", team_alias_key(left_raw, right_raw)
        ):
            return True, "ledger"

        # A canonical collision alone is never enough. If the raw forms differ,
        # the pair is an alias candidate and must be explicitly proven.
        if self._is_reviewed(left_raw, right_raw):
            return True, "reviewed"
        allowlisted = self._is_allowlisted(left_raw, right_raw) or self._is_allowlisted(
            left_normalized, right_normalized
        )
        if allowlisted:
            left_surface = self._surface_team_key(left_raw)
            right_surface = self._surface_team_key(right_raw)
            fuzzy_score = max(
                fuzz.token_set_ratio(left_surface, right_surface),
                fuzz.partial_ratio(left_surface, right_surface),
            )
            if fuzzy_score >= 90:
                return True, "allowlist"

        # A club-type designator is not an identity difference: "FC Liefering"
        # and "Liefering" name one club, and the normalizer already maps both to
        # the same canonical id. Requiring an alias first deadlocks the pair —
        # it can never group, so the learner can never see it. Only leading or
        # trailing designators are dropped, and the remaining spelling and
        # canonical id must be identical. This runs after the reviewed and
        # allowlisted forms so an explicit alias keeps its own evidence.
        if (
            left_normalized == right_normalized
            and self._club_designator_key(left_raw) == self._club_designator_key(right_raw)
        ):
            return True, "designator"

        # A token that is only an initial or a long prefix is an abbreviation,
        # not a different club: "Man Utd" / "Manchester Utd", "Dynamo D" /
        # "Dynamo Dresden". The same-token-count requirement is what keeps
        # "Manchester Utd" / "Manchester City" and "Central Coast" /
        # "Central Coast Mariners" out.
        if self._token_abbreviation_match(left_raw, right_raw):
            return True, "abbreviation"
        return False, ""

    def _teams_match_details(self, a: Match, b: Match) -> tuple[bool, bool, str]:
        """Return ``(ok, is_swapped, alias_source)`` for raw/canonical teams."""
        ah, aa = a.home_team_normalized, a.away_team_normalized
        bh, ba = b.home_team_normalized, b.away_team_normalized
        if not (ah and aa and bh and ba):
            return False, False, ""

        if (
            self._raw_team_key(a.home_team) == self._raw_team_key(b.home_team)
            and self._raw_team_key(a.away_team) == self._raw_team_key(b.away_team)
            and ah == bh
            and aa == ba
        ):
            return True, False, ""
        if (
            self._raw_team_key(a.home_team) == self._raw_team_key(b.away_team)
            and self._raw_team_key(a.away_team) == self._raw_team_key(b.home_team)
            and ah == ba
            and aa == bh
        ):
            return True, True, ""

        direct_home_ok, direct_home_source = self._team_pair_details(
            a.home_team, ah, b.home_team, bh
        )
        direct_away_ok, direct_away_source = self._team_pair_details(
            a.away_team, aa, b.away_team, ba
        )
        if direct_home_ok and direct_away_ok:
            return True, False, direct_home_source or direct_away_source

        swapped_home_ok, swapped_home_source = self._team_pair_details(
            a.home_team, ah, b.away_team, ba
        )
        swapped_away_ok, swapped_away_source = self._team_pair_details(
            a.away_team, aa, b.home_team, bh
        )
        if swapped_home_ok and swapped_away_ok:
            return True, True, swapped_home_source or swapped_away_source

        return False, False, ""

    def _teams_ok(self, a: Match, b: Match) -> tuple[bool, bool, str]:
        """Return ``(ok, is_swapped, reason)`` for normalized team identities.

        A fuzzy alias is accepted only as part of a complete home/away
        orientation. In particular, a single cross-side fuzzy hit is not enough
        to claim a swap.
        """
        ok, is_swapped, _ = self._teams_match_details(a, b)
        return ok, is_swapped, "" if ok else "team_unresolved"

    def _teams_alias_source(self, a: Match, b: Match) -> str:
        """Return the source that carried a non-exact team match, if any."""
        _, _, alias_source = self._teams_match_details(a, b)
        return alias_source

    def _is_allowlisted(self, left: str, right: str) -> bool:
        """Return whether the unordered raw/canonical pair is explicitly reviewed."""
        if not self.alias_allowlist:
            return False
        pair = frozenset((self._raw_team_key(left), self._raw_team_key(right)))
        return pair in self._allowlist_index()

    def _is_reviewed(self, left: str, right: str) -> bool:
        """Return whether the unordered raw pair is in the reviewed-alias file."""
        if not self.reviewed_aliases:
            return False
        pair = frozenset((self._raw_team_key(left), self._raw_team_key(right)))
        return pair in self._reviewed_index()

    def _reviewed_index(self) -> frozenset[frozenset[str]]:
        """The reviewed aliases as a set of normalized pairs, rebuilt when they change."""
        snapshot = (id(self.reviewed_aliases), len(self.reviewed_aliases))
        cached = getattr(self, "_reviewed_cache", None)
        if cached is None or cached[0] != snapshot:
            index = frozenset(
                frozenset(self._raw_team_key(part) for part in entry.split("|"))
                for entry in self.reviewed_aliases
                if entry.count("|") == 1
            )
            cached = (snapshot, index)
            self._reviewed_cache = cached
        return cached[1]

    def _allowlist_index(self) -> frozenset[frozenset[str]]:
        """The allowlist as a set of normalized pairs, rebuilt when it changes.

        Grouping asks this for every candidate pair; re-parsing a thousand-entry
        allowlist on each call made a scan's grouping several times slower.
        The change check is the set's identity and size, not a copy of it:
        copying the allowlist (thousands of entries once the matcher adds the
        canonical forms) on every call cost more than the lookup it guards.
        Callers replace the set (``gate.alias_allowlist = set(...)``) or add to
        it; either one changes the key.
        """
        snapshot = (id(self.alias_allowlist), len(self.alias_allowlist))
        cached = getattr(self, "_allowlist_cache", None)
        if cached is None or cached[0] != snapshot:
            index = frozenset(frozenset(entry) for entry in self.alias_allowlist_entries)
            cached = (snapshot, index)
            self._allowlist_cache = cached
        return cached[1]

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
    def _link_evidence(m: Match) -> tuple[MatchEvidence, bool]:
        """Return this match's link evidence record and whether it settles the link.

        One method, so the record and the decision cannot drift apart: every
        branch states its own record *and* whether that record is a settled fact
        (the second element is True) or an open one (False, and therefore a
        reason).

        Four cases, in this order:

        1. ``deep_link_verified`` — a browser check proved the URL opens the
           intended event. Settled; nothing here can pre-empt it.
        2. The book declares ``supports_event_id: false`` in
           ``config/bookmaker_deeplinks.json`` — it has no per-event route, so
           there is no link to prove. The declaration IS the proof, and the
           absence is recorded as evidence rather than raised as a reason. This
           is the spec's accepted case, and it is why a feed id or a site URL on
           such a book is not read as an unproven link: neither is a route, and
           the book has said so.
        3. The book declares a route it has not proven — whether it captured a
           URL or not. ``link_unverified``, and it blocks. An empty URL for such a
           book is a capture gap, not an absence: reporting it as
           ``no_event_link`` would claim the book has no per-event page when its
           own declaration says it has one, and it would tell the next engineer
           that emptying the URL is a way to unblock a group. It is not.
        4. The book has said nothing at all. A captured URL or id is
           ``link_unverified``; with nothing captured it is ``no_event_link``. Both
           block: an absent declaration is silence, and silence is not proof of
           absence.
        """
        if m.deep_link_verified:
            return (
                MatchEvidence(
                    rule="link_evidence",
                    source="rule",
                    confidence=1.0,
                    reason="verified_link",
                ),
                True,
            )
        if declares_route_pattern_verified(m.bookmaker) and m.event_id:
            # A path-based route whose pattern was browser-proven for sampled
            # events. The feed supplies the same id for every listing, so the
            # route is deterministic; a book with no event id still fails.
            return (
                MatchEvidence(
                    rule="link_evidence",
                    source="rule",
                    confidence=1.0,
                    reason="route_pattern_verified",
                ),
                True,
            )
        if declares_no_event_id(m.bookmaker):
            return (
                MatchEvidence(
                    rule="link_evidence",
                    source="rule",
                    confidence=1.0,
                    reason="no_event_link",
                ),
                True,
            )
        if supports_event_id(m.bookmaker) or m.event_id or m.url:
            return (
                MatchEvidence(
                    rule="link_evidence",
                    source="rule",
                    confidence=0.0,
                    reason="link_unverified",
                ),
                False,
            )
        return (
            MatchEvidence(
                rule="link_evidence",
                source="rule",
                confidence=0.0,
                reason="no_event_link",
            ),
            False,
        )

    def evaluate_pair(self, a: Match, b: Match) -> GateResult:
        """Evaluate a pair and return a deterministic status plus evidence."""
        reasons: list[str] = []
        evidence: list[MatchEvidence] = []

        # Betradar identity. A provider match id is shared across books, so two
        # listings that carry the same non-empty id are the same real match
        # whatever their team or league names say. Two different ids are two
        # different matches and reject outright.
        a_betradar, b_betradar = a.betradar_id or "", b.betradar_id or ""
        same_id = bool(a_betradar and b_betradar and a_betradar == b_betradar)
        different_id = bool(a_betradar and b_betradar and a_betradar != b_betradar)

        # League identity.
        a_league, b_league = a.league_normalized or "", b.league_normalized or ""
        league_ok = self._league_ok(a_league, b_league)
        league_reason = ""
        if same_id:
            league_ok = True
            league_reason = "betradar_id"
        elif not league_ok and self._league_settled_by_teams(a, b):
            league_ok = True
            league_reason = LEAGUE_UNMAPPED_TEAMS_EXACT
        elif (
            not league_ok
            and self.league_resolver is not None
            and self.league_resolver.same_competition(
                a_league,
                b_league,
                a.home_team_source or a.home_team,
                a.away_team_source or a.away_team,
            )
        ):
            league_ok = True
            league_reason = "league_fingerprint"
        if not league_ok:
            reasons.append("league_mismatch")
        evidence.append(
            MatchEvidence(
                rule="league_identity",
                source="rule",
                confidence=1.0 if league_ok else 0.0,
                reason=league_reason,
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
        alias_source = self._teams_alias_source(a, b) if teams_ok else ""
        if same_id:
            # The provider id proves the clubs; the names only decide which way
            # round the listing is. Direct and swapped are compared as whole
            # fixtures, so one coincidental name hit cannot claim a swap.
            direct = fuzz.token_set_ratio(
                a.home_team_normalized, b.home_team_normalized
            ) + fuzz.token_set_ratio(a.away_team_normalized, b.away_team_normalized)
            swapped = fuzz.token_set_ratio(
                a.home_team_normalized, b.away_team_normalized
            ) + fuzz.token_set_ratio(a.away_team_normalized, b.home_team_normalized)
            teams_ok = True
            team_reason = "betradar_id"
            is_swapped = swapped > direct
            alias_source = ""
        if alias_source and not (league_ok and kickoff_ok and category_ok):
            teams_ok = False
            team_reason = "team_unresolved"

        exact_teams = (
            a.home_team_normalized == b.home_team_normalized
            and a.away_team_normalized == b.away_team_normalized
        )
        if not teams_ok:
            team_source: Literal["rule", "allowlist", "ledger"] = "rule"
            team_confidence = 0.0
            team_evidence_reason = team_reason or "team_unresolved"
        elif same_id:
            team_source = "rule"
            team_confidence = 1.0
            team_evidence_reason = "betradar_id"
        elif alias_source == "ledger":
            team_source = "ledger"
            team_confidence = 1.0
            team_evidence_reason = "swapped" if is_swapped else "ledger_alias"
        elif alias_source == "designator":
            team_source = "rule"
            team_confidence = 1.0
            team_evidence_reason = "swapped" if is_swapped else "club_designator"
        elif alias_source == "abbreviation":
            team_source = "rule"
            team_confidence = 1.0
            team_evidence_reason = "swapped" if is_swapped else "token_abbreviation"
        elif alias_source:
            team_source = "allowlist"
            team_confidence = 1.0
            team_evidence_reason = "swapped" if is_swapped else "allowlisted_alias"
        elif exact_teams:
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
                evidence_keys=(
                    [
                        team_alias_key(a.home_team, b.away_team),
                        team_alias_key(a.away_team, b.home_team),
                    ]
                    if team_source == "ledger" and is_swapped
                    else (
                        [
                            team_alias_key(a.home_team, b.home_team),
                            team_alias_key(a.away_team, b.away_team),
                        ]
                        if team_source == "ledger"
                        else []
                    )
                ),
            )
        )

        # Link evidence. A pair is verified only when both sides are settled.
        link_reasons: set[str] = set()
        for m in (a, b):
            link_evidence, settled = self._link_evidence(m)
            # The record is appended either way: a verified group's evidence
            # trail is where a reviewer reads that a link was deliberately
            # absent, so dropping it for the accepted case would erase the only
            # statement of it.
            evidence.append(link_evidence)
            if settled:
                continue
            if link_evidence.reason == "link_unverified":
                link_reasons.add("link_unverified")
            else:
                link_reasons.add("no_event_link")
        reasons.extend(sorted(link_reasons))

        # A pair of different provider ids is a contradiction, not a gap: no
        # name, league or kickoff evidence can make two ids the same event.
        if different_id:
            reasons.append("betradar_mismatch")

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

    def _group_team_reference(
        self,
        group_value: str,
        anchor_home_raw: str,
        anchor_home_normalized: str,
        anchor_away_raw: str,
        anchor_away_normalized: str,
    ) -> tuple[str, str]:
        """Resolve a group field to a raw/canonical reference without fuzzy trust."""
        if group_value == anchor_home_normalized:
            return anchor_home_raw, group_value
        if group_value == anchor_away_normalized:
            return anchor_away_raw, group_value
        return group_value, self.normalizer.normalize_team(group_value)

    def _group_team_orientation(
        self,
        match: Match,
        group: MatchGroup,
        anchor: Match,
    ) -> tuple[bool, bool] | None:
        """Check a candidate against the group's canonical team fields."""
        if not group.canonical_home or not group.canonical_away:
            return None

        group_home_raw, group_home_normalized = self._group_team_reference(
            group.canonical_home,
            anchor.home_team,
            anchor.home_team_normalized,
            anchor.away_team,
            anchor.away_team_normalized,
        )
        group_away_raw, group_away_normalized = self._group_team_reference(
            group.canonical_away,
            anchor.home_team,
            anchor.home_team_normalized,
            anchor.away_team,
            anchor.away_team_normalized,
        )

        direct_home_ok, _ = self._team_pair_details(
            match.home_team,
            match.home_team_normalized,
            group_home_raw,
            group_home_normalized,
        )
        direct_away_ok, _ = self._team_pair_details(
            match.away_team,
            match.away_team_normalized,
            group_away_raw,
            group_away_normalized,
        )
        if direct_home_ok and direct_away_ok:
            return True, False

        swapped_home_ok, _ = self._team_pair_details(
            match.home_team,
            match.home_team_normalized,
            group_away_raw,
            group_away_normalized,
        )
        swapped_away_ok, _ = self._team_pair_details(
            match.away_team,
            match.away_team_normalized,
            group_home_raw,
            group_home_normalized,
        )
        if swapped_home_ok and swapped_away_ok:
            return True, True

        # The canonical reference is resolved through the anchor, so an anchor
        # spelling the candidate cannot be proven against (Betole's "A.
        # Salzburg" beside "Austria Salzburg") must not hide the same proof
        # held by another member. Every accepted member is already in the
        # group's orientation, so any member may prove it — but only while a
        # member actually supports the canonical fields. A canonical value no
        # member holds stays authoritative and keeps the candidate unresolved.
        canonical_supported = any(
            member.home_team_normalized == group.canonical_home
            and member.away_team_normalized == group.canonical_away
            for member in group.matches
        )
        if not canonical_supported:
            return False, False
        orientations: set[bool] = set()
        for member in group.matches:
            direct = self._team_pair_details(
                match.home_team,
                match.home_team_normalized,
                member.home_team,
                member.home_team_normalized,
            )[0] and self._team_pair_details(
                match.away_team,
                match.away_team_normalized,
                member.away_team,
                member.away_team_normalized,
            )[0]
            if direct:
                orientations.add(False)
                continue
            swapped = self._team_pair_details(
                match.home_team,
                match.home_team_normalized,
                member.away_team,
                member.away_team_normalized,
            )[0] and self._team_pair_details(
                match.away_team,
                match.away_team_normalized,
                member.home_team,
                member.home_team_normalized,
            )[0]
            if swapped:
                orientations.add(True)
        if len(orientations) == 1:
            return True, orientations.pop()
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

        # A group may hold a member with no provider id, so comparing only to
        # the anchor can miss a conflict between two other members. Check every
        # non-empty id in the group before anything else.
        group_ids = {member.betradar_id for member in group.matches if member.betradar_id}
        if len(group_ids) > 1 or (match.betradar_id and group_ids and match.betradar_id not in group_ids):
            return GateResult(
                status="rejected",
                reasons=["betradar_mismatch"],
                evidence=[
                    MatchEvidence(
                        rule="betradar_identity",
                        source="rule",
                        confidence=0.0,
                        reason="betradar_mismatch",
                    )
                ],
            )

        anchor = next(
            (
                m
                for m in group.matches
                if match.betradar_id and m.betradar_id == match.betradar_id
            ),
            group.matches[0],
        )
        result = self.evaluate_pair(match, anchor)

        team_proved_by_id = any(
            item.rule == "team_identity" and item.reason == "betradar_id"
            for item in result.evidence
        )

        group_teams = (
            None
            if team_proved_by_id
            else self._group_team_orientation(match, group, anchor)
        )
        if group_teams is not None:
            group_teams_ok, group_is_swapped = group_teams
            # The group orientation is the single reference frame consumed by
            # the matcher when it decides whether to flip a candidate.
            result.is_swapped = group_is_swapped if group_teams_ok else False
            if not group_teams_ok and "team_unresolved" not in result.reasons:
                result.reasons.append("team_unresolved")

        group_kickoff_reason = self._group_kickoff_reason(match, group)
        if group_kickoff_reason and group_kickoff_reason not in result.reasons:
            result.reasons.append(group_kickoff_reason)

        # The anchor is one book's spelling, not the group's identity. A group
        # can hold "germany, bundesliga" from one book and "bundesliga" from
        # seven others; the canonical league is the group's answer. When the
        # candidate agrees with that canonical league, an anchor-only mismatch
        # must not survive as a hard reject: doing so dropped valid listings
        # from groups that already carried the same competition.
        match_league = match.league_normalized or ""
        group_league = group.league or ""
        # Compare with every member's league, not only the canonical one: a
        # group can be anchored by a book whose league spelling never became
        # canonical (Betole's "germany, bundesliga" beside seven "bundesliga"
        # listings). Matching any member is the same evidence the group itself
        # rests on.
        group_leagues = {
            member.league_normalized
            for member in group.matches
            if member.league_normalized
        }
        # The canonical field is authoritative only while a member actually
        # supports it. A test or a corrupted group can set a canonical league
        # no member holds; that must not become a licence to accept every
        # member's league spelling.
        canonical_league_supported = bool(
            group_league
            and (
                group_league in group_leagues
                or any(self._league_ok(group_league, league) for league in group_leagues)
            )
        )
        league_references = (
            group_leagues if canonical_league_supported else ({group_league} if group_league else set())
        )
        group_league_settles = bool(
            match_league
            and any(
                match_league == league or self._league_ok(match_league, league)
                for league in league_references
            )
        )
        if group_league_settles:
            for item in result.evidence:
                if item.rule == "league_identity" and item.confidence < 1.0:
                    item.confidence = 1.0
                    item.reason = "group_canonical_league"
                    item.league_pair = [match_league, group_league]
                    break
            if "league_mismatch" in result.reasons:
                result.reasons.remove("league_mismatch")

        # A team spelling can fail against the anchor for the same reason: the
        # anchor says "RB Leipzig", the candidate says "Leipzig", and the pair
        # check refuses because the anchor's league already failed. The group's
        # canonical teams are the stronger reference, so an orientation proved
        # against them clears that derived failure.
        if group_teams is not None and group_teams[0] and "team_unresolved" in result.reasons:
            result.reasons.remove("team_unresolved")
            for item in result.evidence:
                if item.rule == "team_identity" and item.confidence < 1.0:
                    item.confidence = 1.0
                    item.reason = "group_canonical_teams"
                    break

        league_settled = group_league_settles or team_proved_by_id or any(
            item.rule == "league_identity" and item.reason == LEAGUE_UNMAPPED_TEAMS_EXACT
            for item in result.evidence
        )
        if group.league and not league_settled:
            if (
                match_league
                and match_league != group.league
                and not self._league_ok(match_league, group.league)
                and (self._is_mapped_league(match_league) and self._is_mapped_league(group.league))
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
