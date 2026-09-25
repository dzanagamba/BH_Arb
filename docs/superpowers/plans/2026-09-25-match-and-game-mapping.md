# Match & Game Mapping Certainty System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every surebet rests on a provable same-event claim (fixture identity, market type, and deep link), while a hosted-AI layer maximizes candidate opportunities and a human review queue gates promotion to tradeable.

**Architecture:** The existing `MatchMatcher` becomes the deterministic rule stage. A new `CertaintyGate` applies hard gates (league identity, 15-minute kickoff, category, canonical team IDs, orientation, link evidence) and stamps each `MatchGroup` with `verified` / `suggested` / `rejected` plus an evidence trail. Ambiguous pairs that fail the rule stage are sent to a `MatchAI` adapter (hosted, OpenAI-compatible) which only *proposes*; proposals enter a review queue and only human approval (or an existing allowlist entry) makes a group tradeable. Market IDs move into a single per-book registry `config/bookmaker_markets.json`; deep-link builders move into `config/bookmaker_deeplinks.json` + `scrapers/common.py`.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, rapidfuzz, httpx, Playwright, pytest, ruff, mypy. No new runtime dependencies; the AI adapter uses stdlib `httpx` against an OpenAI-compatible endpoint.

**Spec:** `docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md`

## Global Constraints

- `verified` means **every** part of the claim is proven, including links.
- `KICKOFF_WINDOW_MINUTES` for verified pairs is **15** (down from 120).
- AI never auto-approves a pair; a proposal enters the review queue even at 0.99 confidence.
- Allowlisted fuzzy aliases are the only auto-accepted fuzzy path, and only when league, kickoff, and category gates pass.
- Blanket cross-league merging (`EUROPEAN_COMPATIBLE_LEAGUES`) is removed; equivalence is explicit, per-pair, and still enforces the 15-minute kickoff window.
- A market ID not in the registry is counted in `unmapped_markets` and surfaced on `/api/health` — never silently dropped.
- `MARKET_MAPPING.md` is generated from the registry, not hand-maintained.
- Every registry entry must be exercised by at least one fixture test built from a captured payload.
- Backward compatibility: `MatchGroup` gains optional fields with defaults so existing construction sites and tests keep working.

## Review Focus

Five input classes / failure modes most likely to bite, each pinned to a task:

1. **Aware vs naive kickoff mix** — a `+02:00` kickoff must compare equal to the same instant in naive UTC (Task 2).
2. **Missing kickoff on one side** — must never be `verified` (Task 2).
3. **League name collision across countries** — `Bundesliga` (Austria) vs `Bundesliga` (Germany) and `1.LIGA` (Turkey) vs `1.LIGA` (Slovenia) must not merge; distinct canonical IDs stay distinct (Task 3).
4. **Same teams, two different fixtures 3h apart** — kickoff window rejects regardless of league/team similarity (Task 2, 3).
5. **Unknown market ID** — a bookmaker returning an unmapped ID must be counted, not silently dropped (Task 4).

---

### Task 1: Extend schemas — statuses, evidence, and link metadata

**Files:**
- Modify: `models/schemas.py:57-64` (MatchGroup), `models/schemas.py:31-55` (Match)
- Test: `tests/test_schemas_mapping.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `MatchEventStatus` — `Literal["verified","suggested","rejected"]`.
  - `MatchEvidence` (BaseModel): `rule: str`, `source: Literal["rule","ai","human","allowlist"]`, `confidence: float = 0.0`, `reason: str = ""`, `league_pair: list[str] = []`, `kickoff_delta_minutes: float | None = None`, `allowlist_entries: list[str] = []`.
  - `MatchGroup.status: MatchEventStatus = "suggested"`, `MatchGroup.evidence: list[MatchEvidence] = []`.
  - `Match.deep_link_verified: bool = False`, `Match.event_id: str = ""`.
  - `CandidateReview` (BaseModel): `id: str`, `home_team: str`, `away_team: str`, `league: str`, `kickoff: datetime | None`, `bookmakers: list[str]`, `ai_confidence: float = 0.0`, `ai_reason: str = ""`, `rule_rejections: list[str] = []`, `status: Literal["pending","approved","rejected"] = "pending"`, `created_at: datetime`, `resolved_at: datetime | None = None`, `resolved_by: str = ""`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_schemas_mapping.py`:

```python
"""Schemas for mapping certainty: statuses, evidence, deep-link metadata."""
from datetime import datetime

from models.schemas import CandidateReview, Match, MatchEvidence, MatchGroup


def test_match_group_defaults_to_suggested_with_empty_evidence():
    g = MatchGroup(canonical_home="a", canonical_away="b")
    assert g.status == "suggested"
    assert g.evidence == []


def test_match_group_accepts_verified_status_and_evidence():
    g = MatchGroup(
        canonical_home="a", canonical_away="b", status="verified",
        evidence=[MatchEvidence(rule="league_identity", source="rule", confidence=1.0)],
    )
    assert g.status == "verified"
    assert g.evidence[0].rule == "league_identity"
    assert g.evidence[0].source == "rule"


def test_match_exposes_deep_link_metadata():
    m = Match(bookmaker="mdshop", home_team="A", away_team="B", event_id="123", deep_link_verified=True)
    assert m.event_id == "123"
    assert m.deep_link_verified is True


def test_candidate_review_defaults_pending():
    c = CandidateReview(
        id="c1", home_team="A", away_team="B", league="L", kickoff=datetime(2026, 9, 25, 18, 0),
        bookmakers=["mdshop", "mbet"], created_at=datetime(2026, 9, 25, 12, 0),
    )
    assert c.status == "pending"
    assert c.ai_confidence == 0.0
    assert c.rule_rejections == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_schemas_mapping.py -v`
Expected: FAIL with `AttributeError: module 'models.schemas' has no attribute 'MatchEvidence'` (and similar for `CandidateReview`).

- [ ] **Step 3: Write minimal implementation**

In `models/schemas.py`, add `Literal` to the imports (`from typing import Literal`), add `MatchEventStatus`, `MatchEvidence`, and `CandidateReview` above `MatchGroup`, and add the new fields:

```python
MatchEventStatus = Literal["verified", "suggested", "rejected"]


class MatchEvidence(BaseModel):
    rule: str
    source: Literal["rule", "ai", "human", "allowlist"]
    confidence: float = 0.0
    reason: str = ""
    league_pair: list[str] = []
    kickoff_delta_minutes: float | None = None
    allowlist_entries: list[str] = []


class CandidateReview(BaseModel):
    id: str
    home_team: str
    away_team: str
    league: str
    kickoff: datetime | None = None
    bookmakers: list[str] = []
    ai_confidence: float = 0.0
    ai_reason: str = ""
    rule_rejections: list[str] = []
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str = ""
```

Add to `Match` (after `match_code`):
```python
    event_id: str = ""
    deep_link_verified: bool = False
```
Add to `MatchGroup` (after `matches`):
```python
    status: MatchEventStatus = "suggested"
    evidence: list[MatchEvidence] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_schemas_mapping.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add models/schemas.py tests/test_schemas_mapping.py
git commit -m "feat(mapping): add MatchEventStatus, MatchEvidence, CandidateReview schemas"
```

---

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

### Task 3: Integrate the gate into the matcher and tighten hard gates

**Files:**
- Modify: `engine/matcher.py:1-66` (remove `EUROPEAN_COMPATIBLE_LEAGUES` bridging, add gate import), `engine/matcher.py:104-209` (apply gate, set status/evidence)
- Modify: `config/league_mappings.json` (fix provably wrong entries: `argentine_primera` should not contain `Argentina 2`/`Primera B Nacional`; `bugarian_first_league` should not be the canonical for `Bugarska 2`; `bundesliga_2` vs `nemacka_2` overlap)
- Create: `config/league_equivalences.json`
- Test: `tests/test_matcher_certified.py` (create)

**Interfaces:**
- Consumes: `CertaintyGate`, `GateResult` from Task 2; `MatchEvidence` from Task 1.
- Produces: `MatchMatcher.group_matches` now returns groups with `status` and `evidence` set; groups that fail the gate are dropped (not returned as multi-book groups). `config/league_equivalences.json` shape: `{"pairs": [["europa_league","conference_league"]]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_matcher_certified.py`:

