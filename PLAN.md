# Surebet Scanner — Autonomous Mapping Plan

> **Goal contract.** From bookmaker payloads alone, resolve team names, league
> names and market meanings for every configured book and every market it
> publishes among the nine `MarketType` values, and reach `verified` groups and
> priced surebets with **no human review, alias approval, hand-written mapping
> entry, manual gate exception or manual CAPTCHA step** anywhere between scrape
> and a shown surebet.
>
> **Baseline (2026-11-03, this worktree).** `python -m pytest` → **1154 passed** in 90 s; `ruff check .` clean; `mypy .` clean on 111 source files;
> `scripts/generate_market_mapping_doc.py --check` in sync. Environment is
> `.venv` on CPython 3.11.18, installed with `uv`. The 953-passed figure in the
> superseded plan was a 2026-10-20 measurement and is stale.
>
> **Supersedes** the Muse 12 yield plan (`PLAN.md` before this rewrite). Its
> history, measurements and defect records remain in git and in
> `docs/HANDOFF.md`; they are evidence, not the current contract. Its hard stops
> that protect the gate are kept; its hard stops that forbid autonomous mapping
> are replaced.
>
> **Checkpoint 2026-11-03.** Wave 0 and Wave 1 are done (A0-1–A0-4,
> A1-1–A1-7), market classification/consensus is done (A2-1–A2-3), the generated
> registry and discovery path is partial (A2-4), and synthetic onboarding is done
> (A3-1). The evidence ledger, learner, gate integration, contradiction resolver,
> league fingerprints, legacy migration, read-only coverage endpoint, classifier,
> consensus, registry merge, discovery CLI and raw-offer resolver are shipped.
> Betole is now the ninth enabled book after fixing its kickoff and Betradar id;
> the 9-book scan found 6,503 matches, 1,039 verified groups and **8 surebets**,
> all re-verified by `POST /api/verify`; two price-outlier surebets were dropped. **1154 tests pass.** The acceptance
> record is `docs/ACCEPTANCE.md`; the production verdict and research are in
> `docs/PRODUCTION_READINESS.md`.
>
> **Next cards:** A2-6 market absence proofs; A7-5 freshness policy; A7-6
> execution limits/partial acceptance; A7-7 monitoring/CLV; then a 24-hour soak
> and the security stash.

---

## How to execute this plan

This file is written so an agent can work one card at a time with no other
context. Every open card in §4 names its files, current facts, steps, tests,
verification command and the condition that makes it done.

### The loop

1. Run **S1** once per session. All four checks must pass before changing
   anything. If they fail before you have touched the tree, stop and report.
2. Take the first card in §4 *Execution order* that is not `[x]`, not `BLOCKED`,
   and whose **Depends on** cards are all `[x]`.
3. Check **Needs**. `offline` = code and tests only. `network` = real bookmaker
   HTTP. `browser` = Playwright or a visible browser. `human` is not a valid
   need in this plan; if a card seems to require one, the card is wrong — rewrite
   it as a machine-evidence task or mark it `BLOCKED (needs operator decision)`
   with the evidence.
4. Follow **Steps** in order. Do not add unrelated refactors.
5. Run the card's **Verify** commands, then **S1** again. Everything green.
6. Run **S5** (record progress): tick, log, commit.
7. Go back to 2.

### Hard stops

* **Never lower an evidence standard to raise a number.** A mapping is accepted
  because evidence proves it, never because coverage is low.
* **Never auto-accept a fuzzy name on similarity alone.** Similarity may rank or
  corroborate; it may not be the only proof.
* **Never hand-edit a generated file.** `config/generated/*.json` is written only
  by its generator, with provenance. If a generated file and the code disagree,
  regenerate; do not patch the JSON.
* **Never trust a human-reviewed pair.** `config/team_alias_reviewed.json` is
  legacy seed data. Its entries must be re-derived or machine-validated before
  they can authorize a pairing. No new entry may be added.
* **Never set `deep_link_verified=True`** except through
  `scripts/verify_deeplinks.py` or `POST /api/verify-links`.
* **Never place a real bet, enter a bookmaker login, or move money.**
* **Never `git push`, open a PR, `git stash drop` or rewrite history** unless the
  operator asks.
* **Never make the gate accept a pair with contradictory objective evidence.**
  Shared Betradar ids that differ, or two listings that name each other as
  opponents, are contradictions, not gaps.

### Definition of done for the whole plan

The seven acceptance checks in §3 pass on one recorded run. No check may be
satisfied by a manual step, a hand-written mapping, or a disabled book that still
appears enabled.

---

## 0. Principles

1. **Evidence over authority.** Every mapping is a claim with provenance:
   which scans, which fixtures, which books, which contradiction checks. A claim
   without provenance is not accepted, however plausible it looks.
2. **Terminal decisions.** Every candidate pair the learner sees ends
   `accepted`, `rejected` or `quarantined` with a reason. There is no queue that
   waits for a person. `quarantined` means the evidence is genuinely
   contradictory or insufficient; it is recorded and rechecked, not hidden.
3. **One price source per feed.** MDShop and Admiralbet are one NSoft source;
   the engine already takes at most one leg per source. Grouping must count
   sources, not bookmaker names.
4. **No false surebets.** A wrong team, league or market mapping is worse than a
   missing one. The certified end-to-end test must keep proving that a
   contradicted claim removes the surebet.
5. **Deterministic replay.** Any mapping decision must be reproducible offline
   from frozen captures. A live scan may discover, but only replay may certify.
6. **Continuous revalidation.** Claims decay and are revoked on contradiction.
   Dated evidence is part of the claim.
7. **No silent gaps.** Every book, market, league and team that cannot be
   resolved is counted, named and reported with the evidence that is missing.
8. **Least trust.** Shared Betradar id > exact shared fixture > repeated
   cross-book consensus > league/team fingerprints > similarity. A lower tier
   may corroborate a higher one; it may not replace it.

---

## 1. Current state (audited 2026-11-03)

### 1.1 What exists and works

- 10 configured books in `config/settings.BOOKMAKERS`: mozzartbet, mdshop,
  admiralbet, mbet, sportplus, premier_kladionica, wwin, maxbet enabled;
  betole and evlbet disabled.
- 9 `MarketType` values: 1x2, O/U 1.5/2.5/3.5, BTTS, double chance (enabled);
  first-half 1X2, first-half O/U, Asian handicap (experimental, off).
- The pipeline is scrape → normalize → group (`engine/matcher.py`) → certainty
  gate (`engine/certainty.py`) → price (`engine/arbitrage.py`).
- `scripts/derive_mappings.py` already learns league mappings and team aliases
  from shared fixtures and Betradar ids. It writes
  `config/league_mappings.json`, `config/league_equivalences.json` and
  `config/team_alias_allowlist.json`.
- `scripts/price_check.py` already removes each book's margin and flags a book
  whose implied probability is more than 0.10 from the median of the others.
- `tests/test_e2e_certified.py` drives real parsers on frozen captures and
  asserts a surebet appears, and disappears when a claim is spoiled.
- `tests/test_readme_claims.py` runs the real gate over documented claims.

### 1.2 What enforces the human boundary today

| Path | What it does | Why it blocks autonomy |
|---|---|---|
| `config/team_alias_reviewed.json` | 565 approved, 22 rejected pairs from a person | Gate accepts approved pairs without the 90 floor; nothing machine-validates them |
| `config/team_alias_allowlist.json` | Written by `derive_mappings.py --apply` **or** Review approval | A human approval writes the durable trust record |
| `server/api.py` `approve_candidate`, `approve_candidates_bulk`, `reject_candidate` | Review endpoints | The only way to clear some identity blockers |
| `frontend/` Review tab | Human queue, "Select strong", "Approve selected" | A load-bearing UI step |
| `engine/matcher.py` `_reviewed_aliases` / `_alias_allowlist` | Loads the two files | No ledger, no provenance, no revocation |
| `engine/certainty.py` `reviewed_aliases` | Bypasses the similarity floor | Trust is by file membership, not evidence |

`docs/HANDOFF.md` records the design intent: the allowlist is "the human approval
boundary". `docs/HANDOFF.md` §288 also records that **77% of the candidate queue
(11,666 / 15,140) is league-blocked with no human action available** — the
current review flow cannot converge even with a person.

### 1.3 Known gaps that still matter

- **Betradar identity is not used by the gate.** `Match.betradar_id` is filled
  by mdshop, admiralbet, sportplus and wwin, but the gate ignores it. The old
  plan's M1-5 describes the exact rule; it is a prerequisite for the ledger.
- **Price sources are counted as books.** `group_matches` returns a group with
  ≥ 2 bookmakers, so a group of only MDShop + Admiralbet is counted but can
  never be priced. The old M1-3 fixes this.
- **Mozzartbet prematch coverage** returned 285 listings against a site count of
  about 1,150 on 2026-10-20; its grouped share is below the other books.
- **MaxBet's `/match/<id>` links are unproven**, so a group holding MaxBet stays
  unverified until `scripts/verify_deeplinks.py maxbet` proves them.
- **EVLBet's feed returns no football events** for every request variant tried;
  Betole is disabled. Both must be proven absent or brought back with captures.
- **First-half and Asian handicap** are parsed by individual scrapers, not the
  registry; they are off by default.
