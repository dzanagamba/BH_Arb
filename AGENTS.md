# BH_Arb — agent instructions

## Read first

1. `ROADMAP.md` — the single task list, acceptance criteria and execution log.
2. `docs/SESSION_BRIEF.md` — current state and next action.
3. The `research/` brief a task cites (`research/00_README.md` is the index).
4. `docs/HANDOFF.md` only when historical context is needed.

The predecessor roadmaps and the old maintenance backlog were folded into
`ROADMAP.md` on 2026-11-07. `P*` and `N*` IDs are historical labels; their
glossary is in the `ROADMAP.md` History section. N2-4 stays deferred and P1-6 is
waived; do not start or un-waive either without an explicit operator instruction.

## Task loop

1. Resume an `In progress` task. Otherwise pick the first `Not started` task
   whose dependencies are `Done`.
2. Skip tasks with `Gate: operator` until a written decision is recorded under
   the task.
3. Change its status to `In progress` **before** coding.
4. Implement only that task, following its Objective or Why, Steps and
   Acceptance.
5. Add or update the tests named in the task.
6. Verify:
   ```bash
   python -m pytest
   python -m ruff check .
   python -m mypy .
   python scripts/generate_market_mapping_doc.py --check
   python scripts/refresh_fixtures.py --check
   python scripts/audit_admissibility.py --check
   ```
   plus any task-specific measurement or replay command. While coding, run only
   the test files the change touches; the full suite runs **once**, at task
   completion, in the clean runtime state. Do not run `pytest --cov` or
   `scripts/check_test_isolation.py` in the routine loop: CI's 3.11 leg runs the
   suite in both ledger modes and enforces the coverage floor. The one local
   exception is a change to the ledger, `config/generated/` or the isolation
   guard, which also runs
   `BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest`.
7. Check the acceptance boxes, set the task `Done`, update the execution log
   with the commands and the measured output pasted in, and update
   `docs/SESSION_BRIEF.md`.
8. Review the diff. Commit and push with a conventional message only when the
   operator explicitly asks; otherwise leave the working tree for review.
9. If blocked, record the blocker in the task and stop. Do not start a second
   task.

Use `.venv/bin/python` if `python` is not on `PATH`.

CI runs `python scripts/refresh_fixtures.py --check` and
`python scripts/audit_admissibility.py --check`. It does not call
`python scripts/check_test_isolation.py`: the 3.11 `tests` leg already runs the
suite in both ledger modes (`BH_ARB_TEST_RUNTIME_LEDGER` empty and `populated`)
and owns the coverage floor. The script remains the one-command local equivalent
for the tasks that need it (see the step above). See `docs/CI.md`.

## Test cadence

The suite is 2,237 tests in ~90 s (2026-11-08), so running it is cheap but not
free. Run targeted files while iterating; run the whole suite once when the
task's code is finished. Do not repeat the full suite after every edit, and do
not add the coverage or isolation runs to the routine loop — CI already runs
them on every push.

## Maintenance work and ad-hoc requests

- Work the operator asks for that has no roadmap row gets a row added first
  (status `In progress`) and an execution-log entry.
- Never un-gate a `Gate: operator` row without a written operator approval.
- Keep changes in small, file-disjoint bundles; update `docs/SESSION_BRIEF.md`
  and `ROADMAP.md`; do not commit unless asked.
- A deferred finding stays in `ROADMAP.md`; do not silently start it in a later
  session without operator approval.

## Measurement discipline

- The suite must pass in both clean and populated-ledger modes before a push;
  CI verifies both. Locally the task run is the clean mode, plus the populated
  mode when the task touches the ledger or `config/generated/`.
- Run the command that proves a claim and paste the measured output into the
  execution log; never report a number you did not measure.
- `MARKET_MAPPING.md` is generated. Regenerate it with
  `python scripts/generate_market_mapping_doc.py`; never hand-edit it.

## Shared building blocks

- `engine/name_keys.raw_team_key()` is the only raw team-name key. The certainty
  gate, evidence ledger and review diagnostics delegate to it; do not copy a
  second NFKD/punctuation fold.
- `engine.market_consensus` owns complete-market, devig and outlier math.
  Operator scripts import it; do not reintroduce local market tables.
- `engine.market_registry.registered_spec()` is the shared per-book resolver.
  It keeps the `has_source_id` seam used by test fakes.
