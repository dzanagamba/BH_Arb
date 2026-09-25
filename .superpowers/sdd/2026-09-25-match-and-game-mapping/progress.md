# SDD ledger — plan: docs/superpowers/plans/2026-09-25-match-and-game-mapping.md

Spec: docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md (reachable, binding authority)
Branch: master (in-place, user declined worktree)
Baseline: 185a9a8 — pytest 107 passed, ruff clean, mypy clean, working tree clean
Python: use `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe"` (the project has no venv)

## Pre-flight conflict scan

| # | Tasks sharing file/interface | Produces → Consumes | Finding |
|---|---|---|---|
| 1 | T1 schemas → T2 gate, T3 matcher, T7 API, T8 frontend, T10 scan | `MatchEventStatus`, `MatchEvidence`, `CandidateReview`, `Match.event_id`, `Match.deep_link_verified` | Consistent. All new fields have defaults so existing construction sites keep working. |
| 2 | T2 gate → T3 matcher, T10 scan | `CertaintyGate.evaluate/evaluate_pair`, `GateResult.status/reasons/evidence/is_swapped` | Consistent. |
| 3 | T2 gate ↔ T7 allowlist | Gate consumes `alias_allowlist: set[str]` in `left|right` form; T7 writes `config/team_alias_allowlist.json` with the same `|`-joined pair | Consistent after plan revision (approve writes one `|`-joined pair, not per-book entries). |
| 4 | T3 matcher → T4 registry, T7 API, T10 scan | Matcher loads `config/league_equivalences.json`; T10 reads `matcher._equivalences` | Consistent. |
| 5 | T3 matcher → T2 test fixtures | T3's gate requires `event_id`/`deep_link_verified` on matches; existing `tests/test_matcher.py` fixtures lack both | Known: T3 Step 5 explicitly instructs updating the shared `_match()` helper in `tests/test_matcher.py`. Ruling: proceed as planned. |
| 6 | T4 registry → T5 deeplinks, T9 doc gen, T11 fixtures | `MarketRegistry.lookup/ids_for`, `record_unmapped`, `unmapped_markets` | Consistent. |
| 7 | T4 registry → T7 health | T7 health reads `unmapped_markets` dict | Consistent. |
| 8 | T5 deeplinks → T12 verify | `build_event_url(bookmaker, event_id, base_url, live=False)` | Consistent. |
| 9 | T6 AI → T10 scan, T7 health | `MatchAI.suggest_pairs`, `.available` | Consistent. |
| 10 | T10 scan ↔ T7 API | T10 writes `pending_candidates` dict that T7 endpoints read | Consistent. T10 depends on T7's state existing. |
| 11 | T4 `parse_nsoft_bets` signature change → existing `tests/test_market_mapping.py` | New `bookmaker`/`mode` params default to `mdshop`/`prematch`, so existing direct calls keep working | Consistent. |
| 12 | T9 regenerates `MARKET_MAPPING.md` → T11 fixtures | T11 asserts registry/parser consistency, not doc content | Consistent. |

Per-task self-consistency (tests specified vs code specified, files created vs files later touched):
- T1: schema fields match the tests; `models/schemas.py` only. Clean.
- T2: `GateResult`/`CertaintyGate` signatures match all T2 tests; creates `engine/certainty.py`, touches `config/settings.py`. Clean.
- T3: matcher edits match the new tests; the 120-minute window removal is consistent with the Review Focus item 4. Clean.
- T4: registry JSON covers every book in `BOOKMAKERS`; parser rewire keeps the legacy fallback. Clean.
- T5: `build_event_url` returns the template for unsupported books, which is what the test expects. Clean.
- T6: adapter has no approve/status field, which the test asserts. Clean.
- T7: endpoints use `Depends(_require_api_key)`, matching the rest of `server/api.py`. Clean.
- T8: static-asset smoke test matches the markup/JS identifiers. Clean.
- T9: generator writes the marker the test asserts. Clean.
- T10: bucketed candidate search replaces the O(n²) loop in the same edit (plan revised). Clean.
- T11: parametrized over captured fixtures; each book needs a parser adapter (the plan says to add them). Clean.
- T12: endpoint mirrors the `verify_surebet` lock-free style but is explicitly on-demand. Clean.
- T13: e2e test may pass immediately — plan says treat it as a regression guard. Clean.

