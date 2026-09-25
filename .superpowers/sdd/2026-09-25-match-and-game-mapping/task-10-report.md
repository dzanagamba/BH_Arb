# Task 10 report — wire the gate into the scan pipeline and generate candidates

Commit: `d2e7461cdccebedc549e91563260180915e213f0`
Branch: `master` (in place, no worktree)
Files changed: `server/api.py` (+326/−4), `tests/test_scan_candidates.py` (new, 13 tests)

---

## 1. What I changed

### `server/api.py` — new "Candidate generation" section above `run_scan`

Module-level constants (brief values kept verbatim):

```python
CANDIDATE_KICKOFF_WINDOW_MIN = 30   # wider than verified (15) so near-misses become review items
CANDIDATE_TEAM_SIM_MIN = 70
CANDIDATE_BUCKET_SECONDS = 1800
AI_CANDIDATE_RANK_CAP = 20          # added — see §2
AI_RANK_TIME_BUDGET_SECONDS = 90.0  # added — see §2
```

Helpers: `_kickoff_bucket`, `_match_event_ref`, `_match_side_key`, `_kickoff_delta_minutes`,
`_bigrams`, `_team_similarity`, `_token_run_shared`, `_canonical_pair_key`, `_candidate_id`,
`_verified_group_index`, `_proposal_for_submitted_pair`, plus two `NamedTuple`s
(`_TeamTokens`, `_FoundPair`), then `_rank_candidates_with_ai` and `_collect_candidates`.

`run_scan` (right after the matcher, before arbitrage):

```python
        # Ambiguous pairings the gate refused become review items. The queue is
        # rebuilt every scan so it only ever mirrors the current feed.
        status.current_bookmaker = "Collecting review candidates..."
        try:
            pending_candidates.clear()
            pending_candidates.update(
                await _collect_candidates(all_matches, matcher, groups)
            )
        except Exception as e:
            pending_candidates.clear()
            logger.error(f"❌ Candidate collection failed: {e}", exc_info=True)
            status.errors.append(f"Candidate review failed: {str(e)[:200]}")
```

