### Task 2: Build the CertaintyGate with hard gates and evidence trail

**Files:**
- Create: `engine/certainty.py`
- Modify: `config/settings.py:123-126` (add `VERIFIED_KICKOFF_WINDOW_MINUTES = 15`)
- Test: `tests/test_certainty.py` (create)

**Interfaces:**
- Consumes: `MatchEvidence`, `MatchEventStatus` from Task 1; `Match`, `MatchGroup`; `VERIFIED_KICKOFF_WINDOW_MINUTES` from `config.settings`.
- Produces:
  - `GateResult` (dataclass): `status: MatchEventStatus`, `reasons: list[str]`, `evidence: list[MatchEvidence]`, `is_swapped: bool = False`.
  - `class CertaintyGate` with:
    - `__init__(self, kickoff_window_minutes: int = VERIFIED_KICKOFF_WINDOW_MINUTES, alias_allowlist: set[str] | None = None, league_equivalences: set[tuple[str, str]] | None = None) -> None`
    - `evaluate(self, match: Match, group: MatchGroup) -> GateResult`
    - `evaluate_pair(self, a: Match, b: Match) -> GateResult`
    - `_league_ok(self, a_league: str, b_league: str) -> bool`
    - `_kickoff_delta_minutes(self, a: Match, b: Match) -> float | None`
    - `_teams_ok(self, a: Match, b: Match) -> tuple[bool, bool, str]` returning `(ok, is_swapped, reason)`.
  - Reasons are exactly: `league_mismatch`, `kickoff_missing`, `kickoff_delta`, `category_mismatch`, `team_unresolved`, `orientation_unresolved`, `link_unverified`, `no_event_link`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_certainty.py`:

```python
"""CertaintyGate: hard gates for verified same-event claims."""
import asyncio
from datetime import UTC, datetime, timedelta

from engine.certainty import CertaintyGate
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

K = datetime(2026, 9, 25, 18, 0)


def _m(bookmaker, home, away, league, kickoff=K, home_n=None, away_n=None, tags=None, url="", event_id="", link_ok=True):
    m = Match(
        bookmaker=bookmaker, home_team=home, away_team=away, league=league, kickoff=kickoff,
        home_team_normalized=home_n or home.lower(), away_team_normalized=away_n or away.lower(),
        category_tags=tags or [], url=url, event_id=event_id, deep_link_verified=link_ok,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0), OddsValue(label="2", value=3.0)])],
    )
    return m


def _g(match, league="premier_liga_bih"):
    return MatchGroup(canonical_home=match.home_team_normalized, canonical_away=match.away_team_normalized,
                      league=league, kickoff=match.kickoff, matches=[match])


def test_verified_when_all_gates_pass():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=True)
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=True)
    gate.normalize([a, b])  # populates *_normalized via TeamNormalizer
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert r.reasons == []
    assert any(e.rule == "league_identity" for e in r.evidence)
    assert any(e.rule == "kickoff" for e in r.evidence)
    assert any(e.rule == "team_identity" for e in r.evidence)


def test_aware_and_naive_kickoffs_compare_equal():
    gate = CertaintyGate()
    aware = K.replace(tzinfo=UTC) + timedelta(hours=2)
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", kickoff=K, event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=aware.astimezone(UTC).replace(tzinfo=None), event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "kickoff_delta" not in r.reasons


def test_missing_kickoff_never_verified():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=None, event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status != "verified"
    assert "kickoff_missing" in r.reasons


def test_kickoff_delta_over_15_minutes_rejected():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=K + timedelta(minutes=45), event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status != "verified"
    assert "kickoff_delta" in r.reasons


def test_league_mismatch_rejected():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Arsenal", "Chelsea", "Engleska - Premier liga", event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "league_mismatch" in r.reasons


def test_category_mismatch_rejected():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", tags=[], event_id="1")
    b = _m("mbet", "Sarajevo U21", "Zeljeznicar U21", "Premijer Liga BiH", tags=["U21"], event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "category_mismatch" in r.reasons


def test_home_away_swap_is_provable():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Zeljeznicar", "Sarajevo", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert r.is_swapped is True


def test_link_unverified_blocks_verified():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", url="", event_id="", link_ok=False)
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=True)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert "link_unverified" in r.reasons


def test_explicit_equivalence_allows_different_leagues():
    gate = CertaintyGate(league_equivalences={("europa_league", "conference_league")})
    a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
    b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
    a.league_normalized, b.league_normalized = "europa_league", "conference_league"
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "league_mismatch" not in r.reasons


