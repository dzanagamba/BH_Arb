# Dependency upgrade plan (M4-4)

Planning only: this document records the four remaining upgrades, what a dry run
in a throwaway virtual environment measured, and the acceptance criteria for each
separate change. No pin in `requirements.txt` / `requirements-dev.txt` moved for
this task.

## Current pins and targets

Measured 2026-11-09 from `requirements.lock` / `requirements-dev.lock` and PyPI:

| Package | Installed | Target | Notes |
|---|---|---|---|
| `fastapi` | 0.140.13 | 0.162.2 | runtime |
| `starlette` | 1.10.0 | 1.10.0 | already the latest release; FastAPI 0.162 requires `>=0.46` |
| `mypy` | 1.15.0 | 2.4.1 | dev |
| `ruff` | 0.9.10 | 0.17.4 | dev |
| `httpx` | 0.28.1 | 0.28.1 | runtime client for the adapters and respx; stays |
| `httpx2` | not installed | 2.16.0 | dev-only `TestClient` transport |

`pydantic` (2.13.4 → 2.14.3) and `uvicorn` (0.52.0 → 0.54.0) also have newer
releases, but M4-4 does not cover them: they ride their own Dependabot groups
and get separate rows if a pin needs to move deliberately.

## Measured dry run

A temporary venv (`/tmp/opencode/m44-venv`, never the working `.venv`) installed
`requirements-dev.lock`, then overrode exactly the targets above and added
`httpx2`:

```bash
python -m venv /tmp/opencode/m44-venv
/tmp/opencode/m44-venv/bin/pip install -q -r requirements-dev.lock
/tmp/opencode/m44-venv/bin/pip install -q fastapi==0.162.2 starlette==1.10.0 \
    mypy==2.4.1 ruff==0.17.4 httpx2==2.16.0
```

Results:

* **Full suite: green.** `2,389 tests collected`, exit 0, 17 snapshots passed,
  wall 1 m 50 s. No test or fixture needed a change for FastAPI 0.162.2 or the
  `httpx2`-backed `TestClient`.
* **mypy 2.4.1: one error**,
  `scripts/refresh_fixtures.py:212: error: Incompatible types in assignment
  (expression has type "int", target has type "bool | dict[str, Any] |
  dict[str, str]")`. The report dict is inferred from `build_report()` and then
  gains integer fields (`written`, `len`). One annotation fixes it; no behaviour
  change.
* **Ruff 0.17.4: three `UP042` findings**, all the same pattern —
  `MarketType`, `Sport` (`models/schemas.py`) and `ScrapeKind`
  (`scrapers/errors.py`) inherit `str, Enum` where `StrEnum` is now preferred.
  No other rule fired under the project's `E,F,W,I,UP,B` selection.
* **`httpx2` removes a live deprecation warning.** Today importing
  `fastapi.testclient` raises
  `StarletteDeprecationWarning: Using 'httpx' with 'starlette.testclient' is
  deprecated; install 'httpx2' instead`; in the upgraded venv,
  `starlette.testclient` resolves `httpx2` and the warning is gone.

## U1 — FastAPI 0.140.13 → 0.162.2 (Starlette stays 1.10.0)

Why: 22 minor releases of fixes and security patches. Starlette is already at
1.10.0 in both the old and new resolution, so this is a FastAPI-only move and
the measured suite passes untouched.

Steps:

1. Change the `fastapi==` pin in `requirements.txt`.
2. `python scripts/lock_requirements.py`; commit both locks.
3. Full verification (`pytest`, ruff, mypy, market doc, fixtures, admissibility).

Acceptance:

- the lock carries `fastapi==0.162.2` and still `starlette==1.10.0`;
- the suite is green with no application or test edit;
- `app.openapi()["paths"]` still matches the route assertions in the tests;
- no new deprecation warning is emitted at import time.

Rollback: restore the pin and regenerate the locks; no data or schema migration.

## U2 — mypy 1.15.0 → 2.4.1

Why: MyPy 2.x is the maintained line; the measured surface is one annotation.

Steps:

1. Change `mypy==` in `requirements-dev.txt` and regenerate the dev lock.
2. Annotate the `refresh_fixtures.py` report dict (`dict[str, Any]`) rather than
   adding a `cast` or a blanket ignore.
3. Run `python -m mypy .` and the full suite.

Acceptance:

- `mypy .` reports zero errors on all 290 source files under the same
  `pyproject.toml` settings;
- no new `# type: ignore` and no loosened mypy setting;
- `python scripts/refresh_fixtures.py --check` still passes (the touched file).

Rollback: restore the pin.

## U3 — Ruff 0.9.10 → 0.17.4

Why: nine minor releases of rules and fixes. Under the existing selection the
only findings are the three `UP042` `str, Enum` classes.

Options measured:

1. **Migrate to `StrEnum` (recommended).** Python 3.11 is the target and
   `StrEnum` is the modern form. This is an *unsafe* autofix because
   `str(member)` changes: `str(ScrapeKind.OK)` becomes `"ok"` instead of
   `"ScrapeKind.OK"`. Current code reads `.value` at every comparison and
   serialisation boundary found in `server/`, `engine/` and `scrapers/`; the
   direct-format risk is limited to diagnostics and tests.
2. Add `UP042` to `[tool.ruff.lint] ignore` with the reason that the legacy
   `str()` form is relied on. No such reliance was found, so this is the
   fallback, not the plan.

Steps (option 1):

1. Change the `ruff==` pin and regenerate the dev lock.
2. Replace the three `class X(str, Enum)` declarations with `class X(StrEnum)`
   and drop the now-unused `Enum` import.
3. Audit the few places that format an enum directly rather than `.value`
   (`scripts/live_canary.py`'s market-type reasons and any test expectation),
   and update them only where the new `"over_under_2_5"`-style text is intended.
4. Add a focused assertion that JSON payloads and metric labels still carry the
   value strings (`"1x2"`, `"ok"`, …) — Pydantic and `json.dumps` keep using the
   value for both forms, so this proves the change is text-only.
5. Run ruff, mypy and the full suite.

Acceptance:

- `ruff check .` is clean with the same rule selection (no new ignore);
- the three classes are `StrEnum` and their `.value` strings are unchanged;
- API JSON, metrics labels, cache keys and alert text are unchanged; the canary
  report's market-type strings are reviewed and asserted;
- the suite is green.

Rollback: restore the pin and the three class declarations.

## U4 — `httpx2`-backed `TestClient` (dev only)

Why: Starlette 1.10 already prefers `httpx2`; with only `httpx` installed it
warns on every import of `fastapi.testclient`. `httpx` 0.28.1 stays the runtime
client for the scrapers and `respx`; `httpx2` is a separate distribution and
must not enter `requirements.lock`.

Steps:

1. Add `httpx2==2.16.0` to `requirements-dev.txt` and regenerate the dev lock.
2. Confirm a clean `pip install -r requirements-dev.lock` resolves it and that
   `starlette.testclient` imports `httpx2` (measured: yes).
3. Optionally add a small check that `starlette.testclient.httpx.__name__ ==
   "httpx2"` so a future dev-lock edit cannot silently drop it; keep it offline
   and cheap.
4. Run the full suite.

Acceptance:

- `requirements-dev.lock` has `httpx2==2.16.0` and no runtime lock change;
- importing `fastapi.testclient` with `-W error::DeprecationWarning` is silent;
- the suite is green; `respx` adapter tests still drive the real `httpx` client.

Rollback: remove the dev pin and regenerate the dev lock.

## Order and verification

Do one upgrade per commit, in this order: **U4** (dev-only, removes an existing
warning), **U1** (runtime framework), **U2** (type checker), **U3** (linter with
the only behaviour-shaped edit). Each commit:

```bash
python scripts/lock_requirements.py
python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/refresh_fixtures.py --check
python scripts/audit_admissibility.py --check
```

U1 and U4 touch the runtime/test environment, so their commits also run the
suite once in both ledger modes as CI does. None of the four needs a data,
cache, config or trust-rule change; the certainty gate, link proofs, settlement
and price sources are not involved.