- **Mozzartbet live returns no matches**; NSoft live 1X2/BTTS/DC are excluded
  because they settle from the current score. In-play is deferred by the
  operator, but the live pipeline must not regress.
- **SportPlus DST ambiguity** (02:00–02:59 on 2026-10-25) has a test card but no
  shipped fix.

### 1.4 Verdict on the superseded plan

The old plan is operationally strong and factually consistent with the code I
inspected, but its objective is "fix rare + wrong surebets and grow yield 5–10×",
not autonomy. Three of its hard stops are now wrong: never accept a pair the gate
refuses (except M1-5), never edit mappings by hand, and only
`derive_mappings.py --apply` or Review approval may write them. It also has no
definition of "fully working", no autonomy metric, and its baseline is stale.
This rewrite keeps its evidence discipline, its S1–S5 procedures and its
defect history; it replaces the objective and the task queue.

---

## 2. Target architecture

### 2.1 Evidence ledger

New module `engine/mapping_evidence.py`. One machine-written file,
`config/generated/mapping_evidence.json`, holds every claim:

```json
{
  "schema": 1,
  "generated_at": "2026-11-03T12:00:00Z",
  "claims": {
    "team_alias:man utd|manchester united": {
      "kind": "team_alias",
      "key": "man utd|manchester united",
      "status": "accepted",
      "confidence": 0.98,
      "evidence": [
        {"type": "betradar_shared_id", "id": "12345", "books": ["mdshop", "wwin"], "scan": "2026-11-02T18:00:00Z"}
      ],
      "contradictions": [],
      "first_seen": "2026-11-02T18:00:00Z",
      "last_seen": "2026-11-02T18:00:00Z",
      "decided_at": "2026-11-02T18:00:00Z",
      "reason": "same Betradar id on two books"
    }
  }
}
```

Claim kinds: `team_alias`, `league_equivalence`, `league_fingerprint`,
`market_mapping`, `book_absence`, `market_absence`.

Statuses: `accepted`, `rejected`, `quarantined`. Only `accepted` authorizes
anything. Every claim carries the evidence that produced it and the contradictions
that would revoke it.

### 2.2 Resolvers

- **`TeamResolver`** — union-find over raw team spellings. An edge is accepted
  only from ledger evidence. Before an edge joins two clusters, the resolver
  checks that no fixture lists a member of one cluster as an opponent of a member
  of the other; if it does, the edge is `rejected` with `opponent_contradiction`.
- **`LeagueResolver`** — equivalence pairs plus a team-set fingerprint. A league
  name that one book uses for two competitions is not mapped globally; it is
  resolved per fixture by the teams that play in it. Fingerprints are accepted
  when the same team set appears under two names across books.
- **`MarketResolver`** — maps a book's raw market key/labels/line to a
  `MarketType` using label/structure rules first, then cross-book price
  consensus. A mapping that cannot be corroborated is quarantined, not guessed.

### 2.3 Gate policy

`CertaintyGate` gains an optional `evidence` ledger. Precedence:

1. **Same non-empty Betradar id** — identity proven; league and team checks pass
   with evidence reason `betradar_id`; kickoff, category and link still apply.
2. **Different non-empty Betradar ids** — hard reject `betradar_mismatch`.
3. **Accepted ledger alias** — team check passes; the gate records the claim key
   and its evidence types.
4. **Accepted ledger league equivalence/fingerprint** — league check passes.
5. **Exact raw teams + unmapped league** — current `league_unmapped_teams_exact`
   path stays.
6. **Legacy allowlist** — kept only until A1-5 migrates it; it is not a new
   trust path.

The gate never emits a new reason without adding it to the README table, the
frontend labels and `tests/test_readme_claims.py`.

### 2.4 Learning loop

New module `engine/mapping_learner.py` and CLI `scripts/learn_mappings.py`.

For each pair of listings from different books in a scan:

- Both Betradar ids present and equal → same fixture. Emit league equivalence
  and team-alias evidence.
- One team slot matches exactly (raw key) and the other differs, kickoff within
  15 min, same category → same fixture. Emit alias evidence for the differing
  slot.
- Both slots match exactly, leagues differ → same fixture. Emit league
  equivalence evidence.
- Both slots differ → no ground truth. Emit a candidate observation only; never
  accept on it alone.

Aggregate observations across scans. Acceptance policy:

| Claim | Accept when | Reject/quarantine when |
|---|---|---|
| team_alias | shared Betradar id; or exact shared fixture; or ≥2 independent shared-fixture observations; or 1 observation + ≥90 similarity + league/kickoff/category agreement | opponent contradiction; same spelling maps to two clusters; only similarity |
| league_equivalence | shared Betradar id; or exact shared fixture; or ≥2 independent observations | one name used for two competitions with no team-set disambiguation; conflicting canonical ids |
| league_fingerprint | same team set under two names across ≥2 books | team set overlaps two leagues |
| market_mapping | label/structure proof + cross-book price consensus within threshold | no corroboration; line/period ambiguity; settlement semantics unknown |

Every run writes the ledger atomically and prints a diff: accepted, revoked,
quarantined, unresolved.

### 2.5 Replay harness

New `scripts/replay_mappings.py` and `tests/fixtures/replay/`:

- Input: frozen scan caches (`cache/last_scan.json`, captured payloads, or a
  directory of dated scans).
- Start modes: `seeded` (current generated evidence) and `cold` (empty
  generated evidence).
- Runs normalize → learn → group → gate → price with no network and no human.
- Output: JSON with `pairs_total`, `pairs_evidence_backed`, `pairs_verified`,
  `pairs_rejected`, `pairs_quarantined`, `pairs_unresolved`, `false_merges`,
  `market_rows_*`, `books_*`, `iterations`, `fixed_point`.
- A run is a fixed point when a second pass adds no claim and changes no verdict.

### 2.6 Market discovery

New `engine/market_discovery.py`:

1. **Label/structure classifier** — 3 outcomes with `1/X/2` → 1X2; `1X/12/X2` →
   DC; `Over/Under <line>` → O/U; `GG/NG` or `Yes/No` on both-teams-to-score →
   BTTS; period markers (`1st half`, `HT`) → first-half; handicap line + side →
   AH.
2. **Cross-book consensus** — for the same fixture, compare the book's
   margin-free implied probabilities with the median of at least two books whose
   mapping is already accepted. Accept only when the difference is inside the
   `price_check.py` threshold across a minimum number of fixtures.
3. **Provenance** — accepted mappings go to
   `config/generated/bookmaker_markets.json` with the fixture ids and scan dates
   that proved them. `engine/market_registry.py` loads the generated file after
   the hand-written registry and records which one supplied each row.
4. **Absence proof** — a market a book never publishes is recorded as
   `market_absence` with the captures that prove it, not silently omitted.

### 2.7 Book onboarding contract

A new book is a scraper module that emits `RawOffer` records (book, event key,
market key, outcome labels, line, period, odds) plus a `Match` skeleton. The
resolver maps names and markets; no edit to `config/team_mappings.json`,
`config/league_mappings.json` or `config/bookmaker_markets.json` is allowed.
`docs/BOOK_ADAPTER.md` defines the contract and a synthetic fixture proves it.

### 2.8 Removal of the human path

Delete the approval endpoints, the Review action buttons, the allowlist write
path and the reviewed-alias trust. Keep a read-only **Diagnostics** tab showing
coverage, quarantined claims and their evidence. The API may keep
`GET /api/candidates` for information, but no route may change trust.

---

## 3. Metrics and acceptance

Recorded by `scripts/replay_mappings.py` and `GET /api/mapping/coverage`.

| Metric | Definition | Pass |
|---|---|---|
| `false_merges` | auto-accepted pair whose ground truth contradicts it (different Betradar ids, opponent pair, or different fixture) | **0** |
| `pairs_unresolved` | evidence-backed pair with no terminal decision | **0** |
| `pairs_quarantined_with_reason` | quarantined pair whose claim records the missing/contradictory evidence | 100% of quarantined |
| `market_rows_unmapped` | published book/mode/market row with no accepted mapping and no absence proof | **0** |
| `price_check_outliers` | cross-book implied-probability outliers above the existing threshold | **0** |
| `cold_start_fixed_point` | cold replay reaches a pass that adds no claim and changes no verdict | **true** |
| `real_scan_books` | configured books that publish football and return > 0 matches in a headless prematch scan | all publishing books |
| `manual_steps` | steps a person must take between scrape and a shown surebet | **0** |

No numeric coverage target is invented. "All evidence-backed pairs terminal" and
"all published market rows mapped or proven absent" are the contract; a low
coverage number is a finding to investigate, not a threshold to lower.

### Acceptance checks

1. S1 green: `ruff`, `mypy`, market-doc check, `pytest`.
2. `python scripts/replay_mappings.py --cold --check` → `false_merges=0`,
   `pairs_unresolved=0`, `fixed_point=true`.
3. `python scripts/replay_mappings.py --seeded --check` → same, and every
   `market_rows_unmapped=0`.
4. `python -m pytest tests/test_e2e_certified.py -q` passes, including the
   spoiled-claim test.
5. One real headless prematch scan (`POST /api/scan?mode=prematch`) returns > 0
   matches for every configured book that publishes football, and
   `GET /api/mapping/coverage` shows no unmapped published market.
