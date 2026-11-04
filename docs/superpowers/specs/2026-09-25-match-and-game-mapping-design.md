# Match & Game Mapping Validation — Design Spec

Date: 2026-09-25
Repo: `surebetmuse12` (branch `master`, base commit `80a0075`)
Status: awaiting written-spec review

## 1. Purpose & scope

Goal: every displayed surebet rests on a *provable* same-event claim, while the
AI layer maximizes the number of candidate opportunities. All three mapping
layers are in scope:

1. **Fixture identity** — team, league, kickoff, category, home/away across
   bookmakers.
2. **Market-type mapping** — each book's API market IDs → internal `MarketType`
   with correct settlement period and complete outcome sets.
3. **Deep links** — per-event URLs that land on the intended event.

Out of scope: enabling Asian handicap / first-half markets as tradeable until
their registries are captured and tested; real-money automation; new bookmakers.

Non-goal: replacing the human reviewer. The system is a beta that surfaces
candidates and only promotes *verified* pairs.

## 2. Success criteria

- No surebet is produced from a pair that has not passed the certainty gate.
- Every match group carries a status (`verified` | `suggested` | `rejected`) and
  an evidence trail.
- Every bookmaker's prematch and live market IDs are declared in one registry
  and covered by at least one fixture test.
- Every tradeable book's event deep link is proven to open the intended event
  (or is explicitly flagged `unverified_link`).
- AI can only *propose*; only deterministic proofs or human approval make a
  pair tradeable.
- When AI is unavailable, the engine degrades to rules-only and says so.

## 3. Architecture

```
Scrapers (per book)
  → Feature extraction (teams, league, kickoff, country, event id, markets, url)
  → Rule stage (exact/alias + league + kickoff + category)  ── proven pairs
  → AI stage (ambiguous pairs only)                        ── proposals
  → Certainty gate (deterministic proofs)                  ── VERIFIED
                                                            └─ REVIEW queue
```

Only `verified` groups feed `engine/arbitrage.py`. The existing greedy
`MatchMatcher` becomes the rule stage; a new `CertaintyGate` is a separate
component that can veto a match the rule stage proposed.

## 4. Certainty gate

A pair is `VERIFIED` only when **all** of the following hold:

1. **League identity** — both sides resolve to the same canonical league ID, or
   to an explicitly declared equivalence in `config/league_equivalences.json`
   for that pair. Blanket cross-league merging is removed.
2. **Kickoff** — both known and within `15` minutes (`KICKOFF_WINDOW_MINUTES`
   reduced from 120). Missing kickoff is never verified.
3. **Category** — special-category tags (U21, Women, Reserves, Esports) agree
   and none is unknown.
4. **Team identity** — both teams resolve to the same canonical team ID
   (exact or alias). A fuzzy/AI-proposed alias only counts if present in
   `config/team_alias_allowlist.json`.
5. **Orientation** — home/away is provable (direct or exact swap).
6. **Link evidence** — each book in a tradeable group has a per-event URL that
   resolves to the intended event, or is explicitly flagged `unverified_link`
   in the evidence trail.

Kickoff and league are *hard* rules. Team identity may be proven by an
allowlisted alias. Category and orientation are hard rules.

**Clarified link policy (removes an ambiguity in section 2):** `verified` means
*every* part of the claim is proven, including links. A book with a per-event
URL that was not yet verified is `unverified_link`; a book that genuinely
offers no per-event URL must be declared with `supports_event_id: false` in
`config/bookmaker_deeplinks.json` and is accepted with a `no_event_link`
evidence note. Any other unverified link yields status `suggested`, a
`link_unverified` reason, and a "check link manually" badge in the review
queue. This keeps the `verified` promise honest while still surfacing
high-confidence opportunities for human review.

## 5. Data model

New Pydantic models in `models/schemas.py`:

- `MatchGroup.status: Literal["verified","suggested","rejected"]` (default
  `suggested`) and `MatchGroup.evidence: list[MatchEvidence]`.
- `MatchEvidence` — `rule`, `source` (`rule`|`ai`|`human`|`allowlist`),
  `confidence`, `reason`, `league_pair`, `kickoff_delta_minutes`,
  `allowlist_entries`.
- `CandidateReview` — `id`, `home_team`, `away_team`, `league`, `kickoff`,
  `bookmakers`, `ai_confidence` (AI ranking only; does not affect approval),
  `ai_reason`, `rule_rejections` (why the rule stage refused), `status`
  (`pending`|`approved`|`rejected`), `created_at`, `resolved_at`,
  `resolved_by`.
- Confidence and approval are independent axes: `ai_confidence` is used for
  ordering the review queue; approval is the only mechanism that makes a
  pair tradeable.

`Match` gains `deep_link_verified: bool = False` and `event_id: str` alias for
`match_code` where the book supplies it.

## 6. Market registry

`config/bookmaker_markets.json` — one entry per book, per mode:

