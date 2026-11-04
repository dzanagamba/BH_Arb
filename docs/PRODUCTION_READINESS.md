# Production readiness assessment — 2026-11-03

## Verdict

**The prematch pipeline now finds and re-verifies real surebets; the product is
not yet safe for unattended betting.** On 2026-11-03 the latest nine-book scan
found nine surebets after the price guard dropped three outlier legs. Seven
re-verified as still profitable on a fresh scrape; two disappeared before the
re-check and are reported as gone rather than as confirmed arbs. The core
match/price engine now has a measured pairing quality (0.6% strict miss rate);
the remaining gaps are execution, operations, market breadth and security.

This is an evidence-based verdict, not a score:

| Area | State | Why it is not production-ready |
|---|---|---|
| Event identity | Good and measured | Ledger, Betradar ids, shared-fixture learning, league fingerprints and shared-opponent blocking exist. `scripts/pairing_audit.py` measures a 0.33% strict miss rate (22 of 6,624 offers) and zero groups repeating a bookmaker. |
| Market identity | Good | Label classifier + cross-book consensus + generated registry + raw-offer resolver exist. All nine markets are enabled; first-half 1X2 and AH were proven on a real scan with 0 outliers, and first-half O/U is enabled with no current offer and the price guard active. Only the NSoft parser publishes `source_id`; the other scrapers still use the hand-written registry. |
| Human input | Removed | The three write routes are gone; the Diagnostics tab is read-only. The evidence ledger is the only trust source. |
| Freshness | Partial | Runtime TTLs are explicit and `/api/results` reports scan age, TTL, stale books and per-book fetch times. A feed-integrity scorecard now quarantines stale, empty, broken-set or high-outlier books from pricing and exposes the reason; recovery needs three clean scans. There is still no last-known-value policy or push/streaming path. |
| Execution | Partial | Stakes are rounded, legs are ordered, the slip re-plans, and every shown surebet is re-checked before placement. Book limits, partial acceptance, balance, and the "price moved between legs" workflow are not complete. |
| Operations | Partial | Scheduler, per-book back-off, a 10-cycle soak that plateaus at ~767 MB, and a bounded group-evidence API/dashboard drill-down exist; no alerting, no 24 h soak, no deployment, no health budget for mapping coverage. |
| Security | Good | Loopback by default, same-origin CORS, an all-route API-key guard, a CSRF guard, URL-scheme checks and CSP/anti-framing headers are in place; the dashboard prompts once. Script execution is nonce-gated with no `script-src 'unsafe-inline'`; inline styles remain the documented CSP gap. |
| Evaluation | Partial | Deterministic replay, a cold-start fixed point, a repeatable pairing audit and real scans exist. Opportunity-rate and crossing-lifetime telemetry now report the denominator and a zero-result reason per scan. No local 7-day baseline, labelled multi-day corpus, precision/recall, or CLV/backtest yet. |

The honest summary: **the engine can prove a match and price it on real data
without false merges or price outliers; the product cannot yet prove that it
sees enough of the market, often enough, to be relied on.**

## Measured on real data (2026-11-03)

Two headless prematch scans were run against the live books, not fixtures.

| Run | Matches | Books | Verified groups | Grouped listings | Price comparisons | Outliers | False merges | Surebets |
|---|---|---|---|---|---|---|---|---|
| Baseline (legacy mappings) | 5,285 | 8/8 enabled | 811 | 3,536 | 3,526 | 0 | 0 | 0 |
| With learned ledger | 5,287 | 8/8 enabled | 797 | 3,645 | 3,704 | 0 | 0 | 0 |
| With in-scan learning | 5,276 | 8/8 enabled | 796 | 3,644 | 3,698 | 0 | 0 | 0 |
| With Betole enabled | 6,503 | 9/9 enabled | 1,039 | 5,754 | 4,481 | 3 | 0 | 8 |
| Latest gate + pairing audit | 6,624 | 9/9 enabled | 1,074 | 5,987 | — | 3 | 0 | 11 |

The learned ledger was produced by `scripts/learn_mappings.py` from the first
scan: 1,795 accepted claims and 866 quarantined. The second scan grouped 109
more listings into 14 fewer groups, with zero groups holding two different
Betradar ids and zero price outliers. The third scan ran the learner **inside**
the scan: 1,851 unique accepted claims, 815 quarantined, 796 groups, 3,644
grouped listings, 3,698 comparisons, 0 outliers and 0 false merges. The best
available margin was 1.0021 (0.21% loss), so zero surebets was the correct
answer, not a failure.

This is meaningful evidence for correctness. It is **not** evidence of coverage:
1,221 listings still had an unproven per-event link (MaxBet and Mozzartbet), and
8,618 candidate pairs remained unresolved. Both books' routes were verified on
samples (`scripts/verify_deeplinks.py`), so a full link sweep is the next
coverage lever.

### Pairing coverage on that scan

`python scripts/pairing_audit.py --check` reads the same cache the dashboard
serves. A strict miss is an ungrouped offer that has another book's listing of
the same fixture: same league (or a country-qualified spelling of it), kickoff
within 15 minutes, and both team names at least 80% alike.

| Metric | Value |
|---|---:|
| Matches | 6,624 |
| Verified multi-book groups | 1,074 |
| Listings in groups | 5,987 |
| Ungrouped listings | 637 |
| Duplicate listings from a book already in the group | 305 |
| Strict misses | 22 |
| Strict miss rate | **0.33%** |
| Groups repeating a bookmaker | 0 |

