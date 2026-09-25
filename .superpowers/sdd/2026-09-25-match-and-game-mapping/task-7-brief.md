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

