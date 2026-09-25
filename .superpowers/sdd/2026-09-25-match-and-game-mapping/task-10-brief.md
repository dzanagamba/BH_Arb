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

