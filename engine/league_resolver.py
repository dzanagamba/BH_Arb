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

from engine.mapping_evidence import MappingLedger


def _raw(name: str) -> str:
    from engine.certainty import CertaintyGate

    return CertaintyGate._raw_team_key(name)


class LeagueResolver:
    """Team-set fingerprints read from accepted ``league_fingerprint`` claims."""

    def __init__(self, ledger: MappingLedger | None = None) -> None:
        self.ledger = ledger

    def teams_for(self, league: str) -> frozenset[str]:
        if self.ledger is None or not league:
            return frozenset()
        claim = self.ledger.get("league_fingerprint", league)
        if claim is None or not claim.is_authoritative():
            return frozenset()
        teams: set[str] = set()
        for evidence in claim.evidence:
            raw = evidence.detail.get("teams")
            if isinstance(raw, list):
                teams.update(str(team) for team in raw)
        return frozenset(teams)

    def same_competition(
        self, left_league: str, right_league: str, home: str, away: str
    ) -> bool:
        left = self.teams_for(left_league)
        right = self.teams_for(right_league)
        if not left or not right:
            return False
        fixture = {_raw(home), _raw(away)}
        if not fixture <= left or not fixture <= right:
            return False
        if left == right:
            return False
        smaller, larger = (left, right) if len(left) < len(right) else (right, left)
        return smaller < larger
