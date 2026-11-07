# BH_Arb maintenance backlog

**Not roadmap tasks.** `PROJECT_ROADMAP_V2.md` is complete; N2-4 is deferred by
the operator. Nothing here may be started without explicit operator approval,
and any fix must keep the trust invariants in `AGENTS.md`.

This file records the findings deliberately deferred by the 2026-11-06 cleanup.
Details of the audit and the changes that did land are in
`docs/SESSION_BRIEF.md`.

## Security and authentication

- [ ] Redesign named-key authentication as one coherent change: a middleware
      resolves the env `API_KEY` or a named key for every `/api` route except
      `/api/health`, routes carry explicit read/write scopes, and the dashboard
      sends the key on every fetch and download. Then remove the strict xfail in
      `tests/test_auth_keys.py`.
- [ ] Decide whether `accepted_odds: 0` with a non-zero accepted stake should be
      rejected (422) instead of treated as "not placed". The current settle path
      treats either zero as not placed, so bankroll stays correct.
- [ ] Add an authentication-failure rate limit and avoid one PBKDF2 verification
      per request; invalidate any verification cache immediately on revocation.

## Performance and availability

- [ ] Move the scan's CPU/I/O stages off the event loop (`asyncio.to_thread`):
      learning, `group_matches`, stale/skin/feed-integrity, candidate CPU work and
      JSON/SQLite writes. A real scan blocked `/api/status` for about 100 s.
- [ ] Stop rewriting the ~55 MB scan cache on every `/api/verify-links` call;
      persist failed-check results without a full cache write.
- [ ] Serve a cached `/api/health` summary instead of recomputing freshness and
      the candidate queue on every poll.
- [ ] Decide whether to cap the candidate review queue (14k+ rows) and how to
      report the denominator. Do not trim silently.
- [ ] Evaluate the compact cache/ledger representations against every consumer;
      never delete runtime evidence to meet a budget.

## Architecture

- [ ] Decompose `server/api.py` in stages: pure candidate scoring, a `FeedState`
      object for `_state_for`, then the JSON-store layer. Leave scan and
      deep-link semantics untouched.
- [ ] Move the deep-link declaration store out of `scrapers/common.py` into
      `engine/`, and remove the `engine` ↔ `scrapers` package cycle.
- [ ] Share one link-settled predicate between `CertaintyGate` and cache restore,
      with a parity test over every link case.
- [ ] Unify the repeated datetime and SQLite connection helpers; decide one
      `synchronous` policy for the shared database file.
- [ ] Route the remaining direct `MARKET_REGISTRY` lookups through
      `registered_spec()` (or an accessor) and make the registry test seam patch
      the object, not only the module global.
- [ ] Move `scripts/pairing_audit.audit` and the reusable deep-link verifier into
      `server/` so coverage measures them.

## Supply chain and CI

- [ ] Add a resolved constraints/lock file and install Docker/CI/SBOM from it.
- [ ] Add a Docker Chromium launch check and an OS/image CVE scan.
- [ ] Pin GitHub Actions to commit SHAs and the base image to a digest; keep
      Dependabot able to update both.
- [ ] Plan the separate upgrades for FastAPI/Starlette, MyPy 2.x, Ruff 0.17 and
      Playwright 1.64; evaluate the `httpx2` TestClient migration.

## Product and configuration decisions

- [ ] Remove or deprecate `Surebet.match_urls`, `Surebet.bet_urls`,
      `Match.bet_url` and `MATCH_URL_TEMPLATES` after a documented compatibility
      window. `SurebetStake.destination` is the supported path.
- [ ] Decide the `link_sweeps` SQLite table: wire `append_link_sweep()` into
      `POST /api/link-sweeps`, or remove the table/method/retention entry and
      correct `docs/STORAGE.md`.
- [ ] Decide the unreachable candidate approve/reject functions: restore them
      behind `HUMAN_MAPPING_ENABLED` with a review, or delete them and the stale
      documentation.
- [ ] Decide `engine/raw_market_resolver.resolve_offers`: wire it into
      `scripts/discover_markets.py` or retire it.
- [ ] Finish the PWA: add 192/512 icons; decide whether the browser-notification
      button sends a notification or is removed.
- [ ] Add the "scan completed with zero matches" diagnostic and a run-mode-aware
      no-surebet state; extend the truth table and companions deliberately.
- [ ] Fix the feed-mode tab ARIA contract (`aria-controls`/roving tabindex or a
      `group` with `aria-pressed`) and reconsider the whole-slip live region.

## Tests and process

- [ ] Enable branch coverage with a measured floor and add it to CI.
- [ ] Pin `today=` in the parser-contract unit test so the suite does not turn red
      on 2027-02-17; keep the CLI `--check` as the time-aware gate.
- [ ] Narrow the runtime-state guard's SQLite `-shm`/`-wal` false positive without
      removing the guard.
- [ ] Add a browser-enabled CI job or scheduled run for the existing Chromium
      accessibility tests.
