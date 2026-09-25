# Task 7 Report — Human review queue API and health diagnostics

**Status:** DONE_WITH_CONCERNS  
**Commit:** `f514da0188fd6f11dd03bb3daca1dbaa80f18b27`  
**Branch:** `master` (worked in place; no worktree or branch created)  
**Date:** 2026-09-25

## What changed

- Added module-level candidate state to `server/api.py`:
  - `pending_candidates: dict[str, CandidateReview]`
  - `candidate_reviews: list[CandidateReview]`
- Added the repository-root allowlist path constant and safe load/save helpers for `config/team_alias_allowlist.json`.
  - The file is loaded as `{"aliases": [...]}`, non-string/malformed entries are ignored defensively, and saved aliases are sorted JSON with Unicode preserved.
  - The matcher loader was read before implementation: `engine/matcher.py` resolves the same `config/team_alias_allowlist.json` and accepts one non-empty `left|right` entry.
- Added `GET /api/candidates?mode=prematch|live`, returning `count` and JSON-serializable pending `CandidateReview` objects.
- Added human-only `POST /api/candidates/{candidate_id}/approve` and `POST /api/candidates/{candidate_id}/reject` routes. Both use `Depends(_require_api_key)`, resolve candidates with 404s, mark them resolved by `"human"`, remove them from the pending queue, and prepend a deep copy to `candidate_reviews`.
- Approval writes one sorted, pipe-delimited pair of raw team names to the reviewed team alias allowlist and returns the new entry. No AI method is called by the mutating routes.
- Extended `/api/health` without removing existing fields:
  - `verified_groups`
  - `pending_candidates`
  - `unmapped_markets` (a response copy of the imported live dict)
  - `unverified_links`
  - `ai_available`
- Added seven tests covering the brief's four checks plus candidate serialization, health values, allowlist persistence, resolution state, and API-key enforcement.

## TDD trace

### RED: required failing test from the brief

The required test file was created before production changes.

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v
```

Full output (exit code 1):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 4 items

tests\test_candidates_api.py FF..                                        [100%]

================================== FAILURES ===================================
____________________ test_candidates_list_empty_initially _____________________

    def test_candidates_list_empty_initially():
        r = client.get("/api/candidates")
>       assert r.status_code == 200
E       assert 404 == 200
E        +  where 404 = <Response [404 Not Found]>.status_code

tests\test_candidates_api.py:13: AssertionError
____________________ test_health_includes_new_diagnostics _____________________

    def test_health_includes_new_diagnostics():
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        for key in (
            "verified_groups",
            "pending_candidates",
            "unmapped_markets",
            "unverified_links",
        ):
>           assert key in body
E           AssertionError: assert 'verified_groups' in {'live': {'errors': [], 'last_scan_age_sec': None, 'per_bookie': {}}, 'live_matches_cached': 0, 'live_surebets_cached': 0, 'matches_cached': 0, ...}

tests\test_candidates_api.py:27: AssertionError
=============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_candidates_api.py::test_candidates_list_empty_initially - a...
FAILED tests/test_candidates_api.py::test_health_includes_new_diagnostics - A...
================== 2 failed, 2 passed, 3 warnings in 1.56s ===================
Exited with code 1
```

The failures were for the intended reasons: `/api/candidates` was not registered and the health response lacked the new keys.

### RED: expanded behavioral tests before implementation

I expanded the test file before implementing the routes to cover the state transitions and allowlist contract.

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v
```

Full output (exit code 1):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 7 items

tests\test_candidates_api.py EEEEEEE                                     [100%]

=================================== ERRORS ====================================
________________ ERROR at setup of test_candidates_list_empty_initially ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1230>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_candidates_list_empty_ini0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
________________ ERROR at setup of test_candidates_list_serializes_pending_candidates ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1240>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_candidates_list_serialize0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
________________ ERROR at setup of test_health_includes_new_diagnostics ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1250>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_health_includes_new_diagn0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
________________ ERROR at setup of test_approve_unknown_candidate_returns_404 ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1260>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_approve_unknown_candidate0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
________________ ERROR at setup of test_approve_candidate_writes_reviewed_alias_and_resolves_it ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1270>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_approve_candidate_writes_0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
________________ ERROR at setup of test_reject_candidate_records_human_rejection ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1280>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_reject_candidate_records_0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
________________ ERROR at setup of test_candidate_mutations_require_api_key_when_configured ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000000001F2A1290>
tmp_path = WindowsPath('C:/Users/harun/AppData/Local/Temp/pytest-of-harun/pytest-612/test_candidate_mutations_requir0')

    @pytest.fixture(autouse=True)
    def reset_candidate_state(monkeypatch, tmp_path):
>       original_pending = api.pending_candidates.copy()
E       AttributeError: module 'server.api' has no attribute 'pending_candidates'

tests/test_candidates_api.py:19: AttributeError
=============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
ERROR tests/test_candidates_api.py::test_candidates_list_empty_initially
ERROR tests/test_candidates_api.py::test_candidates_list_serializes_pending_candidates
ERROR tests/test_candidates_api.py::test_health_includes_new_diagnostics
ERROR tests/test_candidates_api.py::test_approve_unknown_candidate_returns_404
ERROR tests/test_candidates_api.py::test_approve_candidate_writes_reviewed_alias_and_resolves_it
ERROR tests/test_candidates_api.py::test_reject_candidate_records_human_rejection
ERROR tests/test_candidates_api.py::test_candidate_mutations_require_api_key_when_configured
=============================== 3 warnings, 7 errors in 1.51s ========================
Exited with code 1
```

