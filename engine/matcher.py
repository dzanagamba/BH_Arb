"""
Match Matcher — Multi-Dimensional Match Grouping

Groups matches from different bookmakers into MatchGroups that represent
the same real-world event using multi-dimensional composite fingerprinting:

  FINGERPRINT = League × Date × Teams × Time

Gates & Matching Rules:
  1. League Gate    — Same normalized league ID or an explicit equivalence
  2. Category Gate  — Special categories (U21, Women, Reserves, Esports) must agree
  3. Time/Date Gate — Candidate scoring uses 120 minutes; verified claims use 15 minutes
  4. Team Match     — Candidate scoring evaluates both home/away orientations
  5. Certainty Gate  — Final authority for verified status, links, and orientation

Weighted composite confidence score:
  team_similarity_avg  × 0.80
  kickoff_proximity    × 0.20
  ≥ 0.80 required to group

Automatic Swap Handling:
  If a bookmaker flips home/away order, the match is auto-swapped and market odds
  labels (1↔2, 1X↔X2) are normalized to the group's canonical orientation.

A match group is only returned when the certainty gate verifies it and it contains
matches from 2+ distinct bookmakers.
"""

import json
import logging
import os
import re
from datetime import UTC, timedelta

from config.settings import (
    BOOKMAKERS,
    FUZZY_MATCH_THRESHOLD,
    KICKOFF_WINDOW_MINUTES,
    TEAM_MATCH_MIN_PERCENT,
    price_source,
)
from engine import name_identity, sports
from engine.ah_labels import flip_ah_label
from engine.certainty import CertaintyGate, GateResult
from engine.league_names import GENERIC_LEAGUES
from engine.mapping_evidence import MappingLedger, league_equivalence_key, team_alias_key
from engine.normalizer import TeamNormalizer, canonical_team_name, canonicalize_fixture
from models.schemas import MarketType, Match, MatchEvidence, MatchGroup, OddsValue

logger = logging.getLogger(__name__)

_LEAGUE_EQUIV_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "league_equivalences.json"
)
_TEAM_ALIAS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "team_alias_allowlist.json"
)
MAPPING_EVIDENCE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "generated", "mapping_evidence.json"
)

# The category markers `canonicalize_fixture` appends to a club's name.
_SIDE_SUFFIX = re.compile(r"(?: (?:U\d{2}|Youth))?(?: II)?(?: \(W\))?$")

# Derived thresholds (from config.settings)
TEAM_MATCH_RATIO = TEAM_MATCH_MIN_PERCENT / 100.0      # per-team similarity gate
GROUP_MIN_CONFIDENCE = FUZZY_MATCH_THRESHOLD / 100.0   # overall composite confidence gate

# Registry position per book: decides which book anchors (and orients) a group
# when listings otherwise tie. Unregistered books follow, by name.
_BOOKMAKER_RANK = {bookmaker: rank for rank, bookmaker in enumerate(BOOKMAKERS)}


