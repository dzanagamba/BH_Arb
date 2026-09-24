"""
Match Matcher — Multi-Dimensional Match Grouping

Groups matches from different bookmakers into MatchGroups that represent
the same real-world event using multi-dimensional composite fingerprinting:

  FINGERPRINT = League × Date × Teams × Time

Gates & Matching Rules:
  1. League Gate    — Same normalized league ID (hard gate; generic leagues match any)
  2. Category Gate  — Special categories (U21, Women, Reserves, Esports) must agree (hard gate)
  3. Time/Date Gate — Kickoff within 120 minutes (hard reject beyond 2 hours / different dates)
  4. Team Match     — Evaluates both direct & swapped home/away team orientations (token_set_ratio ≥ 70%)
  5. Non-Greedy     — Selects the candidate group with the highest overall confidence score

Weighted composite confidence score:
  team_similarity_avg  × 0.80
  kickoff_proximity    × 0.20
  ≥ 0.80 required to group

Automatic Swap Handling:
  If a bookmaker flips home/away order, the match is auto-swapped and market odds
  labels (1↔2, 1X↔X2) are normalized to the group's canonical orientation.

A match group is only returned if it contains matches from 2+ distinct bookmakers.
"""

import logging

from rapidfuzz import fuzz

from config.settings import (
    FUZZY_MATCH_THRESHOLD,
    KICKOFF_WINDOW_MINUTES,
    TEAM_MATCH_MIN_PERCENT,
)
from engine.normalizer import TeamNormalizer
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from scrapers.common import flip_ah_label

logger = logging.getLogger(__name__)

# Generic fallback leagues that are too vague to enforce a league gate on
# Expanded in muse12 (P1-3): friendlies/cups/superliga are vague — keep permissive
# NOTE: cleaned league names keep the dot, e.g. "2. Liga" -> "2. liga" (dot+space). Both forms are listed.
GENERIC_LEAGUES = {
    "football", "fudbal", "soccer", "unknown_league", "", "2.liga", "2. liga", "3.liga", "3. liga",
    "kup", "klubovi", "1.liga", "1. liga", "superliga", "super liga",
    "prijateljske", "prijateljske utakmice", "prijateljske klubske",
    "world club friendly", "club friendly", "klubovi prijateljski",
    "elitne prijateljske", "friendlies",
    # Ambiguous short names without country — treat as generic to avoid false hard rejects
    # (e.g. "Premier Liga" appears for both BIH and ENG; country gate + teams decide)
    "premier liga", "premijer liga", "premier league",
    "bundesliga", "prva liga", "vtora liga",
}

# European competitions that are considered compatible for same-team same-time fixtures
# (same two clubs cannot play two different UEFA competitions at identical kickoff)
EUROPEAN_COMPATIBLE_LEAGUES = {
    "europa_league", "conference_league", "champions_league",
    "europa", "conference", "champions",
}

