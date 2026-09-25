# Fix: `alias_actionable` no longer promises a fix the gate will not deliver

**Branch:** `master` (in place, no worktree) · **Status:** complete, suite green
**Scope:** Critical defect remediation. No new task, no plan changes.

---

## 1. Root cause

`server/api.py:_collect_candidates` built two `CertaintyGate` instances from the
same two arguments. One of them was wrong.

```python
gate = CertaintyGate(kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN, ...)   # 30
what_if_gate = CertaintyGate(kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN, ...)  # 30
```

`gate` is the **collection** gate: it decides which pairs reach the review queue,
so a wide window is correct there — a near-miss should be found.
`what_if_gate` is the **actionability** gate: `_alias_actionable` re-evaluates a
pair on it with the candidate's own aliases granted and both links marked verified,
and answers `True` only if the result is `verified`. That answer is a statement
about what the *real* gate will do next scan.

The real gate is the one `MatchMatcher` builds (`engine/matcher.py:126`), which
passes no `kickoff_window_minutes` and therefore takes the `CertaintyGate` default,
`VERIFIED_KICKOFF_WINDOW_MINUTES = 15`. For a kickoff delta in **(15, 30]** the
what-if gate answers `verified` and the real gate answers `suggested`. Three
things then follow from one wrong number:

1. `frontend/js/app.js:900-902` renders "An approval clears every remaining blocker
   here." for a pair no approval can clear.
2. `server/api.py` sorts `alias_actionable` first, so exactly the mislabelled pairs
   are the ones a reviewer works first.
3. `_resolve_candidate` → `_suppress_candidate` writes the id to
   `cache/suppressed_candidates.json` permanently, so the opportunity is gone for good.

The candidate's own `rule_rejections` never mention it: the 30-minute collection
gate raises no `kickoff_delta` inside its own window, so the card shows
`['team_unresolved', 'link_unverified']` and gives the reviewer nothing to notice.

The same false claim was written in three places, all of which I corrected:
`_alias_actionable`'s docstring, the `alias_actionable` field comment in
`models/schemas.py`, and the `_collect_candidates` comment on the second gate.

---

## 2. The fix, and the alternatives I rejected

**What I did — the what-if gate is built by a new `_what_if_gate(matcher)` that
leaves the kickoff window at the `CertaintyGate` default.**

```python
def _what_if_gate(matcher: MatchMatcher) -> CertaintyGate:
    return CertaintyGate(league_equivalences=getattr(matcher, "_equivalences", set()))
```

The fix is in the **gate construction**, not the comparison. The comparison
(`status == "verified"`) was correct; it was being asked of a misconfigured gate.

### Why the window, and why the default rather than the constant

The candidate window must not answer the actionability question at all. Its entire
meaning is "look this wide"; it carries no information about whether a human can
close what it finds. The actionability question is precisely *"would the gate that
produces `verified` groups verify this after an approval?"* — so it must be asked
of a gate configured the way that one is.

I left the keyword argument out rather than passing
`kickoff_window_minutes=VERIFIED_KICKOFF_WINDOW_MINUTES` explicitly. The default
*is* that constant, so omitting it means the number is named in exactly one place
and the two gates cannot drift apart if the setting is retuned. A structural test
and the script in §3 both pin the equality, so a future change to the default
fails loudly instead of silently re-opening the bug.

### Why two instances, not one shared

The brief asked me to consider sharing. **Sharing is wrong**, for two reasons, and
the second one I only found by measuring — my first attempt at the demo was
inconclusive and I had to re-derive it:

1. **The two jobs want different windows.** 30 to collect, 15 to decide. One
   instance cannot be both, which is the whole defect.
2. **`_alias_actionable` mutates `gate.alias_allowlist` on the instance it is
   handed.** On a shared gate those aliases flow back into collection. Measured
   consequences (probe output in §3):
   - a later pair spelling the same two clubs loses `team_unresolved` from its
     recorded reasons, so its card explains itself wrongly and `human_blockers`
     is understated;
   - once the deep-link check has passed, that later pair evaluates `verified`
     and hits `if result.status == "verified": continue` — it is silently dropped
     from the queue and never reaches a human.

The second effect is reachable in production: `run_scan` applies stored deep-link
verifications at `server/api.py:1095`, *before* grouping at `:1100`, so a pair
whose links are now proven is grouped, left unverified only because its names are
not yet aliased, and handed to the collection gate.

`test_a_candidate_never_inherits_another_candidate_s_approved_aliases` pins both.

### The `decided` check moved

