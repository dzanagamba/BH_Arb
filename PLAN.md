# Surebet Scanner — Detailed Execution Plan (Muse 12)

> **Goal:** Fix “rare + wrong” surebets and grow arbitrage yield 5–10× while keeping false positives near zero.
> **Baseline:** `claudesurebet` == `dzanagamba/surebet-scanner` @ `7d2d5d8` (9 bookmakers, ~6057 prematch matches → ~802 groups → 0–2 surebets per scan, Mozzartbet degraded to 56 matches, EVLBet only 1X2).
> **New repo:** `surebetmuse12` — https://github.com/dzanagamba/surebet-muse12 (`plan/muse12-roadmap` @ `aa33254` → `2935d90`).
> **Status (2026-08-20):** P0 correctness + P1 yield + P2 reliability shipped. 107 tests green, ruff clean, groups 802→856 (+6.7%), WWIN 15s→~7s, Mozzart 56→800+ (projected), dust/health/TTL live.
> **Status (2026-09-26):** Phase 4 (mapping certainty) shipped — 13 tasks. `verified` requires a proven claim, and link evidence is proven two ways: a browser check opened that book's per-event URL, **or** the book declared in `config/bookmaker_deeplinks.json` that it has no per-event route. 6 of the 9 books declare `supports_event_id: false` and are verified on identity alone; the 3 that declare a route (MDShop, Admiralbet, Mozzartbet) must still have theirs proven, and MDShop's and Admiralbet's `?event=<id>` routes are **inert**, so a group holding either still cannot verify. **Zero surebets is today's expected output, and it is correct:** the shipped gate produces 0 surebets on the stored scan — a measured claim with two conditions, read in §3 *Phase 4* along with the correction that supersedes the 2026-09-25 status line.
> **Status (2026-10-20):** MDShop's and Admiralbet's `?event=<id>` routes were re-checked in a browser and are still **inert**, so both now declare `supports_event_id: false` in `config/bookmaker_deeplinks.json`. 8 of the 9 books are verified on identity alone; only Mozzartbet declares a route and must still have it proven. The blockers to a surebet are now identity gaps (league names, team spellings), not links. The zero surebets figure in §3 *Phase 4* is a dated measurement with conditions; §4 *TODO* tracks what replaces it.
> **Status (2026-10-20, later):** M0 mostly done. Prematch and live fixtures re-captured; `scripts/price_check.py` added (fresh prematch scan: 0 outliers); unmapped-id diagnostic empty in both modes; Admiralbet/Premier live gaps declared. A live scan produced a fake 19.8% surebet, so MDShop/Admiralbet live now read only the match total and the engine takes one leg per price source (MDShop + Admiralbet = NSoft). Open in M0: bring NSoft live 1X2/BTTS/DC back only once proven against a live score; Mozzartbet live returns no matches.
> **Status (2026-10-27):** MaxBet added at the operator's request (ahead of M5): scraper, registry rows, prematch and live fixtures. It declares a per-event route (`/match/<id>`, browser-checked 2026-10-27) in `config/bookmaker_deeplinks.json`, so 8 of the 10 books now declare `supports_event_id: false` and MaxBet joins Mozzartbet as a book whose links must be proven before its groups verify. Team names are now canonicalized per listing (youth/reserve/women markers, score and country notes) before grouping.


## How to execute this plan (read this first)

This file is written so that an agent can work through it **one task at a time
with no other context**. You do not need to know what the product is for. Every
open task in §4 is a self-contained card: it names the files, the current facts,
the exact steps, the tests to add, the commands to run and the condition that
makes it done. If a card and the code disagree, the code wins: stop, write down
the disagreement in the card's **Log** line, and move to the next task.

**Sections.** §0–§3 are history and principles: read them only when a card
points there. §4 is the task queue. §5 holds the rules that apply to every task
and the shared procedures (S1–S5) that cards refer to by name.

### The loop

1. Do §5 **S1 (environment check)** once per session. All four checks must pass
   before you change anything. If they fail before you have touched the tree,
   stop and report; do not try to fix them as part of another task.
2. Take the **first** task in §4 *Execution order* that is not ticked `[x]`, not
   marked `BLOCKED` and whose **Depends on** tasks are all ticked.
3. Check its **Needs** line. `offline` means code and tests only. `network`
   means it calls bookmaker sites over HTTP. `browser` means Playwright or a
   human-visible browser. `human` means a person must decide or act; if you are
   not a human and cannot ask one, skip the task and leave a Log line saying so.
4. Follow **Steps** in order. Do not add steps, extra refactors, renames or
   formatting changes outside the listed files.
5. Run the card's **Verify** commands, then §5 **S1** again. Everything must be
   green.
6. Do §5 **S5 (record progress)**: tick the box, fill the Log line, commit.
7. Go back to 2.

### Hard stops: never do these, whatever a card seems to imply

* Never make the certainty gate (`engine/certainty.py`) accept a pair it
  refuses today, **except** in task M1-5, and then only in exactly the way M1-5
  describes. (One operator-approved exception, 2026-10-27: pairs in
  `config/team_alias_reviewed.json` pass the team check without the 90
  similarity floor; league, kickoff, category and link checks are unchanged.)
* Never set `deep_link_verified=True` anywhere except through
  `scripts/verify_deeplinks.py` or `POST /api/verify-links`.
* Never edit `config/team_alias_allowlist.json`, `config/league_mappings.json` or
  `config/league_equivalences.json` by hand. `config/team_alias_reviewed.json` is
  the record of a human review: add to it only pairs someone has actually reviewed,
  each with its fixture evidence (and every rejection with its reason). Only `scripts/derive_mappings.py
  --apply` or the dashboard's Review approval may write them.
* Never flip a `supports_event_id` value in `config/bookmaker_deeplinks.json`
  without a dated browser check written into that book's `note` (task H-3).
* Never edit, delete or re-take a file under `tests/fixtures/e2e_certified/`.
  They are frozen on purpose for `tests/test_e2e_certified.py`.
* Never edit the block-quoted status lines at the top of this file (the lines
  starting with `>`). `tests/test_readme_claims.py` reads them. Record progress
  in the task cards instead.
* Never place a real bet, enter a bookmaker login or move money.
* Never `git push`, open a PR, `git stash drop` or rewrite history unless the
  operator asks.

---

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

## 4. TODO — task queue

**Baseline on 2026-10-20** (branch `production-hardening` @ `69fa373`):
`python -m pytest` → 953 passed; `ruff check .` clean; `mypy .` clean on 68
source files; `scripts/generate_market_mapping_doc.py --check` in sync. If your
own S1 run shows different numbers before you change anything, write them in
the Log line of the task you are about to start.

### Execution order

Do them in this order. Tasks in the same wave do not depend on each other, so
separate agents may do them in parallel, but only when the cards' **Files**
lists do not overlap; otherwise do them one after another.

| Wave | Task | Needs | Summary |
|---|---|---|---|
| 1 | M1-3 | offline | A group must hold ≥ 2 different price sources, not ≥ 2 books |
| 1 | M1-4 | offline, then network after 2026-10-25 | Pin SportPlus local-time parsing across the clock change |
| 1 | H-1 | offline | Delete the gate reason nothing emits |
| 1 | H-2 | offline | Reload the deep-link declarations when the file changes |
| 2 | M1-5 | offline | Same Betradar id = same match, even when the names differ |
| 3 | M0-1 | network (live games) | Capture Premier live O/U and close its declared gap |
| 3 | M0-2 | network (live games) | `price_check.py --live` on a fresh live scan |
| 3 | M0-4 | network, browser | Find out why Mozzartbet live returns nothing, and fix it |
| 3 | M1-2 | network, browser | Get Mozzartbet prematch to the site's full listing |
| 4 | M1-1 | network, human review | Re-learn league/team names from a fresh scan |
| 5 | M3-1 | offline | Store placed legs and settle them |
| 5 | M4-3 | offline | Re-apply the stashed security hardening |
| 6 | M3-2 | offline | Per-book slippage stats from the journal |
| 6 | M3-3 | offline | Per-book balances; flag slips they cannot cover |
| 6 | M4-1 | offline, then a 24 h run | Scan on a timer, with per-book back-off |
| 7 | M4-2 | offline, network for the final check | Message new surebets to Telegram |
| 7 | M4-4 | offline, then docker | One documented way to run it persistently |
| any | H-3 | browser, human | Re-read the 8 "no per-event route" declarations |
| — | M0-3 | BLOCKED | NSoft live 1X2/BTTS/DC back on |
| — | M5 | do not start | Asian handicap, first half, new books, live arbs |

