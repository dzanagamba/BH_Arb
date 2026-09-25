# Closing the link-declaration review findings (I1, I3, I4, M1, M2, M3)

**Base commit:** `122b2a4` `fix(mapping): let the certainty gate read the deep-link declaration`
**Branch:** `master` (in place) · **Date:** 2026-09-26 (UTC clock reads 2026-09-25T23Z)
**Python:** `C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe`

**The gate's behaviour is untouched.** No file under `engine/` and no file under
`config/` changed:

```
$ git diff --name-only | grep -E "certainty|verify_deeplinks|arbitrage|matcher"
NONE of engine/certainty.py, engine/arbitrage.py, engine/matcher.py,
scripts/verify_deeplinks.py, config/* touched

$ git diff --stat
 PLAN.md                      |  47 ++++++++++-
 README.md                    |  15 +++-
 scrapers/common.py           |  52 ++++++++
 server/api.py                |  27 +++++--
 tests/test_candidates_api.py |  97 +++++++++++++++++++++++
 tests/test_deeplinks.py      | 186 +++++++++++++++++++++++++++++++++++++++++++
 tests/test_readme_claims.py  | 169 +++++++++++++++++++++++++++++++++++++--
 7 files changed, 577 insertions(+), 16 deletions(-)
```

The only production-code changes are two additions in `scrapers/common.py` and
`server/api.py`: a new read-only function, and `/api/health`'s diagnostic
predicate. Neither is reachable from `CertaintyGate`.

---

## I1 — `PLAN.md:7` asserted the defect that was just fixed

### What was there

The top status line, in the present tense:

> **The scanner now produces zero surebets on purpose:** `verified` needs a
> proven deep link, and MDShop's and Admiralbet's `?event=<id>` routes are inert.

### What is true instead, and how I know

The counts are read out of the config, not typed in:

```
$ "C:/.../venv/Scripts/python.exe" -c "
import json
from scrapers.common import declares_no_event_id, supports_event_id, has_declaration
from config.settings import BOOKMAKERS
cfg = json.load(open('config/bookmaker_deeplinks.json', encoding='utf-8'))
t = [b for b in cfg if supports_event_id(b)]
f = [b for b in cfg if declares_no_event_id(b)]
print('books in config:', len(cfg), '| BOOKMAKERS:', len(BOOKMAKERS))
print('declares true  :', len(t), sorted(t))
print('declares false :', len(f), sorted(f))
print('undeclared     :', sorted(set(BOOKMAKERS) - set(cfg)))"
books in config: 9 | BOOKMAKERS: 9
declares true  : 3 ['admiralbet', 'mdshop', 'mozzartbet']
declares false : 6 ['betole', 'evlbet', 'mbet', 'premier_kladionica', 'sportplus', 'wwin']
undeclared     : []
```

The "0 surebets" half of the new header is measured, not asserted — see I3 for
the command and the output. The header is now:

> **Status (2026-09-26):** Phase 4 (mapping certainty) shipped — 13 tasks.
> `verified` requires a proven claim, and link evidence is proven two ways: a
> browser check opened that book's per-event URL, **or** the book declared in
> `config/bookmaker_deeplinks.json` that it has no per-event route. 6 of the 9
> books declare `supports_event_id: false` and are verified on identity alone; the
> 3 that declare a route (MDShop, Admiralbet, Mozzartbet) must still have theirs
> proven, and MDShop's and Admiralbet's `?event=<id>` routes are **inert**, so a
> group holding either still cannot verify. **Zero surebets is today's expected
> output, and it is correct:** the shipped gate produces 0 surebets on the stored
> scan — a measured claim with two conditions, read in §3 *Phase 4* along with the
> correction that supersedes the 2026-09-25 status line.

Three things are deliberately kept from the old header, because they did *not*
change: the inertness (a bookmaker-side fact), the zero-surebet figure (still
true), and the pointer to §3.

### The test

`test_plan_declares_phase_four_done_with_the_headline` now checks the header and
§3 in one test, deliberately: they make one claim in two places, and checking
only §3 is exactly what let them drift. The new `_plan_header_defects` predicate
checks four things and derives two of them from the config:

1. The retired present-tense phrases are gone — `"needs a proven deep link"` and
   `"on purpose"`, kept verbatim because the point is to catch *that sentence*
   coming back.
2. The header states `"6 of the 9 books"`, computed from
   `config/bookmaker_deeplinks.json`, so flipping a declaration cannot leave a
   stale count in the first line.
3. The header names the mechanism (`config/bookmaker_deeplinks.json`,
   `supports_event_id: false`) and all three route-declaring books.
4. The header keeps `inert`, `zero surebets` and `§3`.

It is named `_plan_header_defects`, not `*_problems`, because
`test_every_doc_predicate_is_proven_capable_of_failing` calls every
`*_problems` predicate with `README`, and this one reads `PLAN.md` — folding it in
would have failed that guard for the wrong reason.

### Proof the check can fail

The companion `test_plan_header_check_fails_when_the_header_regresses_to_the_old_claim`
restores the exact 2026-09-25 line, asserts §3 is still the corrected one (so the
drift is isolated to the header), and requires the check to fire four ways:

```
$ pytest tests/test_readme_claims.py -p no:cacheprovider -o addopts=""
30 passed, 2 warnings in 1.56s
```

A live mutation of the new header (wrong count, `inert` → `proved`, `§3` → `§9`):

```
mutated: count, inert-token, section pointer
E  AssertionError: the status header does not state '6 of the 9 books'; the counts
   must come from config/bookmaker_deeplinks.json, and a flipped declaration has to
   show up here; the status header drops 'inert': the inertness is a bookmaker-side
   fact that did not change, and the figure has to point at its conditions; the
   status header drops '§3': ...
1 failed, 2 warnings in 1.26s
```

`PLAN.md` was restored from backup afterwards and the header mutation confirmed
reverted (`git diff --stat PLAN.md` → `1 insertion(+), 1 deletion(-)`).

---

## I3 — the "202 groups / 1 surebet" figure

### Where the number appears

**Nowhere in committed documentation.** It exists in exactly one place on disk,
and that place is gitignored:

```
$ git ls-files --error-unmatch .superpowers/sdd/2026-09-25-match-and-game-mapping/whole-branch-fix-link-declaration.md
error: pathspec '...whole-branch-fix-link-declaration.md' did not match any file(s) known to git

$ git check-ignore -v .superpowers/sdd/2026-09-25-match-and-game-mapping/whole-branch-fix-link-declaration.md
.superpowers/sdd/.gitignore:1:*	.superpowers/sdd/2026-09-25-match-and-game-mapping/whole-branch-fix-link-declaration.md

$ git ls-files '*.md'
BUILD_SPECIFICATION_V3.md
MARKET_MAPPING.md
PLAN.md
README.md
ROADMAP.md
ScraperLogic.md
TODO.md
docs/superpowers/plans/2026-09-25-match-and-game-mapping.md
docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md
```

The only committed figure was `PLAN.md` §3's "0 of 197 candidate groups verified,
so zero surebets were produced", which is the honest scenario but is measured on
a 1,592-match three-book live feed, not on anything reproducible from the repo.

### The figure does not reproduce

I re-measured all three scenarios on `cache/last_scan.json` with the shipped gate.
Script: `C:/Users/harun/AppData/Local/Temp/opencode/measure_scenarios.py`
(read-only, offline, no network). It reloads the cache per scenario and applies
two rewrites — every `fetched_at` reset to now, and **one uniform shift** on every
kickoff sized so the latest kickoff in the file lands in the future. The uniform
shift is used precisely so every inter-book kickoff delta, which the gate tests,
is preserved exactly.