All seven setup errors were caused by the intentionally not-yet-created module state. The first four-test RED run above is the primary required failure trace.

### GREEN: focused candidate API tests

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 7 items

tests\test_candidates_api.py .......                                     [100%]

============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 7 passed, 3 warnings in 1.18s ========================
```

## Verification

### Full suite before commit

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 34%]
........................................................................ [ 69%]
...............................................................          [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
207 passed, 3 warnings in 3.46s
```

### Initial Ruff check and correction

The first Ruff run after implementation found only test import ordering/unused-import issues.

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 1):

```text
tests\test_candidates_api.py:3:1: I001 [*] Import block is un-sorted or un-formatted
  |
1 | """Candidates review endpoints and health diagnostics."""
2 |
3 | / import json
4 | | from datetime import UTC, datetime
5 | |
6 | import pytest
7 | | from fastapi.testclient import TestClient
8 | |
9 | | from models.schemas import CandidateReview
10 | | from server import api
11 | | from server.app import app
   | |_________________________ I001
   = help: Organize imports

tests\test_candidates_api.py:4:22: F401 [*] `datetime.UTC` imported but unused
  |
3 | import json
4 | from datetime import UTC, datetime
  |                      ^^^ F401
5 |
6 | import pytest
  = help: Remove unused import: `datetime.UTC`

Found 2 errors.
[*] 2 fixable with the `--fix` option.
```

I removed the unused import and ran Ruff's targeted autofix for import ordering:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check tests/test_candidates_api.py --fix
Found 1 error (1 fixed, 0 remaining).
```

### Mypy before commit

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 47 source files
```

### Commit and staged whitespace check

Commands:

```text
git add server/api.py tests/test_candidates_api.py
git diff --cached --check
git commit -m "feat(mapping): add candidates review endpoints and health diagnostics"
```

Full output:

```text
warning: in the working copy of 'tests/test_candidates_api.py', LF will be replaced by CRLF the next time Git touches it
[master f514da0] feat(mapping): add candidates review endpoints and health diagnostics
 2 files changed, 242 insertions(+), 1 deletion(-)
 create mode 100644 tests/test_candidates_api.py
```

### Fresh post-commit verification

The verification commands were rerun after the commit.

