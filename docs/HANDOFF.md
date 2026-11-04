# Handoff — match & game mapping certainty

**Written:** 2026-09-26
**Covers:** `185a9a8..01090c8` — 38 commits, 13 plan tasks + 3 remediation fixes
**State at handoff:** 572 tests pass, 1 xfailed (intentional tripwire), ruff clean, mypy clean
across 59 source files. Working tree clean, all work pushed to `origin/master`.

---

## 1. What problem this solved

The scanner matched same-event fixtures with a fuzzy confidence score above a threshold. A
wrong pairing and a right one looked alike, so the system could show a surebet built on two
different matches — an arbitrage that does not exist. It also had no way to say *why* it
believed a pair, and no record of what it had checked.

**Design spec:** `docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md`
**Design rationale:** commit `185a9a8`

---

## 2. What was built

### 2.1 The certainty gate — `engine/certainty.py`

The core change. A pair is `verified` only when every part of the claim is proven:

| Gate | Rule |
|---|---|
| League | exact canonical id, or an explicit pair in `config/league_equivalences.json` |
| Kickoff | within **15** minutes (`VERIFIED_KICKOFF_WINDOW_MINUTES`); missing kickoff never verifies |
| Category | `a_tags == b_tags` |
| Team | exact canonical match, or an **allowlisted** alias — never blanket fuzzy |
| Orientation | a complete home/away ordering must be provable |
| Link | proven, **or** the book declares `supports_event_id: false` |

Statuses are `verified` / `suggested` / `rejected`, each carrying `MatchEvidence`. Reasons come
from a fixed vocabulary: `league_mismatch`, `kickoff_missing`, `kickoff_delta`,
`category_mismatch`, `team_unresolved`, `orientation_unresolved`, `link_unverified`,
`no_event_link`.

Only `verified` groups reach `engine/arbitrage.py`. The matcher also fixes team-and-odds
orientation from the gate's single canonical frame, so a reversed book never inverts a surebet.

### 2.2 Market registry — `config/bookmaker_markets.json`, `engine/market_registry.py`

Every bookmaker's market IDs for prematch and live, as the single source of truth.
- A market is emitted only if the ID matches **and** the label-set rule holds (1X2 needs all of
  1/X/2; DC needs ≥2; BTTS needs both; O/U needs both sides).
- An unregistered ID is counted in `unmapped_markets` and surfaced on `/api/health` — never
  silently dropped. A `_excluded` section suppresses IDs that are deliberately unsupported, so
  the diagnostic stays actionable instead of permanently noisy.
- **Historical bug this prevents:** NSoft market `136` ("Ide dalje", advance) was once treated
  as 1X2. `136` is absent from the registry for both NSoft books in both modes, and three test
  layers independently assert it can never produce 1X2 or DC.
- `MARKET_MAPPING.md` is **generated** from the registry between marker comments, with a
  `--check` mode for CI. Narrative sections outside the markers are preserved and marked
  non-authoritative; the generated table is the authority and says so.

### 2.3 Captured-payload fixture tests — `tests/fixtures/markets/`

14 fixtures captured from the live APIs on 2026-09-25, across mdshop, admiralbet, wwin,
premier_kladionica, mbet, sportplus, mozzartbet (prematch + live).

This is the **only** layer that can catch a wrong-but-consistent market ID, because the two
lower layers share a source of truth and would be wrong together. Mutation testing confirms it:
breaking 10 registry rows one at a time, this layer caught 10/10 while the lower layers missed
three (`sportplus` BTTS `6→5`, `mozzartbet` BTTS `130→131`, `mbet` O/U 2.5 `ofb:tg→ofb:ht`).

Authenticity is verifiable from the data itself: mdshop carries `135` and admiralbet carries
`1639`, neither carrying the other's; mdshop spells O/U legs `"Vise"` and admiralbet `"Više"`;
a genuinely suspended `0.0` double-chance leg is preserved as a control.

`scripts/capture_market_fixtures.py` regenerates them.

### 2.4 Deep links — `config/bookmaker_deeplinks.json`, `scripts/verify_deeplinks.py`

Every book declares whether it has a per-event route. `build_event_url` builds the link;
`verify_deeplinks.py` proves it with Playwright and records the result in a TTL'd store that the
next scan reads as a dict lookup — the browser never runs inside a scan.

**The brief's own check was rejected as a false pass.** `event_id in page.content()` is satisfied
by mdshop echoing the query parameter into an iframe `src`, so a dead id reads as verified. The
shipped criterion requires the id as a whole token in a **book-owned response URL**, excluding
the requested document itself. Three live controls caught the rest: a `maxTotalOdd` settings
value, admiralbet's 29 KB `bonus-tickets-with-details` payload served on every page load, and a
shell that renders identically for a dead id.

