# Task 6 Report — Hosted-AI propose-only adapter

**Status:** DONE_WITH_CONCERNS  
**Commit:** `3407cdcd8e0926a010b8880efbc74e33a4bc8d35`  
**Branch:** `master` (worked in place; no worktree or branch created)  
**Date:** 2026-09-25

## What changed

- Created `engine/ai.py` as a hosted, OpenAI-compatible HTTP adapter using `httpx`.
- Added `PairProposal` with only proposal fields:
  `match_a_book`, `match_b_book`, `same_event`, `confidence`, `reason`, `suggested_alias`, and `suggested_league_equivalence`.
  There is no `approved` or `status` field, and `MatchAI` has no approve method.
- Added environment-backed configuration through `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL`, with the supplied OpenAI-compatible defaults and `10.0`-second timeout.
- Implemented `available`, `_chat`, `suggest_pairs`, and `propose_alias`.
  `suggest_pairs` short-circuits when unavailable or given no input, parses AI JSON into proposals, and returns `[]` on chat/JSON failures. Network failures are logged and degrade to an empty proposal set, allowing rules-only operation.
- Created `tests/test_ai_adapter.py` with the five contract tests from the brief. Tests inject `FakeAI._chat` or an overriding failing `_chat`; no network request is made by the test suite.
- No dependency changes were needed because `httpx` is already pinned in `requirements.txt`.

## TDD trace

### RED: required failing test

The test file was created before `engine/ai.py`.

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v
```

Full output (exit code 2):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 0 items / 1 error

=================================== ERRORS ====================================
_________________ ERROR collecting tests/test_ai_adapter.py __________________
ImportError while importing test module 'C:\Users\harun\OneDrive\Documenti\surebetmuse12\tests\test_ai_adapter.py'.
Hint: make sure that test modules/packages have valid Python module names.
Traceback:
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:7: in <module>
    from engine.ai import MatchAI, PairProposal
E   ModuleNotFoundError: No module named 'engine.ai'
=========================== short test summary info ===========================
ERROR tests/test_ai_adapter.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.93s ===============================
Exited with code 2
```

The failure was for the intended reason: `engine.ai` did not exist yet.

### GREEN: focused adapter test

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 5 items

tests\test_ai_adapter.py .....                                           [100%]

============================== 5 passed in 0.62s ==============================
```

The focused contract passed all five tests, including the 0.99-confidence no-auto-approval check and graceful network-failure behavior.

## Verification commands and full output

### Initial full-suite/lint/typecheck pass

The first full-suite and Ruff runs after the initial transcription were:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

```text
........................................................................ [ 38%]
........................................................................ [ 76%]
.............................................                            [100%]
189 passed in 4.39s
```

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

```text
All checks passed!
```

The first mypy run exposed one type issue in the supplied one-line base-URL expression:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 1):

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
engine\ai.py:41: error: Item "None" of "str | None" has no attribute "rstrip"  [union-attr]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Found 1 error in 1 file (checked 46 source files)

Exited with code 1
```

I changed only the base-URL initialization to an equivalent `if/else` form that preserves the explicit argument/environment fallback and allows mypy to narrow the type. No behavior was changed.

After that type-only correction, the focused test and checks were run again:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v
```

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 5 items

tests\test_ai_adapter.py .....                                           [100%]

============================== 5 passed in 0.64s ==============================
```

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

```text
All checks passed!
```

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
Success: no issues found in 46 source files
```

The ten `annotation-unchecked` lines are informational pre-existing notes; mypy found no type errors after the correction.

## Commit and final post-commit verification

Staged whitespace check and commit command:

```text
git add engine/ai.py tests/test_ai_adapter.py && git diff --cached --check && git commit -m "feat(mapping): add hosted-AI adapter for pair proposals (propose-only, graceful degradation)"
```

Full output:

```text
warning: in the working copy of 'engine/ai.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_ai_adapter.py', LF will be replaced by CRLF the next time Git touches it
[master 3407cdc] feat(mapping): add hosted-AI adapter for pair proposals (propose-only, graceful degradation)
 2 files changed, 170 insertions(+)
 create mode 100644 engine/ai.py
 create mode 100644 tests/test_ai_adapter.py
