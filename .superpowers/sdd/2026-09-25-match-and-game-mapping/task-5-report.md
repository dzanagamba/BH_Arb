# Task 5 Report — Per-book deep-link configuration and `build_event_url`

**Status:** DONE_WITH_CONCERNS  
**Commit:** `674fab8196728e5505396f830cca2e78c7d72df0`  
**Branch:** `master` (worked in place; no worktree or branch created)  
**Date:** 2026-09-25

## What changed

- Created `config/bookmaker_deeplinks.json` with the declarations from the brief:
  - `mdshop` and `admiralbet` support per-event IDs and provide event templates.
  - `wwin`, `mbet`, `sportplus`, `evlbet`, `premier_kladionica`, and `betole` explicitly declare `supports_event_id: false` and include the supplied no-event-link notes.
- Added `DEEP_LINK_CONFIG` to `config/settings.py`, pointing at the new JSON file.
- Added the lazy JSON configuration loader and `build_event_url(bookmaker, event_id, base_url, live=False)` to `scrapers/common.py`. The helper preserves the existing `nsoft_event_url` implementation and does not add a module-level `engine.*` import, so the known `engine`/`scrapers.common` cycle is not reintroduced.
- Added `event_id=<provider event id>` and `deep_link_verified=False` to every production `Match` construction in the nine scrapers (including both live/prematch construction paths where applicable). No scraper marks a link verified before the later on-demand check.
- Created `tests/test_deeplinks.py` with the four tests specified in the brief.

## TDD trace

### RED: required failing test

The test file was created before the helper/config implementation.

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py -v
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
_________________ ERROR collecting tests/test_deeplinks.py ___________________
ImportError while importing test module 'C:\Users\harun\OneDrive\Documenti\surebetmuse12\tests\test_deeplinks.py'.
Hint: make sure that test modules/packages have valid Python module names.
Traceback:
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_deeplinks.py:4: in <module>
    from scrapers.common import build_event_url
E   ImportError: cannot import name 'build_event_url' from 'scrapers.common' (C:\Users\harun\OneDrive\Documenti\surebetmuse12\scrapers\common.py)
=========================== short test summary info ===========================
ERROR tests/test_deeplinks.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 1.10s ===============================
```

The failure was for the intended reason: `build_event_url` did not exist yet.

### GREEN: focused deep-link test

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 4 items

tests\test_deeplinks.py ....                                             [100%]

============================== 4 passed in 0.61s ==============================
```

### GREEN: deep-link and existing URL regressions

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py tests/test_urls.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 13 items

tests\test_deeplinks.py ....                                             [ 30%]
tests\test_urls.py .........                                             [100%]

============================= 13 passed in 0.64s ==============================
```

The existing `nsoft_event_url` tests and per-match URL behavior remain green.

## Final verification

All final commands below were run after the implementation and after the commit.

### Full test suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -o addopts="" -q
```

Full output (exit code 0):

```text
........................................................................ [ 41%]
........................................................................ [ 83%]
.............................                                            [100%]
173 passed in 3.94s
```

**Explicit passed-test count: 173 passed, 0 failed.**

### Ruff

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

### Mypy

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
Success: no issues found in 44 source files
```

The annotation notes are pre-existing notes about untyped function bodies; mypy reports no type errors.

### Import-cycle smoke check

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -c "import engine; import scrapers.common; print('imports ok')"
```

Full output (exit code 0):

```text
imports ok
```

### Staged diff check and commit

Before committing, the staged whitespace check was run:

```text
git diff --cached --check
```

Full output (exit code 0):

```text
```

Commit command:

```text
git commit -m "feat(mapping): add per-book deep-link config and build_event_url"
```

Full output:

```text
[master 674fab8] feat(mapping): add per-book deep-link config and build_event_url
 13 files changed, 86 insertions(+)
 create mode 100644 config/bookmaker_deeplinks.json
 create mode 100644 tests/test_deeplinks.py
```

Full commit SHA:

```text
674fab8196728e5505396f830cca2e78c7d72df0
```

Post-commit repository state:

```text
## master
674fab8196728e5505396f830cca2e78c7d72df0
```

## Deviations from the brief and why