Wave 3–4 tasks need real football games on the bookmakers' feeds. Live tasks
need games **in play**: run them between 12:00 and 21:00 UTC, best on a
Saturday or Sunday. A live scan at night returns little or nothing and proves
nothing.

---

### M0 — Market mappings correct for every book

Background for every M0 card: a *market mapping* says which id or block name in
a bookmaker's feed means which bet (1X2, over/under 2.5 goals, and so on). If a
mapping is wrong, the scanner compares two different bets and shows a profit
that does not exist. `config/bookmaker_markets.json` is the mapping;
`MARKET_MAPPING.md` is generated from it; `tests/fixtures/markets/*.json` are
real captured feed payloads, and `tests/test_market_fixtures.py` checks the
mapping against them.

Already done on 2026-10-20 (do not redo): prematch fixtures re-captured for 8
books; live fixtures re-captured for 7 books; `scripts/price_check.py` added
(fresh prematch scan: 0 outliers); NSoft live rest-of-match ids switched off;
unmapped-id diagnostic empty in both modes; Admiralbet live O/U declared
(id `22`) and captured.

#### M0-1 · Capture Premier live over/under and close the gap

- [ ] **Status:** TODO
- **Needs:** network, at least 5 live football games on premier-kladionica.com.
- **Depends on:** nothing.
- **Files:** `tests/fixtures/markets/premier_kladionica_live.json` (re-written by
  the capture script), `tests/test_market_fixtures.py` (`UNCOVERED_ROWS`),
  `MARKET_MAPPING.md` (line starting `Audit date:`, outside the generated block).
- **Facts:** `UNCOVERED_ROWS` in `tests/test_market_fixtures.py` declares three
  Premier live rows as gaps: `("premier_kladionica", "live", "over_under_1_5")`,
  `..._2_5` and `..._3_5`. The registry reads them from the block named
  `LIVE - ZBROJ GOLOVA` (constant `LIVE_ZBROJ_GOLOVA` in
  `scrapers/premier_kladionica.py`). The last capture had no such block. The four
  Mozzartbet O/U 1.5/3.5 rows and the EVLBet/Betole rows are permanent gaps;
  leave them alone.
- **Steps:**
  1. Run `python scripts/capture_market_fixtures.py --books premier_kladionica`.
  2. Open the new `tests/fixtures/markets/premier_kladionica_live.json` and search
     for `LIVE - ZBROJ GOLOVA`. If it is absent, `git checkout --
     tests/fixtures/markets/premier_kladionica_live.json
     tests/fixtures/markets/premier_kladionica_prematch.json`, write
     "no ZBROJ GOLOVA block at <UTC time>, N live games" in the Log line, and
     stop. Try again on another day.
  3. If it is present: delete the `**{ ("premier_kladionica", "live",
     f"over_under_{line}") ... for line in ("1_5", "2_5", "3_5") }` entry from
     `UNCOVERED_ROWS`, but only for the lines whose `Over X`/`Under X` pair is
     actually in the block. Keep the entry for any line that is missing.
  4. Run `python -m pytest tests/test_market_fixtures.py -q`. A failure in
     `test_a_declared_gap_is_not_just_listed_but_forgotten` means a row you kept
     declared is in fact present: remove it too. Any other failure means the
     mapping is wrong: revert the fixture and report the failing assertion.
  5. Run `python -m pytest tests/test_e2e_certified.py -q`. It must still pass
     (it reads the frozen copies, not the file you just replaced).
  6. In `MARKET_MAPPING.md`, change the `Audit date:` sentence so it reads
     `Audit date: <today>; prematch and live captures re-taken 2026-10-20 and
     <today> (Premier live O/U).` Keep the rest of that paragraph unchanged.
  7. Run `python scripts/generate_market_mapping_doc.py --check`.
- **Verify:** §5 S1.
- **Done when:** no `premier_kladionica` row is left in `UNCOVERED_ROWS`, and S1
  is green.
- **Log:** —

#### M0-2 · Cross-book price check on a fresh live scan

- [ ] **Status:** TODO (prematch half done 2026-10-20: 1,028 verified groups,
  4,493 comparisons, 0 outliers)
- **Needs:** network, at least 10 live games in progress.
- **Depends on:** M0-1 is not required; do it first if both are possible the same
  afternoon.
- **Files:** none changed unless an outlier is found.
- **Facts:** `scripts/price_check.py` removes each book's margin per market and
  flags a book whose implied probability is more than `--threshold` (0.10) from
  the median of the other books. It exits 1 when it finds an outlier. It counts
  MDShop and Admiralbet as one source. Live groups hold few books, so a run with
  fewer than 10 comparisons is not a result.
- **Steps:**
  1. §5 S2 with `mode=live`.
  2. Run `python scripts/price_check.py --live` and save the full output into the
     Log line (counts and every outlier row).
  3. If the comparisons count is below 10, write that in the Log and repeat later.
  4. If it exits 0 with ≥ 10 comparisons: tick the task.
  5. If it exits 1: for each outlier, write down book, market, the book's odds and
     the other books' odds. Do **not** change the registry yourself. Add the
     outlier table to the Log, mark the task `BLOCKED (outlier, needs review)`,
     and stop. A human decides whether the id is wrong.
- **Done when:** one live run with ≥ 10 comparisons and 0 outliers is logged.
- **Log:** —

#### M0-3 · NSoft live 1X2 / BTTS / DC (BLOCKED)

- [ ] **Status:** BLOCKED. Do not start without an operator saying so.
- **Facts:** MDShop and Admiralbet (both on the NSoft platform) price live 1X2
  (id `6` at `sbv` 0-0), BTTS (`995`) and DC (`18`/`42`) for the *rest of the
  match* from the current score, not for the full match. On 2026-10-20 that made
  a fake 19.8 % surebet. These ids are in `_excluded` in
  `config/bookmaker_markets.json`, and only the match total (`22`) is read.
- **Unblock condition:** a field in the raw NSoft live event (not the stripped
  fixture) that gives the current score. To look for it: run
  `python scripts/capture_market_fixtures.py --books mdshop` while games are live,
  but print the raw event JSON before it is stripped and search for a score
  (keys like `result`, `score`, `currentResult`). Write what you find in the Log.
- **If unblocked, the design is:** read a market only when the score is 0-0, or
  read id `59` ("Oba tima daju gol") only when a team has not yet scored, and
  prove each with `scripts/price_check.py --live` showing 0 outliers. Write a new
  card for it; do not implement from this paragraph.
- **Log:** —

#### M0-4 · Mozzartbet live returns no matches

- [ ] **Status:** TODO
- **Needs:** network, browser, live games in progress.
- **Depends on:** nothing.
- **Files:** `scrapers/mozzartbet.py` only.
- **Facts:** in both live scans on 2026-10-20, Mozzartbet returned 0 live
  matches while other books returned dozens. `MozzartbetScraper.fetch_and_parse`
  posts to `{BASE_URL}/betting/matches` with `"date": "live"`, then keeps only
  events where `_is_in_play` is true (`startTime` ≤ now + 5 min). Possible causes,
  none confirmed: the live list is on another endpoint; `"date": "live"` returns
  nothing; `startTime` is not in milliseconds for live items; the page load at
  `/sr/kladjenje` does not establish the session needed for live.
