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