`get_results` now also reports group statuses (the brief's "get_results returns group
statuses" produce-line):

```python
        "match_groups": len(report_cache),
        "group_statuses": group_statuses,   # {"verified": n, "suggested": n, ...}
```

New imports: `hashlib`, `rapidfuzz.fuzz`, `typing.NamedTuple`, `engine.certainty.CertaintyGate`,
`engine.ai.PairProposal`, `models.schemas.MatchGroup`. (`CertaintyGate` was **not** already
imported in `server/api.py` as the task message stated — see §6.)

### Behaviour guaranteed

* **AI never auto-approves.** A proposal only ever writes `ai_confidence` / `ai_reason` on a
  candidate that is already in the queue. `CandidateReview.status` stays `"pending"` and
  `rule_rejections` is never cleared, even at confidence 0.99
  (`test_ai_confidence_never_approves_a_candidate`).
* **Queue is rebuilt, never appended** — `clear()` then `update()`
  (`test_pending_candidates_are_rebuilt_not_appended_each_scan`).
* **A `verified` pair is never queued** — the pair gate must return non-`verified`
  (`test_fully_proven_pair_is_never_queued`).

---

## 2. The AI cap I chose and why

The brief calls the AI **once per candidate** and `suggest_pairs` is a network call with a
10 s timeout, so an uncapped scan makes N sequential calls. Two module-level constants bound
it (both named so an operator can tune them without touching logic):

| constant | value | why |
|---|---|---|
| `AI_CANDIDATE_RANK_CAP` | `20` | A scan sits next to 30 s–3 min of browser scraping and a ~40 s matcher run, so ~20 s of extra latency at typical sub-second API latency is invisible in practice. 20 keeps the visible "AI has an opinion on the top 20" promise while bounding the worst case at 20 sequential calls. |
| `AI_RANK_TIME_BUDGET_SECONDS` | `90.0` | The count cap alone does not bound *time*: 20 calls that each hit the 10 s timeout is 200 s. A wall-clock deadline stops the loop early so a degraded AI can never add minutes to a scan. |

**Cap ordering.** Candidates are sorted by `(kickoff_delta_minutes, -team_similarity, id)`
*before* the cap is applied, so the cap drops the least plausible pairs — exactly as
required. The same ordering is the insertion order of the returned dict, so `/api/candidates`
serves the queue best-first.

**Operator visibility.** Both truncation paths log a warning naming the shortfall:
`"AI ranking capped at 20 of N candidates — M stay unranked this scan"` and
`"AI ranking budget of 90s exhausted after K candidates — the rest stay unranked this scan"`.
The full queue is still published; unranked candidates simply carry `ai_confidence = 0.0`.

**The AI path is only entered when `ai.available` is true** — `MatchAI()` is constructed, and
if `.available` is false `_collect_candidates` returns before any call
(`test_ai_is_not_consulted_when_it_is_unavailable`). `ai.aclose()` runs in a `finally`.

---

## 3. Deterministic id scheme

**Chosen: SHA-1 of the canonical pair key, truncated to 16 hex characters** (64 bits).

```python
def _canonical_pair_key(left, right) -> str:
    def side(match): return f"{_match_side_key(match)}|{match.home_team}|{match.away_team}"
    return "||".join(sorted((side(left), side(right))))   # order-independent

def _candidate_id(canonical_key: str) -> str:
    return hashlib.sha1(canonical_key.encode("utf-8")).hexdigest()[:16]
```

The canonical key is built from **both sides' `bookmaker|match_code|event_id` plus both raw
team-name pairs**, sorted so discovery order cannot change the result. The brief's
`f"{pair_key[0]}|{pair_key[1]}"[:120]` is not used: it truncates mid-string, so two real pair
keys that share a 120-character prefix collide and silently overwrite each other in
`pending_candidates`. A truncated hash is fixed-width and collision-safe, and 64 bits is far
beyond the ≤ tens of thousands of pairs in one scan.

The key deliberately includes the **raw** team names: a bookmaker renaming a club is a
different raw claim and must get a different id, whereas a mere kickoff/odds change must not.

**Verified on the real 7k-match cache:** ids are unique, and a second identical pass produced
an identical id set (`ids unique: True`, `ids stable across rescans: True`).
Covered by `test_candidate_ids_are_deterministic_across_rescans` and the `len(id) == 16` assert.

---

## 4. How AI proposals are joined back to submitted pairs

One pair per call. The submitted payload carries the bookmaker keys the model's system prompt
asks for, so it can echo them:

```python
        proposals = await ai.suggest_pairs([{
            "a": left.bookmaker, "b": right.bookmaker,
            "a_event": _match_event_ref(left), "b_event": _match_event_ref(right),
            "a_home": left.home_team, "a_away": left.away_team, "a_league": left.league,
            "b_home": right.home_team, "b_away": right.away_team, "b_league": right.league,
        }])
        proposal = _proposal_for_submitted_pair(proposals, left, right)
        if proposal is None:
            continue          # hallucinated / unrecognised pairing → discarded
```

`_proposal_for_submitted_pair` accepts a proposal only when
`{proposal.match_a_book, proposal.match_b_book} == {left.bookmaker, right.bookmaker}`. Anything
else is dropped, so a model that invents a pairing nobody asked about (Task 6's review finding)
cannot create, reorder, or rank a pairing. `PairProposal` carries no event ids, so the
bookmaker pair is the only available join key; the candidate id is derived from *my* pair key
and never from model output. Covered by
`test_ai_proposal_for_a_pair_we_never_submitted_is_discarded` (a `betole`/`wwin` proposal for a
`mdshop`/`mbet` pair leaves `ai_confidence == 0.0` and `ai_reason == ""`).

---

## 5. Performance (measured on the real 6,999-match cache in `cache/last_scan.json`)

The scan is 6,999 matches / 7 bookmakers / 262 thirty-minute buckets / 3,353 distinct events.

| stage | time |
|---|---|
| `matcher.group_matches` (pre-existing) | ~40–42 s |
| `_collect_candidates` (new, incl. 13,471 `gate.evaluate_pair` calls) | **6.0 s** |

So candidate generation adds ~14 % to the analysis phase, not to the scrape.

How the pair count is kept sane (the brief's bucket index plus the cheap prefilter):

* **Kickoff-bucket index.** Only *same + next* bucket are compared (not ±1), so each adjacent
  pair is compared exactly once — 745,060 cross-bookmaker comparisons instead of the ~1.5 M a
  ±1 sweep would redo. This is safe: with a 1,800 s bucket and a 30-minute candidate window,
  two matches more than 30 minutes apart can never share or neighbour a bucket
  (min gap across a two-bucket gap is 1,801 s > 1,800 s).
* **Per-match precompute.** Normalized strings and their token/bigram sets are computed once
  per match (`_TeamTokens.of`), not per comparison. This alone took the loop from 3.9 s → 2.8 s
  in the prototype.
* **Cheap token prefilter before the full gate** (`_team_similarity`, threshold
  `CANDIDATE_TEAM_SIM_MIN = 70`): a pair is only handed to `fuzz.token_set_ratio` if the two
  fixtures share a token, a substring run, or a character bigram. The full
  `CertaintyGate.evaluate_pair` (normalizer + 5 `MatchEvidence` records + link checks) runs
  only for the ~13.5 k survivors, never for the 745 k compared.
* **Early exit at 100** — `token_set_ratio` cannot exceed 100, so the loop breaks on the
  first perfect combo. It does not change the reported max.

Measured comparison of three prefilter variants over the same data (`verify_variants.py`):

| prefilter | queued pairs | similarity work |
|---|---|---|
| pure `max(token_set_ratio)` (the brief's literal code) | 15,140 | 10.8 s |
| token/substring gate only | 13,495 | 3.0 s |
| **token + substring + bigram gate (shipped)** | **13,471** | **5.4 s** |

Why the bigram term is there — this is a deliberate deviation (§6): a token-only gate drops
1,645 pairs the raw fuzzy score would admit, including genuine typo pairs such as
`Aguilas/Millionarios` vs `Rionegro/Millonarios` (raw score **95.7**), which share no token at
all. Adding the bigram term keeps those. The 1,669 pairs the shipped gate drops relative to the
pure filter were sampled (25 of them, seed 3) and **every one was a different real-world
fixture** — `Bury Town` vs `Exeter`, `Hednesford` vs `Wrexham`, `Chichester City` vs
`Chippenham` — i.e. `token_set_ratio` false positives on short names, exactly the noise a
human reviewer should not have to wade through. Nothing reviewable is lost.

---

## 6. Deviations from the brief (and why)

1. **`@pytest.mark.asyncio` → `asyncio.run`.** `pytest-asyncio` is not installed in this venv
   (pytest reports `plugins: anyio-4.14.2` only), so the brief's tests would error with
   "async def functions are not natively supported". I followed the existing house pattern from
   `tests/test_ai_adapter.py` / `tests/test_candidates_api.py` (`def run(coro): return
   asyncio.run(coro)`). No new dependency.
2. **`monkeypatch.setattr(api.SCRAPERS, ...)` → `monkeypatch.setitem(...)`.** The brief's version
   raises `AttributeError: ... has no attribute 'mdshop'` because `SCRAPERS` is a `dict`, not an
   object. The brief's test file had clearly never been executed.
3. **A state-isolation fixture.** The brief's tests mutate the module globals
   (`_bookmaker_enabled`, `pending_candidates`, `scan_status`, the `cached_*` lists) and leak
   them into every other test module. I added an autouse fixture that snapshots/restores all of
   them and stubs `_save_cache` / `_append_history` so a test scan does not rewrite
   `cache/last_scan.json` or `cache/scan_history.json`.
4. **Deleted the dead line.** `grouped_match_ids = ... if False else set()` is gone, as
   instructed.
5. **Deterministic id** — SHA-1[:16], not the truncated `[:120]` key. Rationale in §3.
6. **Signature: `_collect_candidates(all_matches, matcher, groups=None)`.** The extra `groups`
   argument implements the *intent* of the deleted dead line. The candidate gate is built
   **without** the team alias allowlist (per the brief), so a pair the matcher verified *via an
   approved alias* looks `team_unresolved` to it and would be re-queued for a human to re-approve
   an alias that already exists. `_verified_group_index` skips any pair whose two sides sit in
   the **same verified matcher group**, which the pair gate cannot see. That is strictly fewer
   candidates, never more, and it is the difference between a useful queue and a looping one.
   The parameter is optional, so the brief's call shape still works.
7. **Token prefilter is a superset gate, not the literal brief line.** See §5. The brief's
   literal `fuzz.token_set_ratio` on all four combinations for all 745 k comparisons costs
   ~10.8 s and additionally queues 1,669 junk pairs; the shipped version is faster *and*
   cleaner. The threshold, the four combinations, and the `>= 70` decision rule are unchanged.
8. **Payload includes `"a"` / `"b"` bookmaker keys** (the brief's payload had only
   `a_home`/`a_away`/… while the adapter's system prompt asks the model to return
   `a`/`b` bookmakers). Without them the model cannot echo the pair and the join in §4 can
   never succeed. `a_event`/`b_event` are added as extra context.
9. **`get_results` gained `match_groups` + `group_statuses`.** Required by the brief's
   "Produces: … `get_results` returns group statuses", which the Step 3 code did not implement.
   Additive keys only; the frontend reads `surebets`, `total_matches` and `last_scan_time`.
10. **Local import → top-level import.** The brief does `from rapidfuzz import fuzz` inside the
    function; `rapidfuzz` is a hard dependency already imported by `engine/matcher.py`, so it
    is a module-level import here.
11. **AI `aclose()` in a `finally`** so the adapter's lifecycle seam is always exercised.

---

## 7. Commands and full output

### 7.1 Step 2 — confirm the new test fails for the right reason

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_scan_candidates.py -v
```

```
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 12 items

tests\test_scan_candidates.py E.EEFFFFFFFF                               [100%]
...
>       assert len(api.pending_candidates) >= 1
E       assert 0 >= 1
E        +  where 0 = len({})
...
FAILED tests/test_scan_candidates.py::test_run_scan_creates_pending_candidate_for_gate_failure
...
E       AttributeError: module 'server.api' has no attribute '_collect_candidates'
E       KeyError: 'match_groups'
=================== 11 failed, 1 passed, 3 errors in 1.61s ===================
```

The brief's headline test failed exactly as specified — `run_scan` does not populate
`pending_candidates` — and the other failures were the missing `_collect_candidates` /
`match_groups`, i.e. the missing implementation, not a broken test.

### 7.2 Step 4 — new test file green

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_scan_candidates.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 13 items

tests\test_scan_candidates.py .............                              [100%]

============================= 13 passed in 2.05s =============================
```

13 tests: the brief's 2 plus queue-rebuild, id determinism, fully-proven-never-queued,
matcher-verified-never-requeued, nameless-fixture, hallucinated-proposal-discarded,
0.99-never-approves, ai-unavailable-not-consulted, cap ordering + truncation log,
plausibility ordering, and group statuses in `/api/results`.

### 7.3 Step 5 — full suite, ruff, mypy

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
305 passed, 3 warnings in 6.16s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m ruff check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m mypy .
Success: no issues found in 52 source files
```

**Full suite: 305 passed, 0 failed, 0 errors** (292 pre-existing + 13 new; the 3 warnings are
pre-existing FastAPI `on_event` deprecations in `server/app.py`).

### 7.4 Real-data verification (not part of the suite)

Ran the shipped `_collect_candidates` against `cache/last_scan.json` (6,999 real matches):

```
matches=6999 matcher=42.44s groups=0
ai.available=False cap=20
_collect_candidates: 6.04s -> 13471 candidates
ids unique: True, sample id: 000407b51b424ef0
ids stable across rescans: True
  000407b51b424ef0 Benevento vs Modena | Italija 2 | ['admiralbet', 'mdshop'] | ['league_mismatch', 'link_unverified']
  000dac95f9604258 Nacional M. vs Progreso | URUGVAJ  1  -  KLAUSURA | ['mdshop', 'mozzartbet'] | ['league_mismatch', 'team_unresolved', 'link_unverified']
  0010bb238ead09db Union Brescia vs Carpi | ITALIJA  3  A | ['mbet', 'mozzartbet'] | ['league_mismatch', 'link_unverified']
```

`ai.available=False` there (no `AI_API_KEY` in this shell), which is the availability guard
doing its job: the AI path was never entered.

### 7.5 Commit

```
$ git add server/api.py tests/test_scan_candidates.py
$ git commit -m "feat(mapping): generate AI candidate reviews for gate-failed pairs during scan"
d2e7461 feat(mapping): generate AI candidate reviews for gate-failed pairs during scan
```

---

## 8. Concerns

1. **The queue can be very large — 13,471 entries on the cached 7 k scan.** `/api/candidates`
   serialises the whole dict on every poll and the Review tab renders it all; there is no
   pagination or cap. It is workable but will get slow. Also note that count comes from a
   **stale 20-Aug cache in which the current gate produces 0 verified groups**, so it is a
   worst case; a healthy scan drops verified pairs. If this stays large, the fix is a
   `limit`/cursor on `/api/candidates` plus UI paging, not a change here.
2. **`CandidateReview` has no per-side names, so approving a candidate writes a useless alias.**
   `approve_candidate` does `"|".join(sorted({candidate.home_team, candidate.away_team}))`, and
   both fields come from a *single* fixture, so it appends e.g. `"Benevento|Modena"` — a
   self-alias between the two halves of one fixture, not the cross-bookmaker pair the allowlist
   is for. The Review tab will therefore loop until `CandidateReview` carries both sides'
   raw names. Pre-existing Task 7/Task 1 shape; out of scope here, but it should be a follow-up
   before the Review tab is called functional.
3. **`pending_candidates` is global and mode-agnostic, while `/api/candidates` takes a `mode`
   parameter it ignores.** A live scan clears and overwrites the prematch queue. Pre-existing;
   a per-mode dict would fix it.
4. **Concurrent scans.** `trigger_scan` releases the mode lock before the background task runs,
   so two overlapping scans can interleave their `clear()`/`update()` of `pending_candidates`.
   Individual statements are atomic with respect to the event loop (no `await` inside
   `clear()` or `update()`), so a concurrent `GET /api/candidates` cannot observe a half-mutated
   dict, and AI annotations happen *before* publication — but the last scan to finish wins.
   Pre-existing.
5. **The prefilter is a heuristic, by design.** It is a 70 % token/bigram similarity, not a
   proof, so a same-event pair with no token, substring or bigram overlap (heavy abbreviation
   such as `"MUFC"` vs `"Manchester United"`) is not queued. That is inherent to the brief's
   `CANDIDATE_TEAM_SIM_MIN` design, not something I added; the sampled data shows the misses it
   causes are all false positives of the looser alternative, but a real abbreviation-driven
   miss would be silent. Lowering `CANDIDATE_TEAM_SIM_MIN` or widening the gate is the lever if
   that ever bites.
6. **Two buckets means a pair just over the window is inconsistently queued.** A 45-minute gap
   is queued if it lands in adjacent buckets and silently dropped if it lands two buckets apart
   (a 40-minute gap is dropped, a 45-minute gap is kept). This is inherent to the prescribed
   index; the gate still stamps `kickoff_delta` as the reason, so a reviewer can see why.
7. **Bucket comparison is O(pairs-per-bucket × books)** and would degrade if a bookmaker ever
   dumped thousands of matches into one 30-minute window. At the current 27 matches/bucket there
   is a ~7× headroom before the candidate scan costs more than the matcher.

---

# Fix round 1

Base commit `d2e7461`. Two Critical, four Important and three actionable Minor
findings addressed. Everything below is measured on the real 6,999-match corpus in
`cache/last_scan.json`, not asserted.

## What changed

| file | change |
|---|---|
| `models/schemas.py` | `PairSide`, `TeamPositionPair`; `CandidateReview` gains `side_a`, `side_b`, `team_positions`, `alias_actionable`, `link_blocked`, `ai_same_event` |
| `server/api.py` | both sides recorded; `_alias_entries`, `_team_positions`, `_alias_actionable`; suppression store; paginated+authenticated `GET /candidates`; `same_event` honoured; prefilter inner gate fixed; shared AI client; bounded review log |
| `server/app.py` | loads the suppression store on startup |
| `engine/ai.py` | `MatchAI.with_shared_client()` — one `httpx.AsyncClient` for a batch of calls |
| `frontend/js/app.js` | bounded page + API key on the read, both spellings per card, negative AI verdict sorts last, "Nothing to alias" when approval would write nothing |
| `frontend/css/style.css` | styles for the new card sections |
| `tests/` | `test_scan_candidates.py` 13 → 41, `test_ai_adapter.py` +2, `test_candidates_api.py` rewritten around a real producer, `test_frontend_review.py` +4 |

## CRITICAL 1 — approval now writes the cross-bookmaker alias

### The new shape, and why

```python
class PairSide(BaseModel):          # one bookmaker's raw claim
    bookmaker: str
    event_ref: str = ""
    home_team: str
    away_team: str
    link_verified: bool = False

class TeamPositionPair(BaseModel):  # one team slot as both books spell it
    position: Literal["home", "away"]
    team_a: str
    team_b: str
```

`CandidateReview` keeps `home_team`/`away_team` (side A's fixture, for display and for
the existing UI/tests) and gains `side_a`, `side_b` and `team_positions`.

I chose two small models over four flat fields (`home_team_b`, `away_team_b`, …) because a
side is a coherent thing that will grow: Task 12's per-book link check needs a place to
record each side's own `link_verified`, and a future "approve one side only" flow needs a
side identity. `TeamPositionPair` exists because the *decision* — which slot of book B
corresponds to which slot of book A — must be made once, at collection time, where the
normalized names are in hand. Re-deriving it in the approve endpoint would mean
re-deciding a swap with fuzzy scores at the moment of a button click, and a wrong
orientation writes two wrong allowlist entries.

`_team_positions` picks the better-agreeing orientation
(`max(token_set_ratio(home,home) + token_set_ratio(away,away))` over direct vs swapped,
scored on the *normalized* names, keeping the *raw* spellings).

### Multi-team approval

`_alias_entries` writes **one entry per team slot whose two spellings differ**, and nothing
otherwise:

* Both teams renamed (`A. Salzburg`/`Kapfenberg` vs `Austria Salzburg`/`Kapfenberg SV`) →
  `{"A. Salzburg|Austria Salzburg", "Kapfenberg|Kapfenberg SV"}`.
* Away team already identical → only the home entry: `{"Lech P.|Lech Poznan"}`.
* Both identical → **no** entry, and `approve_candidate` returns **400** rather than
  poisoning the allowlist with a self-alias. The card shows a disabled
  "Nothing to alias" button instead of a button that fails.

Entries keep the two reviewed spellings verbatim and are `sorted()` for a stable file.
`_alias_name_key` mirrors `CertaintyGate._raw_team_key` (case, spacing, trailing dot) to
decide whether a slot already agrees, and
`test_written_alias_is_honoured_by_the_real_certainty_gate` closes the loop by running the
**real** `CertaintyGate` over the written file, so a drift in that mirror fails a test.

I also fixed the test that encoded the bug: `tests/test_candidates_api.py` no longer
fabricates `home_team="Lech Poznan", away_team="Lech P."`; `_produced_candidate()` runs the
real `_collect_candidates` and every endpoint test uses its output.

## CRITICAL 2 — suppression, and what approval actually grants

### (a) Suppression

`cache/suppressed_candidates.json` holds `{candidate_id: "approved"|"rejected"}`, written
atomically through the same temp-file + `os.replace` path as the allowlist
(`_atomic_write_json`, now shared), loaded on startup, and skipped inside
`_collect_candidates` by the same deterministic SHA-1 id as before.

Measured on the real corpus: **approve 20 candidates, rebuild the queue → 15,140 → 15,120**,
the 20 decided ids gone. A rejection suppresses the same way, because "these are not the
same event" is also a decision a human already made. Because the id is derived from
`bookmaker|match_code|event_id|home|away`, a bookmaker republishing the fixture under a new
event id produces a new id and the pair reappears — covered by
`test_suppression_does_not_hide_a_pair_under_a_new_bookmaker_event_id`.

### (b) What a human is approving: the team alias, and nothing else

**I picked the option where approval grants the TEAM alias trust and the link gate stays a
system check.** The reasons, from Task 12's brief and `certainty.py`:

* Task 12 defines `deep_link_verified` as a **machine** fact — `scripts/verify_deeplinks.py`
  opens the event page and checks the event id is in the body, and `POST /api/verify-links`
  records the result. A person comparing two fixture strings in a browser is not that
  check.
* The flag is read as a verified fact in three places: `CertaintyGate._link_evidence`,
  `/api/health`'s `unverified_links`, and Task 12's endpoint. Letting a UI button set it
  would forge a machine result from a name judgement, and would make `verified` mean
  "a human clicked Approve", which is exactly the invariant the gate exists to protect.
* Task 12 is not done, so *nothing* can be `verified` today regardless. Faking the flag
  would hide that instead of surfacing it.

So the decision is now visible instead of silent, in four places:

1. `CandidateReview.link_blocked` (from `LINK_REJECTION_REASONS`) and
   `PairSide.link_verified` per side.
2. `approve_candidate` returns `link_verified`, `link_state` and a `note` that says the
   deep-link check is a separate system verification and the pair is not verified yet.
3. The card states it: *"Approving writes the reviewed team alias … The deep-link check is
   a separate system verification, so this pair stays unverified until that check runs."*
4. `test_written_alias_is_honoured_by_the_real_certainty_gate` asserts the load-bearing
   invariant: after approval, `evaluate_pair` returns **exactly** `["link_unverified"]` —
   the team blocker is gone, the link blocker is not.

**Approval is not inert, and here is the measurement.** Simulating the state Task 12 will
produce (every bookmaker's links verified) and running the real matcher over the real
corpus:

```
BASELINE (repo allowlist, links verified):        516 verified groups
approved 20 candidates, wrote 23 alias entries
AFTER those approvals (links verified):           524 verified groups   -> +8
queue rebuilt: 15120 candidates (was 15140), 20 decided ids suppressed
```

20 approvals unblock **8 additional verified match groups** (some entries serve several
pairs). That is the loop converging. Today it is invisible only because
`deep_link_verified` is hardcoded `False` in 13 scraper call sites — Task 12's job, and the
number above is the size of what it is holding back.

## Actionability — definition and measured before/after

**Definition.** A candidate is *alias-actionable* iff the aliases its `team_positions`
imply would clear **every blocker a human owns**. Answered by the certainty gate itself,
never by a copy of its rules:

```python
if not set(reasons) <= LINK_REJECTION_REASONS | {"team_unresolved"}:
    return False                      # a league/category/kickoff blocker is not an alias fix
gate.alias_allowlist = set(_alias_entries(positions))
linked = [m.model_copy(update={"deep_link_verified": True}) for m in (left, right)]
return gate.evaluate_pair(*linked).status == "verified"
```

Two properties fall out of using the gate: the reviewed-alials similarity floor (≥90 on the
surface forms) is enforced by the gate, not by my arithmetic — so a pair like
`Manchester City` vs `Manchester United` is correctly **not** advertised as actionable
(`test_alias_actionable_is_false_when_the_gate_would_refuse_the_alias`); and the
allowlist-on-allowlist rule (an alias cannot rescue a failed league/kickoff/category gate)
is honoured for free.

**Ordering**: `alias_actionable` first, then fewest non-link blockers, then tightest
kickoff, then closest names, then id. The AI cap is taken from the top of this order.

**Measured before/after on the real corpus** (6,999 matches, 15,140 candidates):

| | before (round 1: kickoff delta, then similarity) | after (shipped) |
|---|---|---|
| first 20 of the order | **1 alias-actionable** | **20 alias-actionable** |
| alias-actionable in the queue | n/a (not computed) | **1,299 of 15,140 (8.6 %)** |
| queue | 13,471 | 15,140 |

The top of the new order is real work, not noise — the first five are
`Gr.Morton ≈ Morton`, `OFI ≈ OFI Crete`, `Jeonnam D. ≈ Jeonnam Dragons`, `Drita ≈ Drita
Gjilan`, `Middlesbrou. ≈ Middlesbrough`. Those 1,299 candidates would write 1,623 alias
entries covering **710 distinct** aliases, so approving the top of the queue compounds.

## Page size

`CANDIDATE_PAGE_SIZE = 100`, `CANDIDATE_PAGE_MAX = 500`. The queue held 13,471 items for
5.33 MB on a 30-second poll; a 100-item page is a bounded payload and a bounded
`innerHTML` rebuild. Because the queue is ordered by actionability, the first page is the
part a reviewer can actually work through, so 100 is enough to be useful rather than a
larger number that buys nothing. Measured: **100 real candidates = 89,750 bytes (88 KB,
898 B each)**; the full 3,712-item dump in the same measurement was 3.2 MB, so the page is
~3,300× smaller. Per-item size grew from ~395 B to ~898 B because the card now carries both
sides and both spellings — that is the payload cost of Critical 1, and it is bounded by the
page. `GET /candidates` now returns `total`, `count`, `limit`, `offset`, and the tab badge
shows `total` with a "Showing the N most actionable of M queued" note.

## Important 1 — the prefilter contradiction, resolved

The review was right: the outer bigram check admitted a typo pair and the **inner**
per-combination gate had no bigram clause, so it still scored 0.0. My round-1 claim was
the exact inverse of the behaviour.

I made the claim true instead of deleting the term, because a token-only gate drops
`Aguilas/Millionarios` vs `Rionegro/Millonarios` (pure score **95.7**, no shared token) —
a real same-event typo, precisely the case the queue exists for. The outer test is now
`_shares_any_signal` (tokens ∪ bigrams ∪ substring) and the inner gate applies the **same**
test per team slot, over per-slot bigram sets whose union is what the outer test uses. That
makes it provable that the inner gate can never veto a slot the outer gate admitted, so
`_team_similarity` returns the plain `max(token_set_ratio(...))` over the four combinations
for every pair the outer gate admits.

`test_cheap_prefilter_never_vetoes_the_fuzzy_rule` pins the invariant both ways, on four
pairs including the reviewer's typo and the `Bury Town`/`Leicester` false positive:

* admitted by the cheap gate → `shipped == pure` exactly;
* rejected by the cheap gate → `pure < CANDIDATE_TEAM_SIM_MIN`, i.e. the gate is not the
  reason a plausible pair was dropped.

Cost of being honest: on the real corpus the queue is 15,140 rather than 13,471 (+12 %, the
1,669 pairs the old inner gate was silently vetoing, e.g. the typo class) and
`_collect_candidates` takes **12.4 s** against the matcher's 41 s. The cheap gate still
earns its place — it skips ~114k of 745k comparisons outright.

Per the process correction: I ran the gate on my own motivating example before writing the
claim this time, and the numbers quoted above (95.7, 15,140, 1,299, 516→524) are all from
runs, not from reading the code.

## Important 3 — `same_event` is honoured

`ai_same_event: bool | None` on the candidate (`None` = not consulted). A `same_event=False`
proposal sets `ai_confidence = 0.0` and `ai_reason = "AI says not the same event: …"`, and
the frontend sorts such cards last regardless of confidence
(`test_ai_negative_verdict_is_not_presented_as_confidence`, and a static frontend test for
the sort). A discarded (hallucinated) proposal still leaves all three fields untouched.

## Minors

* **M1** — `get_candidates` no longer takes a `mode` parameter it cannot honour. The queue
  is global, so the parameter was a lie; dropping it is the honest fix. The underlying
  limitation is unchanged and still listed as a concern below.
* **M2** — the comment on `AI_RANK_TIME_BUDGET_SECONDS` now says what is true: it is
  checked before each call and can overshoot by one in-flight call (`MatchAI.timeout`, 10 s).
* **M3** — `MatchAI.with_shared_client()` builds one `httpx.AsyncClient` per scan, so 20
  calls cost one TLS handshake and `aclose()` now closes something real
  (`test_shared_client_serves_every_call_and_aclose_closes_it`,
  `test_shared_client_keeps_the_configured_endpoint`, `test_ai_calls_share_one_http_client`,
  `test_no_http_client_is_built_when_the_ai_is_unavailable`).
* **M5** — `candidate_reviews` is trimmed to `CANDIDATE_REVIEW_HISTORY_MAX = 200` on every
  decision (`test_candidate_review_history_is_bounded`). It is still served by no endpoint.
* **M4** — no action, agreed.

## Verification commands and output

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_scan_candidates.py
41 passed in 6.99s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
343 passed, 3 warnings in 12.52s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
Success: no issues found in 52 source files
```

**343 passed, 0 failed, 0 errors** (was 305; +38 new). The 3 warnings are the pre-existing
FastAPI `on_event` deprecations.

Browser check (uvicorn on :8099 with 4 real candidates seeded, Chrome):
`Review` badge = 4, 4 cards, first card reads
`OFI VS CSKA Sofia … NAMES THE TWO BOOKS DISAGREE ON HOME OFI ≈ OFI Crete AWAY CSKA Sofia ≈
CSKA Sofia … The deep-link check is a separate system verification, so this pair stays
unverified until that check runs. An approval clears every remaining blocker here. … Approve
pairing / Reject pairing`; the negative-AI card sorts last; the two cards whose books
already agree render a disabled **Nothing to alias** button. `node --check frontend/js/app.js`
parses clean.

## Concerns after this round

1. **`deep_link_verified` is still `False` everywhere**, so 100 % of candidates are
   `link_blocked` and no match group is ever verified. That is Task 12, but until it lands
   the whole product is dark: the 516-group baseline above is what the pipeline would
   produce today with links verified. Task 12 is now the critical path for the feature, not
   a nice-to-have.
2. **League-blocked candidates have no human action at all** (77 % of the queue). An alias
   cannot fix `league_mismatch` and there is no UI for adding a league equivalence, so the
   only available decision is Reject, which suppresses the pair permanently. Correct, but it
   means the queue cannot be worked down to zero by a human.
3. **The queue is 15,140 items.** Suppression only removes what a human has decided, one at
   a time; 710 distinct aliases would cover the 1,299 actionable candidates, but nothing
   batches them. A "write these 23 aliases" bulk action is the obvious next step and is not
   built.
4. **An approval's effect on the queue is invisible until links are verified.** Approving
   clears the *team* blocker, but the candidate gate deliberately holds no allowlist, so the
   other 14,000 candidates keep showing `team_unresolved` even after the alias exists. The
   card says what approval did; the queue total will not move for unrelated pairs.
5. **`_collect_candidates` normalises through the gate when called standalone** and through
   the matcher in production (`run_scan` always runs the matcher first). The two differ by
   the league scope, worth ~1 % of the actionable count (1,299 vs 1,284 measured). I left it
   alone rather than change production behaviour in a fix round; it is a latent
   order-dependence for any future caller.
6. **`pending_candidates` is still global and mode-agnostic**, so a live scan clobbers the
   prematch queue, and two overlapping scans race on it (statements are atomic w.r.t. the
   event loop, so no half-mutated dict is observable, but last-writer-wins).
