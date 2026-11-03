"""Resolve a league pair from the teams that actually play in it.

A global name map cannot represent a book that uses one name for two
competitions ("Serija A" for both Italy and Brazil). The fingerprint is the set
of teams observed under a league name; at gate time the fixture's own teams
decide which specific competition a name refers to.

The rule is deliberately narrow: both league names must cover the fixture's two
teams, and one team set must be a proper subset of the other. The smaller,
specific set is the competition; a name whose set is the union of several
competitions is accepted only against a set contained in it. Two unrelated sets
never match.
"""

from __future__ import annotations

from engine.league_names import GENERIC_LEAGUES
from engine.mapping_evidence import MappingLedger
from engine.normalizer import TeamNormalizer


class LeagueResolver:
    """Team-set fingerprints read from accepted ``league_fingerprint`` claims."""

    def __init__(self, ledger: MappingLedger | None = None) -> None:
        self.ledger = ledger
        self._normalizer = TeamNormalizer()
        self._team_cache: dict[str, frozenset[str]] = {}

    def _key(self, name: str) -> str:
        return self._normalizer.normalize_team(name)

    def teams_for(self, league: str) -> frozenset[str]:
        """The league's teams as canonical ids, so spelling variants agree."""
        if self.ledger is None or not league:
            return frozenset()
        cached = self._team_cache.get(league)
        if cached is not None:
            return cached
        claim = self.ledger.get("league_fingerprint", league)
        if claim is None or not claim.is_authoritative():
            return frozenset()
        teams: set[str] = set()
        for evidence in claim.evidence:
            raw = evidence.detail.get("teams")
            if isinstance(raw, list):
                teams.update(self._key(str(team)) for team in raw)
        result = frozenset(teams)
        self._team_cache[league] = result
        return result

    def same_competition(
        self, left_league: str, right_league: str, home: str, away: str
    ) -> bool:
        left = self.teams_for(left_league)
        right = self.teams_for(right_league)
        if not left or not right:
            return False
        fixture = {self._key(home), self._key(away)}
        if not fixture <= left or not fixture <= right:
            return False
        if left == right:
            # Identical team sets under a generic and a country-qualified name
            # are the same competition. Two arbitrary names with equal sets are
            # not: that is a name alias, and the ledger must prove it.
            return (left_league in GENERIC_LEAGUES) != (right_league in GENERIC_LEAGUES)
        smaller, larger = (left, right) if len(left) < len(right) else (right, left)
        return smaller < larger