- **Steps:**
  1. Write a throwaway script in your scratch directory (not in the repo) that
     runs `asyncio.run(MozzartbetScraper().fetch_and_parse(live=True))` with
     `logging.basicConfig(level=logging.DEBUG)`, and prints `len(all_raw_items)`
     before the in-play filter. (Copy the method into the script and add prints;
     do not edit the repo for this step.)
  2. If raw items > 0 but parsed = 0: print the `startTime` of 3 items and
     `_now_ms()`. Fix the unit or the filter in `_is_in_play`.
  3. If raw items = 0: open `https://www.mozzartbet.ba/sr/uzivo/sport/1` in a
     browser with developer tools (or Playwright with `page.on("response")`
     logging every URL), and find the request that returns the live football
     list. Record its URL, method and body in the Log.
  4. Change `fetch_and_parse` so that `live=True` navigates to the live page from
     step 3 and requests that endpoint. Keep the prematch path byte-identical.
  5. Run the scraper again: it must return > 0 live matches whose markets parse
     (at least some with 1X2 or O/U 2.5).
  6. Run `python scripts/capture_market_fixtures.py --books mozzartbet`, then
     `python -m pytest tests/test_market_fixtures.py -q`. If the live fixture
     changed shape, the capture script also needs the new endpoint: update its
     Mozzartbet live captor the same way.
  7. Add a unit test in `tests/test_live_mode.py` that pins whatever you fixed
     (the endpoint/body sent for `live=True`, or the `_is_in_play` unit), using a
     fake response object — no network in tests.
- **Verify:** §5 S1; then §5 S2 with `mode=live` and check
  `GET /api/health` → `live.per_bookie.mozzartbet` > 0.
- **Done when:** a live scan lists Mozzartbet matches and S1 is green.
- **Log:** —

---

### M1 — Find more real surebets

Background: the pipeline is *scrape → normalize names → group listings of the
same match across books (the certainty gate in `engine/certainty.py` decides) →
price each group (`engine/arbitrage.py`)*. On 2026-10-20 a fresh prematch scan
gave 818 verified groups and 0 surebets (best combination −1.14 %). More books
per group and more groups raise the chance of a surebet.

Already done (do not redo): MDShop/Admiralbet declared route-less; 422/426
Mozzartbet links proven; SportPlus local time fixed; unmapped leagues settled on
exact teams + kickoff; punctuation-insensitive team compare; EVLBet disabled;
`scripts/derive_mappings.py` written and applied once; one-leg-per-price-source
in `ArbitrageEngine._best_combination`.

#### M1-1 · Re-derive name mappings from a fresh scan

- [ ] **Status:** TODO (repeat every 2 weeks; tick only the current round)
- **Needs:** network (a scan), human (review of the proposals).
- **Depends on:** M1-5 and M1-2 done gives better input, but is not required.
- **Files:** `config/league_mappings.json`, `config/team_alias_allowlist.json`
  (written only by the script).
- **Steps:**
  1. §5 S2 with `mode=prematch`.
  2. `python scripts/derive_mappings.py cache/last_scan.json --report
     <scratch>/proposals.json` (`<scratch>` = a directory outside the repo).
  3. Open the report. For every entry under `below_gate_similarity` (pairs like
     "Man. City" / "Manchester City"), list them in the Log. These are **not**
     applied by the script; a human approves them in the dashboard Review tab.
     If you are not a human, stop after listing them.
  4. Check every league proposal joins competitions of the **same country and
     tier**. If one does not (e.g. a women's league joined to a men's league, or
     two countries), write it in the Log and do not run step 5.
  5. `python scripts/derive_mappings.py cache/last_scan.json --apply`.
  6. §5 S2 again and compare the Log numbers: listings in multi-book groups
     (from `GET /api/debug/report`: sum of `len(bookmakers)` over groups with
     ≥ 2 books) before vs after.
- **Verify:** §5 S1 (the config changes must not break any test).
- **Done when:** the round's before/after numbers are in the Log and S1 is green.
- **Log:** 2026-10-27 round (inputs: the 2026-10-20 scan and a 2026-10-27 00:05 UTC scan with MaxBet; Mozzartbet/Premier/WWIN returned nothing at that hour). The script now reads names through `canonicalize_fixture` and writes conflict components as `league_equivalences.json` pairs. Applied: 70 names onto 42 ids, 36 new ids, 5 equivalence pairs (UEFA Youth League, Liga MX women, Russian and Bulgarian 2nd tier, EFL Cup), 542 aliases. Every league proposal was checked for same country and tier; two odd-looking ones are fixture-backed (MaxBet files Carling Knockout games as "Nedbank Cup"; NSoft lists the Irish 1st-division play-off as "Irska 2"). Listings in verified groups: 4,292 -> 4,387 (2026-10-20 scan), 2,270 -> 2,393 (2026-10-27 scan). 588 pairs below the similarity floor and 28 ambiguous names are left for the Review tab. Second pass the same day: stage suffixes (cup groups, championship/relegation groups, East/West) no longer count as ambiguity - 19 names onto 7 ids, 3 new ids, 7 more equivalence pairs; 4,387 -> 4,413 and 2,393 -> 2,411. The 587 below-floor team pairs were reviewed at the operator's request (565 approve, 22 reject) into `config/team_alias_reviewed.json`; the operator then had the gate honour that file without the 90 floor, and the matcher's scorer count a reviewed pair as a full match. Listings in verified groups: 4,413 -> 4,600 (2026-10-20 scan) and 2,411 -> 2,530 (2026-10-27 scan).

#### M1-2 · Mozzartbet prematch coverage