```

The post-commit full test suite was run with:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 38%]
........................................................................ [ 76%]
.............................................                            [100%]
189 passed in 4.26s
```

**Explicit passed-test count: 189 passed, 0 failed.**

Post-commit Ruff command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Post-commit mypy command:

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
Success: no issues found in 46 source files
```

Repository state and full commit SHA:

```text
git rev-parse HEAD && git status --short --branch
```

Full output (exit code 0):

```text
3407cdcd8e0926a010b8880efbc74e33a4bc8d35
## master
```

## Deviations and concerns

- **Deviation:** The brief's single-expression base-URL assignment was written as equivalent `if/else` statements. This was necessary to resolve the initial mypy `union-attr` error while preserving the same explicit-argument and `AI_BASE_URL` fallback behavior.
- **Concern:** Mypy emits pre-existing `annotation-unchecked` notes in unrelated files; it still exits successfully with no issues.
- **Concern:** Git emitted LF-to-CRLF warnings while staging on Windows; the committed files are intact and all verification passed.
- No functional concerns were found. No network calls were made by the tests, and the adapter contains no approval/status mechanism.

## Fix round 1 — 2026-09-25

**Status:** DONE_WITH_CONCERNS  
**Commit:** `ffe741fd25f83331f5cb00b4d1d08d2451bfac88`  
**Base commit:** `3407cdcd8e0926a010b8880efbc74e33a4bc8d35`

### Files and coverage

- Updated production file: `engine/ai.py`.
- Expanded covering test file: `tests/test_ai_adapter.py`.
- Added regression coverage for:
  - top-level JSON `null`, list, number, and string responses;
  - non-JSON-serializable input pairs;
  - the no-key guard not invoking `_chat`;
  - out-of-range confidence rejection;
  - the one-proposal-per-submitted-pair cap;
  - propagation of `VERIFY_SSL` to the default `httpx.AsyncClient`;
  - injected-client async context-manager and `aclose()` lifecycle behavior.
- The tests use fakes/recording clients and make no network calls.

### TDD RED: review regression tests before implementation

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v
```

Full output (exit code 1):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 16 items

tests\test_ai_adapter.py .....FFFFF.FFFFF                                [100%]

================================== FAILURES ===================================
______________ test_suggest_pairs_rejects_non_object_json[null] _______________
content = 'null'

    @pytest.mark.parametrize("content", ["null", "[]", "42", '\"not an object\"'])
    def test_suggest_pairs_rejects_non_object_json(content):
        ai = RawResponseAI(content)
>       assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:106: in test_suggest_pairs_rejects_non_object_json
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:11: in run
    return asyncio.run(coro)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\futures.py:365: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^
self = <RawResponseAI object at 0x000001DBB3F2100>
pairs = [{'a': 'x', 'b': 'y'}]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
        try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
>       for p in data.get("proposals", []):
                 ^^^^^^^^
E       AttributeError: 'NoneType' object has no attribute 'get'

engine\ai.py:84: AttributeError
______________ test_suggest_pairs_rejects_non_object_json[[]] ______________
content = '[]'

    @pytest.mark.parametrize("content", ["null", "[]", "42", '\"not an object\"'])
    def test_suggest_pairs_rejects_non_object_json(content):
        ai = RawResponseAI(content)
>       assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:106: in test_suggest_pairs_rejects_non_object_json
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:11: in run
    return asyncio.run(coro)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\futures.py:365: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^
self = <RawResponseAI object at 0x000001DBB3F2100>
pairs = [{'a': 'x', 'b': 'y'}]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
        try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
>       for p in data.get("proposals", []):
                 ^^^^^^^^
E       AttributeError: 'list' object has no attribute 'get'

engine\ai.py:84: AttributeError
______________ test_suggest_pairs_rejects_non_object_json[42] _______________
content = 42

    @pytest.mark.parametrize("content", ["null", "[]", "42", '\"not an object\"'])
    def test_suggest_pairs_rejects_non_object_json(content):
        ai = RawResponseAI(content)