Full-suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 34%]
........................................................................ [ 69%]
...............................................................          [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the FastAPI docs:
          https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
207 passed, 3 warnings in 3.68s
```

**Explicit passed-test count: 207 passed, 0 failed (plus 3 existing deprecation warnings).**

Ruff command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Mypy command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 47 source files
```

Repository identity/status commands:

```text
git rev-parse HEAD
git status --short --branch
```

Full output (exit code 0):

```text
f514da0188fd6f11dd03bb3daca1dbaa80f18b27
## master
```

## Deviations from the brief and why

- The brief supplied four minimal tests; I added three tests for the actual state transition, persisted allowlist, health values, and API-key behavior. This keeps the required four tests and increases regression coverage.
- `_load_allowlist` validates that the JSON object contains an `aliases` list and filters non-string values before returning a `set[str]`. This is a defensive equivalent of the brief's direct load-and-`.get()` expression and prevents malformed configuration from crashing approval.
- The brief's concrete approval implementation writes the reviewed team alias only. No league-equivalence pair is written because `CandidateReview` has no pair of source league names; `config/league_equivalences.json` remains owned by the matcher. This follows the concrete endpoint code and the plan's clarified allowlist rule.
- The brief lists `CertaintyGate` and `MatchEvidence` as consumed interfaces, but neither is used by the specified candidate endpoint or health implementation. They were not imported as dead dependencies; the matcher remains the consumer of those contracts and Ruff remains clean.

## Concerns

- The full suite passes, but emits the repository's existing Starlette/FastAPI `on_event` and `TestClient` deprecation warnings.
- Mypy emits pre-existing `annotation-unchecked` notes in unrelated modules; it exits successfully with no type errors.
- Candidate state is intentionally module-level/in-memory as required, so pending reviews and review history do not survive a process restart.
- `verified_groups` follows the brief's exact formula over report entries containing `status`. The current matcher debug-report serializer does not currently emit a `status` key, so a scan-produced report may report zero verified groups until that serializer is updated by the mapping integration task. The API field itself is present and correctly counts status-bearing report entries.
- The approval path has no cross-request file lock; concurrent human approvals could theoretically perform a read/modify/write race on the allowlist. The task does not specify concurrent review traffic, and normal single-user review requests are safe.

## Fix round 1 — 2026-09-25

**Status:** DONE_WITH_CONCERNS  
**Commit:** `9283bd966a5ea00135eb74e6a6532578212badc3`  
**Base commit:** `f514da0188fd6f11dd03bb3daca1dbaa80f18b27`

### Findings addressed

1. **Real producer/consumer health mismatch (finding 1):** Chose the producer-side option. `MatchMatcher.get_match_report()` now emits each group's real `status`, so both `/api/debug/report` and `/api/health` consume the same status-bearing report data. The replacement health test uses the real path `MatchMatcher().group_matches(...) -> get_match_report(...) -> cached_match_groups_report -> /api/health`; it no longer fabricates a status-only report dict.
2. **Atomic and serialized allowlist persistence (finding 2):** `_save_allowlist()` now writes a temporary file in the allowlist's directory, flushes and fsyncs it, and uses `os.replace()`. Approval holds a module-level `threading.Lock` around the complete load/add/save read-modify-write. **Concurrency assumption:** the application runs as one worker process, so an in-process lock covers concurrent request threads in that process; the lock does not coordinate independent worker processes. Atomic replacement still prevents a same-process matcher/reader from observing a truncated JSON file.
3. **Cross-task matcher contract (finding 3):** Added a real approval-to-matcher test that points the matcher at the temporary allowlist, approves the Lech candidate, constructs two real `Match` objects, and asserts the resulting group is `verified`. Added a duplicate-approval test and a concurrent-approval preservation test.
4. **Missing required test (finding 4):** Added `test_reject_unknown_candidate_returns_404()`.

The previously confirmed behaviors were retained: the allowlist path/shape, live `unmapped_markets` reference, route authentication split, resolution state transitions, duplicate 404 behavior, and existing health fields.

### Covering files

- `tests/test_candidates_api.py` — real-producer health test, real matcher approval test, atomic-reader test, concurrent-approval test, duplicate approval, and missing rejection test.
- `engine/matcher.py` — emits `status` in the real debug report.
- `server/api.py` — atomic allowlist replacement and in-process read-modify-write lock.

### TDD RED after adding the fix-round tests

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v
```

Full output (exit code 1):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 12 items

tests\test_candidates_api.py ..F.....FF..                                [100%]

================================== FAILURES ===================================
____________________ test_health_includes_new_diagnostics _____________________

    def test_health_includes_new_diagnostics():
        matcher = MatchMatcher()
        groups = matcher.group_matches(
            [
                _mapping_match("mdshop", "Lech Poznan", "Opponent", "mdshop-1"),
                _mapping_match("mbet", "Lech P.", "Opponent", "mbet-1"),
            ]
        )
        report = matcher.get_match_report(groups)
        assert groups and groups[0].status == "verified"
>       assert report and report[0]["status"] == "verified"
                          ^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'status'

tests/test_candidates_api.py:105: KeyError
_____________ test_allowlist_replace_is_atomic_for_concurrent_reader _____________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000001FF0EEB6F10>

    def test_allowlist_replace_is_atomic_for_concurrent_reader(monkeypatch):
        api._save_allowlist({"before"})
        original_dump = json.dump
        dump_started = threading.Event()
        release_dump = threading.Event()
        errors: list[BaseException] = []

        def paused_dump(payload, file, *args, **kwargs):
            file.flush()
            dump_started.set()
            release_dump.wait(5)
            return original_dump(payload, file, *args, **kwargs)

        monkeypatch.setattr(api.json, "dump", paused_dump)

        def write_allowlist():
            try:
                api._save_allowlist({"after"})
            except BaseException as exc:  # pragma: no cover - surfaced by assertion below
                errors.append(exc)

        writer = threading.Thread(target=write_allowlist)
        writer.start()
        try:
            assert dump_started.wait(5)
            for _ in range(20):
                with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
>                   observed = json.load(file)
                               ^^^^^^^^^^^^^^^
tests/test_candidates_api.py:227: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\json\__init__.py:293: in load
    return loads(fp.read(),
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\json\__init__.py:346: in loads
    return _default_decoder.decode(s)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

tests/test_candidates_api.py:227: JSONDecodeError
_____________ test_concurrent_approvals_preserve_both_aliases _______________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000001FF0EEB6F30>

    def test_concurrent_approvals_preserve_both_aliases(monkeypatch):
        first_candidate = _candidate("candidate-1", "Alpha Town", "Alpha")
        second_candidate = _candidate("candidate-2", "Beta Town", "Beta")
        api.pending_candidates[first_candidate.id] = first_candidate
        api.pending_candidates[second_candidate.id] = second_candidate

        real_save = api._save_allowlist
        save_count = 0
        save_count_lock = threading.Lock()
        first_save_entered = threading.Event()
        release_first_save = threading.Event()
        errors: list[BaseException] = []

        def controlled_save(aliases):
            nonlocal save_count
            with save_count_lock:
                save_count += 1
                number = save_count
            if number == 1:
                first_save_entered.set()
                release_first_save.wait(1.0)
            elif number == 2:
                release_first_save.set()
            real_save(aliases)

        def approve(candidate_id: str):
            try:
                asyncio.run(api.approve_candidate(candidate_id, _auth=None))
            except BaseException as exc:  # pragma: no cover - surfaced by assertion below
                errors.append(exc)

        monkeypatch.setattr(api, "_save_allowlist", controlled_save)
        first_thread = threading.Thread(target=approve, args=(first_candidate.id,))
        first_thread.start()
        assert first_save_entered.wait(5)

        second_thread = threading.Thread(target=approve, args=(second_candidate.id,))
        second_thread.start()
        first_thread.join(5)
        second_thread.join(5)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert not errors
        with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
            aliases = set(json.load(file)["aliases"])
>       assert aliases == {"Alpha|Alpha Town", "Beta|Beta Town"}
E       AssertionError: assert {'Alpha|Alpha Town'} == {'Alpha|Alpha...ta|Beta Town'}
E         Extra items in the right set:
E         'Beta|Beta Town'
E         Use -v to get this diff

tests/test_candidates_api.py:285: AssertionError
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_candidates_api.py::test_health_includes_new_diagnostics
FAILED tests/test_candidates_api.py::test_allowlist_replace_is_atomic_for_concurrent_reader
FAILED tests/test_candidates_api.py::test_concurrent_approvals_preserve_both_aliases
================== 3 failed, 9 passed, 3 warnings in 1.77s ===================
Exited with code 1
```

The three failures were the intended regressions: the real report omitted `status`, a reader saw the live file while it was truncated, and concurrent approvals lost one alias.

### TDD GREEN after implementation

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_candidates_api.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 12 items

tests\test_candidates_api.py ............                                [100%]

============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 12 passed, 3 warnings in 2.45s ========================
```

### Full-suite, lint, and typecheck verification before commit

Full-suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 33%]
........................................................................ [ 67%]
....................................................................     [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
212 passed, 3 warnings in 4.91s
```

**Explicit passed-test count: 212 passed, 0 failed (plus 3 existing deprecation warnings).**

Ruff command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Mypy command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:204: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:249: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 47 source files
```

### Commit and fresh post-commit verification

Commands:

```text
git add engine/matcher.py server/api.py tests/test_candidates_api.py
git diff --cached --check
git commit -m "fix(mapping): harden candidate review persistence and diagnostics"
```

Full output:

```text
warning: in the working copy of 'tests/test_candidates_api.py', LF will be replaced by CRLF the next time Git touches it
[master 9283bd9] fix(mapping): harden candidate review persistence and diagnostics
 3 files changed, 192 insertions(+), 11 deletions(-)
```

Fresh post-commit full-suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 33%]
........................................................................ [ 67%]
....................................................................     [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          FastAPI docs: https://fastapi.tiangolo.com/advanced/events/
          

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
212 passed, 3 warnings in 5.08s
```

**Explicit passed-test count: 212 passed, 0 failed.**

Fresh post-commit Ruff command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Fresh post-commit mypy command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:204: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:249: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 47 source files
```

Repository identity/status commands:

```text
git rev-parse HEAD
git status --short --branch
```

Full output (exit code 0):

```text
9283bd966a5ea00135eb74e6a6532578212badc3
## master
```

### Fix-round concerns

- The in-process lock assumes one worker process, matching the module-level in-memory application state; multi-worker deployment would need an inter-process file lock or a single writer service.
- Existing FastAPI/Starlette deprecation warnings and mypy's informational `annotation-unchecked` notes remain; both commands exit successfully.
- The test suite uses a one-second scheduling window in the concurrent-approval test to force the old read/modify/write race deterministically; it is not a timing-sensitive success condition after the lock is present.