- [ ] **Status:** TODO
- **Needs:** network, browser (to read the site's own count).
- **Depends on:** nothing.
- **Files:** `scrapers/mozzartbet.py` (`MozzartbetScraper.fetch_and_parse`),
  `tests/test_live_mode.py` or a new `tests/test_mozzartbet_pagination.py`.
- **Facts:** on 2026-10-20 the scraper returned 285 prematch listings; the site
  lists about 1,150 football matches. Only 85 of the 285 reached a multi-book
  group. The scraper posts `pageSize: 15` and pages from `currentPage: 0` until a
  page returns fewer than 15 items, a non-200, or `totalPages` is reached
  (capped at 100).
- **Steps:**
  1. Read the site's count: open
     `https://www.mozzartbet.ba/sr/kladjenje/sport/1?date=all_days` and note the
     football total shown. Log it with the UTC time.
  2. In a scratch script (not the repo), call the scraper with DEBUG logging and
     log, per page: `currentPage`, items returned, `totalPages`, HTTP status.
     Log why the loop stopped (short page, non-200, exception, cap).
  3. Try `pageSize` 50 and 100 in the scratch script. Keep the largest value for
     which every page returns `pageSize` items except the last.
  4. If the loop stops early because of a non-200 or an exception (not a short
     page), add one retry with a 2 s wait per page before giving up.
  5. If, with the best page size, the total is still below 90 % of step 1: fetch
     per competition instead — read the competition ids from the first
     response's payload (look for a list of competitions with ids), and run the
     same pagination once per id with `"competitionIds": [id]`. Deduplicate by
     event id (the existing `seen` set in `_event_to_match` does this).
  6. Put the chosen page size in a module constant `PAGE_SIZE` and use it in the
     body and the short-page check.
  7. Add a test with a fake `page.request.post` that returns 3 full pages and 1
     short page, and assert all items are collected and the 5th call is not made.
  8. §5 S2 with `mode=prematch`; log `per_bookie.mozzartbet` and the number of
     Mozzartbet listings in multi-book groups.
  9. Prove links for the new events (Mozzartbet is the one book whose links
     must be proven, or its groups do not verify): with the server running, call
     `curl -X POST "http://127.0.0.1:8000/api/verify-links?bookmaker=mozzartbet&limit=20"`
     every 31 s (rate limit is 2 per minute) until the response shows
     `"remaining": 0`. This takes about 10 minutes per 400 events.
  10. §5 S2 again; log verified groups and Mozzartbet's grouped share.
- **Verify:** §5 S1.
- **Done when:** Mozzartbet's prematch count is ≥ 90 % of the site count in step
  1, and its grouped share (listings in multi-book groups ÷ listings) is within
  15 percentage points of the average of the other enabled books.
- **Log:** —

#### M1-3 · Count MDShop and Admiralbet as one price source in grouping

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** nothing.
- **Files:** `engine/matcher.py` (`MatchMatcher.group_matches`, final filter),
  `tests/test_matcher.py`.
- **Facts:** MDShop and Admiralbet run on one odds feed and quote identical
  prices. `config/settings.py` defines `PRICE_SOURCES` and `price_source(book)`.
  The engine already takes at most one leg per price source, and
  `scripts/price_check.py` counts them once. But `group_matches` returns a group
  when it holds ≥ 2 *bookmakers*, so a group of only MDShop + Admiralbet is
  returned, counted in `match_groups` and `verified_groups`, and can never be
  priced.
- **Steps:**
  1. In `group_matches`, in the list comprehension that builds
     `multi_bookie_groups`, replace `len({m.bookmaker for m in g.matches}) >= 2`
     with `len({price_source(m.bookmaker) for m in g.matches}) >= 2`. Import
     `price_source` from `config.settings`.
  2. Change nothing else. In particular leave the `>= 2` check right after
     `best_group.matches.append(...)` (it sets `status = "verified"` while the
     group is still being built) as it is.
  3. Update the comment above the filter to say "at least two distinct price
     sources (config.settings.PRICE_SOURCES)".
  4. Expected fallout, measured by a trial run on 2026-10-20: exactly one
     existing test fails,
     `tests/test_e2e_certified.py::test_scan_refuses_a_link_proof_that_aged_out`,
     because its two books (`ROUTE_BOOKS = ("mdshop", "admiralbet")`) are now
     one price source. That test is about link-proof expiry, not price sources.
     Fix it by adding a `monkeypatch` parameter and, as its first line,
     `monkeypatch.setattr("engine.matcher.price_source", lambda book: book)`
     with a one-line comment saying why. Do not change `ROUTE_BOOKS`. If any
     other test fails, stop and log it.
- **Tests to add** in `tests/test_matcher.py`:
  - `test_group_of_one_price_source_is_not_returned`: two identical listings
    (same teams, league, kickoff, both with 1X2 odds), bookmakers `mdshop` and
    `admiralbet` → `group_matches` returns `[]`.
  - `test_group_with_a_second_price_source_is_returned`: the same two plus a
    `wwin` listing → one group with 3 matches.
  Build the listings the way the existing tests in that file do.
- **Verify:** `python -m pytest tests/test_matcher.py tests/test_matcher_order.py
  tests/test_e2e_certified.py -q`, then §5 S1.
- **Done when:** both new tests pass and S1 is green.
- **Log:** —

#### M1-4 · SportPlus kickoffs across the DST change

- [ ] **Status:** TODO (part A offline; part B after 2026-10-25)
- **Needs:** part A offline; part B network.
- **Depends on:** nothing.
- **Files:** `tests/test_scraper_common.py`; `scrapers/common.py`
  (`parse_local_dt`) only if a test fails.
- **Facts:** SportPlus sends kickoffs as Sarajevo wall-clock time without an
  offset; `parse_local_dt` converts them to naive UTC with
  `ZoneInfo("Europe/Sarajevo")`. On 2026-10-25 at 03:00 local, clocks go back to
  02:00, so 02:00–02:59 happens twice. Python's default (`fold=0`) picks the
  first, summer-time, occurrence. Measured on 2026-10-20:
  `parse_local_dt("2026-10-25T02:30:00")` → `2026-10-25 00:30`,
  `"2026-10-25T01:30:00"` → `2026-10-24 23:30`,
  `"2026-10-25T03:30:00"` → `2026-10-25 02:30`,
  `"2027-03-28T02:30:00"` (a time that does not exist) → `2027-03-28 01:30`.
- **Part A steps:**
  1. Add `test_parse_local_dt_across_the_autumn_change` to
     `tests/test_scraper_common.py` asserting exactly the four values above.
  2. Run it. It must pass without code changes. If it does not, the installed
     `tzdata` differs: report the actual values in the Log and stop.
- **Part B steps (on or after 2026-10-26):**
  1. §5 S2 with `mode=prematch`.
  2. Save this as `<scratch>/dstcheck.py` and run it from the repo root with
     `python <scratch>/dstcheck.py`. It pairs every SportPlus listing with every
     other book's listing of the same normalized teams and prints the kickoff
     differences in minutes, plus each 60-minute pair.
     ```python
     import json
     from collections import Counter
     from datetime import datetime

     scan = json.load(open("cache/last_scan.json", encoding="utf-8"))
     key = lambda m: (m.get("home_team_normalized"), m.get("away_team_normalized"))
     others = {}
     for m in scan["matches"]:
         if m["bookmaker"] != "sportplus" and m.get("kickoff"):
             others.setdefault(key(m), []).append(m)
     deltas = Counter()
     for m in scan["matches"]:
         if m["bookmaker"] != "sportplus" or not m.get("kickoff"):
             continue
         for o in others.get(key(m), []):
             d = (datetime.fromisoformat(m["kickoff"]) - datetime.fromisoformat(o["kickoff"])).total_seconds() / 60
             deltas[round(d)] += 1
             if abs(abs(d) - 60) < 1:
                 print("60-min gap:", m["home_team"], "-", m["away_team"], m["kickoff"], o["bookmaker"], o["kickoff"])
     print(sorted(deltas.items()))
     ```
  3. A 60-minute gap is a SportPlus bug only if SportPlus disagrees with **two
     or more** other books that agree with each other. Log every such case with
     the raw kickoff string SportPlus sent (search the SportPlus scraper's
     response for the match). If there are none, tick the task.
  4. If there are: change `parse_local_dt` so that an ambiguous local time
     (`fold` matters) uses whichever fold the failing cases need, add those cases
     to the part A test, and re-run S1.
- **Already observed (2026-10-20 scan, do not re-investigate):** three USL games
  on 2026-10-25 at 00:00–00:30 UTC (El Paso–New Mexico, Colorado Springs–Tulsa,
  San Antonio–Orange County) are 60 minutes later at Premier Kladionica than at
  SportPlus and WWIN, which agree. Premier sends epoch milliseconds, so the error
  is in Premier's feed, not in parsing; the gate's 15-minute window already keeps
  those pairs out of `verified`. No change needed.
- **Done when:** part A test passes and part B shows no 60-minute difference.
- **Log:** —

#### M1-5 · Accept a shared Betradar id as identity proof

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** M1-3 and H-1 done (they touch neighbouring code and tests).
- **Files:** `engine/certainty.py`, `engine/matcher.py`, `frontend/js/app.js`
  (`REASON_LABELS`), `README.md` (status table in *Match & mapping certainty*),
  `tests/test_certainty.py`, `tests/test_matcher_certified.py`,
  `tests/test_readme_claims.py` (`_observed_reasons`),
  `tests/test_frontend_review.py` (`KNOWN_REASON_CODES`).
- **Facts:** `Match.betradar_id` is filled by `scrapers/mdshop.py`,
  `scrapers/admiralbet.py`, `scrapers/sportplus.py` and `scrapers/wwin.py` (empty
  string when the feed has none). Betradar is a data provider whose match id is
  shared across books, so two listings with the same non-empty id are the same
  real match whatever their team or league names say. Today the gate ignores the
  field: such a pair with differently spelled teams ends as `team_unresolved`
  (and differently named mapped leagues as `league_mismatch`).
- **Rules to implement (exactly these):**
  - `same_id` = both `betradar_id` non-empty and equal.
  - `different_id` = both non-empty and not equal.
  - `different_id` → append the new reason `betradar_mismatch` and add it to
    `HARD_REJECT_REASONS` (status `rejected`). Two different ids are two
    different matches.
  - `same_id` → the league check passes (evidence `league_identity` with
    `reason="betradar_id"`), and the team check passes (evidence
    `team_identity`, `source="rule"`, `reason="betradar_id"`). The kickoff,
    category and link checks are **unchanged** and can still refuse the pair.
  - Orientation for `same_id`: compute
    `direct = fuzz.token_set_ratio(a.home_team_normalized, b.home_team_normalized) + fuzz.token_set_ratio(a.away_team_normalized, b.away_team_normalized)`
    and `swapped` the same with home/away of `b` exchanged. `is_swapped = swapped > direct`.
  - Neither id present, or only one present → behave exactly as today.
- **Steps:**
  1. `engine/certainty.py`, `evaluate_pair`: compute `same_id`/`different_id` at
     the top. In the league block, when `same_id` set `league_ok = True` and
     `league_reason = "betradar_id"` before the `if not league_ok` line. After
     `teams_ok, is_swapped, team_reason = self._teams_ok(a, b)`, when `same_id`
     set `teams_ok = True`, `is_swapped` per the rule above, and use
     `team_evidence_reason = "betradar_id"` (skip the allowlist branch). When
     `different_id`, append `"betradar_mismatch"` to `reasons`.
  2. `engine/certainty.py`, `evaluate(match, group)`: pick the anchor as
     `next((m for m in group.matches if match.betradar_id and m.betradar_id == match.betradar_id), group.matches[0])`.
     When the pair result's team evidence reason is `"betradar_id"`, skip the
     `_group_team_orientation` check (keep `result.is_swapped` from the pair) and
     skip the group-league check (treat it like `league_settled`). Members of a
     group are already stored in the group's home/away frame, so orientation
     against that member is orientation against the group.
  3. `engine/matcher.py`, `group_matches`: keep a dict
     `groups_by_betradar: dict[str, MatchGroup]`, filled whenever a match with a
     non-empty `betradar_id` is added to a group or starts a new one. For each
     match with a non-empty id found in the dict, put that group at the front of
     `scored` with confidence `1.0` (if this bookmaker is not already in it),
     even if it is not in `candidate_groups`. The gate still decides.
  4. `frontend/js/app.js`: add `betradar_mismatch: 'Different Betradar match id'`
     to `REASON_LABELS`.
  5. `tests/test_frontend_review.py`: add `"betradar_mismatch"` to
     `KNOWN_REASON_CODES`.
  6. `README.md`: in the status table row for `rejected`, add
     `` `betradar_mismatch` `` to the reason list. Below the table, in the "Four
     rules inside stage 1" list, add a fifth bullet: "**A shared Betradar id
     proves identity.** MDShop, Admiralbet, SportPlus and WWIN carry the
     provider's match id. Two listings with the same id pass the league and team
     checks whatever their names (evidence reason `betradar_id`); kickoff,
     category and link checks still apply. Two different ids reject with
     `betradar_mismatch`." Change "Four rules" to "Five rules".
  7. `tests/test_readme_claims.py`, `_observed_reasons`: after the existing
     loop, also evaluate the pair `[_match(betradar_id="111"),
     _match(bookmaker="mbet", event_id="e2", betradar_id="222")]` and add its
     reasons to `observed`.
- **Tests to add:**
  - `tests/test_certainty.py`:
    `test_same_betradar_id_verifies_despite_different_names` (mdshop
    "Man. City"/"Arsenal" league "England 1" vs wwin "Manchester City FC"/"Arsenal
    London" league "Premier League", same kickoff, same id → `verified`, team
    evidence reason `betradar_id`);
    `test_same_betradar_id_still_needs_the_kickoff` (same as above, kickoffs
    60 min apart → not verified, reason `kickoff_delta`);
    `test_different_betradar_ids_reject` (identical names, ids differ →
    `rejected`, reason `betradar_mismatch`);
    `test_same_betradar_id_detects_swapped_orientation` (b lists the teams
    reversed → `is_swapped is True`);
    `test_one_sided_betradar_id_changes_nothing` (only one side has an id → same
    result as with no ids).
  - `tests/test_matcher_certified.py`:
    `test_betradar_pair_groups_across_differently_named_leagues` → one group of
    2 from the pair in the first certainty test.
- **Verify:** §5 S1. Then §5 S2 (prematch) and log verified groups before/after
  against the most recent number in M1-1's or M1-2's Log.
- **Done when:** all new tests pass, S1 is green, and a pair with matching ids
  and different spellings verifies while different ids never do.
- **Log:** —

---

### M2 — Make every shown surebet placeable (done 2026-10-20)

- [x] Odds re-checked automatically when a slip opens; stale after 120 s (30 s live); the slip plans from the re-checked prices.
- [x] One click per leg: **Open ↗** plus the book's own spelling of the match copied for its search (no book except Mozzartbet has a public per-event page).
- [x] Stakes rounded to whole KM by default; profit shown after rounding; warnings when rounding eats the edge or a stake is under 1 KM. Per-book maximums are still unknown.
- [x] Placement order (longest odds first), **Mark placed** at the odds actually taken, remaining legs re-planned, red warning when it stops being an arbitrage.
- [x] Gate evidence served: on each surebet (`evidence`, `listings`) and in `/api/debug/report`.

---

### M3 — Record what was actually placed

Background: today **Mark placed** in the bet slip (`markPlaced` in
`frontend/js/app.js`) keeps the placed leg only in browser memory
(`slipState[id].placed`). Nothing is stored, so there is no record of real
profit. Surebet ids (`Surebet.id`) are random per scan, so they cannot identify
an opportunity across scans; the journal stores a snapshot instead.

#### M3-1 · Bet journal

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** nothing.
- **Files:** `models/schemas.py`, new `server/journal.py`, `server/api.py`
  (include routes), `server/app.py` (load on start-up), `frontend/js/app.js`,
  `frontend/index.html`, new `tests/test_journal.py`.
- **Data model** (add to `models/schemas.py`):
  ```python
  class JournalLeg(BaseModel):
      bookmaker: str
      outcome_label: str
      odds_shown: float
      odds_taken: float
      stake: float
      placed_at: datetime          # naive UTC
      outcome: Literal["pending", "won", "lost", "void"] = "pending"

  class JournalEntry(BaseModel):
      id: str                      # uuid4 hex, server-generated
      surebet_id: str              # the scan's Surebet.id, for reference only
      mode: Literal["prematch", "live"]
      home_team: str
      away_team: str
      league: str = ""
      kickoff: datetime | None = None
      market_type: MarketType
      profit_percent_shown: float
      created_at: datetime         # naive UTC
      legs: list[JournalLeg] = []
      settled_at: datetime | None = None
      profit: float | None = None  # set on settle
  ```
- **Storage:** `cache/bet_journal.json`, a JSON list of entries, written with
  `server.api._atomic_write_json` (import it; do not copy it). Load on start-up
  in `server/app.py:_restore_state`. A missing or unreadable file means an empty
  journal; log a warning for unreadable, never crash.
- **Endpoints** (in `server/journal.py` as an `APIRouter`, included from
  `server/api.py` under the same `/api` prefix; every one uses
  `Depends(_require_api_key)`):
  - `POST /api/journal/legs` — body
    `{surebet_id, mode, surebet: <the surebet object as shown>, leg: {bookmaker, outcome_label, odds_shown, odds_taken, stake}}`.
    Finds an open entry (`settled_at is None`) with the same `surebet_id` and
    `mode`, or creates one from `surebet`. Appends the leg with
    `placed_at = now`. If a leg with the same `outcome_label` exists, replace it.
    Returns the entry.
  - `DELETE /api/journal/{entry_id}/legs/{outcome_label}` — removes a leg from an
    open entry; deletes the entry when it has no legs left. 404 if not found,
    409 if settled.
  - `POST /api/journal/{entry_id}/settle` — body
    `{outcomes: {outcome_label: "won" | "lost" | "void"}}` with a value for
    every leg. Sets each leg's `outcome`, `settled_at = now` and
    `profit = Σ(won: stake × odds_taken) + Σ(void: stake) − Σ(all stakes)`,
    rounded to 2 decimals. 400 if a leg is missing from `outcomes`.
  - `GET /api/journal` — `{entries: [...newest first], totals: {staked, profit,
    settled_count, open_count}}`; totals count settled entries only for
    `staked` and `profit`.
- **Frontend:**
  1. In `markPlaced`, after updating `state.placed`, `fetch` `POST
     /api/journal/legs` with the leg (`odds_shown` = the slip's planned odds for
     that leg, `odds_taken` = the typed odds, `stake` = `leg.plannedStake`). Use
     the same headers helper the Review actions use (`candidateActionHeaders()`).
     On failure show `showToast('Not saved to the journal: ...')`; keep the slip
     state either way.
  2. In `unmarkPlaced`, call the DELETE endpoint for the open entry (keep the
     returned `entry.id` in `slipState[id].journalId`).
  3. Add a **Placed bets** section to the History tab in `frontend/index.html`:
     a table with date, match, market, legs (book @ odds taken, stake), profit
     (or a **Settle** button). **Settle** opens a small form with a
     won/lost/void select per leg and posts to the settle endpoint. Show the
     totals line above the table. Escape every value with `escapeHtml`.
- **Tests** (`tests/test_journal.py`, FastAPI `TestClient`, journal path
  monkeypatched to `tmp_path`): create with one leg; second leg appends to the
  same entry; same label replaces; delete last leg removes entry; settle 1X2
  with legs 1 @ 2.10 / 40, X @ 3.60 / 25, 2 @ 4.00 / 35 and outcomes X won →
  profit = 25×3.60 − 100 = −10.00; settle with a void leg refunds its stake;
  settle missing a leg → 400; settle twice → 409; reload from file gives the
  same entries; with `API_KEY` set, a call without the header → 401.
- **Verify:** §5 S1; then start the server (§5 S2 steps 1–2 only), open the
  dashboard, mark a leg placed on any surebet (or POST one with curl), and check
  `cache/bet_journal.json` contains it.
- **Done when:** a settled entry shows its profit in the History tab and in
  `GET /api/journal` totals, and S1 is green.
- **Log:** —

#### M3-2 · Slippage and limit stats per book

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** M3-1.
- **Files:** `models/schemas.py` (`JournalLeg`), `server/journal.py`,
  `frontend/js/app.js`, `tests/test_journal.py`.
- **Steps:**
  1. Add to `JournalLeg`: `stake_requested: float | None = None` and
     `limited: bool = False`. In the slip's leg row add an optional
     "Book limited my stake" checkbox; when ticked, send `limited: true` and
     `stake_requested` = the planned stake, with `stake` = the amount actually
     accepted (a second number input shown only when the box is ticked).
  2. Add `GET /api/journal/stats` returning, per bookmaker:
     `legs`, `moved` (count where `odds_taken < odds_shown − 0.005`),
     `moved_rate` (`moved / legs`, 3 decimals), `avg_drop_percent`
     (mean of `(odds_shown − odds_taken) / odds_shown × 100` over moved legs, 2
     decimals, `null` when none), `limited`, `limited_rate`.
  3. In the bet slip, next to each leg's bookmaker name, show a warning badge
     "moves often" when that book has `legs ≥ 5` and `moved_rate ≥ 0.30`, and
     "limits" when `limited ≥ 1`. Fetch stats once on load and after every
     journal write. Do not change the surebet list's sort order.
- **Tests:** stats on a hand-built journal of 6 legs at one book, 2 moved, 1
  limited → exact numbers above; badges thresholds in a frontend test if the
  repo's `tests/test_frontend_*.py` pattern (Node runs app.js functions) makes
  it practical.
- **Done when:** `/api/journal/stats` returns the numbers and the badges show.
- **Log:** —

#### M3-3 · Bankroll per book

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** M3-1 (shares `server/journal.py` patterns), not its data.
- **Files:** `server/journal.py` (or new `server/bankroll.py`), `server/app.py`,
  `frontend/js/app.js`, `frontend/index.html`, `tests/test_bankroll.py`.
- **Steps:**
  1. Store `{bookmaker: balance_km}` in `cache/bankroll.json` (atomic write, load
     on start-up). `GET /api/bankroll` returns it; `PUT /api/bankroll` replaces it
     (body: the map; reject unknown bookmaker ids and negative numbers with 400).
     Both require the API key.
  2. In Settings (gear), add one number input per enabled bookmaker, saved with
     PUT on change.
  3. In the bet slip, for each leg whose planned stake exceeds that book's
     balance, show a red line "Balance at {book} is {x} KM; this leg needs {y}
     KM". In the surebet list, mark such surebets with a "balance" badge. A book
     with no balance entered is not flagged.
  4. Balances are never changed automatically.
- **Tests:** PUT/GET round trip; unknown book → 400; negative → 400; reload
  from file.
- **Done when:** a surebet whose stake exceeds a set balance is flagged in the
  list and the slip.
- **Log:** —

---

### M4 — Run it unattended

#### M4-1 · Scheduled scans

- [ ] **Status:** TODO
- **Needs:** offline; then a 24-hour run on a machine with network.
- **Depends on:** nothing (M4-3 first if the server will be reachable from other
  machines).
- **Files:** `config/settings.py`, `server/api.py`, new `server/scheduler.py`,
  `server/app.py` (lifespan), `.env.example`, `README.md` (*Configuration*),
  new `tests/test_scheduler.py`.
- **Settings** (env, in `config/settings.py`):
  `AUTO_SCAN_PREMATCH_MINUTES` (int, default `0` = off),
  `AUTO_SCAN_LIVE_MINUTES` (int, default `0` = off),
  `BOOK_BACKOFF_AFTER_FAILURES` (int, default `3`),
  `BOOK_BACKOFF_MAX_MINUTES` (int, default `60`).
- **Steps:**
  1. In `server/api.py`, extract the body of `trigger_scan` after the rate limit
     into `async def start_scan_if_idle(mode: str) -> bool` (returns False when
     the mode lock is held or a scan is running, else marks
     `status.is_scanning = True` and returns True). `trigger_scan` calls it and
     then `background_tasks.add_task(run_scan, mode)` as before. Behaviour of the
     endpoint must not change.
  2. `server/scheduler.py`: `async def scan_loop(mode: str, minutes: int)` —
     forever: `await asyncio.sleep(minutes * 60)`; if
     `await start_scan_if_idle(mode)`: `await run_scan(mode)`. Catch and log every
     exception inside the loop; never let it end except on cancel.
  3. In `server/app.py` lifespan: after `_restore_state()`, for each mode with
     minutes > 0 create a task with `asyncio.create_task`; on shutdown cancel
     them and await them with `contextlib.suppress(asyncio.CancelledError)`.
  4. Per-book back-off in `run_scan.scrape_one`: keep
     `_book_failures: dict[tuple[str, str], int]` (key: mode, book) and
     `_book_skip_until: dict[tuple[str, str], datetime]`. A scrape that raises or
     returns 0 matches while other books returned some increments the counter;
     a scrape with > 0 matches resets it. When the counter reaches
     `BOOK_BACKOFF_AFTER_FAILURES`, set skip-until to now +
     `min(2 ** (failures − BOOK_BACKOFF_AFTER_FAILURES) × interval, BOOK_BACKOFF_MAX_MINUTES)`
     minutes (interval = that mode's auto-scan minutes, or 5 when 0). While
     skipped, mark the book `"skipped"` in `bookmaker_progress` and append
     "{name}: backing off until HH:MM UTC" to `status.errors`. **Back-off
     applies only to scheduled scans**; a manual `POST /api/scan` scrapes every
     enabled book (pass a flag `scheduled: bool = False` into `run_scan`).
  5. Add to `GET /api/health`: `"scheduler": {"prematch_minutes": ...,
     "live_minutes": ..., "backoff": {"<mode>/<book>": {"failures": n,
     "skip_until": iso or null}}}`.
  6. Document the four settings in `.env.example` and README *Configuration*.
- **Tests:** `start_scan_if_idle` returns False while the lock is held; the loop
  calls `run_scan` (monkeypatched) once per tick with `minutes` patched to a tiny
  sleep; back-off counter increments, skips, resets, and caps at the max; a
  manual scan ignores back-off.
- **24-hour run:** set `AUTO_SCAN_PREMATCH_MINUTES=10`,
  `AUTO_SCAN_LIVE_MINUTES=3`, start `python main.py`, and every 2–4 hours log:
  `GET /api/health` (`prematch.last_scan_age_sec`, `live.last_scan_age_sec`,
  `scheduler.backoff`), the server's memory (Windows:
  `Get-Process python | Select-Object Id,WS`; Linux: `ps -o rss= -p <pid>`), and
  the count of `chrome`/`chromium` processes. Memory must not grow by more than
  50 % between hour 2 and hour 24; browser processes must return to 0 between
  scans.
- **Done when:** tests pass and the 24-hour log meets the limits above.
- **Log:** —

#### M4-2 · Telegram notifications

- [ ] **Status:** TODO
- **Needs:** offline; a Telegram bot token and chat id from the operator for the
  final check.
- **Depends on:** M4-1.
- **Files:** `config/settings.py`, new `server/notify.py`, `server/api.py`
  (`run_scan`, `verify_surebet`), `frontend/js/app.js`, `.env.example`, `README.md`,
  new `tests/test_notify.py`.
- **Settings:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (both empty = off),
  `NOTIFY_MIN_PROFIT_PERCENT` (float, default `MIN_PROFIT_PERCENT`),
  `PUBLIC_BASE_URL` (default `http://localhost:{PORT}`).
- **Steps:**
  1. Extract the body of `verify_surebet` (`POST /api/verify`) into
     `async def reverify(surebet: dict, mode: str) -> dict` returning the same
     payload; the endpoint calls it. Behaviour must not change
     (`tests/test_verify_surebet.py` must pass untouched).
  2. Signature of a surebet: `f"{mode}|{market_type}|{home_team}|{away_team}|{kickoff}|"`
     + `",".join(sorted(f"{s.bookmaker}:{s.outcome_label}" for s in stakes))`.
  3. `server/notify.py`: `async def notify_new_surebets(mode, surebets)`. Skip
     if token or chat id is empty. For each surebet with `profit_percent ≥
     NOTIFY_MIN_PROFIT_PERCENT` whose signature is not in
     `cache/notified.json` (signature → ISO time, entries older than 6 h
     dropped on load): call `reverify`; send only if `still_profitable` and
     `meets_min_profit` are both true. Send with
     `httpx.AsyncClient().post(f"https://api.telegram.org/bot{token}/sendMessage",
     json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})`,
     timeout 10 s. Store the signature only after a 200 response. Never raise
     out of this function; log failures.
  4. Text: `"{profit:.2f}% {home} – {away}\n{league}, {kickoff UTC}\n{market}\n"`
     + one line per leg `"{book}: {label} @ {odds}"` + `"\nRe-checked margin:
     {margin}\n{PUBLIC_BASE_URL}/#surebet={id}"`.
  5. Call it at the end of a successful `run_scan` as
     `asyncio.create_task(notify_new_surebets(mode, surebets))` so a slow
     Telegram call never delays the scan.
  6. In `frontend/js/app.js`, on load and on `hashchange`: if `location.hash`
     starts with `#surebet=`, switch to the right mode if needed, and select that
     surebet once results are loaded (if the id no longer exists, show a toast
     "That surebet is gone; showing the latest results").
- **Tests:** no send when off; dedup across two calls; no send when `reverify`
  says not profitable; signature stored only on 200 (mock httpx with
  `httpx.MockTransport`); expired signatures dropped.
- **Final check (needs operator's token):** run one scan with the env set; a
  message must arrive for each qualifying surebet, and a second scan must not
  repeat it.
- **Done when:** tests pass and the final check is logged (or the Log says the
  token was not available).
- **Log:** —

#### M4-3 · Security hardening (re-apply the stash)

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** nothing. Must be done before the server is reachable from any
  other machine.
- **Files:** `config/settings.py`, `main.py`, `server/api.py`, `server/app.py`,
  `frontend/js/app.js`, `.env.example`, `README.md`, tests as needed.
- **Facts:** `git stash list` shows `stash@{0}: On production-hardening: paused:
  security hardening (CSRF guard, same-origin CORS, API key on all endpoints +
  dashboard, XSS escaping, loopback default HOST)`. It was made against an older
  `frontend/js/app.js` and will conflict. Its contents: `HOST` default
  `127.0.0.1`; `CORS_ORIGINS` env (empty = same-origin only, replacing
  `allow_origins=["*"]`); `API_KEY` required on every `/api` route except
  `/api/health`; a CSRF guard in `server/app.py`; frontend `apiFetch()` that
  sends `X-API-Key` from `sessionStorage` and prompts once on 401; `safeUrl()`
  for every rendered `href`; `escapeHtml` on bookmaker names in chips.
- **Steps:**
  1. `git stash show -p "stash@{0}" > <scratch>/security.patch` and read all of
     it.
  2. `git apply --3way <scratch>/security.patch`. Resolve every conflict by
     keeping the current code's features and adding the stash's behaviour. In
     `frontend/js/app.js`, every `fetch('/api/...')` must go through `apiFetch`
     (including the new journal/bankroll calls if M3 is done).
  3. Where the stash's `LOG_LEVEL` line duplicates the current one, keep the
     current one.
  4. Update `.env.example` (`HOST=127.0.0.1`, `CORS_ORIGINS`, `API_KEY` comment)
     and README *Configuration* to match.
  5. Add tests: with `API_KEY` set, `GET /api/results` without the header → 401
     and with it → 200; `GET /api/health` without it → 200; a cross-origin
     `POST /api/scan` with an `Origin` header that is not the server's own →
     refused by the CSRF guard; `HOST` default is `127.0.0.1` (import settings
     with the env var unset via `monkeypatch.delenv` + `importlib.reload`).
  6. Do **not** `git stash drop`. Write in the Log that the operator can drop it.
- **Verify:** §5 S1, then start the server and confirm the dashboard loads and a
  scan starts with `API_KEY` unset and with it set (the prompt appears once).
- **Done when:** S1 green and both manual checks pass.
- **Log:** —

#### M4-4 · Deployment

- [ ] **Status:** TODO
- **Needs:** offline to write; docker to verify.
- **Depends on:** M4-1, M4-3.
- **Files:** new `Dockerfile`, new `docker-compose.yml`, new `.dockerignore`,
  `README.md` (new section *Running persistently*).
- **Steps:**
  1. `Dockerfile`: `FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy` (the
     tag must match `playwright==` in `requirements.txt`; if you change one,
     change both). `WORKDIR /app`, copy `requirements.txt`, `pip install
     --no-cache-dir -r requirements.txt`, copy the repo, `ENV HOST=0.0.0.0
     PORT=8000 HEADLESS=true`, `EXPOSE 8000`, `CMD ["python", "main.py"]`.
  2. `.dockerignore`: `.git`, `.venv`, `venv`, `cache/*.json`, `__pycache__`,
     `.claude`, `tests/fixtures`.
  3. `docker-compose.yml`: one service `scanner`, `build: .`,
     `restart: unless-stopped`, `env_file: .env`, `ports: ["127.0.0.1:8000:8000"]`,
     `volumes: ["./cache:/app/cache"]`, a `healthcheck` that runs
     `python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"`
     every 60 s, and `logging: {driver: json-file, options: {max-size: "10m",
     max-file: "5"}}`.
  4. README *Running persistently*: build/run commands, that `API_KEY` must be set
     before changing the port binding away from `127.0.0.1`, where logs and
     `cache/` live, how to update (`git pull && docker compose up -d --build`).
- **Verify:** `docker compose up -d --build`; `curl http://127.0.0.1:8000/api/health`
  returns `"status": "ok"`; trigger a prematch scan and confirm at least 5 books
  return matches (`/api/health` → `prematch.per_bookie`); `docker compose restart`
  and confirm the cached results come back (within the 30-minute cache TTL).
- **Done when:** the verify steps pass and are logged.
- **Log:** —

---

### M5 — Grow the yield (do not start)

Start none of these until M3-1 has at least 20 settled entries with a positive
total profit. Each needs its own card written first, in the same format as above.

- Asian handicap and first-half markets (`EXPERIMENTAL_MARKETS` in
  `config/settings.py`): need captured fixtures for every book that offers them,
  plus a `price_check.py` run with 0 outliers.
- EVLBet: re-enable only with a captured payload (its feed returned no football
  events for every request tried).
- New bookmakers (MaxBet, Meridianbet): each needs a scraper, registry entries,
  captured fixtures, a deep-link declaration and a price check. MaxBet was done
  on 2026-10-27 at the operator's request; its price check and link proof
  (`scripts/verify_deeplinks.py maxbet`) are still open.
- Live surebets as their own view: only if the M3-2 stats show live legs can be
  placed before the odds move.

---

### Housekeeping

#### H-1 · Delete the unused `orientation_unresolved` reason

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** nothing.
- **Decision (made, do not reopen):** delete it. The gate never emits it; the
  case it was meant for is already reported as `team_unresolved`, and
  `docs/HANDOFF.md` §5.6's alternative (emit it) would turn soft refusals into
  hard rejects.
- **Files and exact edits:**
  1. `engine/certainty.py`: `HARD_REJECT_REASONS = frozenset({"league_mismatch",
     "category_mismatch"})`.
  2. `frontend/js/app.js`: delete the `orientation_unresolved: ...` line from
     `REASON_LABELS`.
  3. `tests/test_frontend_review.py`: delete `"orientation_unresolved",` from
     `KNOWN_REASON_CODES`.
  4. `tests/test_certainty.py`: the assertion
     `assert "orientation_unresolved" not in observed` may stay (still true).
  5. `tests/test_readme_claims.py`: delete the whole function
     `test_dead_hard_reject_vocabulary_is_documented_as_dead` (it asserts the
     dead reason exists). Leave
     `test_vocabulary_check_fails_on_an_invented_and_on_a_dropped_reason` as it
     is: substituting `` `orientation_unresolved` `` still proves the check
     catches an invented reason.
  6. `README.md`, section *Match & mapping certainty*: replace the text from
     "One wrinkle worth knowing:" through "treat `rejected` as the two reasons
     above." with exactly: "The hard-reject reasons are the set
     `HARD_REJECT_REASONS` in `engine/certainty.py`, cited by symbol rather than
     line number, and the gate emits every reason in it." The README must keep
     the token `HARD_REJECT_REASONS` in this section and must not cite
     `engine/certainty.py:<line>`: two other tests in
     `tests/test_readme_claims.py` check both.
  7. `docs/HANDOFF.md` §5 item 6: append "**Resolved 2026-MM-DD: deleted.**"
- **Verify:** `grep -rn orientation_unresolved engine frontend README.md` returns
  nothing; §5 S1.
- **Done when:** S1 green.
- **Log:** —

#### H-2 · Reload `config/bookmaker_deeplinks.json` without a restart

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** nothing.
- **Files:** `scrapers/common.py` (`_load_deeplink_config`), `tests/conftest.py`,
  `server/api.py` (comment in `health`), `README.md` (paragraph under *Run* about
  `deep_link_declarations`), `tests/test_deeplinks.py`.
- **Steps:**
  1. Add a module global `_deeplink_cache_mtime: float | None = None`.
  2. In `_load_deeplink_config`: read `mtime = os.path.getmtime(path)` (on
     `OSError`, `mtime = None`). Reload when `_deeplink_cache is None`, or when
     `_deeplink_cache_mtime is not None and mtime != _deeplink_cache_mtime`. After
     a reload, set `_deeplink_cache_mtime = mtime`. A file that fails to parse
     yields `{}` (unchanged fail-safe: every book then blocks) and logs a
     warning.
  3. `tests/conftest.py`: wherever `_deeplink_cache` is reset or monkeypatched,
     also set `_deeplink_cache_mtime` to `None`, so a test's injected
     declarations are never replaced by the file.
  4. Update the `health` comment and the README paragraph: the map is re-read
     when the file's modification time changes; no restart needed.
- **Tests** (`tests/test_deeplinks.py`): point `_DEEPLINK_CONFIG_PATH` at a
  `tmp_path` file; load; rewrite the file with a different `supports_event_id`
  and a later mtime (`os.utime`); the next call returns the new value; a
  monkeypatched cache with `_deeplink_cache_mtime = None` is not replaced.
- **Verify:** §5 S1. Also update the sentence in `docs/HANDOFF.md` §5 item 8
  that says editing a declaration "needs a process restart" (append
  "**Fixed YYYY-MM-DD: re-read on file change.**").
- **Done when:** S1 green.
- **Log:** —

#### H-3 · Re-check the `supports_event_id: false` notes

- [ ] **Status:** TODO (repeat every 3 months; next due 2027-01-20)
- **Needs:** browser, human judgement.
- **Files:** `config/bookmaker_deeplinks.json` (`note` fields only, unless a book
  gained a route).
- **Steps:** for each of the 8 books declaring `supports_event_id: false`
  (mdshop, admiralbet, wwin, mbet, sportplus, evlbet, premier_kladionica,
  betole): open its football page, click into one match, and look at the
  address bar. If the URL now contains an event id and reloading it opens the
  same match, the book has gained a route: do not flip the flag; write it in the
  Log and stop (it needs a code change and a link check, see
  `scripts/verify_deeplinks.py`). Otherwise prefix the book's `note` with
  `"<YYYY-MM-DD> re-checked: still no per-event route. "`.
- **Verify:** §5 S1.
- **Done when:** all 8 notes carry this round's date.
- **Log:** —

---

## 5. Working rules and procedures

### Rules for every task

* **Python:** use the project virtualenv, `.venv`. Windows:
  `.venv\Scripts\python.exe`; Linux/macOS: `.venv/bin/python`. If it does not
  exist: `python -m venv .venv`, then `pip install -r requirements.txt -r
  requirements-dev.txt` and `python -m playwright install chromium`.
* **Scope:** change only the files the card lists. If you must touch another
  file, say which and why in the Log.
* **Comments and style:** match the surrounding code. Ruff line length is 100.
  Every user-facing claim in `README.md` and this file is tested by
  `tests/test_readme_claims.py`; when a test there fails after your change, fix
  the document (or the test's expectation, if the card says the behaviour
  changed), never the gate.
* **Registry rule:** every new entry in `config/bookmaker_markets.json` needs a
  captured payload under `tests/fixtures/markets/`, and `MARKET_MAPPING.md` must
  be regenerated (`python scripts/generate_market_mapping_doc.py`).
* **Tests touch no network.** Use fakes, `httpx.MockTransport` or fixtures.
* **Dates** in logs and notes: `YYYY-MM-DD`, times in UTC.
* **Before betting anything** (operators, not agents): `POST /api/verify` on the
  card and act only on `still_profitable` and `meets_min_profit` both true.

### S1 · Environment check (the four CI checks)

```bash
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python -m pytest
```

All four must succeed (exit code 0). CI (`.github/workflows/ci.yml`) runs the
same four; frontend tests also need Node 22 on the path.

### S2 · Run a scan and read its numbers

1. Start the server in the background: `python main.py` (it listens on
   `HOST`:`PORT`, default port 8000). Wait until
   `curl http://127.0.0.1:8000/api/health` answers.
2. If `API_KEY` is set in `.env`, add `-H "X-API-Key: <key>"` to every call below.
3. `curl -X POST "http://127.0.0.1:8000/api/scan?mode=prematch"` (or
   `mode=live`). At most 3 scan requests per minute are accepted.
4. Poll `curl "http://127.0.0.1:8000/api/status?mode=prematch"` every 15 s until
   `"is_scanning": false`. A prematch scan takes about 3 minutes.
5. Read and log: `GET /api/results?mode=...` (`total_matches`, `match_groups`,
   `group_statuses`, `surebets_count`) and `GET /api/health`
   (`<mode>.per_bookie`, `<mode>.errors`, `unmapped_markets`).
6. The scan is saved to `cache/last_scan.json` (prematch) or
   `cache/last_live_scan.json` (live); the offline scripts read those files.
7. Stop the server when the task is done.

### S3 · Re-capture market fixtures

`python scripts/capture_market_fixtures.py --books <comma-separated ids>`
rewrites `tests/fixtures/markets/<book>_<mode>.json`. Then run
`python -m pytest tests/test_market_fixtures.py -q`. Never re-capture into
`tests/fixtures/e2e_certified/`.

### S4 · Prove Mozzartbet links

With the server running and a fresh scan in cache: repeat
`curl -X POST "http://127.0.0.1:8000/api/verify-links?bookmaker=mozzartbet&limit=20"`
every 31 s until the response has `"remaining": 0`. CLI alternative (no server):
`python scripts/verify_deeplinks.py mozzartbet --limit 20 --offset <n>` with
`n` = 0, 20, 40, … Verdicts are stored in `cache/deep_link_verifications.json`
and used by the next scan.

### S5 · Record progress

1. In the task card: change `- [ ]` to `- [x]`, set **Status** to
   `DONE YYYY-MM-DD`, and replace `**Log:** —` with 1–5 lines: what changed,
   the measured numbers, anything surprising.
2. If the task is blocked, leave `- [ ]`, set **Status** to `BLOCKED (<reason>)`,
   and log what you tried.
3. Commit only the task's files plus `PLAN.md`, one commit per task, message
   `<type>(<scope>): <summary>` (types used in this repo: `feat`, `fix`,
   `docs`, `chore`, `test`), e.g. `fix(matcher): count NSoft books as one price
   source`. Do not push.