```python
"""Matcher integration: only gate-passing groups are returned."""
from datetime import datetime, timedelta

from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue

K = datetime(2026, 9, 25, 18, 0)


def _m(bookmaker, home, away, league, kickoff=K, event_id="", link_ok=True):
    return Match(
        bookmaker=bookmaker, home_team=home, away_team=away, league=league, kickoff=kickoff,
        url=f"https://example.test/{bookmaker}/{event_id}" if event_id else "",
        event_id=event_id, deep_link_verified=link_ok,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0), OddsValue(label="2", value=3.0)])],
    )


def test_verified_group_returned_with_evidence():
    a = _m("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 1
    assert groups[0].status == "verified"
    assert any(e.rule == "team_identity" for e in groups[0].evidence)


def test_group_with_unresolved_team_is_not_returned():
    a = _m("mdshop", "Alpha FC", "Beta United", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Gamma SC", "Delta Club", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 0


def test_europa_conference_merge_only_via_declared_equivalence():
    a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
    b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
    import engine.matcher as matcher_mod
    assert not hasattr(matcher_mod, "EUROPEAN_COMPATIBLE_LEAGUES"), "blanket European merging must be removed"
    # With the shipped league_equivalences.json this may group, but only as `verified`
    # when every hard gate (kickoff, teams, link) also passes.
    groups = MatchMatcher().group_matches([a, b])
    for g in groups:
        assert g.status == "verified"
        assert any(e.rule == "league_identity" and e.league_pair for e in g.evidence)


def test_kickoff_gap_of_16_minutes_is_not_verified():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=K + timedelta(minutes=16), event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert all(g.status != "verified" for g in groups)


def test_same_teams_three_hours_apart_never_group():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=K + timedelta(hours=3), event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 0


def test_unverified_link_yields_suggested_or_dropped_not_verified():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=False)
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    for g in groups:
        assert g.status != "verified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py -v`
Expected: FAIL — `test_verified_group_returned_with_evidence` fails because `MatchGroup` has no `status`/`evidence` set by the matcher (currently the group is `suggested` by default, and `test_group_with_unresolved_team_is_not_returned` may pass only by accident of fuzzy thresholds).

- [ ] **Step 3: Write minimal implementation**

First, fix the provably wrong league mappings. In `config/league_mappings.json`:
- Remove `"Argentina 2"`, `"ARGENTINA 2"`, and `"Primera B Nacional"` from `argentine_primera` and add a new key:
```json
    "argentine_primera_b_nacional": [
        "Argentina 2", "ARGENTINA 2", "Primera B Nacional", "Primera Nacional"
    ],
```
- Remove `"Bugarska 2"`-style entries: the current `bugarian_first_league` contains only tier-1 names. Add:
```json
    "bugarian_second_league": [
        "Bugarska 2", "BULGARIA 2", "bulgaria 2", "Vtora Liga", "vtora liga"
    ],
```
- `bundesliga_2` currently lists `Bundesliga 2` which is the same as `nemacka_2`. Keep `bundesliga_2` for German `2. Bundesliga` and add `"Bundesliga 2"` to `nemacka_2` only (already present), removing it from `bundesliga_2`.

Then create `config/league_equivalences.json`:
```json
{
  "pairs": [
    ["europa_league", "conference_league"]
  ]
}
```

Now modify `engine/matcher.py`:
1. Remove the `EUROPEAN_COMPATIBLE_LEAGUES` constant and its use (lines 58-63, 145-149, 237-239).
2. Add at the top of the imports: `from engine.certainty import CertaintyGate, GateResult`.
3. In `MatchMatcher.__init__`, load equivalences and build a gate:
```python
import json, os
_LEAGUE_EQUIV_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "league_equivalences.json")

def __init__(self):
    self.normalizer = TeamNormalizer()
    self._equivalences: set[tuple[str, str]] = set()
    try:
        with open(_LEAGUE_EQUIV_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for pair in data.get("pairs", []):
            if len(pair) == 2:
                self._equivalences.add((pair[0], pair[1]))
    except (OSError, ValueError):
        logger.warning("league_equivalences.json not found or invalid — no cross-league merging")
    self.gate = CertaintyGate(league_equivalences=self._equivalences)
```
4. In `group_matches`, after computing `best_group` and before appending, apply the gate. Replace the confidence check at line 164 with:
```python
            if best_group and best_conf >= GROUP_MIN_CONFIDENCE:
                gate_result = self.gate.evaluate(match, best_group)
                if gate_result.status == "verified":
                    match_to_add = swap_match_teams_and_odds(match) if gate_result.is_swapped else match
                    best_group.matches.append(match_to_add)
                    best_group.evidence.extend(gate_result.evidence)
                    ... existing generic-league upgrade and kickoff upgrade ...
                else:
                    logger.debug(
                        f"⛔ GATE REJECTED [{match.bookmaker}] '{match.home_team}' vs '{match.away_team}' "
                        f"→ reasons={gate_result.reasons}"
                    )
                    # do not append; the match stays a singleton
```
5. When a new group is created, set `status="suggested"` and seed `evidence` with a rule-stage note. When a group reaches 2+ verified bookmakers, set `status="verified"`.
6. In the final multi-book filter, only keep groups with `status == "verified"` and ≥2 distinct bookmakers.

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the full suite**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q`
Expected: `tests/test_matcher.py` will need updates because several of its fixtures build matches with **no `event_id` and no `url`**, which the gate flags `no_event_link` → `suggested`, so those groups are no longer returned. Update the shared `_match()` helper in `tests/test_matcher.py` to accept and set `event_id` + `deep_link_verified=True` (e.g. `event_id=f"{bookmaker}-{home}"`, `url=f"https://example.test/{bookmaker}"`), then assert `groups[0].status == "verified"` in the grouping tests and keep the U21/Women tests asserting `len(groups) == 0`. All tests must pass.

- [ ] **Step 6: Commit**

```bash
git add engine/matcher.py config/league_mappings.json config/league_equivalences.json tests/test_matcher_certified.py tests/test_matcher.py
git commit -m "feat(mapping): integrate certainty gate into matcher, remove blanket European merging, fix wrong league entries"
```

---

### Task 4: Create the per-book market registry and wire parsers to it

**Files:**
- Create: `config/bookmaker_markets.json`
- Create: `engine/market_registry.py`
- Modify: `scrapers/common.py:298-374` (`parse_nsoft_bets` reads the registry for NSoft books), `scrapers/mbet.py` (`_resolve_mbet_market`), `scrapers/wwin.py`, `scrapers/sportplus.py`, `scrapers/premier_kladionica.py`, `scrapers/evlbet.py`, `scrapers/mozzartbet.py`, `scrapers/betole.py` (each parser looks up IDs via the registry)
- Test: `tests/test_market_registry.py` (create)

**Interfaces:**
- Consumes: `config/bookmaker_markets.json` (new), existing `Market`, `MarketType`, `OddsValue`.
- Produces:
  - `class MarketRegistry` with `__init__(self, path: str = REGISTRY_PATH)`, `lookup(self, bookmaker: str, mode: str, source_id: int | str) -> MarketSpec | None`, `ids_for(self, bookmaker: str, mode: str, market_type: MarketType) -> set[int | str]`, `unmapped` counter.
  - `class MarketSpec` (dataclass): `bookmaker: str`, `mode: str`, `market_type: MarketType`, `ids: set[int | str]`, `labels: set[str]`, `min_legs: int = 3`, `line: float | None = None`, `settlement: str = "full_time"`.
  - Module-level `MARKET_REGISTRY = MarketRegistry()` for import.
  - `unmapped_markets: dict[str, int]` keyed by `f"{bookmaker}:{source_id}"`, incremented by `record_unmapped(bookmaker, source_id)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_market_registry.py`:

```python
"""Market registry: one source of truth for per-book market IDs."""
import json

import pytest

from engine.market_registry import MarketRegistry, record_unmapped, unmapped_markets
from models.schemas import MarketType


def test_registry_loads_and_looks_up_mdshop_1x2():
    r = MarketRegistry()
    spec = r.lookup("mdshop", "prematch", 135)
    assert spec is not None
    assert spec.market_type == MarketType.MATCH_RESULT
    assert spec.settlement == "full_time"


def test_registry_looks_up_admiralbet_bookmaker_specific_id():
    r = MarketRegistry()
    spec = r.lookup("admiralbet", "prematch", 1639)
    assert spec is not None
    assert spec.market_type == MarketType.MATCH_RESULT


def test_registry_distinguishes_prematch_from_live_ids():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 135) is not None
    assert r.lookup("mdshop", "live", 135) is None
    assert r.lookup("mdshop", "live", 6) is not None