# Derived thresholds (from config.settings)
TEAM_MATCH_RATIO = TEAM_MATCH_MIN_PERCENT / 100.0      # per-team similarity gate
GROUP_MIN_CONFIDENCE = FUZZY_MATCH_THRESHOLD / 100.0   # overall composite confidence gate


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

    def __init__(self):
        self.normalizer = TeamNormalizer()

    def normalize_matches(self, matches: list[Match]) -> list[Match]:
        """
        Enrich all matches with normalized fields.
        Must be called before group_matches.
        """
        for m in matches:
            m.league_normalized = self.normalizer.normalize_league(m.league)
            m.country_normalized = self.normalizer.normalize_country(m.country)
            m.home_team_normalized = self.normalizer.normalize_team(
                m.home_team, league_scope=m.league_normalized
            )
            m.away_team_normalized = self.normalizer.normalize_team(
                m.away_team, league_scope=m.league_normalized
            )
            m.category_tags = self.normalizer.detect_special_category(
                f"{m.home_team} {m.away_team} {m.league}"
            )
        return matches

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
        # Sort matches so specific league matches are processed first to establish canonical groups
        sorted_matches = sorted(
            all_matches,
            key=lambda m: (0 if m.league_normalized not in GENERIC_LEAGUES else 1)
        )

        groups: list[MatchGroup] = []
        # League index: normalized league → groups in it. Generic leagues keyed under "".
        # Cuts the candidate list per match from O(all groups) to O(same-league groups).
        groups_by_league: dict[str, list[MatchGroup]] = {}

        for match in sorted_matches:
            best_group: MatchGroup | None = None
            best_conf = 0.0
            best_is_swapped = False

            m_league = match.league_normalized or match.league or ""
            if m_league in GENERIC_LEAGUES:
                # Generic league — eligible against every group
                candidate_groups = list(groups)
            else:
                # Specific league — only its bucket plus generic groups
                candidate_groups = list(groups_by_league.get(m_league, []))
                candidate_groups.extend(groups_by_league.get("", []))
                # European cross-label: Europa/Conference/Champions at same time are same match
                if m_league in EUROPEAN_COMPATIBLE_LEAGUES:
                    for euro in EUROPEAN_COMPATIBLE_LEAGUES:
                        if euro != m_league:
                            candidate_groups.extend(groups_by_league.get(euro, []))

            for group in candidate_groups:
                # Skip if this bookmaker already contributed a match to this group
                group_bookmakers = {m.bookmaker for m in group.matches}
                if match.bookmaker in group_bookmakers:
                    continue

                confidence, is_swapped = self._calculate_confidence(match, group)

                if confidence >= GROUP_MIN_CONFIDENCE and confidence > best_conf:
                    best_conf = confidence
                    best_group = group
                    best_is_swapped = is_swapped

            if best_group and best_conf >= GROUP_MIN_CONFIDENCE:
                match_to_add = swap_match_teams_and_odds(match) if best_is_swapped else match
                best_group.matches.append(match_to_add)

                # Upgrade group's canonical league/kickoff if generic
                if best_group.league in GENERIC_LEAGUES and match.league_normalized not in GENERIC_LEAGUES:
                    old_key = ""
                    best_group.league = match.league_normalized
                    # Re-index the upgraded group into its new league bucket
                    if old_key in groups_by_league and best_group in groups_by_league[old_key]:
                        groups_by_league[old_key].remove(best_group)
                    groups_by_league.setdefault(best_group.league, []).append(best_group)
                if not best_group.kickoff and match.kickoff:
                    best_group.kickoff = match.kickoff

                logger.debug(
                    f"✅ MATCHED [{match.bookmaker}] "
                    f"'{match.home_team}' vs '{match.away_team}' "
                    f"→ group ('{best_group.canonical_home}' vs '{best_group.canonical_away}') "
                    f"[conf={best_conf:.2f}, swapped={best_is_swapped}]"
                )
            else:
                new_group = MatchGroup(
                    canonical_home=match.home_team_normalized or match.home_team,
                    canonical_away=match.away_team_normalized or match.away_team,
                    league=match.league_normalized or match.league,
                    kickoff=match.kickoff,
                    matches=[match],
                )
                groups.append(new_group)
                bucket_key = new_group.league if new_group.league not in GENERIC_LEAGUES else ""
                groups_by_league.setdefault(bucket_key, []).append(new_group)

        # Only return groups with 2+ different bookmakers
        multi_bookie_groups = [
            g for g in groups
            if len(set(m.bookmaker for m in g.matches)) >= 2
        ]

        logger.info(
            f"Match grouping: {len(all_matches)} total matches "
            f"→ {len(groups)} groups "
            f"→ {len(multi_bookie_groups)} multi-bookmaker groups"
        )

        return multi_bookie_groups

    def _calculate_confidence(self, match: Match, group: MatchGroup) -> tuple[float, bool]:
        """
        Confidence score (0.0–1.0) that a match belongs to a group,
        and boolean flag indicating if home/away order is swapped.

        Returns: (confidence_score, is_swapped)
        """
        m_league = match.league_normalized or ""
        g_league = group.league or ""

        # Hard gate: special categories (U21, Women, Reserves, Esports) must agree.
        # Prevents "Sarajevo U21" from grouping with senior "Sarajevo", women's
        # teams with men's teams, or virtual/esports events with real matches.
        match_tags = set(match.category_tags or [])
        group_tags = set(group.matches[0].category_tags or []) if group.matches else set()
        if match_tags != group_tags:
            return 0.0, False

        # Hard gate: If both match and group have specific (non-generic) leagues, they MUST match
        # Exception: European competitions at same kickoff with same teams are same match even if labeled differently
        if (
            m_league and g_league
            and m_league not in GENERIC_LEAGUES
            and g_league not in GENERIC_LEAGUES
            and m_league != g_league
        ):
            # Allow cross-label European fixtures (e.g. Europa vs Conference at identical time)
            if m_league in EUROPEAN_COMPATIBLE_LEAGUES and g_league in EUROPEAN_COMPATIBLE_LEAGUES:
                pass  # compat — don't reject, rely on team/time gates
            else:
                return 0.0, False

        # Country soft gate (P1-3): if both have normalized country and mismatch, reject
        # Prevents Borac BL (BiH) vs Borac Cacak (Serbia) when league is generic/fuzzy
        m_country = (match.country_normalized or "").strip().lower()
        # Group country is from first match (representative)
        g_country = ""
        if group.matches:
            g_country = (group.matches[0].country_normalized or "").strip().lower()
        if m_country and g_country and m_country != g_country:
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

        # Check direct orientation
        dir_home = fuzz.token_set_ratio(match.home_team_normalized, group.canonical_home) / 100.0
        dir_away = fuzz.token_set_ratio(match.away_team_normalized, group.canonical_away) / 100.0

        # Check swapped orientation
        swap_home = fuzz.token_set_ratio(match.home_team_normalized, group.canonical_away) / 100.0
        swap_away = fuzz.token_set_ratio(match.away_team_normalized, group.canonical_home) / 100.0

        dir_conf = ((dir_home + dir_away) / 2.0) * 0.80 + time_score * 0.20 if (dir_home >= TEAM_MATCH_RATIO and dir_away >= TEAM_MATCH_RATIO) else 0.0
        swap_conf = ((swap_home + swap_away) / 2.0) * 0.80 + time_score * 0.20 if (swap_home >= TEAM_MATCH_RATIO and swap_away >= TEAM_MATCH_RATIO) else 0.0

        if dir_conf >= swap_conf and dir_conf >= GROUP_MIN_CONFIDENCE:
            return dir_conf, False
        elif swap_conf > dir_conf and swap_conf >= GROUP_MIN_CONFIDENCE:
            return swap_conf, True

        return max(dir_conf, swap_conf), False

    def get_match_report(self, groups: list[MatchGroup]) -> list[dict]:
        """
        Generate a debugging report of all match groupings.
        Call this to verify correct pairing before trusting surebets.
        """
        report = []
        for i, group in enumerate(groups):
            bookmakers: list[dict] = []
            entry: dict[str, object] = {
                "group_id": i + 1,
                "canonical_match": f"{group.canonical_home} vs {group.canonical_away}",
                "league": group.league,
                "kickoff": group.kickoff.isoformat() if group.kickoff else "unknown",
                "bookmakers": bookmakers,
            }
            for match in group.matches:
                bookmakers.append({
                    "bookmaker": match.bookmaker,
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


def swap_match_teams_and_odds(match: Match) -> Match:
    """
    Flip home/away teams and swap 1X2 / Double Chance odds labels
    so that outcome 1 corresponds to canonical home team and outcome 2 to canonical away team.
    """
    m = match.model_copy(deep=True)
    m.home_team, m.away_team = m.away_team, m.home_team
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
            if market.market_type == MarketType.ASIAN_HANDICAP:
                new_label = flip_ah_label(ov.label)
            elif market.market_type == MarketType.FIRST_HALF_1X2:
                new_label = FLIP_MAP.get(ov.label, ov.label)
            else:
                new_label = FLIP_MAP.get(ov.label, ov.label)
            new_odds.append(OddsValue(label=new_label, value=ov.value))
        new_markets.append(Market(market_type=market.market_type, odds=new_odds))
    m.markets = new_markets
    return m
