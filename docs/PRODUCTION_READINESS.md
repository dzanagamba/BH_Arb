# Production readiness assessment — 2026-11-11

> **Supersedes the 2026-11-03 assessment.** Every number below was measured on
> 2026-11-11 with the command named next to it. The same status lives in the
> **Production-readiness checklist** in [`ROADMAP.md`](../ROADMAP.md). SR8-1 is
> still open: Betole live was fixed that day, Mozzartbet live is websocket-only
> and waits on the operator; that gap is carried as **not met**, not averaged
> away. Raw reports and every command:
> [`docs/evidence/2026-11-11-m8-1-scans.md`](evidence/2026-11-11-m8-1-scans.md).

## Verdict

**The prematch pipeline finds and re-verifies real surebets; the product is not
yet safe for unattended betting.** Two state-restored scans on 2026-11-11 found
6,459 prematch matches / 1,283 verified groups / 20 surebets, and 243 live
matches / 19 groups / 0 surebets. The price guard dropped eight prematch
surebets whose leg was a price outlier rather than showing them. Pairing quality
is measured at a 0.28 % strict miss rate with zero groups repeating a bookmaker,
and the cold replay still reaches a fixed point with zero false merges. What is
still missing is live coverage (Mozzartbet), market mapping breadth, leg links
for six of eighteen cells, a defined price-outlier bar, and the multi-day /
24-hour evidence the operator rows would provide.

This is an evidence-based verdict, not a score:

| Area | State | Why it is not production-ready |
|---|---|---|
| Event identity | Good and measured | Ledger, Betradar ids, shared-fixture learning, league fingerprints and shared-opponent blocking exist. `scripts/pairing_audit.py --cache cache/last_scan.json --check` reports a **0.28 %** strict miss rate (18 of 6,459 offers) and zero groups repeating a bookmaker; live reports 0 misses over 243 matches. |
| Market identity | Good | Label classifier + cross-book consensus + generated registry + raw-offer resolver exist. All nine markets are enabled; first-half 1X2 and AH were proven on a real scan with 0 outliers, and first-half O/U is enabled with no current offer and the price guard active. Only the NSoft parser publishes `source_id`; the other scrapers still use the hand-written registry. Every served surebet exposes its exact `raw_margin` and separate exact/realized profit. |
| Human input | Removed | The three write routes are gone; the Diagnostics tab is read-only. The evidence ledger is the only trust source. |
| Freshness | Partial | Runtime TTLs are explicit and `/api/results` reports scan age, TTL, stale books and per-book fetch times. A feed-integrity scorecard quarantines stale, empty, broken-set or high-outlier books from pricing and exposes the reason; recovery needs three clean scans. There is still no last-known-value policy or push/streaming path. |
| Execution | Partial | Stakes are rounded, legs are ordered, the slip re-plans, and every shown surebet is re-checked before placement. Book limits, partial acceptance, balance, and the "price moved between legs" workflow are not complete. |
| Operations | Partial | Scheduler, per-book back-off, a 10-cycle soak that plateaus at ~767 MB, a bounded group-evidence API/dashboard drill-down, request/scan correlation ids, JSON logs and a Prometheus `/api/metrics` endpoint exist. Docker Compose and a hardened systemd unit are shipped. The structural-drift alarm was reduced from 225 to 23 lines per prematch scan (SR8-2), so a real shape change is visible again. No 24 h soak and no health budget for mapping coverage. |
| Security | Good | Loopback by default, same-origin CORS, an all-route API-key guard, a CSRF guard, URL-scheme checks and CSP/anti-framing headers are in place; the dashboard prompts once. Script execution is nonce-gated and styles are CSSOM/class-based, so neither `script-src` nor `style-src` admits `'unsafe-inline'`. CI enforces a **87.05 %** branch-coverage floor (measured 88.05 %), a clean `pip-audit` on runtime and dev requirements, and Bandit at medium severity and above. |
| Evaluation | Partial | Deterministic replay, a cold-start fixed point, a repeatable pairing audit and real scans exist. Opportunity-rate and crossing-lifetime telemetry report the denominator and a zero-result reason per scan. No local 7-day baseline, labelled multi-day corpus, precision/recall, or CLV/backtest yet. |

