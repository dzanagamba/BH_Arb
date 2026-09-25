# Task 9 report — Generate `MARKET_MAPPING.md` from the registry

**Status:** DONE_WITH_CONCERNS (all constraints met; concerns are documentation-freshness
observations, listed at the end)

**Commit:** `ee15a36975a46e571f80283cfca2c7232e8e1a33` (`ee15a36`)
**Branch:** `master` (in place — no worktree, no branch)
**Working tree after commit:** clean

---

## 1. What changed

| File | Change |
| --- | --- |
| `scripts/generate_market_mapping_doc.py` | **new**, 283 lines. Renders the generated block from `config/bookmaker_markets.json` and splices it into `MARKET_MAPPING.md`. |
| `tests/test_registry_parser_consistency.py` | **new**, 386 lines, 21 tests. Registry ↔ doc consistency + narrative-preservation regressions. |
| `MARKET_MAPPING.md` | **modified, +137 / −0.** Pure append: a separator + editorial note + the generated section. No hand-written line was touched. |

No other file was modified. `engine/market_registry.py` and
`config/bookmaker_markets.json` (Task 4) are untouched, so Tasks 10–13 see no
unexpected churn.

### The generated section

The block between the markers contains:

1. **"Mapped markets"** — one row per registry `book / mode / market`:
   `Bookmaker | Mode | Market | Source IDs | Outcome labels | Min legs | Line | Settlement`.
   9 bookmakers, 85 rows. Both `prematch` and `live` for every book.
2. **"Deliberately unmapped source IDs"** — a table of the registry's `_excluded`
   block (8 books), with a paragraph explaining that these offers are recognised
   and rejected on purpose so they cannot reach the arbitrage engine, and that a
   name pattern applies to any ID matching it.

`_excluded` is skipped as a bookmaker (`book.startswith("_")`) and rendered in
its own section instead, so it never appears as a bookmaker row.

### Registry-resolved, not raw-JSON values

The brief's script walked the raw JSON and printed `spec.get("labels", [])`. That
would have documented an empty `Outcome labels` cell for every Over/Under row,
because the O/U entries in the JSON carry no explicit `labels` — the labels come
from `_DEFAULT_LABELS` inside `MarketRegistry.__init__`. The generator therefore
resolves each entry **through the loader** using only the public API:

```python
registry.ids_for(book, mode, market_type)   # IDs registered for the type
registry.specs_for(book, mode, source_id)   # specs, filtered by market_type
```

so the doc shows what the code will actually do (`Over 2.5, Under 2.5`,
`min_legs 2`, `settlement full_time`), not what the JSON literally spells. It also
means the brief's `from engine.market_registry import MarketRegistry` import is
actually used instead of being dead.

If the JSON and the loader ever disagree (an entry that resolves to zero specs,
or to conflicting specs for one market type), `_specs_for` raises `ValueError` and
the generator exits 2 rather than emitting a plausible-looking lie.

---

## 2. Replace or preserve? — **PRESERVED**

### Decision

The hand-written narrative is **preserved verbatim**; the generated table is
**appended below it** inside a marker pair. The file was **not** overwritten.

### Why

The brief's generator opens `MARKET_MAPPING.md` with `"w"` and writes 7 lines
of preamble plus the table. Executing that literally would have deleted all 200
lines of hand-written content, and almost all of it is **not derivable from the
registry**:

- Which live endpoint each book uses and how it is filtered
  (`getwebevents?isLive=true`, `events_cached?live=true`, `betting/matches` with
  `date:"live"`, SportPlus's `ML/` team-prefix stripping, MBet's `finished` events,
  Mozzartbet's "feed also returns upcoming fixtures").
- The post-mortem of the Admiralbet bug: *"`1639` is the real Admiralbet 1X2 offer.
  The old `136 -> double_chance` mapping was incorrect and caused qualification
  odds to pollute cross-market arbitrage."* That sentence is the only record of
  **why** ID 136 is excluded, and `test_nsoft_136_advance_market_is_rejected` in
  `tests/test_market_mapping.py` depends on the same premise.
- Why EVLBet is absent from live mode ("`Offers` always empty") and why Betole
  live reuses prematch pick codes.
- Premier Kladionica's `PrSync` JSON-RPC section indices, the positional
  `dogTipK` row layout, and the `setTip`/`setTipVar`/`setTipTip` name/code split.
- SportPlus's duplicate-O/U consolidation rule and the unsupported O/U threshold
  exclusion (4.5/5.5/6.5).
- Mozzartbet's live aliases (`2+/0-1`, `3+/0-2`, `4+/0-3`) and the `gg3+` combo
  exclusion.

The registry stores `ids`, `labels`, `min_legs`, `line`, `settlement`. It stores
**none** of the above. Replacing the file would be a net information loss on the
one document an operator consults before touching a parser — and other files
already point at it: `README.md:87`, `ScraperLogic.md:10`, `PLAN.md:87` and
`PLAN.md:111` reference it as the audit record, and `PLAN.md:145` requires
"`MARKET_MAPPING.md` updated with any new market" as a definition of done.

Splitting the file is also the semantically honest outcome: **the ID tables are
the part that drifts, so only the ID tables are generated.** The narrative is
stable knowledge, so it stays hand-maintained.

### Proof of preservation

```
$ git show HEAD~1:MARKET_MAPPING.md > /tmp/mm_head.md   # pre-task version
$ python -c "import pathlib; head=...; now=...; print(now.startswith(head))"
hand-written narrative preserved verbatim: True
head lines: 200 -> now lines: 337
```

and the committed diff is **137 insertions, 0 deletions** — git's own record that
not one existing byte was removed or rewritten.

The seam is explicit to a human reader:

```markdown
---

Everything above this line is hand-written analysis of the live bookmaker
catalogs: live-feed notes, settlement reasoning and the per-book audit tables.
Edit it freely; the generator below never touches it.

The table below is generated from `config/bookmaker_markets.json`, the same file
`engine/market_registry.py` loads, so the documented IDs cannot drift from the
IDs the parsers actually use. When the table and the analysis above disagree,
the registry is authoritative.

<!-- GENERATED FROM bookmaker_markets.json -->
```

---

## 3. How a future regeneration cannot clobber the preserved narrative

Four independent layers, weakest first:

**(a) The generator only ever writes inside the markers.**
`splice()` finds `BEGIN_MARKER` and `END_MARKER` and returns
`existing[:start] + block + existing[end + len(END_MARKER):]`. The bytes before
and after the markers are copied through untouched. It is the only function that
writes to the file.

**(b) No fallback path — the generator refuses to guess.**
If the marker pair is missing, unbalanced, reversed, or duplicated, `splice()`
raises `MarkerError` and `main()` prints an error and returns **2 without opening
the file for writing**. There is deliberately no "create the file fresh" or
"append the block" fallback, because either of those would be the exact path by
which a future contributor could silently destroy the narrative. The only remedy
is a human re-adding the markers.

Verified end-to-end (markers stripped from the real file, generator run):

```
$ python scripts/generate_market_mapping_doc.py ; echo "exit=$?"
error: <!-- GENERATED FROM bookmaker_markets.json --> is missing from MARKET_MAPPING.md; refusing to rewrite the file because the hand-written sections have no protected boundary
exit=2
md5 before=271883e55bfc2eca786be0afcd89095d
md5 after =271883e55bfc2eca786be0afcd89095d
FILE UNTOUCHED - narrative safe
```

**(c) A test locks the splice semantics in place.**
`test_splice_replaces_only_the_generated_block` proves prose *and* trailing
content outside the markers survive while the block is replaced.
`test_splice_refuses_to_touch_a_doc_without_exactly_one_marker_pair` is
parametrised over 5 malformed layouts (no markers / no end / no begin / reversed /
duplicated) and asserts `RuntimeError` every time.
`test_splice_preserves_narrative_around_the_markers` asserts splicing the current
block into the current doc is a no-op **and** that the narrative above the marker
is non-empty — so the narrative cannot be quietly deleted and re-spliced around.

**(d) A test fails the build if the committed doc is stale.**
`test_committed_doc_is_up_to_date_with_the_registry` re-renders and compares, so a
registry change without a regeneration is a red test, not drift. This is also
available standalone for CI via `--check` (exit 1 on drift, exit 0 on sync).

Line endings are handled too: the generator detects the file's existing dominant
EOL from its raw bytes and writes with the same one, so a `core.autocrlf=true`
checkout cannot turn a one-line doc change into a 337-line whole-file diff.
Verified: a CRLF'd file regenerates with 337 CRLF and 0 bare LF.

---

## 4. TDD sequence followed

**Step 1 — failing test.** Wrote `tests/test_registry_parser_consistency.py`.

**Step 2 — confirmed red for the right reason.** First run gave a *collection
error* (`ModuleNotFoundError: No module named 'scripts.generate_market_mapping_doc'`),
which would have hidden whether the doc actually carries a generated section. So
I made the generator import **lazy** (`importlib.import_module` inside
`_generator()`) and re-ran:

```
FAILED tests/test_registry_parser_consistency.py::test_generated_section_marker_is_present
...
18 failed, 3 passed in 1.26s
```

and the headline failure was exactly the intended one:

```
E  AssertionError: <!-- GENERATED FROM bookmaker_markets.json --> missing from MARKET_MAPPING.md
E  assert -1 != -1
tests\test_registry_parser_consistency.py:60: AssertionError
```

The 3 that passed are the brief's own three checks — `test_registry_matches_documented_market_mapping`
passed only because the hand-written doc happens to mention `135`, which is
precisely the scenario the brief predicted.

**Step 3 — implement.** Generator written; markers + seam added to
`MARKET_MAPPING.md`; generator run.

**Step 4 — green.** 21/21 in the task module.

**Step 5 — mutation-checked.** A green test proves nothing if it cannot fail, so I
broke the world seven ways and confirmed each was caught:

| # | Mutation | Result |
| --- | --- | --- |
| 1 | Registry ID `135` → `999`, doc not regenerated | 4 failed (incl. `test_committed_doc_is_up_to_date_with_the_registry`) |
| 2 | `END_MARKER` deleted from the doc | 11 failed |
| 3 | Hand-edit inside the generated block (`135` → `4242`) | 11 failed |
| 4 | `_excluded` renamed to a real book key | loader raises — confirms the `_` prefix is the only thing separating it |
| 5 | Second reserved `_notes` key added to the registry | generator emitted **0** occurrences → skipped correctly, 21 passed |
| 6 | `END_MARKER` deleted, then generator run | exit 2, refused to write |
| 7 | Both markers deleted, then generator run | exit 2, **md5 identical before/after** |

**Step 6 — full suite + lint + types**, then commit.

---

## 5. Test coverage (21 tests)

**The brief's three, kept verbatim** (minus two unused imports that ruff rejects —
`import json` and the unused `cfg` loop variable; the loop was reduced to `for bid in BOOKMAKERS`,
which asserts exactly the same thing):