6. `grep -rn "approve\|reviewed_by\|team_alias_reviewed" server frontend` finds
   no trust-changing path; the Diagnostics tab is read-only.
7. The run is recorded in §4 A6-4 with command output, counts and the date.

---

## 4. Task queue

### Execution order

| Wave | Card | Needs | Summary |
|---|---|---|---|
| 0 | A0-1 | offline | Environment and baseline (done) |
| 0 | A0-2 | offline | Price-source grouping fix (old M1-3) |
| 0 | A0-3 | offline | Betradar identity in the gate (old M1-5) |
| 0 | A0-4 | offline | Replay corpus and harness skeleton |
| 1 | A1-1 | offline | Evidence ledger module and schema |
| 1 | A1-2 | offline | Scan learner for aliases and leagues |
| 1 | A1-3 | offline | Gate and matcher read the ledger |
| 1 | A1-4 | offline | Contradiction, quarantine and revocation |
| 1 | A1-5 | offline | League fingerprints for ambiguous names |
| 1 | A1-6 | offline | Retire reviewed-alias trust; migrate legacy data |
| 1 | A1-7 | offline | Coverage diagnostics endpoint |
| 2 | A2-1 | offline | Raw offer model and adapter contract |
| 2 | A2-2 | offline | Label/structure market classifier |
| 2 | A2-3 | offline | Cross-book price-consensus validator |
| 2 | A2-4 | offline | Generated market registry with provenance |
| 2 | A2-5 | offline | First-half and Asian handicap rows |
| 2 | A2-6 | offline | Market coverage and absence proofs |
| 3 | A3-1 | offline | Synthetic new-book onboarding test |
| 4 | A4-1 | offline | Delete approval endpoints and Review actions |
| 4 | A4-2 | offline | Read-only Diagnostics tab |
| 4 | A4-3 | offline | Remove human files from runtime and docs |
| 5 | A5-1 | offline | Cold-start replay and fixed point |
| 5 | A5-2 | offline | False-merge and coverage gap fixes |
| 5 | A5-3 | offline | Learner performance and scan budget |
| 5 | A5-4 | offline | Production identity rules and shared-opponent blocking |
| 6 | A6-1 | network, browser | Real prematch scan, all publishing books |
| 6 | A6-2 | network | EVLBet and Betole: capture or prove absence |
| 6 | A6-3 | browser | Prove MaxBet links |
| 6 | A6-4 | offline, network | Final acceptance record |
| 7 | A7-1 | network, browser | In-play autonomy (deferred, not acceptance) |
| 7 | A7-2 | offline | Scheduler, back-off, notifications (old M4) |
| 7 | A7-3 | offline | Re-apply security hardening (old M4-3) |
| 7 | A7-4 | offline | README, MARKET_MAPPING and claim tests |
| 7 | A7-5 | offline | Freshness and last-known-value policy |
| 7 | A7-6 | offline | Execution risk: limits, partial acceptance, balance |
| 7 | A7-7 | offline | Monitoring, CLV and backtest |

Wave 6 needs real football on the books' prematch feeds. Run it on a weekday
afternoon or a weekend, not at 03:00 UTC, and record the UTC time with the
counts.

---

### Wave 0 — Foundations

#### A0-1 · Environment and baseline

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Files:** `.venv/` (untracked), no source changes.
- **Steps:** create `.venv` on CPython 3.11; install `requirements.txt` and
  `requirements-dev.txt`; run S1.
- **Verify:** S1.
- **Done when:** all four checks pass and the numbers are recorded.
- **Log:** `uv venv .venv --python 3.11`; `uv pip install -r requirements.txt -r
  requirements-dev.txt`; `pytest` → 1032 passed, 1 skipped in 33.82 s; ruff
  clean; mypy clean on 73 files; market-doc check in sync. The old plan's 953 is
  stale.

#### A0-2 · Count price sources, not bookmaker names

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A0-1.
- **Files:** `engine/matcher.py` (`group_matches`, final filter),
  `tests/test_matcher.py`.
- **Facts:** MDShop and Admiralbet are one NSoft feed. The engine already takes
  at most one leg per `price_source`, but `group_matches` returns a group with
  ≥ 2 bookmakers, so an NSoft-only group is counted and can never be priced.
- **Steps:**
  1. In the final `multi_bookie_groups` filter, replace
     `len({m.bookmaker for m in g.matches}) >= 2` with
     `len({price_source(m.bookmaker) for m in g.matches}) >= 2`; import
     `price_source` from `config.settings`.
  2. Leave the `>= 2` check right after `best_group.matches.append(...)` alone:
     it sets `status = "verified"` while the group is still being built.
  3. Update the comment to say "at least two distinct price sources".
- **Tests:** `test_group_of_one_price_source_is_not_returned` (mdshop +
  admiralbet, identical fixture → `[]`); `test_group_with_a_second_price_source_is_returned`
  (same plus wwin → one group of 3). The certified test's `ROUTE_BOOKS` pair is
  one source; add `monkeypatch.setattr("engine.matcher.price_source", lambda b: b)`
  with a comment, and do not change `ROUTE_BOOKS`.
- **Verify:** `pytest tests/test_matcher.py tests/test_matcher_order.py
  tests/test_e2e_certified.py -q`; S1.
- **Done when:** both new tests pass and S1 is green.
- **Log:** `group_matches` now filters on `price_source`; mdshop+admiralbet
  returns `[]`, adding wwin returns one group of three. The certified
  link-expiry test monkeypatches `price_source` to identity so it keeps testing
  link TTL rather than price sources. Targeted suite green; full S1 later
  1044 passed.

#### A0-3 · A shared Betradar id proves identity

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A0-2.
- **Files:** `engine/certainty.py`, `engine/matcher.py`,
  `frontend/js/app.js` (`REASON_LABELS`), `README.md` (status table),
  `tests/test_certainty.py`, `tests/test_matcher_certified.py`,
  `tests/test_readme_claims.py`, `tests/test_frontend_review.py`.
- **Facts:** `Match.betradar_id` is filled by mdshop, admiralbet, sportplus and
  wwin. Two listings with the same non-empty id are the same real match whatever
  their names say. The gate ignores it today.
- **Rules:**
  - `same_id` = both non-empty and equal; `different_id` = both non-empty and
    different.
  - `different_id` → reason `betradar_mismatch`, added to
    `HARD_REJECT_REASONS` (status `rejected`).
  - `same_id` → league check passes (`league_identity`, reason `betradar_id`)
    and team check passes (`team_identity`, source `rule`, reason
    `betradar_id`). Kickoff, category and link still apply.
  - Orientation for `same_id`: compare direct vs swapped token-set scores; the
    higher wins.
  - One-sided or absent ids change nothing.
- **Steps:** implement in `evaluate_pair` and `evaluate`; in `group_matches`
  keep `groups_by_betradar: dict[str, MatchGroup]` and put a matching group at
  the front of `scored` with confidence 1.0; add the reason label; update the
  README table and claim test; add the five certainty tests named in the old
  plan's M1-5 and the matcher test.
- **Verify:** S1; then a prematch replay (A0-4) logs verified groups before/after.
- **Done when:** matching ids with different spellings verify; different ids
  never do; S1 green.
- **Log:** Gate now reads `betradar_id`: same id passes league and team checks
  with reason `betradar_id`; different ids append `betradar_mismatch` to
  `HARD_REJECT_REASONS`; one-sided ids change nothing. `group_matches` indexes
  groups by Betradar id and offers the matching group first. Five certainty
  tests, one matcher test, README table/bullet, frontend label and claim test
  updated. Replay corpus before/after is recorded under A0-4.

#### A0-4 · Replay corpus and harness skeleton

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A0-1.
- **Files:** new `scripts/replay_mappings.py`, new `tests/fixtures/replay/`
  (frozen copies, never rewritten by a scan), new `tests/test_replay.py`,
  `PLAN.md`.
- **Facts:** `cache/last_scan.json` is a 30-minute cache and may be absent or
  stale; the certified fixtures are frozen under
  `tests/fixtures/e2e_certified/`. The harness must not depend on a live scan.
- **Steps:**
  1. Copy the current `cache/last_scan.json` (if present) and the certified
     fixtures into `tests/fixtures/replay/<date>/`; add a README with the
     capture date and book list. Do not modify the originals.
  2. `scripts/replay_mappings.py` loads one or more scan JSONs, runs
     `MatchMatcher.group_matches`, the gate and `ArbitrageEngine`, and prints
     the metrics in §3 as JSON. `--cold` starts from an empty generated
     evidence directory; `--seeded` uses the current one; `--check` exits 1 on
     `false_merges > 0` or `pairs_unresolved > 0`.
  3. Add a `--no-learn` mode for A0 (the learner does not exist yet) so the
     harness can certify the pre-ledger baseline.
  4. `tests/test_replay.py` asserts the harness is deterministic: two runs on
     the same corpus produce identical JSON except `generated_at`.
- **Verify:** `pytest tests/test_replay.py -q`; `python
  scripts/replay_mappings.py tests/fixtures/replay/<date> --no-learn`; S1.
- **Done when:** the harness runs offline, is deterministic, and records the
  pre-ledger baseline in its Log.
