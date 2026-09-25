# Task 1 Report — Extend schemas: statuses, evidence, and link metadata

**Status:** DONE
**Commit:** `1df3b7e778981ed8a401c5f1ba25dc63d48747c7`
**Branch:** `master` (worked in place, no worktree, no new branch)
**Date:** 2026-09-25

---

## What I changed

### 1. `models/schemas.py` (modified)

**Import added** (line 3):
```python
from typing import Literal
```
Placed in the stdlib group after `from enum import Enum`, satisfying ruff's isort rule (`I`).

**`Match` — two new fields**, inserted after `match_code` exactly as the brief specified:
```python
    match_code: str = ""
    event_id: str = ""
    deep_link_verified: bool = False
    category_tags: list[str] = []
```

**Three new top-level symbols**, added above `MatchGroup` as the brief specified:

- `MatchEventStatus = Literal["verified", "suggested", "rejected"]`
- `class MatchEvidence(BaseModel)` with `rule`, `source`, `confidence`, `reason`,
  `league_pair`, `kickoff_delta_minutes`, `allowlist_entries` — verbatim field
  names, types, and defaults from the brief.
- `class CandidateReview(BaseModel)` with `id`, `home_team`, `away_team`, `league`,
  `kickoff`, `bookmakers`, `ai_confidence`, `ai_reason`, `rule_rejections`,
  `status`, `created_at`, `resolved_at`, `resolved_by` — verbatim from the brief.

**`MatchGroup` — two new fields**, appended after `matches`:
```python
    matches: list[Match] = []
    status: MatchEventStatus = "suggested"
    evidence: list[MatchEvidence] = []
```

I added two one-line docstrings (`MatchEvidence`, `CandidateReview`) to match the
existing file convention, where every other `BaseModel` carries a short docstring.
These are the only additions not literally in the brief's code block; they are
comments only and cannot affect behaviour.

### 2. `tests/test_schemas_mapping.py` (created)

The 4 tests copied **verbatim** from the brief, with no edits, no extra tests, no
reordering, and no added assertions.

---

## TDD trace

### Baseline (before any change)

```
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
........................................................................ [ 67%]
...................................                                      [100%]
=== EXIT 0 ===
```
107 tests passing. `ruff check .` → `All checks passed!`.
`mypy .` → `Success: no issues found in 37 source files`.

I captured this baseline first so that "nothing regressed" is provable against a
known-good state rather than assumed.

### Step 2 — failing test

```
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_schemas_mapping.py -v
```

Output:
```
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 0 items / 1 error

=================================== ERRORS ====================================
_______________ ERROR collecting tests/test_schemas_mapping.py ________________
ImportError while importing test module 'C:\Users\harun\OneDrive\Documenti\surebetmuse12\tests\test_schemas_mapping.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level + 1)
tests\test_schemas_mapping.py:4: in <module>
    from models.schemas import CandidateReview, Match, MatchEvidence, MatchGroup
E   ImportError: cannot import name 'CandidateReview' from 'models.schemas' (C:\Users\harun\OneDrive\Documenti\surebetmuse12\models\schemas.py)
=========================== short test summary info ===========================
ERROR tests/test_schemas_mapping.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.63s ===============================
=== EXIT 2 ===
```

It failed for the right reason: the module is missing the new symbols, and the
failure is at import/collection time rather than a false-positive assertion
pass. See "Deviations" below for the one wording difference vs. the brief.

### Step 4 — test passes after implementation

```
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_schemas_mapping.py -v
```

Output:
```
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 4 items

tests\test_schemas_mapping.py ....                                       [100%]

============================== 4 passed in 0.22s ==============================
=== EXIT 0 ===
```

### Full suite + lint + types (final gate)

```
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
........................................................................ [ 64%]
.......................................                                  [100%]
=== EXIT 0 ===
```

```
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m ruff check .
All checks passed!
=== RUFF EXIT 0 ===
```

```
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m mypy .
Success: no issues found in 38 source files
=== MYPY EXIT 0 ===
```

**Test count: 107 baseline → 111 final (+4, exactly the new file).** Zero
pre-existing tests were modified, skipped, or broken. mypy went 37 → 38 source
files because of the new test module.

---

## Global constraints — compliance evidence

- **Every new field on `Match` and `MatchGroup` has a default.**
  `event_id=""`, `deep_link_verified=False`, `status="suggested"`, `evidence=[]`.
  The 107-test suite passing unchanged is the empirical proof that the ~20
  existing `Match`/`MatchGroup` construction sites across tests and scrapers
  still work with no edits.
- **Pydantic v2** — no v1-only constructs used; `Literal`, `X | None`, and
  `list[str]` defaults are all v2-native. mypy clean.
- The new standalone models `MatchEvidence` and `CandidateReview` intentionally
  keep some required fields (`rule`, `source`; `id`, `home_team`, `away_team`,
  `league`, `created_at`) because they are brand-new with zero existing call
  sites and the brief specified them without defaults.

---

## Deviations from the brief

**One, and it is cosmetic — the failure message wording.**

The brief predicted `AttributeError: module 'models.schemas' has no attribute
'MatchEvidence'`. Actual result was `ImportError: cannot import name
'CandidateReview' from 'models.schemas'`. Same root cause, same red test, at the
same moment; only the exception class differs, because the brief's test file uses
`from models.schemas import CandidateReview, ...` — a `from`-import — and Python
raises `ImportError`, not `AttributeError`, for a name missing from a `from`-import
target. The brief's prediction would only be accurate for `import models.schemas`
followed by attribute access. No action needed; I did not change the test to
manufacture the predicted error type.

**Nothing else deviated.** Field names, types, defaults, ordering, placement
(above `MatchGroup`; after `match_code`; after `matches`), the commit message, and
the staged file list are all exactly as the brief specified.

---

## Concerns

Nothing blocking. Two notes for the tasks that follow:

1. **`Literal` is not runtime-validating here in the way a later task may assume.**
   `MatchGroup.status` and `CandidateReview.status` are `Literal`-typed, so
   Pydantic v2 *will* reject an out-of-set value at construction. That is
   intended and is what the brief specified. But it means any code path in Tasks
   2+ that wants to persist a status read back from JSON must be tolerant of a
   value that was never validated on the way in (e.g. hand-edited JSON). Cheap to
   handle with a `model_validator` or a fallback, but worth flagging now rather
   than debugging in Task 5.

2. **`MatchEventStatus` is exported as a type alias, not an `Enum`.** The brief is
   explicit about `Literal`, and it is the right call (it serialises to a plain
   string in JSON with no `.value` unwrapping, which keeps the stored output
   human-readable). But it is a subtle behavioural difference from the
   `MarketType(str, Enum)` pattern used earlier in the same file: a consumer
   writing `MatchEventStatus.VERIFIED` will not work. Later tasks should compare
   against bare strings.

Also worth noting for the plan owner: the brief's "Produces" contract line listed
`CandidateReview.kickoff: datetime | None` and `bookmakers: list[str]` as if they
were required, while the Step 3 code block gives them defaults (`= None`, `= []`).
I followed the Step 3 code block, since it is the explicit implementation and it
is consistent with the "every new field must have a default" global constraint. The
resulting runtime behaviour is a strict superset of the contract line, so nothing
that type-checks against the contract will break.

---

## Commit

```
[master 1df3b7e] feat(mapping): add MatchEventStatus, MatchEvidence, CandidateReview schemas
 2 files changed, 72 insertions(+)
 create mode 100644 tests/test_schemas_mapping.py
```

Full SHA: `1df3b7e778981ed8a401c5f1ba25dc63d48747c7`
Working tree clean after commit.
