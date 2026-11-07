# Scraper fixtures, test strategy, and known pain points

Read-only investigation, 2026-11-07. Repo state: `2e06756` on branch `claude`,
clean working tree.

## Files inspected

- `tests/conftest.py` (1-279), `tests/test_market_fixtures.py` (1-652),
  `tests/test_parser_contracts.py` (1-182), `tests/test_registry_parser_consistency.py` (1-120),
  `tests/test_market_registry_wiring.py` (1-40), `tests/test_live_mode.py` (291-324),
  `tests/test_fetch_pages.py` (1-42), `tests/test_scraper_common.py` (1-109),
  `tests/test_betole.py` (1-56), `tests/test_maxbet.py` (1-60),
  `tests/test_e2e_certified.py` (700-900), `tests/test_scan_cost.py` (1-92),
  `tests/test_feed_integrity.py` (1-45), `tests/test_probe_feeds.py` (1-43),
  `tests/test_live_feed.py` (1-125), `tests/test_accessibility_axe.py` (196-234).
- `scripts/refresh_fixtures.py` (1-143), `scripts/check_test_isolation.py` (1-62),
  `scripts/audit_admissibility.py` (1-108), `scripts/capture_market_fixtures.py`
  (1-130, 184, 339-342, 937-940, 1252-1290), `scripts/probe_feeds.py` (1-90),
  `scripts/verify_deeplinks.py` (560-593).
- `engine/parser_contracts.py` (29-357), `.github/workflows/ci.yml` (10-98),
  `pyproject.toml` (1-34), `config/settings.py` (10-86),
  `scrapers/base.py` (1-177), `scrapers/cost.py` (1-140), `scrapers/__init__.py` (1-50).
- Docs: `docs/PARSER_CONTRACTS.md`, `docs/CI.md` (1-70), `docs/SCAN_COST.md`,
  `docs/FEED_STATUS.md`, `docs/BOOK_ADAPTER.md`, `docs/HANDOFF.md` (225-300),
  `docs/PRODUCTION_READINESS.md`, `docs/MULTISPORT_EVIDENCE.md` (62-74, 306-316),
  `docs/ADMISSIBILITY_AUDIT.md` (105-120), `ScraperLogic.md`,
  the V2 roadmap (now historical: findings G6–G15, N2-4 and N2-6), `AGENTS.md`,
  `docs/SESSION_BRIEF.md`.
- Git: `git log --oneline -n 300`, `git log --oneline -- scrapers/` (40 commits),
  `git show -s` for the fix commits cited below.

## Findings — A) Fixture and test strategy

1. **Capture is manual and live, not recorded in CI.** `scripts/capture_market_fixtures.py`
   fetches each book's live endpoint, trims the payload to the smallest payload that
   still exercises the registry rows, and writes `tests/fixtures/markets/<book>_<mode>.json`
   (`capture_market_fixtures.py:1-28`, `_finish` at 80-95). Most books use `httpx`;
   WWIN and Mozzartbet launch the real Chromium via `scrapers.base.launch_browser`
   (339-342, 937-940). A book that is unreachable or has no qualifying payload is
   `SKIPPED` and gets **no** fixture (21, 104). `expected_markets` comes from the
   registry rows the payload carries, never from parser output (`_finish`, 80-95).
2. **Format is trimmed JSON, not raw captures.** There is no HAR, HTML, VCR cassette,
   or respx fixture anywhere. Every market fixture records
   `bookmaker, mode, captured_at, endpoint, source, provenance, payload_kind, bets,
   expected_markets` plus per-book `dropped_*` field lists
   (e.g. `tests/fixtures/markets/mozzartbet_prematch.json:1-20`). `source` must be
   `live_api_response` and `captured_at` a valid ISO date
   (`test_market_fixtures.py:364-380`). `tests/fixtures/e2e_certified/` is a second,
   frozen (2026-09-25) copy used by the end-to-end chain; `tests/fixtures/replay/`
   holds bounded scan/corpus JSON for the replay harness.
3. **Tests stub at the parser boundary, not with HTTP mocks.** `test_market_fixtures.py`
   feeds each fixture to the real parsing entry point via `_run_parser`
   (202-278) and asserts the emitted set, source ids and label rules (290-360).
   `test_market_registry_wiring.py` feeds synthetic payloads to the same entry points
   to prove registry→dispatch wiring (1-40). `test_live_mode.py` monkeypatches
   `scrapers.mdshop.fetch_with_retry` and runs the real `scrape()` (307-324) — the only
   `scrape()` call in the suite. `test_e2e_certified.py` injects fake scraper classes
   into `api.SCRAPERS` and switches other books off (787-865). There is **no respx,
   VCR, or fake httpx client** for scraper network paths.