```json
{
  "mdshop": {
    "prematch": {
      "1x2":            { "ids": [135],       "labels": ["1","X","2"], "settlement": "full_time" },
      "double_chance":  { "ids": [152],       "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [151],       "labels": ["GG","NG"], "settlement": "full_time" },
      "over_under_1_5": { "ids": [137,138],   "line": 1.5 },
      "over_under_2_5": { "ids": [137,138],   "line": 2.5 },
      "over_under_3_5": { "ids": [137,138],   "line": 3.5 }
    },
    "live": {
      "1x2":           { "ids": [6],    "labels": ["1","X","2"] },
      "double_chance": { "ids": [18,42],"labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":          { "ids": [995],  "labels": ["GG","NG"] }
    }
  }
}
```

`over_under_1_5/2_5/3_5` in NSoft live feeds use IDs `22` and `28` with the
line in `sbv`; the registry models these as `"ids": [22,28], "line": <float>`.

Rules:

- Parsers read the registry; hardcoded per-book IDs move out of the scraper
  modules. The label-set and settlement checks move into a shared validator so
  every book applies the same acceptance rule.
- A market ID not in the registry is never silently dropped: it is counted in
  `status.unmapped_markets` and surfaced on `/api/health`.
- Every registry entry must be exercised by at least one fixture test built
  from a captured payload (not synthetic-only).
- `MARKET_MAPPING.md` is regenerated from the registry so docs cannot drift.

## 7. Deep links

`config/bookmaker_deeplinks.json` declares, per book, whether a per-event URL
is supported and how to build it. Builders live in `scrapers/common.py`
(`nsoft_event_url` already exists for NSoft books).

- Tradeable books must expose a real per-event URL; books that do not are
  flagged `unverified_link` in the evidence and on `/api/health`.
- A manual/on-demand Playwright check verifies a generated link opens the
  intended event (the event ID appears in the page). This check is not part
  of the hot scan path.

## 8. Review queue (API + UI)

Endpoints:

- `GET /api/candidates?mode=…` — pending pairs and the reason each was not
  verified.
- `POST /api/candidates/{id}/approve` — human approval; writes an alias
  allowlist entry (and/or league equivalence) that the gate then trusts.
- `POST /api/candidates/{id}/reject` — record rejection with reason.
- `GET /api/health` — adds `verified_groups`, `pending_candidates`,
  `unmapped_markets`, `unverified_links`.

Dashboard: a "Review" tab lists pending candidates (teams, league, kickoff,
AI confidence, reason) with one-click approve/reject. Only `verified` groups
produce surebets; the existing results view is unchanged otherwise.

## 9. AI layer

`MatchAI` adapter interface:

- `suggest_pairs(features: list[PairFeatures]) -> list[PairProposal]`
- `propose_alias(raw: str, candidates: list[str], league: str) -> AliasProposal`

Backed by a hosted OpenAI-compatible chat API (key, base URL, model from env;
timeout + retry; no network → rules-only, `ai_unavailable` in health).

Usage rules:

- AI runs only on ambiguous pairs (failed rule stage but plausible).
- AI proposals never auto-approve. A proposal enters the review queue even at
  0.99 confidence.
- Allowlisted fuzzy aliases are auto-accepted *only* when league, kickoff and
  category gates pass; the acceptance is logged.

## 10. League equivalence instead of blanket European merging

`config/league_equivalences.json` replaces `EUROPEAN_COMPATIBLE_LEAGUES`:

```json
{ "pairs": [["europa_league", "conference_league"]] }
```

The gate honors an equivalence only for a specific pair and still enforces the
15-minute kickoff window. A blanket "any two UEFA competitions" merge is
removed.

## 11. Error handling & observability

- Every group carries a status and evidence; every rejection records a reason
  (league_mismatch, kickoff_missing, kickoff_delta, category_mismatch,
  team_unresolved, orientation_unresolved, betradar_mismatch, sport_mismatch,
  link_unverified, no_event_link).
- `/api/health` exposes verified/pending/unmapped/unverified counts.
- AI failures degrade to rules-only and are visible in health.
- Unknown market IDs are counted, not silently dropped.

## 12. Testing

- Unit: gate rules (each reason), equivalence pairs, registry validator.
- Fixture: every registry entry per book per mode from captured payloads.
- Matcher: existing tests updated — Europa/Conference no longer merge without
  an explicit equivalence + kickoff proof; generic-league bridging removed.
- AI adapter: contract tests with a fake backend; no network in CI.
- API: candidates endpoints, health fields.
- End-to-end: scan → group statuses → only verified groups produce surebets.

## 13. Rollout

1. Add status/evidence fields and gate (default: nothing tradeable until
   registry + allowlists are populated).
2. Port market IDs into `bookmaker_markets.json` and add fixture tests.
3. Add candidates endpoints and the Review tab.
4. Add deep-link builders + on-demand verification.
5. Add AI adapter (rules-only until configured).
6. Tighten kickoff window to 15 minutes and remove blanket European merging
   once equivalences are declared.
7. Populate allowlists from the first review cycle.

## 14. Risks

- Fixture-based gate is stricter than today → fewer surebets initially. The
  review queue and allowlist growth recover recall.
- Hosted AI costs scale with ambiguous pairs; cap per scan.
- Deep-link verification depends on bookmaker site changes; flagged books are
  excluded from "verified link" claims, not silently trusted.
