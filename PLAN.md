# Surebet Scanner — Detailed Execution Plan (Muse 12)

> **Goal:** Fix “rare + wrong” surebets and grow arbitrage yield 5–10× while keeping false positives near zero.
> **Baseline:** `claudesurebet` == `dzanagamba/surebet-scanner` @ `7d2d5d8` (9 bookmakers, ~6057 prematch matches → ~802 groups → 0–2 surebets per scan, Mozzartbet degraded to 56 matches, EVLBet only 1X2).
> **New repo:** `surebetmuse12` — https://github.com/dzanagamba/surebet-muse12 (`plan/muse12-roadmap` @ `aa33254` → `2935d90`).
> **Status (2026-08-20):** P0 correctness + P1 yield + P2 reliability shipped. 107 tests green, ruff clean, groups 802→856 (+6.7%), WWIN 15s→~7s, Mozzart 56→800+ (projected), dust/health/TTL live.
> **Status (2026-09-26):** Phase 4 (mapping certainty) shipped — 13 tasks. `verified` requires a proven claim, and link evidence is proven two ways: a browser check opened that book's per-event URL, **or** the book declared in `config/bookmaker_deeplinks.json` that it has no per-event route. 6 of the 9 books declare `supports_event_id: false` and are verified on identity alone; the 3 that declare a route (MDShop, Admiralbet, Mozzartbet) must still have theirs proven, and MDShop's and Admiralbet's `?event=<id>` routes are **inert**, so a group holding either still cannot verify. **Zero surebets is today's expected output, and it is correct:** the shipped gate produces 0 surebets on the stored scan — a measured claim with two conditions, read in §3 *Phase 4* along with the correction that supersedes the 2026-09-25 status line.
> **Status (2026-10-20):** MDShop's and Admiralbet's `?event=<id>` routes were re-checked in a browser and are still **inert**, so both now declare `supports_event_id: false` in `config/bookmaker_deeplinks.json`. 8 of the 9 books are verified on identity alone; only Mozzartbet declares a route and must still have it proven. The blockers to a surebet are now identity gaps (league names, team spellings), not links. The zero surebets figure in §3 *Phase 4* is a dated measurement with conditions; §4 *TODO* tracks what replaces it.

## 0. Principles

1.  **Correctness over yield.** Never show an arb that can’t be bet. Every P1 yield change needs a P0 correctness guard (suspend check, label-set validation, staleness, cross-book distinct rule `engine/arbitrage.py:185`).
2.  **Evidence before synthesis.** Live payload captures under `tests/fixtures/` + `cache/last_scan.json` are ground truth. No “already verified” shortcuts.
3.  **One `fetched_at` to rule them.** All 9 scrapers stamped with the same scan wall-clock; mixing ages >90s is a bug, not a feature.
4.  **Matcher gates are load-bearing.** League `engine/matcher.py:208-215` + category `engine/matcher.py:204` + 120min `KICKOFF_WINDOW_MINUTES` `config/settings.py:122` are hard gates — relax only with metrics.

---

## 1. Where this came from

Forked from `dzanagamba/surebet-scanner` @ `7d2d5d8` (9 bookmakers, ~6,057
prematch matches → ~802 groups → 0–2 surebets per scan).

## 2. Original diagnosis

The baseline's problem was "surebets are rare *and* wrong": Mozzartbet pagination returned ~56 of ~1,150
matches, EVLBet parsed only 1X2, scan windows differed per book, odds carried no
age, suspended odds leaked through, `Z` timestamps parsed as `kickoff=None`, and a
restart replayed hours-old arbs. Phases 0–2 fixed those; Phase 4 replaced fuzzy
matching with a proven claim. The detailed task tables live in git history
(`git log -- PLAN.md`).

---

## 3. Phases

### Phase 0 — Correctness (Done)

- [x] P0-1 `fetched_at` stamped once per scan on every `Match`
- [x] P0-2 shared suspend guard — no inactive or <1.01 odds reach the engine
- [x] P0-3 one `parse_dt` everywhere (`Z` / offsets → naive UTC)
- [x] P0-4 Mozzartbet pagination fix
- [x] P0-5 one scan window passed to every prematch book
- [x] P0-6 cache TTL (30 min) — a restart no longer replays stale arbs
- [x] P0-7 scan lock held for the whole scan, separate prematch / live locks

### Phase 1 — Yield (Done, except where noted)