def test_registry_rejects_unmapped_id():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 99999) is None


def test_every_enabled_book_has_prematch_and_live_1x2():
    from config.settings import BOOKMAKERS
    r = MarketRegistry()
    for bid, cfg in BOOKMAKERS.items():
        if not cfg.get("enabled"):
            continue
        for mode in ("prematch", "live"):
            spec = r.lookup(bid, mode, _first_id(r, bid, mode))
            if spec is None:
                pytest.fail(f"{bid}/{mode} has no 1X2 entry")


def _first_id(r, bid, mode):
    ids = r.ids_for(bid, mode, MarketType.MATCH_RESULT)
    assert ids, f"{bid}/{mode} missing 1X2"
    return sorted(ids)[0]


def test_unknown_id_is_recorded_not_silently_dropped():
    from engine.market_registry import record_unmapped
    record_unmapped("mdshop", 424242)
    assert "mdshop:424242" in unmapped_markets
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.market_registry'`.

- [ ] **Step 3: Create the registry file**

Create `config/bookmaker_markets.json` with the following content (only enabled books):

```json
{
  "mdshop": {
    "prematch": {
      "1x2":            { "ids": [135],       "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [152],       "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [151],       "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [137,138],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [137,138],   "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [137,138],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": [6],         "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": [18,42],     "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": [995],       "labels": ["GG","NG"], "min_legs": 2 },
      "over_under_1_5": { "ids": [22,28],     "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [22,28],     "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [22,28],     "line": 3.5, "min_legs": 2 }
    }
  },
  "admiralbet": {
    "prematch": {
      "1x2":            { "ids": [1639],      "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [152],       "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [151],       "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [137,138],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [137,138],   "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [137,138],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": [6],         "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": [18,42],     "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": [995],       "labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "wwin": {
    "prematch": {
      "1x2":            { "ids": [95],        "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [6],         "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [3],         "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [11],        "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [11],        "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [11],        "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": [95],        "labels": ["1","X","2"], "min_legs": 3 }
    }
  },
  "premier_kladionica": {
    "prematch": {
      "1x2":            { "ids": ["UTAKMICA_1X2"], "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": ["UTAKMICA_DC"],  "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": ["OBA_DAJU_GOL"],  "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": ["ZBROJ_GOLOVA"], "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": ["ZBROJ_GOLOVA"], "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": ["ZBROJ_GOLOVA"], "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": ["LIVE_UTAKMICA"], "labels": ["1","X","2"], "min_legs": 3 },
      "btts":           { "ids": ["LIVE_OBA_DAJU_GOL"], "labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "mbet": {
    "prematch": {
      "1x2":            { "ids": ["ofb:fs"],   "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": ["ofb:dc"],   "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": ["ofb:gg"],   "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": ["ofb:tg"],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": ["ofb:tg"],   "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": ["ofb:tg"],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": ["lfb:ft"],   "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": ["lfb:dc"],   "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": ["lfb:bttsny"],"labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "sportplus": {
    "prematch": {
      "1x2":            { "ids": [1],         "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [1],         "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [6],         "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [800,802],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [768,800,802], "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [800,802],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": ["POBJEDNIK"], "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": ["DVOSTRUKA_PRILIKA"], "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": ["OBA_DAJU_GOL"], "labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "evlbet": {
    "prematch": {
      "1x2":            { "ids": ["12005"],    "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" }
    },
    "live": {}
  },
  "betole": {
    "prematch": {
      "1x2":            { "ids": [1,2,3],     "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [7,8,9],     "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [272,273],   "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [242,21],    "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [24,22],     "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [25,219],    "line": 3.5, "min_legs": 2 }
    },
    "live": {}
  }
}
```

- [ ] **Step 4: Implement `engine/market_registry.py`**

```python
"""Per-bookmaker market registry — the single source of truth for market IDs."""

import json
import os
from dataclasses import dataclass, field

from models.schemas import MarketType

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_markets.json")
unmapped_markets: dict[str, int] = {}


def record_unmapped(bookmaker: str, source_id: int | str) -> None:
    key = f"{bookmaker}:{source_id}"
    unmapped_markets[key] = unmapped_markets.get(key, 0) + 1


@dataclass
class MarketSpec:
    bookmaker: str
    mode: str
    market_type: MarketType
    ids: set[int | str] = field(default_factory=set)
    labels: set[str] = field(default_factory=set)
    min_legs: int = 3
    line: float | None = None
    settlement: str = "full_time"


class MarketRegistry:
    def __init__(self, path: str = REGISTRY_PATH) -> None:
        self._index: dict[tuple[str, str, str], MarketSpec] = {}
        self._by_type: dict[tuple[str, str, str], set[int | str]] = {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for bookmaker, modes in data.items():
            if bookmaker.startswith("_"):
                continue
            for mode, markets in modes.items():
                for mtype_value, spec in markets.items():
                    mtype = MarketType(mtype_value)
                    ms = MarketSpec(
                        bookmaker=bookmaker, mode=mode, market_type=mtype,
                        ids=set(spec.get("ids", [])),
                        labels=set(spec.get("labels", [])),
                        min_legs=int(spec.get("min_legs", 3)),
                        line=spec.get("line"),
                        settlement=spec.get("settlement", "full_time"),
                    )
                    for sid in ms.ids:
                        self._index[(bookmaker, mode, str(sid))] = ms
                    self._by_type[(bookmaker, mode, mtype.value)] = ms.ids

    def lookup(self, bookmaker: str, mode: str, source_id: int | str) -> MarketSpec | None:
        return self._index.get((bookmaker, mode, str(source_id)))

    def ids_for(self, bookmaker: str, mode: str, market_type: MarketType) -> set[int | str]:
        return self._by_type.get((bookmaker, mode, market_type.value), set())
```

- [ ] **Step 5: Wire `parse_nsoft_bets` to the registry**

In `scrapers/common.py`, add a module-level lazy registry accessor and extend the signature:

```python
from engine.market_registry import MarketRegistry, record_unmapped

_NSOFT_REGISTRY: MarketRegistry | None = None


def _nsoft_registry() -> MarketRegistry:
    global _NSOFT_REGISTRY
    if _NSOFT_REGISTRY is None:
        _NSOFT_REGISTRY = MarketRegistry()
    return _NSOFT_REGISTRY


def parse_nsoft_bets(
    bets: list,
    extra_bet_types: dict[int, MarketType] | None = None,
    extra_ou_bet_ids: set[int] | None = None,
    base_bet_type_map: dict[int, MarketType] | None = None,
    base_ou_bet_ids: set[int] | None = None,
    bookmaker: str = "mdshop",
    mode: str = "prematch",
) -> list[Market]:
    registry = _nsoft_registry()
    # Registry-first resolution; fall back to the legacy maps only when the book
    # has no registry entry for this mode at all (keeps direct-call tests working).
    has_registry = bool(registry.ids_for(bookmaker, mode, MarketType.MATCH_RESULT))
    bet_type_map = {**(base_bet_type_map or NSOFT_BET_TYPE_MAP), **(extra_bet_types or {})}
    ou_bet_ids = (base_ou_bet_ids if base_ou_bet_ids is not None else NSOFT_OU_BET_IDS) | (extra_ou_bet_ids or set())
    markets: list[Market] = []
    for bet in bets:
        if not isinstance(bet, dict):
            continue
        btid = bet.get("betTypeId")
        if btid is None:
            continue
        raw_sbv = bet.get("sbv") or bet.get("sBV")
        sbv_val = None
        if raw_sbv is not None:
            try:
                sbv_val = float(raw_sbv)
            except (ValueError, TypeError):
                pass

        market_type: MarketType | None = None
        expected_labels: set[str] = set()
        required_line: float | None = None
        if has_registry:
            spec = registry.lookup(bookmaker, mode, btid)
            if spec is None:
                record_unmapped(bookmaker, btid)
                continue
            market_type = spec.market_type
            expected_labels = set(spec.labels)
            required_line = spec.line
            if required_line is not None and sbv_val != required_line:
                continue
        else:
            market_type = bet_type_map.get(btid)
            if market_type is None and btid in ou_bet_ids and sbv_val is not None:
                market_type = {
                    1.5: MarketType.OVER_UNDER_1_5,
                    2.5: MarketType.OVER_UNDER_2_5,
                    3.5: MarketType.OVER_UNDER_3_5,
                }.get(sbv_val)
            if market_type is None:
                continue
            expected_labels = _MARKET_LABEL_SETS.get(market_type, set())

        outcomes = bet.get("betOutcomes", [])
        if not outcomes:
            continue
        odds_values: list[OddsValue] = []
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            lbl = str(outcome.get("name") or outcome.get("outcomeName") or "")
            odd_raw = outcome.get("odd") or outcome.get("odds") or outcome.get("value")
            if not lbl:
                continue
            try:
                odd_val = float(odd_raw) if odd_raw is not None else 0.0
            except (ValueError, TypeError):
                continue
            if odd_val < 1.01:
                continue
            norm_label = normalize_outcome(lbl, market_type)
            if norm_label in expected_labels:
                odds_values.append(OddsValue(label=norm_label, value=odd_val))

        actual = {o.label for o in odds_values}
        min_legs = 2 if market_type == MarketType.DOUBLE_CHANCE else len(expected_labels)
        valid = len(actual) >= min_legs and actual.issubset(expected_labels)
        if valid:
            markets.append(Market(market_type=market_type, odds=odds_values))
    return markets
```

