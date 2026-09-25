# Task 4 Report — Per-book market registry and parser wiring

**Status:** DONE_WITH_CONCERNS  
**Commit:** `f34a14d7493a6f23813a3b0e6929e7d48ab3faa9`  
**Branch:** `master` (worked in place; no worktree or branch created)  
**Date:** 2026-09-25

## What changed

### Registry and diagnostics

- Created `config/bookmaker_markets.json` as the per-bookmaker/per-mode source ID registry.
- Created `engine/market_registry.py` with:
  - `MarketSpec` and the requested `MarketRegistry` API;
  - the module-level `MARKET_REGISTRY` instance;
  - process-wide `unmapped_markets` and `record_unmapped()`;
  - line-aware resolution for IDs shared by multiple O/U lines;
  - default label sets for JSON entries that intentionally omit O/U labels;
  - `min_legs` defaulting to 3 when omitted;
  - explicit empty-mode tracking, so an empty live mode is registry-first rather than falling back to legacy mappings.
- Added `unmapped_markets` to `GET /api/health` in `server/api.py`.

### NSoft wiring

- `scrapers/common.py` now lazily loads the registry (avoiding the existing `engine`/`scrapers.common` import cycle).
- `parse_nsoft_bets()` now resolves registered IDs first, uses the registered line/labels/`min_legs`, records unknown IDs, and falls back to the legacy maps only for an unregistered book/mode.
- The historical 136 “Ide dalje” advance market remains rejected by the complete-label rule.
- O/U IDs 137/138 and live IDs 22/28 are disambiguated by the `sbv` line rather than selecting the last registry declaration.
- `parse_nsoft_live_bets()` passes the bookmaker and live mode through the registry.
- MDShop and Admiralbet now pass their own bookmaker/mode; Admiralbet’s redundant `extra_bet_types={1639: ...}` argument was removed.

### Other bookmaker parsers

The following parsers now gate their core market mappings through the registry and apply the registered minimum-leg/label rules:

- `scrapers/mbet.py` (`ofb:*` prematch and `lfb:*` live prefixes);
- `scrapers/wwin.py` (registered IDs and dynamic request ID selection);
- `scrapers/sportplus.py` (prematch IDs and live semantic IDs);
- `scrapers/premier_kladionica.py` (registered semantic market names);
- `scrapers/evlbet.py` (registered `12005` 1X2 ID);
- `scrapers/mozzartbet.py` (registered game IDs in both modes);
- `scrapers/betole.py` (registered pick-code groups).

Unknown source IDs encountered by these parsers are recorded rather than silently discarded. Existing experimental-market parsing is retained only where the current captured fixtures require it and is not silently treated as a core registry mapping.

### Tests

Created `tests/test_market_registry.py` covering registry loading, mode separation, bookmaker-specific IDs, intentionally empty modes, health exposure, `min_legs` behavior, unsupported O/U lines, unknown-ID recording, and registry authority over parser hard-coded IDs.

## Registry population by book/mode

| Bookmaker | Prematch | Live |
|---|---|---|
| `mdshop` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 |
| `admiralbet` | 1X2 (`1639`), DC, BTTS, O/U 1.5/2.5/3.5 | 1X2, DC, BTTS |
| `wwin` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | 1X2 |
| `premier_kladionica` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | 1X2, BTTS |
| `mbet` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 |
| `sportplus` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 |
| `evlbet` | 1X2 (`12005`) | **Intentionally empty**: the live API exposes no odds |
| `betole` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | **Intentionally empty**: disabled bookmaker/no supported live odds path |
| `mozzartbet` | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 | 1X2, DC, BTTS, O/U 1.5/2.5/3.5 |

The registry therefore has explicit `prematch` and `live` mode objects for all nine configured bookmakers, while preserving the two intentionally empty live modes.

## TDD trace

### RED: required failing test

