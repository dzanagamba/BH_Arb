# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 is Done**. First eligible task is **N0-2**
(source-updated timestamps and frozen-price quarantine).
**Last task commit:** `b1820d0` — N0-1 hermetic tests.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite now
runs **1,481 passed, 2 skipped** in both ledger modes: with no generated ledger
and with a deliberately populated one. A throwaway copy with no
`config/generated/` and no `cache/` also passes in both modes. Ruff, MyPy and the
generated market doc are clean.

`tests/conftest.py` redirects the generated ledger, `cache/` and the SQLite store
into a per-test temporary tree, and a session guard fails the run if anything
writes into the checkout's runtime directories. The operator's real ledger is
never deleted or rewritten. CI runs the suite a second time on Python 3.11 with
`BH_ARB_TEST_RUNTIME_LEDGER=populated`; the local equivalent is
`python scripts/check_test_isolation.py`.

The two skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan corpus
(`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the opt-in
path itself.

## Next action

Start **N0-2**: mark it `In progress`, then add optional `source_updated_at`
without inventing timestamps, the bounded per-book observation store, and the
frozen-price rule that refuses a stale leg without touching the certainty gate.
N0-3 is independent and still eligible if N0-2 is deferred.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