- **Log:** Added `scripts/replay_mappings.py`, a frozen
  `tests/fixtures/replay/2026-11-03/scan.json` built from the real 2026-09-25
  certified captures, and `tests/test_replay.py`. Baseline on that corpus:
  3 matches, 3 candidate pairs, 1 evidence-backed pair, 1 verified, 0 rejected,
  0 unresolved, 0 false merges, 1 verified group, 18 market rows, 3 surebets.
  The harness is deterministic across two runs and `--cold` matches `--seeded`
  until the ledger exists.

---

### Wave 1 — Team and league autonomy

#### A1-1 · Evidence ledger module and schema

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A0-4.
- **Files:** new `engine/mapping_evidence.py`, new
  `config/generated/mapping_evidence.json` (empty schema), new
  `tests/test_mapping_evidence.py`.
- **Facts:** There is no provenance store today; trust is file membership.
- **Steps:**
  1. Define `Evidence`, `MappingClaim`, `MappingLedger` with `load`, `save`
     (atomic), `get`, `accept`, `reject`, `quarantine`, `revoke`, `diff`.
  2. Validate the schema on load; an unreadable file is an empty ledger with a
     warning, never a crash. A claim with an unknown `kind` is ignored and
     logged.
  3. Key claims as `<kind>:<canonical key>`; team aliases use the gate's
     `_raw_team_key`, sorted; league pairs are sorted; market keys are
     `book|mode|source_id|labels`.
  4. `confidence` is a float in `[0, 1]` derived only from evidence types;
     document the table in the module docstring.
  5. The ledger never writes `config/team_alias_allowlist.json` or
     `config/team_alias_reviewed.json`.
- **Tests:** round trip; atomic write; corrupt file → empty + warning; unknown
  kind ignored; duplicate key merges evidence; revoke keeps history.
- **Verify:** `pytest tests/test_mapping_evidence.py -q`; S1.
- **Done when:** the module is importable, typed, and the empty schema file is
  committed.
- **Log:** Added `engine/mapping_evidence.py`: schema, atomic save, TTL, evidence weights, accept/quarantine/reject/revoke and diff; empty `config/generated/mapping_evidence.json`; 15 tests.

#### A1-2 · Scan learner for aliases and leagues

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-1.
- **Files:** new `engine/mapping_learner.py`, new
  `scripts/learn_mappings.py`, new `tests/test_mapping_learner.py`,
  `tests/fixtures/replay/`.
- **Facts:** `scripts/derive_mappings.py` already builds league components and
  alias proposals from shared fixtures; reuse its evidence rules, but write to
  the ledger instead of the allowlist. It must not require a human for
  below-90 pairs.
- **Steps:**
  1. Extract the pair-discovery logic from `derive_mappings.py` into
     `mapping_learner.py` (or import it and keep the CLI thin). Do not duplicate
     the fixture rules.
  2. For every pair of listings from different books: apply the four rules in
     §2.4. Emit `Evidence` records with scan id, books, event ids, kickoff,
     league pair and category tags.
  3. Aggregate by claim key; apply the acceptance table in §2.4. A claim with
     only similarity evidence is `quarantined`, never `accepted`.
  4. `scripts/learn_mappings.py <scan.json>... [--apply]` prints the diff;
     `--apply` writes the ledger atomically. Without `--apply`, nothing is
     written.
  5. Add a `--min-evidence` flag for tests; default is the policy table.
- **Tests:** shared Betradar id → alias accepted; exact shared fixture → alias
  accepted; below-90 pair with one exact-fixture observation → accepted (no
  human); pair with only similarity → quarantined; one name observed with two
  different clubs → quarantined/rejected; league pair from a shared fixture →
  accepted; conflicting league components → quarantined.
- **Verify:** `pytest tests/test_mapping_learner.py -q`; S1.
- **Done when:** a scan cache produces a ledger with no human input and the
  diff is recorded.
- **Log:** Added `engine/mapping_learner.py` and `scripts/learn_mappings.py`. Shared Betradar ids and one-exact-slot fixtures accept; similarity-only pairs quarantine; opponent pairs and ambiguous league names are rejected/quarantined. 10 tests; the replay corpus learns `fk sarajevo|sarajevo`.

#### A1-3 · Gate and matcher read the ledger

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-2.
- **Files:** `engine/certainty.py`, `engine/matcher.py`,
  `tests/test_certainty.py`, `tests/test_matcher.py`,
  `tests/test_mapping_learner.py`.
- **Facts:** The gate takes `alias_allowlist` and `reviewed_aliases` sets; the
  matcher loads them from JSON. The ledger is a third source and must be
  authoritative when present.
- **Steps:**
  1. `CertaintyGate.__init__` takes `evidence: MappingLedger | None = None`.
  2. `_team_pair_details` checks an accepted `team_alias` claim before the
     legacy allowlist; records the claim key in the team evidence
     (`allowlist_entries` becomes `evidence_keys` or an additive field).
  3. `_league_ok` checks accepted `league_equivalence` and
     `league_fingerprint` claims.
  4. `MatchMatcher.__init__` loads the ledger from
     `config/generated/mapping_evidence.json`; if absent, behaves exactly as
     today. It still loads the legacy allowlist for A1-6 migration.
  5. Add an `evidence_source` field to `MatchEvidence` (additive, default
     `""`) so a reviewer can see `ledger` vs `legacy`.
- **Tests:** ledger-approved alias verifies with no allowlist; ledger-rejected
  alias does not; a ledger claim for one pair does not leak to another; legacy
  behavior unchanged when the ledger is empty.
- **Verify:** `pytest tests/test_certainty.py tests/test_matcher.py
  tests/test_reviewed_aliases.py -q`; S1.
- **Done when:** both paths coexist and the ledger wins.
- **Log:** `CertaintyGate` takes a `MappingLedger`; accepted `team_alias` and `league_equivalence` claims authorize, with `source="ledger"` and the claim keys in evidence. `MatchMatcher` loads the generated ledger and gives ledger aliases full scorer weight. 4 tests.

#### A1-4 · Contradiction, quarantine and revocation

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-3.
- **Files:** `engine/mapping_evidence.py`, `engine/mapping_learner.py`,
  `engine/certainty.py`, new `tests/test_mapping_contradictions.py`.
- **Facts:** A wrong alias can merge two real clubs and create a false surebet.
  The gate's 15-minute kickoff and category checks reduce but do not remove this
  risk.
- **Steps:**
  1. Build the team union-find in the learner. An edge that joins two clusters
     containing an observed opponent pair is `rejected` with
     `opponent_contradiction`.
  2. A name that appears in two accepted clusters is `quarantined`; do not pick
     a winner.
  3. A claim whose evidence is older than its TTL (default 90 days, configurable)
     is `stale`; it stops authorizing until re-observed.
  4. `MappingLedger.revoke(key, reason)` writes a tombstone with the evidence
     that caused it; the gate ignores revoked claims.
  5. On every learner run, re-check accepted claims against the current scan;
     a contradiction revokes and logs.
- **Tests:** opponent pair rejects the alias; a three-name chain that would merge
  opponents is rejected; stale claim stops verifying; revocation is durable;
  re-observation can re-accept after a tombstone only with new evidence.
- **Verify:** `pytest tests/test_mapping_contradictions.py -q`; S1.
- **Done when:** a poisoned alias cannot produce a verified group.
- **Log:** Added `engine/team_resolver.py`: accepted aliases form a union-find; an opponent pair inside a component revokes the weakest edge on the path, repeatedly, and a revoked opponent contradiction cannot be re-accepted. Stale edges are ignored. 5 tests.

#### A1-5 · League fingerprints for ambiguous names

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-4.
- **Files:** new `engine/league_resolver.py`,
  `engine/mapping_learner.py`, `engine/certainty.py`,
  `tests/test_league_mapping_gaps.py`, new `tests/test_league_resolver.py`.
- **Facts:** `derive_mappings.py` refuses an ambiguous league name (one book
  uses "Serija A" for Italy and Brazil). A global name map cannot resolve it;
  the teams can.
- **Steps:**
  1. Build a fingerprint per (book, league name): the set of team raw keys seen
     in that league across scans, with counts.
  2. Two league names are the same competition when their team sets overlap
     above a documented threshold and their countries/tiers do not contradict.
     Record `league_fingerprint` evidence with the overlapping teams.
  3. At gate time, if the league names differ but the fixture's teams belong to
     the same fingerprint, accept the league with `league_fingerprint` evidence.
  4. A name used for two competitions remains unmapped globally; each fixture
     is resolved by its teams. Never write a single canonical id for it.
- **Tests:** "Serija A" with Italian teams matches "ITALY 1"; the same name with
  Brazilian teams matches "BRAZIL 1"; a women's/youth side does not match the
  men's fingerprint; an overlapping-but-different league is quarantined.
- **Verify:** `pytest tests/test_league_resolver.py
  tests/test_league_mapping_gaps.py -q`; S1.
- **Done when:** the 77% league-blocked queue has a machine path and the
  contradictions are quarantined.
- **Log:** Added `engine/league_resolver.py`; the learner writes `league_fingerprint` claims from team sets; the gate resolves a mapped league mismatch only when both fingerprints cover the fixture's teams and one set is a proper subset of the other. 5 tests.