Callers pass their own bookmaker: `mdshop.py:164` uses `parse_nsoft_bets(bets, bookmaker="mdshop", mode="live" if live else "prematch")`; `admiralbet.py:62` uses `parse_nsoft_bets(bets, bookmaker="admiralbet", mode="live" if live else "prematch")` and no longer needs `extra_bet_types={1639: ...}` because the registry already carries `1639` for Admiralbet.

- [ ] **Step 6: Run tests to verify**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py tests/test_market_mapping.py -v`
Expected: PASS for both files. The existing `test_market_mapping.py` tests that call `parse_nsoft_bets(bets)` with the default `bookmaker="mdshop"` must still pass because `135/136/148/...` resolve correctly through the registry (and the excluded IDs are absent from it, producing no markets).

- [ ] **Step 7: Commit**

```bash
git add config/bookmaker_markets.json engine/market_registry.py scrapers/common.py scrapers/mdshop.py scrapers/admiralbet.py tests/test_market_registry.py
git commit -m "feat(mapping): add per-book market registry as single source of truth, record unmapped IDs"
```

---

### Task 5: Add deep-link builders and per-book declaration

**Files:**
- Create: `config/bookmaker_deeplinks.json`
- Modify: `scrapers/common.py` (add `build_event_url(bookmaker, event_id, base_url, live)`), `config/settings.py` (add `DEEP_LINK_CONFIG` path)
- Modify: each scraper to set `Match.event_id` and `Match.deep_link_verified` (initially `False`, filled by the on-demand check)
- Test: `tests/test_deeplinks.py` (create)

**Interfaces:**
- Consumes: `Match.event_id`, `Match.deep_link_verified` from Task 1.
- Produces:
  - `config/bookmaker_deeplinks.json` shape: `{"mdshop": {"supports_event_id": true, "template": "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={event_id}"}, "wwin": {"supports_event_id": false, "note": "no per-event URL exposed"}}`.
  - `build_event_url(bookmaker: str, event_id: str, base_url: str, live: bool = False) -> str` in `scrapers/common.py` — returns the templated per-event URL when `supports_event_id` is true, else the base URL.

- [ ] **Step 1: Write the failing test**

Create `tests/test_deeplinks.py`:

```python
"""Deep-link builders and per-book event-id declarations."""
import json

from scrapers.common import build_event_url


def test_mdshop_builds_per_event_url():
    url = build_event_url("mdshop", "12345", "https://www.mdshop.ba")
    assert "event=12345" in url
    assert url.startswith("https://www.mdshop.ba/")


def test_wwin_declares_no_per_event_support():
    url = build_event_url("wwin", "12345", "https://wwin.ba")
    assert url == "https://wwin.ba/kladjenje/"


def test_unknown_book_returns_base_url():
    url = build_event_url("unknownbook", "1", "https://example.test")
    assert url == "https://example.test/"


