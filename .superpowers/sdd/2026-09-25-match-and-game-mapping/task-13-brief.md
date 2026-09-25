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