class MatchMatcher:
    """
    Groups matches from different bookmakers into real-world events.

    Key design principles:
    - NEVER match on team names alone
    - League gate is a HARD requirement (prevents Borac BL vs Borac Čačak confusion)
    - Date gate is a HARD requirement (prevents future fixture confusion)
    - Team name matching uses normalized forms (after full pipeline)
    - Kickoff time adds a confidence bonus but hard-rejects > KICKOFF_WINDOW_MINUTES diff
    """

    def __init__(self, evidence_path: str | os.PathLike[str] | None = None) -> None:
        self.normalizer = TeamNormalizer()
        self._equivalences: set[tuple[str, str]] = set()
        try:
            with open(_LEAGUE_EQUIV_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("league equivalences must be a JSON object")
            for pair in data.get("pairs", []):
                if (
                    isinstance(pair, list | tuple)
                    and len(pair) == 2
                    and all(isinstance(value, str) for value in pair)
                ):
                    self._equivalences.add((pair[0], pair[1]))
        except (OSError, TypeError, ValueError):
            logger.warning(
                "league_equivalences.json not found or invalid — no cross-league merging"
            )

        # Only explicitly reviewed aliases may authorize fuzzy identity.
        self._alias_allowlist: set[str] = set()
        # Reviewed club spellings by raw key, to extend an alias to the club's
        # youth, reserve and women's sides (see `_extend_aliases_to_sides`).
        self._alias_partners: dict[str, set[str]] = {}
        try:
            with open(_TEAM_ALIAS_FILE, encoding="utf-8") as f:
                alias_data = json.load(f)
            if not isinstance(alias_data, dict) or not isinstance(
                alias_data.get("aliases"), list
            ):
                raise ValueError("team alias allowlist must contain an aliases list")
            for alias in alias_data["aliases"]:
                if not isinstance(alias, str) or alias.count("|") != 1:
                    continue
                left, right = (part.strip() for part in alias.split("|", 1))
                if left and right:
                    self._alias_allowlist.add(f"{left}|{right}")
                    # Listings are compared in their canonical spelling, so an
                    # entry reviewed on a book's raw spelling ("Rapid Vienna (Am)")
                    # is also held in that form ("Rapid Vienna II").
                    canonical = (canonical_team_name(left), canonical_team_name(right))
                    if all(canonical) and canonical != (left, right):
                        self._alias_allowlist.add(f"{canonical[0]}|{canonical[1]}")
                    if canonical == (left, right):
                        key = CertaintyGate._raw_team_key
                        self._alias_partners.setdefault(key(left), set()).add(right)
                        self._alias_partners.setdefault(key(right), set()).add(left)
        except (OSError, TypeError, ValueError):
            logger.warning(
                "team_alias_allowlist.json not found or invalid — no fuzzy aliases"
            )

        # The human-reviewed file is no longer a trust source. It is migrated
        # into the evidence ledger as quarantined ``legacy_review`` evidence by
        # scripts/migrate_reviewed.py; only machine corroboration can accept it.
        # The attributes stay for the side-extension helper and for tests that
        # inject a pair explicitly.
        self._reviewed_aliases: set[str] = set()
        self._reviewed_partners: dict[str, set[str]] = {}

        self._ledger = MappingLedger(
            str(evidence_path) if evidence_path is not None else MAPPING_EVIDENCE_FILE
        ).load()
        self.gate = CertaintyGate(
            alias_allowlist=self._alias_allowlist,
            league_equivalences=self._equivalences,
            evidence=self._ledger,
        )

    def normalize_matches(self, matches: list[Match]) -> list[Match]:
        """
        Enrich all matches with normalized fields.
        Must be called before group_matches.

        Each listing is first rewritten into the canonical team spelling (see
        `canonicalize_fixture`), always from the book's own spelling, so running
        this twice gives the same result. Category tags come from that same
        parse, so two books that mark a U21 side differently agree on it.
        """
        for m in matches:
            m.sport = sports.normalize_sport(m.sport) or m.sport or sports.FOOTBALL
            source_home = m.home_team_source or m.home_team
            source_away = m.away_team_source or m.away_team
            if m.sport != sports.FOOTBALL:
                home = sports.clean_team(m.sport, source_home)
                away = sports.clean_team(m.sport, source_away)
                m.home_team, m.away_team = home, away
                m.home_team_source = source_home if home != source_home else ""
                m.away_team_source = source_away if away != source_away else ""
                m.league_normalized = sports.clean_league(m.sport, m.league)
                m.country_normalized = self.normalizer.normalize_country(m.country)
                m.home_team_normalized = name_identity.normalize(home)
                m.away_team_normalized = name_identity.normalize(away)
                m.category_tags = self.normalizer.detect_special_category(
                    f"{source_home} {source_away} {m.league}"
                )
                continue
            fixture = canonicalize_fixture(source_home, source_away, m.league)
            m.home_team, m.away_team = fixture.home, fixture.away
            m.home_team_source = source_home if fixture.home != source_home else ""
            m.away_team_source = source_away if fixture.away != source_away else ""
            m.league_normalized = self.normalizer.normalize_league(m.league)
            m.country_normalized = self.normalizer.normalize_country(m.country)
            m.home_team_normalized = self.normalizer.normalize_team(
                m.home_team, league_scope=m.league_normalized
            )
            m.away_team_normalized = self.normalizer.normalize_team(
                m.away_team, league_scope=m.league_normalized
            )
            m.category_tags = list(fixture.tags)
        self._extend_aliases_to_sides(matches)
        return matches

    def _extend_aliases_to_sides(self, matches: list[Match]) -> None:
        """Hold a reviewed club alias for the same side of both clubs.

        Two spellings of one club are also two spellings of its youth, reserve
        and women's sides: "AEK|AEK Atena" holds for "AEK U19|AEK Atena U19".
        Only the sides this scan lists are added, since the gate copies the
        whole allowlist into the evidence of every alias it accepts. The gate
        still requires league, kickoff and category to agree.
        """
        if not self._alias_partners and not self._reviewed_partners:
            return
        key = CertaintyGate._raw_team_key
        for m in matches:
            for name in (m.home_team, m.away_team):
                hit = _SIDE_SUFFIX.search(name)
                if not hit or not hit.group(0) or hit.start() == 0:
                    continue
                base, suffix = name[: hit.start()], hit.group(0)
                for partner in self._alias_partners.get(key(base), ()):
                    self._alias_allowlist.add(f"{base}{suffix}|{partner}{suffix}")
                for partner in self._reviewed_partners.get(key(base), ()):
                    self._reviewed_aliases.add(f"{base}{suffix}|{partner}{suffix}")

    def group_matches(self, all_matches: list[Match]) -> list[MatchGroup]:
        """
        Group matches into MatchGroups using multi-dimensional matching.

        Process:
        1. Normalize all matches
        2. Group by normalized league (Layer 1 — HARD gate)
        3. Within each league, group by date (Layer 2 — HARD gate)
        4. Within each date bucket, match teams (Layer 3)
        5. Return groups with 2+ bookmakers only
        """
        if not all_matches:
            return []

        all_matches = self.normalize_matches(all_matches)

        # --- Cluster all normalized matches into MatchGroups ---
        # A total order makes the result a function of the input *set*: the
        # first match in a group is its anchor, so a partial key (specific
        # league first, then input order) let the same scan yield 6x
        # different group counts. Specific leagues still come first so they
        # establish canonical groups.
        # A league name no mapping covers can never equal another book's name
        # for the same competition, so bucketing it by that name would hide it
        # from its real group. Such a listing is offered every group, like a
        # generic league, and the gate decides (it accepts an unmapped league
        # only when both teams and the kickoff match exactly).
        is_open = self._open_league
        sorted_matches = sorted(
            all_matches, key=lambda m: (is_open(m), _processing_order_key(m))
        )

        groups: list[MatchGroup] = []
        # Creation index per group (by identity) — the deterministic tie-break
        # between candidates of equal confidence.
        group_index: dict[int, int] = {}
        # League index: (sport, normalized league) → groups in it. Generic
        # leagues keyed under "". The sport is part of the key, so a football
        # group can never even be offered to a basketball listing.
        groups_by_league: dict[tuple[str, str], list[MatchGroup]] = {}
        # Exact team key → groups that already hold that team. This is the
        # shared-opponent lookup: a listing whose league name differs can still
        # be offered to the group of the team it is playing, and the gate decides.
        groups_by_team: dict[tuple[str, str], list[MatchGroup]] = {}
        # Betradar id → the group that already holds it, scoped by sport.
        groups_by_betradar: dict[tuple[str, str], MatchGroup] = {}
        # Non-football candidate index: (sport, UTC date) → groups. A date
        # bucket keeps the open-league scan bounded without ever crossing sports.
        groups_by_sport_date: dict[tuple[str, str], list[MatchGroup]] = {}

        for match in sorted_matches:
            m_league = match.league_normalized or match.league or ""
            candidate_groups: list[MatchGroup]
            if match.sport != sports.FOOTBALL:
                candidate_groups = []
                for date_key in _sport_date_keys(match):
                    candidate_groups.extend(
                        groups_by_sport_date.get((match.sport, date_key), [])
                    )
            elif is_open(match):
                # Generic or unmapped league — eligible against every group
                candidate_groups = list(groups)
            else:
                # Specific leagues are candidate buckets only when they are
                # identical or explicitly declared equivalent.
                league_keys = [m_league, ""]
                for left, right in self._equivalences:
                    if left == m_league and right not in league_keys:
                        league_keys.append(right)
                    elif right == m_league and left not in league_keys:
                        league_keys.append(left)
                candidate_groups = []
                for league_key in league_keys:
                    candidate_groups.extend(
                        groups_by_league.get((match.sport, league_key), [])
                    )

            # Shared-opponent candidates, independent of the league bucket.
            for team_name in (match.home_team, match.away_team):
                for team_key in _team_index_keys(team_name):
                    for group in groups_by_team.get((match.sport, team_key), []):
                        if group not in candidate_groups:
                            candidate_groups.append(group)

            scored: list[tuple[float, int, MatchGroup]] = []
            for group in candidate_groups:
                # Skip if this bookmaker already contributed a match to this group
                group_bookmakers = {m.bookmaker for m in group.matches}
                if match.bookmaker in group_bookmakers:
                    continue

                confidence, _ = self._calculate_confidence(match, group)

                if confidence >= GROUP_MIN_CONFIDENCE:
                    scored.append((confidence, group_index[id(group)], group))

            # Best confidence first, ties by creation order. The scorer only
            # ranks; the gate decides. A refusal of the best candidate (e.g. its
            # anchor's link is unproven) moves on to the next one instead of
            # orphaning the match in a new group.
            scored.sort(key=lambda item: (-item[0], item[1]))

            # A shared Betradar id is proof of identity, so the group that
            # already holds this id is offered first even when its names put it
            # outside the league bucket. The gate still decides.
            if match.betradar_id:
                known_group = groups_by_betradar.get((match.sport, match.betradar_id))
                if known_group is not None and match.bookmaker not in {
                    m.bookmaker for m in known_group.matches
                }:
                    # A shared provider id is proof of the event. That group
                    # must be the first candidate even when another group's
                    # spelling happens to score higher; otherwise the id-carrying
                    # books split across two groups that both look valid.
                    scored = [
                        (1.0, group_index[id(known_group)], known_group),
                        *[
                            item
                            for item in scored
                            if item[2] is not known_group
                        ],
                    ]

            accepted = False
            for best_conf, _, best_group in scored:
                gate_result: GateResult = self.gate.evaluate(match, best_group)
                if gate_result.status == "verified":
                    # The gate owns orientation; the scorer only prunes candidates.
                    match_to_add = (
                        swap_match_teams_and_odds(match)
                        if gate_result.is_swapped
                        else match
                    )
                    best_group.matches.append(match_to_add)
                    best_group.evidence.extend(gate_result.evidence)
                    if match.betradar_id:
                        groups_by_betradar.setdefault(
                            (match.sport, match.betradar_id), best_group
                        )
                    for team_name in (match.home_team, match.away_team):
                        for team_key in _team_index_keys(team_name):
                            bucket = groups_by_team.setdefault(
                                (match.sport, team_key), []
                            )
                            if best_group not in bucket:
                                bucket.append(best_group)
                    if len({m.bookmaker for m in best_group.matches}) >= 2:
                        best_group.status = "verified"

                    # Upgrade group's canonical league/kickoff if generic or unmapped.
                    # Football only: non-football leagues have no mapping file, and
                    # treating every one as "unmapped" would rewrite the canonical
                    # league on every member.
                    if (
                        best_group.sport != sports.FOOTBALL
                        and not best_group.league
                        and match.league_normalized
                    ):
                        # The first non-football listing may carry no
                        # competition ("-" in SportPlus). Keep the group's
                        # display league from the first member that does.
                        best_group.league = match.league_normalized
                    if (
                        best_group.sport == sports.FOOTBALL
                        and (
                            best_group.league in GENERIC_LEAGUES
                            or not self.gate._is_mapped_league(best_group.league)
                        )
                        and not is_open(match)
                    ):
                        old_key = (best_group.sport, "")
                        best_group.league = match.league_normalized
                        # Re-index the upgraded group into its new league bucket
                        if (
                            old_key in groups_by_league
                            and best_group in groups_by_league[old_key]
                        ):
                            groups_by_league[old_key].remove(best_group)
                        groups_by_league.setdefault(
                            (best_group.sport, best_group.league), []
                        ).append(best_group)
                    if not best_group.kickoff and match.kickoff:
                        best_group.kickoff = match.kickoff

                    logger.debug(
                        f"✅ MATCHED [{match.bookmaker}] "
                        f"'{match.home_team}' vs '{match.away_team}' "
                        f"→ group ('{best_group.canonical_home}' vs '{best_group.canonical_away}') "
                        f"[conf={best_conf:.2f}, swapped={gate_result.is_swapped}]"
                    )
                    accepted = True
                    break
                logger.debug(
                    f"⛔ GATE REJECTED [{match.bookmaker}] "
                    f"'{match.home_team}' vs '{match.away_team}' "
                    f"→ group ('{best_group.canonical_home}' vs '{best_group.canonical_away}') "
                    f"reasons={gate_result.reasons}"
                )

            if not accepted:
                new_group = MatchGroup(
                    canonical_home=match.home_team_normalized or match.home_team,
                    canonical_away=match.away_team_normalized or match.away_team,
                    sport=match.sport,
                    # For a non-football listing a missing competition is
                    # unknown, not the literal bookmaker placeholder "-". Keep
                    # it empty so the first member that names the competition
                    # can fill it.
                    league=(
                        match.league_normalized
                        if match.sport != sports.FOOTBALL
                        else (match.league_normalized or match.league)
                    ),
                    kickoff=match.kickoff,
                    matches=[match],
                    status="suggested",
                    evidence=[
                        MatchEvidence(
                            rule="rule_stage",
                            source="rule",
                            reason="new_group",
                        )
                    ],
                )
                group_index[id(new_group)] = len(groups)
                groups.append(new_group)
                if match.betradar_id:
                    groups_by_betradar.setdefault(
                        (match.sport, match.betradar_id), new_group
                    )
                for team_name in (match.home_team, match.away_team):
                    for team_key in _team_index_keys(team_name):
                        bucket = groups_by_team.setdefault((match.sport, team_key), [])
                        if new_group not in bucket:
                            bucket.append(new_group)
                bucket_key = (
                    (match.sport, "")
                    if match.sport != sports.FOOTBALL or is_open(match)
                    else (match.sport, new_group.league)
                )
                groups_by_league.setdefault(bucket_key, []).append(new_group)
                if match.sport != sports.FOOTBALL:
                    for date_key in _sport_date_keys(match):
                        groups_by_sport_date.setdefault(
                            (match.sport, date_key), []
                        ).append(new_group)

        # Only return groups whose every accepted addition passed the gate and
        # that contain at least two distinct price sources. Two books on one
        # feed (MDShop + Admiralbet are both NSoft) quote the same prices, so a
        # group made only of them can never be priced and must not be counted
        # as a multi-book group.
        multi_bookie_groups = [
            g
            for g in groups
            if g.status == "verified"
            and len({price_source(m.bookmaker) for m in g.matches}) >= 2
        ]

        logger.info(
            f"Match grouping: {len(all_matches)} total matches "
            f"→ {len(groups)} groups "
            f"→ {len(multi_bookie_groups)} multi-bookmaker groups"
        )

        return multi_bookie_groups

    def _open_league(self, match: Match) -> bool:
        """Whether a listing's league is generic or names no known competition."""
        return self._open_name(match.league_normalized or match.league or "")

    def _open_name(self, league: str) -> bool:
        return league in GENERIC_LEAGUES or not self.gate._is_mapped_league(league)

    def _calculate_confidence(self, match: Match, group: MatchGroup) -> tuple[float, bool]:
        """
        Confidence score (0.0–1.0) that a match belongs to a group,
        and boolean flag indicating if home/away order is swapped.

        Returns: (confidence_score, is_swapped)
        """
        # Hard gate: a group belongs to exactly one sport.
        if match.sport != group.sport or any(
            member.sport != match.sport for member in group.matches
        ):
            return 0.0, False

        m_league = match.league_normalized or ""
        g_league = group.league or ""

        # Hard gate: special categories (U21, Women, Reserves, Esports) must agree.
        # Prevents "Sarajevo U21" from grouping with senior "Sarajevo", women's
        # teams with men's teams, or virtual/esports events with real matches.
        match_tags = set(match.category_tags or [])
        group_tags = set(group.matches[0].category_tags or []) if group.matches else set()
        if match_tags != group_tags:
            # MBet does not mark ITF women's events; the gate decides whether
            # the two player names at the same minute are the same match. Do
            # not prune that candidate before the gate can see it.
            tennis_women_gap = (
                match.sport == sports.TENNIS
                and match_tags in (set(), {"Women"})
                and group_tags in (set(), {"Women"})
            )
            if not tennis_women_gap:
                return 0.0, False

        # Hard gate: two KNOWN leagues must be identical or explicitly
        # equivalent; no blanket competition compatibility is allowed. An
        # unmapped name proves nothing either way, so it is left to the gate.
        leagues_known = not self._open_name(m_league) and not self._open_name(g_league)
        if (
            m_league and g_league
            and leagues_known
            and m_league != g_league
            and (m_league, g_league) not in self._equivalences
            and (g_league, m_league) not in self._equivalences
            and not self._ledger.is_accepted(
                "league_equivalence", league_equivalence_key(m_league, g_league)
            )
        ):
            return 0.0, False

        # Country soft gate (P1-3): if both have normalized country and mismatch, reject
        # Prevents Borac BL (BiH) vs Borac Cacak (Serbia) when league is generic/fuzzy
        m_country = (match.country_normalized or "").strip().lower()
        # Group country is from first match (representative)
        g_country = ""
        if group.matches:
            g_country = (group.matches[0].country_normalized or "").strip().lower()
        if m_country and g_country and m_country != g_country and not leagues_known:
            # Allow empty/generic country to pass, but hard mismatch rejects
            # Exception: friendlies/cups often have empty country — already handled above
            return 0.0, False

        # Kickoff time/date proximity gate
        time_score = 1.0  # Default: same time assumed if unknown

        if match.kickoff and group.kickoff:
            from datetime import UTC as _UTC

            m_dt = match.kickoff.astimezone(_UTC).replace(tzinfo=None) if match.kickoff.tzinfo else match.kickoff
            g_dt = group.kickoff.astimezone(_UTC).replace(tzinfo=None) if group.kickoff.tzinfo else group.kickoff
            diff_minutes = abs((m_dt - g_dt).total_seconds()) / 60.0

            # Hard gate: >KICKOFF_WINDOW_MINUTES apart (different kickoff time or date)
            if diff_minutes > KICKOFF_WINDOW_MINUTES:
                return 0.0, False

            if diff_minutes <= 5:
                time_score = 1.0
            elif diff_minutes <= 30:
                time_score = 0.8
            else:
                time_score = 0.5
        elif match.kickoff or group.kickoff:
            # One has time, other doesn't — mild penalty
            time_score = 0.65

        # A reviewed or allowlisted pair is one club however differently it is
        # spelled ("Chiba" / "JEF Utd" scores 0), so it scores as a full match
        # here and reaches the gate, which still decides on league, kickoff,
        # category, orientation and links. Holding allowlisted pairs to the
        # surface floor in the scorer pruned them before the gate could verify
        # them, which is why an approved alias could leave a candidate listed.
        anchor = group.matches[0] if group.matches else None

        def similarity(raw: str, normalized: str, group_normalized: str, group_raw: str) -> float:
            if group_raw and (
                self.gate._is_reviewed(raw, group_raw)
                or self.gate._is_allowlisted(raw, group_raw)
                or self.gate._is_allowlisted(normalized, group_normalized)
                or self._ledger.is_accepted("team_alias", team_alias_key(raw, group_raw))
            ):
                return 1.0
            # Identity rules, not raw token-set alone: an initialism can match
            # ("LAL" / "Los Angeles Lakers") and a differing academy/youth
            # marker is vetoed even at high string similarity.
            return name_identity.similarity(raw or normalized, group_raw or group_normalized)

        anchor_home = anchor.home_team if anchor else ""
        anchor_away = anchor.away_team if anchor else ""

        # Football keeps the anchor's spelling as the single reference. A
        # non-football group can contain a book that names the same player or
        # club differently ("Samsonova L" anchor, "Laura Samson" member); the
        # gate already proves a candidate against every member, so the scorer
        # must not prune it on the anchor alone. Try each member and keep the
        # best whole-fixture orientation.
        if match.sport != sports.FOOTBALL and group.matches:
            references = [
                (
                    member.home_team_normalized,
                    member.home_team,
                    member.away_team_normalized,
                    member.away_team,
                )
                for member in group.matches
            ]
        else:
            references = [
                (
                    group.canonical_home,
                    anchor_home,
                    group.canonical_away,
                    anchor_away,
                )
            ]

        dir_conf = swap_conf = 0.0
        for group_home, group_home_raw, group_away, group_away_raw in references:
            # Check direct orientation
            dir_home = similarity(
                match.home_team, match.home_team_normalized, group_home, group_home_raw
            )
            dir_away = similarity(
                match.away_team, match.away_team_normalized, group_away, group_away_raw
            )
            # Check swapped orientation
            swap_home = similarity(
                match.home_team, match.home_team_normalized, group_away, group_away_raw
            )
            swap_away = similarity(
                match.away_team, match.away_team_normalized, group_home, group_home_raw
            )
            if (
                dir_home >= TEAM_MATCH_RATIO
                and dir_away >= TEAM_MATCH_RATIO
            ):
                dir_conf = max(
                    dir_conf,
                    ((dir_home + dir_away) / 2.0) * 0.80 + time_score * 0.20,
                )
            if (
                swap_home >= TEAM_MATCH_RATIO
                and swap_away >= TEAM_MATCH_RATIO
            ):
                swap_conf = max(
                    swap_conf,
                    ((swap_home + swap_away) / 2.0) * 0.80 + time_score * 0.20,
                )

        if dir_conf >= swap_conf and dir_conf >= GROUP_MIN_CONFIDENCE:
            return dir_conf, False
        elif swap_conf > dir_conf and swap_conf >= GROUP_MIN_CONFIDENCE:
            return swap_conf, True

        return max(dir_conf, swap_conf), False

    def get_match_report(self, groups: list[MatchGroup]) -> list[dict]:
        """
        Generate a debugging report of all match groupings.
        Call this to verify correct pairing before trusting surebets.

        Each leg carries its `event_id` because the report outlives the process
        that built it: `_save_cache` persists it and `_load_cache` restores it
        after a restart, and a restored `verified` group is only kept while the
        link store still proves every one of its legs. Keying that check needs
        the id — a book publishes many events, so "this book has some proven
        match" is not the same claim as "this group's leg is proven". The field
        is additive and nothing reads it except that restore.
        """
        report = []
        for i, group in enumerate(groups):
            bookmakers: list[dict] = []
            entry: dict[str, object] = {
                "group_id": i + 1,
                "sport": group.sport,
                "canonical_match": f"{group.canonical_home} vs {group.canonical_away}",
                "league": group.league,
                "kickoff": group.kickoff.isoformat() if group.kickoff else "unknown",
                "status": group.status,
                "bookmakers": bookmakers,
                # The gate's trail, including the `no_event_link` note a
                # route-less book is accepted on — the one place a wrong
                # declaration would show.
                "evidence": [item.model_dump() for item in group.evidence],
            }
            for match in group.matches:
                bookmakers.append({
                    "bookmaker": match.bookmaker,
                    "event_id": match.event_id,
                    "home_team_raw": match.home_team,
                    "away_team_raw": match.away_team,
                    "home_normalized": match.home_team_normalized,
                    "away_normalized": match.away_team_normalized,
                    "league_raw": match.league,
                    "league_normalized": match.league_normalized,
                    "num_markets": len(match.markets),
                })
            report.append(entry)
        return report


def _team_index_keys(name: str) -> set[str]:
    """Keys under which a team is indexed for shared-opponent lookup."""
    raw = CertaintyGate._raw_team_key(name)
    normalized = name_identity.normalize(name)
    return {key for key in (raw, normalized) if key}


def _sport_date_keys(match: Match) -> tuple[str, ...]:
    """UTC date buckets a non-football listing may belong to.

    Book feeds disagree about a midnight kickoff by a few hours, so the two
    neighbouring dates are offered as well. The gate still proves the kickoff.
    """
    if match.kickoff is None:
        return ("",)
    kickoff = (
        match.kickoff.astimezone(UTC).replace(tzinfo=None)
        if match.kickoff.tzinfo
        else match.kickoff
    )
    day = kickoff.date()
    return tuple(
        (day + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)
    )


def _processing_order_key(match: Match) -> tuple[object, ...]:
    """Total order over normalized matches, independent of input position.

    The caller has already put specific leagues before generic/unmapped ones
    with ``is_open``; this key must not reorder by a different definition of
    "generic", or an unmapped league would anchor a group it is about to be
    treated as open against. Within that bucket: league, kickoff (naive UTC;
    missing last within a league), bookmaker (registry order, so the anchoring
    book is a configured choice), normalized teams and the remaining
    identifying fields so no two distinct listings tie.
    """
    kickoff = ""
    if match.kickoff:
        kickoff_utc = (
            match.kickoff.astimezone(UTC).replace(tzinfo=None)
            if match.kickoff.tzinfo
            else match.kickoff
        )
        kickoff = kickoff_utc.isoformat()
    return (
        match.sport,
        # Build provider-id groups first in the non-football pass. A book
        # without a provider id then joins the already-proven group instead of
        # anchoring a duplicate with its own league spelling. Football keeps
        # this element constant, so its long-standing order is untouched.
        (
            1
            if match.sport != sports.FOOTBALL and not match.betradar_id
            else 0
        ),
        match.league_normalized,
        kickoff == "",
        kickoff,
        _BOOKMAKER_RANK.get(match.bookmaker, len(_BOOKMAKER_RANK)),
        match.bookmaker,
        match.home_team_normalized,
        match.away_team_normalized,
        match.event_id,
        match.home_team,
        match.away_team,
        match.league,
        match.url,
    )


def swap_match_teams_and_odds(match: Match) -> Match:
    """
    Flip home/away teams and swap 1X2 / Double Chance odds labels
    so that outcome 1 corresponds to canonical home team and outcome 2 to canonical away team.
    """
    m = match.model_copy(deep=True)
    m.sport = match.sport
    m.home_team, m.away_team = m.away_team, m.home_team
    m.home_team_source, m.away_team_source = m.away_team_source, m.home_team_source
    m.home_team_normalized, m.away_team_normalized = m.away_team_normalized, m.home_team_normalized
    m.is_swapped = True

    FLIP_MAP = {
        "1": "2",
        "2": "1",
        "1X": "X2",
        "X2": "1X",
    }

    new_markets = []
    for market in m.markets:
        new_odds = []
        for ov in market.odds:
            if market.market_type in (MarketType.ASIAN_HANDICAP, MarketType.HANDICAP):
                new_label = flip_ah_label(ov.label)
            elif market.market_type in (
                MarketType.MATCH_RESULT,
                MarketType.FIRST_HALF_1X2,
                MarketType.MONEYLINE,
                MarketType.MONEYLINE_3WAY,
            ):
                new_label = FLIP_MAP.get(ov.label, ov.label)
            else:
                new_label = FLIP_MAP.get(ov.label, ov.label)
            new_odds.append(OddsValue(label=new_label, value=ov.value))
        new_markets.append(
            market.model_copy(
                update={
                    "odds": new_odds,
                    "outcome_ids": {
                        FLIP_MAP.get(label, label): value
                        for label, value in market.outcome_ids.items()
                    },
                }
            )
        )
    m.markets = new_markets
    return m