The 348 duplicate listings are the main reason Betole (75.1%) and Mozzartbet
(73.6%) have lower per-book grouping rates: both publish several listings for
the same fixture, and only one can enter a group. The remaining strict misses
are abbreviations and city-qualified spellings such as `Qingdao H` /
`Qingdao Hainiu`, `Dynamo D` / `Dynamo Dresden`, and `Central Coast (W)` /
`Central Coast Mariners (W)`.

This is the strongest evidence so far that the ledger, shared-opponent blocking
and league fingerprints are doing the job. The gate fixes that produced it are
recorded in `docs/ACCEPTANCE.md`: the anchor is no longer treated as the whole
group, any supporting member can prove a team, club designators are not
aliases, and generic league names get team-set fingerprints.

### Verified surebet sample (2026-11-03 04:39 UTC)

| Match | Market | Profit | Books | Re-check |
|---|---|---|---|---|
| kanazawa – parceiro n | double chance | 8.28% | mdshop / mozzartbet | not found on fresh data |
| anaitasuna ft – alaves | BTTS | 1.69% | betole / maxbet | still profitable |
| boston united – leicester u21 | double chance | 1.52% | sportplus / wwin | not found on fresh data |
| villarreal – psg | 1X2 | 1.20% | mdshop / mozzartbet / wwin | still profitable |
| tochigi – fukushima | double chance | 0.51% | mdshop / mozzartbet | still profitable |
| bodo/glimt – lille | double chance | 0.49% | betole / maxbet | still profitable |
| atl madrid – bayern munich | double chance | 0.42% | mdshop / mozzartbet | still profitable |
| roma – sassuolo | double chance | 0.42% | mbet / mozzartbet | still profitable |
| tochigi – fukushima | 1X2 | 0.33% | mdshop / mozzartbet | still profitable |

The 04:39 sample had 6,492 matches, 1,043 verified groups, 5,805 grouped
listings, 0 false merges and 3 price-outlier legs. The price guard dropped the
Kitakyushu–Reilac Shiga (MaxBet X2, SportPlus 1) and Kanazawa–Parceiro N
(SportPlus 1) legs instead of showing those arbs. Seven of the nine shown
re-verified with `still_profitable: true`; the two that disappeared before the
re-check are reported as gone. The latest 07:54 scan found 6,624 matches, 1,074 groups and 11 surebets.
Pairing quality is exposed in `/api/health` and `/api/results`. The 06:30
verified sample's 10 surebets: eight re-verified at a fresh price and the two
Boston United–Leicester U21 legs were gone and are reported as gone.

The route-pattern proof for MaxBet/Mozzartbet and enabling Betole were the
coverage unlocks: grouped listings rose from 3,645 to 5,805. Betole also carries
a Betradar match id, which its scraper now keeps; its kickoff field was never
read before 2026-11-03.

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

1. **Human write path.** Removed: the routes are gone and the Diagnostics view
   is read-only. The direct migration functions remain only for legacy tests.
2. **Prove coverage over time.** One scan now has a measured 0.33% strict miss
   rate and zero duplicate-book groups. Add several days of scans to the replay
   corpus so the number is not one feed snapshot, and track the 22 remaining
   abbreviation/city-qualified pairs until they are learned or explained.
3. **Finish market coverage.** Publish `source_id` from every parser, run
   discovery on captured payloads, and generate the registry. Prove first-half
   and AH rows with captures and consensus; record absence for markets a book
   does not offer.
4. **Finish freshness and execution policy.** Runtime and per-book staleness
   budgets, the stale banner and action-gating are in place. Still missing:
   last-known value, a re-check immediately before placement, stake limits,
   partial acceptance, and a clear "price moved" state. Pre-match 30–60 s polling
   is the baseline; live needs a push or sub-10 s path.
5. **Operate it.** Scheduler with per-book back-off, 24 h soak, memory/browser
   leak checks, health/alerting on mapping coverage and stale books, and a
   documented persistent deployment.
6. **Harden it.** Loopback, same-origin CORS, the all-route API key guard, the
   CSRF guard and URL-scheme checks are in place; finish the XSS sweep from the
   stash.
7. **Measure quality.** The pairing audit now reports strict miss rate,
   false-merge rate and duplicate-book groups on every scan. Still missing:
   precision/recall on a labelled multi-day corpus, mapping coverage trends and
   CLV/backtest once real bets are recorded. A low coverage number is a finding,
   not a threshold to lower.

## What would make it production-ready

A single recorded run that satisfies all of the following:

* a real headless prematch scan returns matches for every configured book that
  publishes football;
* `scripts/pairing_audit.py --check` stays under a 2% strict miss rate across
  several days, with zero groups repeating a bookmaker;
* every published market row is mapped or has a dated absence proof;
* `price_check.py` reports 0 outliers over a meaningful comparison count;
* the cold-start replay reaches a fixed point with 0 false merges and 0
  unresolved evidence-backed pairs;
* the certified end-to-end test still removes a surebet when a claim is spoiled;
* no endpoint, config file or UI action can change trust;
* a 24 h soak shows no memory/browser growth and no stale-book blindness;
* the security hardening is applied and the server is not exposed without a key.

Until then, the correct description is **a strong research and correctness
platform with a working prematch pipeline, not a production betting product.**