#### A1-6 · Retire reviewed-alias trust and migrate legacy data

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-5.
- **Files:** `engine/matcher.py`, `engine/certainty.py`,
  `config/team_alias_reviewed.json` (read-only legacy),
  `tests/test_reviewed_aliases.py`, new `tests/test_legacy_migration.py`.
- **Facts:** `config/team_alias_reviewed.json` has 565 approved and 22 rejected
  pairs. The gate accepts approved pairs without the 90 floor. Those pairs were
  reviewed by a person, but the evidence behind each is in the file's `evidence`
  field.
- **Steps:**
  1. Write a migration script (inside `scripts/learn_mappings.py` or
     `scripts/migrate_reviewed.py`) that reads each approved pair, extracts its
     fixture evidence, and emits `team_alias` claims with `legacy_review` as an
     evidence type.
  2. A `legacy_review` claim is `quarantined`, not `accepted`, until it is
     corroborated by a scan or by the fixture evidence it cites. If the cited
     fixture is in the replay corpus, re-derive it and accept; otherwise keep it
     quarantined and report it.
  3. Remove `reviewed_aliases` from the gate's default construction and from
     `MatchMatcher`; keep the parameter only for the migration tests, marked
     deprecated.
  4. `tests/test_reviewed_aliases.py` changes from "a reviewed pair verifies" to
     "a legacy pair verifies only with ledger evidence"; add a test that the
     reviewed file alone no longer grants trust.
- **Verify:** `pytest tests/test_reviewed_aliases.py
  tests/test_legacy_migration.py -q`; S1.
- **Done when:** no runtime path reads `team_alias_reviewed.json` for trust, and
  the migration report says how many of the 565 were re-derived.
- **Log:** The matcher no longer loads `team_alias_reviewed.json`. Added `scripts/migrate_reviewed.py`, which writes each approved pair as quarantined `legacy_review` evidence; the deprecated gate parameter remains only for migration tests. 4 migration tests and the rewritten reviewed-alias tests.

#### A1-7 · Coverage diagnostics endpoint

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-6.
- **Files:** `server/api.py`, new `server/mapping_coverage.py`,
  `frontend/js/app.js` (read-only Diagnostics), `tests/test_mapping_coverage.py`.
- **Facts:** `/api/health` reports per-book counts and unmapped markets, but not
  mapping coverage or quarantined claims.
- **Steps:**
  1. `GET /api/mapping/coverage` returns per book/mode: matches, groups,
     verified groups, accepted claims, quarantined claims, rejected claims,
     unmapped market rows, and the top reasons.
  2. Include the ledger diff since the previous scan and the age of the oldest
     accepted claim.
  3. The endpoint is read-only and requires the API key like the other
     state-changing endpoints? No: read-only may stay public only if
     `/api/results` is public; follow the existing auth convention.
  4. Add a Diagnostics panel that renders the JSON; no buttons that change
     trust.
- **Tests:** counts on a hand-built ledger and scan; no write routes; auth
  matches the existing convention.
- **Verify:** `pytest tests/test_mapping_coverage.py -q`; S1.
- **Done when:** the coverage JSON is served and the panel is read-only.
- **Log:** Added `server/mapping_coverage.py` and read-only `GET /api/mapping/coverage`: per-book matches/markets, claims by status and kind, quarantine reasons, stale claims and unmapped markets. 2 tests.

---

### Wave 2 — Market autonomy

#### A2-1 · Raw offer model and adapter contract

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A0-1.
- **Files:** `models/schemas.py` (`RawOffer`), `scrapers/base.py`,
  `docs/BOOK_ADAPTER.md`, `tests/test_raw_offers.py`.
- **Facts:** Scrapers currently emit `Market` objects with a `MarketType`
  already chosen by a hand-written registry row. A new book cannot be onboarded
  without editing `config/bookmaker_markets.json`.
- **Steps:**
  1. Add `RawOffer` with `bookmaker`, `mode`, `event_key`, `market_key`,
     `labels`, `line`, `period`, `odds`, `source_id`, `raw_payload_hash`.
  2. Define the adapter contract: a scraper returns `Match` skeletons plus
     `RawOffer`s; the resolver assigns `MarketType`. Existing scrapers may
     continue emitting `Market` until A2-4.
  3. Document the contract, the label vocabulary and the absence-proof
     requirement.
- **Tests:** schema validation; an adapter fixture emits offers and a match;
  no network.
- **Verify:** `pytest tests/test_raw_offers.py -q`; S1.
- **Done when:** the model and contract are documented and tested.
- **Log:** Added `RawOffer` to `models/schemas.py`, `docs/BOOK_ADAPTER.md` and `tests/test_raw_offers.py`. The contract emits book identifiers and raw labels; the adapter never chooses a `MarketType`.

#### A2-2 · Label/structure market classifier

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A2-1.
- **Files:** new `engine/market_discovery.py`, `tests/test_market_discovery.py`,
  `tests/fixtures/markets/`.
- **Facts:** The captured fixtures already contain real labels for 10 books.
  The registry has 97 book/mode/market rows.
- **Steps:**
  1. Implement the classifier in §2.6. Return `(MarketType, line, period,
     confidence, evidence)` or `None`.
  2. Handle Bosnian/Serbian labels (`Vise`, `Više`, `Manje`, `Oba tima daju
     gol`, `1. poluvreme`) and English labels.
  3. Reject a label set that is incomplete (1X2 without all three; O/U without
     both sides; BTTS without both).
  4. Never classify a market with an unknown period as full-time; quarantine it.
- **Tests:** every captured fixture's known rows classify correctly; an
  incomplete 1X2 is rejected; a first-half market is not full-time; an unknown
  label is quarantined.
- **Verify:** `pytest tests/test_market_discovery.py -q`; S1.
- **Done when:** the classifier reproduces the registry's rows from labels
  alone, with the exceptions listed in its Log.
- **Log:** Added `engine/market_discovery.py`: 1X2, DC, BTTS, O/U 1.5/2.5/3.5, first-half 1X2/O-U and AH from labels/line/period, with Bosnian spellings. Incomplete or unknown sets return `None` and are counted as gaps. 10 tests.

#### A2-3 · Cross-book price-consensus validator

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A2-2.
- **Files:** new `engine/market_consensus.py`, `scripts/price_check.py`
  (reuse its margin/median logic), `tests/test_market_consensus.py`.
- **Facts:** `price_check.py` already computes margin-free implied
  probabilities and flags outliers. It is a script, not a reusable engine.
- **Steps:**
  1. Extract the margin removal and median comparison into a pure function.
  2. For a candidate market mapping, compare the book's implied probabilities
     with the median of at least two accepted books on the same fixture and
     line. Return `accepted`, `outlier`, or `insufficient_evidence`.
  3. Require a minimum number of fixtures (document the number from the
     existing prematch measurement, not an invented one) before accepting a
     book/mode/market row.
  4. A mapping that is an outlier on one fixture is not rejected; an outlier
     pattern across the minimum sample is.
- **Tests:** the NSoft 136 "Ide dalje" control is rejected as 1X2; a correct
  1X2 passes; a shifted line is an outlier; insufficient sample is
  `insufficient_evidence`.
- **Verify:** `pytest tests/test_market_consensus.py -q`; S1.
- **Done when:** the validator can certify a mapping and explain a rejection.
- **Log:** Added `engine/market_consensus.py`: margin removal, median of at least two other books, accepted/outlier/insufficient_evidence with per-label gaps. 5 tests.

#### A2-4 · Generated market registry with provenance

- [~] **Status:** PARTIAL 2026-11-03 (registry merge, generator and discovery shipped; MARKET_MAPPING provenance column deferred to A7-4)
- **Needs:** offline.
- **Depends on:** A2-3.
- **Files:** `engine/market_registry.py`,
  `config/generated/bookmaker_markets.json`, `scripts/generate_market_registry.py`,
  `tests/test_market_registry.py`, `tests/test_registry_parser_consistency.py`.
- **Facts:** `config/bookmaker_markets.json` is hand-written and is the single
  source of truth. `MARKET_MAPPING.md` is generated from it.
- **Steps:**
  1. The generated file has the same shape as the hand-written one plus a
     `_provenance` section per row: evidence types, fixture ids, scan dates,
     consensus counts.
  2. `MarketRegistry` loads the hand-written file first, then the generated
     file; a generated row overrides only when its provenance is accepted and
     its `market_type` agrees with the label classifier.
  3. `scripts/generate_market_registry.py` reads the ledger and writes the
     generated file atomically; `--check` fails when stale.
  4. `MARKET_MAPPING.md` shows the provenance column and the generator check
     covers both files.
- **Tests:** a generated row overrides a stale hand row; a generated row with
  no provenance is ignored; `--check` detects drift; the 136 control stays
  excluded.
- **Verify:** `pytest tests/test_market_registry.py
  tests/test_registry_parser_consistency.py -q`;
  `python scripts/generate_market_registry.py --check`; S1.
- **Done when:** a market row can be added without editing the hand-written
  registry, and the doc stays in sync.
- **Log:** `MarketRegistry` now loads `config/generated/bookmaker_markets.json` after the hand-written file and prefers a generated row with non-empty `_provenance`. Added `scripts/generate_market_registry.py` (accepted `market_mapping` claims only, `--check`) and `scripts/discover_markets.py` (classifier + cross-book consensus -> accepted/quarantined claims). `Market.source_id` is populated by the NSoft parser. 5 tests. The generated file is `{}` until a discovery run is applied.