`if candidate_id in decided` now runs *after* `gate.evaluate_pair`, because the
premise it is checked against (`link_blocked`) is a property of the verdict. The
gate evaluation is cheap and already unconditional for every pair that passes the
token prefilter. `link_blocked` is computed once and reused for the card, so the
premise is read off the same facts the card displays.

---

## 3. BEFORE / AFTER on a 20-minute-delta pair

Command:

```
PYTHONIOENCODING=utf-8 "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" \
  "C:/Users/harun/AppData/Local/Temp/opencode/demo_band_pair.py"
```

The pair is the ambiguous fixture with a 20-minute kickoff delta — inside the
30-minute candidate window, outside the 15-minute verified window.

```
kickoff delta                        = 20 min
CANDIDATE_KICKOFF_WINDOW_MIN (collect) = 30
VERIFIED_KICKOFF_WINDOW_MINUTES (gate) = 15
aliases this pair implies             = ['FC Thun|Thun', 'Lech P.|Lech Poznan']

REAL GATE (the one that produces `verified` groups), approval applied:
  suggested ['kickoff_delta', 'team_unresolved']

BEFORE - what-if gate built on the 30-minute candidate window:
  suggested ['team_unresolved']   -> alias_actionable = True
  but the real gate said suggested, so the card promised a fix that
  the next scan would not deliver. kickoff_delta present in real verdict: True

AFTER  - what-if gate built by `_what_if_gate` (window 15):
  suggested ['kickoff_delta', 'team_unresolved']   -> alias_actionable = False
  agrees with the real gate: True

THE QUEUE, end to end:
  queued                          = True (the 30-minute window still finds it)
  rule_rejections                 = ['team_unresolved', 'link_unverified']
  alias_actionable                = False
  UI sentence rendered            = 'An approval alone cannot clear the remaining blockers here.'
```

The promise now holds: the AFTER reason list is **identical** to the real gate's
list, so the two can no longer disagree, and the pair is still collected (the
constraint on the collection window is respected — `queued = True`).

### The window identity, proved

```
$ PYTHONIOENCODING=utf-8 python "%LOCALAPPDATA%\Temp\opencode\verify_what_if_gate_claims.py"   # cwd = repo root
== claim 1: the what-if gate decides with the verified window ==
CertaintyGate() default window      = 15
MatchMatcher().gate window          = 15
VERIFIED_KICKOFF_WINDOW_MINUTES     = 15
api._what_if_gate(matcher) window   = 15
  -> all three equal: OK
```

### The shared-gate harm, proved (this is what I got wrong first)

My first draft of this docstring claimed sharing "would drop a later pair from the
queue". The first run of the probe **refuted it** — both pairs were still queued,
because a link-blocked pair evaluates to `suggested`, never `verified`, so the
`continue` never fires. I rewrote the probe to isolate the two real effects:

```
$ PYTHONIOENCODING=utf-8 python "%LOCALAPPDATA%\Temp\opencode\probe_shared_gate.py"   # cwd = repo root
== links unverified (the ordinary review case) ==
  SHARED    events 1/2 -> suggested ['team_unresolved', 'link_unverified']
  SHARED    events 7/8 -> suggested ['link_unverified']
  SEPARATE  events 1/2 -> suggested ['team_unresolved', 'link_unverified']
  SEPARATE  events 7/8 -> suggested ['team_unresolved', 'link_unverified']

== links already proven by the system check, no groups passed in ==
  SHARED    events 1/2 -> suggested ['team_unresolved'] actionable=True
  SHARED    events 7/8 -> <dropped: verified> [] actionable=None
  SEPARATE  events 1/2 -> suggested ['team_unresolved'] actionable=True
  SEPARATE  events 7/8 -> suggested ['team_unresolved'] actionable=True
```

The claim in the final docstring states exactly these two effects. The three probe
scripts (`demo_band_pair.py`, `verify_what_if_gate_claims.py`, `probe_shared_gate.py`)
were moved to `%LOCALAPPDATA%\Temp\opencode\` after use — they tripped `ruff`'s
F401 while sitting in the repo — so they are not part of the commit. Each must be
run with the repo root as the working directory; they add `.` to `sys.path` and
import from `tests.test_scan_candidates`.

---

## 4. The suppression guard

I did add one, and I considered three designs before choosing it.

**Chosen: a decision is held against the system-owned state it was taken on, and
stops applying when the system changes that state on its own.**

```python
def _decision_premise(link_blocked: bool) -> str:
    return f"link_blocked={int(link_blocked)}"