```
cache scan_time : 2026-08-20T18:26:52.956406  (scan_time key is naive UTC)
now (UTC)       : 2026-09-25T23:13:36.546217+00:00
cache age       : 36 days, 4:46:43.589811
matches         : 6999
books           : ['admiralbet', 'mbet', 'mdshop', 'mozzartbet', 'premier_kladionica', 'sportplus', 'wwin']
matches with deep_link_verified=True: 0

== AFTER: the shipped gate, which reads the declarations ==
  A. links exactly as cached (no proof stored)
    verified groups : 16
    groups holding a DECLARED-ROUTE book: 0 []
    surebets        : 0
  B. + mozzartbet's link proven
    verified groups : 179
    groups holding a DECLARED-ROUTE book: 1 ['mozzartbet']
    surebets        : 0
  C. + every book's link proven (the ceiling)
    verified groups : 516
    groups holding a DECLARED-ROUTE book: 3 ['admiralbet', 'mdshop', 'mozzartbet']
    surebets        : 0

== BEFORE: the same gate with the declaration lookup answering 'nothing declared' ==
  A. links exactly as cached (no proof stored)
    verified groups : 0
    groups holding a DECLARED-ROUTE book: 0 []
    surebets        : 0
  B. + mozzartbet's link proven
    verified groups : 0
    groups holding a DECLARED-ROUTE book: 0 []
    surebets        : 0
  C. + every book's link proven (the ceiling)
    verified groups : 516
    groups holding a DECLARED-ROUTE book: 0 []
    surebets        : 0
```

**Not one of scenario B's numbers reproduces** (report: 202 / 1; measured: 179 /
0). A and C do not reproduce either (26 → 16, 532 → 516).

### Why the report's 1 surebet cannot exist

Its surebet is quoted as `over_under_2_5 egnatia vs lillestrom 0.86%
{'premier_kladionica': 2.15, 'sportplus': 1.9}`. Both prices are genuinely in the
capture, and the arithmetic is right. The pair is the problem:

```
KICKOFF_WINDOW_MINUTES = 120
VERIFIED_KICKOFF_WINDOW_MINUTES = 15

pair A: premier_kladionica Egnatia vs Lillestrom kl=2026-08-20T17:00:00 league='EUROPSKA LIGA'
        ou2.5 = {'Over 2.5': 2.15, 'Under 2.5': 1.75}
pair B: sportplus          Egnatia vs Lillestrom kl=2026-08-20T19:00:00 league='PLAY OFF - KVALIFIKACIJE - FINALE'
        ou2.5 = {'Over 2.5': 1.8, 'Under 2.5': 1.9}
delta min: 120.0
gate: suggested ['kickoff_delta'] swapped: False
leagues: 'europa_league' | 'europa_league'
teams:   egnatia / lillestrom || egnatia / lillestrom
confidence: (1.0, False)

quoted arb 1/2.15 + 1/1.9 = 0.9914321 -> 0.8642%
```

120 minutes apart against a **15**-minute verified window. The matcher's
candidate filter (`KICKOFF_WINDOW_MINUTES = 120`) admits the pair on confidence
1.0, and the gate then refuses it with `kickoff_delta`. That is the pairing
working, not a link problem, and it holds at *any* link state — faking every
link in the book does not produce this surebet either (scenario C: 0 surebets).
`VERIFIED_KICKOFF_WINDOW_MINUTES = 15` was set in `51060ea`, 25 commits before
`122b2a4`, so it was already 15 when the report was written:

```
$ git log -p --follow -S "VERIFIED_KICKOFF_WINDOW_MINUTES" --oneline -- config/settings.py
51060ea feat(mapping): add CertaintyGate with league/kickoff/category/team/orientation/link hard gates
+VERIFIED_KICKOFF_WINDOW_MINUTES = 15  # Max kickoff delta for a `verified` group
```

### The group count is also order-sensitive

`MatchMatcher.group_matches` sorts with a stable sort on league genericity, so
ties keep the input order and the first match to arrive anchors its group. Same
cache, same rewrites, only the order the books are fed in changes:

```
cache order          -> A=  16 B= 179 C= 516
BOOKMAKERS order     -> A=  16 B= 179 C= 516
bookmaker alpha      -> A=  34 B= 101 C= 568
reverse cache order  -> A= 106 B= 205 C= 473
```

So a bare group count is not a property of the feed, and neither 26/202/532 nor
16/179/516 is more "the" number without stating the order.