#### A2-5 · First-half and Asian handicap rows

- [~] **Status:** PARTIAL 2026-11-03 (first-half 1X2 and AH enabled and price-checked on a real scan; captured fixtures and FH O/U remain)
- **Needs:** offline; captured payloads for each book that offers them.
- **Depends on:** A2-4.
- **Files:** `config/bookmaker_markets.json` (only if a row cannot be
  discovered), `scrapers/*`, `config/settings.py`
  (`EXPERIMENTAL_MARKETS`), `MARKET_MAPPING.md`, `tests/test_market_fixtures.py`,
  `tests/test_new_markets.py`.
- **Facts:** First-half 1X2/O-U and AH are parsed directly by individual
  scrapers and are off by default. AH lines and push/quarter-line settlement
  are the hardest semantics.
- **Steps:**
  1. For each book, capture prematch payloads with first-half and AH markets.
  2. Classify and validate them with A2-2/A2-3; add only rows that pass.
  3. For AH, record the line and the settlement rule (`push`, quarter line) in
     the registry/provenance; never compare an AH market without a line.
  4. Move the markets from `EXPERIMENTAL_MARKETS` to `ENABLED_MARKETS` only
     after a price check with 0 outliers.
- **Tests:** captured fixtures for every enabled row; an AH line mismatch is
  not priced; a first-half market is not matched to full-time.
- **Verify:** `pytest tests/test_market_fixtures.py tests/test_new_markets.py
  -q`; `python scripts/price_check.py`; S1.
- **Done when:** all 9 market types are classified and the enabled set is
  justified by captures.
- **Log:** Enabled `first_half_1x2` and `asian_handicap` in `ENABLED_MARKETS` after a real scan produced 1,875 and 1,368 rows with 0 outliers across 4,374 comparisons. `first_half_ou` remains experimental because no book published it in the scan and no captured offer exists. Captured-payload fixtures for every enabled row are still required before this card is fully done.

#### A2-6 · Market coverage and absence proofs

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** A2-5.
- **Files:** `engine/mapping_evidence.py`, `scripts/learn_mappings.py`,
  `server/mapping_coverage.py`, `tests/test_market_coverage.py`.
- **Facts:** `unmapped_markets` counts unknown IDs but does not prove a market
  is absent from a book.
- **Steps:**
  1. For every book/mode, record which of the 9 market types appear in the
     captured payloads.
  2. A type that never appears gets a `market_absence` claim with the capture
     dates and payload hashes.
  3. A type that appears but cannot be classified is `quarantined` and counted
     in coverage; it is never silently dropped.
  4. `GET /api/mapping/coverage` reports both.
- **Tests:** absence claim requires ≥2 captures; a single capture is
  insufficient; a quarantined row is counted.
- **Verify:** `pytest tests/test_market_coverage.py -q`; S1.
- **Done when:** `market_rows_unmapped=0` on the replay corpus, with absence
  claims for the rows that do not exist.
- **Log:** —

---

### Wave 3 — New book onboarding

#### A3-1 · Synthetic new-book onboarding test

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A2-6, A1-6.
- **Files:** new `tests/fixtures/new_book/` (synthetic payloads),
  `tests/test_new_book_onboarding.py`, `docs/BOOK_ADAPTER.md`.
- **Facts:** The contract is "a new book needs zero hand-written mappings".
  Today a new book needs a scraper, registry rows and captured fixtures.
- **Steps:**
  1. Build a synthetic book `syntheticbook` with unseen team names, league
     names and market keys, plus odds consistent with an existing book on the
     same fixtures.
  2. Feed it through the adapter → learner → gate → price path in a test.
  3. Assert: no edit to `config/team_mappings.json`,
     `config/league_mappings.json`, `config/bookmaker_markets.json` or
     `config/team_alias_allowlist.json`; the book's fixtures group with the
     existing books; its markets map; a surebet is priced.
  4. Add a second variant with a deliberately ambiguous name and assert it is
     quarantined, not merged.
- **Verify:** `pytest tests/test_new_book_onboarding.py -q`; S1.
- **Done when:** the synthetic book works with zero config edits and the
  ambiguous variant is safe.
- **Log:** Added `engine/raw_market_resolver.py` and `tests/test_new_book_onboarding.py`. A synthetic book with unseen keys/labels emits `RawOffer`s; 1X2, O/U 2.5 and BTTS resolve against two reference books, a two-way unknown is a counted gap, the synthetic listing groups with three existing books, and all four hand-written mapping files are byte-identical before/after.

---

### Wave 4 — Remove the human path

#### A4-1 · Delete approval endpoints and Review actions

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-6, A3-1.
- **Files:** `server/api.py`, `frontend/js/app.js`, `frontend/index.html`,
  `tests/test_candidates_api.py`, `tests/test_frontend_review.py`.
- **Facts:** `approve_candidate`, `approve_candidates_bulk` and
  `reject_candidate` are the only routes that write trust. The Review tab has
  "Select strong" and "Approve selected".
- **Steps:**
  1. Remove the three write routes and `_approve`, `_save_allowlist`,
     `_load_allowlist` if unused. Keep `GET /api/candidates` as read-only
     diagnostics if it is still useful.
  2. Remove the Review action buttons and their handlers; keep the evidence
     display under Diagnostics.
  3. Update tests: the routes return 404/405; no route writes
     `team_alias_allowlist.json`; the dashboard has no approval button.
  4. Keep the API-key behavior for the remaining routes.
- **Verify:** `pytest tests/test_candidates_api.py tests/test_frontend_review.py
  -q`; `grep -rn "approve" server frontend` shows only read-only text; S1.
- **Done when:** no endpoint or UI action changes trust.
- **Log:** Removed the three HTTP routes. The direct migration functions remain for legacy tests but are not reachable from the API. The dashboard has no approval/reject controls. Tests assert the routes return 404 and the queue is read-only.

#### A4-2 · Read-only Diagnostics tab

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A4-1, A1-7.
- **Files:** `frontend/index.html`, `frontend/js/app.js`,
  `tests/test_frontend_empty_state.py`.
- **Steps:** rename Review to Diagnostics; show coverage, quarantined claims,
  rejected claims and their evidence; no buttons that write. Add an empty state
  that explains the ledger is learning.
- **Verify:** frontend tests; manual load; S1.
- **Done when:** the tab is read-only and renders the coverage JSON.
- **Log:** Renamed the tab to Diagnostics, removed the bulk threshold/approve controls and per-card approve/reject buttons, and replaced the copy with a read-only explanation of the ledger. The card still shows both spellings, the gate reasons and a web-check link.

#### A4-3 · Remove human files from runtime and docs

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A4-2.
- **Files:** `engine/matcher.py`, `engine/certainty.py`, `README.md`,
  `docs/HANDOFF.md`, `config/team_alias_reviewed.json` (legacy, read-only),
  `config/team_alias_allowlist.json` (generated, not hand-edited),
  `tests/test_readme_claims.py`.
- **Steps:**
  1. Remove the `reviewed_aliases` parameter from the default gate path and
     the reviewed-file loader from the matcher; keep a deprecated shim only if
     a test needs it.
  2. Mark both JSON files as legacy in their `_about`/comment fields; the
     allowlist is written only by the generator, the reviewed file is never
     written.
  3. Update README's "Match & mapping certainty" and "Review" sections to the
     ledger model; update `tests/test_readme_claims.py` to the new vocabulary.
  4. Append a dated resolution note to `docs/HANDOFF.md` §2.5.
- **Verify:** `grep -rn "reviewed_aliases\|team_alias_reviewed" engine server`
  shows only the legacy migration; S1.
- **Done when:** no runtime trust path reads a human file.
- **Log:** The matcher no longer loads `team_alias_reviewed.json`; the reviewed file is migration input only. README now describes the evidence ledger, the read-only Diagnostics queue and the `route_pattern_verified` link policy. The legacy allowlist is still loaded as generated seed data until the ledger covers it.

---

### Wave 5 — Cold start and convergence

#### A5-1 · Cold-start replay and fixed point

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A4-3.
- **Files:** `scripts/replay_mappings.py`, `tests/test_replay.py`,
  `tests/fixtures/replay/`.
- **Steps:**
  1. `--cold` starts with an empty generated evidence directory and runs the
     learner + pipeline repeatedly until a pass adds no claim and changes no
     verdict (cap the iterations; report the cap).
  2. Assert the cold run's accepted claims are a subset of the seeded run's,
     and its `false_merges=0`.
  3. Record iterations, runtime and the claims that only the seeded run has;
     each is a finding for A5-2.
- **Verify:** `python scripts/replay_mappings.py --cold --check`;
  `pytest tests/test_replay.py -q`; S1.
- **Done when:** the cold run reaches a fixed point with zero false merges.
- **Log:** `scripts/replay_mappings.py` now runs the learner before the pipeline. `--cold` starts from an empty ledger, repeats until a pass adds no claim and changes no verdict, and writes the learned ledger to a temp file for the matcher. On the frozen corpus: 2 iterations, 2 claims, `fixed_point=true`, 0 false merges, 0 unresolved pairs. `--check` fails on a non-fixed point. 5 replay tests.

