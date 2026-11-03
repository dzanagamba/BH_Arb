# Production readiness assessment — 2026-11-03

## Verdict

**The prematch pipeline now finds and re-verifies real surebets; the product is
not yet safe for unattended betting.** On 2026-11-03 a real scan found five
surebets after a price-outlier guard dropped a sixth, and all five re-verified as
still profitable on a fresh scrape. The remaining gaps are execution, operations,
market breadth and security, not the core match/price engine.

This is an evidence-based verdict, not a score:

| Area | State | Why it is not production-ready |
|---|---|---|
| Event identity | Good and improving | Ledger, Betradar ids, shared-fixture learning, league fingerprints and shared-opponent blocking exist. No real-scan precision/recall measurement yet. |
| Market identity | Good | Label classifier + cross-book consensus + generated registry + raw-offer resolver exist. Eight of nine markets are enabled; first-half 1X2 and AH were proven on a real scan with 0 outliers. Only the NSoft parser publishes `source_id`; the other scrapers still use the hand-written registry. First-half O/U has no captured offer. |
| Human input | Removed | The three write routes are gone; the Diagnostics tab is read-only. The evidence ledger is the only trust source. |
| Freshness | Partial | The engine has odds TTL and every shown surebet is re-verified; there is still no per-book freshness budget, no last-known-value policy, and no push/streaming path. |
| Execution | Partial | Stakes are rounded, legs are ordered, the slip re-plans, and every shown surebet is re-checked before placement. Book limits, partial acceptance, balance, and the "price moved between legs" workflow are not complete. |
| Operations | Missing | No scheduler/back-off, no alerting, no 24 h soak, no deployment, no health budget for mapping coverage. |
| Security | Good | Loopback by default, same-origin CORS, and a single guard requires the API key on every `/api` route except `/api/health`; the dashboard prompts once. A CSRF guard and a full XSS sweep remain from the paused stash. |
| Evaluation | Partial | Deterministic replay, a cold-start fixed point and two real scans exist. No large multi-scan corpus, no labelled precision/recall, no CLV/backtest. |

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

The scan is a direct measurement of the naming problem:

| Ground truth | Fixtures | Grouped | Missed | Miss rate |
|---|---|---|---|---|
| Same non-empty Betradar id on >1 book | 736 | 711 | 25 | 3.4% |
| Identical raw teams + kickoff on >1 book | 1,032 | 986 | 46 | 4.5% |

The missed Betradar cases are almost all MaxBet, whose groups stay unverified
until its per-event link is proven; the missed exact-fixture cases are MaxBet,
Mozzartbet and the MDShop/Admiralbet pair, which is one NSoft price source and is
correctly not treated as two books. This is the strongest evidence so far that
the ledger, shared-opponent blocking and league fingerprints are doing the job.

### First real surebets (2026-11-03 03:24 UTC)

| Match | Market | Profit | Books | Re-verified |
|---|---|---|---|---|
| kanazawa – parceiro n | 1X2 | 7.59% | mdshop / sportplus / mozzartbet | yes, unchanged |
| kanazawa – parceiro n | 1X2 + DC | 5.96% | mdshop / mozzartbet | yes, unchanged |
| nara – kusatsu | O/U 2.5 | 3.94% | mbet / mozzartbet | yes, unchanged |
| nara – kusatsu | BTTS | 1.69% | wwin / mozzartbet | yes, unchanged |
| anaitasuna ft – alaves | BTTS | 1.69% | betole / maxbet | yes, unchanged |
| fulham – newcastle | 1X2 | 0.49% (dust) | sportplus / mozzartbet / maxbet | yes, unchanged |
| atl madrid – bayern munich | draw / not-draw | 0.42% (dust) | mdshop / mozzartbet | yes, unchanged |
| roma – sassuolo | home / not-home | 0.42% (dust) | mbet / mozzartbet | yes, unchanged |

The 9-book scan had 6,503 matches, 1,039 verified groups, 5,754 grouped
listings, 4,481 price comparisons, 0 false merges and 3 price outliers. The outlier was the
`boston utd – leicester u21` MaxBet X2 leg; the price guard dropped that surebet
instead of showing it. The five above passed the guard and `POST /api/verify`
returned `still_profitable: true` for every one, with unchanged odds.

This is the first end-to-end evidence that the product can do the job it exists
for. The route-pattern proof for MaxBet/Mozzartbet and enabling Betole were the
coverage unlocks: grouped listings rose from 3,645 to 5,683. Betole also carries
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
2. **Prove coverage on real data.** Run a headless prematch scan on a day with
   real fixtures, record per-book counts, verified groups, mapping coverage and
   `price_check.py` outliers, and add the scan to the replay corpus. The current
   corpus is three matches; it cannot prove production coverage.
3. **Finish market coverage.** Publish `source_id` from every parser, run
   discovery on captured payloads, and generate the registry. Prove first-half
   and AH rows with captures and consensus; record absence for markets a book
   does not offer.
4. **Add freshness and execution policy.** Per-book staleness budgets, last-known
   value, a re-check immediately before placement, stake limits, partial
   acceptance, and a clear "price moved" state. Pre-match 30–60 s polling is the
   baseline; live needs a push or sub-10 s path.
5. **Operate it.** Scheduler with per-book back-off, 24 h soak, memory/browser
   leak checks, health/alerting on mapping coverage and stale books, and a
   documented persistent deployment.
6. **Harden it.** Loopback, same-origin CORS and the all-route API key guard are
   in place; apply the remaining stash items: CSRF guard and the XSS sweep.
7. **Measure quality.** Precision/recall on a labelled corpus, false-merge rate,
   mapping coverage, price-check outliers, CLV/backtest once real bets are
   recorded. A low coverage number is a finding, not a threshold to lower.

## What would make it production-ready

A single recorded run that satisfies all of the following:

* a real headless prematch scan returns matches for every configured book that
  publishes football;
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