def test_allowlisted_alias_is_accepted_but_unlisted_fuzzy_is_not():
    # "lech p" is a reviewed alias of "lech poznan" (written as "lech p|lech poznan")
    gate = CertaintyGate(alias_allowlist={"lech p|lech poznan"})
    a = _m("mdshop", "Lech Poznan", "Thun", "Liga Evrope", event_id="1")
    b = _m("mbet", "Lech P.", "Thun", "Liga Evrope", event_id="2")
    gate.normalize([a, b])
    b.home_team_normalized = "lech p"  # force the alias form (normalizer may have stripped it)
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert any(e.rule == "team_identity" and e.source == "allowlist" for e in r.evidence)

    gate2 = CertaintyGate()  # no allowlist
    r2 = gate2.evaluate_pair(a, b)
    assert r2.status != "verified"
    assert "team_unresolved" in r2.reasons


def test_evaluate_against_group_uses_group_as_canonical():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    g = _g(a)
    r = gate.evaluate(b, g)
    assert r.status == "verified"
    # Unknown league on the candidate is a hard reject even when the group is known
    c = _m("wwin", "Sarajevo", "Zeljeznicar", "Liga totally unknown", event_id="3")
    gate.normalize([c])
    r2 = gate.evaluate(c, g)
    assert r2.status == "rejected"
    assert "league_mismatch" in r2.reasons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.certainty'`.

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, after `KICKOFF_WINDOW_MINUTES` (line 124), add:
```python
VERIFIED_KICKOFF_WINDOW_MINUTES = 15  # Max kickoff delta for a `verified` group
```

Create `engine/certainty.py`:

```python
"""CertaintyGate — deterministic proofs that two matches are the same event.

The rule stage of the mapping pipeline. Produces `verified` only when league,
kickoff, category, team identity, orientation, and link evidence all hold.
Ambiguous pairs get `suggested` with explicit reasons; `rejected` when a hard
gate contradicts the claim.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from engine.normalizer import TeamNormalizer
from models.schemas import Match, MatchEventStatus, MatchEvidence, MatchGroup

HARD_REJECT_REASONS = frozenset({"league_mismatch", "category_mismatch", "orientation_unresolved"})


@dataclass
class GateResult:
    status: MatchEventStatus
    reasons: list[str] = field(default_factory=list)
    evidence: list[MatchEvidence] = field(default_factory=list)
    is_swapped: bool = False


class CertaintyGate:
    """Evaluate candidate same-event pairs against hard, deterministic gates."""

    def __init__(
        self,
        kickoff_window_minutes: int = 15,
        alias_allowlist: set[str] | None = None,
        league_equivalences: set[tuple[str, str]] | None = None,
    ) -> None:
        self.normalizer = TeamNormalizer()
        self.kickoff_window_minutes = kickoff_window_minutes
        self.alias_allowlist = alias_allowlist or set()
        self.league_equivalences = league_equivalences or set()

    def normalize(self, matches: list[Match]) -> list[Match]:
        for m in matches:
            m.league_normalized = m.league_normalized or self.normalizer.normalize_league(m.league)
            m.home_team_normalized = m.home_team_normalized or self.normalizer.normalize_team(m.home_team)
            m.away_team_normalized = m.away_team_normalized or self.normalizer.normalize_team(m.away_team)
            m.category_tags = m.category_tags or self.normalizer.detect_special_category(
                f"{m.home_team} {m.away_team} {m.league}"
            )
        return matches

    def _league_ok(self, a_league: str, b_league: str) -> bool:
        if not a_league or not b_league:
            return False
        if a_league == b_league:
            return True
        return (a_league, b_league) in self.league_equivalences or (b_league, a_league) in self.league_equivalences

    @staticmethod
    def _as_naive_utc(dt: datetime) -> datetime:
        return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt

    def _kickoff_delta_minutes(self, a: Match, b: Match) -> float | None:
        if not a.kickoff or not b.kickoff:
            return None
        return abs((self._as_naive_utc(a.kickoff) - self._as_naive_utc(b.kickoff)).total_seconds()) / 60.0

    def _teams_ok(self, a: Match, b: Match) -> tuple[bool, bool, str]:
        """Exact canonical IDs or an allowlisted alias; returns (ok, is_swapped, reason)."""
        from rapidfuzz import fuzz
        ah, aa = a.home_team_normalized, a.away_team_normalized
        bh, ba = b.home_team_normalized, b.away_team_normalized
        if not (ah and aa and bh and ba):
            return False, False, "team_unresolved"
        if ah == bh and aa == ba:
            return True, False, ""
        if ah == ba and aa == bh:
            return True, True, ""
        # The only fuzzy path: a reviewed alias present in the allowlist.
        for left, right in ((ah, bh), (ah, ba), (aa, bh), (aa, ba)):
            if self._is_allowlisted(left, right) and fuzz.token_set_ratio(left, right) >= 90:
                return True, left == ba, ""
        return False, False, "team_unresolved"

    def _is_allowlisted(self, left: str, right: str) -> bool:
        """True when the pair (in either order) is in the allowlist, scoped per bookmaker when given."""
        if not self.alias_allowlist:
            return False
        pair = {left, right}
        return any(set(entry) == pair for entry in self.alias_allowlist_entries)

    @property
    def alias_allowlist_entries(self) -> list[set[str]]:
        return [set(e.split("|")) for e in self.alias_allowlist if "|" in e]

    @staticmethod
    def _link_evidence(m: Match) -> MatchEvidence | None:
        if m.deep_link_verified:
            return MatchEvidence(rule="link_evidence", source="rule", confidence=1.0, reason="verified_link")
        if m.event_id or m.url:
            return MatchEvidence(rule="link_evidence", source="rule", confidence=0.0, reason="link_unverified")
        return MatchEvidence(rule="link_evidence", source="rule", confidence=0.5, reason="no_event_link")

    def evaluate_pair(self, a: Match, b: Match) -> GateResult:
        reasons: list[str] = []
        evidence: list[MatchEvidence] = []

        # League identity
        a_league, b_league = a.league_normalized or "", b.league_normalized or ""
        league_ok = self._league_ok(a_league, b_league)
        if not league_ok:
            reasons.append("league_mismatch")
        evidence.append(MatchEvidence(
            rule="league_identity", source="rule",
            confidence=1.0 if league_ok else 0.0,
            league_pair=[a_league, b_league],
        ))

        # Kickoff
        delta = self._kickoff_delta_minutes(a, b)
        if delta is None:
            reasons.append("kickoff_missing")
        elif delta > self.kickoff_window_minutes:
            reasons.append("kickoff_delta")
        evidence.append(MatchEvidence(
            rule="kickoff", source="rule",
            confidence=1.0 if delta is not None and delta <= 5 else (0.8 if delta is not None else 0.0),
            kickoff_delta_minutes=delta,
        ))

        # Category
        a_tags, b_tags = set(a.category_tags or []), set(b.category_tags or [])
        if a_tags != b_tags:
            reasons.append("category_mismatch")

        # Team identity
        teams_ok, is_swapped, team_reason = self._teams_ok(a, b)
        exact_teams = (a.home_team_normalized == b.home_team_normalized
                       and a.away_team_normalized == b.away_team_normalized)
        if not teams_ok:
            reasons.append(team_reason)
        if not teams_ok:
            team_source = "rule"
        elif exact_teams:
            team_source = "rule"
        else:
            team_source = "allowlist"
        evidence.append(MatchEvidence(
            rule="team_identity", source=team_source, confidence=1.0 if teams_ok else 0.0,
            reason=("exact" if team_source == "rule" else ("swapped" if is_swapped else "allowlisted_alias")),
            allowlist_entries=sorted(self.alias_allowlist) if team_source == "allowlist" else [],
        ))

        # Link evidence
        link_reasons = set()
        for m in (a, b):
            le = self._link_evidence(m)
            evidence.append(le)
            if le.reason == "link_unverified":
                link_reasons.add("link_unverified")
            elif le.reason == "no_event_link":
                link_reasons.add("no_event_link")
        reasons.extend(sorted(link_reasons))

        if reasons:
            hard = [r for r in reasons if r in HARD_REJECT_REASONS]
            status: MatchEventStatus = "rejected" if hard else "suggested"
        else:
            status = "verified"
        return GateResult(status=status, reasons=reasons, evidence=evidence, is_swapped=is_swapped)

    def evaluate(self, match: Match, group: MatchGroup) -> GateResult:
        anchor = group.matches[0]
        result = self.evaluate_pair(match, anchor)
        if result.status == "verified" and group.league:
            m_league = match.league_normalized or ""
            if m_league and m_league != group.league and not self._league_ok(m_league, group.league):
                result.status = "rejected"
                result.reasons.append("league_mismatch")
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v`
Expected: PASS (9 passed, including the two assertions inside `test_evaluate_against_group_uses_group_as_canonical`).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q`
Expected: all existing tests still PASS (no failures introduced by schema defaults).

- [ ] **Step 6: Commit**

```bash
git add config/settings.py engine/certainty.py tests/test_certainty.py
git commit -m "feat(mapping): add CertaintyGate with league/kickoff/category/team/orientation/link hard gates"
```

---