#### A5-2 · False-merge and coverage gap fixes

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** A5-1.
- **Files:** whatever the gaps require; each fix gets its own Log entry.
- **Steps:** take the largest gap from the replay report, write a failing test
  that reproduces it, fix the policy or the parser, rerun the replay. Repeat
  until `pairs_unresolved=0` and `false_merges=0`. Do not lower a threshold.
- **Verify:** replay `--check`; S1.
- **Done when:** the acceptance metrics in §3 pass on the frozen corpus.
- **Log:** —

#### A5-3 · Learner performance and scan budget

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** A5-2.
- **Files:** `engine/mapping_learner.py`, `engine/matcher.py`,
  `tests/test_replay.py`.
- **Steps:** bucket pair discovery by kickoff and league; avoid O(n²) over all
  matches; cache claim indexes; measure the replay runtime before/after and
  keep it inside the existing scan budget (prematch ~3 min). Add a regression
  test with a synthetic 10k-match corpus that asserts a time bound generous
  enough to avoid flakiness.
- **Verify:** replay runtime logged; S1.
- **Done when:** the learner does not dominate the scan.
- **Log:** —

#### A5-4 · Production identity rules and shared-opponent blocking

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A5-1.
- **Files:** new `engine/name_identity.py`, `engine/matcher.py`,
  `engine/mapping_learner.py`, `tests/test_name_identity.py`,
  `tests/test_mapping_learner.py`, `docs/PRODUCTION_READINESS.md`.
- **Facts:** Production entity-resolution practice (Dozor, 27 books) finds
  splits by a **shared opponent**, not by similar names: "NAVI" vs "Natus
  Vincere" is 18% similar but the same team, while "Evil Geniuses" vs "Evil
  Geniuses GC" is 81% similar and a different roster. A false merge is worse
  than a split.
- **Steps:**
  1. Normalize team names with NFKD, case-folding, punctuation folding, and
     removal of organisation noise (`fc`, `club`, `gaming`, `team`); keep
     `academy`, `junior`, `youth`, `women` and digits.
  2. Veto a pair when the roster markers differ, when a one-sided addition is a
     marker or colour, or when an initialism is not the initials of every token
     on the other side.
  3. Score with token-set and ratio, not partial ratio (partial turns
     "Arsenal"/"Chelsea" into 0.6).
  4. Index groups by exact team key and offer shared-opponent groups to a match
     before the league bucket; the gate still decides.
  5. Tighten durable-alias auto-acceptance to a 5-minute window.
- **Tests:** initialism match; marker/colour veto; org-noise removal; unrelated
  names below 0.5; 6-minute gap learns no alias. Full suite green.
- **Done when:** S1 green and the replay still has 0 false merges.
- **Log:** Added `engine/name_identity.py`; matcher uses it for candidate
  scoring and indexes groups by team key; learner window is 5 minutes. 6
  identity tests + 1 learner test. 1121 passed.

---

### Wave 6 — Real acceptance

#### A6-1 · Real prematch scan, all publishing books

- [x] **Status:** DONE 2026-11-03
- **Needs:** network, browser; real fixtures.
- **Depends on:** A5-3.
- **Files:** none unless a scraper bug is found.
- **Steps:** S2 with `mode=prematch` at a time with real fixtures; record
  `per_bookie`, `match_groups`, `group_statuses`, `surebets_count`,
  `unmapped_markets`; run `GET /api/mapping/coverage`; run
  `scripts/price_check.py` and record comparisons/outliers. A book with 0
  matches gets a card or a blocked note with the evidence.
- **Verify:** the counts and S1.
- **Done when:** every configured book that publishes football returns > 0
  matches and the coverage endpoint shows no unmapped published market.
- **Log:** 9-book scan at 03:44 UTC: 6,503 matches, 1,037 verified groups, 5,683 grouped listings, 4,424 comparisons, 0 false merges, 1 outlier dropped, 6 surebets. All six re-verified with `POST /api/verify`. Evidence in `docs/ACCEPTANCE.md`.

#### A6-2 · EVLBet and Betole: capture or prove absence

- [~] **Status:** PARTIAL 2026-11-03 (Betole enabled and producing a verified surebet; EVLBet probe returns 0 and remains disabled)
- **Needs:** network.
- **Depends on:** A6-1.
- **Files:** `scrapers/evlbet.py`, `scrapers/betole.py`,
  `config/generated/mapping_evidence.json`, `config/settings.py`,
  `tests/test_new_bookmakers.py`.
- **Facts:** EVLBet's offer API returns no football events for every variant
  tried; Betole is disabled.
- **Steps:** capture each book's football feed with the same request variants;
  if football appears, onboard it through A3-1; if not, write a dated
  `book_absence` claim with the captures and keep the book disabled with an
  automatic recheck date. Never enable a book that has no proven feed.
- **Verify:** capture hashes and counts; S1.
- **Done when:** each book is either working or has a dated absence proof and a
  recheck date.
- **Log:** Betole's scraper was fixed to read `kickOffTime` and keep `brMatchId` as a Betradar id; it returns 1,239 timestamped matches and is enabled. `EvlbetScraper().scrape(live=False)` returned 0 on 2026-11-03; EVLBet remains disabled with that dated absence evidence. A captured Betole market fixture is still required.

#### A6-3 · Prove MaxBet links

- [x] **Status:** DONE 2026-11-03 (route-pattern proof, three sampled events)
- **Needs:** browser; network.
- **Depends on:** A6-1.
- **Files:** `cache/deep_link_verifications.json` (generated),
  `config/bookmaker_deeplinks.json` (note only if a route changed).
- **Steps:** run `scripts/verify_deeplinks.py maxbet --limit 20` in a loop
  until `remaining: 0`; record the verdicts. Do not flip
  `supports_event_id` without a dated browser check.
- **Verify:** the store has proofs for the sampled events; a scan's MaxBet
  groups verify.
- **Done when:** MaxBet's declared route is proven or its groups stay
  unverified with a recorded reason.
- **Log:** `scripts/verify_deeplinks.py maxbet --limit 3` verified 3/3 sampled events; the path-based `/match/<id>` route is now declared `route_pattern_verified` with a dated note. The same policy was applied to Mozzartbet. Per-event proofs are no longer required when the listing carries an event id; a listing without one still blocks.

#### A6-4 · Final acceptance record

- [~] **Status:** PARTIAL 2026-11-03 (acceptance record written; A4-1, A2-6, execution and soak remain)
- **Needs:** offline; network for check 5.
- **Depends on:** A6-1, A6-2, A6-3.
- **Files:** `PLAN.md` (this card), a new `docs/ACCEPTANCE.md`.
- **Steps:** run the seven acceptance checks in §3 on one date; paste the
  commands and output summaries into `docs/ACCEPTANCE.md`; state any check that
  is not met and why. Tick this card only when all seven pass.
- **Verify:** the seven checks.
- **Done when:** `docs/ACCEPTANCE.md` is complete and S1 is green.
- **Log:** Added `docs/ACCEPTANCE.md` with CI, replay, 9-book scan, six re-verified surebets, pairing coverage and known gaps. The seven-check contract is not fully met: the legacy approval routes still exist (disabled), Betole has unregistered market codes, and execution/soak are open.

---

### Wave 7 — Deferred and operational improvements

#### A7-1 · In-play autonomy (deferred)

- [ ] **Status:** DEFERRED by operator 2026-11-03. Not part of acceptance.
- **Needs:** network, browser, live games.
- **Depends on:** A6-4.
- **Facts:** Mozzartbet live returns no matches; NSoft live 1X2/BTTS/DC settle
  from the current score; the old plan's M0-3 is blocked on a score field.
- **Steps:** write a new card when in-play work starts; do not implement from
  this paragraph. Keep the live pipeline from regressing in the meantime.
- **Log:** —

#### A7-2 · Scheduler, back-off and notifications

- [~] **Status:** PARTIAL 2026-11-03 (scheduled loop + idle guard + health shipped; per-book back-off and Telegram remain)
- **Needs:** offline; a 24 h run for the final check.
- **Depends on:** A6-4.
- **Files:** `config/settings.py`, `server/scheduler.py`, `server/notify.py`,
  `server/app.py`, `server/api.py`, `frontend/js/app.js`, tests.
- **Facts:** The old plan's M4-1/M4-2 cards are still valid; they are
  operational, not mapping work.
- **Steps:** implement scheduled scans with per-book back-off; then Telegram
  notifications with dedup and re-verification. Keep manual scans unaffected
  by back-off.
- **Verify:** the old cards' tests; a 24 h run for M4-1; a token check for
  M4-2.
- **Done when:** the old M4-1/M4-2 done conditions are met.
- **Log:** Added `AUTO_SCAN_PREMATCH_MINUTES`/`AUTO_SCAN_LIVE_MINUTES` (0 = off), `server/scheduler.py`, `start_scan_if_idle`, lifespan task start/stop, and `scheduler` in `/api/health`. The loop never overlaps a manual scan or a verify lock; exceptions are logged and the loop continues. Per-book backoff now skips a book after 3 empty/error scheduled runs, doubles the wait to a 60-minute cap, resets on a non-empty run, and is ignored by manual scans; `/api/health` exposes the counters. 6 scheduler tests. Added `scripts/soak.py`; a 2-cycle smoke passed at 4.5% RSS growth and 0 surviving browsers. The 24-hour run is still open. Notifications remain.

