# Multi-sport / multi-market evidence — 2026-11-04

This is the dated evidence record for the expansion of BH_Arb from a football-only
scanner into a multi-sport, multi-market scanner. Every number below came from a
live feed or a reproducible script; nothing was chosen by preference.

## 1. What was measured, and how

`scripts/measure_sports.py` reads the real prematch endpoints for the nine enabled
books and counts, per sport, the events and the *comparable* full-match market
families (moneyline, handicap, total). The admissibility rule was fixed before
the measurement:

> A sport is admissible only when at least three of the nine enabled books publish
> at least three comparable full-match families **with the same settlement**.

The raw report is `docs/evidence/2026-11-04-sport-discovery.json`.

### Measurement result (prematch, 2026-11-04)

| Sport | Qualifying books | Result |
| --- | --- | --- |
| Basketball | sportplus, mbet, mdshop, admiralbet | **admissible** |
| Tennis | sportplus, mbet, mdshop, admiralbet, maxbet | **admissible** |
| Ice hockey | sportplus, mbet (only two) | not admissible |

Per-book market counts from that run:

| Sport | Book | Matches | Markets seen | Comparable families |
| --- | --- | ---: | --- | ---: |
| Basketball | sportplus | 76 | moneyline, handicap, total | 3 |
| Basketball | mbet | 90 | moneyline, handicap, total | 3 |
| Basketball | mdshop | 103 | moneyline, handicap, total | 3 |
| Basketball | admiralbet | 103 | moneyline, handicap, total | 3 |
| Basketball | maxbet | 32 | moneyline, total (no handicap in this window) | 2 |
| Tennis | sportplus | 96 | moneyline, handicap, total | 3 |
| Tennis | mbet | 188 | moneyline, handicap, total | 3 |
| Tennis | mdshop | 184 | moneyline, handicap, total | 3 |
| Tennis | admiralbet | 184 | moneyline, handicap, total | 3 |
| Tennis | maxbet | 324 | moneyline, handicap, total | 3 |
| Ice hockey | sportplus | 53 | moneyline, handicap, total | 3 |
| Ice hockey | mbet | 55 | moneyline, handicap, total | 3 |
| Ice hockey | mdshop+admiralbet | 21 | moneyline, total | 2 |
| Ice hockey | maxbet | 20 | moneyline, handicap | 2 |

### Ice hockey: exact blocking evidence

- **mdshop + admiralbet (NSoft)**: IDs 135 (3-way regulation) and 137 (match
  goals) are served; no full-match handicap ID was observed in the measured
  window. Two comparable families, not three.
- **maxbet**: IDs 1 (3-way) and 16 (handicap) are regular time; the only total
  offered was ID 212, *including overtime*. Pairing that with a regular-time total
  would price a different bet, so it is not counted.
- **sportplus** and **mbet** each publish three regular-time families, but only
  two books reach the threshold. Lowering the requirement to two books, or
  treating the incl-OT total as comparable, would weaken the gate. Ice hockey is
  therefore **left unimplemented** and recorded here rather than guessed.

### Books not measured for non-football

| Book | Blocking evidence |
| --- | --- |
| premier_kladionica | The event rows expose a sport id, but the `setTip` market rows use a different sport dimension; no non-football mapping was proven, so none was admitted. |
| mozzartbet | Cloudflare browser session required; the non-football sport id map was not proven from a captured payload. |
| wwin | The event endpoint needs a browser session; unauthenticated probes return an empty body, so sport/market ids are unproven. |
| betole | The desk feed is football-only: every event carries `sport: "S"`. |
| evlbet | Disabled in `config/settings.py`; its football API already returns no events. |

## 2. Implemented sports and market semantics

| Sport | Market | Outcome labels | Line | Settlement used | Period |
| --- | --- | --- | --- | --- | --- |
| Basketball | moneyline | `1`, `2` | none | `full_time_incl_ot` | full game |
| Basketball | handicap | `1 <home line>`, `2 <away line>` | signed, half-point | `regulation` | full game, regulation |
| Basketball | total | `Over <points>`, `Under <points>` | half-point | `regulation` | full game, regulation |
| Tennis | moneyline | `1`, `2` | none | `full_match` | full match |
| Tennis | handicap | `1 <home games>`, `2 <away games>` | signed games | `full_match` | full match |
| Tennis | total | `Over <games>`, `Under <games>` | half-point games | `full_match` | full match |