The required test was written before the registry module existed.

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py -v
```

Output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 0 items / 1 error

==================================== ERRORS ====================================
_____________________________ test_market_registry.py ______________________________
ImportError while importing test module 'C:\Users\harun\OneDrive\Documenti\surebetmuse12\tests\test_market_registry.py':
Hint: make sure that test modules/packages have valid Python module names.
Traceback:
tests\test_market_registry.py:5: in <module>
    from engine.market_registry import MarketRegistry, unmapped_markets
E   ModuleNotFoundError: No module named 'engine.market_registry'
========================== short test summary info ============================
ERROR tests/test_market_registry.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.95s ===============================
```

The failure was for the intended reason: the requested production module was absent.

### GREEN: focused final suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py tests/test_market_mapping.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 33 items

tests/test_market_registry.py ...........                                [ 33%]
tests/test_market_mapping.py ......................                      [100%]

============================= 33 passed in 1.15s =============================
```

## Final verification

All commands below were run after the final implementation changes and before the commit.

### Full test suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output (exit code 0):

```text
........................................................................ [ 45%]
........................................................................ [ 90%]
................                                                         [100%]
```

The repository’s `pyproject.toml` already supplies `-q`, so the second quiet flag suppresses the usual summary line.

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
Success: no issues found in 43 source files
```

The notes are pre-existing untyped-function notes; there are no type errors.

### Staged diff check

Command:

```text
git diff --cached --check
```

Full output (exit code 0):

```text
```

### Commit

Command:

```text
git commit -m "feat(mapping): add per-book market registry as single source of truth, record unmapped IDs"
```

Full output:

```text
[master f34a14d] feat(mapping): add per-book market registry as single source of truth, record unmapped IDs
 14 files changed, 1154 insertions(+), 177 deletions(-)
 create mode 100644 config/bookmaker_markets.json
 create mode 100644 engine/market_registry.py
 create mode 100644 tests/test_market_registry.py
```

Full commit SHA:

```text
f34a14d7493a6f23813a3b0e6929e7d48ab3faa9
```

Post-commit repository state:

```text
## master
```

## Deviations from the brief and why

1. **The supplied completeness test contradicted the supplied JSON.** It required an enabled book to have live 1X2, but the brief explicitly defines `evlbet.live` as `{}` and the current EVLBet scraper documents that its live endpoint exposes no odds. The test was corrected to require both mode objects for all nine books, require at least one populated 1X2 mode for enabled books, and explicitly assert that `evlbet/live` and `betole/live` are intentionally empty.
2. **The supplied JSON omitted `mozzartbet`, although the repository has nine configured bookmakers and the task requires all nine.** A registry block for the already-supported Mozzartbet game IDs was added so every configured book has both mode objects and its enabled parser can be registry-driven.
3. **The supplied JSON omitted live O/U entries for MBet and SportPlus even though current captured/reconstructed payload tests exercise those markets.** Those IDs/lines were added (`lfb:tg` and live `ZBROJ_GOLOVA`) rather than silently preserving a second hard-coded parser path. This is the main intentional extension to the verbatim JSON block.
4. **The implementation adds line-aware lookup and default O/U labels.** The literal one-spec-per-ID implementation in the brief is ambiguous for the shared NSoft 137/138 and 22/28 IDs; without line-aware selection, only one O/U line could be emitted. The registry fills canonical labels when the brief’s O/U JSON entries omit `labels`.
5. **`server/api.py` was modified although it was not in the brief’s file list.** This was required by the binding global constraint that `unmapped_markets` be surfaced on `/api/health`.
6. **The registry import in `scrapers/common.py` is lazy rather than a module-level import.** A module-level `engine.market_registry` import creates a real circular import through the existing eager `engine/__init__.py`; the lazy accessor preserves the requested behavior without changing the engine package initializer.

## Concerns