```

Recorded next to the decision in `suppressed_candidates.json` and re-checked at
re-queue time by `_decision_still_stands`. Concretely: a pair a human **rejected**
while its card said only the deep-link check could clear it comes **back** once the
per-book check has passed, because the card's own reason is gone and the pair is
now one an approval genuinely clears.

**Why `link_blocked` and nothing else.** Only state the system changes by itself
may be in the premise. I explicitly rejected recording the gate's `rule_rejections`
and worked out why before writing any code: an approval grants the aliases, which
clears `team_unresolved` from the next scan's reason list, so a reason-based
premise would make **every approval contradict its own record** and re-queue the
pair it had just resolved. That is the exact non-convergence the comment above
`_suppressed_candidates` exists to prevent. I confirmed this by reasoning and then
by test — `test_an_approval_does_not_contradict_its_own_record` fails if the
premise ever widens to cover a decision's own effects.

**Why not a kickoff-delta premise.** I built this one first. It works and it is
provable, but it is worth less: after the label is honest, a (15, 30] pair shows
the truth, a human rejects it knowingly, and a later kickoff reading is a *new*
claim whose id is unchanged but whose premise has drifted. It is a plausible
extension of this mechanism, not the live harm. `link_blocked` is the live one.

**Why not make `approved` non-durable while a non-human blocker stands.** That
would immediately break `test_approved_candidate_is_suppressed_on_the_next_scan`
(the fixture is link-blocked, so the pair would return every scan forever) and the
documented convergence invariant at `server/api.py:186-188`. Rejected.

**What it does not cover.** A decision taken on a wrong *kickoff* is still held
for good, even though the kickoff may later change. The mechanism accepts a
premise; I recorded one. Extending it is a two-line change to `_decision_premise`
and is called out in §6.

**Back-compat.** The file gains a `premises` sibling under a `{"decisions", "premises"}`
wrapper. `_load_suppressed_candidates` still returns the same `id -> decision` map
and falls back to the old flat shape, so every already-decided candidate stays
decided across the upgrade. A record with no premise is honoured unconditionally,
exactly as written. `test_a_suppression_file_written_before_premises_still_loads`
pins it, and the on-disk payload was verified directly:

```
on disk: { "decisions": { "abc123": "rejected" }, "premises": { "abc123": "link_blocked=1" } }
decision stands while still link-blocked : True
decision stands once the check has passed: False
after reload, stands once proven         : False
```

---

## 5. Commands and full output

### TDD, RED — written first, watched fail before any code changed

The RED runs below were reproduced from the committed source with the new tests in
place (`git stash push server/api.py server/app.py models/schemas.py`), so this is
the real output of the pre-fix code against the new tests, not a recollection.

```
$ python -m pytest -p no:warnings tests/test_scan_candidates.py \
    -k "approval_cannot_clear or whole_band_above or exact_edge or actually_verifies or never_inherits"