>       assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:106: in test_suggest_pairs_rejects_non_object_json
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:11: in run
    return asyncio.run(coro)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\futures.py:365: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^
self = <RawResponseAI object at 0x000001DBB3F2100>
pairs = [{'a': 'x', 'b': 'y'}]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
        try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
>       for p in data.get("proposals", []):
                 ^^^^^^^^
E       AttributeError: 'int' object has no attribute 'get'

engine\ai.py:84: AttributeError
______________ test_suggest_pairs_rejects_non_object_json["not an object"] ________
content = 'not an object'

    @pytest.mark.parametrize("content", ["null", "[]", "42", '\"not an object\"'])
    def test_suggest_pairs_rejects_non_object_json(content):
        ai = RawResponseAI(content)
>       assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:106: in test_suggest_pairs_rejects_non_object_json
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:11: in run
    return asyncio.run(coro)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\futures.py:365: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^
self = <RawResponseAI object at 0x000001DBB3F2100>
pairs = [{'a': 'x', 'b': 'y'}]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
        try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
>       for p in data.get("proposals", []):
                 ^^^^^^^^
E       AttributeError: 'str' object has no attribute 'get'

engine\ai.py:84: AttributeError
____________________ test_suggest_pairs_degrades_for_non_serializable_input ____________________

    def test_suggest_pairs_degrades_for_non_serializable_input():
        ai = FakeAI([])
