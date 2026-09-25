# Fix: the certainty gate never read `supports_event_id`

> **§6 IS PARTLY WRONG — READ THIS BEFORE QUOTING IT.** Re-measured on
> 2026-09-25T23:13Z against the same `cache/last_scan.json` with the same two
> rewrites, the shipped gate gives scenario A **16 groups / 0 surebets**,
> B **179 / 0** and C **516 / 0** — not 26/202/532 and not 1 surebet. The
> "202 groups / 1 surebet" line in §6 is superseded: its surebet is the
> `premier_kladionica` Over 2.5 @ 2.15 vs `sportplus` Under 2.5 @ 1.9 pair, both
> prices real, but those matches are 120 minutes apart and
> `VERIFIED_KICKOFF_WINDOW_MINUTES` is 15, so the gate refuses the pair with
> `kickoff_delta` at any link state. The group counts also depend on the order
> the books are fed to `group_matches`, which §6 does not state.
> `tests/test_deeplinks.py::test_a_declared_no_route_book_never_carries_a_per_event_url_in_the_capture`
> is the new tripwire; `PLAN.md` §3 *Phase 4* carries the corrected table and its
> conditions. The rest of this report (the diagnosis, the design, the test
> inventory) stands.

**Branch:** `master` (in place, no worktree) · **Status:** complete, suite green
**Scope:** Critical defect remediation. No new task, no plan changes.

---

## 1. Root cause

`engine/certainty.py:_link_evidence` branched on two things only —
`deep_link_verified`, and `event_id or url` — and `evaluate_pair` added *every*
non-`verified_link` record to `reasons`:

```python
if m.event_id or m.url:
    return MatchEvidence(..., reason="link_unverified")
return MatchEvidence(..., confidence=0.5, reason="no_event_link")
...
if link_evidence.reason == "link_unverified":
    link_reasons.add("link_unverified")
elif link_evidence.reason == "no_event_link":
    link_reasons.add("no_event_link")
```

`config/bookmaker_deeplinks.json` was read by `scripts/verify_deeplinks.py` and by
`server/api.py`, and by nothing in the gate. The design spec's clarified link
policy (`docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md:74-84`)
says a book that *genuinely offers no per-event URL* "must be declared with
`supports_event_id: false` … and **is accepted with a `no_event_link` evidence
note**". Six books declare exactly that — `wwin`, `mbet`, `sportplus`, `evlbet`,
`premier_kladionica`, `betole` — and every one of them was structurally excluded
from `verified` by a code path that never asked the config.

The exclusion was total, not partial, and that is the part that is easy to
misread. In a real scrape the route-less books *do* carry a `url` and an
`event_id`: WWIN publishes a Betradar feed id (`4620444`) and its site URL,
MBet publishes a feed id. Measured on the cached scan: **6999 of 6999 matches
carry a url or an event id, and 0 of 6999 have a proven link.** So the old gate
never even reached the `no_event_link` branch in production — it read "there is
an id" as "there is an unproven link" and produced `link_unverified` for every
book. The fix is not a nuance of branch ordering; without reordering the
declaration ahead of the id check, the change would have been worth nothing.

One correction to the brief's premises, both verified rather than assumed:

* **`no_event_link` was never in `HARD_REJECT_REASONS`.** The brief says it was.
  It is not, and never was:
  ```
  HARD_REJECT_REASONS = ['category_mismatch', 'league_mismatch', 'orientation_unresolved']
  'no_event_link' in HARD_REJECT_REASONS = False
  ```
  It was a *soft* reason producing `suggested`. So no test that pins
  `HARD_REJECT_REASONS` had to change, and the constant is untouched.