The honest summary: **the engine can prove a match and price it on real data
without false merges; the product cannot yet prove that it sees enough of the
market, often enough, to be relied on.**

## Measured on real data (2026-11-11)

Both scans restored the persisted runtime state first (`scripts/record_scan.py`,
SR8-4). No login, no bet, nothing submitted.

| Run | Command | Matches | Books | Verified groups | Price comparisons | Outliers | Surebets |
|---|---|---:|---:|---:|---:|---:|---:|
| Prematch | `python scripts/record_scan.py prematch --out …` | 6,459 | 9/9 enabled | 1,283 | 5,795 | 21 | 20 |
| Live | `python scripts/record_scan.py live --out …` | 243 | 8/9 enabled | 19 | 34 | 0 | 0 |

The prematch scan's only error line is
`8 surebet(s) dropped: a leg was a price outlier`; the live scan's is
`Mozzartbet: returned no matches` (SR8-1). Betole live reported 75 matches in
the live run (fixed that day, was `empty`). EVLBet is disabled.

### Pairing coverage on those scans

`python scripts/pairing_audit.py --cache cache/last_scan.json --check` exit 0;
the live cache was audited without `--check`.

| Metric | Prematch | Live |
|---|---:|---:|
| Matches | 6,459 | 243 |
| Verified multi-book groups | 1,283 | 19 |
| Ungrouped listings | 1,008 | 178 |
| Duplicate listings from a book already in the group | 0 groups | 0 groups |
| Strict misses | 18 | 0 |
| Strict miss rate | **0.28 %** | **0.0 %** |

The remaining strict misses are abbreviations and city-qualified spellings; the
examples are printed by the audit. This is still one feed snapshot, not several
days: the multi-day baseline is N2-4, deferred to the operator.

### Market mapping

Printed by the scans:

| Mode | Mapped rows | Published rows | Share | Floor |
|---|---:|---:|---:|---:|
| Prematch | 45,268 | 589,502 | 7.7 % | 0.95 |
| Live | 1,288 | 50,477 | 2.6 % | 0.95 |

The denominator is dominated by unregistered full-offer markets (the Betole
`by-ids` long tail), so the warning fires on every scan and no longer separates
a regression from the known gap. **SR8-3 is gated on the operator** deciding how
mapping coverage is measured; the floor was not lowered.

### Price check

`python scripts/price_check.py` (exit 1 by design on an outlier) and
`python scripts/price_check.py --live` (exit 0):

| Mode | Verified groups | Market comparisons | Outliers | Rate |
|---|---:|---:|---:|---:|
| Prematch | 1,283 | 5,795 | 21 | 0.36 % |
| Live | 19 | 34 | 0 | 0 % |

The outliers are concentrated in a few fixtures (`torque – racing club`,
`malawi – egypt`, `al ahly amman – dar al dawa`, `ajax – thun`), which reads as
a wrong or stale leg rather than 21 independent errors. The price guard already
drops a surebet with an outlier leg: eight were dropped in this scan. Whether
criterion 4 should be "0 outliers" or a rate is a proposal for the operator
below; **nothing was changed in the guard**.

### Verified surebet sample (2026-11-11 20:52 UTC)

| Match | Market | Profit | Books |
|---|---|---|---|
| botswana – uganda | double chance | 6.20 % | betole 2 @ 1.82 / maxbet 1X @ 2.55 |
| niger – morocco | BTTS | 5.57 % | betole GG @ 5.90 / maxbet NG @ 1.29 |
| angola – south sudan | BTTS | 3.17 % | maxbet GG @ 5.00 / sportplus NG @ 1.30 |
| gl rangers – aberdeen | BTTS | 2.44 % | betole GG @ 2.10 / maxbet NG @ 2.00 |
| malawi – egypt | 1X2 | 2.17 % | sportplus 1 @ 10.0 / maxbet X @ 8.25 / betole 2 @ 1.32 |

The 20 surebets came from seven books (maxbet 17 legs, betole 10, sportplus 5,
premier 3, mdshop/mozzartbet/wwin 2 each). The live scan served none; with 19
verified groups and 34 comparisons that is a small sample, not a defect.

