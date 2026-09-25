# Task 2 Report — CertaintyGate

**Status:** DONE_WITH_CONCERNS  
**Commit:** `51060ea6fddd4c2ddbbcb768d4cd254846ed8c97`  
**Branch:** `master` (worked in place; no worktree and no new branch)  
**Date:** 2026-09-25

## What changed

### `config/settings.py`

Added the verified-pair kickoff window without changing the existing general matching window:

```python
KICKOFF_WINDOW_MINUTES = 120
VERIFIED_KICKOFF_WINDOW_MINUTES = 15
```

### `engine/certainty.py`

Created the deterministic proof layer with the requested public interface:

- `GateResult` dataclass with `status`, `reasons`, `evidence`, and `is_swapped`.
- `CertaintyGate` with normalization, league/equivalence checking, timezone-safe kickoff delta calculation, complete home/away team orientation checks, category checks, link checks, evidence generation, and pair/group evaluation.
- `HARD_REJECT_REASONS` contains the specified hard rejection reasons.
- The default window is wired to `VERIFIED_KICKOFF_WINDOW_MINUTES` (15).
- No AI path or AI approval behavior was added.

The requested swap ambiguity was handled by evaluating complete direct and swapped orientations. An allowlisted fuzzy hit is accepted only when both team pairs line up in the same orientation; a single cross-side hit cannot set `is_swapped=True`.

### `tests/test_certainty.py`

Added 18 deterministic tests covering:

- all-gate verified success and evidence;
- aware/naive UTC-equivalent kickoffs;
- missing and over-window kickoffs, including the inclusive 15-minute boundary;
- league, category, team, and link failures;
- league equivalences;
- allowlisted versus unlisted fuzzy aliases;
- complete alias swaps and the wrong-side fuzzy regression;
- consistent swap flags when another gate fails;
- group evaluation;
- the 15-minute default and the preserved 120-minute setting through the implementation.

## TDD trace

### RED: required failing test

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v
```

Output before creating `engine/certainty.py`:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 0 items / 1 error

=================================== ERRORS ====================================
__________________ ERROR collecting tests/test_certainty.py ___________________
ImportError while importing test module 'C:\Users\harun\OneDrive\Documenti\surebetmuse12\tests\test_certainty.py'.
Hint: make sure your test modules/packages have valid Python packages installed?
Traceback:
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_certainty.py:5: in <module>
    from engine.certainty import CertaintyGate
E   ModuleNotFoundError: No module named 'engine.certainty'
=========================== short test summary info ===========================
ERROR tests/test_certainty.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.92s ===============================
```

Exit code: 2. This was the expected red failure: the requested production module did not yet exist.

### Intermediate red/green corrections

The first implementation run exposed three inconsistencies in the brief's literal test block: the timezone fixture represented a real two-hour delta, the no-link fixture expected `link_unverified` while the specified `_link_evidence` logic classifies no ID/URL as `no_event_link`, and the reviewed `lech p|lech poznan` abbreviation scores 80 with `token_set_ratio` in the installed RapidFuzz version. The tests were corrected to test their stated behavior, and allowlisted abbreviations use the maximum of token-set and partial ratios while still requiring an allowlist entry and a score of at least 90.

A subsequent regression test intentionally failed when an exact swapped pair was incorrectly marked as allowlist evidence because the allowlist happened to match the unselected orientation. The implementation was then refactored to track the selected orientation, and the test passed.

### GREEN: focused suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 18 items

tests\test_certainty.py ..................                               [100%]

============================= 18 passed in 1.02s =============================
```

## Final verification

### Full test suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output:

```text
........................................................................ [ 55%]
.........................................................                [100%]
```

Exit code: 0. The project has 129 collected tests after adding this task's 18 tests (the repository's `pyproject.toml` already supplies `-q`, so the requested second `-q` suppresses the summary line).

### Ruff

The bare `ruff`/`mypy` names are not on this shell's PATH. The venv executables were used:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output:

```text
All checks passed!
```

Exit code: 0.

### Mypy

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output:

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 40 source files
```

Exit code: 0. The notes are pre-existing untyped-function notes; there are no type errors.