- [x] P1-2 league-mapping generator (`scripts/generate_mappings.py`)
- [x] P1-5 WWIN / Premier throughput
- [x] P1-6 dust tier (`DUST_PROFIT_PERCENT`, 0.2–0.5%) shown separately
- [x] P1-7 per-book health on `GET /api/health`
- [ ] P1-1 EVLBet markets beyond 1X2 — blocked on a captured payload (see §4)
- [ ] P1-4 Asian handicap across books — parsed, still in `EXPERIMENTAL_MARKETS` (off by default) until proven on live payloads
- [~] P1-3 fuzzy-threshold recall tuning — superseded by Phase 4: grouping is now decided by the certainty gate, not a score

### Phase 2 — Reliability (Done)

- [x] P2-1 one shared stealth launcher (`scrapers/base.py:launch_browser`)
- [x] P2-2 `fetch_with_retry` for the httpx scrapers
- [x] P2-3 odds TTL in the engine (`ODDS_TTL_SECONDS`, live stricter)
- [x] P2-4 `/api/verify` re-scrapes only the books in the surebet
- [x] P2-5 structured logs + `/api/debug/report`

### Phase 4 — Mapping certainty (Done)

Shipped in 13 tasks (see git history and `docs/HANDOFF.md`).
The premise: the old matcher decided "same match" with a fuzzy score and a
threshold, so a wrong pairing and a right one looked alike. Phase 4 replaces the
score with a claim that has to be proven.

**Task list (all shipped).** Data model (`MatchEventStatus`, `MatchEvidence`,
`MatchGroup`, `CandidateReview`) · the `CertaintyGate` and its reason vocabulary ·
league equivalence restricted to declared pairs · the shared market registry
(`config/bookmaker_markets.json`) · declared deep links
(`config/bookmaker_deeplinks.json` + `build_event_url`) · the AI candidate layer
(`engine/ai.py`) · the review queue and its API · candidate suppression and
human approval · captured-payload fixture tests for every registry entry · the
deep-link verification endpoint and Playwright checker · the end-to-end guard
(`tests/test_e2e_certified.py`) · docs (`README.md` § *Match & mapping certainty*).

**The invariant everything else serves:** a `verified` group requires ZERO
reasons, links included. Allowlisted fuzzy aliases are the only auto-accepted
fuzzy path. The AI never auto-approves a pair — a human approval grants team
identity only, never `deep_link_verified`, which is a machine fact.

**HEADLINE RESULT, and it is not a good-looking one.** `verified` groups were
unreachable in production. MDShop's and Admiralbet's declared `?event=<id>`
routes are **inert**: the served page is byte-identical to the plain football
prematch page, the id appears in none of ~250 captured response bodies or in
rendered text, and `?event=` provokes no event-scoped request. Only Mozzartbet
verifies (15/15, via `$.match.id`; a dead id answers 200 with 14 bytes instead of
328 KB). Consequence, measured on a real 1,592-match three-book feed: **0 of 197
candidate groups verified, so zero surebets were produced.** The gate, the
registry and the parsers are correct and tested.

**Correction (2026-09-26): that measurement was the gate being stricter than the
design specified, not only a bookmaker-side routing fact.** The gate never read
`supports_event_id`, so the six books that declare no per-event route were refused
for the links they never claimed to have — the declaration was documented in
§4 of the design spec and wired to nothing. The gate now consults
`config/bookmaker_deeplinks.json`: a declared-false book is verified on identity
alone with a `no_event_link` evidence note, a declared-true book still needs its
route proven, and a book with no declaration fails safe. So "flipping the route to
`supports_event_id: false`" is no longer the no-op this section used to call it —
it is exactly what such a book now relies on. The bookmaker-side routing fact
above stands on its own: a group holding MDShop or Admiralbet still cannot be
`verified` while their routes are inert.

**Measured on the stored scan (2026-09-26).** `cache/last_scan.json`: 6,999
matches, 7 books, `scan_time 2026-08-20T18:26:52Z` — 36 days old — and **0 of
6,999 matches carry a proven link**. The matcher and the arbitrage engine are
pure functions of that file, so the whole measurement is offline:

| scenario | verified groups | surebets |
|---|---|---|
| **A — links exactly as cached (the state this repo is in)** | **16** | **0** |
| B — plus Mozzartbet's link *faked* proven | 179 | 0 |
| C — every book's link *faked* proven (the ceiling) | 516 | 0 |

Before the fix, the same gate with the declaration lookup answering "nothing is
declared", A and B are 0/0 and C is **516/0** — bit-identical, which is the
monotonicity datum: the change only ever adds pairs, it removes none.