4. **Playwright is not exercised for scrapers in the suite.** The two Chromium tests
   are dashboard accessibility only and skip unless `BH_ARB_TEST_BROWSER=1`
   (`test_accessibility_axe.py:196-234`). Deep-link tests use a `FakePlaywright`
   (`test_verify_links.py:1096-1102`). The only real scraper browser use in the repo
   is the manual capture script and the on-demand `verify_deeplinks.py:560-562`.
   `test_layering.py:30-75` separately proves importing engine/scrapers loads no
   `playwright` module.
5. **Contract/golden tests are the main drift net.** `engine/parser_contracts.py`
   computes per-fixture required keys, source-id set, label set, bounded nested-shape
   signature and three SHA-256 fingerprints (`compute_contract`, 163-194).
   `tests/fixtures/markets/contracts.json` stores the reviewed expectation plus
   `max_age_days: 120`. `test_parser_contracts.py` proves the shipped contracts match
   (48-54), every enabled book has a dated contract (57-67), a changed id/label/shape
   fails with an exact diff (81-125), and a refresh never edits the registry (150-165).
   A separate golden test keeps generated `MARKET_MAPPING.md` in sync
   (`test_registry_parser_consistency.py:1-40`; CI at `ci.yml:33-34`).
6. **`--check` modes:**
   - `refresh_fixtures.py --check` fails on added/removed/changed contract, a stale
     fixture, or an enabled book with no contract (`refresh_fixtures.py:52-79`,
     `ci.yml:70-72`). `--capture` distinguishes `capture_failed` from feed drift
     (`refresh_fixtures.py:82-96`; `test_parser_contracts.py:168-182`).
   - `audit_admissibility.py --check` fails when an admitted sport/market/family or
     price source disappears or a fixed rule changes (`audit_admissibility.py:1-16,
     93-96`; `ci.yml:38-39`).
   - `generate_market_mapping_doc.py --check` keeps the generated registry table in
     sync (`ci.yml:33-34`).
   - `check_test_isolation.py` runs the suite in both ledger modes
     (`check_test_isolation.py:29-57`), but CI does **not** invoke it; the workflow
     only sets `BH_ARB_TEST_RUNTIME_LEDGER=populated` (`ci.yml:80-86`).
7. **Freshness is 120 days and currently green.** All 17 contracts were captured
   2026-10-20…2026-11-05, so none is stale on 2026-11-07. `contract_health` exposes
   counts, gaps, `stale`, `oldest_capture` and `checked_at` on `/api/health`
   (`parser_contracts.py:330-357`; `test_parser_contracts.py:139-147`).
8. **Isolation rules** (N0-1): autouse fixture redirects the generated ledger,
   `CACHE_DIR`, every JSON cache file, `STORAGE_PATH` and lazily-created SQLite
   stores into a per-test temp tree (`conftest.py:191-263`); a session guard
   fingerprints `config/generated/` and `cache/` and fails the run if any file
   changes (`conftest.py:167-189`). `real_runtime_state` tests are skipped unless
   `BH_ARB_TEST_RUNTIME_STATE=1` (`conftest.py:203-210`). Shipped config inputs are
   deliberately not redirected (`conftest.py:16-19`).
9. **Coverage gaps in the fixture set** are declared, not silent: `UNCOVERED_ROWS`
   (11 rows) and `BOOKS_WITHOUT_FIXTURES` (`test_market_fixtures.py:83-136`);
   `test_coverage_gaps_are_declared_rather_than_ignored` (430-463) fails if a
   declared gap gains a capture, and `test_a_declared_gap_is_not_just_listed_but_forgotten`
   (466-524) re-proves gaps against the payload where one exists. Gaps today:
   EVLBet has no fixture at all; Betole is prematch-only; Premier live O/U 1.5/2.5/3.5,
   Mozzartbet 1.5/3.5 and Betole DC/1.5/3.5 are declared uncovered.

## Findings — B) Known pain points

### Breakage from site changes

- **Premier Kladionica host 503:** `svc-test.premier-kladionica.com` began answering
  503; host moved to `svc-web` (`84ebf0d`, 2026-10-27, `git show -s`).
- **SportPlus live O/U misread:** a team total named `Zbroj golova domaćin/gost X.5`
  was read as the match total, producing a 0.17 outlier while the real line was
  suspended (`d1423d7`, 2026-10-27; documented in `ScraperLogic.md:98-120`).
- **NSoft suspended prices read as real:** `isPlayable:false` / `isInOffer:false` at
  event, bet or outcome level was ignored; 8 of 42 live match totals were suspended
  prices (`51f9b6a`, 2026-10-27; `scrapers/base.py` unchanged but `nsoft_offered()`
  now filters).