## Deviations from the brief

1. **Default value source:** the implementation uses `VERIFIED_KICKOFF_WINDOW_MINUTES` as the default rather than a second literal `15`, matching the explicit interface line and the new setting.
2. **Swap resolution:** the complete-orientation algorithm and selected-orientation evidence tracking implement the caller's explicit ambiguity correction. This is intentionally stricter than the brief's single-pair loop.
3. **Fuzzy alias metric:** the supplied `lech p|lech poznan` case has a token-set score of 80, so the allowlisted path accepts a reviewed abbreviation when `max(token_set_ratio, partial_ratio) >= 90`. Unallowlisted fuzzy matches remain rejected.
4. **Test fixture corrections:** the timezone fixture now represents the same instant in `+02:00`; the link-unverified fixture includes a URL/event-link presence, with a separate no-event-link test. These resolve contradictions in the brief while preserving both specified reason strings.
5. **Additional regression coverage:** extra tests cover the resolved swap ambiguity, boundary behavior, missing links, and the hard-gate restriction on alias acceptance. The unused `asyncio` import from the sample test was omitted.
6. **Small robustness/evidence improvements:** an empty group returns a deterministic `team_unresolved` result instead of indexing an empty list, and an exact swap remains `source="rule"` even if an allowlist happens to contain a potentially matching unselected pair.

## Concerns

- The brief's literal timezone, link, and alias test examples are internally inconsistent with its stated implementation/values; the resolutions above are intentional and covered by tests.
- `orientation_unresolved` is retained in the specified `HARD_REJECT_REASONS` set, but the requested `_teams_ok` contract's incomplete-team path returns `team_unresolved` as shown in the brief. If later tasks need to distinguish an orientation-only ambiguity from an unresolved team, that will require an explicit reason-mapping decision.
- The report directory is ignored by Git, so this report is present on disk but not included in the three-file implementation commit.

## Fix round 1 — review findings

**Fix-round commit:** `a45246913035c5dfead26e477d075d1f2f07ee5e`  
**Covering test file:** `tests/test_certainty.py`  
**Production file:** `engine/certainty.py`

### Critical #1 decision

I chose the suggested option (b): `CertaintyGate` now uses the original raw team names for the identity/allowlist decision, while retaining normalized values for canonical comparisons and the league/category gates. The shared `TeamNormalizer` was not modified.

The gate compares a lossless raw key (case-folding, whitespace collapse, and trailing-dot cleanup) before consulting the normalizer's canonical fields. If the raw forms differ, a canonical collision is not enough: the pair must match an explicit allowlist entry and pass the existing fuzzy threshold. This blocks the existing normalizer fuzzy fallback from silently promoting an unapproved name, while preserving reviewed aliases such as the existing `lech p|lech poznan` case.

The new regression test uses `Sarajevo` versus the normalizer-fuzzy `Sarjevo`: without an allowlist it is `suggested` with `team_unresolved`; with `sarjevo|sarajevo` it is `verified` with allowlist evidence.

### Other fixes

- `evaluate()` now checks the group's canonical home/away fields, canonical kickoff, and league independently of the pair status. A group-league contradiction is appended even when the pair also has a soft link failure; final status is recomputed from the accumulated reasons.
- The timezone regression now passes a genuinely aware datetime to one `Match` and a naive UTC datetime to the other in both argument orders.
- Status/reason tests now pin exact values for league mismatch, category mismatch, kickoff missing/delta, link unverified, and team unresolved. A vocabulary test reaches all seven currently reachable reason strings and explicitly excludes `orientation_unresolved`, which remains in `HARD_REJECT_REASONS` but is not emitted, per the controller ruling.

### TDD red run before the fixes

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v
```

Output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 24 items

tests\test_certainty.py .....................FF.                         [100%]

=================================== FAILURES ===================================
________________________ test_evaluate_checks_group_canonical_team_fields _________________________
...
E       AssertionError: assert 'verified' == 'suggested'
...
____________________________ test_evaluate_checks_group_kickoff ____________________________
...
E       AssertionError: assert 'verified' == 'suggested'
...
=========================== short test summary info ===========================
FAILED tests/test_certainty.py::test_evaluate_checks_group_canonical_team_fields
FAILED tests/test_certainty.py::test_evaluate_checks_group_kickoff
========================= 2 failed, 22 passed in 2.96s =========================
```