Settlement is part of market identity. The engine groups legs by settlement and
refuses to pair `regulation` with `full_time_incl_ot`; that is a different bet
even when both labels read `Over 221.5`.

### Per-book mapping provenance (measured 2026-11-04)

- **sportplus**: basketball `POBJEDNIK` (incl. OT), `HENDIKEP` (line in the
  competitors suffix, home line = negation), `ZBROJ KOŠEVA` (regular time);
  tennis `Osnovno`, `HENDIKEP GEMOVA`, `ZBROJ GEMOVA`.
- **mbet**: basketball `obb:fsot` (winner incl. OT), `obb:hc:H1|line` /
  `H2|line`, `obb:p:(+)|line` / `(-)`; tennis `otn:fs`, `otn:hg:1|line` /
  `2|line`, `otn:g:(+)|line` / `(-)`.
- **mdshop (NSoft)**: basketball 186 / 191 / 213; tennis 1723 / 220 / 187.
  ID 210 on tennis is a **set** handicap (±1.5 sets) and was rejected by price
  consensus as a game handicap.
- **admiralbet (NSoft)**: same as mdshop except the basketball winner is ID 1640.
- **maxbet**: basketball 175 / 16 / 224; tennis 175 / 176 / 178. ID 224 is the
  regular-time points total; 212 is incl. OT and is not used for basketball.

### Cross-book non-merge

Every listing carries `sport`; the certainty gate rejects a pair whose sports
differ (`sport_mismatch`) before any name, league or provider-id proof, and the
matcher buckets candidates by `(sport, league/date/team)`. A test feeds two
books' identical football names and two books' identical basketball names and
asserts two separate groups and no cross-sport member.

## 3. Football markets added beyond the nine MarketTypes

Three complete, two-way football lines were admitted from live offers:

| Market | Rows measured | Books (price sources) | Label/structure classification | Cross-book consensus |
| --- | ---: | --- | --- | --- |
| `over_under_0_5` | 961 | maxbet, nsoft (mdshop+admiralbet), premier_kladionica, wwin | 961/961 classified | 0 outliers |
| `over_under_4_5` | 3,827 | maxbet, mbet, nsoft, premier_kladionica, wwin | 3,827/3,827 classified | 0 outliers |
| `over_under_5_5` | 2,452 | maxbet, mbet, nsoft, premier_kladionica, wwin | 2,452/2,452 classified | 0 outliers |

`docs/evidence/2026-11-04-football-lines.json` records the run: 4,611 matches,
1,009 groups, 5,140 market rows compared by the devigged median test, **0 price
outliers**. Each line is a complete Over/Under partition and prices with the same
equation as the existing 1.5/2.5/3.5 lines. No existing line's parser or label set
was changed.

The same run covers every book that actually publishes the line:

| Book | 0.5 | 4.5 | 5.5 | Evidence |
| --- | --- | --- | --- | --- |
| maxbet | yes | yes | yes | `specifiers.total` on odd type 17; browser-checked in §3.1 |
| mdshop / admiralbet (NSoft) | yes | yes | yes | bet type 137/22, `sbv` line; prematch and live |
| wwin | yes | yes | yes | `spec.total` on idBt 11; 6 / 318 / 21 rows |
| premier_kladionica | yes | yes | yes | `ZBROJ_GOLOVA` line from setTipVar |
| mbet | no | yes | yes | goal ranges `0-4/5+`, `0-5/6+`; no 0.5 partition |
| mozzartbet | no | yes | yes | goal ranges `0-4/5+`, `0-5/6+`; no 0.5 partition |
| sportplus | no | no | no | only `RASPON GOLOVA` ranges 1.5/2.5/3.5 |
| betole | no | no | no | desk feed exposes only the 2.5 codes 22/24 |