- **NSoft live market identity:** `betTypeId 28` is home-team goals, not match total;
  `6`/`995` are rest-of-match markets. All five 2026-10-19 live surebets came from
  these misreads (`3c3fda0`, `bbd21bc`; `ScraperLogic.md:19-54`).
- **Premier live BTTS spelling:** live feed says `LIVE - OBA TIMA DAJU GOL`, prematch
  says `OBA DAJU GOL`; parser only knew the prematch spelling (`711a23d`, 2026-10-19;
  regression tests `test_market_fixtures.py:582-605`).
- **Mozzartbet pagination:** page index is 0-based and `matchCount` cannot be trusted;
  naive pagination returned 88 instead of 831 matches (`01b8804`, `102c209`;
  `ScraperLogic.md:124-169`).
- **WWIN two-bet-per-call quirk:** the prematch endpoint serves at most two bet ids
  per call, so the scraper fetches three groups and merges (`ScraperLogic.md:269`).
- **SportPlus double-serialized response:** the JSON body can be a JSON string inside
  JSON (`ScraperLogic.md:96-120`).
- **MDShop / Admiralbet `?event=` routes are inert:** both re-declared
  `supports_event_id:false` on 2026-10-20 (`051fe9a`; `conftest.py:27-33`), which is
  why those books' links verify as "declared no route" rather than proving a URL.
- **EVLBet flat offer feed returns an empty list** for every endpoint variant tried;
  disabled since 2026-10-20 and no fixture exists (`config/settings.py:53-60`;
  `test_market_fixtures.py:83-92`; `docs/FEED_STATUS.md:1-15`).
- **Ice hockey remains blocked:** only SportPlus and MBet publish three regular-time
  families; MaxBet's total includes overtime (`docs/ADMISSIBILITY_AUDIT.md:111-120`;
  `docs/MULTISPORT_EVIDENCE.md:306-316`).

### Rate limiting / blocking

- **Cloudflare/Turnstile forces Playwright** for Mozzartbet (custom `medium: WEB`
  header, pure httpx → 403 "Pogresan medium"), Admiralbet (Turnstile + per-session
  `officeid`) and WWIN (browser session; unauthenticated probes return an empty body)
  (`ScraperLogic.md:124-128, 173-177, 255-257`; `docs/MULTISPORT_EVIDENCE.md:70-72`).
- **No 429/403 retry policy:** `fetch_with_retry` retries only 5xx and network/timeout
  failures; a 403/429 is returned immediately and the caller logs/aborts
  (`scrapers/base.py:148-177`). The outcome is classified as `blocked` only
  textually (`scrapers/cost.py:24-34, 103-115`), and the scheduled scan backs off a
  repeatedly failing book (`server/api.py:1740-1764`) — manual scans ignore it.
- **No proxy rotation or login by design:** no proxy/login code in `scrapers/`
  (`grep`); AGENTS invariant 9 forbids evasion and account actions (`AGENTS.md:79`).

### Playwright flakiness

- `settle()` swallows every exception from `wait_for_load_state("networkidle")`
  (`scrapers/base.py:106-115`), so a browser that never settles silently proceeds.
- Browser navigation has a 60 s timeout but no retry (`admiralbet.py:116-123`,
  `mozzartbet.py:387`, `wwin.py:260`); concurrency was tuned to three browser slots
  and adaptive waits (`cd5a1a2`).
- No CI Chromium job exists; the roadmap explicitly defers a browser-enabled CI/scheduled run
  and a Docker Chromium launch check (`ROADMAP.md` M4-2 and SR4-8). The two local Chromium
  tests skip by default (`SESSION_BRIEF.md:15-17`).

### Parsing / mapping errors

- The registry and wiring suites read the same file, so a wrong-but-consistent id stays
  green; only captured payloads catch it (`test_market_fixtures.py:9-13`;
  `test_market_registry_wiring.py:1-40`). Historical examples: SportPlus prematch BTTS
  `6→5`, Mozzartbet prematch BTTS `130→131`, MBet prematch O/U `ofb:tg→ofb:ht`.
- NSoft `136` "Ide dalje" (advance) was once read as Double Chance, polluting DC arbs
  (`docs/HANDOFF.md:51-55`; `ScraperLogic.md:17-54`).
- `parse_dt` truncation mishandled valid `.%f` formats; fixed then made explicit and
  logged (`80a0075`, `be334ef`, `facaff9`).
- Only the NSoft parser currently publishes `source_id`; other scrapers use the
  hand-written registry (`docs/PRODUCTION_READINESS.md:18`), weakening attribution for
  discovered mappings.
- Three books' league names needed country qualification, and Betradar ids were added
  in one mapping fix (`3c3fda0`).