- The brief’s “exact JSON” and “all 9 books × both modes” requirements are internally inconsistent. The committed registry resolves that in favor of completeness and current parser evidence; the deviations above should be reviewed by the plan owner.
- Experimental legacy markets (for example first-half/handicap paths) are not all represented in the core JSON block because the supplied registry intentionally contains the six primary market families. They remain supported where existing captured fixtures require them, while unknown/unregistered source IDs are visible in diagnostics.
- `unmapped_markets` is process-local in-memory state, as requested. It resets when the API/worker process restarts; it is not persisted in the scan cache.
- The additional line-aware `lookup(..., line=...)` and `lookup_type(...)` methods extend the brief’s three-argument lookup interface without breaking callers of the original signature.

## Fix round 1 — code-review findings

**Status:** DONE_WITH_CONCERNS  
**Commit:** `97f6def6d5cc4877977b460c3abf25ab8fcb3beb`  
**Date:** 2026-09-25

### Findings addressed

1. **WWIN live data loss — chose registry restoration.** I restored the live `double_chance` (6), `btts` (3), and O/U (11) entries alongside live 1X2 (95), and kept the live request registry-driven. The parser docstring, the pre-existing `MARKET_IDS` request, and the live parser implementation all use the same IDs; reverting to the old constant would preserve a second source of truth and leave the registry incomplete. `tests/test_market_registry.py::test_wwin_live_request_includes_every_supported_live_market_id` and `::test_wwin_live_parser_keeps_dc_btts_and_ou` cover the request set and emitted markets.

2. **Premier live DC loss — fixed.** Added `premier_kladionica/live/double_chance` with source ID `UTAKMICA_DC`, removed the no-op ternary, and added a live fixture asserting DC is emitted and the exclusion counter is not incremented.

3. **Noisy exclusion diagnostics — fixed with an explicit namespace.** Added top-level `_excluded` data and `MarketRegistry.is_excluded()`; `record_unmapped()` now ignores declared IDs/name patterns while retaining genuinely unknown IDs. The health endpoint remains backed by the same global counter.

   I verified the seed against the actual parser mappings and `ScraperLogic.md`/`MARKET_MAPPING.md` before excluding IDs. In particular, I **did not** declare these currently supported experimental paths excluded: MBet `ofb:ht`/`ofb:hc`, WWIN `2`, SportPlus `4`/`25`, and Betole `4`/`5`/`6`; doing so would have silenced real output that existing tests exercise. The excluded seeds are the NSoft prematch/live unsupported IDs, Mozzart `141` and advance/qualification names, WWIN `7/10/4/476/443/51`, Premier’s verified `1435/1440` and documented unsupported template names, MBet `ofb:fts/ofb:sh/ofb:htdc/ofb:shdc/ofb:dnb/ofb:fi/lfb:tg1sth`, Betole `335/336`, and SportPlus `5/178/308-311/1285` plus advance/qualification names.

4. **Betole cross-book attribution — fixed.** `_parse_markets()` now takes a `bookmaker` parameter, and Betole passes `bookmaker="betole"` to both the shared odds parser and the NSoft fallback. Betole’s registry also includes the legacy NSoft-style aliases exercised by its captured browser fixture (`135/152/151/137/138` and the corresponding game IDs), so the fallback remains functional while diagnostics are filed under Betole.

5. **Two registry instances — fixed.** `_nsoft_registry()` now returns the module-level `MARKET_REGISTRY`; it no longer constructs or caches a second `MarketRegistry`. A regression test monkeypatches `engine.market_registry.MARKET_REGISTRY` and verifies the shared object is returned.

6. **Vacuous label checks — fixed.** All constant-set comparisons such as `len({"GG", "NG"}) >= spec.min_legs` and `len({"Over", "Under"}) >= spec.min_legs` now operate on the actual collected `OddsValue` labels and also require `actual.issubset(spec.labels)`. A regression test supplies incomplete registered label sets and verifies no market is emitted.

### TDD red evidence for the six fixes