### Figures I changed, and why

| figure | was | now | why |
|---|---|---|---|
| PLAN.md §3 scenario table | absent | A 16/0, B 179/0, C 516/0 | measured on the stored cache with the shipped gate; reproducible with the script above |
| PLAN.md §3 before-fix column | absent | A 0/0, B 0/0, C 516/0 | same measurement with the declaration lookup answering "nothing declared" |
| `PLAN.md:7` header | "503 tests green" | dropped | superseded by the §3 verification line, which now carries the live count |
| `PLAN.md:7` header | "zero surebets **on purpose**… **needs a proven deep link**" | measured, conditional, past-tense correction | the defect this commit fixed (I1) |
| PLAN.md §3 verification | `pytest` 503 passed + 1 xfailed | `pytest` 572 passed + 1 xfailed (2026-09-26) | 503 was stale before I started; 572 is the verified post-change count |
| report §6 | "202 groups / 1 surebet" | superseded, with the reason | does not reproduce; the surebet is refused on kickoff |

The **cache age** is stated as 36 days, not 37: `scan_time 2026-08-20T18:26:52Z`
against `now 2026-09-25T23:13Z` is 36 days 4h 47m elapsed. 37 is the calendar-date
difference in local time; the elapsed figure is the one that goes in a document.

### What went into `PLAN.md` §3

A measured table with scenario A bolded as **the state this repo is in**, then a
"Conditions, and read them before quoting any of the three" list stating: A is the
only real scenario and **no browser check has been run in this repo** (nothing in
`cache/` carries a `deep_link_verified` flag, and `scripts/verify_deeplinks.py` is
on-demand, never part of a scan — so B and C are arithmetic, not observations);
the two rewrites a surebet count needs, and that a surebet appearing only after
them is not evidence the arbitrage is on; the order sensitivity; and that zero
surebets on a 36-day-old cache is a statement about that cache.

### The report file itself

The bad number also gets a correction banner at the top of
`.superpowers/sdd/2026-09-25-match-and-game-mapping/whole-branch-fix-link-declaration.md`,
so the one place it lives cannot be quoted later. That file is gitignored
(`.superpowers/sdd/.gitignore` is `*`), so this does not enter the commit.

---

## I4 — nothing could catch a wrongly-declared book

`scripts/verify_deeplinks.py:466` still returns `status="skipped"` for any book
whose `supports_event_id` is not `True`. **I did not change it** — the tool's
behaviour is load-bearing for the check-must-not-report-a-failure rule, and
reversing it would make it launch browsers against books that have no route. The
structural check is a test instead, in `tests/test_deeplinks.py`.

### The invariant, and the correction to the review's description of it

> a book declared `supports_event_id: false` whose captured `match.url` differs
> from the `template` … Today mbet, sportplus and wwin all carry exactly their
> declared fallback URL

**That last sentence is not true for mbet**, and a byte comparison would have
failed on correct data:

```
mbet: declared false, n=834
   template   = 'https://www.mbet.ba/'
   url      x834: 'https://mbet.ba/'
   url != template: 834
premier_kladionica: declared false, n=1117
   template   = 'https://www.premier-kladionica.com/ponuda/'
   url      x1117: 'https://www.premier-kladionica.com/ponuda/'
   url != template: 0
sportplus: declared false, n=996
   template   = 'https://www.sportplus.ba/prematch/betting'
   url      x996: 'https://www.sportplus.ba/prematch/betting'
   url != template: 0
wwin: declared false, n=1279
   template   = 'https://wwin.ba/kladjenje/'
   url      x1279: 'https://wwin.ba/kladjenje/'
   url != template: 0
```

`scrapers/mbet.py:532` hard-codes `url="https://mbet.ba/"` — no `www.` — while
`config/bookmaker_deeplinks.json` declares the fallback as
`https://www.mbet.ba/`. Same page, different bytes. (The review's sentence is
also incomplete in the other direction: **four** declared-false books are in the
capture, not three — `premier_kladionica` is there too, at 1,117 matches, and it
*is* byte-identical to its declaration.)