* **There is no import cycle to solve.** The brief said `engine/certainty.py` is
  imported by `engine/arbitrage.py` (it is not — `arbitrage.py` imports
  `parse_ah_label` from `scrapers.common`, nothing from `certainty`) and that a
  cycle would need Task 4's lazy-accessor treatment. The engine *already*
  imports `scrapers.common` at module scope, in two other modules:
  `engine/arbitrage.py:33` and `engine/matcher.py:43`. Measured cost of adding a
  third such import, before and after: **456 modules and ~850 ms either way**,
  with `playwright` and `httpx` already loaded in both cases (the scrapers
  package is on the engine's import path already). I therefore used a plain
  module-level import, matching the existing pattern, and verified all seven
  import orders (§5.4). A lazy accessor would have been the more defensive
  choice and I would have used it if the edge did not already exist; inventing a
  cycle to solve would have been theatre.

---

## 2. What the gate does now

```python
if m.deep_link_verified:            -> verified_link,    settled   (unchanged)
if declares_no_event_id(book):      -> no_event_link,    settled   (the fix)
if supports_event_id(book) or event_id or url:
                                   -> link_unverified,  blocking
else                               -> no_event_link,    blocking  (undeclared)
```

Three properties I made structural rather than incidental:

* **`_link_evidence` returns `(MatchEvidence, bool)`** — the record and the
  decision come from one method, so "what the trail says" and "what blocks" cannot
  drift apart.
* **`declares_no_event_id` requires the boolean `False` specifically** (`is
  False`), not falsiness. `supports_event_id` cannot answer this question: it
  returns `False` both for a declared-false book *and* for a book with no
  declaration at all, which is exactly the distinction the gate must make. A
  quoted `"false"`, a `null`, a missing key and an unreadable config file all fail
  safe, because a typo in that JSON must never be able to grant trust.
* **The config read is already cached** (`_load_deeplink_cache`, one module
  global, the same pattern `build_event_url` uses). Measured: 0.46 µs per
  declaration lookup, 43.62 µs per `evaluate_pair` — about 2% of the gate, and no
  I/O on the hot path.

Identity gates (league, 15-minute kickoff, category, team, orientation) are
untouched, and `HARD_REJECT_REASONS` is untouched. Diff: `engine/certainty.py`,
`scrapers/common.py` (one new predicate), `server/api.py` (one health field — §6).

---

## 3. The judgment calls

### 3.1 Must the `no_event_link` record be present and well-formed for `verified`? — **Yes, and it is structural**

I agree with the brief, and the implementation makes it unfalsifiable by accident:
the record is appended for **every** side of **every** pair, settled or not
(`engine/certainty.py`, the `evaluate_pair` loop), and `verified` is reachable
only when no side is unsettled. So a `verified` group cannot exist without the
record; there is no code path that skips it.

The stronger half of the argument is the opposite one: if the record were
*optional*, a verified group's link half would be unaccounted for, and the only
trace of the decision would be the absence of a complaint. That is the defect
being fixed, reproduced in the evidence trail.

Two deliberate choices inside the record:

* `confidence=1.0`, not the old `0.5`. A declared absence is as certain as a
  proven link; `0.5` would read as an unproven claim. Pinned by
  `test_the_accepted_no_link_note_is_a_well_formed_evidence_record` and by the
  e2e test on `MatchGroup.evidence`.
* `source="rule"`, not `"human"`. A human wrote the declaration, but `source`
  records which *stage* decided, and the precedent in this gate is the league
  equivalence — also human-authored, also consumed by the rule stage — which is
  recorded as `source="rule"` in `league_identity`. The declaration is a declared
  fact the rule stage trusts, exactly like that.

### 3.2 Hard-reason change, evidence-only change, or both? — **Evidence-only, for declared books; the reason is untouched for undeclared books. `HARD_REJECT_REASONS` does not change at all.**

It cannot change `HARD_REJECT_REASONS`, because `no_event_link` was never in it
(§1). What changes is *which inputs* produce that reason. `no_event_link` keeps
both of its old jobs, now partitioned by declaration:

| book | unproven link | outcome |
|---|---|---|
| declares `false` | any, including a present `url`/`event_id` | `no_event_link` as **evidence**, `confidence 1.0`, **not a reason** → does not block |
| declares nothing | none captured | `no_event_link` as **evidence**, `confidence 0.0`, **is a reason** → blocks |
| declares `true` | any | `link_unverified`, `confidence 0.0`, **is a reason** → blocks |

`tests/test_frontend_review.py` AST-derives the reason vocabulary from the source.
**Verified, not assumed** (§5.4): the extractor reads literals out of
`reasons.append/extend`, `result.reasons.append/extend`, `link_reasons.add(...)`
and the `HARD_REJECT_REASONS` assignment. Had I written
`link_reasons.add(link_evidence.reason)`, both literals would have left the
derived set and `test_source_reason_extraction_is_nonempty` would have failed. The
sink therefore keeps both literals explicit, which is also the more readable
form: the two names of "this blocks" are written at the place that decides it.

**One reason changed its meaning, deliberately:** a declared-`true` book with an
empty `url` **and** an empty `event_id` used to be `no_event_link` and is now
`link_unverified`. It still blocks, so no group is gained — but the old reason
claimed the book has no per-event page, which its own declaration contradicts,
and it is the exact sentence that would have kept the Task 12 dead end alive.
Measured, §5.2, case 5.

### 3.3 Import cycle — **none; plain module-level import, existing pattern.** Evidence in §1 and §5.4.

### 3.4 Caching — **already cached, nothing added.** §2.

---

## 4. BEFORE / AFTER on all three cases

Probe: two real bookmakers, every identity gate satisfied, so only the link half
can decide. `url`/`event_id` set to the shape a real scrape produces.
`git stash push engine/certainty.py scrapers/common.py` gives the true BEFORE
from the committed code, not a recollection.

```
############ AFTER (working tree) ############
1. declared a route, link unproven      (mdshop + mbet)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'no_event_link'] confidence=[0.0, 1.0]
2. declared NO route, unproven link      (mbet + wwin)
     status=verified  reasons=[]
     link evidence=['no_event_link', 'no_event_link'] confidence=[1.0, 1.0]
3. declared NO route, real feed id+url   (mbet + wwin, as scraped)
     status=verified  reasons=[]
     link evidence=['no_event_link', 'no_event_link'] confidence=[1.0, 1.0]
4. NO declaration at all, unproven link  (nosuchbook + alsonotabook)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'link_unverified'] confidence=[0.0, 0.0]
5. declared a route, url AND event_id emptied (mdshop + admiralbet)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'link_unverified'] confidence=[0.0, 0.0]
6. declared a route, link PROVEN by the browser check (mdshop + mbet)
     status=verified  reasons=[]
     link evidence=['verified_link', 'verified_link'] confidence=[1.0, 1.0]

HARD_REJECT_REASONS = ['category_mismatch', 'league_mismatch', 'orientation_unresolved']
'no_event_link' in HARD_REJECT_REASONS = False

############ BEFORE (HEAD engine/certainty.py + scrapers/common.py) ############
1. declared a route, link unproven      (mdshop + mbet)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'link_unverified'] confidence=[0.0, 0.0]
2. declared NO route, unproven link      (mbet + wwin)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'link_unverified'] confidence=[0.0, 0.0]
3. declared NO route, real feed id+url   (mbet + wwin, as scraped)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'link_unverified'] confidence=[0.0, 0.0]
4. NO declaration at all, unproven link  (nosuchbook + alsonotabook)
     status=suggested reasons=['link_unverified']
     link evidence=['link_unverified', 'link_unverified'] confidence=[0.0, 0.0]
5. declared a route, url AND event_id emptied (mdshop + admiralbet)
     status=suggested reasons=['no_event_link']
     link evidence=['no_event_link', 'no_event_link'] confidence=[0.5, 0.5]
6. declared a route, link PROVEN by the browser check (mdshop + mbet)
     status=verified  reasons=[]
     link evidence=['verified_link', 'verified_link'] confidence=[1.0, 1.0]
```

Reading the three cases the brief asked for:

1. **Declared-true, unverified** — identical before and after:
   `suggested ['link_unverified']`. Unchanged, as required.
2. **Declared-false** — `suggested ['link_unverified']` → **`verified`, no
   reasons**, with a `no_event_link` record at `confidence 1.0` for each side.
   This is the spec's accepted case and it now happens.
3. **Undeclared** — still blocking. With a captured id/url it is
   `link_unverified` (unchanged); with nothing captured it is `no_event_link` at
   `confidence 0.0` (was `0.5` — the old `0.5` read as "half a fact" for a case
   that is a plain refusal).

**The Task 12 dead end, measured (case 5).** The recorded follow-up said emptying
`url`/`event_id` on the mdshop/admiralbet scrapers "would make 197 groups
verifiable". It does not, before or after: it is `suggested` with
`link_unverified` both times. The conclusion was wrong; the reason it gave
(`no_event_link`) was also wrong, and is now `link_unverified`, which is what the
situation actually is.

---

## 5. Commands and full output

### 5.1 TDD, RED — written first, watched fail

New gate tests, before any source change:

```
$ python -m pytest -p no:warnings tests/test_certainty.py -q
FAILED tests/test_certainty.py::test_a_book_that_declares_no_per_event_route_is_accepted
FAILED tests/test_certainty.py::test_a_declared_no_link_book_is_accepted_even_with_a_url_and_an_event_id
FAILED tests/test_certainty.py::test_the_accepted_no_link_note_is_a_well_formed_evidence_record
FAILED tests/test_certainty.py::test_a_declared_route_book_with_no_captured_url_is_link_unverified
FAILED tests/test_certainty.py::test_a_book_with_no_declaration_fails_safe - ...
FAILED tests/test_certainty.py::test_a_malformed_declaration_does_not_grant_trust
FAILED tests/test_certainty.py::test_every_declared_route_book_blocks_and_every_other_book_is_accepted
FAILED tests/test_certainty.py::test_evaluating_against_a_group_accepts_a_declared_no_link_book[mbet]
FAILED tests/test_certainty.py::test_evaluating_against_a_group_accepts_a_declared_no_link_book[wwin]
FAILED tests/test_certainty.py::test_evaluating_against_a_group_accepts_a_declared_no_link_book[sportplus]
FAILED tests/test_certainty.py::test_evaluating_against_a_group_accepts_a_declared_no_link_book[betole]
11 failed, 31 passed in 2.19s
```

Three of the new tests passed at this point and I am flagging them so they are not
mistaken for reproductions: `test_an_undeclared_book_with_a_url_is_link_unverified_not_accepted`
and `test_a_book_that_declares_a_route_still_needs_it_proven` (the honest case the
brief told me to leave alone — they pin that it stays broken), and
`test_an_unreadable_deep_link_config_fails_safe`, a fail-safe pin that holds under
both the old and new gate.

Health counter, RED:

```
$ python -m pytest -p no:warnings tests/test_candidates_api.py::test_health_includes_new_diagnostics
>       assert body["unverified_links"] == 1
E       AssertionError: assert 2 == 1
1 failed in 1.35s
```

Two failures I caused myself, both fixed before touching the source, and both
worth recording because they are the failure mode this repo's TDD keeps hitting:
`test_a_malformed_declaration_does_not_grant_trust` paired the book under test
with an mbet that the monkeypatched cache had made undeclared, so the expected
single reason arrived as two; and the first branch ordering I wrote put the
"nothing captured" test ahead of the "declares a route" test, which made case 5
come out `no_event_link` instead of `link_unverified`.

### 5.2 The new tests, GREEN

```
$ python -m pytest -p no:warnings -v -k "declares_no_per_event or declared_no_link or \
  declared_a_route or no_declaration_fails_safe or undeclared_book or malformed_declaration or \
  unreadable_deep_link or every_declared_route_book or verified_link_still_wins or \
  evaluating_against_a_group_accepts or callout_states_the_link_policy or link_policy_fails or \
  declared_no_link_book_with_no_stored_proof or records_the_declared_absence"
collected 561 items / 543 deselected / 18 selected

tests\test_certainty.py ............                                     [ 66%]
tests\test_deeplinks.py .                                                [ 72%]
tests\test_e2e_certified.py ..                                           [ 83%]
tests\test_readme_claims.py ...                                          [100%]

===================== 18 passed, 543 deselected in 1.88s =====================
```

### 5.3 Full suite — explicit passed count

```
$ python -m pytest -p no:warnings
........................................................................ [ 25%]
......................................................x................. [ 38%]
........................................................................ [ 51%]
........................................................................ [ 64%]
........................................................................ [ 77%]
........................................................................ [ 89%]
.................................................................        [100%]
560 passed, 1 xfailed in 17.66s
```

**560 passed, 1 xfailed** — up from **540 passed, 1 xfailed** at the base commit
`854bcb5`, i.e. +20 new test cases, zero pre-existing tests dropped, the strict
`xfail` unchanged.

```
$ ruff check .
All checks passed!

$ mypy .
Success: no issues found in 59 source files
```

### 5.4 The AST vocabulary derivation, verified rather than assumed

```
$ python -c "import test_frontend_review as t; c=t._source_reason_codes(); ..."
AST-derived reason codes from engine/certainty.py:
['category_mismatch', 'kickoff_delta', 'kickoff_missing', 'league_mismatch',
 'link_unverified', 'no_event_link', 'orientation_unresolved', 'team_unresolved']

KNOWN_REASON_CODES still covered by the AST extraction: True
missing from AST extraction: []
labels missing for derived codes: []
```

### 5.5 Import orders, with the shipped module-level import in place

```
import engine                                              OK
import scrapers                                            OK
import engine.certainty                                    OK
import engine.matcher                                      OK
import engine.arbitrage                                    OK
import server.api                                          OK
from scrapers.common import build_event_url; import engine.certainty OK
```

### 5.6 Hot-path cost

```
200000 evaluate_pair calls: 8.725s -> 43.62 us per call
deeplink config cached in module global: True
200000 declares_no_event_id calls: 0.461 us each
```

---

## 6. Measured effect on real counts (`cache/last_scan.json`, no network)

Input: a real prematch scan, 6999 matches, 7 books, `scan_time 2026-08-20`, and
**0 of 6999 matches carry a proven link**. The matcher and the arbitrage engine
are pure functions of that file, so nothing here touches the network. Surebet
counts are measured with the odds age reset to now and past kickoffs pushed
forward, because the cache is a month old and the engine would otherwise refuse
every leg for reasons unrelated to the link gate; both rewrites are in the script
docstring. The BEFORE column is the same process with the declaration lookup
patched to "no book declares anything", which is exactly the old gate on this data.

```
== AFTER: the shipped gate, which reads the declarations ==
  A. links exactly as cached (no proof stored)
    verified groups        : 26
    groups holding a book that DECLARES a route: 0
    surebets               : 0
  B. + the one book whose route verifies (mozzartbet)
    verified groups        : 202
    groups holding a book that DECLARES a route: 1 ['mozzartbet']
    surebets               : 1
      over_under_2_5 egnatia vs lillestrom 0.86%  {'premier_kladionica': 2.15, 'sportplus': 1.9}
  C. + every book's link proven (the ceiling)
    verified groups        : 532
    groups holding a book that DECLARES a route: 3 ['admiralbet', 'mdshop', 'mozzartbet']
    surebets               : 1
      over_under_2_5 egnatia vs lillestrom 0.86%  {'premier_kladionica': 2.15, 'sportplus': 1.9}

== BEFORE: the same gate with the declaration lookup answering 'nothing is declared' ==
  A. links exactly as cached (no proof stored)
    verified groups        : 0
    surebets               : 0
  B. + the one book whose route verifies (mozzartbet)
    verified groups        : 0
    surebets               : 0
  C. + every book's link proven (the ceiling)
    verified groups        : 532
    surebets               : 1

== summary (groups / surebets) ==
scenario                                                     BEFORE          AFTER
A. links exactly as cached (no proof stored)                  0 / 0         26 / 0
B. + the one book whose route verifies (mozzartbet)           0 / 0       202 / 1
C. + every book's link proven (the ceiling)                 532 / 1       532 / 1
```

Reading these:

* **A — the cache as it stands: 0 → 26 verified groups, 0 → 0 surebets.** On the
  stored scan, not one group holds a declared-route book, so there is no 1X2
  three-book group and nothing is priced. The 26 groups are real: same identity
  gates, same prices, just no longer refused for links those books never claimed.
* **B — the state a deployment with Mozzartbet's link check actually reaches:
  0 → 202 groups, 0 → 1 surebet.** This is the number the brief was reaching for.
  I get 202, not 197; the brief's figure came from a 1,592-match three-book feed
  (PLAN.md §3), mine from a 6,999-match seven-book one, and the two are not
  comparable. I am reporting mine and not reconciling the difference.
* **C — the ceiling is bit-identical before and after: 532 groups, 1 surebet.**
  This is the safety datum that matters most: the change is **strictly
  monotone**. It can only add pairs that were refused; when every link is proven
  the accepted set is unchanged, so no group that used to be verified is now
  refused, and no group that used to be refused is priced *except* by having its
  link half settled by a declaration.

Unchanged by this work, and worth stating: `scripts/verify_deeplinks.py`'s logic,
and all nine `supports_event_id` declarations. MDShop, Admiralbet and Mozzartbet
still declare `true`, and their two inert routes are still reported honestly —
scenario A shows 0 surebets for the stored scan, and the two books' groups are
excluded from `verified` for the same reason as before.

---

## 7. Every test I changed, and why

Nothing was deleted. Twelve new test functions, one rewritten, six retargeted.

**`tests/test_certainty.py`** — 12 new tests (one of them parametrized ×4, so 15
cases), which is the file the defect belonged to:
`test_a_book_that_declares_no_per_event_route_is_accepted` (the spec's case),
`test_a_declared_no_link_book_is_accepted_even_with_a_url_and_an_event_id` (the
real scrape shape — without this one the fix would have been worth nothing),
`test_the_accepted_no_link_note_is_a_well_formed_evidence_record` (judgment call
3.1), `test_a_book_that_declares_a_route_still_needs_it_proven` and
`test_a_declared_route_book_with_no_captured_url_is_link_unverified` (the honest
case, unchanged, plus the dead-end guard), `test_a_book_with_no_declaration_fails_safe`
and `test_an_undeclared_book_with_a_url_is_link_unverified_not_accepted` (fail
safe), `test_a_malformed_declaration_does_not_grant_trust` and
`test_an_unreadable_deep_link_config_fails_safe` (a config typo must not grant
trust), `test_every_declared_route_book_blocks_and_every_other_book_is_accepted`
(parameterised over the JSON, so flipping a declaration is a reviewed diff),
`test_a_verified_link_still_wins_over_the_declaration`,
`test_evaluating_against_a_group_accepts_a_declared_no_link_book` (the path the
matcher actually uses, not just `evaluate_pair`).
**Changed:** `test_evaluate_records_group_league_mismatch_with_soft_pair_failure`
used mbet for its soft failure; mbet no longer fails softly, so the pair now uses
admiralbet, a declared-route book. The test's claim (a soft pair failure turned
into a hard reject by the group's own league) is preserved exactly.

**`tests/test_e2e_certified.py`** — 2 new tests, 1 rewritten, 1 breaker retargeted.
`test_scan_verifies_a_declared_no_link_book_with_no_stored_proof_at_all` and
`test_a_verified_group_records_the_declared_absence_as_evidence` are the e2e
proof of the fix, built from the three captured books that all declare no route,
with the store empty. `_break_link` no longer breaks "the state every scraped match
is in" (which stopped being true for these three) and instead relabels one book
onto a declared-route id; its param now also asserts the gate's
`link_unverified`, which the old `gate_reason=None` did not. **The one rewrite I
want flagged:** `test_scan_refuses_a_link_proof_that_aged_out` can no longer be
written on `BOOKS`, because all three of those books settle their link from the
declaration and an aged-out proof costs them nothing — the case is not
demonstrable on them at all. It now runs on two books that declare a route
(mdshop + admiralbet, the real capture of one real NSoft event, event 6828117, with
the identity shell filled in exactly as the three parsers above already do), and
keeps every original assertion: the group is verified with a fresh proof, not
reported at all with an aged-out one, nothing priced, the pair queued with
`link_blocked is True` and `link_unverified` in its rejections. **What that
rewrite no longer covers end-to-end:** "an aged-out proof costs a *surebet*". It
cannot be covered end-to-end in this file, because the only three captured books
for one fixture are all route-less, and a four-book chain would need one declared
route book's real prices for that same fixture, which no capture contains. I
would rather say that than fabricate it. The store-level TTL is still pinned
independently by `tests/test_verify_links.py::test_an_expired_verification_is_ignored_and_dropped`.
Also corrected in this file: the module docstring's "HONESTY NOTE ON LINKS", which
stated that no group is ever `verified` in production, and the docstring of
`test_scan_applies_stored_link_proofs_and_serves_the_surebet`, which claimed the
store is "the only way a real deployment ever gets" a verified link — no longer
true for these books. The store is still applied and still asserted.

**`tests/test_matcher_certified.py`** — one test,
`test_gate_rejected_singleton_cannot_later_merge_into_wrong_group`, used mbet as
"the gate-rejected" book. It needs a book the gate actually refuses, so it now
uses admiralbet. The claim is unchanged.

**`tests/test_readme_claims.py`** — 3 new tests, and the vocabulary probe
retargeted. `_observed_reasons` produced `no_event_link` from
`_match(bookmaker="mbet", url="", event_id="", deep_link_verified=False)` and
`link_unverified` from `_match(bookmaker="mbet", ..., deep_link_verified=False)`;
neither is reachable through mbet any more, so the first is now an **undeclared**
book and the second uses the default bookmaker (mdshop, declared `true`). Both
reasons are still reachable, through the inputs that now reach them, and the
comment above the probe says so. `_headline_problems` was re-scoped from "the
claim that says zero surebets are produced" to "the claim that says the routes
are inert", because the callout no longer contains the former. New
`_link_policy_problems` checks the callout's link-policy claim **by running the
gate** on one declared-route and one route-less book, and rejects the old
"requires a proven deep link on both sides" sentence outright; two companion
mutations prove the check can fail.

**`tests/test_candidates_api.py`** — `test_health_includes_new_diagnostics`'s
fixture gained a `bookmaker` on each cached match and a third, route-less match.
`/api/health`'s `unverified_links` counted any match with an event id and no
proof, which after this change would report thousands of "blockers" belonging to
books that block nothing. It now counts only matches whose unproven link can
still block, with the reason in a comment. This is the one change outside
`engine/` and `scrapers/`; I made it because the alternative was a health
endpoint whose main diagnostic is wrong by a factor of six, and this repo's tests
exist precisely to stop that.

---

## 8. Documentation that my change falsified

Two documents asserted the opposite of what the code now does, and one asserted
the defect itself. All three are corrected here, with the tests re-pointed at the
new claims rather than deleted:

* **README callout** — "`verified` requires a proven deep link on *both* sides …
  in production zero groups reach `verified` and zero surebets are produced …
  This is a bookmaker-side routing fact, not a bug in the code." Now states the
  two-branch policy, that a route-less book is verified on identity alone, that an
  undeclared book fails safe, and that what still blocks `verified` is a
  declared-route book whose link is unproven. The "Re-check this claim yourself"
  block, the runnable command, the dated-inertness paragraph and the pointers
  (`tests/test_readme_claims.py::_POINTERS`) are unchanged.
* **README § Match & mapping certainty** — one bullet added on the declared
  absence, next to the existing "links are a machine fact" bullet.
* **PLAN.md § Phase 4 headline** — the claim "the blocker is a bookmaker-side
  routing fact. The route was deliberately NOT flipped to `supports_event_id:
  false` — **that would change nothing in the gate**" was true when written and is
  now exactly backwards. A dated correction paragraph was added rather than
  rewriting the historical measurement, so the four tokens
  `test_plan_declares_phase_four_done_with_the_headline` checks
  (`inert`, `zero surebets`, `Mozzartbet`, `verified`) still appear and still
  appear in true sentences.

I did not touch `scripts/verify_deeplinks.py` or any declaration.

---

## 9. Concerns

1. **Is this unsafe for the "no wrong surebet ever shown" promise? I do not think
   so, and here is the argument rather than the assurance.** The link half is
   corroboration, not the identity proof. Identity is carried by the canonical
   league, the 15-minute kickoff window, the special-category agreement, the
   canonical team ids (exact or reviewed alias) and a provable orientation — all
   untouched, and all still required. What a per-event URL added was a second,
   weaker witness that the two listings are the same event, and the gate never
   even read the URL: it read a boolean a browser script set by finding the event
   id in the page. So the change removes one corroborating signal for six books
   and adds none. The measured datum that settles it for me is scenario C in §6:
   with every link proven the accepted set is bit-identical before and after, and
   scenario A shows the newly-accepted groups carry no declared-route book at all.
2. **The real residual risk is config integrity, and it is now the whole risk.**
   A bookmaker that *does* have per-event routes and whose operator wrongly
   declares `false` would be accepted without corroboration. Three mitigations:
   the fail-safe is one-sided (only a literal boolean `false` grants trust, so a
   typo, a string, a null and an unreadable file all refuse);
   `test_every_declared_route_book_blocks_and_every_other_book_is_accepted` is
   parameterised over the JSON, so flipping a declaration fails the suite and
   shows up in review; and each `false` declaration already carries a `note`
   (pinned by `test_false_declarations_have_no_event_link_notes`). What it does
   *not* do is re-verify the six notes against the live books. That is a manual
   check, and it is now load-bearing in a way it was not before. I would put it on
   the review queue.
3. **What I could not demonstrate, stated plainly (§7):** "an aged-out stored proof
   costs a *surebet*" is no longer covered end-to-end anywhere, because the only
   three captured books for one fixture all declare no route. The store-level TTL
   is covered, the group-level consequence is covered on a two-book declared-route
   scan, and the gate-level consequence is covered. The surebet-level variant
   needs a captured declared-route book for the same fixture, which needs a new
   capture.
4. **The review queue changes shape.** Pairs of route-less books that were
   link-blocked are now team-blocked only, so `link_blocked` is `False` and they can
   be advertised as approval-actionable. That is correct — an approval really can
   clear them now — and the invariant that makes it safe,
   `test_every_actionable_candidate_is_one_an_approval_actually_verifies`, passes
   by re-running the real gate. But a deployment's queue will shift: fewer
   link-blocked cards, more alias-actionable ones, and the AI will rank a
   different population.
5. **`/api/health`'s `unverified_links` now means something narrower** than the
   spec's field name suggests: unproven links that can still block. Any dashboard
   or alert built on the old semantics — "count of matches whose link is
   unverified" — will read a much smaller number, correctly, but the field name
   is now slightly wider than its value.
6. **The `no_event_link` reason string now carries two meanings**: an accepted
   evidence note (declared) and a blocking refusal (undeclared). They are
   distinguished by `confidence` (1.0 vs 0.0) and by the branch that produces
   them, and both are tested, but a reader scanning reasons alone could confuse
   them. I kept one string rather than inventing a fourth reason because the
   README's vocabulary test pins the emitted set and the spec names this pair.
7. **Cost:** the gate does two cached dict lookups per side per evaluation,
   measured at ~0.9 µs against a 43.6 µs `evaluate_pair` (§5.6). No new I/O, no new
   import cost.
8. **Not done:** I did not add the declared-absence note to
   `MatchMatcher.get_match_report`'s served output. The evidence lives on
   `MatchGroup.evidence` (and is asserted there end-to-end), but the report the
   dashboard reads carries only `status` and the per-book rows, so a reviewer
   looking at `/api/match-groups` will not see *why* the link was accepted. That is
   a real gap for the "explain the claim" promise and it is a display change, not
   a gate change, so I left it rather than widen this change.