The following focused tests were written before their corresponding production changes. Each red run failed for the intended missing behavior:

- WWIN live tests: `pytest ...::test_wwin_live_request_includes_every_supported_live_market_id ...::test_wwin_live_parser_keeps_dc_btts_and_ou -v` → **2 failed** (`{95}` versus `{3, 6, 11, 95}`; live parser returned `set()`).
- Premier live DC: `pytest ...::test_premier_live_double_chance_resolves_and_is_not_unmapped -v` → **1 failed** (no DC market).
- Shared registry: `pytest ...::test_nsoft_accessor_uses_shared_module_registry ...::test_nsoft_parser_uses_registry_min_legs -v` → **2 failed** (a second `MarketRegistry` was returned; the custom registry was ignored).
- Real label validation: `pytest ...::test_label_checks_reject_incomplete_registered_label_sets -v` → **1 failed** (two markets were emitted with incomplete label sets).
- Betole attribution: `pytest ...::test_betole_shared_parser_files_unknown_ids_under_betole -v` → **1 failed** with `TypeError: _parse_markets() got an unexpected keyword argument 'bookmaker'`.
- Exclusion namespace: `pytest ...::test_declared_exclusions_are_not_counted_as_unmapped ...::test_supported_experimental_ids_are_not_declared_excluded -v` → **2 failed** (`mdshop:136` was counted; `is_excluded` did not exist).

After implementation, the focused suite covering the fixes and existing regressions was run with an explicit pass count.

### Covering test files

- `tests/test_market_registry.py` — 20 tests covering all six review findings, including the shared registry, WWIN live request/parser, Premier live DC, exclusions, Betole attribution, and real label validation.
- `tests/test_market_mapping.py` — NSoft 136 safety and cross-book market regressions.
- `tests/test_live_mode.py` — NSoft/MBet/SportPlus live parser regressions.
- `tests/test_betole.py` — legacy Betole reference-resolution and extraction regressions.

### Exact final commands and output

Focused covering suite:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py tests/test_market_mapping.py tests/test_live_mode.py tests/test_betole.py -o addopts="" -q
```

Full output (exit code 0):

```text
..........................................................               [100%]
58 passed in 1.37s
```

Full repository suite:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -o addopts="" -q
```

Full output (exit code 0):

```text
........................................................................ [ 42%]
........................................................................ [ 85%]
.........................                                                [100%]
169 passed in 4.18s
```

Ruff:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Mypy:

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
Success: no issues found in 43 source files
```

Staged diff check:

```text
git diff --cached --check
```

Full output (exit code 0):

```text
```

Commit:

```text
git commit -m "fix(mapping): close live registry and exclusion gaps"
```

Full output:

```text
[master 97f6def] fix(mapping): close live registry and exclusion gaps
 10 files changed, 448 insertions(+), 114 deletions(-)
```

Full SHA:

```text
97f6def6d5cc4877977b460c3abf25ab8fcb3beb
```

Post-commit repository state:

```text
## master
```

### Fix-round deviations and remaining concerns

- The accepted WWIN choice is a registry expansion, not a network reversion; this is intentional because the live feed and parser already use the same IDs and keeping the request registry-driven preserves the single-source-of-truth design.
- The exclusion namespace is book-scoped and currently ignores `mode` in `is_excluded()`; mode-specific exclusions can be added later without changing parser call sites.
- Some IDs documented as “excluded” in the older canonical mapping are deliberately **not** in `_excluded` because the current parser and captured tests still emit them as experimental markets (the explicit list is above). This follows the review instruction not to hide a supported market.
- Betole’s legacy NSoft aliases are additional registry entries, not a change to Betole’s direct pick-code mapping; they preserve the existing captured browser fixture while fixing attribution.
- `unmapped_markets` remains process-local and now contains only genuinely unknown IDs plus IDs not covered by the explicit exclusion namespace; it is not persisted across process restarts.