So the comparison folds host case, a leading `www.`, and a trailing slash, and
keeps path and query byte for byte. **The accepted limit, stated in the test's
docstring:** a bookmaker that changed only its fallback's `www.` would not be
caught. That is not a per-event route, so it is not the drift this exists for.

### The three tests

1. `test_a_declared_no_route_book_never_carries_a_per_event_url_in_the_capture` —
   over `cache/last_scan.json`, with `pytest.skip` and a message naming the
   unconditional companion if the corpus is absent, and a **hard failure** (not a
   skip) if the corpus is present but carries no declared-false book, so it can
   never go quietly vacuous.
2. `test_the_declared_no_route_url_check_catches_a_per_event_url[bookmaker]` —
   parametrised over all six declared-false books, always runs, proves the
   predicate is real: the declared fallback is clean, and three plausible
   per-event URL shapes are each reported, one report each. Written per book
   because real per-event routes differ in shape.
3. `test_the_declared_no_route_url_check_ignores_books_that_claim_a_route` — a
   declared-true book carrying a per-event URL and an undeclared book carrying one
   are both clean. A check that fires on those would be noise.

### Proof the corpus check is real

All 1,279 wwin matches in the real cache rewritten to `https://wwin.ba/utakmica/4620444`:

```
mutated 1279 wwin matches to a per-event URL
E  AssertionError: wwin: captured 'https://wwin.ba/utakmica/4620444', declared no
   per-event route with fallback 'https://wwin.ba/kladjenje/'
E  assert ["wwin: captu...jenje/'", ...] == []
1 failed
```

The cache was then restored and verified **byte-identical**:

```
cache restored byte-identical: True
sha256: 8c0afc3929f90282
```

And with the cache removed (a fresh clone), the suite stays green and the corpus
test *skips* rather than passes:

```
$ mv cache/last_scan.json /tmp/ && pytest tests/test_deeplinks.py -rs
SKIPPED [1] tests\test_deeplinks.py:213: ...cache\last_scan.json is absent
(cache/*.json is gitignored); this corpus check needs a real scan. The predicate
itself is covered unconditionally by
test_the_declared_no_route_url_check_catches_a_per_event_url
22 passed, 1 skipped in 0.60s
```

`cache/last_scan.json` was moved back and its hash re-checked.

---

## M1 — `/api/health`'s `unverified_links` used the wrong predicate

`server/api.py:1429` now reads `not declares_no_event_id(...)`. The comment above
it is true as written for the first time, and says *why* the two predicates are
not interchangeable.

```
$ git diff server/api.py
-            and supports_event_id(str(match.get("bookmaker", "")))
+            and not declares_no_event_id(str(match.get("bookmaker", "")))
```

The existing `test_health_includes_new_diagnostics` still expects
`unverified_links == 1` and passes unchanged — as it must, since the shipped
config declares all nine books and the two predicates agree on every one of them.
That is precisely why the wrong one looked right.

### The regression test

`test_health_counts_an_undeclared_books_link_as_a_blocker` empties
`scrapers.common._deeplink_cache` via `monkeypatch`, which is the one piece of
state the gate *and* the counter both read — so it takes the real code path
rather than replacing the predicate under test. It is also the shape of the
accident: a declaration is removed from the JSON, the process does not restart,
and both are answering from the old map.

```
$ pytest tests/test_candidates_api.py -p no:cacheprovider -o addopts=""
17 passed, 3 warnings in 3.78s
```