### 2.5 Review queue and AI boundary

- `engine/ai.py` — hosted, OpenAI-compatible, **propose-only**. `PairProposal` has no `approved`
  or `status` field; `MatchAI` has no approve method. Returns `[]` on any error, never raises.
  Degrades to rules-only when unavailable, and says so.
- `config/team_alias_allowlist.json` — the **human approval boundary**. `team_mappings.json` is
  a normalization registry and grants no trust; only an explicitly reviewed alias pair may be
  fuzzy-matched. Approval writes one entry **per differing team**, not one per fixture.
- Approving grants **team identity only**. It never sets `deep_link_verified`, which is a
  machine fact set only by the browser check. A human button cannot forge a proof.
- Suppressed candidates persist, so an approved pair does not reappear every scan. A decision
  records its premise (`link_blocked=…`) and is revisited if that premise moves.
- `frontend/` Review tab + `/api/candidates` endpoints, paginated and API-key protected.

### 2.6 Generated-doc discipline — `tests/test_readme_claims.py`

30 tests that run the **real gate** over documented claims and require the documents to match.
Found two real errors in its own documentation on first run. This is the artifact that would
have caught this project's recurring mistake automatically.

---

## 3. Two Critical defects the final review found

Neither was visible to any single task's review. Each was correct against its own brief and
wrong against another task's shipped behaviour.

### 3.1 The gate never read `supports_event_id` (fixed, `122b2a4`)

The spec says a book declaring `supports_event_id: false` "is accepted with a `no_event_link`
evidence note." The gate added `no_event_link` to blocking reasons like any other, so **six of
nine books were excluded from `verified` forever, by code, not by bookmaker behaviour.**

Task 5's report noticed this and wrote "until the later link-verification integration consults
the declarations." No later task did. Eight tasks passed in between.

The decisive fact, which reframes the whole result:
`scripts/verify_deeplinks.py` skips every book whose `supports_event_id` is not `True`, so
`deep_link_verified` could never become `True` for those six books by any code path. The link
half was a **constant veto carrying zero bits of information** — not one link was ever proved or
disproved on them. The fix removes no proof; it stops treating an impossible check as a failed
one.

Safety review verdict: the accepted set is a **provable strict superset** (it can add a pair,
never remove one), and the five identity gates are byte-identical.

### 3.2 `alias_actionable` used the wrong kickoff window (fixed, `854bcb5`)

The candidate gate ran at 30 minutes; the real gate at 15. For a kickoff gap in **(15, 30]**:

- the UI rendered *"An approval clears every remaining blocker here"* — false
- those pairs sorted **first**, so reviewers worked them first
- approving them wrote a suppression record **permanently**

A genuine opportunity was discarded forever on the strength of a false statement. A 15-vs-30
disagreement between Task 3 and Task 10 that neither task's reviewer could have known about.

---

## 4. Current honest numbers

**The scanner still produces zero surebets.** This is worth stating plainly rather than
implying otherwise.

Measured offline on the `2026-08-20` cache (6,999 matches, 7 books, 0 proven links):

| Scenario | Verified groups | Surebets |
|---|---|---|
| **A — cache as it stands** | **16** | **0** |
| B — Mozzartbet's link check run | 179 | 0 |
| C — every link proven | 516 | 0 |

Scenario C is **bit-identical** before and after the fix, which is the monotonicity proof.

**A correction worth keeping:** an earlier implementer reported "202 groups / 1 surebet." That
figure is unproducible by the shipped pipeline at any link state. The quoted surebet is a pair
**120 minutes apart** against a 15-minute window, so the gate refuses it. Do not quote it.

**Another caveat — the table above predates the order fix.** `MatchMatcher.group_matches` *was*
order-sensitive: that cache yielded 16 / 34 / 106 groups by input order alone, so the 16 / 179 /
516 are one input order's numbers. It is now order-independent (§5 item 4), and the `2026-08-20`
cache is no longer on disk to re-measure. On the `2026-09-26` cache (5,373 matches, 7 books),
across 7 input orders:

| Scenario | Before the fix | After |
|---|---|---|
| Links as cached | 251–304 groups, 7 different results | **365** groups, every order |
| Every link proven | 470–555 groups, 7 different results | **704** groups, every order |

**Why zero, precisely:** mdshop and admiralbet declare per-event routes that are measurably
inert, so they still block — correctly, and that is a bookmaker fact this code keeps reporting
honestly. The other six books now verify on identity alone, which is what the spec intended. The
remaining lever is running the link check against Mozzartbet, the one book whose route works.

