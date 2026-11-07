# Deep research — arbitrage betting and scraped-data processing

**Date:** 2026-11-04
**Scope:** external research to challenge and extend the BH_Arb roadmap.
**Status:** research record; no application code changed.

This document collects what the wider market, open-source projects, vendor documentation,
forums, and Reddit discussions say about building an arbitrage scanner. It is deliberately
separate from `ROADMAP.md` so the roadmap can stay an execution plan.

> **Evidence quality**
>
> - Vendor blogs (OddsJam, BetBurger, RebelBetting, ClawArbs, OddsPapi, SharpAPI) are
>   marketing as well as documentation. Their architectural claims are useful; their
>   performance and coverage claims are not treated as measured facts.
> - Open-source repositories were read directly. Their numbers are reproducible only to the
>   extent their own fixtures and scripts are.
> - Reddit blocks automated fetching (HTTP 403). Reddit findings below come from search-index
>   snippets of the named threads, not from a full page read. They are community opinion, not
>   evidence.
> - Arbusers forum threads were readable and are quoted as community experience.
> - Legal statements here are not legal advice. The project scrapes public pages only; it does
>   not log in, place bets, or bypass authentication.

---

## 1. The economics: most boards are not arbs, and most arbs are not actionable

### 1.1 The measured base rate

The strongest public measurement found is `Rijul0107/sports-arbitrage-scanner` ("Arb Desk"),
which recorded every odds board it saw, not only the ones that crossed:

| Metric | Value |
|---|---:|
| Odds boards recorded | 115,583 |
| Fixtures / sports | 984 / 18 |
| Boards where a market crossed | 1,553 (**1.34%**) |
| Cleared the profit and margin gates | 26 |
| Median margin, all boards | **−3.60%** |
| Median margin, when crossed | 0.21% |
| Boards above 10% margin | 3 (up to 30.18%), treated as data errors |

Source: <https://github.com/Rijul0107/sports-arbitrage-scanner>

The same project found that taking only the gated opportunities earned 92% of the dollars on
38% of the capital compared with taking every crossing. `MIN_MARGIN_PCT` and `MIN_PROFIT` are
therefore **capital-efficiency constraints**, not just caution settings. It also found that
crossing rate is not opportunity rate: ice hockey crossed 23.38% of boards and produced zero
actionable opportunities because the average margin was 0.20%.

A second useful result from that project: two books can be one price source. Ladbrokes and
Neds posted the **same price 99.9%** of the time across 11,198 shared markets. Holding both is
one account's worth of information behind two accounts' worth of capital. This is the same
problem BH_Arb already models for MDShop/Admiralbet (both NSoft), but BH_Arb hardcodes the
pair instead of measuring it.

### 1.2 What a realistic edge looks like

- OddsJam: “profit margins are small (generally no greater 2.5%)”; arbing alone is hard to
  scale. <https://oddsjam.com/betting-education/arbitrage>
- `cengizmandros/odds-arb-scanner`: “Typical real-world arbs: 0.5%–3% edges. Rarely above 5%
  outside of boosted promos or pricing errors.”
  <https://github.com/cengizmandros/odds-arb-scanner>
- RebelBetting warns that unusually high arbs are usually a bookmaker mistake, reversed
  participants, or a mismatched market, and that a palpable error can be voided.
  <https://www.rebelbetting.com/blog/how-to-avoid-risks-in-sports-arbitrage>
- The Reddit thread “93.62% NHL arb?!?” reached the same conclusion: the “usual suspects” on a
  number that large are a stale price, a palpable error, or a market-definition mismatch (the
  bet was on the game not going to overtime).
  <https://www.reddit.com/r/arbitragebetting/comments/1xl4kfn/9362_nhl_arb/>