Assertion: 1 with the config as shipped (mdshop's unproven link is the only real
blocker; wwin's is settled by its declaration), then **2** with nothing declared
— because the gate blocks both unproven matches. Under the old predicate the
second number stays at 1.

**This test caught a real bug in my own M3 code** before I got to M3: my first
`effective_deeplink_declarations` mapped a declared `false` to `null`, so
`supports_event_id` and `declared_no_event_id` could both be falsey for a book
that plainly says `false`. Fixed to `raw if isinstance(raw, bool) else None`, with
the reason in a comment. This is worth flagging: the field is new, and the first
implementation of it was wrong in exactly the way the codebase's history predicts.

---

## M2 — two stale line references

Both cited `engine/certainty.py:20`; the assignment moved to line 27 in
`122b2a4`:

```
$ grep -n "HARD_REJECT_REASONS = " engine/certainty.py
27:HARD_REJECT_REASONS = frozenset({"league_mismatch", "category_mismatch", "orientation_unresolved"})
```

`README.md` now names the symbol and says why it does not cite a line. The
doc-claim test asserts the **shape** of the citation and resolves the symbol, so
no future edit can make it stale:

`test_readme_cites_hard_reject_reasons_by_symbol_and_not_by_line` —
(1) no `` `engine/certainty.py:<digits>` `` anywhere in README.md, and
(2) exactly one module-level `HARD_REJECT_REASONS` assignment found by `ast`.

Proof it can fail, by putting the line-number citation back:

```
mutated: re-added a line-number citation
>       assert cited == [], (
E       assert ['20'] == []
1 failed, 2 warnings in 1.26s
```

README.md restored from backup afterwards.

---

## M3 — the operative declaration is now observable

`effective_deeplink_declarations(bookmakers=None)` in `scrapers/common.py:534`,
built from the same `_load_deeplink_config()` the gate reads. Each entry carries
`configured`, `supports_event_id` and `declared_no_event_id`.

The third field is the reason there are three: `supports_event_id` and
`declared_no_event_id` are not complements, and `declared_no_event_id` alone
cannot express "unconfigured" — which is the state a removed declaration puts a
book in, and the state `deep_link_declarations` most has to be able to say.

Live output of the new `/api/health` field:

```
$ "C:/.../venv/Scripts/python.exe" -c "
import asyncio, json
from config.settings import BOOKMAKERS
from server.api import health
print(json.dumps(asyncio.run(health())['deep_link_declarations'], indent=1))"
{
 "mozzartbet": { "configured": true, "supports_event_id": true,  "declared_no_event_id": false },
 "mdshop":     { "configured": true, "supports_event_id": true,  "declared_no_event_id": false },
 "admiralbet": { "configured": true, "supports_event_id": true,  "declared_no_event_id": false },
 "betole":     { "configured": true, "supports_event_id": false, "declared_no_event_id": true  },
 "mbet":       { "configured": true, "supports_event_id": false, "declared_no_event_id": true  },
 "sportplus":  { "configured": true, "supports_event_id": false, "declared_no_event_id": true  },
 "evlbet":     { "configured": true, "supports_event_id": false, "declared_no_event_id": true  },
 "premier_kladionica": { "configured": true, "supports_event_id": false, "declared_no_event_id": true },
 "wwin":       { "configured": true, "supports_event_id": false, "declared_no_event_id": true  }
}
```

(whitespace condensed for width; the raw output is one field per line)

`test_health_echoes_the_declaration_map_the_gate_is_using` asserts the map covers
every `BOOKMAKERS` key, the three-field shape per entry, that `supports_event_id`
matches a `_ROUTE_BOOKS` set read through the same loader (no second copy of the
config to drift), that `declared_no_event_id` equals what the gate's own
`declares_no_event_id` returns for every book, and that an unconfigured book
comes back as `configured: false` rather than silently omitted.

`README.md` documents both new/changed health fields under *Health Check*.

I did **not** add cache invalidation. The item asked for observability, and a TTL
or mtime check on a safety gate's config is a behaviour change to the gate's
inputs; that is a separate decision with its own review.

---

## Full verification

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -p no:cacheprovider -rs -o addopts=""
572 passed, 1 xfailed, 3 warnings in 19.82s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
Success: no issues found in 59 source files
```

**572 passed, 1 xfailed, 0 failed, 0 errors, 0 skipped.** Baseline before this
work was **560 passed, 1 xfailed**; +12 tests, all of them new. `-rs` printed no
skips, so the corpus test ran against the real cache rather than skipping.

The thirteen new/extended tests:

```
tests/test_deeplinks.py::test_a_declared_no_route_book_never_carries_a_per_event_url_in_the_capture PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_catches_a_per_event_url[betole] PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_catches_a_per_event_url[evlbet] PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_catches_a_per_event_url[mbet] PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_catches_a_per_event_url[premier_kladionica] PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_catches_a_per_event_url[sportplus] PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_catches_a_per_event_url[wwin] PASSED
tests/test_deeplinks.py::test_the_declared_no_route_url_check_ignores_books_that_claim_a_route PASSED
tests/test_candidates_api.py::test_health_counts_an_undeclared_books_link_as_a_blocker PASSED
tests/test_candidates_api.py::test_health_echoes_the_declaration_map_the_gate_is_using PASSED
tests/test_readme_claims.py::test_readme_cites_hard_reject_reasons_by_symbol_and_not_by_line PASSED
tests/test_readme_claims.py::test_plan_declares_phase_four_done_with_the_headline PASSED
tests/test_readme_claims.py::test_plan_header_check_fails_when_the_header_regresses_to_the_old_claim PASSED
```

---

## Concerns

1. **The review's I4 premise was wrong in a detail, and a byte-equality version of
   the check would have shipped a red test on correct data.** MBet's scraper
   hard-codes a `www.`-less host, so its captured URL is not byte-equal to its own
   declared fallback. The check folds the alias. If the intent really was strict
   byte equality, the fix belongs in `scrapers/mbet.py:532` or in the declared
   fallback — and that is a declaration edit, which needs its own review. I did
   not do it.

2. **The review said three declared-false books are in the capture; there are
   four** (`premier_kladionica` at 1,117 matches, and byte-identical). Harmless
   here, but it means the review's spot-check did not look at all four.

3. **The review said `202 groups / 1 surebet` "was verified against
   `cache/last_scan.json`".** The surebet cannot be produced by the shipped
   pipeline at any link state — its two matches are 120 minutes apart against a
   15-minute verified window. The prices are real; the pairing is refused. I have
   not established *how* the report's script produced it, only that
   `group_matches` + `find_surebets` cannot. If that script is still around it is
   worth finding out, because something in it is not measuring the pipeline.

4. **`MatchMatcher.group_matches` is order-sensitive** — 16/34/106 for the same
   feed. That is pre-existing and outside this commit, but it means no group
   count in any document is a fact until the input order is stated. I documented
   it rather than fixing it.

5. **`_deeplink_cache` still never invalidates.** M3 makes the stale value
   *visible*; it does not make it stop being stale. An operator who edits the JSON
   and restarts sees the new map, and one who does not restart now sees the old
   map in `/api/health` — which is the improvement, but the footgun is intact.

6. **`deep_link_declarations` adds a public field to `/api/health`** that echoes
   configuration. It is not a secret (the JSON is in the repo) and
   `unverified_links` was already there, but the endpoint is unauthenticated and
   this is more surface than a counter. Say the word if you would rather it went
   behind `Depends(_require_api_key)`.

7. **I wrote "36 days" where the brief said 37.** The brief's 37 is the
   local-calendar-date difference; elapsed time from `scan_time 2026-08-20T18:26:52Z`
   to `2026-09-25T23:13Z` is 36 days 4h 47m. I used the elapsed figure and left
   the 37 out of the document.

8. **The `test_..._catches_a_per_event_url` mutation uses invented URL shapes**
   (`/match/<id>`, `?event=<id>`, `/<book>/<id>`), not a real bookmaker's real
   route, because the whole point is that no declared-false book has one. If a
   bookmaker ships something stranger, the check fires on the path anyway — the
   shapes only have to differ from the fallback, which is the mechanism.

9. **`scripts/verify_deeplinks.py:466` still skips declared-false books.** The
   item flagged the skip as the reason nothing can catch a wrong `false`; I added
   the structural check rather than changing the tool. The browser
   re-verification the implementer named is still the only way to learn that a
   declared-false book now *has* a route but no scraper emits it yet — the
   structural check only catches the opposite drift, where the bookmaker ships
   routes and the scraper already uses them.