1. The brief's Step 6 staging command names only `config/bookmaker_deeplinks.json`, `scrapers/common.py`, and `tests/test_deeplinks.py`, while the task requirements also explicitly require `config/settings.py` and every scraper to be modified. I staged and committed all required files so the stated per-book metadata and settings path are actually included.
2. The exact JSON block in the brief contains eight bookmakers and does not contain `mozzartbet`, although the repository has a Mozzartbet scraper and the task says “each scraper.” I did not invent an unprovided Mozzartbet template or note; its scraper still populates `event_id` and starts unverified, and `build_event_url` falls back to the caller's base URL for an undeclared book. See the concern below.
3. No `engine/certainty.py` change was made. The current gate's existing no-event-link classification depends on an empty `event_id`/`url`; the configuration notes and on-demand evidence handling are left to the later verification task. This task correctly leaves all production links unverified rather than claiming verification.

## Concerns

- The brief's exact deep-link JSON omits `mozzartbet` even though Mozzartbet is a configured bookmaker and has a scraper. If the later policy requires every configured book to have an explicit `supports_event_id` declaration, Mozzartbet needs a reviewed `false` entry (and an agreed no-event-link note) before the evidence/reporting layer is finalized.
- At scrape time, the unsupported-book scrapers still retain their existing sport/base URLs and provider event IDs. Therefore the current certainty gate will conservatively classify them as `link_unverified` until the later link-verification/evidence integration consults the `supports_event_id: false` declarations. No false `verified` claim is made by this task.
- The supplied helper intentionally ignores its `live` argument and returns the configured template unchanged for unsupported books; this matches the brief's implementation and tests, but live-specific URL behavior should be revisited if the later checker requires separate live templates.
- The deep-link configuration cache is process-local and invalid JSON/missing files degrade to an empty configuration, as specified by the brief.

**Final status:** DONE_WITH_CONCERNS

---

## Fix round 1 — Review findings

**Status:** DONE_WITH_CONCERNS  
**Commit:** `5c4bd346c68030766dfa07e832ee81eaffaec609`  
**Date:** 2026-09-25  
**Branch:** `master` (worked in place; no worktree or branch created)

### Findings addressed

1. **Mozzartbet declaration:** added an explicit `mozzartbet` entry to `config/bookmaker_deeplinks.json`. It is declared `supports_event_id: true` with both public per-event templates.
2. **Declared versus undeclared books:** added `has_declaration(bookmaker) -> bool`. A declared-false book and an undeclared book can now be distinguished without wiring the later certainty gate to the helper.
3. **Helper robustness:** added mode-specific `template_live` selection, placeholder validation for event-enabled templates, normalized non-event fallback for empty/`None` IDs, and `urllib.parse.quote(..., safe="")` URL encoding. Invalid enabled templates fail closed with `ValueError` rather than returning a misleading URL.
4. **Configuration invariant tests:** `tests/test_deeplinks.py` now checks that the config key set equals `set(BOOKMAKERS)`, every false declaration has a note, and every enabled event template has `{event_id}`.

### Mozzartbet decision and evidence

**Decision: `supports_event_id: true`.**

The repository already extracts a real provider identifier in `scrapers/mozzartbet.py:380`:

```python
mid = str(event.get("id", event.get("matchId", event.get("eventId", ""))))
```

The same value is assigned to `Match.event_id` at the scraper's `Match` construction. The existing `MATCH_URL_TEMPLATES["mozzartbet"]` is the generic football board:

```text
https://www.mozzartbet.ba/sr/kladjenje/sport/1
```

I checked the public route pattern against a provider `id` (`73601748` from the live board). The prematch and live per-event routes both returned HTTP 200:

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -c "import httpx; urls=['https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/73601748','https://www.mozzartbet.ba/sr/uzivo/mec/1/73601748']; [print(u, httpx.get(u,timeout=30,follow_redirects=True).status_code) for u in urls]"
```

Full output (exit code 0):

```text
https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/73601748 200
https://www.mozzartbet.ba/sr/uzivo/mec/1/73601748 200
```

The live board's rendered links exposed the `/sr/uzivo/mec/1/{event_id}` form, while the prematch route follows the existing generic Mozzartbet board path with `/match/{event_id}`. The declaration is therefore evidence-based rather than treating the scraper's generic URL fallback as proof that no route exists. `deep_link_verified` remains `False`; the later on-demand checker must still prove that the page resolves to the intended event.

The added templates are:

```text
prematch: https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/{event_id}
live:     https://www.mozzartbet.ba/sr/uzivo/mec/1/{event_id}
```

### TDD trace for the fix round

The expanded `tests/test_deeplinks.py` was written before changing production code.

#### RED

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py -v
```

Full output (exit code 1):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 15 items

tests\test_deeplinks.py ...FFFF..FFFFFF                                  [100%]