The earlier red run also failed the raw-normalizer regression with `verified` instead of `suggested`; the two failures shown above are the final pre-fix red run after all review tests were added.

### Focused green run

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 24 items

tests\test_certainty.py ........................                         [100%]

============================= 24 passed in 3.42s =============================
```

### Full suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output:

```text
........................................................................ [ 53%]
...............................................................          [100%]
```

Exit code: 0. The suite now contains 135 tests (129 from the initial task plus 6 review-round tests).

### Ruff

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output:

```text
All checks passed!
```

Exit code: 0.

### Mypy

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output:

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 40 source files
```

Exit code: 0; the notes are pre-existing untyped-function notes.

### Fix-round concerns

No blocking concerns. The normalizer's existing fuzzy behavior is intentionally unchanged, so callers that need fuzzy team matching outside `CertaintyGate` retain their current behavior. The report file remains ignored by Git, while the two implementation/test files are committed in `a45246913035c5dfead26e477d075d1f2f07ee5e`.

## Fix round 2 — scoped re-review

**Fix-round commit:** `660cce50972910deb7afe17c300eae01272bcbf6`  
**Covering test file:** `tests/test_certainty.py`  
**Production file:** `engine/certainty.py`

### Fixes

- Extracted the group-side identity decision onto the same raw/canonical + explicit-allowlist helper used by pair evaluation. Group canonical values equal to the anchor's normalized side retain the anchor's raw name; other group values are treated as raw and must pass the same allowlist rule. `engine/normalizer.py` was not changed.
- Valid allowlisted aliases now pass both `evaluate_pair()` and `evaluate()` against a group.
- Group orientation now uses the canonical group frame as the single `is_swapped` reference frame. When canonical group fields are present, the result replaces the pair-relative flag with the group-relative flag; an unresolved group identity yields a safe false flag. This prevents the matcher from flipping an already-canonical candidate.
- Added regressions for a fuzzy group canonical name, pair/group parity for the Lech alias, and a canonical group whose orientation differs from its first member.

### TDD red run

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v
```

Output before the round-2 implementation:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 27 items

tests\test_certainty.py ...............FF........F.                      [100%]

=================================== FAILURES ===================================
____________________ test_group_canonical_fuzzy_name_requires_allowlist ____________________
...
E       AssertionError: assert 'verified' == 'suggested'
...
_______________ test_allowlisted_alias_passes_pair_and_group_evaluation ________________
...
E       AssertionError: assert 'suggested' == 'verified'
...
________________ test_evaluate_swap_flag_uses_group_canonical_orientation ________________
...
E       AssertionError: assert True is False
...
=========================== short test summary info ===========================
FAILED tests/test_certainty.py::test_group_canonical_fuzzy_name_requires_allowlist
FAILED tests/test_certainty.py::test_allowlisted_alias_passes_pair_and_group_evaluation
FAILED tests/test_certainty.py::test_evaluate_swap_flag_uses_group_canonical_orientation
========================= 3 failed, 24 passed in 2.93s =========================
```

### Focused green run

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_certainty.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 27 items

tests\test_certainty.py ...........................                      [100%]

============================= 27 passed in 9.81s =============================
```

### Full suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output:

```text
........................................................................ [ 52%]
..................................................................       [100%]
```

Exit code: 0. The suite now contains 138 tests.

### Ruff

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output:

```text
All checks passed!
```

Exit code: 0.

### Mypy

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output:

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 40 source files
```

Exit code: 0; the notes are pre-existing untyped-function notes.

### Round-2 concerns

No blocking concerns. `orientation_unresolved` remains in `HARD_REJECT_REASONS` and remains intentionally unreachable, as directed. The report remains ignored by Git; the implementation and tests are committed in `660cce50972910deb7afe17c300eae01272bcbf6`.