...
>       assert candidate.alias_actionable is False
E       AssertionError: assert True is False
E        +  where True = CandidateReview(id='bbcde4248d2a4f86', home_team='Zrinjski', ...
E        assert len(verified) == 1
>       assert {c.id for c in out.values() if c.alias_actionable} == verified
E       AssertionError: assert {'8a0cf93ae1a...e4248d2a4f86'} == {'8a0cf93ae1a63598'}
E
E         Extra items in the left set:
E         'bbcde4248d2a4f86'
=========================== short test summary info ===========================
FAILED tests/test_scan_candidates.py::test_an_approval_cannot_clear_a_kickoff_delta_the_verified_window_refuses
FAILED tests/test_scan_candidates.py::test_the_whole_band_above_the_verified_window_is_not_actionable[16]
FAILED tests/test_scan_candidates.py::test_the_whole_band_above_the_verified_window_is_not_actionable[20]
FAILED tests/test_scan_candidates.py::test_the_whole_band_above_the_verified_window_is_not_actionable[25]
FAILED tests/test_scan_candidates.py::test_the_whole_band_above_the_verified_window_is_not_actionable[30]
FAILED tests/test_scan_candidates.py::test_the_verified_kickoff_window_is_the_exact_edge_of_actionability
FAILED tests/test_scan_candidates.py::test_every_actionable_candidate_is_one_an_approval_actually_verifies
7 failed, 1 passed, 45 deselected in 2.85s
```

**The 1 passed is `test_a_candidate_never_inherits_another_candidate_s_approved_aliases`**
— correctly, since the pre-fix code already used two separate instances and only the
*window* was wrong. It is a pin on the design decision, not a witness to the defect.

The guard test, likewise written first:

```
$ python -m pytest tests/test_scan_candidates.py -k "does_not_outlive or contradict_its_own" -q
>       assert list(out) == [candidate.id]  # same id, so suppression is what let it go
E       AssertionError: assert [] == ['8a0cf93ae1a63598']
tests\test_scan_candidates.py:526: AssertionError
FAILED tests/test_scan_candidates.py::test_a_decision_does_not_outlive_the_deep_link_result_it_was_made_on
```

`test_an_approval_does_not_contradict_its_own_record` **passed at this point and
still passes**. It is a regression pin on the new mechanism, not a reproduction of
the defect — it exists to fail if the premise is ever widened to cover a decision's
own effects. I am flagging it so it is not mistaken for one.

Two of the seven failures above were my own test-authoring bugs, not the defect, and
I fixed them before touching the source: the property test initially put a tight and
a shifted copy of the *same* fixture in one scan, and `_canonical_pair_key` does not
include the kickoff, so `seen_pairs` collapsed them into one candidate. The fixture
is now a distinct one with its own teams and event ids.

### The 12 new tests, GREEN

```
$ python -m pytest -p no:warnings -v -k "approval_cannot_clear or whole_band_above or exact_edge or actually_verifies or never_inherits or does_not_outlive or contradict_its_own or with_its_premise or before_premises_still_loads"
collected 541 items / 529 deselected / 12 selected

tests\test_scan_candidates.py ............                               [100%]
==================== 12 passed, 529 deselected in 2.96s =====================
```
### Full suite — explicit passed count

```
$ python -m pytest -p no:warnings
........................................................................ [ 53%]
........................................................................ [ 66%]
........................................................................ [ 79%]
........................................................................ [ 93%]
.....................................                                    [100%]
540 passed, 1 xfailed in 16.58s
```

**540 passed, 1 xfailed** — up from 528, i.e. the 12 tests above, with every
pre-existing test still passing and the xfailed one unchanged.

### ruff

```
$ ruff check .
All checks passed!
```

### mypy

```
$ mypy server models engine
Success: no issues found in 12 source files
```

---

## 6. Concerns

1. **The premise currently holds one fact.** `_decision_premise` records
   `link_blocked` and nothing else. A decision taken against a wrong kickoff is
   still held for good. The mechanism takes more premises; I deliberately did not
   add the kickoff band because after this fix it guards a hypothetical rather
   than a live harm, and a continuous measurement is the kind of premise most
   likely to cause queue churn if someone adds it carelessly.

2. **Moving the `decided` check below the gate evaluation** makes the gate run for
   pairs that were previously skipped as already-decided. That is one extra
   `evaluate_pair` per already-decided candidate per scan, on a path that already
   ran a second `evaluate_pair` inside `_alias_actionable` for every queued pair.
   Negligible against the per-book scrapes, but it is a real change in work done.

3. **`_what_if_gate` depends on `getattr(matcher, "_equivalences", set())`** — the
   same private access the collection gate already used, so the two are configured
   identically today. If the matcher ever stops exposing `_equivalences`, both
   gates would silently lose league equivalences together and the promise would
   fail open. I kept the existing idiom rather than widening scope, but it is the
   next place this would break.

4. **The what-if gate is never `normalize`d explicitly.** It inherits normalised
   fields from the `gate.normalize(all_matches)` call above it, because
   `normalize` mutates the shared `Match` objects in place. That is a hidden
   ordering dependency on the line directly above. It predates this change and I
   left it alone, but it is now load-bearing for the honesty claim.

5. **There is no `cache/suppressed_candidates.json` in this working copy** (I
   checked: `cache/` holds only `bookmaker_state.json`, `last_scan.json`,
   `last_live_scan.json`, `scan_history.json`, `.gitkeep`). So I cannot say how
   many real decisions exist or how many would re-queue — I have no evidence and am
   not going to guess. What I can state from the code: every pre-existing record
   has no premise, and `_decision_still_stands` honours a premise-less record
   unconditionally, so **no already-decided candidate changes behaviour across this
   upgrade**. Only decisions taken *after* it carry a premise and can lapse. The
   first scan after the upgrade will therefore re-queue nothing that is already in
   a deployed cache.

6. **The frontend needed no change.** `frontend/js/app.js:900` reads
   `candidate.alias_actionable` from the served payload, which is now honest; the
   false sentence can no longer be reached for a pair the gate still refuses.
   `get_candidates` serves `candidate.model_dump(mode="json")`, i.e. the same field
   the tests assert on.

7. **Not done, and worth saying plainly:** the wider 30-minute collection window is
   still doing more work than it needs to. It queues a pair, and for deltas above
   15 the card now says "an approval alone cannot clear the remaining blockers" —
   which is true but is a weaker reason than the reviewer deserves. The card cannot
   say *why* (kickoff), because the collection gate is deliberately not the gate
   that raises `kickoff_delta`. Surfacing the real reason would mean running the
   verdict gate over collected pairs; that is a feature, not this fix, and I did
   not want to change the queue's contents while making its labels honest.
