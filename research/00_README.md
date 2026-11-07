# Scraper architecture map and research — index

Written 2026-11-07 by research agents; read-only investigation. Line numbers drift:
re-check before relying on one. The backlog built from these briefs is
`ROADMAP.md` at the repo root.

| File | Contents |
|------|----------|
| `01_shared_infra.md` | `scrapers/base.py`, scan orchestration in `server/api.py`, httpx and Playwright stacks, retry, throttling, anti-breakage guards, observability, dependencies |
| `02_adapters.md` | One section per bookmaker adapter (10): transport, endpoints, pagination, retry, parsing, deep links, fixtures, fragility notes; summary table |
| `03_fixtures_and_pain_points.md` | Fixture capture and refresh, test stubbing, contract checks, CI, isolation; pain points grouped with commit hashes; trust invariants |
| `04_http_reliability_research.md` | httpx ecosystem, retry, rate limiting, circuit breakers, observability, frameworks; adopt/borrow/avoid verdicts |
| `05_browser_automation_research.md` | Playwright features and lifecycle, Crawlee, Crawl4AI, scrapy-playwright, alternatives; adopt/borrow/avoid verdicts |
| `06_parser_contract_testing_research.md` | Wire schemas, snapshot tests, record/replay, property tests, contract testing, drift detection |
| `07_roadmap_migration_inventory.md` | What the 2026-11-07 roadmap migration had to carry across; describes the repository before that migration |

## Summary

- 10 adapters: 7 plain httpx (mdshop, betole, evlbet, maxbet, mbet, sportplus,
  premier_kladionica), 3 Playwright hybrids reading network JSON (mozzartbet,
  admiralbet, wwin). No DOM parsing, no websockets.
- One process, `asyncio.gather` per scan, `Semaphore(3)` for browsers, no
  scan-level timeout; a fresh httpx client and a fresh Chromium per scrape.
- One shared retry helper (3 attempts, 5xx/network, no jitter, no 429/403
  handling), not used by three books; per-book scheduled backoff after 3 failures.
- Anti-breakage is strong at the parsed-result level (pydantic, dated fixture
  contracts, quarantine, coverage deltas, stale/outlier guards) and weak at the
  raw-payload and transport level (no wire schemas, no transport tests, no
  browser replay).
- The browser launcher masks automation markers (`scrapers/base.py:32`,
  `:50-55`), which conflicts with the no-evasion rule; flagged for an operator
  decision (SR0-1).