### 3.1 Browser (vision) checks

The screenshots are stored under `docs/evidence/screenshots/` and were read back
as images, not inferred from the parser:

- **MaxBet** `https://sportsbook.maxbet.ba/match/980094` (Leeds - Tottenham)
  shows `Ukupno golova` with Manje/Više at 0.5 (13.00/1.06), 4.5 (1.12/7.00)
  and 5.5 (1.03/15.00). The parser's labels and values match the page exactly.
- **Mozzartbet** `match/10088123` (Fenerbahce - Liverpool) shows the goal range
  market `0-1/2+`, `0-2/3+`, `0-3/4+`, `0-4/5+`, `0-5/6+`. That confirms
  4.5/5.5 and confirms the absence of a 0.5 partition (the smallest is 1.5).
- **MDShop** renders the NSoft football list with `Ukupno golova` and
  `Manje/Vise`; the full line ladder is present in the book's own JSON feed
  (`sbv` 0.5 through 6.5) and is exercised in §3's row counts.
- **Betole** rendered as a blank page in the browser session (its SPA did not
  start); the desk endpoint's own pick map contains only codes `22`/`24` for
  2.5, so no 4.5/5.5 claim is made.

A line is admitted only when its labels classify to that line and at least three
independent price sources publish it. The browser checks are corroboration, not
a replacement for the measured label/structure rule.

### 3.2 Non-football team identity: measured audit

`scripts/audit_nonfootball_matching.py` collects the four implemented non-NSoft
sources (sportplus, mbet, mdshop, maxbet) and asks two separate questions:

1. two listings that carry the same provider id must be in one verified group;
2. two listings that spell both teams identically and kick off within the
   verified 15-minute window must be in one group.

The 2026-11-04 run (`docs/evidence/2026-11-04-team-matching-audit.json`):

| Sport | Matches | Groups | Provider pairs | Missed | Exact-name pairs in window | Missed | False merges |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Basketball | 422 | 107 | 220 | 0 | 150 | 0 | 0 |
| Tennis | 797 | 255 | 232 | 0 | 202 | 0 | 0 |

44 tennis exact-name pairs were outside the 15-minute verified window; without a
shared provider id they are deliberately not verified. Three normalisation fixes
made the zero possible:

- **Compound surnames and doubles.** `De Minaur A.` / `Alex De Minaur`,
  `Romero Gormaz L.` / `Leyre Romero Gormaz` and `Haverlag I / Udvardy P` /
  `Haverlag Udvardy` now match; `Zverev A.` / `Zverev M.` still do not.
- **Women's markers.** `Evrokup Ž`, `EuroCup Women`, `Alba Berlin Wom`,
  `ITF W50` and `WTA` all produce the same `Women` tag, so an MBet listing that
  omits the marker can still join an NSoft/MaxBet listing when the players and
  clock are identical; basketball keeps the tag hard because the same club
  name can field a men's and a women's side.