================================== FAILURES ===================================
_________________ test_declared_true_book_is_distinguishable __________________
E       AttributeError: module 'scrapers.common' has no attribute 'has_declaration'
______________________ test_declared_false_book_is_still_declared ______________
E       AttributeError: module 'scrapers.common' has no attribute 'has_declaration'
___________________________ test_unknown_book_is_not_declared _________________
E       AttributeError: module 'scrapers.common' has no attribute 'has_declaration'
_____________________ test_deeplink_config_covers_every_configured_bookmaker ____
E       Extra items in the left set: 'mozzartbet'
________________________ test_live_template_is_used_for_supported_book ________
E       assert 'https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=12345' == 'https://www.mdshop.ba/sport-live?event=12345'
________ test_mozzartbet_live_template_uses_public_event_route ______________
E       assert 'https://www.mozzartbet.ba/' == 'https://www.mozzartbet.ba/sr/uzivo/mec/1/73601748'
________________ test_empty_event_id_uses_non_event_url _______________________
E       assert '...event={event_id}' == 'https://www.mdshop.ba/'
_________________ test_none_event_id_uses_non_event_url ______________________
E       assert '...event={event_id}' == 'https://www.mdshop.ba/'
_____________________ test_event_id_is_url_encoded ____________________________
E       assert '...event=12&x=3' == '...event=12%26x%3D3'
________________ test_true_template_without_placeholder_is_rejected ___________
E       Failed: DID NOT RAISE <class 'ValueError'>

============================== 10 failed, 5 passed in 1.02s ==============================
```

The failures directly corresponded to the four review findings: missing declaration API/`mozzartbet`, ignored `live`, raw empty IDs, unencoded IDs, and missing-placeholder validation.

#### GREEN — focused deep-link tests

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 15 items

tests\test_deeplinks.py ...............                                  [100%]

============================= 15 passed in 0.99s ==============================
```

#### GREEN — focused URL regressions

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py tests/test_urls.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 24 items

tests\test_deeplinks.py ...............                                  [ 62%]
tests\test_urls.py .........                                             [100%]

============================= 24 passed in 0.76s ==============================
```

### Final post-commit verification

All commands below were run after commit `5c4bd346c68030766dfa07e832ee81eaffaec609`.

#### Full test suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -o addopts="" -q
```

Full output (exit code 0):

```text
........................................................................ [ 39%]
........................................................................ [ 78%]
........................................                                 [100%]
184 passed in 4.11s
```

**Explicit passed-test count: 184 passed, 0 failed.**

#### Ruff

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

#### Mypy

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
Success: no issues found in 44 source files
```

#### Import-cycle smoke check

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -c "import engine; import scrapers.common; print('imports ok')"
```

Full output (exit code 0):

```text
imports ok
```

#### Commit and repository state

Commit command:

```text
git commit -m "fix(mapping): harden deeplink declarations and URL builder"
```

Full output:

```text
[master 5c4bd34] fix(mapping): harden deeplink declarations and URL builder
 3 files changed, 156 insertions(+), 16 deletions(-)
```

Full commit SHA:

```text
5c4bd346c68030766dfa07e832ee81eaffaec609
```

Post-commit repository state:

```text
## master
5c4bd346c68030766dfa07e832ee81eaffaec609
```

### Covering test files

- `tests/test_deeplinks.py` — 15 tests covering all nine configured books, declared/undeclared distinction, notes/placeholders, Mozzartbet live route, live template selection, empty/`None` IDs, URL encoding, and invalid-template rejection.
- `tests/test_urls.py` — 9 existing URL regressions, including `nsoft_event_url` behavior and Mozzartbet's existing generic scraper URL.
- The full repository suite — 184 tests, all passing.

### Deviations and deferred items

- Added optional `template_live` fields to the three enabled books. This extends the original config shape so the existing `live` argument is meaningful instead of silently ignored; the original `template` values remain unchanged.
- Added `has_declaration` rather than changing the certainty gate, per the review scope. A later task can use the predicate to choose `no_event_link` versus `link_unverified`.
- Chose `ValueError` for a declared-true template missing `{event_id}`. This fails closed and prevents a malformed declaration from being treated as a valid per-event link.
- The minor findings explicitly deferred by the reviewer remain unchanged: `DEEP_LINK_CONFIG` is still unused/duplicated, the configuration remains a raw dict, and missing/invalid config files are not logged.
- The public-route checks establish a defensible Mozzartbet declaration; they do not replace the later on-demand event-identity verification, so production `deep_link_verified` values remain false.

**Fix-round final status:** DONE_WITH_CONCERNS