**Conditions, and read them before quoting any of the three.**
* **A is the only scenario the repo is actually in.** B and C require setting
  `deep_link_verified=True` on matches no browser check has proven. **No browser
  check has been run in this repo** — nothing in `cache/` carries a
  `deep_link_verified` flag, and `scripts/verify_deeplinks.py` is on-demand,
  never part of a scan. Until `/api/verify-links?bookmaker=mozzartbet` is run and
  its result stored, B and C are arithmetic, not observations.
* **A surebet count from this cache needs two rewrites.** Every match's
  `fetched_at` has to be reset to now and kickoffs shifted into the future, or
  the engine refuses every leg for reasons unrelated to the link gate. Both are
  applied and neither touches link state. A surebet that appears only after those
  two rewrites is not evidence that the arbitrage is still on.
* **The group counts above predate the order fix.** `MatchMatcher.group_matches`
  used to let the first match to arrive anchor its group, so this feed gave 16, 34
  or 106 for scenario A depending only on the order the books were fed in. It now
  processes listings in a total order and falls through to the next-best group
  when the gate refuses one, so a count no longer depends on input order — but
  the figures here were taken before that change and have not been re-measured
  (see `docs/HANDOFF.md` §4 for after-fix numbers on a newer cache).
* Zero surebets on a 36-day-old cache is a statement about that cache, not about
  any book's prices today.

**Superseded figure.** The whole-branch report of 2026-09-26
(`whole-branch-fix-link-declaration.md`, §6) quotes "202 groups / 1 surebet" for
scenario B. It does not reproduce: the shipped gate gives 179/0. Its surebet is
`premier_kladionica` Over 2.5 at 2.15 against `sportplus` Under 2.5 at 1.9 —
both prices are really in the capture, and 1/2.15 + 1/1.9 is 0.86% — but those
two matches are 120 minutes apart and `VERIFIED_KICKOFF_WINDOW_MINUTES` is 15, so
the gate refuses the pair with `kickoff_delta` at *any* link state. The matcher
admits it as a candidate (`KICKOFF_WINDOW_MINUTES` is 120) and the gate then
rejects it; that is the pairing working, not a link problem. The report's 26 and
532 group figures do not reproduce either, for the order reason above.

**Recorded at the time, both since fixed** (regression tests replaced the
tripwires — see `README.md` § *Fixed defects*):
* `premier_kladionica/live/btts` — the parser now matches per mode
  (`NAME_BTTS` / `NAME_BTTS_LIVE`).
* NSoft live window (`mdshop`, `admiralbet`) — both now use
  `scrapers.common.nsoft_event_window`, which looks back 12 hours for live.

**Fixed since the above list was written:**
* `build_targets` takes `settled` and `offset`, so a per-book link sweep advances
  instead of re-checking its first N events. The endpoint fills `settled` itself
  from `cache/deep_link_decisions.json`, which records every COMPLETED check — a
  navigation that errored is not a verdict, so that event is offered again. This
  — not the rate limit — was what blocked convergence. A sweep still costs
  `events / limit` calls at 2 calls/min: 608 mozzartbet events at the cap of 20
  is 31 calls, about 15 minutes.

**Verification.** `pytest` 572 passed + 1 xfailed (2026-09-26), `ruff` clean,
`mypy` clean.
`tests/test_e2e_certified.py` drives mbet/wwin/sportplus through their real
parsers on the real 2026-09-25 captures and asserts the chain end to end,
including that a spoiled claim in any one book removes the surebet. Its constants
are tied to the captured prices, so re-running `scripts/capture_market_fixtures.py`
requires re-deriving `EXPECTED_LEGS` / `EXPECTED_MARGIN` / `UNSWAPPED_COMBINATIONS`.


---

## 4. TODO

**The goal:** an operator opens the dashboard, sees a surebet that is real right
now, places every leg at the shown odds within a minute or two, and comes out
ahead after limits and slippage. Every item below is ordered by how much it
moves that goal, and each has a "done when" that can be checked. Do the
milestones in order: there is no point polishing placement while the scanner
shows zero surebets.

### M1 — Show a real surebet (done 2026-10-20 — the pipeline is no longer the blocker)

Funnel on a fresh prematch scan, before → after: 217 → **818** verified groups
(up to 7 books each, every enabled book now groups). Still **0 surebets**: the
best cross-book combination on that scan was −1.14%, i.e. the remaining gap is
the market, not the code. Surebets in this market are rare and short-lived, so
yield now depends on scanning often (M4) and on more books/markets (M5).