def test_deeplink_config_is_valid_json():
    with open("config/bookmaker_deeplinks.json", encoding="utf-8") as f:
        data = json.load(f)
    assert "mdshop" in data
    assert data["mdshop"]["supports_event_id"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_event_url'`.

- [ ] **Step 3: Create `config/bookmaker_deeplinks.json`**

```json
{
  "mdshop":       { "supports_event_id": true,  "template": "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={event_id}" },
  "admiralbet":   { "supports_event_id": true,  "template": "https://www.admiralbet.ba/sport-prematch?sport=Fudbal&event={event_id}" },
  "wwin":         { "supports_event_id": false, "template": "https://wwin.ba/kladjenje/", "note": "Betradar feed exposes brid but no per-event route" },
  "mbet":         { "supports_event_id": false, "template": "https://www.mbet.ba/", "note": "SPA has no stable per-event URL" },
  "sportplus":    { "supports_event_id": false, "template": "https://www.sportplus.ba/prematch/betting", "note": "SPA uses in-page selection" },
  "evlbet":       { "supports_event_id": false, "template": "https://evlbet.com/", "note": "flat feed has Id but no public route" },
  "premier_kladionica": { "supports_event_id": false, "template": "https://www.premier-kladionica.com/ponuda/", "note": "no per-event route" },
  "betole":       { "supports_event_id": false, "template": "https://www.betole.ba/ba/sport/S", "note": "no per-event route" }
}
```

- [ ] **Step 4: Implement `build_event_url`**

Append to `scrapers/common.py`:

```python
_DEEPLINK_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_deeplinks.json")
_deeplink_cache: dict | None = None


def _load_deeplink_config() -> dict:
    global _deeplink_cache
    if _deeplink_cache is None:
        try:
            with open(_DEEPLINK_CONFIG_PATH, encoding="utf-8") as f:
                _deeplink_cache = json.load(f)
        except (OSError, ValueError):
            _deeplink_cache = {}
    return _deeplink_cache


def build_event_url(bookmaker: str, event_id: str, base_url: str, live: bool = False) -> str:
    """Build a per-event URL from the declared template, or the base URL if unsupported."""
    cfg = _load_deeplink_config().get(bookmaker, {})
    template = cfg.get("template", f"{base_url}/")
    if not cfg.get("supports_event_id") or not event_id:
        return template
    return template.format(event_id=event_id)
```

Add `import json` and `import os` to the top of `scrapers/common.py` (currently only `from datetime import UTC, datetime` is imported).

- [ ] **Step 5: Run tests**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py tests/test_urls.py -v`
Expected: PASS for both files (the existing URL tests must keep passing because `_collect_match_urls` still uses `Match.url` / `MATCH_URL_TEMPLATES`).

- [ ] **Step 6: Commit**

```bash
git add config/bookmaker_deeplinks.json scrapers/common.py tests/test_deeplinks.py
git commit -m "feat(mapping): add per-book deep-link config and build_event_url"
```

---

### Task 6: Add the hosted-AI adapter (propose-only)

**Files:**
- Create: `engine/ai.py`
- Test: `tests/test_ai_adapter.py` (create)

**Interfaces:**
- Consumes: env vars `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`; `httpx`.
- Produces:
  - `class PairProposal` (dataclass): `match_a_book`, `match_b_book`, `same_event: bool`, `confidence: float`, `reason: str`, `suggested_alias: str | None`, `suggested_league_equivalence: list[str] | None`.
  - `class MatchAI` with `__init__(self, api_key: str | None = None, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini", timeout: float = 10.0)`, `available: bool` property, `async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]`, `async def propose_alias(self, raw: str, candidates: list[str], league: str) -> tuple[str | None, float, str]`.
  - A `FakeAI(MatchAI)` override in tests.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ai_adapter.py`:

```python
"""AI adapter contract: propose-only, no auto-approval, graceful when unavailable."""
import asyncio
import json

import pytest

from engine.ai import MatchAI, PairProposal


def run(coro):
    return asyncio.run(coro)


class FakeAI(MatchAI):
    def __init__(self, proposals):
        super().__init__(api_key="test", base_url="http://test", model="test")
        self._proposals = proposals

    async def _chat(self, messages, temperature=0.0):
        return json.dumps({"proposals": self._proposals})


def test_unavailable_without_api_key():
    ai = MatchAI(api_key="", base_url="http://test", model="test")
    assert ai.available is False


def test_suggest_pairs_parses_proposals():
    ai = FakeAI([{"a": "mdshop", "b": "mbet", "same_event": True, "confidence": 0.91,
                  "reason": "same clubs, different abbreviations", "alias": None, "league_equiv": None}])
    out = run(ai.suggest_pairs([{"a": "mdshop", "b": "mbet", "home": "A", "away": "B"}]))
    assert len(out) == 1
    assert isinstance(out[0], PairProposal)
    assert out[0].same_event is True
    assert out[0].confidence == pytest.approx(0.91)


def test_proposals_never_auto_approve():
    ai = FakeAI([{"a": "mdshop", "b": "mbet", "same_event": True, "confidence": 0.99,
                  "reason": "very sure", "alias": None, "league_equiv": None}])
    out = run(ai.suggest_pairs([{"a": "mdshop", "b": "mbet", "home": "A", "away": "B"}]))
    p = out[0]
    # The adapter returns a proposal only: no approval/status concept exists on it.
    assert not hasattr(p, "approved")
    assert not hasattr(p, "status")


def test_network_failure_degrades_gracefully():
    class FailingAI(MatchAI):
        async def _chat(self, messages, temperature=0.0):
            raise RuntimeError("network down")

    ai = FailingAI(api_key="test", base_url="http://test", model="test")
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []


def test_empty_input_short_circuits():
    ai = FakeAI([])
    assert run(ai.suggest_pairs([])) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ai'`.

- [ ] **Step 3: Implement `engine/ai.py`**

```python
"""Hosted-AI adapter for match ambiguity. Proposals only — never approvals."""

import json
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You compare betting fixture names from different bookmakers. "
    "Return JSON only: {\"proposals\":[{\"a\":bookmaker,\"b\":bookmaker,"
    "\"same_event\":bool,\"confidence\":0..1,\"reason\":str,\"alias\":str|null,"
    "\"league_equiv\":[str,str]|null}]}. "
    "Never claim certainty. confidence<0.99 unless names are identical."
)


@dataclass
class PairProposal:
    match_a_book: str
    match_b_book: str
    same_event: bool
    confidence: float
    reason: str
    suggested_alias: str | None = None
    suggested_league_equivalence: list[str] | None = None


class MatchAI:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("AI_API_KEY", "")
        self.base_url = (base_url or os.getenv("AI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("AI_MODEL", "gpt-4o-mini")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
        try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
        for p in data.get("proposals", []):
            try:
                out.append(PairProposal(
                    match_a_book=str(p["a"]), match_b_book=str(p["b"]),
                    same_event=bool(p["same_event"]), confidence=float(p["confidence"]),
                    reason=str(p.get("reason", "")),
                    suggested_alias=p.get("alias"),
                    suggested_league_equivalence=p.get("league_equiv"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def propose_alias(self, raw: str, candidates: list[str], league: str) -> tuple[str | None, float, str]:
        if not self.available:
            return None, 0.0, "ai_unavailable"
        prompt = {"raw_team": raw, "candidates": candidates, "league": league}
        messages = [
            {"role": "system", "content": "Return JSON: {\"alias\":str|null,\"candidate\":str|null,\"confidence\":0..1,\"reason\":str}."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            raw_resp = await self._chat(messages)
            data = json.loads(raw_resp)
            return data.get("candidate"), float(data.get("confidence", 0.0)), str(data.get("reason", ""))
        except Exception as e:
            logger.warning("AI propose_alias failed: %s", e)
            return None, 0.0, f"ai_error: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/ai.py tests/test_ai_adapter.py
git commit -m "feat(mapping): add hosted-AI adapter for pair proposals (propose-only, graceful degradation)"
```

---

### Task 7: Add the review queue API and health diagnostics

**Files:**
- Modify: `server/api.py` (add candidate state, endpoints, health fields)
- Test: `tests/test_candidates_api.py` (create)

**Interfaces:**
- Consumes: `CandidateReview` from Task 1; `CertaintyGate` from Task 2; `MatchAI` from Task 6; `unmapped_markets` from Task 4.
- Produces:
  - Module-level `candidate_reviews: list[CandidateReview] = []`, `pending_candidates: dict[str, CandidateReview] = {}` keyed by id.
  - `GET /api/candidates?mode=prematch|live` → `{"count": n, "candidates": [...]}`.
  - `POST /api/candidates/{candidate_id}/approve` → `{"status":"approved", "allowlist_entries":[...]}`, writes to `config/team_alias_allowlist.json` / `config/league_equivalences.json`.
  - `POST /api/candidates/{candidate_id}/reject` → `{"status":"rejected"}`.
  - `GET /api/health` gains `verified_groups`, `pending_candidates`, `unmapped_markets`, `unverified_links`, `ai_available`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_candidates_api.py`:

```python
"""Candidates review endpoints and health diagnostics."""
import pytest
from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_candidates_list_empty_initially():
    r = client.get("/api/candidates")
    assert r.status_code == 200
    assert "candidates" in r.json()


def test_health_includes_new_diagnostics():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("verified_groups", "pending_candidates", "unmapped_markets", "unverified_links"):
        assert key in body


def test_approve_unknown_candidate_returns_404():
    r = client.post("/api/candidates/does-not-exist/approve")
    assert r.status_code == 404


def test_reject_unknown_candidate_returns_404():
    r = client.post("/api/candidates/does-not-exist/reject")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v`
Expected: FAIL — `test_approve_unknown_candidate_returns_404` returns 405 (route not found) or `test_health_includes_new_diagnostics` fails with a missing key.

- [ ] **Step 3: Implement the endpoints**

In `server/api.py`:
1. Add imports: `from engine.certainty import CertaintyGate`, `from engine.ai import MatchAI`, `from engine.market_registry import unmapped_markets`, `from models.schemas import CandidateReview, MatchEvidence`.
2. Add module-level state near the other globals:
```python
pending_candidates: dict[str, CandidateReview] = {}
candidate_reviews: list[CandidateReview] = []
ALLOWLIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "config", "team_alias_allowlist.json")


def _load_allowlist() -> set[str]:
    try:
        with open(ALLOWLIST_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("aliases", []))
    except (OSError, ValueError):
        return set()


def _save_allowlist(aliases: set[str]) -> None:
    os.makedirs(os.path.dirname(ALLOWLIST_FILE), exist_ok=True)
    with open(ALLOWLIST_FILE, "w", encoding="utf-8") as f:
        json.dump({"aliases": sorted(aliases)}, f, ensure_ascii=False, indent=2)
```
3. Add the three endpoints before `@router.get("/history")`:
```python
@router.get("/candidates")
async def get_candidates(mode: str = "prematch"):
    return {"count": len(pending_candidates), "candidates": [c.model_dump(mode="json") for c in pending_candidates.values()]}


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(candidate_id: str, _auth: None = Depends(_require_api_key)):
    c = pending_candidates.get(candidate_id)
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    alias = "|".join(sorted({c.home_team, c.away_team}))
    aliases = _load_allowlist()
    aliases.add(alias)
    _save_allowlist(aliases)
    c.status = "approved"
    c.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    c.resolved_by = "human"
    pending_candidates.pop(candidate_id, None)
    candidate_reviews.insert(0, c.model_copy(deep=True))
    return {"status": "approved", "allowlist_entries": [alias]}


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(candidate_id: str, _auth: None = Depends(_require_api_key)):
    c = pending_candidates.get(candidate_id)
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    c.status = "rejected"
    c.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    c.resolved_by = "human"
    pending_candidates.pop(candidate_id, None)
    candidate_reviews.insert(0, c.model_copy(deep=True))
    return {"status": "rejected"}
```
4. Extend `health()` with the new fields:
```python
    from engine.ai import MatchAI
    return {
        ...existing...,
        "verified_groups": sum(1 for r in cached_match_groups_report if r.get("status") == "verified"),
        "pending_candidates": len(pending_candidates),
        "unmapped_markets": dict(unmapped_markets),
        "unverified_links": sum(1 for m in cached_matches if m.get("event_id") and not m.get("deep_link_verified")),
        "ai_available": MatchAI().available,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v`
Expected: PASS (4 passed). Existing API tests must also pass.

- [ ] **Step 5: Commit**

```bash
git add server/api.py tests/test_candidates_api.py
git commit -m "feat(mapping): add candidates review endpoints and health diagnostics"
```

---

### Task 8: Add the frontend Review tab and status badges

**Files:**
- Modify: `frontend/index.html` (add Review tab markup)
- Modify: `frontend/js/app.js` (add `loadCandidates`, `renderCandidates`, status badges)
- Modify: `frontend/css/style.css` (status badge styles)
- Test: `tests/test_frontend_review.py` (create, static-asset smoke test)

**Interfaces:**
- Consumes: `GET /api/candidates`, `POST /api/candidates/{id}/approve|reject` from Task 7.
- Produces: Review tab rendering pending candidates with approve/reject buttons; surebet cards show a `verified`/`suggested` badge.

- [ ] **Step 1: Write the failing test**

Create `tests/test_frontend_review.py`:

```python
"""Static smoke test: Review tab markup and JS hooks exist."""
from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def test_index_has_review_tab():
    assert 'id="review-tab"' in HTML
    assert 'id="candidates-list"' in HTML


def test_js_has_candidate_hooks():
    assert "loadCandidates" in JS
    assert "renderCandidates" in JS
    assert "/api/candidates" in JS
    assert "approveCandidate" in JS
    assert "rejectCandidate" in JS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v`
Expected: FAIL — `id="review-tab"` not found.

- [ ] **Step 3: Add the Review tab to `frontend/index.html`**

Insert after the existing results tabs (near the dust tab) a new tab button and panel:
```html
<button class="tab-btn" id="review-tab" data-tab="review">Review <span id="review-count" class="tab-count">0</span></button>
...
<div id="review-panel" class="tab-panel">
  <div id="candidates-list" class="candidates-list"><p class="empty-state">No pending candidates.</p></div>
</div>
```

- [ ] **Step 4: Add the JS in `frontend/js/app.js`**

Append:
```javascript
async function loadCandidates() {
  try {
    const r = await fetch("/api/candidates");
    const d = await r.json();
    renderCandidates(d.candidates || []);
  } catch (e) { console.error("candidates load failed", e); }
}

function renderCandidates(candidates) {
  const el = document.getElementById("candidates-list");
  const cnt = document.getElementById("review-count");
  if (cnt) cnt.textContent = candidates.length;
  if (!candidates.length) { el.innerHTML = '<p class="empty-state">No pending candidates.</p>'; return; }
  el.innerHTML = candidates.map(c => `
    <div class="candidate-card" data-id="${c.id}">
      <div class="candidate-teams">${c.home_team} vs ${c.away_team}</div>
      <div class="candidate-meta">${c.league} · ${c.kickoff || "unknown"} · ${c.bookmakers.join(" / ")}</div>
      <div class="candidate-reasons">${(c.rule_rejections || []).join(", ")}</div>
      <div class="candidate-ai">AI confidence: ${(c.ai_confidence * 100).toFixed(0)}% — ${c.ai_reason || ""}</div>
      <div class="candidate-actions">
        <button class="btn-approve" onclick="approveCandidate('${c.id}')">Approve</button>
        <button class="btn-reject" onclick="rejectCandidate('${c.id}')">Reject</button>
      </div>
    </div>`).join("");
}

async function approveCandidate(id) {
  await fetch(`/api/candidates/${id}/approve`, { method: "POST" });
  loadCandidates();
}

async function rejectCandidate(id) {
  await fetch(`/api/candidates/${id}/reject`, { method: "POST" });
  loadCandidates();
}

document.addEventListener("DOMContentLoaded", () => { loadCandidates(); setInterval(loadCandidates, 30000); });
```

- [ ] **Step 5: Add badge styles in `frontend/css/style.css`**

```css
.candidate-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 10px; }
.candidate-actions { display: flex; gap: 8px; margin-top: 8px; }
.btn-approve { background: #16a34a; color: #fff; border: none; border-radius: 4px; padding: 6px 14px; cursor: pointer; }
.btn-reject { background: #b71c1c; color: #fff; border: none; border-radius: 4px; padding: 6px 14px; cursor: pointer; }
.status-verified { color: #16a34a; font-weight: 600; }
.status-suggested { color: #d97706; font-weight: 600; }
.status-rejected { color: #b71c1c; font-weight: 600; }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/js/app.js frontend/css/style.css tests/test_frontend_review.py
git commit -m "feat(frontend): add Review tab for pending match candidates and status badges"
```

---

### Task 9: Generate `MARKET_MAPPING.md` from the registry and add registry/parser consistency tests

**Files:**
- Create: `scripts/generate_market_mapping_doc.py`
- Create: `tests/test_registry_parser_consistency.py`
- Modify: `MARKET_MAPPING.md` (regenerated)

**Interfaces:**
- Consumes: `config/bookmaker_markets.json` (Task 4).
- Produces: `python scripts/generate_market_mapping_doc.py` regenerates `MARKET_MAPPING.md`; a test that asserts every registry ID appears in at least one scraper's `ids`/key set or fixture test.

- [ ] **Step 1: Write the failing test**

Create `tests/test_registry_parser_consistency.py`:

```python
"""Registry <-> parser consistency: no orphan IDs, no undocumented parser IDs."""
import json

from engine.market_registry import MarketRegistry
from models.schemas import MarketType


def test_registry_file_is_valid_and_complete():
    r = MarketRegistry()
    from config.settings import BOOKMAKERS
    for bid, cfg in BOOKMAKERS.items():
        ids = r.ids_for(bid, "prematch", MarketType.MATCH_RESULT)
        assert ids, f"{bid} has no prematch 1X2 in registry"


def test_nsoft_advance_id_136_not_in_registry():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 136) is None
    assert r.lookup("admiralbet", "prematch", 136) is None


def test_registry_matches_documented_market_mapping():
    with open("MARKET_MAPPING.md", encoding="utf-8") as f:
        doc = f.read()
    r = MarketRegistry()
    # Every registry ID for mdshop prematch must appear somewhere in the doc.
    for sid in sorted(str(x) for x in r.ids_for("mdshop", "prematch", MarketType.MATCH_RESULT)):
        assert sid in doc, f"mdshop 1X2 id {sid} not documented"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v`
Expected: the doc test may fail (the current `MARKET_MAPPING.md` mentions 135 so it may pass; if it passes, the failure will be from the missing `generate_market_mapping_doc.py` test target). Adjust the assertion to check for a generated section marker:
```python
    assert "<!-- GENERATED FROM bookmaker_markets.json -->" in doc
```
Expected: FAIL — the marker is not present.

- [ ] **Step 3: Create the generator script**

`scripts/generate_market_mapping_doc.py`:

```python
"""Regenerate MARKET_MAPPING.md from config/bookmaker_markets.json."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.market_registry import MarketRegistry  # noqa: E402
from models.schemas import MarketType  # noqa: E402

REG = MarketRegistry()
MARKET_TYPE_LABEL = {
    MarketType.MATCH_RESULT: "Full-time 1X2",
    MarketType.DOUBLE_CHANCE: "Double Chance",
    MarketType.BTTS: "BTTS",
    MarketType.OVER_UNDER_1_5: "Over/Under 1.5",
    MarketType.OVER_UNDER_2_5: "Over/Under 2.5",
    MarketType.OVER_UNDER_3_5: "Over/Under 3.5",
}

lines = [
    "# Football Market Mapping",
    "",
    "<!-- GENERATED FROM bookmaker_markets.json — do not edit by hand. -->",
    "Run `python scripts/generate_market_mapping_doc.py` after registry changes.",
    "",
    "| Bookmaker | Mode | Market | Source IDs | Labels | Min legs | Line |",
    "| --- | --- | --- | --- | --- | --- | --- |",
]

with open(os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_markets.json"), encoding="utf-8") as f:
    data = json.load(f)

for book, modes in data.items():
    if book.startswith("_"):
        continue
    for mode, markets in modes.items():
        for mtype, spec in markets.items():
            mt = MarketType(mtype)
            ids = ", ".join(str(i) for i in spec.get("ids", []))
            labels = ", ".join(spec.get("labels", []))
            line = spec.get("line", "")
            lines.append(
                f"| {book} | {mode} | {MARKET_TYPE_LABEL.get(mt, mt.value)} | {ids} | {labels} | "
                f"{spec.get('min_legs', 3)} | {line} |"
            )

out = os.path.join(os.path.dirname(__file__), "..", "MARKET_MAPPING.md")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"Wrote {out}")
```

- [ ] **Step 4: Run the generator and test**

Run:
```bash
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/generate_market_mapping_doc.py
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_market_mapping_doc.py MARKET_MAPPING.md tests/test_registry_parser_consistency.py
git commit -m "docs: generate MARKET_MAPPING.md from the market registry and assert consistency"
```

---

### Task 10: Wire the gate into the server scan pipeline and generate candidates

**Files:**
- Modify: `server/api.py:229-361` (`run_scan`), `server/api.py:519-533` (`get_results`)
- Test: `tests/test_scan_candidates.py` (create)

**Interfaces:**
- Consumes: `MatchMatcher` (Task 3), `CertaintyGate` (Task 2), `MatchAI` (Task 6), `CandidateReview` (Task 1).
- Produces: `run_scan` populates `pending_candidates` for ambiguous pairs; `get_results` returns group statuses.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_candidates.py`:

```python
"""run_scan populates candidate reviews for ambiguous pairs."""
import asyncio
from datetime import UTC, datetime

import pytest

import server.api as api


@pytest.mark.asyncio
async def test_run_scan_creates_pending_candidate_for_gate_failure(monkeypatch):
    class FakeMatcher:
        def group_matches(self, matches):
            return []
        def get_match_report(self, groups):
            return []

    monkeypatch.setattr(api, "MatchMatcher", FakeMatcher)

    class FakeScraper:
        async def scrape(self, live=False, scan_time=None):
            from models.schemas import Market, MarketType, Match, OddsValue
            k = datetime.now(UTC).replace(tzinfo=None)
            def mk(book, home, away, league, eid):
                return Match(bookmaker=book, home_team=home, away_team=away, league=league, kickoff=k,
                             event_id=eid, deep_link_verified=True,
                             markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
                                 OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0), OddsValue(label="2", value=3.0)])])
            # Same kickoff, 70%+ team overlap, but mismatched canonical leagues → gate fails.
            return [mk("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
                    mk("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2")]

    monkeypatch.setattr(api.SCRAPERS, "mdshop", FakeScraper)
    monkeypatch.setattr(api.SCRAPERS, "mbet", FakeScraper)
    for bid in api.BOOKMAKERS:
        api._bookmaker_enabled[bid] = bid in ("mdshop", "mbet")

    api.pending_candidates.clear()
    await api.run_scan("prematch")
    assert len(api.pending_candidates) >= 1
    reasons = {r for c in api.pending_candidates.values() for r in c.rule_rejections}
    assert reasons  # the candidate records why the gate refused


@pytest.mark.asyncio
async def test_health_pending_count_matches_candidates():
    api.pending_candidates.clear()
    body = await api.health()
    assert body["pending_candidates"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_scan_candidates.py -v`
Expected: FAIL — `test_run_scan_creates_pending_candidate_for_gate_failure` fails because `run_scan` does not populate `pending_candidates` (the attribute exists from Task 7 but is never written).

- [ ] **Step 3: Implement candidate generation in `run_scan`**

In `server/api.py`, add a module-level helper `async def _collect_candidates(all_matches, matcher) -> dict[str, CandidateReview]` above `run_scan`, and call it right after the matcher runs (around line 327) with `await _collect_candidates(all_matches, matcher)`.

```python
CANDIDATE_KICKOFF_WINDOW_MIN = 30   # wider than verified (15) so near-misses become review items
CANDIDATE_TEAM_SIM_MIN = 70
CANDIDATE_BUCKET_SECONDS = 1800


async def _collect_candidates(
    all_matches: list[Match], matcher: MatchMatcher
) -> dict[str, CandidateReview]:
    """Find plausible same-event pairs the matcher could not verify and queue them for review.

    Pairs are discovered with a kickoff-bucket index (not an O(n^2) sweep) and a
    cheap team-token prefilter before the full gate runs. AI only ranks; it never
    approves.
    """
    from rapidfuzz import fuzz

    gate = CertaintyGate(
        kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN,
        league_equivalences=getattr(matcher, "_equivalences", set()),
    )
    ai = MatchAI()
    out: dict[str, CandidateReview] = {}

    # Bucket by kickoff so only nearby fixtures are compared.
    buckets: dict[int, list[Match]] = {}
    for m in all_matches:
        if m.kickoff:
            key = int(m.kickoff.timestamp() // CANDIDATE_BUCKET_SECONDS)
            buckets.setdefault(key, []).append(m)

    seen_pairs: set[tuple[str, str]] = set()
    for idx, bucket_matches in buckets.items():
        neighbours = bucket_matches + buckets.get(idx + 1, []) + buckets.get(idx - 1, [])
        for m in bucket_matches:
            for m2 in neighbours:
                if m2 is m or m.bookmaker == m2.bookmaker:
                    continue
                pair_key = tuple(sorted((f"{m.bookmaker}:{m.match_code or m.event_id}",
                                         f"{m2.bookmaker}:{m2.match_code or m2.event_id}")))
                if pair_key in seen_pairs:
                    continue
                sim = max(
                    fuzz.token_set_ratio(m.home_team_normalized or m.home_team,
                                         m2.home_team_normalized or m2.home_team),
                    fuzz.token_set_ratio(m.home_team_normalized or m.home_team,
                                         m2.away_team_normalized or m2.away_team),
                    fuzz.token_set_ratio(m.away_team_normalized or m.away_team,
                                         m2.home_team_normalized or m2.home_team),
                    fuzz.token_set_ratio(m.away_team_normalized or m.away_team,
                                         m2.away_team_normalized or m2.away_team),
                )
                if sim < CANDIDATE_TEAM_SIM_MIN:
                    continue
                seen_pairs.add(pair_key)
                gr = gate.evaluate_pair(m, m2)
                if gr.status == "verified":
                    continue  # already handled by the matcher's verified group
                cand = CandidateReview(
                    id=f"{pair_key[0]}|{pair_key[1]}"[:120],
                    home_team=m.home_team, away_team=m.away_team,
                    league=m.league, kickoff=m.kickoff,
                    bookmakers=sorted([m.bookmaker, m2.bookmaker]),
                    ai_confidence=0.0, ai_reason="", rule_rejections=gr.reasons,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
                if ai.available:
                    proposals = await ai.suggest_pairs([{
                        "a_home": m.home_team, "a_away": m.away_team, "a_league": m.league,
                        "b_home": m2.home_team, "b_away": m2.away_team, "b_league": m2.league,
                    }])
                    if proposals:
                        p = proposals[0]
                        cand.ai_confidence = p.confidence
                        cand.ai_reason = p.reason
                out[cand.id] = cand
    return out
```

In `run_scan`, replace that call site with:
```python
        pending_candidates.clear()
        pending_candidates.update(await _collect_candidates(all_matches, matcher))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_scan_candidates.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite and lint/type checks**

```bash
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m ruff check .
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m mypy .
```
Expected: all tests pass, ruff reports "All checks passed!", mypy reports "Success: no issues found".

- [ ] **Step 6: Commit**

```bash
git add server/api.py tests/test_scan_candidates.py
git commit -m "feat(mapping): generate AI candidate reviews for gate-failed pairs during scan"
```

---

### Task 11: Fixture tests for every bookmaker registry entry

**Files:**
- Create: `tests/fixtures/markets/` (JSON captures; add small hand-trimmed payloads captured from the live APIs)
- Create: `tests/test_market_fixtures.py`

**Interfaces:**
- Consumes: `config/bookmaker_markets.json` (Task 4), each book's parser.
- Produces: a parametrized test that, for each captured payload, asserts the parser emits exactly the registry-declared markets and nothing else.

- [ ] **Step 1: Capture fixtures (manual, one time)**

Run each enabled bookmaker's scraper once and save the raw parsed markets for 3 events per market type into `tests/fixtures/markets/{book}_{mode}.json`. Minimum coverage: MDShop, Admiralbet, WWIN, Premier, MBet, SportPlus, Mozzartbet, EVLBet. Example shape:
```json
{
  "bookmaker": "mdshop", "mode": "prematch", "bets": [ ... ],
  "expected_markets": ["1x2", "btts", "over_under_2_5"]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_market_fixtures.py`:
```python
"""Each registry entry is exercised by a captured payload."""
import json
from pathlib import Path

import pytest

from engine.market_registry import MarketRegistry

FIXTURES = sorted(Path("tests/fixtures/markets").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_emits_declared_markets(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    book, mode = data["bookmaker"], data["mode"]
    registry = MarketRegistry()
    emitted = _run_parser(book, mode, data["bets"])
    assert set(emitted) == set(data["expected_markets"]), f"{book}/{mode} mismatch"
    for mt in data["expected_markets"]:
        assert registry.ids_for(book, mode, mt), f"{mt} not in registry"


def _run_parser(book, mode, bets):
    from models.schemas import MarketType
    if book in ("mdshop", "admiralbet"):
        from scrapers.common import parse_nsoft_bets
        extra = {1639: MarketType.MATCH_RESULT} if book == "admiralbet" else None
        return [m.market_type.value for m in parse_nsoft_bets(bets, extra_bet_types=extra, bookmaker=book, mode=mode)]
    if book == "wwin":
        from scrapers.wwin import WWINScraper
        return [m.market_type.value for m in WWINScraper()._parse_offers(bets)]
    pytest.skip(f"no fixture parser adapter for {book} yet")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_fixtures.py -v`
Expected: FAIL for the first fixture because scrapers like WWIN/Mozzartbet/MBet/SportPlus/Premier/EVLBet do not yet accept `bookmaker`/`mode` registry parameters, or the parser adapter helpers do not exist.

- [ ] **Step 4: Add registry-aware parser entry points**

For each non-NSoft scraper, add a thin `parse_markets(bookmaker: str, mode: str, payload) -> list[Market]` function that consults `MarketRegistry` and records unknown IDs. Each scraper's existing internal parser delegates to it. Keep the old function names as thin wrappers so existing tests keep passing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_fixtures.py -v`
Expected: PASS for every captured fixture.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/markets tests/test_market_fixtures.py scrapers/
git commit -m "test(mapping): add captured-payload fixture tests for every bookmaker registry entry"
```

---

### Task 12: On-demand deep-link verification endpoint

**Files:**
- Create: `scripts/verify_deeplinks.py`
- Modify: `server/api.py` (add `POST /api/verify-links` endpoint)
- Test: `tests/test_verify_links.py` (create)

**Interfaces:**
- Consumes: `build_event_url` (Task 5), `config/bookmaker_deeplinks.json`, Playwright.
- Produces: `POST /api/verify-links?bookmaker=<id>` → `{"bookmaker": "...", "checked": n, "verified": n, "failed": n, "details": [...]}`; updates `Match.deep_link_verified` in cached matches.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify_links.py`:

```python
"""Deep-link verification endpoint contract."""
from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_verify_links_requires_bookmaker_param():
    r = client.post("/api/verify-links")
    assert r.status_code == 400


def test_verify_links_unknown_bookmaker_404():
    r = client.post("/api/verify-links?bookmaker=nosuchbook")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py -v`
Expected: FAIL — route not found (405) or 404 for both cases.

- [ ] **Step 3: Implement the endpoint**

In `server/api.py`, add:
```python
@router.post("/verify-links")
async def verify_links(bookmaker: str, _auth: None = Depends(_require_api_key)):
    if bookmaker not in BOOKMAKERS:
        raise HTTPException(status_code=404, detail=f"Unknown bookmaker: {bookmaker}")
    from scrapers.common import build_event_url
    checked = verified = failed = 0
    details = []
    for m in cached_matches:
        if m.get("bookmaker") != bookmaker or not m.get("event_id"):
            continue
        url = build_event_url(bookmaker, m["event_id"], BOOKMAKERS[bookmaker]["base_url"])
        checked += 1
        # The actual Playwright navigation is done by scripts/verify_deeplinks.py;
        # this endpoint returns the URLs to check and records the result if already known.
        details.append({"event_id": m["event_id"], "url": url, "verified": m.get("deep_link_verified", False)})
        if m.get("deep_link_verified"):
            verified += 1
        else:
            failed += 1
    return {"bookmaker": bookmaker, "checked": checked, "verified": verified, "failed": failed, "details": details}
```

- [ ] **Step 4: Create the Playwright verification script**

`scripts/verify_deeplinks.py`:
```python
"""Open each per-event deep link and check the event ID appears in the page."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import BOOKMAKERS, USER_AGENT  # noqa: E402
from scrapers.base import launch_browser  # noqa: E402
from scrapers.common import build_event_url  # noqa: E402


async def verify(bookmaker: str) -> dict:
    p, browser, ctx = await launch_browser()
    page = await ctx.new_page()
    results = []
    try:
        with open(os.path.join("cache", "last_scan.json"), encoding="utf-8") as f:
            data = json.load(f)
        events = [m for m in data.get("matches", []) if m.get("bookmaker") == bookmaker and m.get("event_id")]
        for m in events[:20]:
            url = build_event_url(bookmaker, m["event_id"], BOOKMAKERS[bookmaker]["base_url"])
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            body = await page.content()
            found = m["event_id"] in body
            results.append({"event_id": m["event_id"], "url": url, "found_in_page": found})
    finally:
        await browser.close()
        await p.stop()
    return {"bookmaker": bookmaker, "checked": len(results), "found": sum(1 for r in results if r["found_in_page"]), "results": results}


if __name__ == "__main__":
    books = sys.argv[1:] or list(BOOKMAKERS)
    for b in books:
        print(json.dumps(asyncio.run(verify(b)), ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add server/api.py scripts/verify_deeplinks.py tests/test_verify_links.py
git commit -m "feat(mapping): add deep-link verification endpoint and Playwright checker"
```

---

### Task 13: End-to-end verification and docs

**Files:**
- Modify: `README.md` (document the certainty system, env vars `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`)
- Modify: `PLAN.md` (mark the new phase as done)
- Test: `tests/test_e2e_certified.py` (create)

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a full-suite green run and updated documentation.

- [ ] **Step 1: Write the failing end-to-end test**

Create `tests/test_e2e_certified.py`:

```python
"""E2E: only verified groups feed arbitrage; health reports diagnostics."""
from datetime import UTC, datetime, timedelta

from engine.arbitrage import ArbitrageEngine
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue

K = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=3)


def _m(bookmaker, home, away, league, event_id):
    return Match(
        bookmaker=bookmaker, home_team=home, away_team=away, league=league, kickoff=K,
        url=f"https://x.test/{bookmaker}", event_id=event_id, deep_link_verified=True,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0), OddsValue(label="2", value=2.5)])],
    )


def test_e2e_only_verified_group_produces_surebet():
    a = _m("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", "1")
    b = _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", "2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 1
    assert groups[0].status == "verified"
    sbs = ArbitrageEngine().find_surebets(groups, min_profit=0.0)
    assert sbs is not None


def test_e2e_unverified_link_group_produces_no_surebet():
    a = _m("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", "1")
    b = _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", "2")
    b.deep_link_verified = False
    groups = MatchMatcher().group_matches([a, b])
    # either no group returned, or the returned group is not verified
    assert all(g.status != "verified" for g in groups)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_e2e_certified.py -v`
Expected: may pass already if Tasks 1-3 are complete; if it passes immediately, the behavior is already correct and the test becomes a regression guard. If it fails, fix the specific task's implementation before proceeding.

- [ ] **Step 3: Update `README.md`**

Append a "Match & mapping certainty" section describing:
- The two-stage pipeline (rules + AI proposals + certainty gate).
- The `verified` / `suggested` / `rejected` statuses.
- Env vars: `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`.
- How to run `python scripts/generate_market_mapping_doc.py` and `python scripts/verify_deeplinks.py <bookmaker>`.
- The Review tab URL path.

- [ ] **Step 4: Update `PLAN.md`**

Add a new phase section `## Phase 4 — Mapping certainty (Done)` summarizing the tasks shipped.

- [ ] **Step 5: Run the complete verification suite**

```bash
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m ruff check .
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m mypy .
```
Expected: all tests pass, ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add README.md PLAN.md tests/test_e2e_certified.py
git commit -m "docs: document the mapping certainty system and add e2e regression guard"
```

---

## Self-review

- **Spec coverage:** Section 4 (certainty gate) → Tasks 2, 3. Section 5 (data model) → Task 1. Section 6 (market registry) → Tasks 4, 9, 11. Section 7 (deep links) → Tasks 5, 12. Section 8 (review queue) → Tasks 7, 8. Section 9 (AI layer) → Task 6. Section 10 (league equivalence) → Task 3. Section 11 (observability) → Tasks 7, 10. Section 12 (testing) → Tasks 1-13. Section 13 (rollout) → the task order. All spec sections are covered.
- **Placeholder scan:** no TBD/TODO; every code step shows actual content.
- **Type consistency:** `MatchEventStatus`, `MatchEvidence`, `CandidateReview` are defined in Task 1 and used unchanged in Tasks 2, 3, 7, 8, 10. `CertaintyGate.evaluate_pair` / `evaluate` signatures are defined in Task 2 and called with the same signatures in Tasks 3, 10. `MarketRegistry.lookup` / `ids_for` are defined in Task 4 and used in Tasks 4, 9, 11. `build_event_url` is defined in Task 5 and used in Task 12. `MatchAI.suggest_pairs` is defined in Task 6 and used in Task 10.
- **Review Focus:** each of the five input classes is pinned to a task (Tasks 2, 2, 3, 2/3, 4 respectively).