1. `test_registry_file_is_valid_and_complete` — every book in `BOOKMAKERS` has a prematch 1X2.
2. `test_nsoft_advance_id_136_not_in_registry` — the Admiralbet bug guard.
3. `test_registry_matches_documented_market_mapping` — brief's substring check.
4. `test_generated_section_marker_is_present` — the brief's Step-2 marker assertion.

**Strengthened to meet the global constraint** ("every bookmaker's prematch and
live market IDs must be represented"). The brief only checked mdshop prematch 1X2
via substring matching, which is trivially satisfied by `"1"` appearing anywhere:

5. `test_documented_market_rows_match_registry_defaults` — **bidirectional
   `Counter` equality** over `(book, mode, ids, labels, min_legs, line, settlement)`
   for all 85 rows. A row the registry does not declare fails as loudly as a
   missing one. It re-derives expectations from `ids_for`/`specs_for` itself and
   deliberately does **not** import the generator's `MARKET_TYPE_LABEL`, so the
   market-name column stays prose while the numbers stay the contract.
6. `test_every_bookmaker_mode_and_market_id_is_documented` — all 9 books, both
   modes, exact ID-set equality per book/mode plus row-count parity. Declared-but-empty
   modes (`evlbet`/`live`, `betole`/`live`) must produce no rows, and are explained
   by the preserved narrative.
7. `test_every_bookmaker_appears_in_the_generated_table`.
8. `test_documented_market_rows_...` is backed by `_documented_market_rows`, which
   parses the markdown table, so the *rendered* doc — not the generator's
   intermediate objects — is what gets asserted on.

**`_excluded` handling:**

9. `test_excluded_block_is_not_rendered_as_a_bookmaker` — `_excluded` is not a row.
10. `test_excluded_market_ids_are_documented` — exact set equality per book, so the
    operator-facing table cannot silently drop a pattern.
11. `test_excluded_ids_do_not_leak_into_mapped_rows` — `136` must never appear in a
    mapped row for `mdshop`/`admiralbet`, tying the doc back to the original bug.

**Regeneration safety:** tests 12–19 are described in §3.

**Cosmetic:** 20. `test_generated_market_names_are_human_readable` (no raw enum
values leak into the Market column), 21. `test_generator_never_emits_a_table_row_for_a_dashed_key`.

---

## 6. Commands and full output

### 6.1 Generator — idempotent (run twice)

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/generate_market_mapping_doc.py ; echo "exit=$?"
MARKET_MAPPING.md already in sync; no write needed
exit=0
MARKET_MAPPING.md already in sync; no write needed
exit=0
```

First run (before the second, in the same session) printed:

```
Wrote C:\Users\harun\OneDrive\Documenti\surebetmuse12\MARKET_MAPPING.md (337 lines)
```

### 6.2 `--check` (CI gate)

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/generate_market_mapping_doc.py --check ; echo "exit=$?"
MARKET_MAPPING.md is in sync with config/bookmaker_markets.json
exit=0
```

### 6.3 Task test module — **21 passed**

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 21 items

tests\test_registry_parser_consistency.py .....................          [100%]

============================= 21 passed in 0.69s ==============================
```

### 6.4 FULL SUITE — **239 passed, 0 failed**

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
239 passed, 3 warnings in 4.75s
```

**Explicit passed-test count: 239 passed, 0 failed, 0 errors, 0 skipped**
(218 pre-existing + 21 new). The 3 warnings are pre-existing FastAPI
`on_event` deprecations from `server/app.py:35`, unrelated to this task.

### 6.5 Ruff

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!
exit=0
```

### 6.6 Mypy

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
tests\test_candidates_api.py:249: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 50 source files
exit=0
```

Mypy initially reported 4 errors in the new files (an un-annotated `specs` dict,
and `dict[str, object]` making `row["ids"]` non-iterable). All four were fixed
by annotating `dict[tuple[Any, ...], MarketSpec]` and using `dict[str, Any]` for
the parsed rows; the repo is now at **0 errors**. Ruff initially reported one
`F841` (unused `excluded` local) — also fixed.

### 6.7 Diff stat — narrative preservation

```
$ git diff --cached --stat
 MARKET_MAPPING.md                         | 137 +++++++++++
 scripts/generate_market_mapping_doc.py    | 283 ++++++++++++++++++++++++++++++
 tests/test_registry_parser_consistency.py | 386 ++++++++++++++++++++++++++++++
 3 files changed, 806 insertions(+)
```

`MARKET_MAPPING.md`: **137 insertions, 0 deletions.**

### 6.8 Commit

```
$ git commit -m "docs: generate MARKET_MAPPING.md from the market registry and assert consistency"
ee15a36 docs: generate MARKET_MAPPING.md from the market registry and assert consistency
$ git rev-parse HEAD
ee15a36975a46e571f80283cfca2c7232e8e1a33
$ git status --short
(clean)
```

---

## 7. Deviations from the brief

1. **The brief's script is restructured into functions with a `main()` guard.**
   The brief's version is module-level code with no entry point, which makes it
   untestable and (unlike `scripts/generate_mappings.py`) non-importable. It also
   imports `MarketRegistry` and never uses it — dead. `build_section()`,
   `splice()`, `render()` and `main()` replace it, keeping the same
   `python scripts/generate_market_mapping_doc.py` CLI.

2. **Values are resolved through `MarketRegistry`, not read raw from the JSON.**
   Reason in §1. The observable difference: O/U rows document their real
   `Over X.5 / Under X.5` labels and `settlement: full_time` instead of blanks and
   the loader default.

3. **`splice()` instead of a full-file write — the core deviation, and the
   central design decision.** Justified in §2/§3. The brief's `"w"` write would
   have deleted 200 lines of irreplaceable audit content.

4. **Added a `Settlement` column and an `_excluded` table.** The brief had 7
   columns and no `_excluded` output. `settlement` is in the registry, is what
   distinguishes a full-time market from a look-alike, and was a whole paragraph
   of hand-written prose. The `_excluded` table is the operator-facing surface the
   task context asked for.

5. **Added `--check`.** The brief's step-5 commit would leave a stale doc possible
   between registry edits. `--check` gives CI a one-command gate; the same
   assertion also runs in the test suite.

6. **Test file: removed `import json` and the unused `cfg` variable** from the
   brief's first test, and replaced the brief's substring-only doc check with
   structured table parsing across all books/modes (reason in §5).

7. **Book/mode order follows the registry's JSON order**, not alphabetical. The
   registry deliberately groups the two NSoft books (`mdshop`, `admiralbet`)
   together; alphabetical order would interleave them with unrelated platforms.
   `json.load` preserves order, so output stays deterministic
   (`test_build_section_is_deterministic`).

8. **The exact brief marker string is used.** Note the brief's own generator emits
   `<!-- GENERATED FROM bookmaker_markets.json — do not edit by hand. -->`, which
   does **not** contain the substring `<!-- GENERATED FROM bookmaker_markets.json -->`
   that the brief's test asserts — the brief is internally inconsistent here. I
   emit the exact bare marker the test requires, and carry the "do not edit by
   hand" warning in a separate adjacent comment inside the block.

Nothing in the brief was dropped without cause; the brief's three tests and its
marker assertion are all present and passing.

---

## 8. Concerns

1. **Stale fact left in the preserved narrative (not fixed on purpose).**
   `MARKET_MAPPING.md:3` still says *"the canonical market audit for the **seven**
   configured bookmakers"*, but `config/settings.BOOKMAKERS` has **nine**. I left
   it byte-identical so the "narrative preserved verbatim" claim is verifiable by
   diff, and so this task stays scoped to generation. It is a one-word fix
   (`seven` → `nine`) that someone should make in a follow-up.

2. **Narrative prose can now disagree with the generated table and nothing detects
   it.** The table is machine-checked against the registry; the prose is not
   machine-checked against anything. E.g. the WWIN section still describes the
   three-group endpoint fetch (`95,6` / `3` / `11`), which is a scraper fact the
   registry does not model. I added the sentence *"When the table and the analysis
   above disagree, the registry is authoritative"* to make the precedence explicit,
   but a prose claim that silently rots is still a real risk. A future task could
   extract a handful of high-value prose claims into the test suite.

3. **The generator is not wired into CI.** `--check` exists and the test suite
   enforces it, but no CI config in this repo runs `pytest` on push yet. If CI is
   never added, the guarantee is only as good as someone running the suite.

4. **Adding a *new bookmaker* requires hand work.** The generated table and tests
   pick up a new registry book automatically, but `MARKET_MAPPING.md` has no
   per-book narrative section for it. Not a defect, just a reminder that the
   narrative half of the file is now the manual part of adding a book.

5. **The generator imports the whole app package** (`engine.market_registry` →
   `models.schemas` → pydantic). It is therefore not runnable in a
   dependencies-free environment, unlike a pure `json`-only doc script. This is
   the deliberate cost of resolving values through the loader (§7.2) — the
   alternative is a doc that lies about defaults.

6. **Shared O/U IDs make the row↔registry mapping non-injective.** `mdshop`
   prematch `137`/`138` appear as three rows (1.5/2.5/3.5) from three distinct
   `MarketSpec` objects. The generator and the test both de-duplicate on
   `(ids, line)`, and both raise/assert if a market type resolves to conflicting
   specs — so a future registry change that makes the mapping ambiguous fails
   loudly instead of emitting an arbitrary row. Worth remembering if a new
   bookmaker shares an ID across lines with different `min_legs`.

7. **The 3 pytest warnings are pre-existing** (`server/app.py:35`, FastAPI
   `on_event` deprecation) and were left alone — out of scope for a docs task.

---

# FIX ROUND 1 (of 5)

**Commit:** `6398eedd4dc1b54c57c9d292edce5e6d7d6b3c3c` (`6398eed`), a single
commit on top of `ee15a36`. An intermediate `wip:` commit was squashed away so the
round is one reviewable diff.
**Working tree after commit:** clean.
**Result:** 359 passed / 0 failed / 0 errors / 0 skipped; ruff clean; mypy clean.

Confirmed and left untouched: refusing the brief's destructive `"w"` rewrite, the
bare-marker fix, idempotence, the bidirectional generated-table test, `--check`,
and the 5 malformed-marker cases.

## Test inventory: 141 tests (was 21)

| Test | Count | New? |
| --- | --- | --- |
| `test_registered_ids_resolve_through_their_own_books_parser` | 85 | **new** (one per registry declaration) |
| `test_hand_written_narrative_anchor_survives` | 21 | **new** (one per anchor phrase) |
| `test_no_hand_maintained_id_table_survives_beside_the_generated_one` | 8 | **new** (one per retired table header) |
| `test_every_bookmaker_has_a_parser_resolution_probe` | 1 | **new** |
| `test_parser_resolution_returns_the_declared_spec_not_just_any_spec` | 1 | **new** |
| `test_mapped_and_excluded_ids_are_disjoint` | 1 | **new** (the minor) |
| `test_intro_bookmaker_count_matches_settings` | 1 | **new** |
| `test_intro_market_type_claims_match_the_registry` | 1 | **new** |
| `test_generated_table_is_the_authority_and_comes_first` | 1 | **new** |
| `test_generated_market_names_are_human_readable_and_carry_the_enum_key` | 1 | changed (replaces `..._human_readable`) |
| `test_splice_preserves_narrative_around_the_markers` | 1 | strengthened |
| pre-existing (markers, doc table, `_excluded`, splice refusal, determinism) | 20 | unchanged |

---

## Finding 1 — registry↔parser coverage (was unmet)

### What the new test does

`test_registered_ids_resolve_through_their_own_books_parser` is parametrised over
all **85 registry declarations**. For each one it calls **that bookmaker's own
parser resolution function** with **every source ID the registry declares for it**,
and asserts the call returns a `MarketSpec` rather than `None`, that the spec's
`bookmaker` and `mode` are the ones asked about, and that resolving it recorded no
unmapped-market diagnostic.

`test_parser_resolution_returns_the_declared_spec_not_just_any_spec` closes the
loophole: a resolver that returns *some* spec is not enough, it must return the
**declared** spec — same `market_type`, `labels`, `min_legs`, `line` and
`settlement`. That is the shape of the original NSoft `136` bug, where an ID
resolved to a plausible but wrong market.

`test_every_bookmaker_has_a_parser_resolution_probe` asserts every key in
`config/settings.BOOKMAKERS` has a probe, so adding a book without wiring the test
fails loudly.

### The nine resolution paths, and how each is reached

| Book | Resolution path exercised |
| --- | --- |
| `mdshop`, `admiralbet` | `scrapers.common.nsoft_registered_spec` — the NSoft `betTypeId` + `sbv` lookup `parse_nsoft_bets` performs |
| `betole` | `scrapers.betole.betole_registered_spec` |
| `evlbet` | `scrapers.evlbet.evlbet_registered_spec` |
| `mbet` | `scrapers.mbet._registered_spec` (already module-level) |
| `mozzartbet` | `scrapers.mozzartbet._registered_spec` (already module-level) |
| `premier_kladionica` | `scrapers.premier_kladionica._registered_spec` (already module-level) |
| `sportplus` | `scrapers.sportplus._registered_spec` (already module-level) |
| `wwin` | `scrapers.wwin.wwin_registered_spec` |

Five of the nine had their resolution step as a **nested closure** inside the parse
function (`betole`, `evlbet`, `wwin`) or inline in a branch (`common.py`'s
`parse_nsoft_bets`), so it was not importable and not testable. I lifted each to
module scope and made the original call site **delegate** to the new function, so
there is still exactly one implementation and no behaviour change. Proof: the
suite went 239 → 239 immediately after the refactor, before any new test existed.
EVLBet's literal `"12005"` default also became the named constant
`DEFAULT_BASIC_OFFER_ID` (same value, same fallback order).

### What it explicitly does NOT prove

- **It does not prove a real bookmaker feed emits these IDs.** No network call, no
  captured payload, no JSON fixture. A registry entry can be perfectly reachable
  and still be fiction.
- **It cannot detect a wrong ID.** Registry and parser read the same source of
  truth, so a wrong ID is wrong *consistently* in both. Verified: changing `mdshop`
  prematch 1X2 from `135` to `999` leaves all 85 reachability cases green and fails
  only the doc-consistency tests. Catching a wrong ID is the doc tests' job, and is
  exactly what Task 11's captured payloads are for.
- **It does not prove the call site's payload shape.** It calls the resolution
  function with the right arguments; it does not prove `MDShopScraper._parse_bets`
  passes `mode="live"` for live. That layer is already covered elsewhere by
  `tests/test_market_mapping.py` and `tests/test_live_mode.py`, which drive the
  real parse entry points with synthetic NSoft, MBet, SportPlus, Mozzartbet,
  Betole and EVLBet payloads. Between the two files the gap is closed, but neither
  alone would close it, and **neither substitutes for real captured feeds**.
- **It does not prove the resulting market is usable.** No odds, no legs, no
  arbitrage.
- **The betole registry rows are supersets.** `betole prematch over_under_1_5`
  declares `137`/`138`/`3` alongside its own `242`/`21`; the betole parser's
  hardcoded pick table only ever reads `242`/`21`. Those extra codes are reachable
  through `betole_registered_spec` but never exercised. Documented in the Betole
  section rather than encoded as expected behaviour.

### Mutation-tested

| Mutation | Caught by |
| --- | --- |
| Break `nsoft_registered_spec` to return `None` | 40+ `..._resolve_through_...` cases |
| Point the mozzartbet probe at `wwin` | 12 cases + the declared-spec test |
| Make `wwin_registered_spec` return wrong labels | `test_parser_resolution_returns_the_declared_spec_not_just_any_spec` |
| Map `136` while it is also `_excluded` | `test_mapped_and_excluded_ids_are_disjoint` |
| Add a registry book with no probe | `test_every_bookmaker_has_a_parser_resolution_probe` |

---

## Finding 2 — stale facts corrected

Both corrections are **above** the generated markers, so the splice is untouched by
design. The wording was changed to be *self-verifying* rather than merely true once.

**Was** (lines 3-5): *"the canonical market audit for the **seven** configured
bookmakers. The scanner emits only the **six** `MarketType` values in
`models/schemas.py`."*

**Now:**

> This is the canonical market audit for the **nine** configured bookmakers in
> `config/settings.BOOKMAKERS`. The registry-backed scanner maps **six of the nine**
> `MarketType` values in `models/schemas.py`; the remaining three
> (`first_half_1x2`, `first_half_ou`, `asian_handicap`) are experimental and are
> parsed directly by individual scrapers rather than declared in the registry.

Two new tests stop it rotting again:

- `test_intro_bookmaker_count_matches_settings` parses the number word out of the
  intro and asserts it equals `len(BOOKMAKERS)`, and that the generated table's
  book set equals `BOOKMAKERS`.
- `test_intro_market_type_claims_match_the_registry` asserts `len(MarketType) == 9`,
  that the registry maps exactly 6, and that **each of the three non-registry types
  is named in the intro** — the specific omission that made "six values" wrong.

Mutation-verified: reverting the intro to "seven configured bookmakers" fails with
`intro says seven configured bookmakers, settings has 9`.

I accepted the reviewer's judgement that byte-identical preservation was review
evidence, not a product invariant. It stays on the record honestly: the round-1
narrative was byte-identical, and this round changed it deliberately, with the diff
and the reasoning shown above.

---

## Finding 3 — generated mapping is now unmistakably the authority

### New file order

```
1    # Football Market Mapping           (intro, facts corrected)
21   <!-- GENERATED FROM bookmaker_markets.json -->    <- table now FIRST
30   ## Registry table (generated)       85 mapped rows + excluded table
148  <!-- END GENERATED FROM bookmaker_markets.json -->
152  ## Per-book field notes (hand-written)
164  ## Live (In-Play) Feeds       (Mapped markets column dropped)
184  ## WWIN
200  ## Premier Kladionica
230  ## MDShop
243  ## Admiralbet
254  ## MBet
277  ## SportPlus
300  ## Mozzartbet
312  ## EVLBet
324  ## Betole
```

An explicit authority paragraph sits immediately before the marker: *"The table
below is the authority on which source ID maps to which market … Where the
hand-written field notes at the bottom of this file disagree with it, it wins: fix
the registry and regenerate rather than editing either."*

### Sections removed — nine hand-maintained ID→market tables

| Section | Table removed | Fate of its cells |
| --- | --- | --- |
| Live (In-Play) Feeds | "Mapped markets" **column** only (endpoint + notes columns kept as a 2-column table) | 11 of 30 tokens in the generated table; 19 are endpoints/flags/feed vocabulary, kept as prose |
| WWIN | `Source offer / Mapping / Decision` | 10 in generated; 12 kept as prose (`idBt` field, `t` label vocabulary, `total` comma decimal) |
| Premier Kladionica | same | 1 in generated; 22 kept as prose (PrSync section indices, `dogTipK` layout, `setTip`/`setTipVar`/`setTipTip`, `grupaTipID=2`, Bosnian names) |
| **Supported Internal Markets** | `Internal type / Required outcomes / Meaning` — whole section | 14 in generated; the 6 internal enum values were **restored into the generated Market column** (below) |
| MDShop | same | 12 in generated; 8 kept as prose (`betTypeId`, `sbv`, unsupported 4.5/5.5/6.5) |
| Admiralbet | same | 13 in generated; 6 kept as prose (`sBV` casing, the 1639 post-mortem) |
| MBet | same | 6 in generated; 12 kept as prose (`o<sport>:<market>:<outcome>`, `ofb:tg:2+`…`4+` with `0-1`…`0-3`, live `lfb:tg:over\|1.5`) |
| SportPlus | same | 1 in generated; 20 kept as prose (`NOGOMET`, `RASPON GOLOVA`, the `id` field and its ids, `308`-`311`, `1285`, `178`, `5`) |
| Mozzartbet | same | 0 in generated; 17 kept as prose (`ki`/`ds`/`ug`/`tgg` **paired with their numeric ids**, `gg3+`, `kmb`/141, `dalje`/`prolaz`/`kvalifikacije`) |
| EVLBet | same | 1 in generated; 7 kept as prose (`SportIds=388`, `BetTypeKey=12005`/`GameId=1`, `Ishod meca`, `HasSbv`/`Sbv`) |
| Betole | `Pick codes / …` | 0 in generated; 8 kept as prose (`KI_1`/`KI_X`/`KI_2`, `esMatches[].odds`, `/restapi/offer/ba/sport/S/desk`, `10`-`18`/`284`-`286`/`295`-`296`, `IDE DALJE` = 335/336, `ttg_lang`) |

### Proof that no registry-derived content was lost

I extracted every backticked token from each *old* section, subtracted what the new
generated block documents, and for each remainder decomposed the `field=value` /
`a-b` / `name ...` composite into the facts it actually asserts, then checked every
part is present somewhere in the new file.

Final result: **29 composite tokens, all explained** — e.g. `idBt=95` is present as
the field name `idBt` in prose plus `95` in the generated table; `308-311` as
`308`/`311`; `10-18` as `10`/`18`; `TOČAN ...` as `TOČAN …` (Unicode ellipsis).
One token, `lfb:tg:over\|X.5`, needed a manual check because the old file had it
backslash-escaped inside a markdown table; the new MBet section states
`lfb:tg:over|1.5` / `lfb:tg:over|2.5` and notes the `|` is literal.
**Zero registry-derived facts lost without a generated replacement.**

The audit did find one real regression, which I fixed: the retired *Supported
Internal Markets* table was the only place documenting the raw `MarketType` enum
values. The generated **Market** column now carries both forms — for example
`Over/Under 2.5 (` + `` `over_under_2_5` `` + `)` — so an operator reads the label
and a developer can grep the code key.
`test_generated_market_names_are_human_readable_and_carry_the_enum_key` asserts
both, and that the set of enum keys equals the registry-backed set exactly.

### Two stale hand-written claims corrected (the code disagreed with the doc)

- **SportPlus `id=4` (`PRVO POLUVRIJEME`) and `id=25` (`AZIJSKI HENDIKEP`)** were
  listed as "Excluded". `tests/test_market_mapping.py:126-127` says the opposite:
  *"4 (PRVO POLUVRIJEME) and 25 (AZIJSKI HENDIKEP) are now supported experimental
  markets"*. Now stated as supported-experimental.
- **Betole pick codes `4`/`5`/`6`** were listed as "Excluded" but
  `tests/test_market_mapping.py:260-261` says *"First-half 1X2 (codes 4/5/6) is a
  supported experimental market"*. Now stated as supported-experimental.

### New invariants so this cannot regress

- **21 narrative anchors** (`NARRATIVE_ANCHORS`) must survive outside the markers:
  `getwebevents?isLive=true`, `events_cached?live=true`, `betting/matches`,
  `15 minutes`, `sport-livecontent`, the `PrSync` endpoint, `execRes, tipIgre, sport`,
  `grupaTipID=2`, `o-da`, `o<sport>:<market>:<outcome>`, `ofb:fts`,
  `sportName=NOGOMET`, `RASPON GOLOVA`, `betting: false`, `gg3+`, `SportIds=388`,
  `Ishod meca`, `esMatches[].odds`, `/restapi/offer/ba/sport/S/desk`, `KI_1`, and
  `real Admiralbet 1X2 offer` (the `136` post-mortem). Each is knowledge no
  generated table can reproduce, so deleting one is a real deletion.
- **8 retired table headers** (`| Source offer |`, `| Source key |`,
  `| Source market |`, `| Source game |`, `| Pick codes |`, `| Internal type |`,
  `| Bookmaker | Live feed | Mapped markets |`, and the PK variant) must **not**
  reappear outside the markers, so a second hand-maintained source of truth cannot
  creep back in beside the generated one.
- `test_generated_table_is_the_authority_and_comes_first` asserts `BEGIN_MARKER`
  precedes `## Per-book field notes`, that the markers are correctly ordered, and
  that the word "authority" appears in the text before the table.
- `test_splice_preserves_narrative_around_the_markers` no longer accepts a merely
  non-empty preamble (the preamble is now 20 lines). It requires non-empty
  narrative **outside the markers on both sides**, which is where the notes live.

All four doc mutations were run and each is caught: delete the Admiralbet
post-mortem → anchor test fails; re-add a `| Source offer |` table → retired-header
test fails; move the generated block below the notes → authority-ordering test
fails; revert the intro to "seven" → bookmaker-count test fails.

---

## Minor — done

`test_mapped_and_excluded_ids_are_disjoint` asserts that no registered source ID
also matches its book's `_excluded` patterns, using the production matcher
`MarketRegistry.is_excluded` (so glob patterns like `*DALJE*` are honoured) across
all 85 declarations. It also asserts the `_excluded` block still exists.
Mutation-verified: adding `136` to `mdshop` prematch 1X2 while it remains excluded
fails the test.

The `_excluded` prose in the generated block was softened from *"recognised by the
parsers and rejected on purpose … so they never reach the arbitrage engine"* to:

> Listing an ID here suppresses the unmapped-market health diagnostic for it, so an
> operator does not chase a market the project intends to ignore. **It is a
> declaration of intent, not a rejection mechanism:** a parser still has to decline
> the offer on its own, and no ID may appear both here and in the table above.

The second minor (loader-resolved labels blessing a wrong-but-non-empty label set)
was **deferred** as instructed.

---

## Commands and output

### `python scripts/generate_market_mapping_doc.py --check`

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/generate_market_mapping_doc.py --check ; echo "exit=$?"
MARKET_MAPPING.md is in sync with config/bookmaker_markets.json
exit=0
```

### Task module — 141 passed

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 141 items

tests\test_registry_parser_consistency.py .............................. [ 21%]
........................................................................ [ 72%]
.......................................                                  [100%]

============================= 141 passed in 1.16s =============================
```

### FULL SUITE — 359 passed, 0 failed

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
359 passed, 3 warnings in 5.45s
```

**Explicit passed-test count: 359 passed, 0 failed, 0 errors, 0 skipped**
(218 pre-existing + 141 in the task module). The 3 warnings are the pre-existing
FastAPI `on_event` deprecations from `server/app.py:35`.

### `ruff check .`

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check . ; echo "exit=$?"
All checks passed!
exit=0
```

Two ruff errors appeared during the round and were fixed: `UP037` (a quoted
`MarketSpec | None` annotation in `common.py`) and `F401` (`record_unmapped` left
unused in `parse_nsoft_bets` after delegation).

### `mypy .`

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" . ; echo "exit=$?"
Success: no issues found in 50 source files
exit=0
```

One transient `invalid syntax` report during the round was a stale `.mypy_cache`
after multi-line lambdas were replaced with nested defs; cleared the cache and it
is clean.

### Diff and commit

```
$ git diff --stat ee15a36
 MARKET_MAPPING.md                         | 542 +++++++++++++++---------------
 scrapers/betole.py                        |  26 +-
 scrapers/common.py                        |  38 ++-
 scrapers/evlbet.py                        |  43 ++-
 scrapers/wwin.py                          |  26 +-
 scripts/generate_market_mapping_doc.py    |  18 +-
 tests/test_registry_parser_consistency.py | 376 ++++++++++++++++++++-
 7 files changed, 750 insertions(+), 319 deletions(-)

$ git rev-parse HEAD
6398eedd4dc1b54c57c9d292edce5e6d7d6b3c3c
$ git status --short
(clean)
```

---

## Concerns

1. **Four scraper files are touched** (`common.py`, `betole.py`, `evlbet.py`,
   `wwin.py`) purely to lift four nested closures to module scope. Behaviour is
   unchanged (the 239-test suite passed unchanged immediately after, before any new
   test existed) and each original call site now delegates, so there is one
   implementation. But it is production-code churn in a docs task, and later tasks
   that edit those parsers will see a larger diff than they expect. This was the
   price of the finding's "the parser's `_registered_spec`-equivalent lookup" being
   importable at all; the alternative was a payload-driven test per book needing
   hardcoded per-book feed shapes, which would have been far more fragile.

2. **The parser test cannot catch a wrong ID, by construction.** Registry and
   parser share one source of truth, so they are wrong *together*. Demonstrated:
   `135` → `999` leaves all 85 reachability cases green. The doc-consistency tests
   catch it; only real captured payloads (Task 11) can catch a *systematically*
   wrong-but-consistent ID.

3. **`_excluded` has gaps that the audit made visible.** `ofb:ht` (MBet first-half)
   and `ofb:hc` (MBet handicap) are described as excluded in the narrative but are
   **not** in the registry's `_excluded` block, so they still raise an
   unmapped-market diagnostic. Same for Betole's combination codes (`10`-`18`,
   `284`-`286`, `295`-`296`), which appear in neither the registry nor `_excluded`.
   Not fixed — that is Task 4's file. All three are now called out in the doc prose
   so the knowledge is not lost.

4. **`betole` registry rows are supersets of what the parser reads** (see Finding 1).
   Benign — the unreachable IDs resolve to the right spec and are disjoint from
   `_excluded` — but the generated table overstates Betole's coverage. Documented in
   the Betole section; deliberately not encoded as expected behaviour, because that
   would freeze a bug.

5. **`PLAN.md:87` now points at a stale line range** — it cites
   `MARKET_MAPPING.md:168-178` for the EVLBet audit; that section is now at
   `:312-323`. I did not edit `PLAN.md` (not in scope; it belongs to the parent
   session), so this needs a one-token fix by whoever owns it. The other
   cross-references (`README.md:87`, `ScraperLogic.md:10`, `PLAN.md:145`) are
   file- or section-level and remain correct.

6. **The generated table is now first and is wide** (8 columns, 85 rows), so the file
   is 336 lines and someone opening it for "how does Mozzartbet parse totals?" now
   scrolls past the whole table. That is the deliberate trade for authority-first
   ordering, and the per-book notes are one heading away, but it is a real change in
   reading experience.

7. **Narrative anchors are a maintenance cost.** 21 phrases must stay in the doc, and
   a legitimate rewrite (say, a renamed `PrSync` endpoint) now fails a test. That is
   the intended friction — a rewrite has to update the list deliberately — but it is
   friction.

8. **The deferred minor stands**: loader-resolved labels would bless a
   wrong-but-non-empty label set. Out of scope per the findings.

---

# FIX ROUND 2 (of 5)

**Commit:** `9567cfe73bd139809688d03d6ed33303b0309ccf` (`9567cfe`), one commit on
top of `6398eed`.
**Working tree after commit:** clean.
**Result:** 292 passed / 0 failed / 0 errors / 0 skipped; ruff clean; mypy clean.

**Addressed and kept from round 1:** the corrected introductory facts (nine
bookmakers; nine `MarketType` values with the accurate six/three split) and
`test_mapped_and_excluded_ids_are_disjoint`. Item 1 stays accepted at the resolver
level; the extraction it enabled is kept, now private.

**The headline of this round: I wrote a confident false statement, and I found two
more of the same kind while verifying it. All three are corrected below.**

---

## 1. The false MBet claim — corrected

### What I got wrong

Round 1 wrote, in the MBet field notes:

> Note that `_excluded` currently lists `ofb:sh` but not `ofb:ht` or `ofb:hc`
> (handicap), so those two still raise an unmapped-market diagnostic when they
> appear.

**That is false.** I inferred it from the registry file's shape — those prefixes
are absent from `_excluded` — and did not check the parser. The parser
contradicts it:

- `scrapers/mbet.py:107` — the allowed-prefix set is
  `{"fs", "dc", "gg", "tg", "ht", "hc"}`, so `ht` and `hc` are explicitly
  dispatched, not reported.
- `scrapers/mbet.py:147-155` — `o{s}:ht:1|X|2` becomes `first_half_1x2`.
- `scrapers/mbet.py:157-190` — `o{s}:hc:H1|<line>` / `H2|<line>` becomes
  `asian_handicap`, favourite on the lower odds, all lines preserved.
- `tests/test_new_markets.py:183-197` (`test_mbet_parses_fh_and_ah`) asserts both.

So I documented a defect that does not exist, and in a document whose stated
purpose is accuracy.

### What the MBet section says now

> Six prefixes are dispatched: `fs`, `dc`, `gg`, `tg`, `ht` and `hc`. The last two
> are **not** full-time result markets, and they are not ignored either — they are
> experimental markets parsed directly, outside the registry:
>
> - `ofb:ht` with sides `1`/`X`/`2` becomes `first_half_1x2`.
> - `ofb:hc` is a two-way handicap keyed `H1|<line>` / `H2|<line>` and becomes
>   `asian_handicap`; the favourite is the side with the lower odds, and all
>   handicap lines are preserved rather than overwritten.
>
> Two other prefixes look like the result market and are genuinely not mapped:
> `ofb:fts` is first team to score (its labels can be `1`/`X`/`2`), and `ofb:fi` is
> a baseball first-inning market that the football feed still carries. `ofb:sh` is
> the second-half result. All three are in the registry's `_excluded` block, so
> their unmapped-market diagnostic is suppressed on purpose.

I checked the last sentence too: `ofb:fts`, `ofb:fi` and `ofb:sh` **are** in
`config/bookmaker_markets.json`'s `_excluded.mbet`, and `record_unmapped` returns
early for excluded values, so they genuinely do not raise a diagnostic.

### Two more errors found while verifying the first

I re-read the parser and its tests for every prose claim I added in round 1, not
just the one flagged. Two more of mine were wrong:

| Claim in round 1 | Reality | Now says |
| --- | --- | --- |
| "In live **the same shape** is used with the `lfb:` prefix" | Prematch is `o<sport>:<market>:<outcome>`; live is `lfb:<market>:<outcome>` — no `o`, no sport segment (`mbet.py:288-296`) | "Live drops the `o` prefix and the sport segment: the keys are `lfb:ft:1`, `lfb:dc:1X`, `lfb:bttsny:Yes`…" |
| The threshold "arrives in a `total` spec field as a comma decimal" | It arrives in the bet's **`spec`** field, whose content is `total=1,5` (`wwin.py:173`) | "arrives in the bet's `spec` field as `total=1,5` / `total=2,5` / `total=3,5`" |

(`lfb:tg:over|1.5` itself I had got right — confirmed by
`tests/test_live_mode.py:87-89`.)

### The claims I checked and found accurate

Stating these so the record shows the check was broad, not reactive:

* WWIN: "1X2 accepted only with all three `1`/`X`/`2`; double chance needs at least
  two valid legs" — both branches gate on `spec.min_legs` (`wwin.py:122-136`,
  registry `min_legs` 3 and 2). ✓
* Mozzartbet: `id 1/ki`, `2/ds`, `3/ug`, `130/tgg` — the dispatch is
  `gid == 1 or gshort == "ki"` etc. (`mozzartbet.py:220-250`). ✓ Live totals
  aliases `2+/0-1`, `3+/0-2`, `4+/0-3` — `mozzartbet.py:270-277`. ✓
  `dalje`/`prolaz`/`kvalifikacije` exclusion — `mozzartbet.py:47`. ✓
* Betole `4`/`5`/`6` as supported experimental first-half — `betole.py:111`, with
  the comment "Experimental market". ✓
* SportPlus `id=4` → `FIRST_HALF_1X2`, `id=25` → `ASIAN_HANDICAP` —
  `sportplus.py:460,478`. ✓
* Premier Kladionica `da`/`ne`, `o-da`, `m`/`v` — `premier_kladionica.py:25,344,376`. ✓
* SportPlus `betting: false` skipped, `ML/` prefix stripping —
  `sportplus.py:154,164`. ✓
* MBet prematch totals read only `2+/0-1`, `3+/0-2`, `4+/0-3` —
  `mbet.py:216-220`. ✓

The process failure was mine: I wrote prose about parser behaviour from the shape
of a config file, and the config file was the wrong source. From this round on the
rule I applied was *read the parser and its tests before writing a behavioural
claim, and cite the line in the report*.

---

## 2. Betole — the generated table no longer overstates itself

`config/bookmaker_markets.json:136-141` declares more Betole IDs per row than
`scrapers/betole.py:107-115` reads; the unknown-code loop at `:131-137` reports
them. Round 1 handled this with a caveat placed *after* a table the document called
authoritative, which is what the finding objects to.

I did **not** edit the registry: it is Task 4's file, later tasks may depend on it,
and the instruction for this round was to reduce scope. So the fix is that the
generated block now qualifies its own authority, inside the markers, immediately
above the table it applies to (`scripts/generate_market_mapping_doc.py`):

> Scope: these are the IDs the **registry declares**. It is the authority on the
> declared mapping, not on parser dispatch — a book's parser may read a subset of
> the IDs listed for it, because some parsers dispatch on a hardcoded pick table
> rather than iterating the registry. Where a row lists more IDs than the book
> actually consumes, the per-book field notes at the bottom of this file say so.

That makes the claim true as written: the table *is* authoritative about the
registry, and it no longer claims to enumerate what each parser consumes. The
concrete case stays in the Betole field notes, which still name it and still say
the row is "the union of everything Betole might emit rather than a description of
what it currently parses".

`test_generated_table_states_the_scope_of_its_authority` asserts the statement is
present **inside the block** (searching within the marker-bounded `block` makes
that structural, not textual) and that the field notes still name betole and call
it a superset — so neither half can be deleted alone.

**This does not resolve the underlying registry inaccuracy.** Betole's rows are
still broader than the parser. The registry is the right place to fix that and
belongs to Task 4; I have flagged it rather than silently editing it.

---

## 3. WWIN audit semantics restored

Round 1 deleted the old `MARKET_MAPPING.md:41` row and left only the IDs. The
deleted part was the *reason* each ID is excluded, which a generated table cannot
hold — the table records that `443` is excluded, not that `443` is Asian totals
including quarter lines. Restored in the WWIN field notes as prose:

* `idBt=7` — draw no bet.
* `idBt=10` — three-way handicap.
* `idBt=4` — half-time / full-time.
* `idBt=476` — "Prolaz", the advance market.
* `idBt=443` — Asian totals, including quarter lines such as `2.25` and `2.75`
  that have no representation in the supported Over/Under set.
* `idBt=51` — correct score.

with the framing: *"the table records **that** they are excluded, not **what they
are**"*.

**One correction found while restoring it.** The old row also listed `idBt=2`
(first-half 1X2) as excluded. That is stale, in the same class as SportPlus 4/25
and Betole 4/5/6: `scrapers/wwin.py:163-172` reads `idBt=2` in prematch and emits
`first_half_1x2`, with the comment *"experimental market retained outside the core
registry"*. It is not in `_excluded.wwin` either. The section now says so, and
cross-references the identical MBet treatment.

So round 1's stale-claim sweep, while it corrected three entries, missed this one
because it sat inside a table I removed wholesale rather than one I edited.

---

## 4. Scope reduction

### 4a. The four resolvers are private

| Before (public) | After (private test seam) |
| --- | --- |
| `scrapers.common.nsoft_registered_spec` | `scrapers.common._nsoft_registered_spec` |
| `scrapers.betole.betole_registered_spec` | `scrapers.betole._betole_registered_spec` |
| `scrapers.evlbet.evlbet_registered_spec` | `scrapers.evlbet._evlbet_registered_spec` |
| `scrapers.evlbet.DEFAULT_BASIC_OFFER_ID` | `scrapers.evlbet._DEFAULT_BASIC_OFFER_ID` |
| `scrapers.wwin.wwin_registered_spec` | `scrapers.wwin._wwin_registered_spec` |

The four `mbet` / `mozzartbet` / `premier_kladionica` / `sportplus`
`_registered_spec` helpers were already private and are unchanged. Verified with
`hasattr` across all ten scraper modules: **no leaked public names**. The extraction
is kept — each call site delegates to the module-level function, so there is still
exactly one implementation, and the other 218 tests pass unchanged.

### 4b. The test file is split

| File | Concern | Tests | Imports a scraper? |
| --- | --- | --- | --- |
| `tests/test_registry_parser_consistency.py` | generator mechanics, generated-table content, narrative preservation, intro claims, registry disjointness | 55 | **no** |
| `tests/test_market_registry_wiring.py` | registry ↔ parser wiring (new file) | 19 | yes |

The doc file no longer imports a scraper module at all; it reads the registry JSON
and the Markdown. Its module docstring now says what it covers and points at the
wiring file, instead of the stale "no orphan IDs, no undocumented parser IDs".

### 4c. The 85-case loop is gone, replaced by 8 dispatch cases

The round-1 test called the extracted resolver **directly**, so it never touched the
hardcoded dispatch/pick tables. Proof it could not have caught a dispatch bug:

```
$ git show 6398eed:tests/test_registry_parser_consistency.py \
    | grep -E "_build_markets_from_bets|_parse_betole_markets|parse_nsoft_bets|_parse_markets|_parse_event|_resolve_mbet_market"
  NONE - it only imported the four resolvers
```

The replacement feeds a **synthetic payload into each book's real parse entry
point** — `parse_nsoft_bets`, `_parse_bets`, `_resolve_mbet_market`,
`SportPlusScraper._parse_markets`, `_parse_markets`, `_parse_betole_markets`,
`EvlbetScraper._parse_event`, `_build_markets_from_bets` — and asserts a
`MATCH_RESULT` market comes out whose label set equals what the registry declares
for the ID that went in.

Crucially the source ID in each case is **the code that book's own dispatch table
uses**, not the registry's, so the test cannot become a tautology over the
registry. Each case carries a comment saying where that code comes from, e.g.
`# wwin.py:122 dispatches on bet_id == 95`, `# betole.py:107 dispatches MATCH_RESULT
on pick codes 1/2/3 (not 135)`.

Also added: a **negative control** (an unregistered NSoft `betTypeId` must produce
no match-result market) so the positive cases cannot be vacuous, and a **static
routing check** for all nine books that the registry-owning module imports
`engine.market_registry`, actually queries it, and does not instantiate its own
`MarketRegistry` (which would drift from the singleton the docs describe).

`premier_kladionica` is deliberately covered only by that static check: its
dispatch sits inside a positional `PrSync` response builder, and fabricating a
multi-section payload would have been a contrived fixture. The gap is named in the
module docstring and enforced by
`test_every_enabled_bookmaker_has_a_parser_module_and_a_documented_gap`, which
fails for any book with neither a dispatch case nor a documented gap.

### 4d. The new wiring tests actually bite

| Mutation | Result |
| --- | --- |
| Break WWIN dispatch: `bet_id == 95` → `9999` | **FAILS** `test_registered_id_is_dispatched_by_its_books_parser[wwin]` |
| Break Betole pick table: `1/2/3` → `4/5/6` | **FAILS** `..._dispatched_by_its_books_parser[betole]` |
| Give SportPlus a private `MarketRegistry()` | **FAILS** both `[sportplus]` cases |
| Change a registry label (`1/X/2` → `H/D/A` for mbet) | **FAILS** `..._dispatched_by_its_books_parser[mbet]` |

The first two are exactly the class of bug the 85-case loop could not see: the
loop called the resolver, so breaking the dispatch that *calls* the resolver was
invisible to it.

### 4e. Net effect

Full suite: **359 → 292 tests**. Round 1 added 120 tests; round 2 removes 67 of
them and adds 19, of which only 10 are net-new behaviour. The production diff in
this round is 20 lines across four files, all of it renames.

---

## Commands and output

### `python scripts/generate_market_mapping_doc.py --check`

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/generate_market_mapping_doc.py --check ; echo "exit=$?"
MARKET_MAPPING.md is in sync with config/bookmaker_markets.json
exit=0
```

### Doc / generator / narrative tests — 55 passed

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 55 items

tests\test_registry_parser_consistency.py .............................. [ 54%]
.........................                                                [100%]

============================= 55 passed in 0.71s =============================
```

### Parser wiring tests — 19 passed

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry_wiring.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 19 items

tests\test_market_registry_wiring.py ...................                 [100%]

============================= 19 passed in 0.61s =============================
```

### FULL SUITE — 292 passed, 0 failed

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
292 passed, 3 warnings in 5.18s
```

**Explicit passed-test count: 292 passed, 0 failed, 0 errors, 0 skipped**
(218 pre-existing + 55 doc/generator + 19 parser wiring). The 3 warnings are the
pre-existing FastAPI `on_event` deprecations from `server/app.py:35`.

### `ruff check .`

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check . ; echo "exit=$?"
All checks passed!
exit=0
```

### `mypy .`

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" . ; echo "exit=$?"
Success: no issues found in 51 source files
exit=0
```

### Diff and commit

```
$ git diff --stat 6398eed HEAD
 MARKET_MAPPING.md                         |  73 +++++---
 scrapers/betole.py                        |   4 +-
 scrapers/common.py                        |   4 +-
 scrapers/evlbet.py                        |   8 +-
 scrapers/wwin.py                          |   4 +-
 scripts/generate_market_mapping_doc.py    |   7 +
 tests/test_market_registry_wiring.py      | 280 ++++++++++++++++++++++++++++++
 tests/test_registry_parser_consistency.py | 251 +++++++-------------------
 8 files changed, 410 insertions(+), 221 deletions(-)

$ git rev-parse HEAD
9567cfe73bd139809688d03d6ed33303b0309ccf
$ git status --short
(clean)
```

---

## Concerns

1. **Betole's registry rows are still broader than its parser.** I narrowed the
   *claim* the document makes about them, not the registry itself. The accurate fix
   is to trim `config/bookmaker_markets.json:136-141` to the pick codes
   `scrapers/betole.py:107-115` actually reads, or to add a registry-level
   distinction between "declared" and "dispatched". That is Task 4's file and I did
   not touch it. Until then the table is honest-but-wider-than-reality for betole,
   and the caveat is in two places (generated scope paragraph and the Betole notes).

2. **Four production files are still touched**, though the footprint is now 20 lines
   of renames. The extraction itself is the reviewer's accepted trade-off and is
   covered by the unchanged suite, but `scrapers/*.py` shows up in a documentation
   task's diff and later tasks will see it.

3. **`premier_kladionica` has no payload-driven coverage.** It is guarded by a
   source-level routing check only. If its dispatch ever stops consulting the
   registry — say it starts hardcoding IDs — the static check will not catch it,
   because it only asserts the module imports and queries the registry somewhere.
   A fabricated PrSync payload would close this, and I judged that worse than a
   named gap; the gap is enforced by name in
   `test_every_enabled_bookmaker_has_a_parser_module_and_a_documented_gap` so it
   cannot be forgotten silently.

4. **The static routing check is a source-text assertion**, not a behavioural one.
   It uses `inspect.getsource` plus regex, so it is sensitive to refactors (renaming
   `lookup_type`, moving the import) and insensitive to logic errors. It is
   labelled as static in both the docstring and the test name.

5. **`MARKET_MAPPING.md` is now 374 lines with the table first.** The three
   corrections made it longer, not shorter, and a reader looking for one book's
   notes still scrolls past 130 rows of table. Authority-first ordering was the
   reviewed decision, so this is a restatement rather than a new objection.

6. **`PLAN.md:87` still points at a stale line range** (cites
   `MARKET_MAPPING.md:168-178` for the EVLBet audit; EVLBet is now at `:343-354`).
   Carried over from round 1; `PLAN.md` belongs to the parent session.

7. **I have not re-audited the whole document for prose-vs-code drift**, only the
   claims *I* wrote in round 1 plus the restored WWIN list. Pre-existing prose that
   I inherited (Premier Kladionica's `grupaTipID=2` tip group, the `ttg_lang`
   endpoint, the MBet `/markets?extended=true` metadata check) has no
   machine-checkable backing in the code, because those describe feed payloads
   rather than code paths. It came from the original hand-written audit, which is
   the best available source, but I cannot verify it from the repository and I am
   not asserting that I did.