---

## 5. What still needs doing

Ordered by value. Items 1–3 are what turn the machinery into yield.

### 1. Run the link check against live books, and re-verify the six `false` declarations
**Why it is now the top item.** A wrongly-declared book is accepted uncorroborated. Today the six
`note` fields are load-bearing in a way they were not before, and they are only as good as the
last time someone read them.

A structural check now catches the reverse drift — a declared-`false` book whose captured
`match.url` differs from its declared `template` (i.e. a bookmaker *adding* routes) fires the
test suite with no browser. What it cannot catch is a human mis-declaring. That needs a manual
read of the six notes against the live books, and it should be recorded when it was done.

Run: `python scripts/verify_deeplinks.py mozzartbet --limit 20`, then a full scan.

### 2. Serve `MatchGroup.evidence`
`engine/matcher.py:get_match_report` omits the evidence trail and `server/api.py:_save_cache`
does not persist it. The `no_event_link` acceptance note — the entire justification for accepting
a link-less book — is in the model, asserted in tests, and **reachable by no operator, in no API
response, and after no restart.** This is the only place a wrong declaration would surface, and
it is currently invisible. Rated Important by the safety review.

### 3. ~~Add a cursor to `build_targets`~~ (fixed)
It walked matches in cache order and `break`ed at `limit`, with no offset, no cursor and no
skip-already-checked, so repeated calls re-checked the same first N events forever and a per-book
sweep over 600+ events was impossible. **Now:** `build_targets` takes `settled` (ids the caller has
already decided, skipped *before* the window is cut) and `offset` (a positional resume, for a caller
with no store — the CLI). `POST /api/verify-links` fills `settled` itself from the new
`cache/deep_link_decisions.json`, which records every **completed** check, so its caller keeps no
cursor, and every response echoes `remaining` so a sweep loop knows when to stop. Two design points
worth knowing before changing it: a completed **fail** must settle too (the proof store deletes
those, so without the decisions store a book whose links do not verify can never advance), and a
**proof must not settle** (a proven link has to stay re-checkable so a later completed fail can
clear it — `?recheck=1` is the way back for a decided event). The throttle was never the blocker and
is unchanged at 2 calls/min; a cursor is what made those calls worth making.

### 4. ~~Make `group_matches` order-insensitive, or document the order~~ (fixed)
**Now:** listings are processed in a total order (`engine/matcher.py:_processing_order_key` —
specific leagues first, then league, kickoff, bookmaker *registry* order, normalized teams, ids),
and when the gate refuses the best-scoring group the listing tries the next one, highest
confidence first, before opening a new group. The gate is untouched and still decides every join.
`tests/test_matcher_order.py` shuffles a multi-book fixture set across seeds and pins the
fall-through. Two things worth knowing before changing it: the bookmaker's position in
`config.settings.BOOKMAKERS` decides which book anchors (and orients) a group, so reordering that
dict changes canonical orientation; and the fall-through is why `/api/verify` now answers
`still_profitable: None` when a cached leg's book is missing from the fresh group — two route-less
books can verify with each other without it, and pricing that pair would judge a different bet.
The original note: 16 → 106 groups from the same input was a 6× swing driven by iteration order.

### 5. ~~Fix `premier_kladionica/live/btts` and the NSoft live window~~ (fixed)
**Now:** the Premier parser matches BTTS per mode (`NAME_BTTS_LIVE`), and both NSoft
scrapers build their window from `scrapers.common.nsoft_event_window` (live looks back
12h). Both have regression tests in place of the tripwires. The original notes follow.

- *Premier live BTTS* — an `xfail(strict=True)` tripwire at `tests/test_market_fixtures.py:559`.
  The feed says `LIVE - OBA TIMA DAJU GOL`; the parser's `NAME_BTTS` is `OBA DAJU GOL`. The fix
  belongs in the parser, **not** a registry rename: prematch genuinely is `OBA DAJU GOL`, so a
  rename would break it. `strict=True` means fixing the parser turns the test red until the
  marker is removed — nobody can half-fix it.
- *NSoft live window* — mdshop and admiralbet request live with `dateFrom=now`, but NSoft filters
  on **kickoff**, so already-started in-play games fall outside the window. Measured: `dateFrom=now`
  returned `{"events": []}`; `now - 12h` returned 35 live football events. **Both books' live
  scraping is very likely returning nothing in production.** Marked in both scrapers —
  `scrapers/mdshop.py:91` (`KNOWN DEFECT`) and `scrapers/admiralbet.py:86-95` — with the
  working-window receipt in the fixture's `endpoint` field. This is a bigger live-mode bug than
  the BTTS one.