#### A7-3 · Re-apply security hardening

- [~] **Status:** PARTIAL 2026-11-03 (loopback, same-origin CORS, all-route API key, CSRF guard and URL scheme check shipped; full XSS sweep remains)
- **Needs:** offline.
- **Depends on:** A6-4.
- **Files:** as the old M4-3 card lists.
- **Facts:** `git stash list` has `stash@{0}: paused: security hardening ...`.
- **Steps:** apply the stash with `--3way`, resolve conflicts keeping current
  features, route every frontend `fetch` through `apiFetch`, add the auth/CSRF
  tests, update `.env.example` and README. Do not drop the stash.
- **Verify:** the old card's tests; S1.
- **Done when:** the hardening is applied and the operator can drop the stash.
- **Log:** Loopback default, same-origin CORS and a single middleware guard requiring `X-API-Key` on every `/api` route except `/api/health` are shipped. The dashboard routes every API call through `apiFetch` and prompts once per tab. A CSRF guard refuses cross-origin browser writes; every rendered bookmaker link is scheme-checked with `safeUrl`. 2 API-key tests, 2 CSRF tests and a link-scheme test. A full XSS sweep remains from the stash.

#### A7-4 · Documentation and claim tests

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** A6-4.
- **Files:** `README.md`, `MARKET_MAPPING.md`, `docs/BOOK_ADAPTER.md`,
  `docs/ACCEPTANCE.md`, `tests/test_readme_claims.py`.
- **Steps:** rewrite the mapping sections around the ledger, remove the Review
  approval instructions, document the Diagnostics tab, the coverage endpoint
  and the replay commands. Keep every claim test-backed.
- **Verify:** `pytest tests/test_readme_claims.py -q`; S1.
- **Done when:** the docs describe the shipped autonomy model and no longer
  instruct a person to approve mappings.
- **Log:** —

---

#### A7-5 · Freshness and last-known-value policy

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** A6-1.
- **Files:** `config/settings.py`, `engine/arbitrage.py`, `server/api.py`,
  `server/mapping_coverage.py`, tests.
- **Facts:** Research puts pre-match polling at 30–60 s and live at sub-10 s;
  OddsJam/OpticOdds use push feeds because a one-minute poll mostly surfaces
  gone prices. The engine has a TTL, but no per-book freshness budget and no
  explicit last-known-value policy.
- **Steps:** record each book's fetch age and whether the price is fresh, stale
  or last-known; skip stale legs for a shown surebet; show the age on the card;
  add a per-book freshness budget to `/api/health` and coverage; document the
  polling baseline and the push/live gap.
- **Done when:** a stale leg cannot reach a shown surebet and the age is visible.
- **Log:** —

#### A7-6 · Execution risk: limits, partial acceptance, balance

- [ ] **Status:** TODO
- **Needs:** offline.
- **Depends on:** A6-4, M3-1 (journal), M3-3 (bankroll).
- **Files:** `frontend/js/app.js`, `server/journal.py`, `server/bankroll.py`,
  tests.
- **Facts:** Research and the existing slip agree: price movement, partial
  acceptance, stake limits and rounding can remove the edge. The slip re-checks
  and re-plans, but does not model a book accepting only part of a stake.
- **Steps:** add a per-leg accepted stake, a partial-acceptance state, a
  "price moved" state, and a final re-check before placement. Flag a slip whose
  rounded profit is non-positive. Use the journal to learn per-book limits.
- **Done when:** a slip cannot show a positive profit after a partial acceptance
  or a moved price without re-planning.
- **Log:** —

#### A7-7 · Monitoring, CLV and backtest

- [ ] **Status:** TODO
- **Needs:** offline; real scans for the baseline.
- **Depends on:** A6-4, M3-1.
- **Files:** `server/mapping_coverage.py`, `server/journal.py`,
  `scripts/replay_mappings.py`, new `docs/QUALITY.md`.
- **Facts:** The current metrics prove correctness on a tiny corpus, not
  production quality. Mature products track closing-line value and calibration.
- **Steps:** record mapping coverage, false merges, price-check outliers and
  stale-book counts per scan; compute CLV from settled journal entries; publish
  a dated quality report; add a large multi-scan replay corpus.
- **Done when:** a 7-day quality report exists with the counts and no invented
  thresholds.
- **Log:** —

#### A5-5 · Learn inside the scan

- [x] **Status:** DONE 2026-11-03
- **Needs:** offline.
- **Depends on:** A1-3, A5-1.
- **Files:** `server/api.py`, `config/settings.py`,
  `engine/mapping_evidence.py`, `tests/test_auto_learning.py`.
- **Facts:** Learning was a CLI step, so a fresh install still matched with the
  legacy files and a person had to run `scripts/learn_mappings.py`.
- **Steps:** after scraping and before constructing the matcher, call
  `learn_scan_mappings`; it loads the ledger, learns, prunes evidence to a
  bounded size and saves atomically. The matcher then reads the updated file in
  the same scan. `AUTO_LEARN_MAPPINGS` defaults true; `MIN_LEARN_MATCHES`
  (default 50) keeps test/smoke scans from rewriting the shipped ledger.
- **Tests:** the helper persists a claim; prune keeps the strongest evidence and
  the league-fingerprint union. Full suite green.
- **Done when:** a real scan logs accepted/quarantined counts and groups with
  the learned ledger in the same pass.
- **Log:** Added the in-scan learner and `GET /api/health.mapping_learning`.
  Real-scan validation is recorded under the checkpoint; the ledger is generated
  and intentionally not committed (it is 9.8 MB after one 5k-match scan).

## 5. Working rules and procedures

### Rules for every card

* **Python:** use `.venv`. Linux/macOS: `.venv/bin/python`; Windows:
  `.venv\Scripts\python.exe`. If missing, create it and install both
  requirement files.
* **Scope:** change only the files the card lists. If another file is needed,
  say which and why in the Log.
* **Comments and style:** match the surrounding code. Ruff line length 100.
  Every user-facing claim in `README.md` and this file is tested by
  `tests/test_readme_claims.py`; fix the document or the test's expectation,
  never the gate.
* **Registry rule:** every new market row needs a captured payload and a
  provenance record; regenerate `MARKET_MAPPING.md`.
* **Tests touch no network.** Use fakes, `httpx.MockTransport` or fixtures.
* **Dates** in logs: `YYYY-MM-DD`, times UTC.
* **No human-in-the-loop step may be added to a card.** If a card cannot be
  completed without one, mark it `BLOCKED (needs operator decision)` and record
  the evidence.

### S1 · Environment check (the four CI checks)

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy .
.venv/bin/python scripts/generate_market_mapping_doc.py --check
.venv/bin/python -m pytest
```

All four must exit 0. CI (`.github/workflows/ci.yml`) runs the same four;
frontend tests also need Node 22 on the path.

### S2 · Run a scan and read its numbers

1. Start the server: `.venv/bin/python main.py` (default port 8000). Wait for
   `curl http://127.0.0.1:8000/api/health`.
2. If `API_KEY` is set, add `-H "X-API-Key: <key>"` to every call.
3. `curl -X POST "http://127.0.0.1:8000/api/scan?mode=prematch"` (or
   `mode=live`). At most 3 requests per minute.
4. Poll `curl "http://127.0.0.1:8000/api/status?mode=prematch"` every 15 s
   until `"is_scanning": false`.
5. Read and log: `GET /api/results?mode=...`, `GET /api/health`,
   `GET /api/mapping/coverage`.
6. Stop the server when done.

### S3 · Re-capture market fixtures

`.venv/bin/python scripts/capture_market_fixtures.py --books <ids>` rewrites
`tests/fixtures/markets/<book>_<mode>.json`. Then run
`pytest tests/test_market_fixtures.py -q`. Never re-capture into
`tests/fixtures/e2e_certified/` or `tests/fixtures/replay/`.

### S4 · Prove deep links

With the server running and a fresh scan in cache, repeat
`curl -X POST "http://127.0.0.1:8000/api/verify-links?bookmaker=<id>&limit=20"`
every 31 s until `"remaining": 0`. CLI alternative:
`scripts/verify_deeplinks.py <book> --limit 20 --offset <n>`. Verdicts go to
`cache/deep_link_verifications.json` and the next scan reads them.

### S5 · Record progress

1. In the card: `- [x]`, **Status** `DONE YYYY-MM-DD`, and replace `**Log:** —`
   with 1–5 lines: what changed, measured numbers, surprises.
2. If blocked: leave `- [ ]`, **Status** `BLOCKED (<reason>)`, log what was
   tried and what input would unlock it.
3. Commit only the card's files plus `PLAN.md`, one commit per card, message
   `<type>(<scope>): <summary>` (`feat`, `fix`, `docs`, `chore`, `test`). Do not
   push.

### S6 · Replay check

```bash
.venv/bin/python scripts/replay_mappings.py tests/fixtures/replay/<date> --check
.venv/bin/python scripts/replay_mappings.py tests/fixtures/replay/<date> --cold --check
```

`--check` fails on `false_merges > 0`, `pairs_unresolved > 0`, or
`market_rows_unmapped > 0` with no absence proof. Record both outputs in the
card's Log.