- [x] **MDShop and Admiralbet routes.** Re-checked in a browser: `?event=` is inert and match detail is login-walled. Both declared `supports_event_id: false` with a dated note; scrapers now emit the declared page instead of the dead URL.
- [x] **Mozzartbet links.** 422 of 426 proven (≈10 min). The CLI used to throw its verdicts away — it now merges them into `cache/deep_link_verifications.json` like the API does.
- [x] **Funnel measured; the biggest losses fixed.** (a) SportPlus sends Sarajevo local time, stored as UTC → every SportPlus pair failed the 15-min kickoff check; fixed with `parse_local_dt` (+ `tzdata`). (b) Unmapped league names blocked exact fixtures; the gate now settles those on exact teams + kickoff. (c) Team names compare ignoring punctuation/accents ("Bodo/Glimt" = "Bodø Glimt").
- [x] **EVLBet** disabled until a payload can be captured (feed returns no football events).
- [ ] Work the review queue: ~920 pairs are blocked only by team spellings ("Slavia P." / "Slavia Prague"). Use **Select strong** → **Approve selected** in the Review tab after each scan.

### M2 — Make every shown surebet placeable (done 2026-10-20)

- [x] Odds re-checked automatically when a slip opens; stale after 120 s (30 s live); the slip plans from the re-checked prices.
- [x] One click per leg: **Open ↗** plus the book's own spelling of the match copied for its search (no book except Mozzartbet has a public per-event page).
- [x] Stakes rounded to whole KM by default; profit shown after rounding; warnings when rounding eats the edge or a stake is under 1 KM. Per-book maximums are still unknown.
- [x] Placement order (longest odds first), **Mark placed** at the odds actually taken, remaining legs re-planned, red warning when it stops being an arbitrage.
- [x] Gate evidence served: on each surebet (`evidence`, `listings`) and in `/api/debug/report`.

### M3 — Track what was actually placed

Without records there is no way to know whether the platform makes money.

- [ ] **Bet journal.** Add a "Mark as placed" action that stores both legs (book, odds shown, odds actually taken, stake, time) in a local store, plus a settle action for the result. *Done when:* a history view shows realized profit per surebet and in total.
- [ ] **Slippage and limit stats per book.** Track how often the odds moved between scan and placement, by how much, and which books limited or voided bets. Feed this back into ranking, so that books which move or limit get demoted. *Done when:* each book has a measured slippage rate.
- [ ] **Bankroll per book.** The operator enters a balance per book. Hide or flag surebets the balances cannot cover.

### M4 — Run it unattended

- [ ] **Scheduled scans.** Scan prematch every N minutes and live more often. Back off on errors per book, using the existing health data. *Done when:* the server runs 24 hours without manual scans and without exhausting memory or browsers.
- [ ] **Notifications.** Send a Telegram or Discord message when a new verified surebet passes a threshold. The message carries the card link and the re-verified margin. De-duplicate by surebet signature.
- [ ] **Security before exposure.** Finish the stashed hardening (`git stash list`: "paused: security hardening"). Until then the server is localhost-only, or `API_KEY` must be set.
- [ ] **Deployment.** Write one documented way to run the server persistently: a service or container with Playwright browsers installed, logs, and restart on crash.

### M5 — Grow the yield (only after M1–M3 show real profit)

- [ ] Turn on Asian handicap and first-half markets once each has captured fixtures for every book that offers them.
- [ ] Add more BiH bookmakers (MaxBet, Meridianbet). Each needs the full audit: registry entries, fixtures, a deep-link declaration.
- [ ] Look at live-mode surebets separately. Live odds move in seconds, so they only matter if M2's re-verify-then-place loop is fast enough.

### Housekeeping (do when touching the area)

- [ ] `orientation_unresolved`: emit it from the gate or delete it. Today `engine/certainty.py`, `frontend/js/app.js` and `tests/test_frontend_review.py` must change together.
- [ ] Reload `config/bookmaker_deeplinks.json` without restarting the server.
- [ ] Re-read the six `supports_event_id: false` notes against the live sites every few months, and date the check.

---

## 5. Working rules

* `python -m pytest`, `ruff check .`, `mypy .` and `scripts/generate_market_mapping_doc.py --check` must stay green — CI (`.github/workflows/ci.yml`) runs all four.
* Every new registry entry needs a captured payload under `tests/fixtures/markets/`.
* Before betting anything: `POST /api/verify` on the card, and only act on `still_profitable` + `meets_min_profit`.
* Doc claims in this file and `README.md` are checked by `tests/test_readme_claims.py`; keep the status callout and the Phase 4 section in step with the code.