- **Group reference, not anchor only.** The gate and scorer now try every group
  member's spelling and clock, not only the first listing. A group anchored by
  `Samsonova L` (one book's spelling of the same Betradar event) still accepts
  `Laura Samson`, and a group whose first clock is 11:11 still accepts a member
  at 11:03 when another member proves the 15-minute window.
- **Provider id overrides a bad clock/category.** Same non-empty Betradar id
  proves the event; measured feeds differed by up to 5h40 on one tennis match.
  The id still cannot decide home/away, so a pair whose names tie in both
  directions is left `orientation_unresolved` rather than flipped blindly.

## 4. Research: practical ways to increase yield

Sources were read on 2026-11-04. Each option gets a verdict and the reason.

| Source | Finding that drove a decision |
| --- | --- |
| https://en.surebet.com/wiki/beginners-guide-to-arbitrage-betting | Returns are typically 1–5% of stake; volume matters more than per-bet edge; account limits are the binding constraint. |
| https://www.statsnbet.io/en/tools/arbitrage | Reachable surebets usually 1–3%; above 5% is usually a stale price, line error, or two non-equivalent markets. |
| https://www.goldedge.net/tools/arbitrage-calculator | Names the failure modes: incomplete outcome sets, regulation-vs-overtime mismatches, stale prices, partial acceptance. |
| https://parlay-api.com/blog/detecting-stale-sportsbook-lines-2026-05-19 | Stale lines are found by peer-price clusters, source freshness and suspended-status flags; quarantine a stale book from cross-book scans. |
| https://help.outlier.bet/en/articles/11011706-use-multi-book-devigs-and-custom-weighting-to-increase-your-roi | Devig each book and compare against a multi-book fair value; a single book is not a reference. |
| https://theses-dissertations.princeton.edu/entities/publication/437f7731-67ad-4af7-a1e6-648c1d003d46 | Live NBA arbitrage was present only ~4.52% of scraped time and typically lasted ~13 seconds. |
| https://www.ubplj.org/index.php/jgbe/article/view/630/0 | European football markets show persistent odds biases and arbitrage across many books, but edges are small and execution-sensitive. |
| https://www.unifr.ch/tim/en/assets/public/uploads/Publication%20list/2013/Franck_Verbeek_N%C3%BCesch_2013.pdf | Inter-market arbitrage is concentrated where books disagree; liquidity and execution are the practical limits. |

### Verdicts

| Option | Verdict | What was done |
| --- | --- | --- |
| Coverage breadth (more sports/markets) | **Feasible and implemented** | Basketball and tennis admitted only after the three-book measurement; hockey refused with evidence. |
| Line shopping across books | **Feasible and implemented** | The engine already takes the best price per outcome from distinct price sources; the same rule now applies to the new families and lines. |
| Polling / freshness | **Feasible, partially implemented** | Each leg carries `fetched_at`; live odds expire after 60 s and prematch after 600 s; the scan stamps one wall-clock. Polling frequency is an operator setting, not raised by default (load/rate-limit risk). |
| Stale-price and outlier handling | **Feasible and implemented** | Existing price guard + per-book margin sanity (a non-football book whose own complete set implies < 1.0 is stale) + a two-source high-edge rule (>= 10% with fewer than three **distinct price sources** is rejected; NSoft's MDShop/Admiralbet pair counts once) + a per-line consistency check (a non-football book whose side of a line differs by more than 20% from the peer median cannot support an edge). The last rule removed a 13% NBA handicap artefact made from two books each having one broken side. Settlement mismatches are never paired. |
| Market consensus | **Feasible and implemented** | `engine/market_consensus.py` devigs each book and compares against the median of at least two others; it admitted the three new football lines and runs as the price-outlier guard. |
| Account/limit management, stake rounding, bookmaker relationship | **Not feasible in this scanner** | Requires accounts and bet placement; the project explicitly never places a bet or logs in. |
| Auto-placing the second leg / execution latency | **Not feasible under the project constraints** | Would move money and place bets; the dashboard only deep-links to a prefilled ticket. |
| Lowering the minimum profit or the certainty gate to raise the count | **Rejected** | The research itself says high apparent edges are usually stale/void; the brief forbids lowering the evidence standard. |
| Adding books without a feed capture | **Rejected for now** | No capture means no label/structure proof; listed as blockers above. |

## 5. Real scans (2026-11-04)

Command used: `python scripts/record_scan.py prematch` and
`python scripts/record_scan.py live`, all nine enabled books. The reports are
`docs/evidence/2026-11-04-prematch-scan.json` and
`docs/evidence/2026-11-04-live-scan.json`.

| Metric | Prematch | Live |
| --- | ---: | ---: |
| Matches | 9,629 | 182 |
| Football matches / verified groups / surebets | 8,018 / 1,295 / 7 | 71 / 11 / 1 |
| Basketball matches / verified groups / surebets | 568 / 114 / 1 | 20 / 0 / 0 |
| Tennis matches / verified groups / surebets | 1,043 / 248 / 0 | 91 / 12 / 0 |
| Groups the gate verified | 1,657 / 1,657 | 23 / 23 |
| Unmapped markets | 0 | NSoft live IDs and Betole live pick codes (see limitation) |
| Two-source OUTLIER guard | 13.08% NBA handicap artefact rejected after stale-set support accounting; remaining non-football surebets are 3.07%, 0.49% and 0.36% | none |
| Pairing audit, all sports | 1.06% strict miss (90 / 8,467), 0 duplicate-book groups | 3.33% (2 / 60), 0 duplicate-book groups |
| Pairing audit, football only | 1.04% (74 / 7,089) | 9.09% (2 / 22) |
| Pairing audit, non-football | 1.16% (16 / 1,378) | 0% (0 / 38) |

The pairing-audit rows are the earlier fixed-corpus run
(`docs/evidence/2026-11-04-pairing-audit.json`); the new matching audit in §3.2
is the like-for-like check for the fixes in this pass. The live feed is not a
frozen experiment, so its counts move with the day's fixtures. The same-corpus
before/after control is the frozen replay in §6.

A basketball surebet at 13.08% (Washington - Atlanta, handicap -3.5) was
examined by hand: MDShop and SportPlus each had one side >20% away from the peer
median, and MBet's own complete set implied 0.879. The engine now drops every
book whose side of the line is that far from the peer median and counts only
distinct plausible price sources; the artefact is gone. The final prematch run shows one non-football surebet (0.36%,
Oklahoma - Cleveland total) between two complete, consistent books, and no
other-sport edge above 1%.

## 6. Frozen replay (football must not move)

`scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --no-learn`:

| Metric | Before | After |
| --- | ---: | ---: |
| Matches | 3 | 3 |
| Pairs verified | 1 | 1 |
| False merges | 0 | 0 |
| Verified groups | 1 | 1 |
| Surebets | 3 | 3 |
| Mapped market rows | 18 | 18 |
| Unmapped market rows | 0 | 0 |

Cold and seeded replay modes are unchanged by the sport fields because football
still takes the original `canonicalize_fixture` path and the original market
types; the new fields default to `football` / `full_time`.

## 7. What is deliberately not implemented

- **Ice hockey**: two qualifying books only; exact per-book blockers in §1.
- **Volleyball, handball, baseball, table tennis, American football, MMA**:
  published by some books but not measured to three qualifying books with
  comparable settlement in this pass; no parser was added.
- **NSoft non-football live**: the live bet-type ID space for those sports was
  not observed (no in-play events during measurement), so the parser refuses to
  guess. SportPlus, MBet and MaxBet provide the live non-football path.
- **Premier, Mozzartbet, WWIN, Betole non-football**: blockers in §1.
- **Betole live pick codes**: the live desk returns the same pick-code shape as
  prematch, but no live registry row is proven and the feed's live detail is not
  exposed. Every live code is therefore recorded in `unmapped_markets`; the
  parser prices nothing from it. This is a diagnostics gap, not a surebet source.
- **NSoft live extension IDs**: the 2026-11-04 live scan observed IDs 110, 74,
  86, 124, 125 and similar in the football feed. They are not in the registry and
  are recorded unmapped. They were not admitted because no label/structure and
  cross-book price proof exists for them yet; guessing one as a total or
  handicap would weaken the gate.

## 5. P2-5 admissibility re-audit (2026-11-04)

The expansion task re-applied the rule to the next candidate, ice hockey, using
the same measured run above (`docs/evidence/2026-11-04-sport-discovery.json`).
No new sport was admitted and no parser was added.

- **Basketball** and **tennis** remain the only enabled non-football sports:
  four and five qualifying books respectively, each with all three comparable
  families.
- **Ice hockey** is **blocked**, not a TODO: only `sportplus` and `mbet` publish
  three regular-time families. NSoft has no full-match handicap, and MaxBet's
  only total includes overtime, which is a different settlement.
- The three-book threshold was not lowered to two, and the incl-OT total was not
  treated as comparable.
- Cross-sport pairing remains a hard `sport_mismatch` reject
  (`tests/test_sports.py::test_sport_mismatch_is_a_hard_rejection`), and
  `ice_hockey` stays out of `ENABLED_SPORTS`.