### Cold replay

`python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold
--check` exit 0: `fixed_point: true`, `false_merges: 0`,
`pairs_unresolved: 0`, 3 pairs (1 verified), 2 iterations, 18/18 market rows
mapped.

## What the research says

### How the mature products work

* **OddsJam / OpticOdds** scan 100+ books and advertise over a million odds
  updates per second. Their arbitrage windows are described as lasting under
  ~90 seconds, and live prices move much faster than pre-match. The API overview
  distinguishes polling from **push** delivery and says push is what serious
  arbitrage/live applications need; a scanner that polls once a minute mostly
  surfaces prices that are already gone. ([OddsJam tools](https://oddsjam.com/betting-tools),
  [API overview](https://www.surebets.bet/blog/harnessing-the-power-an-overview-of-the-oddsjam-api/16192909))
* **SharpAPI / UK Odds API** normalize books into one schema, pre-match events
  across books, and warn that stale odds and event-matching errors are the two
  main sources of phantom arbs. Pre-match polling every 30–60 s is often enough;
  sub-10 s is live territory. ([SharpAPI arbitrage guide](https://sharpapi.io/use-cases/arbitrage-scanner),
  [UK Odds API architecture](https://ukoddsapi.com/blog/arbitrage-bot-architecture))
* **Dozor's 27-book entity-resolution write-up** is the closest match to this
  repo's problem. Its rules are directly applicable:
  - normalize names, but keep `academy`, `junior`, `youth`, `women` and digits —
    they identify a different roster;
  - remove only organisation noise (`gaming`, `team`, `club`, `esports`);
  - time slots are anchored, not chained; use the nearest compatible slot;
  - **find splits by a shared opponent, not by similar names** — "NAVI" vs
    "Natus Vincere" is 18% similar but the same team, while "Evil Geniuses" vs
    "Evil Geniuses GC" is 81% similar and a different roster;
  - an initialism matches only if one side is the initials of every token on the
    other; a differing marker is a veto; a one-sided addition is vetoed;
  - auto-write rules only with strong non-spelling evidence, a tight start-time
    window (90% of real matches start within 5 minutes), a meaningful tournament
    token, at least two independent feed groups on each side, and a write cap.
  ([Dozor article](https://dev.to/dozor/matching-the-same-esports-match-across-27-bookmakers-entity-resolution-in-go-2dg5))
* **Entity-resolution practice** is consistent: normalize hard, block on cheap
  keys (sport, date, league, team), score candidates, cluster transitively with a
  contradiction policy, and keep provenance. A false merge is worse than a split.
  ([blocking guide](https://fuzzy.direct/blocking-strategies-for-entity-resolution),
  [dedupe.dev](https://dedupe.dev/guides/entity-resolution))

### What this repo now does about it

* `engine/name_identity.py` implements the production identity rules: org-token
  removal, marker/colour vetoes, initialism matching, and a token-set/ratio score
  without the over-permissive partial ratio.
* `engine/matcher.py` uses those rules in candidate scoring, indexes groups by
  exact team key (shared-opponent lookup), and consults ledger league
  equivalences in the league gate.
* `engine/mapping_learner.py` learns only within a **5-minute** alias window,
  accepts a shared Betradar id or a one-exact-slot shared fixture, quarantines
  similarity-only pairs, and rejects opponent contradictions.
* `engine/team_resolver.py` splits transitive alias chains at the weakest edge
  when two clubs are listed as opponents.
* `engine/league_resolver.py` resolves an ambiguous league name per fixture by
  team-set fingerprints.
* `scripts/replay_mappings.py --cold` learns from an empty ledger and reaches a
  fixed point; `--check` fails on a false merge or an unresolved evidence-backed
  pair.
* The learner now runs **inside a real scan**, before the matcher, so the
  aliases proved by that scan's own fixtures are available in the same pass.
  `MIN_LEARN_MATCHES` keeps test/smoke scans from rewriting the shipped ledger.

## Production blockers, in priority order

1. **Live coverage.** Mozzartbet live is available only over Socket.IO; the HTTP
   list the adapter reads has no in-play events. SR8-1 carries the dated proof
   and waits on the operator (collector, its own row, or accepted limitation).
   Betole live is fixed.
2. **Market mapping breadth.** 7.7 % of prematch rows and 2.6 % of live rows are
   mapped against a 0.95 floor. The gap is the unregistered full-offer long
   tail; SR8-3 is gated on how coverage is measured. A low coverage number is a
   finding, not a threshold to lower.
3. **Leg links.** Six of eighteen book/mode cells still open a generic page:
   SportPlus (2), Premier Kladionica (2), Mozzartbet live, Betole live. The
   remaining 6 ticket-filled and 6 match-page cells are dated and confirmed in
   `config/bookmaker_destinations.json`; every served surebet shows its per-leg
   reach and can be checked on demand (SR9-3).
4. **Prove coverage over time.** Today's audit is one snapshot (0.28 % strict
   miss rate, zero duplicate-book groups). Several days of scans and the 18
   remaining strict misses need the deferred N2-4 baseline.
5. **Define the price-outlier bar.** 21 outliers over 5,795 comparisons (0.36 %),
   concentrated in a few fixtures, with the guard already dropping their
   surebets. Criterion 4 below proposes a definition; it is not applied.
6. **Operate and soak it.** No 24 h soak and no mapping-coverage health budget;
   P1-6 is waived and conflicts with criterion 8. Scheduler, back-off, alerting
   and a 10-cycle plateau exist.
7. **Finish execution and evaluation.** Book limits, partial acceptance, the
   "price moved" workflow, a re-check immediately before placement, a local
   7-day baseline, precision/recall on a labelled corpus and CLV/backtest are
   still missing.

## Where each number comes from

| Number(s) | Source and command |
|---|---|
| Scan, pairing, price, mapping, drift and replay figures above | `docs/evidence/2026-11-11-m8-1-scans.md` (commands and raw JSON in the same folder) |
| 2,453 tests, ruff, mypy | `python -m pytest`; `python -m ruff check .`; `python -m mypy .` (2026-11-11) |
| 87.05 % floor, 88.05 % measured | `pyproject.toml` `[tool.coverage.report] fail_under`; `docs/CI.md` |
| ~767 MB 10-cycle plateau | `docs/evidence/2026-11-04-soak-smoke.json` |
| 6 / 6 / 6 leg-link cells | `config/bookmaker_destinations.json` (confirmed proofs only), `docs/evidence/2026-11-11-sr9-2.md` |
| 225 → 23 drift lines | SR8-2 execution-log row in `ROADMAP.md` |

## What would make it production-ready

A single recorded run that satisfies all of the following:

* a real headless prematch scan returns matches for every configured book that
  publishes football;
* `scripts/pairing_audit.py --check` stays under a 2 % strict miss rate across
  several days, with zero groups repeating a bookmaker;
* every published market row is mapped or has a dated absence proof;
* `price_check.py` reports 0 outliers over a meaningful comparison count;
* the cold-start replay reaches a fixed point with 0 false merges and 0
  unresolved evidence-backed pairs;
* the certified end-to-end test still removes a surebet when a claim is spoiled;
* no endpoint, config file or UI action can change trust;
* a 24 h soak shows no memory/browser growth and no stale-book blindness;
* the security hardening is applied and the server is not exposed without a key.

**Proposed definition for criterion 4 (for the operator; not applied).** Replace
"0 outliers" with: *zero outlier legs on any served surebet in both modes, and at
most 0.10 % of market comparisons flagged (at the current 0.10 probability-gap
threshold) with at least 1,000 comparisons in each mode.* Today that reads
21 / 5,795 = 0.36 % prematch (fails the rate) and 0 / 34 live (too small to
count); the guard dropped all eight affected surebets.

**Criteria 2 and 8 need the operator.** Criterion 2 ("several days") needs N2-4,
deferred; criterion 8 (24 h soak) needs P1-6, waived. The waiver and the
criterion conflict, so the product cannot be declared production-ready while
either stands.

Until then the correct description is **a strong research and correctness
platform with a working prematch pipeline, not a production betting product.**