**Implication:** BH_Arb's `MAX_SUREBET_PROFIT_PERCENT = 20`, `MAX_TWO_SOURCE_PROFIT_PERCENT =
10`, price guard, and settlement field are directionally correct. The missing piece is a
denominator: how many boards were seen, how many crossed, how many were actionable, and how
long did each survive?

### 1.3 Account limits are the binding constraint

Multiple sources agree that soft books limit or close accounts that win consistently, while
sharp books and exchanges do not:

- OddsShopper: “Will sportsbooks ban you for arbitrage betting?” — limits are the normal
  outcome. <https://www.oddsshopper.com/articles/betting-101/arbitrage-betting-limits-getting-banned>
- ClawArbs: “If you arb soft books, you will get limited. The question is when, not if.”
  It lists detection signals (non-round stakes, reaction time to line moves, positive CLV,
  niche markets, bet velocity) and account-longevity tactics.
  <https://clawarbs.com/blog/avoid-sportsbook-limits/>
- Reddit “How to not get banned” and “My strategy after 3 years of arbing” both emphasize
  diversification, sharp-friendly books, and avoiding recreational books.
  <https://www.reddit.com/r/arbitragebetting/comments/1ehvyzo/how_to_not_get_banned/>
  <https://www.reddit.com/r/arbitragebetting/comments/1op798l/how_to_avoid_getting_limited_my_strategy_after_3/>

**Implication for BH_Arb:** the “never places a bet” non-goal is not a limitation to
apologize for; it is the honest boundary. The scanner can add **book risk profiles** and
warnings, but it should not implement stake jitter, “mug betting”, multi-account rotation, or
any KYC/identity evasion. Those are account-fraud-adjacent and outside the product's stated
scope. The useful feature is transparency: label a book as soft/sharp/exchange and show a
realistic limit warning next to a leg.

---

## 2. Scraped-data processing: the parts that break

### 2.1 Prefer the feed over the rendered page

Every mature source says the same thing:

- Use the bookmaker’s own JSON/XHR endpoint when it exists; parse HTML only as a fallback.
- For live odds, intercept or subscribe to the WebSocket/push feed rather than re-rendering a
  page.
- Browser automation is the slowest and most fragile option, but it is sometimes the only way
  to establish a session.

Sources:

- Roundproxies: “HTTP Requests with Hidden APIs” is the fastest method; Playwright is for
  JavaScript-heavy sites; live odds are often on a WebSocket.
  <https://roundproxies.com/blog/scrape-sports-betting-sites/>
- `declanwalpole/sportsbook-odds-scraper`: requests the books’ undocumented APIs instead of
  parsing HTML, and notes that “no SLA can be given as the sites may change without warning or
  block your traffic.” It supports a time-series workflow by repeatedly scraping one event URL
  and timestamping each snapshot. <https://github.com/declanwalpole/sportsbook-odds-scraper>
- `Habeel-Shamsudeen/sportsbook-scraper`: an asynchronous, scheduler-based 1xBet scraper with
  separate prematch (60 s) and live (2 s) loops, game lifecycle transitions, stale-game cleanup,
  and Prometheus metrics. <https://github.com/Habeel-Shamsudeen/sportsbook-scraper>
- `enesmertcetin/surebet-scanner`: Playwright/WebSocket discovery for Digitain-style books.
  <https://github.com/enesmertcetin/surebet-scanner>

**Implication:** BH_Arb already prefers direct HTTP where possible and uses Playwright for the
Cloudflare-backed books. The next reliability step is to capture the network feed of the
browser books once, document the endpoint, and use the browser only to establish the session
where possible. That is a maintenance reduction, not a new trust rule.

### 2.2 Every row needs two timestamps and a provenance record

A price is a fact with a time and a source. The Odds API’s documentation is explicit that a
market-level `last_update` stops advancing when a market is suspended or closed, and the market
is removed after about 15 minutes. <https://the-odds-api.com/liveapi/guides/v4/>

SharpAPI’s documentation makes the same distinction in a different way: a row’s `timestamp`
records when the provider last delivered the row, not when the price last moved. End-to-end
freshness is capture time + processing time + delivery time.
<https://sharpapi.io/learn/how-live-is-real-time-odds-data>

**Implication:** BH_Arb has `fetched_at` but not a distinct “source last changed” time. Add
`source_updated_at` where the feed provides it, and keep `fetched_at` as the collection time.
A stale market that is still being served is more dangerous than a missing market.

### 2.3 Missing data looks like a smaller dataset

This is the sharpest warning in the `sports-betting` reconciliation docs:

> “If a name fails to match, that match has no odds. A missing odd does not look like an error.
> It looks like a slightly smaller dataset. That gives you a backtest that is clean, plausible
> and wrong.”
> <https://georgedouzas.github.io/sports-betting/generated/gallery/sources/plot_reconciliation/>

The library’s policy is the right one: resolve what it can, drop what it cannot, and require an
explicit alias for the rest. Never guess a club from a fuzzy score.

**Implication:** BH_Arb’s pairing audit is the right instrument, but it measures only fixtures
that have a counterpart. It does not answer “which book/sport/market is silently missing?”
That needs an expected-vs-observed coverage budget.

### 2.4 Event identity: IDs first, aliases second, fuzzy only for candidates

The consensus across vendors and practitioners:

- Use a provider match ID when one exists.
- Use reviewed/canonical aliases next.
- Use fuzzy similarity only to *find* candidates, never to confirm.
- Keep qualifiers (`U21`, `Women`, reserve, academy, digits) that identify a different roster.
- Use a shared opponent to find splits; do not trust name similarity alone.
- A false merge is worse than a split.

Sources:

- Dozor’s 27-book esports entity-resolution write-up:
  <https://dev.to/dozor/matching-the-same-esports-match-across-27-bookmakers-entity-resolution-in-go-2dg5>
- Reep’s football entity-resolution notes:
  <https://reep.football/entity-resolution>
- OddsRelay’s “normalise odds across bookmakers”:
  <https://oddsrelay.io/blog/how-to-normalise-odds-across-bookmakers>
- Betting52’s “match event names across bookmakers”:
  <https://betting52.com/betting-tools/match-event-names-across-bookmakers/>

**Canonical-ID caveat:** SharpAPI builds IDs from league + sorted teams + date + a 6-hour
start-time bucket, with an optional doubleheader suffix. It documents two known failure modes:
a kickoff near a bucket boundary can split one fixture across two IDs, and a doubleheader can
produce a `_g1` suffix mismatch. <https://docs.sharpapi.io/en/concepts/event-matching/>

**Implication:** BH_Arb’s Betradar-first, ledger-second, conservative-name gate is aligned with
best practice. The untested edge cases are same-day doubleheaders, same teams meeting twice in
a short window, and kickoff data that crosses a date boundary. These deserve explicit fixtures
and regression tests.

### 2.5 Market identity is not just a label

Market identity has four parts:

1. market family (1X2, total, handicap, BTTS, …),
2. line (2.5 vs 3.5, -0.5 vs +0.5),
3. period (full time, first half, quarter),
4. settlement (regulation vs including overtime).

RebelBetting calls out the exact human errors this causes: full-time vs first-half, +1.5 vs
+1.0 Asian handicap, match winner vs draw-no-bet, regulation vs overtime.
<https://www.rebelbetting.com/blog/how-to-avoid-risks-in-sports-arbitrage>

BH_Arb already models `settlement` and `period`, and refuses to pair different settlements.
The remaining gap is coverage: every parser should publish the book’s own `source_id` so a
mapping can be attributed and tested.

### 2.6 Storage: append-only prices, not just the current snapshot

The useful design from the open-source projects:

- record every board, not only the arbs (`Rijul0107`);
- timestamp every snapshot (`declanwalpole`);
- keep the raw payload hash and the normalized row (`Habeel-Shamsudeen`);
- store market/selection IDs alongside labels (`SharpAPI`, `declanwalpole`);
- index by event, book, market, timestamp.

For BH_Arb’s scale, SQLite is enough to start; the key is the schema, not the engine. A
time-series extension is only warranted after the board log proves the query volume. The
current 218 MB JSON cache is the opposite pattern: it stores the latest snapshot in one
document and pays the whole parse cost on every read.

### 2.7 Validation belongs before pricing

A practical validation ladder, assembled from the sources:

1. **Shape:** odds are numeric and in a plausible range (e.g. 1.01–1000); no missing sides.
2. **Completeness:** a 1X2 set has 1/X/2; BTTS has both; a total has both sides.
3. **Line parity:** both sides of a total/handicap refer to the same line.
4. **Settlement parity:** both legs settle on the same period and overtime rule.
5. **Book margin sanity:** a book’s own complete set should imply a margin above 1.0; a set
   below 1.0 is stale/suspended, not a gift.
6. **Cross-book consensus:** an outlier side far from the peer median cannot support an edge.
7. **Price movement:** a jump larger than a configured bound is quarantined until re-checked.
8. **Suspension:** a market flagged suspended is never priced.

BH_Arb has most of these (price guard, margin sanity, consensus, settlement). The missing
operational piece is a **per-book integrity score** and a quarantine state that survives across
scans.

---

## 3. What mature products actually do

| Product | Architecture / features | What to learn | What not to copy |
|---|---|---|---|
| **OddsJam** | 100+ books, real-time odds and tools, detection-only, US-focused, subscription. API is powered by OpticOdds. | Polished detection, educational content, value + arb in one UI. | No execution, no local-book coverage, expensive. |
| **BetBurger** | 200+ books (230+ with clones), prematch + live, filters, API with separate live/prematch endpoints and rotating tokens. | Filter design, separate feeds, explicit bookmaker selection. | Token refresh complexity; broad coverage is its moat, not ours. |
| **RebelBetting** | 120+ books, sure + value betting, BetTracker, auto-settlement, browser-extension semi-automation, Pinnacle reference. | Bet log + settlement + ROI is a first-class feature. | Browser-extension automation is fragile; no prediction markets. |
| **ClawArbs** | Execution-first, WebSocket feeds, Kalshi/Polymarket, kill switch, naked-position tracking, daily loss limits, exposure caps, paper trading. | Risk-management vocabulary: naked leg, kill switch, exposure cap, paper mode. | Auto-execution and account-longevity tactics are outside BH_Arb’s scope. |
| **SharpAPI** | Canonical event IDs, SSE/WebSocket, arbitrage/EV/middles endpoints, deep links, closing-line value. | Canonical IDs and raw + derived separation; CLV as a first-class metric. | Enterprise pricing; not a local-book source. |
| **The Odds API** | ~40 soft books, credit-based polling, no sharps, no deeplinks/settlement. | Cheap way to prototype; explicit `last_update` semantics. | Not enough for a real edge; data-quality caveats. |
| **OpticOdds / Unabated / SportsGameOdds** | Enterprise feeds, settlement, deeplinks, WebSocket/SSE, $3k–$5k+/month. | What “production” means: settlement, deeplinks, latency, support. | Cost and scope; BH_Arb is local and independent. |

Sources:

- OddsJam: <https://oddsjam.com/betting-education/arbitrage>, <https://oddsjam.com/odds-api>
- BetBurger: <https://www.betburger.com/sport-arbitrage-betting>, <https://www.betburger.com/blog/what-is-odds-api-in-betting>
- RebelBetting: <https://www.rebelbetting.com/en-us/surebetting>
- ClawArbs: <https://clawarbs.com/blog/best-arbitrage-betting-software/>
- SharpAPI: <https://docs.sharpapi.io/en/concepts/event-matching/>
- The Odds API: <https://the-odds-api.com/liveapi/guides/v4/>
- Provider comparison: <https://sportsgameodds.com/blog/comparing-odds-api-providers>

**Strategic read:** BH_Arb cannot win on book count or latency. It can win on **local book
coverage, proof-carrying identity, honest settlement handling, and reproducible evidence**.
That is already its differentiator; the roadmap should deepen it rather than chase OddsJam.

---

## 4. Community wisdom from Reddit and forums

Reddit blocks automated fetching, so these are search-index snippets of the named threads.
Treat them as anecdote, not measurement.

### 4.1 Building a scanner

- **“Building my own arb scanner, what APIs or tech do you recommend?”**
  <https://www.reddit.com/r/arbitragebetting/comments/1xfpx7p/building_my_own_arb_scanner_what_apis_or_tech_do/>
  Snippet: “An arb can disappear pretty quickly if one book is lagging behind.” The thread asks
  whether the builder will poll on an interval or wait for push notifications, and warns to
  check staleness before committing.
- **“How does Oddsjam work so quickly?”**
  <https://www.reddit.com/r/algobetting/comments/17uhas9/how_does_oddsjam_work_so_quickly/>
  Snippet: for specific markets, a 1–2 minute delay is often acceptable; “you can scrape the
  data from almost any of the apps.” Speed is relative to the market and the edge.
- **“Odds scraping and storage questions”**
  <https://www.reddit.com/r/algobetting/comments/1bky53f/odds_scraping_and_storage_questions/>
  Community answers mention Selenium to log in and browse, IP blocks, proxies, Scrapy, and the
  fact that many books serve their own JSON APIs.
- **“Best Odds APIs?”**
  <https://www.reddit.com/r/algobetting/comments/1sdygwx/best_odds_apis/>
  Snippet: “The Odds API had similar scraping issues when I tested it — biggest lesson,
  whatever API you pick, build verification checks from day one.”
- **“Technical guide to scraping betting odds for profit”**
  <https://www.reddit.com/r/WebDataDiggers/comments/1qg2nb8/technical_guide_to_scraping_betting_odds_for/>
  Snippet: if a scraper takes 30 seconds to cycle five bookmakers, the odds have likely moved;
  Selenium is not suitable for that loop.

### 4.2 Account limits and realistic expectations

- **“How to not get banned”**
  <https://www.reddit.com/r/arbitragebetting/comments/1ehvyzo/how_to_not_get_banned/>
  Community reports limits after weeks or months, sometimes with maximum stakes around $20.
- **“My strategy after 3 years of arbing”**
  <https://www.reddit.com/r/arbitragebetting/comments/1op798l/how_to_avoid_getting_limited_my_strategy_after_3/>
  Advice: diversify books, focus on sharp-friendly books, avoid recreational books.
- **“Is Arbitrage Betting Still Worth It? How Much Have You Earned?”**
  <https://www.reddit.com/r/arbitragebetting/comments/1jltzur/is_arbitrage_betting_still_worth_it_how_much_have/>
  The discussion is dominated by limits, bans, and risk rather than edge math.

### 4.3 Stale prices and palpable errors

- **“93.62% NHL arb?!?”**
  <https://www.reddit.com/r/arbitragebetting/comments/1xl4kfn/9362_nhl_arb/>
  Snippet: the usual suspects for a number that large are a stale price, a palpable/obvious
  error the book will void, or a market-definition mismatch (the bet was on the game not going
  to overtime). Most books have a palpable-error rule and will void it.
- **“What Do You Do When Your Accounts Get Limited?”**
  <https://www.reddit.com/r/arbitragebetting/comments/1phsziv/what_do_you_do_when_your_accounts_get_limited/>
  Advice includes betting closer to kickoff, when books have adjusted to their closing line.

### 4.4 Legal and access

- **“Is it legal to scrape odds?”**
  <https://www.reddit.com/r/algobetting/comments/1i11wqi/is_legal_to_scrape_odds/>
  Snippet: “It seems legal until you’re doing it against the site’s terms.”
- **“Undetectable scraping”**
  <https://www.reddit.com/r/algobetting/comments/1er99py/undetectable_scraping/>
  The discussion centers on IP analysis and browser fingerprinting — a reminder that anti-bot
  is an arms race, not a one-time setup.

### 4.5 Arbusers forum

- **“Build your own sports betting arbitrage software”**
  <https://arbusers.com/build-your-own-sports-betting-arbitrage-software-t4583/>
  Practical warnings from developers: bookmaker sites change, IPs get blocked, and a scraper
  needs maintenance; one developer ran multiple servers to spread requests; another used Excel
  for pre-match because a 5-minute delay was acceptable. Cost estimates ranged from “a few
  hundred” to €20k+, which says more about scope uncertainty than about the market.
- **“Is web-scraping betting sites for events, odds, etc legal?”**
  <https://arbusers.com/is-web-scraping-betting-sites-for-events-odds-etc-legal-t7120/>
  No definitive answer. The thread notes that public odds are visible to everyone, that ToS
  may still prohibit automated collection, and that commercial data deals are common. Treat
  this as a jurisdiction/ToS question, not a technical one.

**Community summary:** the recurring failure modes are stale data, false identity, account
limits, and maintenance. The recurring success factors are broad coverage, fast refresh,
discipline about high edges, and a long enough account life to make the small edges compound.
BH_Arb already handles false identity unusually well; it is weakest on measured freshness and
opportunity-rate visibility.

---

## 5. Direct implications for BH_Arb

| Research finding | Current state | Action |
|---|---|---|
| Most boards never cross; crossing ≠ actionable | The dashboard reports groups and surebets, but no denominator or lifetime | Add **opportunity-rate and arb-lifetime telemetry** (P0-6) |
| Stale books are the main phantom-arb source | Per-surebet price guard, but no per-book quarantine | Add a **feed-integrity scorecard + stale-book quarantine** (P0-7) |
| Two books can be one price source | `PRICE_SOURCES` hardcodes only the NSoft pair | Add measured **identical-feed/skin detection** (P2-7) |
| Served margins should be recomputable from raw prices | API serves precomputed margins; no rounding audit test | Add **raw-price invariant + rounding audit** (P1-7) |
| Missing data looks like a smaller dataset | Pairing audit covers same-fixture misses, not expected coverage | Add **silent-drop coverage budget** (P2-9) |
| Doubleheaders/rematches/bucket boundaries are known identity edge cases | Betradar-first gate helps; no explicit fixtures | Add **identity edge-case tests** (P2-8) |
| Account limits are the binding constraint | The tool is advisory and never places bets | Keep it that way; add **book risk profiles** (P3-6), no evasion |
| Paper trading / record-only is standard in mature tools | No simulation mode; only live scans | Add **record-only/paper mode** (P3-7) |

---

## 6. What not to copy

- **Auto-execution of both legs.** It moves money, creates naked-leg risk, and contradicts the
  project's stated non-goal. It also requires account credentials and likely violates bookmaker
  terms. Keep the tool advisory.
- **Account-longevity evasion** (stake jitter, “mug betting”, multi-account rotation, KYC
  evasion). Some of this is legal but it is outside the product's scope and close to fraud.
  The honest feature is a warning and a book risk label, not a disguise.
- **Proxy/browser-fingerprint evasion as a core feature.** It is a maintenance arms race and
  may violate ToS. If the project ever needs it for reliability, document the legal review
  first.
- **Lowering the certainty gate to increase the count.** The research consistently says a
  false merge is worse than a missed match. Keep the gate.
- **Broad book count as a vanity metric.** Coverage matters only if the books are independent
  price sources and the scanner can actually reach them.

---

## 7. Open questions for the next research pass

1. **What is the real arb lifetime on the Bosnian books?** Measure time from first crossing to
   the next scan where it is gone. The answer decides whether 5-minute polling is enough.
2. **How often do the nine books post identical prices?** A pairwise exact-agreement matrix
   over shared markets would replace the hardcoded NSoft assumption.
3. **How often does a book suspend or void a market, and does the scanner notice?** A
   suspension/void rate per book is a missing integrity metric.
4. **What is the actual cost of a full nine-book scan?** Requests, browser seconds, bytes, and
   failure rate per book. This should be a dashboard number, not an estimate.
5. **What does a labelled multi-day corpus say about precision/recall?** The existing pairing
   audit is a good start; a labelled corpus is the next step.

---

## 8. Source index

**Open-source projects**

- <https://github.com/Rijul0107/sports-arbitrage-scanner> — board logging, 1.34% crossing
  rate, backtest, identical-price book pairs, whole-dollar stakes.
- <https://github.com/cengizmandros/odds-arb-scanner> — clean FastAPI + CLI + TTL cache.
- <https://github.com/smartworkersai/KOS> — supervised async daemon, SQLite WAL, state machine,
  Telegram.
- <https://github.com/Habeel-Shamsudeen/sportsbook-scraper> — scheduler, prematch/live loops,
  Kafka, Prometheus.
- <https://github.com/declanwalpole/sportsbook-odds-scraper> — undocumented APIs, normalized
  DataFrame, time-series example.
- <https://github.com/enesmertcetin/surebet-scanner> — Playwright/WebSocket discovery.
- <https://github.com/georgedouzas/sports-betting> — feed reconciliation and the “silent drop”
  warning.

**Vendor documentation and comparisons**

- <https://the-odds-api.com/liveapi/guides/v4/> — polling, credit model, `last_update`.
- <https://docs.sharpapi.io/en/concepts/event-matching/> — canonical IDs, bucket/doubleheader
  caveats.
- <https://sharpapi.io/learn/how-live-is-real-time-odds-data> — capture vs delivery latency.
- <https://sportsgameodds.com/blog/comparing-odds-api-providers> — provider pricing/coverage
  comparison.
- <https://oddsjam.com/betting-education/arbitrage> — edge sizes and risks.
- <https://www.betburger.com/sport-arbitrage-betting> — arb math and bookmaker attitude.
- <https://www.rebelbetting.com/en-us/surebetting> — product scope, BetTracker, auto-settlement.
- <https://www.rebelbetting.com/blog/how-to-avoid-risks-in-sports-arbitrage> — palpable errors,
  rules, human errors.
- <https://clawarbs.com/blog/best-arbitrage-betting-software/> — detection vs execution,
  risk-management vocabulary.
- <https://clawarbs.com/blog/avoid-sportsbook-limits/> — account-limit signals and tactics
  (reported, not recommended).

**Forums and community**

- <https://arbusers.com/build-your-own-sports-betting-arbitrage-software-t4583/>
- <https://arbusers.com/is-web-scraping-betting-sites-for-events-odds-etc-legal-t7120/>
- Reddit threads listed in §4 (direct fetch blocked; snippets used).

**Scraping practice**

- <https://roundproxies.com/blog/scrape-sports-betting-sites/> — hidden APIs, Playwright,
  WebSocket, rate limits, anti-bot.
- <https://blog.willbraun.dev/how-i-tried-to-get-rich-using-web-scraping> — a real project’s
  data-quality and result-tracking lessons.