### Observability gaps

- Per-book scan cost (`success|empty|parse_error|blocked|skipped`), failure-rate metric,
  feed-integrity quarantine and coverage-budget alerts exist
  (`docs/SCAN_COST.md:16-24, 49`; `docs/COVERAGE_BUDGET.md`).
- **The first live scan-cost baseline is still pending** — the evidence file explicitly
  records no measurement (`docs/evidence/2026-11-05-scan-cost-baseline.md:1-8`;
  `SESSION_BRIEF.md:62-64`).
- `blocked` vs `parse_error` is a text-marker heuristic, not an HTTP-status signal
  (`scrapers/cost.py:103-115`).
- Roadmap findings G6/G12 (historical labels; glossary in `ROADMAP.md`) recorded
  that coverage/mapping gaps and parser maintenance were reactive; N1-2 and N2-6
  now cover most of it.
- N2-4 (seven-day opportunity baseline/drift gates) is **deferred by the operator**,
  not blocked (`ROADMAP.md`, Deferred and waived section).
- P1-6 (24-hour soak) is **waived and excluded** (`AGENTS.md:12`;
  `SESSION_BRIEF.md:13`).

### Test / fixture gaps

- No fixture for EVLBet; no live Betole contract (registry declares no live rows);
  Premier live O/U and Mozzartbet 1.5/3.5 have no payload (`test_market_fixtures.py:83-136`;
  `docs/PARSER_CONTRACTS.md:47-58`).
- No test runs the real network path of WWIN, Mozzartbet, Admiralbet, SportPlus, MBet or
  Premier; only MDShop `scrape()` is exercised with a fake fetch (`test_live_mode.py:307-324`).
- No test proves `fetch_with_retry` backoff, 5xx retry, or `fetch_pages` failure against a
  fake HTTP client; pagination is tested only with a synthetic `fetch_page`
  (`test_fetch_pages.py:1-42`).
- The parser-contract unit test reads `date.today()`, so the suite turns red when a
  fixture crosses 120 days (2027-02-17 for the 2026-10-20 captures); SR1-1 in
  `ROADMAP.md` owns the fix (`test_parser_contracts.py:48-54`).
- The runtime-state guard has a known SQLite `-shm`/`-wal` false positive
  (SR1-2 in `ROADMAP.md`).
- `docs/CI.md:43` documents `check_test_isolation.py` as a local command; the
  workflow does not run it (`ci.yml` has no such step). Trust the workflow: CI runs
  the suite twice via env, not the script. SR1-2 in `ROADMAP.md` owns the fix.
- Branch coverage is not gated (`ROADMAP.md` M6-1).

## Trust invariants a scraper change must respect

Verbatim from `AGENTS.md:69-80`:

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

## Risks / uncertainties

- I did not run the suite or `pytest --collect-only`; line claims come from reading the
  files, not from execution.
- Git history in this repo starts at the 2026 import (`8064340`); earlier
  `claudesurebet` history is not available, so older scraper incidents may be missing.
- `docs/HANDOFF.md:259-265` says EVLBet is "enabled" and has no fixture, contradicting
  `config/settings.py:60` (`enabled: False`) and `docs/FEED_STATUS.md`/`ACCEPTANCE.md`.
  I trust the code and the dated probe: EVLBet is disabled.
- Contract freshness is wall-clock dependent; "not stale today" will change on
  2027-02-17 without a re-capture.
- I did not audit the frontend/dashboard paths that consume scraper output.

## Conclusions

1. The fixture strategy is strong at the parser layer: real trimmed payloads, dated
   contracts, fingerprints, declared gaps, and a strict "no fixture rather than a fake"
   rule.
2. It is weak at the transport layer: no respx/HAR/VCR, no real scrape() test for six of
   nine books, and no test of retry/backoff/429 behaviour.
3. Playwright is the least-tested surface; browser scraping is manual-only, CI has no
   Chromium job, and `settle()` hides navigation failures.
4. The historical pain pattern is site-shape and market-identity drift (NSoft suspended
   flags, Premier host/BTTS, SportPlus team totals, Mozzart pagination), not parser
   arithmetic.
5. Blocking is handled by per-book backoff rather than a 429-aware retry policy; 403/429
   are never retried by `fetch_with_retry`.
6. Observability exists (cost, failure rate, coverage budget, integrity quarantine) but
   the first live cost baseline is unmeasured and outcome classification is heuristic.
7. EVLBet remains the one enabled-book exception in spirit but is disabled in code; any
   re-enable requires a captured fixture first.
8. Two operational facts must not be lost: N2-4 stays deferred and P1-6 stays waived
   until the operator says otherwise.