- `engine.deeplinks` owns the deep-link declaration store the certainty gate
  reads (`config/bookmaker_deeplinks.json`, its cache and provenance, the
  `supports_event_id: false` predicate and `build_event_url`).
  `engine.ah_labels` owns the Asian-handicap label helpers; `scrapers.common`
  re-exports them for the adapters. The dependency runs one way,
  `scrapers` → `engine`: never import `scrapers` from `engine`.
- `scrapers/protocol.BookAdapter` is the one adapter contract: no-arg
  construction and an async `scrape(live=, scan_time=, sports_wanted=)`, even
  when an adapter ignores a keyword. Read the class through
  `SCRAPERS.adapter(book)` so mypy checks it; `SCRAPERS.get()` is `Any`.
- Browser books call their JSON APIs through `scrapers.base.measured_api_get/post`
  (an in-page `fetch`, SR4-8a). Never use `page.request`: it bypasses
  `context.route` and HAR, which SR4-8's replay depends on.
- `scrapers/har_fixtures.py` owns the committed HAR rules and
  `scripts/capture_har.py` regenerates them; never hand-edit a `.har.gz`. A
  replay must run with `route_from_har(not_found="abort")` so it cannot reach
  the network. See `docs/HAR_REPLAY.md`.
- `server/csv_export.csv_cell()` neutralises formula-leading cells in every CSV
  export. Use it rather than a local copy.
- Keep `engine/__init__.py` and `scrapers/__init__.py` lazy. Import submodules
  directly (`from engine.matcher import MatchMatcher`) instead of re-exporting
  eagerly.

The auth gap that used to be pinned by a strict `xfail` in
`tests/test_auth_keys.py` is fixed (M1-1): `api_key_guard` in `server/app.py`
resolves the env key or a named key for every `/api` route except
`/api/health`, so a new route cannot rely on a per-route dependency alone. Do
not weaken that back to per-route-only auth; with no bootstrap key and no stored
key record the API is open by documented design (local-only, loopback bind).

## Trust invariants — never weaken

1. Only `verified` groups reach pricing.
2. `verified` means zero outstanding reasons, including the link half.
3. Only a browser check can set `deep_link_verified`; no human or AI action can.
4. A missing declaration fails safe.
5. A false merge is worse than a split; no fuzzy score alone confirms identity.
6. `sport` is a hard identity gate; no cross-sport pricing.
7. Settlement is part of market identity; regulation vs overtime never pair.
8. One leg per bookmaker and one leg per price source.
9. The scanner never logs in, places a bet, moves money, or evades account limits.
10. Never lower the certainty gate to increase the number of surebets.

## Scraper rules

- A scraper failure must fail closed: a book that cannot be read is missing from
  the scan, never filled with stale or guessed prices.
- Reliability changes must never increase traffic. Retries, limiters and
  breakers only ever reduce or space out traffic.
- No stealth, fingerprint masking, TLS impersonation (`curl_cffi`), captcha
  solving or proxy rotation, except the scoped browser exception below. Do not
  spread the pattern.
- **Browser fingerprint masking is a scoped exception** (SR0-1, operator decision
  2026-11-08). `launch_browser()` keeps
  `--disable-blink-features=AutomationControlled` and the init script that hides
  `navigator.webdriver` and supplies `navigator.plugins`, `navigator.languages`
  and `window.chrome`, because the browser books need it to pass
  Cloudflare/Turnstile. It stays limited to those markers inside
  `launch_browser()`: no TLS impersonation, proxy rotation, captcha solving,
  extra stealth or account-limit evasion. A book that is still challenged is
  reported `blocked` and drops out; revisit SR0-1 if the browser books drop out.

## Session handoff

Keep `docs/SESSION_BRIEF.md` short and current: goal, task status, project
state, next action, last commit, blockers. Update it at the end of every task,
not only when the session ends. The next session starts from that file and the
roadmap, so it must be enough to resume without reading the whole history.

## Do not

- Do not delete `config/generated/mapping_evidence.json` or other operator
  runtime state to make a test pass; redirect tests instead.
- Do not change trust rules, accepted evidence semantics, or price-source
  identity as part of an unrelated task.
- Do not start from `cache/` contents; they are runtime state, not fixtures.