### 6. Decide `orientation_unresolved`: implement it or delete it
A three-site removal, not a one-line fix. `engine/certainty.py:27` declares a hard-reject reason
the gate never emits; `frontend/js/app.js:43` ships a user-facing label for it, and
`tests/test_frontend_review.py:159` *requires* it to stay, so the three are coupled.

**The right fix is to implement it, not delete it.** The gate genuinely has a case the vocabulary
cannot express: a pair where the allowlist admits both teams but no complete home/away ordering
is provable. `engine/certainty.py:500` returns `rejected` with `team_unresolved` for the pair
path, and `:511-512` appends the same reason when group teams are not ok — which is why the
reason was reachable in the design and unreachable in the code.

### 7. Capture an EVLBet payload
EVLBet is **enabled** and has no captured payload — its offer API returned an empty list for every
endpoint variant tried. Its entire registry, including the load-bearing `1x2` → `12005`, rests on
documentary provenance in `MARKET_MAPPING.md:347`. The spec states a captured fixture per registry
entry as a hard rule; this is the one enabled book that does not meet it.

### 8. Smaller items
- ~~`engine/arbitrage.py` has **no status check at all**~~ (fixed: `find_surebets` and
  `evaluate_market` now refuse any group that is not `verified`) — "only `verified` groups feed arbitrage"
  rests entirely on one `if` in `engine/matcher.py:279-284`. For a product whose purpose is
  *never show a wrong surebet*, a guard inside `find_surebets` would make the central safety
  property local rather than ambient.
- ~~`pending_candidates` is global and mode-blind~~ (fixed: one queue per feed, and
  `/api/candidates` takes `mode`). Original note: a live scan wiped the prematch queue.
  `/api/candidates` takes no `mode` parameter, so the spec's documented contract is unmet.
- The UI's empty state says *"try reducing the minimum profit threshold or checking all
  markets."* The filters are not the cause — the link gate is. The data to say so is already
  shipped and unused (`group_statuses` on `/api/results`, `verified_groups` / `unverified_links`
  on `/api/health`).
- `_deeplink_cache` is populated once and never invalidated. Editing a declaration needs a
  process restart. It is now observable via `/api/health` (`deep_link_declarations`).
- `unverified_links` was switched to `not declares_no_event_id(...)` so it matches the gate's own
  predicate — correct now, but the guarantee rests on a test that every configured book is
  declared.
- 77% of the candidate queue (11,666 / 15,140) is league-blocked with no human action available.

---

## 6. How this was built, and the lesson

13 tasks, each with a fresh implementer, a per-task review against its brief, and a whole-branch
review at the end. **17 fix commits against 10 feat.** Two tasks were reworked twice and one
three times.

**The recurring defect class was documentation lying about the code** — a comment, docstring, or
report sentence describing something the code did not do. Five instances. Twice the *code* was
right and only the *description* was wrong, which is the more dangerous shape.

It was caught every single time by a **mutation run or an env-var run, never by re-reading.** A
reviewer grepping a file found what the author had asserted from memory. The discipline that
works: before writing a claim about behaviour, run the command that proves it and paste the
output.

That discipline lived in the reviewers and the ledger rather than in the code, so it did not
compound — the same class reappeared in three consecutive tasks. The one durable
institutionalization is `tests/test_readme_claims.py`, which is the model the rest of the project
needs: a check that runs the real gate over the documented claims instead of trusting the prose.

**Where the per-task process genuinely worked:** Task 12's implementer rejected its own brief's
verification criterion after proving a dead id would pass it, and declined to flip two
declarations that would have made its number look better. Task 9's implementer found and
corrected three false claims of its own. Both were found and fixed without prompting. Where it
did not: the two Critical defects in §3 were each invisible to a reviewer given only one task's
brief, because each was correct against that brief and wrong against another task's shipped
behaviour. Whole-branch review is not optional on this kind of work.

---

## 7. Where to look

| What | Where |
|---|---|
| Design spec (binding authority) | `docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md` |
| The gate | `engine/certainty.py` |
| Market registry + exclusions | `config/bookmaker_markets.json` |
| Link declarations | `config/bookmaker_deeplinks.json` |
| Human approval boundary | `config/team_alias_allowlist.json` |
| AI adapter (propose-only) | `engine/ai.py` |
| Link checker | `scripts/verify_deeplinks.py` |
| Fixture regenerator | `scripts/capture_market_fixtures.py` |
| Generated market doc | `MARKET_MAPPING.md` (between `<!-- GENERATED ... -->` markers) |
| User-facing docs | `README.md` §"Match & mapping certainty" |