>       assert run(ai.suggest_pairs([{"a": {"x", "y"}, "b": "z"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:111: in test_suggest_pairs_degrades_for_non_serializable_input
    assert run(ai.suggest_pairs([{"a": {"x", "y"}, "b": "z"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:11: in run
    return asyncio.run(coro)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\futures.py:365: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^
self = <FakeAI object at 0x000001DBB3F2100>
pairs = [{'a': {'x', 'y'}, 'b': 'z'}]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
>       try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
        for p in data.get("proposals", []):
            try:
                out.append(PairProposal(
                    match_a_book=str(p["a"]), match_b_book=str(p["b"]),
                    same_event=bool(p["same_event"]), confidence=float(p["confidence"]),
                    reason=str(p.get("reason", "")),
                    suggested_alias=p.get("alias"),
                    suggested_league_equivalence=p.get("league_equiv"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

tests\test_ai_adapter.py:111: in test_suggest_pairs_degrades_for_non_serializable_input
    assert run(ai.suggest_pairs([{"a": {"x", "y"}, "b": "z"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_ai_adapter.py:11: in run
    return asyncio.run(coro)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\futures.py:365: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^
self = <FakeAI object at 0x000001DBB3F2100>
pairs = [{'a': {'x', 'y'}, 'b': 'z'}]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
>       try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
        for p in data.get("proposals", []):
            try:
                out.append(PairProposal(
                    match_a_book=str(p["a"]), match_b_book=str(p["b"]),
                    same_event=bool(p["same_event"]), confidence=float(p["confidence"]),
                    reason=str(p.get("reason", "")),
                    suggested_alias=p.get("alias"),
                    suggested_league_equivalence=p.get("league_equiv"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

E               TypeError: Object of type set is not JSON serializable

engine\ai.py:75: TypeError
_________________ test_suggest_pairs_rejects_out_of_range_confidence[-0.1] __________________
confidence = -0.1

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_suggest_pairs_rejects_out_of_range_confidence(confidence):
        ai = FakeAI([{"a": "x", "b": "y", "same_event": True,
                      "confidence": confidence, "reason": "out of range"}])
>       assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:133: in test_suggest_pairs_rejects_out_of_range_confidence
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           AssertionError: assert [PairProposal(match_a_book='x', match_b_book='y', same_event=True, confidence=-0.1, reason='out of range', suggested_alias=None, suggested_league_equivalence=None)] == []
E
E            +  where False = [PairProposal(match_a_book='x', match_b_book='y', same_event=True, confidence=-0.1, reason='out of range', suggested_alias=None, suggested_league_equivalence=None)]
E            +    where True = []
_________________ test_suggest_pairs_rejects_out_of_range_confidence[1.1] __________________
confidence = 1.1

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_suggest_pairs_rejects_out_of_range_confidence(confidence):
        ai = FakeAI([{"a": "x", "b": "y", "same_event": True,
                      "confidence": confidence, "reason": "out of range"}])
>       assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_ai_adapter.py:133: in test_suggest_pairs_rejects_out_of_range_confidence
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           AssertionError: assert [PairProposal(match_a_book='x', match_b_book='y', same_event=True, confidence=1.1, reason='out of range', suggested_alias=None, suggested_league_equivalence=None)] == []
E
E            +  where False = [PairProposal(match_a_book='x', match_b_book='y', same_event=True, confidence=1.1, reason='out of range', suggested_alias=None, suggested_league_equivalence=None)]
E            +    where True = []
____________________ test_suggest_pairs_caps_proposals_to_submitted_pair_count ____________________

    def test_suggest_pairs_caps_proposals_to_submitted_pair_count():
        ai = FakeAI([
            {"a": "x", "b": "y", "same_event": True, "confidence": 0.8, "reason": "one"},
            {"a": "x", "b": "z", "same_event": True, "confidence": 0.7, "reason": "two"},
            {"a": "x", "b": "w", "same_event": True, "confidence": 0.6, "reason": "three"},
        ])
>       out = run(ai.suggest_pairs([{"a": "x", "b": "y"}]))
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           AssertionError: assert 3 == 1
E            +  where False = 3
E            +    where True = 1

tests\test_ai_adapter.py:143: AssertionError
________________________ test_default_chat_passes_ssl_verification_setting ________________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000001DBB3F2100>

    def test_default_chat_passes_ssl_verification_setting(monkeypatch):
        import engine.ai as ai_module
        from config.settings import VERIFY_SSL

        created = []

        class Client(RecordingClient):
            def __init__(self, **kwargs):
                super().__init__("{}", **kwargs)
                created.append(self)

        monkeypatch.setattr(ai_module.httpx, "AsyncClient", Client)
        ai = MatchAI(api_key="test", base_url="http://test", model="test")
        assert run(ai._chat([{"role": "user", "content": "x"}])) == "{}"
>       assert created[0].kwargs.get("verify") is VERIFY_SSL
E       AssertionError: assert None is False
E        +  where None = <built-in method get of dict object at 0x000001DBB3F2100>('verify')
E        +    where False = <built-in method get of dict object at 0x000001DBB3F2100>('verify')
E        +        where False = {'timeout': 10.0}.get('verify')
E        +        where {'timeout': 10.0} = <test_ai_adapter.test_default_chat_passes_ssl_verification_setting.<locals>.Client object at 0x000001DBB3F2100>

tests\test_ai_adapter.py:160: AssertionError
___________________________ test_injected_client_has_lifecycle_seam __________________________

    def test_injected_client_has_lifecycle_seam():
        client = RecordingClient(content='{\"proposals\": []}')

        async def exercise():
            ai = MatchAI(api_key="test", base_url="http://test", model="test", client=client)
>           async with ai:
                ^^^^^^^^^^^^^^
E           TypeError: MatchAI.__init__() got an unexpected keyword argument 'client'

tests\test_ai_adapter.py:167: TypeError
=============================== short test summary info ===========================
FAILED tests/test_ai_adapter.py::test_suggest_pairs_rejects_non_object_json[null]
FAILED tests/test_ai_adapter.py::test_suggest_pairs_rejects_non_object_json[[]]
FAILED tests/test_ai_adapter.py::test_suggest_pairs_rejects_non_object_json[42]
FAILED tests/test_ai_adapter.py::test_suggest_pairs_rejects_non_object_json["not an object"]
FAILED tests/test_ai_adapter.py::test_suggest_pairs_degrades_for_non_serializable_input
FAILED tests/test_ai_adapter.py::test_suggest_pairs_rejects_out_of_range_confidence[-0.1]
FAILED tests/test_ai_adapter.py::test_suggest_pairs_rejects_out_of_range_confidence[1.1]
FAILED tests/test_ai_adapter.py::test_suggest_pairs_caps_proposals_to_submitted_pair_count
FAILED tests/test_ai_adapter.py::test_default_chat_passes_ssl_verification_setting
FAILED tests/test_ai_adapter.py::test_injected_client_has_lifecycle_seam
========================= 10 failed, 6 passed in 1.37s ==========================
Exited with code 1
```

The failures confirmed the reported containment, serialization, validation, cap, SSL, and missing-seam defects before production changes.

### TDD GREEN: focused adapter tests

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 16 items

tests\test_ai_adapter.py ................                                [100%]

============================== 16 passed in 0.61s ==============================
```

**Explicit focused passed-test count: 16 passed, 0 failed.**

### Full verification before commit

Full test suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 36%]
........................................................................ [ 72%]
........................................................                 [100%]
200 passed in 3.72s
```

**Explicit full-suite passed-test count: 200 passed, 0 failed.**

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
Success: no issues found in 46 source files
```

The `annotation-unchecked` lines are pre-existing informational notes; mypy reports no type errors.

### Commit

Command:

```text
git add engine/ai.py tests/test_ai_adapter.py && git diff --cached --check && git commit -m "fix(mapping): harden AI adapter error containment"
```

Full output:

```text
warning: in the working copy of 'engine/ai.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_ai_adapter.py', LF will be replaced by CRLF the next time Git touches it
[master ffe741f] fix(mapping): harden AI adapter error containment
 2 files changed, 194 insertions(+), 31 deletions(-)
```

### Post-commit verification

Full test suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output (exit code 0):

```text
........................................................................ [ 36%]
........................................................................ [ 72%]
........................................................                 [100%]
200 passed in 4.82s
```

**Explicit post-commit passed-test count: 200 passed, 0 failed.**

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
Success: no issues found in 46 source files
```

Repository state and full commit SHA:

```text
git rev-parse HEAD && git status --short --branch
```

Full output (exit code 0):

```text
ffe741fd25f83331f5cb00b4d1d08d2451bfac88
## master
```

### Lifecycle seam and Task 10 usage

`MatchAI` now accepts an optional `client: httpx.AsyncClient | None`, uses that client for all calls when supplied, and exposes `aclose()` plus `async with MatchAI(...)` support. The default path still creates and closes an `AsyncClient` per `_chat` call, so this round does not change current per-call behavior. Task 10 should create one long-lived `httpx.AsyncClient`, pass it as `client=...`, reuse the same `MatchAI` instance for its candidate calls, and let `await ai.aclose()` or `async with MatchAI(client=...)` close it.

### Complete deviations list

1. The brief's interface lists literal defaults for `base_url` and `model`, while the implementation uses `str | None = None` plus `AI_BASE_URL`/`AI_MODEL` environment fallbacks (`https://api.openai.com/v1` and `gpt-4o-mini`). This behavior is equivalent and was intentionally left unchanged.
2. The base-URL assignment remains the equivalent `if/else` form from the initial round rather than the brief's single expression; this was needed for mypy type narrowing.
3. The adapter now imports and passes `VERIFY_SSL` to the default `httpx.AsyncClient`, as required by the review.
4. The adapter now has an optional injected `client`, `aclose()`, and async context-manager methods. Default per-call client creation remains unchanged; only callers that inject a client opt into reuse.
5. Out-of-range confidence values are rejected (rather than clamped), which is one of the two remedies allowed by the findings and prevents invalid values reaching downstream review/filter logic.
6. Proposal output is capped at one accepted proposal per submitted pair; invalid proposals do not count toward the cap, and processing stops once the cap is reached.
7. The top-level response type and proposal collection type are explicitly guarded, and the complete message construction, parse, validation, and build path is enclosed by the outer `Exception` containment block.
8. The covering test file was expanded from five tests to sixteen collected tests (including parametrized cases); no new runtime dependency or approval/status mechanism was added.

### Concerns

- Mypy emits pre-existing `annotation-unchecked` notes in unrelated files but exits successfully with no type errors.
- Git emitted LF-to-CRLF warnings while staging on Windows.
- The injected client is adapter-managed when passed: `ai.aclose()` closes it. Task 10 must therefore use one adapter/client owner and avoid closing the same client independently before leaving the adapter context.

