# Roadmap — Issue Breakdown

Copy to GitHub Issues after `git push`. Each item links to `PLAN.md` phase.

## P0 — Correctness (must close before P1)

- [ ] **#1 Mozzartbet pagination fix** `scrapers/mozzartbet.py:359-401` — `pageSize=15`, `totalPages` fallback. Fixture: `tests/fixtures/mozzartbet_pagination.json`.
- [ ] **#2 Centralize `parse_dt`** `scrapers/common.py:23` — replace `sportplus.py:291`, `mbet.py:376`, add `Z` test.
- [ ] **#3 Uniform scan window** `server/api.py:217` — single `scan_started_at` passed to all scrapers.
- [ ] **#4 `fetched_at` on Match** `models/schemas.py:31` — stamp + store in `cache/last_scan.json`.
- [ ] **#5 Unified suspend guard** `scrapers/common.py` — `is_active_odds` helper.
- [ ] **#6 Cache TTL + staleness badge** `server/api.py:322-367`, `frontend/js/app.js`.
- [ ] **#7 Scan lock per mode** `server/api.py:63` — separate prematch/live.

## P1 — Yield

- [ ] **#8 EVLBet market audit** `scrapers/evlbet.py:107` — capture 1500 events, decide BTTS/O_U.
- [ ] **#9 WWIN/Premier concurrency** `scrapers/wwin.py:136`, `scrapers/premier_kladionica.py:213`.
- [ ] **#10 League mappings auto-grow** `scripts/generate_mappings.py` (new).
- [ ] **#11 Matcher recall tuning** `engine/matcher.py:190` — A/B on snapshot.
- [ ] **#12 AH unification** `scrapers/mbet.py:130`, `scrapers/sportplus.py:398`, `scrapers/common.py:68`.
- [ ] **#13 Profit dust tab** `engine/arbitrage.py:193`, `frontend/js/app.js:155`.
- [ ] **#14 Health dashboard** `server/api.py:419`.

## P2 — Reliability

- [ ] **#15 Browser pool** `scrapers/base.py:35`.
- [ ] **#16 Unified retry 403** `scrapers/base.py:74`.
- [ ] **#17 Odds TTL expiry** `engine/arbitrage.py:86`.

## P3 — Growth

- [ ] **#18 Bet-slip deep links** `models/schemas.py:45`, `scrapers/common.py:105`.
- [ ] **#19 Telegram webhook** — server `POST /notify`.
- [ ] **#20 Eval new books (MaxBet/Meridian)** — `MARKET_MAPPING.md`.