No unresolved conflicts. Proceeding to Task 1.
Task 1: complete (commits 185a9a8..1df3b7e, review clean)
Task 1: minor (deferred): tests/test_schemas_mapping.py does not cover every new default, invalid Literal values, or independent mutable-list instances
Task 1: minor (deferred): mutable [] defaults in schemas are safe under pinned Pydantic v2 but Field(default_factory=list) is clearer
Task 2: fix round 1/5 (3 addressed, 1 critical open — group path trusted normalizer fuzzy output; allowlisted alias downgraded by evaluate(); is_swapped mixed reference frames; commits 1df3b7e..a452469)
Task 2: fix round 2/5 (3 addressed, 0 open — shared raw-name+allowlist rule in pair and group paths; pair/group alias parity; single canonical-orientation frame for is_swapped; commits a452469..660cce5)
Task 2: Ruling: orientation_unresolved stays in HARD_REJECT_REASONS but unreachable (no input maps to it) — costs a dead constant until a future task introduces an orientation-only reason.
Task 2: minor (deferred): allowlist_entries records every configured alias rather than the one(s) actually used
Task 2: minor (deferred): the empty-group branch returns a result with no evidence
Task 2: complete (commits 1df3b7e..660cce5, review clean)
Task 3: fix round 1/5 (3 addressed, 1 critical open — team_mappings.json was granting fuzzy trade authority; bundesliga_2 unreachable; Vtora Liga generic bypass; 3 vacuous assertions; commits 8e82467..4141848)
Task 3: Ruling: team_mappings.json is a normalization registry, NOT an approval registry — fuzzy trust comes only from config/team_alias_allowlist.json. Costs: legitimate bookmaker spelling variants need a deliberate approval before they can group.
Task 3: fix round 2/5 (1 addressed, 0 open — German tier two consolidated under bundesliga_2, whole-file duplicate scan added; commits 4141848..c7c2f25)
Task 3: minor (deferred): allowlist_entries records every configured alias rather than the entry that authorized the pair
Task 3: minor (deferred): _surface_team_key is called "lossless" but NFKD does not transliterate every character
Task 3: complete (commits 660cce5..c7c2f25, review clean)
Task 4: fix round 1/5 (6 addressed, 0 open — WWIN live market loss restored; Premier live DC restored; explicit _excluded namespace stops unmapped noise; betole cross-book attribution fixed; single shared registry instance; vacuous label checks replaced with real subset checks; commits f34a14d..97f6def)
Task 4: Ruling: exclusion rules are book-scoped, not mode-scoped — an ID excluded in prematch is also excluded in live because the parser catalog is shared per book. Costs: a book that serves an ID in only one mode cannot declare that exclusion narrowly.
Task 4: minor (deferred): unmapped_markets is process-local; a comment about cross-process signal sharing is misleading
Task 4: minor (deferred): EVLBet GameId-only payloads yield nothing (only "12005" is registered)
Task 4: minor (deferred): admiralbet/live has no O/U entries while mdshop/live does (unverified asymmetry)
Task 4: minor (deferred): fail-open fallback for unregistered bookmaker ids silently reverts to legacy maps
Task 4: minor (deferred): captured-payload fixture coverage for registry entries is deferred to Task 11
Task 4: complete (commits c7c2f25..97f6def, review clean)
Task 5: fix round 1/5 (4 addressed, 0 open — mozzartbet declared true with live-board route evidence; declared-vs-undeclared API added; placeholder/empty-id/URL-encoding/live-template handling; set-equality invariant test; commits 674fab8..5c4bd34)
Task 5: Ruling: mozzartbet supports per-event links (supports_event_id true) based on observed live-board routes returning HTTP 200 — costs: its event links stay unverified until Task 12's checker runs, so its groups are suggested until then.
Task 5: minor (deferred): DEEP_LINK_CONFIG in config/settings.py is unused and duplicated in scrapers/common.py
Task 5: minor (deferred): the deeplink config is an untyped raw dict; a Pydantic v2 config model would be safer
Task 5: minor (deferred): a missing or invalid config file is cached as {} with no log
Task 5: complete (commits 97f6def..5c4bd34, review clean)
Task 6: fix round 1/5 (7 addressed, 0 open — top-level non-object JSON containment; json.dumps inside try; verify=VERIFY_SSL; absent-key no-chat test; confidence range validation; proposal cap; client lifecycle seam; commits 3407cdc..ffe741f)
Task 6: Ruling: per-call AsyncClient behaviour stays as-is; only a lifecycle seam (aclose/context manager/injectable client) is added, so Task 10 owns the long-lived-client change. Costs: N candidates still cost N handshakes until Task 10 lands.
Task 6: Ruling: .available keeps its key-presence contract (Task 7 depends on it); TLS failure surfaces via the existing warning path, not by changing the property. Costs: health can read "available" while calls fail.
Task 6: minor (deferred): propose_alias returns raw exception text into a human-facing reason field
Task 6: minor (deferred): no exc_info on the two warnings
Task 6: minor (deferred): base_url/model default signature differs from the brief's literal interface line
Task 6: complete (commits 5c4bd34..ffe741f, review clean)
Task 7: fix round 1/5 (4 addressed, 0 open — get_match_report now emits status so verified_groups is real; atomic temp-file+os.replace allowlist writes under a lock; E2E approval->verified test plus concurrent and duplicate tests; missing reject-404 test added; commits f514da0..9283bd9)
Task 7: Ruling: allowlist writes use an in-process lock (asyncio/single-worker assumption) plus atomic os.replace; a multi-worker deployment would still need an inter-process lock. Costs: documented limitation, acceptable because main.py runs one worker.
Task 7: minor (deferred): API-key coverage tests cover approval but not rejection (both are protected in production code)
Task 7: complete (commits ffe741f..9283bd9, review clean)
Task 8: fix round 1/5 (3 addressed, 1 important open — hardcoded "Verified" status claim removed; reason-label coverage test added; X-API-Key header sent on approve/reject; commits 8e9da28..752d32a)
Task 8: Ruling: the reviewer's Critical ("no production producer") is plan sequencing — Task 10 is the producer and had not run. Cost: the Review tab is non-functional until Task 10 lands; mitigated by an honest empty state that does not promise candidates.
Task 8: Ruling: the status badge renders only an explicitly supplied supported status and stays hidden otherwise, rather than adding a status field to the Surebet schema. Cost: the badge is usually absent, so the operator gains no positive confirmation; a status field remains a possible future improvement.
Task 8: Ruling: no JavaScript test runner is added; the reason-label invariant is enforced by a Python test that AST-derives reason codes from engine/certainty.py's reason sinks. Cost: interactive UI behaviour stays unexercised by automated tests.
Task 8: fix round 2/5 (1 addressed, 0 open — reason-code extraction moved from enumerated scenarios to source-anchored AST walk over reasons.append/HARD_REJECT_REASONS/GateResult(reasons=); commits 752d32a..c187e06)
Task 8: minor (deferred): the API key is prompted in-memory on 401 and is not persisted; an operator must re-enter it after a page reload when API_KEY is configured
Task 8: complete (commits 9283bd9..c187e06, review clean)
Task 9: fix round 1/5 (2 addressed, 3 important open — registry<->parser reachability test added; stale intro facts corrected; duplicate tables subordinated; PLUS the round introduced a false MBet claim and touched 4 production scrapers; commits ee15a36..6398eed)
Task 9: Ruling: byte-identical narrative preservation is review evidence, not a product invariant — stale facts in an accuracy document must be corrected even when they sit outside the generated markers. Cost: the "nothing was lost" diff claim from round 1 no longer holds.
Task 9: fix round 2/5 (4 addressed, 0 open — false MBet ofb:ht/ofb:hc claim corrected plus two more self-found false claims; Betole authority claim scoped inside the markers above the table; WWIN audit semantics restored; resolvers made private, test file split, 85-case loop replaced by payload-driven dispatch tests verified to bite; commits 6398eed..9567cfe)
Task 9: Ruling: parser wiring is proven by payload-driven dispatch tests that reach the real parse entry points, not by parametrized resolver calls that bypass dispatch. Cost: live-mode and non-1X2 registry rows lost their parser-side reachability assertion; premier_kladionica has a named static-routing gap only.
Task 9: minor (deferred): MARKET_MAPPING.md:15-19 opening paragraph still claims authority over Betole rows that the scope note at :37-42 qualifies
Task 9: minor (deferred): scrapers/common.py:304 docstring cross-references a test file that no longer imports scrapers
Task 9: minor (deferred): the wiring negative control leaves a permanent mdshop:4242 entry in the health-exposed unmapped_markets dict
Task 9: complete (commits c187e06..9567cfe, review clean)
Task 10: fix round 1/5 (6 addressed, 0 open — CandidateReview carries both sides and approval writes one alias per differing team; approved candidates suppressed across scans; prefilter claim made true; candidates paginated with bounded default; same_event honoured; actionability ordering; commits d2e7461..0a49bc3)
Task 10: Ruling: human approval grants TEAM IDENTITY ONLY. deep_link_verified stays a machine fact set by Task 12's Playwright check; a UI button may never set it. Cost: until Task 12 lands, 0 of ~7000 matches are link-verified, so no group is verified and an approval's only visible effect is removing 20 candidates from the queue.
Task 10: Ruling: the bigram term was made true (inner gate now applies the same per-slot signal) rather than deleted, because a token-only gate demonstrably dropped genuine typo pairs. Cost: the queue grew 13,471 -> 15,140 and collection runs ~12.4s.
Task 10: BLOCKING DEPENDENCY: Task 12 (link verification) is the critical path for this feature to produce any verified group at all.
Task 10: KNOWN LIMITATION: 77% of the queue (11,666/15,140) is league-blocked with no human action; the queue cannot be worked to zero by a human. Accepted because hiding them would hide the real disagreement surface.
Task 10: minor (deferred): app.js:894 reimplements the alias-writable rule with raw !== while the server uses _alias_name_key, so a case/whitespace-only difference yields a 400 behind an enabled Approve button
Task 10: minor (deferred): no paging control in the UI; app.js hardcodes offset=0, so 14,040 of 15,140 entries are reachable only by attrition
Task 10: minor (deferred): app.js re-sorts the page by ai_confidence after the server ordered by actionability (harmless today, latent re-introduction of confidence-first ordering)
Task 10: minor (deferred): suppression write is not in the same transaction as the allowlist write, so an I/O failure can leave an alias durable while the candidate reappears
Task 10: minor (deferred): /api/candidates now requires the API key, so any deployment with API_KEY set opens a window.prompt on every page load
Task 10: minor (deferred): per-item payload grew 395B -> 898B; candidate memory is now the dominant in-memory cost of a scan
Task 10: minor (deferred): two report/docstring proofs are overstated (the "two therefore agree exactly" non-sequitur, and the C2b section phrasing that implies Task 12 files already exist)
Task 10: complete (commits 9567cfe..0a49bc3, review clean)
Task 11: fix round 1/5 (6 addressed, 0 open — premier live BTTS recorded as xfail(strict=True) backed by real fixture rows; NSoft live-window defect recorded in both scrapers; expected_markets non-empty guard; stale mdshop 135-999 claim corrected; EVLBet provenance pointer; commits 4ad48c1..02d7124)
Task 11: Ruling: the confirmed defects are recorded in-repo, not fixed. premier live BTTS is an xfail(strict=True) tripwire (suite stays green; fixing the parser XPASSes and forces marker removal) and the NSoft live window is a KNOWN DEFECT comment citing the committed fixture receipt. Cost: two production defects remain live; both are now visible in the repo rather than in a session report.
Task 11: fix round 2/5 (5 addressed, 0 open — false POLUVRIJEME comment deleted and replaced with the measured reason; xfail reason repointed to KNOWN_DEFECT_ROWS; silent gap-row continue made explicit; literal unified to a named constant; module docstring updated; commits 02d7124..9bac376)
Task 11: fix round 3/5 (2 addressed, 0 open — contradictory SAME predicate sentences removed (grep-verified 0); gap guard given real executed coverage via a controlled A/B; commits 9bac376..4be48b5)
Task 11: PROCESS FINDING: four downstream-caught instances where a comment/report described something other than what the code or data did; twice the code was right and only the description wrong, which is the more dangerous shape. The working check is to run the proving command before writing the claim and paste the output. Raised to the implementer; it self-caught two further instances afterwards.
Task 11: minor (deferred): EVLBet has no fixture — its offer API returns an empty list for every endpoint variant tried, so prematch/1x2 = 12005 rests on MARKET_MAPPING.md documentary provenance only
Task 11: minor (deferred): betole's 6 registry rows have no capture (disabled book; its parser emits first_half_1x2 outside the registry)
Task 11: minor (deferred): live fixture capture is time-of-day dependent (needs football in play); re-capture has no staleness bound and no retry
Task 11: minor (deferred): the capture script duplicates scraper endpoints with no cross-check — this is the check that would catch the comment-drift error class automatically
Task 11: minor (deferred): report hygiene only — stale "58 tests" count, a diff-stat mismatch, and an uncorrected "7 of 9" in the gitignored report
Task 11: complete (commits 0a49bc3..4be48b5, review clean)
Task 12: fix round 1/5 (0 critical, 1 important + 7 minors — sliding-window 429 throttle, _browser_sem acquired, post-await scan re-check; subframe tests added; id-key tightened; errored count; script docstring; commits 4be48b5..f2ee803)
Task 12: HEADLINE RESULT: MDShop's and Admiralbet's declared ?event=<id> route is INERT. The served page is byte-identical to the plain football prematch page, the id appears in none of ~250 response bodies or rendered text, and ?event= provokes no event-scoped request. Only Mozzartbet verifies (15/15 via $.match.id; a dead id answers 200 with 14 bytes). Consequence: verified groups remain UNREACHABLE in production — 0 of 197 on a real 1,592-match three-book feed.
Task 12: Ruling: the brief's own criterion (event_id in page.content()) was rejected as a false pass — MDShop echoes the query param into an iframe src, so a dead id reads as verified. The shipped criterion requires the id as a whole token in a book-owned RESPONSE URL, excluding the requested document itself. Cost: a POST carrying the id in a request body is structurally invisible; the checker under-reports, which is the safe direction.
Task 12: Ruling: the two false NSoft routes were NOT flipped to supports_event_id:false. Flipping would change nothing in the gate and would make the user-facing links worse. They stay declared-but-unverified, and the finding is documented as a follow-up.
Task 12: KNOWN DEFECT: build_targets (verify_deeplinks.py:301-324) has no offset, cursor, or skip-already-checked, so repeated calls re-check the same first N events forever. This — not the rate limit — blocks convergence. A per-book sweep over 600+ events is impossible today. NOT IMPLEMENTED; recorded as a follow-up.
Task 12: fix round 2/5 (8 addressed — errored test rewritten against a real verify_bookmaker run and mutation-verified; convergence mis-attribution corrected; maxTotalOdd and empty-neighbour attributions corrected; applied became three-state; teardown, window constant, throttle placement, EVENT_ID_KEYS, disabled path; commits f2ee803..1dfb33a)
Task 12: fix round 3/5 (3 addressed — throttle tests pinned to the value under test so the suite is green at 0/2/7; RATE_LIMIT_WINDOW_SECONDS no longer ambient-dependent in tests; applied_note names _apply_deep_link_verifications; float clause now exercised by a decimal under an event-named key; commits 1dfb33a..e3f3216)
Task 12: PROCESS FINDING: the fourth report/docstring claim in this plan that asserted a property the code lacked. Every instance was caught by a mutation run or an env-var run, never by re-reading. The working check is to run the proving command and paste the output.
Task 12: minor (deferred): a per-request wall-clock cap is still absent — MAX_LIMIT=20 x 75s is the real duration risk and the throttle only bounds frequency
Task 12: minor (deferred): rate-limit windows are per-process, matching the pre-existing SCAN_RATE_LIMIT behaviour
Task 12: minor (deferred): a completed-fail cannot demote a stale deep_link_verified=True in the cache until a scan rebuilds the list, so the negative case errs toward "verified" for one scan cycle
Task 12: minor (deferred): Content-Type must contain "json", so a JSON body served as text/plain is invisible; both this and the POST-body gap fail safe (under-report only)
Task 12: complete (commits 4be48b5..e3f3216, review clean)
Task 13: fix round 1/5 (blocker fixed — README.md and PLAN.md had been dropped silently; mutation table re-run as one measurement set; EXPECTED_LEGS note; alias-evidence assertion strengthened; link_unverified test de-over-specified; commits e29e1b0..c5fe4d5)
Task 13: Ruling: the two scope additions (a bare-competition-name breaker for the gate's league rule, and an ODDS_TTL_SECONDS test) are in scope, not creep. Both are test-only, on seams the brief named, and both closed observation holes the implementer found. Cost: none material.
Task 13: fix round 2/5 (4 addressed — doc-claim script committed as tests/test_readme_claims.py; three code-only checks now read the document; the approval-boundary check asserts on one claim; new cross-checks; commits c5fe4d5..59b5186)
Task 13: NOTABLE: the committed doc-claim test found two real errors in the documentation the previous commit shipped on its first run — the README listed orientation_unresolved in the rejected row though the gate never emits it, and a probe of the implementer's own wrongly blamed the README for no_event_link. It is the artifact that would have caught this plan's earlier corrected claims automatically.
Task 13: fix round 3/5 (4 addressed — report section F.9 superseded-bannered and the %TEMP% paragraph replaced; a docstring naming a non-existent guard test corrected; the headline check widened; predicate counts corrected 11->10; commits 59b5186..e7b31dd)
Task 13: FOLLOW-UP (needs its own plan): orientation_unresolved is a three-site removal, not a one-line fix. engine/certainty.py:20 declares a hard-reject reason the gate never emits; tests/test_frontend_review.py folds HARD_REJECT_REASONS into its source-derived set, which is why frontend/js/app.js:43 ships a user-facing label for it and that label is load-bearing for a passing test. Either implement the reason or delete the entry plus the label plus the fold.
Task 13: minor (deferred): build_targets has no cursor, so a per-book link sweep over 600+ events cannot converge (recorded in README)
Task 13: minor (deferred): the README headline is a dated browser measurement the suite cannot reproduce; the repo-reproducible half (which books declare a route) is pinned
Task 13: minor (deferred): the doc-claim test is coupled to prose — a legitimate rewording fails it loudly and locally
Task 13: minor (deferred): the .superpowers report is gitignored so its staleness is invisible to the suite; a banner-and-count checker would be worth more than more prose
Task 13: complete (commits e3f3216..e7b31dd, review clean)

================================================================
WHOLE-BRANCH REVIEW (185a9a8..e7b31dd) — 2 Critical, 4 Important
================================================================

Critical 1 (fixed, 122b2a4): the gate never read supports_event_id. The spec's declared-no-route
  escape hatch did not exist, so six of nine books were structurally excluded from verified
  forever BY CODE, not by bookmaker behaviour. Production yielded zero surebets and the README
  blamed the bookmakers. Flagged in Task 5's report as "a later task will handle it" and never
  picked up by any of the eight tasks that followed. This was spec compliance that no single
  task's reviewer could see.
  - Reviewer safety verdict: YES. The accepted set is a provable strict superset; the five
    identity gates are byte-identical; declares_no_event_id feeds exactly one boolean.
  - Decisive fact: verify_deeplinks.py skips every non-declared-route book, so
    deep_link_verified could never be True for those six books by any code path. The link was
    a constant veto carrying zero bits of information. The change removes no proof.
  - Implementer corrected two of the controller's premises: no_event_link was never in
    HARD_REJECT_REASONS, and there is no import cycle.

Critical 2 (fixed, 854bcb5): alias_actionable was computed with the 30-minute candidate window
  while the real gate uses 15. For a delta in (15,30] the UI said "An approval clears every
  remaining blocker here" — false — and the pair was then permanently suppressed, so a real
  opportunity was discarded forever. A 15-vs-30 window disagreement between Task 3 and Task 10
  that neither reviewer could have known about.

Important (fixed, 01090c8): PLAN.md top header still asserted the retired causal claim in the
  present tense; no automated check could catch a wrong supports_event_id:false and the one tool
  that could was skipped for exactly those books; unverified_links used the wrong predicate so
  the diagnostic would go dark if a declaration were removed; two stale line references; the
  operative declaration was unobservable.

PROCESS: 17 fix commits to 10 feat. The recurring defect class across the plan was a comment,
docstring, or report sentence describing something other than what the code or data did — five
instances, twice with the code right and only the description wrong. It was caught every time
by a mutation run or an env-var run, never by re-reading. The one durable institutionalization
is tests/test_readme_claims.py, which found two real documentation errors on its first run.

MEASUREMENT CORRECTION: the "202 groups / 1 surebet" figure from the link-declaration
  implementer is unproducible by the shipped pipeline at any link state. The quoted surebet is a
  pair 120 minutes apart against a 15-minute window, so the gate refuses it. Honest numbers on
  the 2026-08-20 cache: scenario A 16 groups / 0 surebets; B 179/0; C 516/0 (bit-identical to
  the pre-fix ceiling, confirming monotonicity). Also: group_matches is ORDER-SENSITIVE — the
  same cache gives 16/34/106 by input order alone — so no group count is a fact until the order
  is stated. Pre-existing, documented, not fixed.

FOLLOW-UP (needs its own plan, in priority order):
  1. Run the link check against the live books and re-verify the six supports_event_id:false
     notes. A wrongly-declared book is now accepted uncorroborated; the new structural check
     catches a bookmaker ADDING routes, not a human mis-declaring one.
  2. build_targets has no cursor, so a per-book link sweep over 600+ events cannot converge.
  3. MatchGroup.evidence is never served — get_match_report omits it and _save_cache does not
     persist it — so an operator cannot audit WHY a link was accepted. That is the only place a
     wrong declaration would surface.
  4. group_matches order-sensitivity.
  5. orientation_unresolved is a three-site removal, not a one-line fix. The gate genuinely has
     a case the vocabulary cannot express (allowlist admits the teams but no complete
     home/away orientation is provable) and certainty.py:450-451 collapses it into
     team_unresolved. The right fix is to IMPLEMENT the reason, not delete it.
  6. EVLBet is enabled but has no captured payload; its 1x2 -> 12005 rests on documentary
     provenance only.
  7. premier_kladionica/live/btts (xfail tripwire) and the NSoft live-window bug — both
     recorded in-repo, neither fixed. Both books' live scraping is likely returning nothing.
================================================================
