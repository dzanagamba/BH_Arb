# Task 12 report — on-demand deep-link verification endpoint and Playwright checker

Commit: `2f4a1e8` — `feat(mapping): add deep-link verification endpoint and Playwright checker`
Branch: `master` (in place, no worktree)
Files: `scripts/verify_deeplinks.py` (new, 521), `tests/test_verify_links.py` (new, 753),
`server/api.py` (+293), `scrapers/common.py` (+11), `server/app.py` (+6), `scripts/__init__.py` (new)
(This report file is untracked on purpose: `.superpowers/` is gitignored, as it is for
tasks 1–11.)

---

## 0. THE ONE SENTENCE THAT MATTERS

**MDShop and Admiralbet could NOT be verified, and they stay `unverified_link`: the
`?event=<id>` route those two books declare is inert — the page it serves is
byte-for-byte the same football prematch page a dead event id gets, the id never
appears in any of the ~250 response bodies or in the rendered text, and `?event=`
provokes no event-scoped request at all. Only Mozzartbet (15/15 real events
verified across three runs, `$.match.id` in a 328 KB per-event payload) survives
the criterion, so with today's book set `verified` groups are still unreachable in
production: measured on a real 1,592-match three-book feed, the shipped code
produces 0 verified groups, and the same feed with every link marked proven
produces 197.**

---

## 1. What I changed

### `scripts/verify_deeplinks.py` (new) — the checker

Pure core (unit-tested, no browser) plus a thin Playwright shell:

| symbol | what it is |
|---|---|
| `CRITERION` | the one sentence the API returns so an operator can audit what "verified" means |
| `book_owned_host(url, base_url)` | same site? sub-domains yes, look-alikes no (`evil-mdshop.ba.attacker.test` is not) |
| `whole_token_span(text, id)` | standalone-token search, so `9984468` never matches inside `199844681` |
| `json_event_paths(body, id)` | **the criterion**: JSON paths where a key that names an event holds exactly the id |
| `payload_evidence(...)` | evidence from book-owned JSON payloads that were **requested for that id** |
| `rendered_text_evidence(text, id)` | evidence from visible page text (never from a URL, never a decimal) |
| `build_targets(matches, book, base_url, live, limit)` | one URL per distinct event id, from the declared template |
| `check_target(page, target, base_url)` | load one link, return a `LinkOutcome` |
| `verify_bookmaker(...)` | the whole run: one browser, N links, one `LinkReport` |
| `apply_report(matches, report)` | write verdicts onto matches; return how many changed |
| CLI | `python scripts/verify_deeplinks.py mozzartbet --limit 3 [--mode live]` |

`LinkOutcome.error` is the load-bearing distinction: a check that **completed** and
found nothing is `verified=False, error=""`; a check that could not complete
(navigation error) is `error="Timeout…"`. Only a completed check may clear a proof.

`scripts/__init__.py` was added because mypy otherwise resolved
`scripts/verify_deeplinks.py` under two module names at once (`verify_deeplinks`
and `scripts.verify_deeplinks`) and refused to check anything.

### `server/api.py` — store, seam, endpoint

* `DEEP_LINK_VERIFICATION_TTL_SECONDS = 3600`, `DEEP_LINK_VERIFY_DEFAULT_LIMIT = 5`,
  `DEEP_LINK_VERIFY_MAX_LIMIT = 20`, `cache/deep_link_verifications.json`
  (written through Task 7's `_atomic_write_json`).
* `_load/_save/_record/_apply_deep_link_verifications` — per-mode store
  `{mode: {"book|event_id": {verified, checked_at, url}}}`.
* `_apply_deep_link_verifications(matches, mode)` — a dict lookup that SETS
  `deep_link_verified` on matches with a fresh record. Called from **`run_scan`**
  (before the matcher) and from `_load_cache`. It never launches a browser.
* `_run_link_verification(...)` — the endpoint's only browser seam, monkeypatched in
  every test.
* `POST /api/verify-links?bookmaker=&mode=&limit=`.

Response: `{bookmaker, mode, status, skip_reason, criterion, available, checked,
verified, failed, unchecked, duration_seconds, details[{event_id, url, verified,
evidence, error}]}`.

Status codes: `400` missing/blank bookmaker, bad mode, `limit < 1`; `404` unknown
bookmaker; `409` a scan is in progress; `200` for `skipped`, for "nothing to
check", and for a real run.

### `scrapers/common.py`

`supports_event_id(bookmaker) -> bool` — the declared-vs-undeclared distinction the
checker needs, next to the existing `has_declaration`.

---

## 2. Design decision 1 — only books that declare `supports_event_id: true` are checked

A book that declares `false` has no per-event route *by definition*, so checking it
is meaningless. `verify_bookmaker` returns before it touches Playwright:

```json
{"bookmaker": "wwin", "status": "skipped",
 "skip_reason": "wwin declares no declared event route — nothing to verify",
 "available": 0, "checked": 0, "verified": 0, "failed": 0, "unchecked": 0,
 "duration_seconds": 0.0, "details": []}
```

The endpoint short-circuits **before** the browser seam, so no Chromium is even
constructed (`test_book_without_a_declared_event_route_is_skipped_not_failed`,
`test_a_book_with_no_declared_route_never_launches_a_browser`). No match is touched
(`test_a_skipped_book_never_gets_a_link_flag`). An **undeclared** book is treated the
same way: unknown route ≠ proven route. The six false declarations (wwin, mbet,
sportplus, evlbet, premier_kladionica, betole) can therefore never contribute a
`link_unverified` failure — the gate's existing `no_event_link` reason already
covers them.

## 3. Design decision 2 — the endpoint is on-demand and its cost is in the response

* `run_scan` never calls the checker. `test_the_checker_never_runs_inside_a_scan`
  replaces `_run_link_verification` with a function that raises and runs a full
  scan: it completes normally, and every match stays `deep_link_verified=False`.
* It is refused with `409` while a scan holds the mode lock
  (`test_verifying_links_is_refused_while_a_scan_runs`), and a module-level
  `asyncio.Lock` serialises two check runs so two browsers never run at once.
* The cost is visible: `duration_seconds`, `available`, `checked`, `unchecked`,
  plus the `criterion` string. `available` is counted from the live cache, not from
  the report, so a capped run says so instead of looking complete —
  `test_the_response_shows_what_the_check_cost` (3 available, limit 1 → `checked: 1`,
  `unchecked: 2`).

Measured cost: **≈ 2.5–3.2 s per event** for the NSoft shells (they never produce
evidence, so every check pays the full 15 s settle window plus navigation) and
**≈ 1.5 s per event** for Mozzartbet (evidence arrives in ~1 s and the poll returns
early). 5 events ≈ 85 s for MDShop/Admiralbet, ≈ 17 s for Mozzartbet.

## 4. The two write questions

### Per-mode? **Yes.**
`template` and `template_live` are different routes and a live event id is not a
prematch one, so a live proof must not satisfy a prematch match
(`test_live_and_prematch_verifications_are_separate`). The whole store is keyed by
mode, and `?mode=live` checks `…/sr/uzivo/mec/1/{id}`.

### Is a stale verification cleared? **Yes, but only on a completed check.**
* Completed check, nothing found → the record is **deleted** and the cached match's
  flag is cleared (`test_a_stale_verification_is_cleared_by_a_later_failed_check`).
* Check that **errored** (timeout, nav error) → the record is left alone
  (`test_a_navigation_error_is_not_a_failed_check`). Absence of evidence is not
  evidence of absence, and a flaky network must not revoke a proof.
* TTL 1 h, enforced on load, on apply (pruned and rewritten), and by
  `_deep_link_record_is_fresh` (`test_an_expired_verification_is_ignored_and_dropped`).

### One deviation from the brief, and it is deliberate
The brief has the endpoint write into `cached_matches`. That is not enough: a scan
rebuilds every match from the scrapers, all of which hardcode
`deep_link_verified=False`, so a cache-only write is destroyed by the next scan
within minutes. The durable record is therefore `cache/deep_link_verifications.json`
and `run_scan` re-applies it as a dict lookup before the matcher
(`test_a_stored_verification_reaches_the_next_scan`,
`test_verification_survives_a_cache_reload`). The browser still never runs in a
scan. **Net effect on the stated intent:** the brief's framing ("so the next scan's
gate can see them") is not true of a cache-only write; it is true of this one.

Also: the endpoint does not touch `pending_candidates`, `_suppressed_candidates` or
the allowlist (`test_verifying_links_does_not_touch_the_candidate_queue_or_allowlist`),
and it only touches matches of the requested bookmaker
(`test_only_the_matching_bookmaker_is_touched`).

---

## 5. What "verified" means here, and how the bar got raised

`deep_link_verified` is set **only** when the id is resolved as *data*, by a
response attributable to our request, or shown as a value on the page:

1. a JSON payload from a book-owned host, **whose request URL carries the event id**,
   containing the id as the value of a key that names an event (`id`, `matchId`,
   `eventId` — any key ending in `id`), as an **int or string**; or
2. the rendered text of the page or a sub-frame showing the id as a standalone
   value — never adjacent to URL punctuation, never a decimal.

### The brief's check, and why I did not ship it

The brief's Step 4 is `found = m["event_id"] in body` on `page.content()`. I
measured it against a control (an id in no feed) **before** writing any code:

```
mdshop event_id=6828117     id_in_main=True   (inside <iframe src="…&eventId=6828117">)
mdshop event_id=999999999999 id_in_main=True  (same page, same iframe src shape)
```

The NSoft shell forwards the query parameter into the product iframe's `src` and
echoes the return URL into a tracking link, so the brief's check returns `True` for
**an event id that has never existed**. Shipping it would have set
`deep_link_verified=True` on dead links and unblocked `verified` groups on false
evidence. Mozzartbet's shell does the same thing with `og:url`.

### Three more false passes the controls caught, and what fixed them

| # | control | what happened | rule added |
|---|---|---|---|
| 1 | dead id `999999999999` on MDShop | **verified** via `mdoffer.mdshop.ba/api/SlowCache/businessModel/1678`, which contains `"maxTotalOdd":999999999999.00` | structural, not lexical: a key that names an event, an int/string value, **never a float** (`test_a_config_number_that_merely_contains_the_id_is_not_evidence`) — but see the correction below: the KEY rule is what stopped this control |
| 2 | MDShop/Admiralbet real ids | 0 whole-token hits in 211/250 response bodies, and the product iframe's render is **byte-identical** to the plain sport page after digit normalisation (815,530 = 815,530; the visible text is the 2,547-char sport nav) | nothing to add — the route simply proves nothing, and the check reports that |
| 3 | Admiralbet `6828118`, `6828120` | **"verified"** (2 of 6) via `sport.admiralbet.ba/set-api-rs/api/webclient/bonus-tickets-with-details` — a 29,382 B payload served on **every** page load, with and without `?event=`, which merely lists the events that happen to have a bonus ticket | **attributability**: the payload must have been *requested for that id* (`test_a_nsoft_event_id_field_is_not_enough`) |

**Correction (fix round 1, at the reviewer's request).** Row 1 credited the
`maxTotalOdd` false pass to the "never a float" rule. Both rules were live in that
run, and the **key rule alone already rejected it**: `"maxTotalOdd".lower()` is
`"maxtotalodd"`, which does not end in `"id"`, so it never reached the
int-vs-float comparison. The float rule is real but was not the defence that
stopped this control; the key rule was, and it has since been tightened further
(§9.4). Nothing about the outcome changes — the control still fails, and it now
fails on two independent grounds.

Control 3 is the one that mattered. The evidence was real data about a real event
and still proved nothing about the link, and only a no-event control run exposed it:

```
plain-no-event:  bonus_ticket_payloads=1  29382B  contains 6828118 = True
with-event:      bonus_ticket_payloads=1  29382B  contains 6828118 = True
with-other-event:bonus_ticket_payloads=1  29382B  contains 6828118 = True

request paths ONLY in with-event vs plain (5):
   bihoffer.admiralbet.ba/api/offer/sportsWithEventsStartingSoon/…
   bihoffer.admiralbet.ba/api/offer/webTree/…
   connect.facebook.net/signals/config/…   google.com/g/collect   facebook.com/tr/
```

No event-scoped request. The same shape held for MDShop (probe: 271 vs 272
requests, all differences being timestamps in the same offer paths).

---

## 6. Per-book result, with the evidence

Live run of the **shipped** code on 2026-09-25, real ids scraped minutes earlier.
`verify_bookmaker(..., limit=5)`:

| bookmaker | declared | verified | checked | cost | what was found |
|---|---|---|---|---|---|
| **mdshop** | `supports_event_id: true` | **0** | 5 | 84.2 s | nothing: `no book-owned JSON payload or rendered text carried <id> (http 200)` |
| **admiralbet** | `supports_event_id: true` | **0** | 5 | 83.5 s | nothing (the two bonus-ticket "hits" are gone under rule 3) |
| **mozzartbet** | `supports_event_id: true` | **5** | 5 | 17.6 s | `book payload https://www.mozzartbet.ba/betting/match/9984468 (application/json) served $.match.id = 9984468` |
| wwin (+5 more) | `false` | — | — | 0.0 s | `skipped: no declared event route` |

Was the event id **actually found in the served page**?

* **mozzartbet — YES, and it is the real thing.** The SPA issues
  `GET /betting/match/<id>` and the server resolves the event:
  `{"match":{"id":9984468,"rank":100,"filter":{"matchId":9984468,…` in **327,946 B**.
  The same route for a dead id answers **HTTP 200 with 14 bytes** and no such field.
  Across three runs: **15/15** events verified (5 + 6 + 4), 0 failures.
* **mdshop — NO.** 0/11 real events across three runs. The id appears in the main
  document only as an echo (`<iframe src="…&eventId=…">`), never in the 211
  captured bodies, never in the 815 KB product-frame render (whose digit-normalised
  form is identical to the plain page), and never in the 2,547 chars of visible text.
* **admiralbet — NO.** 0/11 real events across three runs, for the same reasons
  (the product is the same NSoft build). The two bonus-ticket hits that the looser
  rule produced were measured to be unrelated to `?event=`.

Control, same code, id `999999999999` (in no feed): **0/3 verified** — mdshop,
admiralbet and mozzartbet all report
`no book-owned JSON payload or rendered text carried 999999999999 (http 200)`.

### What this costs the product (measured, not asserted)

Real 1,592-match feed (mdshop 483 + admiralbet 483 + mozzartbet 626, fresh scrape),
`MatchMatcher` run twice:

```
verify mdshop: 0/12 (192.4s)     verify admiralbet: 0/12 (192.7s)     verify mozzartbet: 12/12 (31.1s)
AS SHIPPED (only provable links marked):  1592 matches -> 0 groups  {}          (1.4s)
COUNTERFACTUAL (every link marked proven): 1592 matches -> 197 groups {'verified': 197} (1.3s)
```

0 → 197 is the size of what the unprovable NSoft route holds back. `group_matches`
only appends a match when `gate.evaluate` returns `verified`, so with every book
unproven the matcher produces **no groups at all** — which is why
`cached_match_groups_report` is empty and the surebet engine has nothing to work
on. The mechanism itself is proven end to end by
`test_a_stored_verification_unblocks_a_verified_group` (two books, two stored
proofs, real `MatchMatcher` → one `verified` group).

---

## 7. Commands and full output

### 7.1 Step 2 — the new tests fail first

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py -v
ImportError while importing test module 'tests\test_verify_links.py'.
E   ImportError: cannot import name 'verify_deeplinks' from 'scripts' (unknown location)
collected 0 items / 1 error
```

### 7.2 After the first implementation — 7 real failures, 30 passing

```
tests\test_verify_links.py F..FFFFFFFF........F.................F
FAILED tests/test_verify_links.py::test_the_event_id_in_a_book_owned_payload_is_evidence
FAILED tests/test_verify_links.py::test_a_navigation_error_is_not_a_failed_check
FAILED tests/test_verify_links.py::test_apply_report_reports_how_many_matches_it_changed
FAILED tests/test_verify_links.py::test_the_response_shows_what_the_check_cost
FAILED tests/test_verify_links.py::test_a_stored_verification_reaches_the_next_scan
FAILED tests/test_verify_links.py::test_a_stored_verification_unblocks_a_verified_group
FAILED tests/test_verify_links.py::test_the_live_template_is_used_for_a_live_check
1 failed, 36 passed
```

Six were my own test bugs (a helper that hardcoded the store key, a `_stub_scan`
that gave both scrapers both books, `available` counted from the cache rather than
the report). One was a real implementation gap: an expired record was ignored but
never pruned, so `_apply_deep_link_verifications` now prunes and rewrites. That one
I fixed in the implementation, not the test.

### 7.3 The control-driven test additions, failing first

```
$ …python.exe -m pytest tests/test_verify_links.py -k "config_number or key_that_does_not or different_value or nsoft_event_id_field or not_json or control_dead"
FAILED tests/test_verify_links.py::test_a_config_number_that_merely_contains_the_id_is_not_evidence
FAILED tests/test_verify_links.py::test_a_value_under_a_key_that_does_not_name_an_event_is_not_evidence
FAILED tests/test_verify_links.py::test_a_body_that_is_not_json_is_never_payload_evidence
FAILED tests/test_verify_links.py::test_a_control_dead_id_never_verifies_on_the_nsoft_shell
1 failed, 2 passed, 37 deselected
```

and after the attributability rule:

```
$ …python.exe -m pytest tests/test_verify_links.py -k "nsoft_event_id_field"
FAILED tests/test_verify_links.py::test_a_nsoft_event_id_field_is_not_enough
1 failed, 46 deselected
```

### 7.4 This task's file, green

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py -v
…
tests\test_verify_links.py ..............................................  [100%]
46 passed, 3 warnings in 2.07s
```

### 7.5 FULL suite, ruff, mypy — final, before the commit

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
450 passed, 1 xfailed, 3 warnings in 14.13s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
Success: no issues found in 57 source files
```

**450 passed, 0 failed, 0 errors, 1 xfailed.** Verified split:

```
$ …python.exe -m pytest tests/test_verify_links.py            →  46 passed
$ …python.exe -m pytest --ignore=tests/test_verify_links.py   →  404 passed, 1 xfailed
$ …python.exe -m pytest                                       →  450 passed, 1 xfailed
```

404 already on `master` (Tasks 10 and 11 included) + **46 new**, all in this task's
file. The `1 xfailed` is pre-existing — Task 11's documented Premier live BTTS
defect. The 3 warnings are the pre-existing FastAPI `on_event` deprecations.

### 7.6 Live endpoint run (shipped code, `TestClient`, temp store, repo cache untouched)

```
=== POST /api/verify-links?bookmaker=mozzartbet -> 200
{"bookmaker":"mozzartbet","mode":"prematch","status":"checked",
 "criterion":"event id resolved as a value under a key that names an event in a book-owned JSON
   payload that was requested for that id, or shown as a standalone value in rendered page text; …",
 "available":665,"checked":2,"verified":2,"failed":0,"unchecked":663,"duration_seconds":15.99,
 "details":[{"event_id":"9984468","url":"https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/9984468",
   "verified":true,"evidence":"book payload https://www.mozzartbet.ba/betting/match/9984468
   (application/json) served $.match.id = 9984468","error":""}, …]}

=== POST /api/verify-links?bookmaker=wwin -> 200
{"bookmaker":"wwin","status":"skipped","skip_reason":"wwin declares no declared event route — nothing to verify",
 "available":0,"checked":0,"verified":0,"failed":0,"unchecked":0,"duration_seconds":0.0,"details":[]}
```

(That run predates the attributability rule, so it still shows the admiralbet
bonus-ticket hit; §6's table is the final code. The control section of the same run
showed mdshop false-passing, which is what produced rule 1.)

### 7.7 CLI

```
$ "…python.exe" scripts/verify_deeplinks.py --help
usage: verify_deeplinks.py [-h] [--mode {prematch,live}] [--limit LIMIT] [bookmakers ...]

$ "…python.exe" scripts/verify_deeplinks.py mozzartbet wwin --limit 1
{"bookmaker":"mozzartbet","status":"checked",
 "skip_reason":"no mozzartbet match carries an event id — nothing to check (run a scan first)",
 "available":0,"checked":0,"verified":0,"failed":0,"duration_seconds":0.0,"outcomes":[]}
{"bookmaker":"wwin","status":"skipped",
 "skip_reason":"wwin declares no declared event route — nothing to verify", …}
```

The repo's `cache/last_scan.json` is the stale 2026-08-20 scan and predates the
`event_id` field, hence "nothing to check" — reported, not papered over, and no
browser was launched.

---

## 8. Concerns

1. **`verified` is still unreachable in production, and this task is why that is
   now provable rather than assumed.** Only Mozzartbet's route is provable
   (15/15). MDShop and Admiralbet declare a per-event route that does not select
   the event, so every group containing them stays `link_unverified`, and since
   `group_matches` only admits gate-verified pairs the matcher returns **0 groups**
   on a real 1,592-match feed where it would return 197. I did not weaken the
   criterion to make them pass, and I did not flip their declaration (see 3).
2. **The declaration in `config/bookmaker_deeplinks.json` is now contradicted by
   measurement** for mdshop and admiralbet (`supports_event_id: true`, but the route
   is inert). I left it alone on purpose: flipping it to `false` changes **nothing**
   in the gate, because `_link_evidence` blocks on `m.event_id or m.url` and both
   scrapers always set them — it would only make `build_event_url` return the plain
   sport page and make the *links we give the user* worse. The real follow-up is a
   decision I do not own: either find a route the NSoft SPA actually honours (the
   undocumented `ticketItems` fast-bet deep link that `nsoft_event_url`'s own
   docstring mentions) **or** accept `no_event_link` for those books by teaching the
   mdshop/admiralbet scrapers to leave `url`/`event_id` empty, which would make
   197 groups verifiable but would also mean "we do not link these books at all".
   Both are product decisions; neither belongs in this task.
3. **The endpoint is not rate-limited.** `/api/scan` has `SCAN_RATE_LIMIT`; this one
   has a 409 and a serialising lock but no cooldown, so a client can queue
   back-to-back runs at ~3 s per event. A `_scan_request_times`-style window is the
   obvious fix if that matters.
4. **The 1 h TTL is a guess.** It bounds how long a proof can outlive the event it
   proved, but nothing measures how fast Mozzartbet retires an event id. Too short
   and the group re-verify loop never converges; too long and a dead link keeps
   unblocking `verified`. `DEEP_LINK_VERIFICATION_TTL_SECONDS` is the single knob.
5. **The Mozzartbet criterion is coupled to one undocumented endpoint.** It depends
   on the SPA continuing to request `/betting/match/<id>`; if that route changes, the
   check fails closed (0 verified) rather than open, which is the safe direction, but
   it would look like a bookmaker problem rather than a selector problem. The
   response always names the payload URL, so a failure is diagnosable.
6. **Every check costs 2.5–3.2 s for a book that will never verify** (it must pay
   the full 15 s settle window to be sure). Verifying 12 events of mdshop took
   192 s. The store means that cost is paid once per event per hour, not per scan,
   but an operator pressing the button on a book that cannot verify pays the most.
7. **No frontend.** The endpoint is API-only; the Review tab still says the link
   check "is a separate system verification" and there is no button to run it. The
   `/api/health` `unverified_links` counter is the only place the result surfaces in
   the UI today.
8. **The store is keyed by `bookmaker|event_id`, not by URL.** If a declaration's
   `template` changes, old records still apply to the same id. Harmless today (the
   record stores the URL it proved) but it would be wrong to rely on across a
   template change; the record's `url` is the thing to compare if that ever matters.
9. **Live mode is untested against a real bookmaker.** Every live measurement here is
   prematch. The live templates (`/sport-live?event=`, `/sr/uzivo/mec/1/{id}`) go
   through the same code path, and the same criterion is expected to be at least as
   strict, but no live event id was available to check.

---

# Fix round 1

Base commit `2f4a1e8`. Spec compliance was already ✅ with zero Critical issues, and
nothing confirmed in round 1 has been undone: the NSoft inert-route finding, the
rejection of the brief's `event_id in body` criterion, Mozzartbet's `$.match.id`,
both design decisions, the durable-store ordering and "a timeout never revokes a
proof" are all unchanged. This round adds the tests for the load-bearing
assumption, the endpoint's cost controls, and the cheap corrections.

Files: `server/api.py` (+108/−29), `tests/test_verify_links.py` (+398/−…),
`scripts/verify_deeplinks.py` (+30/−6), `config/settings.py` (+6),
`scripts/__init__.py` (docstring).

## 9.1 IMPORTANT — throttling, browser concurrency, and the post-await re-check

`_require_api_key` is a no-op unless `API_KEY` is set (`settings.py:135` defaults
to `""`), so the endpoint is open on any deployment without a key while it drives a
real browser at third-party sites. All three required parts are in.

**A sliding window, and which one was reused.** `/api/scan` had the window as six
inline lines, not as a helper, so I lifted that exact code into
`_enforce_sliding_window(request, bucket, limit, what)` (`api.py:1201`) and both
endpoints call it. It reuses the scan's semantics — per-client-IP, 60 s window,
429 on overflow — and the window length itself is now the shared constant
`RATE_LIMIT_WINDOW_SECONDS = DEEP_LINK_VERIFY_RATE_WINDOW_SECONDS` (60 s), which
`/api/scan`'s hard-coded `60` also used. The **bucket is separate**:
`_scan_request_times` vs `_verify_link_request_times`, so spending one budget
cannot exhaust the other. Limits: scans keep `SCAN_RATE_LIMIT` (3/min, unchanged
behaviour); the check gets `DEEP_LINK_VERIFY_RATE_LIMIT = 2/min`, env-overridable.
Two per minute is deliberate: one run is 8 s for one Mozzartbet event and ~85 s for
five NSoft events, so two per minute cannot be used to hammer a bookmaker even
accidentally, while an operator working through a book is not blocked.

```python
    # Refuse a flood BEFORE paying for a browser. Throttling, not serialising.
    _enforce_sliding_window(
        request, _verify_link_request_times, DEEP_LINK_VERIFY_RATE_LIMIT, "verify-links checks"
    )
```

The check's own `_deep_link_check_lock` is kept, and the reviewer's point stands —
it serialises, it does not throttle, so it stays as the second line and the window
is the first.

**`_browser_sem`.** The check now runs inside the same semaphore the Playwright
scrapers use, so total browser concurrency cannot exceed
`BROWSER_CONCURRENCY=2` server-wide — a scan that starts *after* the 409 check
still finds its budget respected:

```python
    async with _deep_link_check_lock:
        async with _browser_sem:
            report = await _run_link_verification(...)
```

**Post-await re-check.** The 409 above is a snapshot taken minutes before the
writes, so the scan state is read again after the await and the cache write is
skipped if a scan overtook us. The proof itself is still stored, because the store
is per-event, TTL'd and written atomically, and the next scan applies it:

```python
    status_after, _, _, _, _ = _state_for(mode)
    scan_underway = _lock_for(mode).locked() or status_after.is_scanning
    applied = not scan_underway
    ...
    else:
        applied_note = (
            f"a {mode} scan started while this check was running, so the cached "
            "matches were left untouched; the proof is stored and the next scan "
            "will apply it"
        )
```

`applied` and `applied_note` are in every response body (including the two
early-return shapes), so a caller is never told a cache write happened when it
did not. Tests: `test_verify_links_is_throttled_with_a_429`,
`test_a_throttled_call_does_not_run_the_checker`,
`test_the_scan_and_verify_link_budgets_are_separate`,
`test_the_check_runs_inside_the_browser_semaphore`,
`test_a_scan_that_starts_during_the_check_skips_the_cache_write`,
`test_the_proof_is_still_recorded_when_the_cache_write_is_skipped`,
`test_a_normal_run_reports_that_it_applied`.

The semaphore test wraps the **real** semaphore in a recorder and asserts it was
held for the whole run and released after, plus that the real semaphore is back to
`BROWSER_CONCURRENCY` free slots — a leak would be invisible to a `locked()`
assertion, because `Semaphore(2).locked()` is `False` while one slot is in use.

### Measured, live, through the endpoint

```
SCRAPE mozzartbet: 622 matches, first ids ['9985390', '9985407', '9985416']

--- attempt 1: HTTP 200
{ "bookmaker": "mozzartbet", "status": "checked", "available": 622,
  "checked": 1, "verified": 1, "failed": 0, "errored": 0, "unchecked": 621,
  "duration_seconds": 8.05, "applied": true, "applied_note": "" }
    detail[0].evidence: book payload https://www.mozzartbet.ba/betting/match/9985390
      (application/json) served $.match.id = 9985390
    checked == verified + failed + errored: OK

--- attempt 2: HTTP 200   (verified 1, 8.27s, applied true)
--- attempt 3: HTTP 429
    detail: Rate limit exceeded: max 2 verify-links checks per 60 seconds
```

## 9.2 MINOR that was actually load-bearing — subframes now have tests

The review was right, and I verified it before writing the test: with the shipped
code, narrowing `page.on("response")` to the main frame and dropping the
`page.frames` loop **kept all 46 tests green**. That is the assumption the entire
finding rests on, untested.

`tests/test_verify_links.py` now has a fake `Page`/`Frame`/`Response` harness
(`FakePage` carries a real `main_frame` + `frames` list, and each `FakeResponse`
records the frame it came from) and six tests:

| test | what it pins |
|---|---|
| `test_a_subframe_response_proves_the_link` | evidence delivered by an IFRAME verifies |
| `test_a_main_frame_response_still_proves_the_link` | the main frame is not special-cased |
| `test_a_subframe_does_not_make_a_third_party_response_evidence` | subframes do not bypass the host rule |
| `test_rendered_text_of_a_subframe_proves_the_link` | the `page.frames` loop, for text |
| `test_rendered_text_of_the_main_frame_still_proves_the_link` | ditto for the shell |
| `test_a_subframe_showing_our_own_url_is_not_evidence` | an iframe echoing the URL proves nothing |

The fake schedules the handler with `asyncio.ensure_future` because Playwright's
async event emitter does exactly that; calling the coroutine handler synchronously
is what made the first version of these tests fail for the wrong reason.

### Evidence that a main-frame-only implementation fails them

Both narrowings applied to the shipped file, one at a time, against the final code:

```
$ …python.exe - <<'PY'   # then pytest
VARIANT 1 applied: page.on('response') narrowed to the main frame only
FAILED tests/test_verify_links.py::test_a_subframe_response_proves_the_link
1 failed, 80 passed, 3 warnings in 2.55s

>       assert outcome.verified is True, outcome.evidence
E       AssertionError: no book-owned JSON payload or rendered text carried 9984468 (http 200)

VARIANT 2 applied: the page.frames loop dropped to the shell frame only
FAILED tests/test_verify_links.py::test_rendered_text_of_a_subframe_proves_the_link
1 failed, 80 passed, 3 warnings in 2.51s

--- restored ---
81 passed, 3 warnings in 2.21s
```

Each regression is caught independently, and the failure message is the same one
the NSoft conclusion rests on ("no book-owned JSON payload or rendered text
carried …") — so silently inverting the finding now breaks the build instead of
quietly changing a report.

### A real bug this shook out

`rendered_text_evidence` rejected an id at the very start or end of the text,
because `"" in "/?&#=.,;:"` is `True` in Python. Nothing in the live measurements
hit it (no book ever showed the id in visible text).

**Corrected attribution (fix round 2).** This section first credited the
subframe-text test. That was wrong, and re-verified by mutation: reverting the fix
so the empty neighbour is tested again fails exactly one test —
`test_rendered_text_of_the_main_frame_still_proves_the_link`, whose text is
`f"Utakmica {EVENT_ID}"` and therefore puts the id at the very **end** of the
string. The subframe-text test places the id mid-string between a space and `\n`,
neither of which is in `URL_PUNCTUATION`, so it passes either way and never
observed the bug.

```
$ …python.exe -m pytest tests/test_verify_links.py -k "rendered_text" -v
MUTANT applied: reverted the empty-neighbour fix
FAILED tests/test_verify_links.py::test_rendered_text_of_the_main_frame_still_proves_the_link
1 failed, 1 passed, 79 deselected, 3 warnings in 1.70s
```

## 9.3 Cheap corrections

* **`errored` is now counted.** `LinkReport.errored` and `"errored"` in the
  response, so `checked == verified + failed + errored` always holds
  (`test_errored_checks_are_counted_separately`, `test_the_response_reports_errored_checks`).
  The live run above asserts the identity in-process.
* **`scripts/__init__.py`** no longer claims the package is "not part of the
  running application" — `server/api.py` imports it, and the docstring now says so.
* **`test_the_event_id_in_a_book_owned_payload_is_evidence`** no longer indexes
  `found[1]` unguarded: it asserts `len(found) >= 1` and then checks the
  `$.match.id` path is present, so a single-hit payload reports a clean assertion
  failure instead of an `IndexError`.

## 9.4 The id-key rule, tightened

`key.lower().endswith("id")` also accepted `paid`, `valid`, `grid`, `void` and
`uuid`. The rule is now explicit:

```python
EVENT_ID_KEYS = frozenset({"id", "eventid", "matchid", "gameid", "fixtureid"})
EVENT_ID_KEY_SUFFIXES = ("eventid", "matchid", "gameid", "fixtureid")

def is_event_id_key(key: str) -> bool:
    normalized = key.lower().replace("_", "")
    return normalized in EVENT_ID_KEYS or normalized.endswith(EVENT_ID_KEY_SUFFIXES)
```

Negative cases, each a live-shaped key that must not speak for an event
(`test_keys_that_merely_end_in_id_are_not_accepted`): `paid`, `valid`, `grid`,
`void`, `uuid`, `maxTotalOdd`, `displayNumberFormat`, `selectionId`, `oddsId`.
Positive cases (`test_keys_that_name_an_event_are_accepted`): `id`, `ID`,
`eventId`, `matchId`, `event_id`, `match_id`, `gameId`, `fixtureId`,
`originalEventId`, `parentMatchId` — the last two matter because they are the
compound forms a real feed uses. The two measured payloads still verify:
`$.match.id` (Mozzartbet) and `[13].bonusTicketItems[1].eventId` (NSoft, still
rejected earlier for being unattributable, which is the point).

## 9.5 Covering test files

`tests/test_verify_links.py` — **81 tests** (46 → 81), all of the above. No other
test file needed changing; `config/settings.py` only gained two constants, and the
scan endpoint's rate-limit behaviour is unchanged (3/min, 429) and still covered by
the pre-existing suite.

## 9.6 Commands and output

### Failing first

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py
… ERROR at setup of test_verify_links_requires_bookmaker_param
   AttributeError: module 'server.api' has no attribute '_verify_link_request_times'
… 81 collected
```

Every test errored at fixture setup because the throttle bucket did not exist yet —
the missing implementation, not a broken test.

After the first cut of the implementation, three genuine test-side mistakes of mine
surfaced (my `_report()` fixture did not fill `errored`; `_browser_sem.locked()` is
`False` while one of two slots is held; the bucket-separation test over-filled the
scan window instead of expecting its 429):

```
$ …python.exe -m pytest tests/test_verify_links.py
FAILED tests/test_verify_links.py::test_the_scan_and_verify_link_budgets_are_separate
FAILED tests/test_verify_links.py::test_the_check_runs_inside_the_browser_semaphore
FAILED tests/test_verify_links.py::test_the_response_reports_errored_checks
3 failed, 78 passed, 3 warnings in 2.77s

TypeError: 'RecordingSemaphore' object does not support the asynchronous context manager protocol
AttributeError: 'RecordingSemaphore' object has no attribute 'locked'
AttributeError: 'RecordingSemaphore' object has no attribute '_value'
```

All three fixed in the tests (the recorder gained `__aenter__`/`__aexit__` and
`locked()`, and the final assertion now reads the *real* semaphore captured before
the patch).

### This task's file, green

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py
81 passed, 3 warnings in 2.21s
```

### Full suite, ruff, mypy — final

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
485 passed, 1 xfailed, 3 warnings in 14.06s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
Success: no issues found in 57 source files
```

**485 passed, 0 failed, 0 errors, 1 xfailed** (the pre-existing Premier live BTTS
xfail; the 3 warnings are the pre-existing FastAPI `on_event` deprecations). Split:
404 pre-existing + 46 from round 1 + **35 new this round** = 485.
`tests/test_verify_links.py` alone is 81.

## 9.7 Concerns after this round

1. **Nothing here changes the headline.** MDShop and Admiralbet still cannot be
   verified, so `verified` groups are still unreachable in production (0 of 197 on a
   real 1,592-match feed). The subframe tests prove that conclusion was reached by
   actually examining the iframe, and that a regression would now fail the build.
2. **`DEEP_LINK_VERIFY_RATE_LIMIT = 2/min` is my number, not a measurement.** It is
   env-overridable, and it is not what stops an operator sweeping a book.

   **Corrected attribution (fix round 2).** This concern previously said the
   throttle "makes the pre-existing convergence problem worse". That was wrong and
   would have sent a maintainer to tune the wrong knob. The actual blocker is that
   **`build_targets` has no cursor, no offset and no skip of already-checked
   events** (`verify_deeplinks.py:294-317`): it walks the cache in order, dedupes
   event ids, and `break`s at `limit`. So repeated calls re-check the *same* first
   N events forever — 32 calls at `limit=20` would never reach event 21, with or
   without a rate limit. An unlimited limit converges no further than a limited
   one; it just fails faster.

   The cost arithmetic, stated honestly: the throttle costs ~16 minutes of wall
   clock to cover a 622-event book at `limit=20`; the missing cursor costs
   infinity. The fix is an **offset / `skip_verified` on `build_targets` plus a
   cursor echoed in the response** — not a bigger limit, and not a looser
   throttle. It is deliberately **not** implemented in this task (it is a feature,
   and it changes the request/response contract), but the cause is recorded here so
   nobody "fixes" the throttle instead.
3. **The post-await re-check leaves a real gap, deliberately.** If a scan starts
   during a check, the proof is stored but that scan will not see it — its
   `_apply_deep_link_verifications` already ran — so the group stays unverified for
   that cycle. The alternative, writing into a scan's in-flight match list, is the
   TOCTOU this avoids. The response says so in `applied_note`, including the
   asymmetry noted in §10.4.
4. **The in-memory windows are per-process.** Two uvicorn workers get two budgets,
   exactly as they already do for `SCAN_RATE_LIMIT`. Unchanged, pre-existing.
5. **The `rendered_text_evidence` empty-neighbour bug was latent in a rule the
   headline never exercised.** It is a reminder that the text rule is nearly dead
   code in production (no book shows the id in visible text) and is therefore the
   least trustworthy part of the criterion: two tests now cover it, but it has no
   live evidence behind it.
6. **Deferred as instructed** (both fail safe, under-report only): requiring
   `Content-Type` to contain `json` hides a JSON body served as `text/plain`; and
   requiring the id in the *response* URL misses a POST that carries it in a
   request body. The Mozzartbet SPA uses neither, so nothing measured is affected.


---

# Fix round 2

Base commit `f2ee803`. The re-review confirmed all three round-1 items are
genuinely fixed, traced both mutants, and confirmed there is no lock-order
inversion. Nothing accepted in rounds 1–2 has been undone: the rate limit,
`_browser_sem` acquisition, the post-await re-check, both subframe tests, the
id-key tightening, the `scripts/__init__.py` docstring, the `found[1]` guard and
the §5 `maxTotalOdd` correction all stand.

Three of the eight items are the same error class the review arc keeps catching —
a comment or a report sentence describing something other than what the code
does — so I grepped both artifacts before changing either.

Files: `tests/test_verify_links.py` (+124/−…), `server/api.py` (+21/−14),
`scripts/verify_deeplinks.py` (+16/−13), `config/settings.py` (+5/−2).

## 10.1 Item 1 — the `errored` test: REWRITTEN, not deleted, and it bites

The reviewer is right: `test_verify_bookmaker_counts_errored_outcomes` recomputed
`report.errored` in the test body and asserted its own expression, so deleting
`verify_deeplinks.py`'s `report.errored = …` left it green. Manufactured coverage
of the only line that computes `errored` on the browser path.

**I rewrote it, because the fixture needed building anyway and the coverage is
worth having.** The fake browser harness is now complete enough to drive a real
`verify_bookmaker` run: `FakePage` gained `fail_urls` (a `goto` that raises
`TimeoutError`, exactly what a navigation timeout looks like) and
`set_default_navigation_timeout`, and `FakeContext` / `FakeBrowser` /
`FakePlaywright` plus `_install_fake_browser(monkeypatch, page)` stand in for
`launch_browser`. The test runs the real function over two real targets — one that
serves the event, one whose navigation never completes — and asserts on the object
it returned:

```python
report = run(verify_deeplinks.verify_bookmaker("mozzartbet", matches, limit=2))
assert report.checked == 2 and report.verified == 1 and report.failed == 0
assert report.errored == 1, "the navigation error was not counted as errored"
assert report.checked == report.verified + report.failed + report.errored
assert [o.error for o in report.outcomes if o.error]
assert playwright.stopped is True, "the browser was not shut down"
```

Proof that it bites, by deleting the production line:

```
$ …python.exe -m pytest tests/test_verify_links.py
MUTANT applied: deleted report.errored = sum(...) from verify_bookmaker
FAILED tests/test_verify_links.py::test_errored_checks_are_counted_by_a_real_verify_bookmaker_run
1 failed, 79 passed, 3 warnings in 2.85s
--- restored ---
80 passed, 3 warnings in 2.25s
```

It also pins the `finally` cleanup, which nothing covered before.

I also **deleted** the second self-fulfilling test
(`test_errored_checks_are_counted_separately`, which assigned `report.errored`
itself) rather than keep a decorative one; the arithmetic identity it asserted is
now asserted on the real report above. The endpoint-level
`test_the_response_reports_errored_checks` stays: it exercises the pass-through
through the documented `_run_link_verification` seam, which is a real contract.

## 10.2 Item 2 — the convergence concern was MIS-ATTRIBUTED; corrected

Round 1's concern #2 said the throttle "makes the pre-existing convergence problem
worse". The reviewer's counter-analysis is correct, and I read the code before
accepting it: `build_targets` (`verify_deeplinks.py:294-317`) walks the cache in
order, dedupes event ids and `break`s at `limit` — **no offset, no cursor, no
skip of already-checked events**. Repeated calls therefore re-check the same first
N events forever; 32 calls at `limit=20` would never reach event 21, and removing
the rate limit entirely converges exactly as far. The report now names the real
cause and the real fix (a cursor / `skip_verified`, plus a cursor echoed in the
response, **not** a bigger limit), and records that the cursor is deliberately not
implemented here. Not implemented in code this round, as instructed.

## 10.3 Item 3 — two docstrings and a report sentence that described the wrong defence

**`verify_deeplinks.py`.** The module docstring and `json_event_paths` still
presented `maxTotalOdd` as the float rule's evidence, contradicting §5 of the
report. Both now say the opposite of what they used to: the **key** rule is the
first of three and the one that stopped that control (`"maxtotalodd"` does not end
in `id`, so the int-vs-float comparison is never reached), with the float rule
described as a second line of defence for the same shape of false pass. The
`EVENT_ID_KEYS` comment now states which rule rejected the measured settings keys.

**The report's empty-neighbour attribution.** §9.2 credited the subframe-text
test with catching the `"" in "/?&#"` bug. Re-verified by mutation: that test
places the id mid-string between a space and `\n`, neither in `URL_PUNCTUATION`,
so it passes either way. The test that actually failed is
`test_rendered_text_of_the_main_frame_still_proves_the_link`, whose text ends with
the id. Both the correction and the mutation output are quoted in §9.2 above.

## 10.4 Item 4 — `applied` has three distinguishable states, and the note is honest

`applied: False` in the two zero-work early returns read as "a write was
suppressed" when nothing needed writing. `applied` is now:

| value | meaning |
|---|---|
| `None` | there was nothing to write (skipped book, or a cache with no event ids) |
| `False` | a write was suppressed because a scan started |
| `True` | the cached matches were written |

The `applied_note` for the suppressed case now also states the asymmetry the
reviewer identified: `_apply_deep_link_verifications` only ever SETS a flag, so a
skipped write defers a *positive* verdict to the next scan (the record is durable),
while a completed-FAIL pops the record and leaves a stale
`deep_link_verified=True` in `cached_matches` until a scan rebuilds the list from
the scrapers. Benign and bounded by one scan cycle, but now said out loud in the
response instead of only in a report. Tests:
`test_nothing_to_check_is_not_reported_as_a_suppressed_write`,
`test_an_empty_cache_is_not_reported_as_a_suppressed_write`,
`test_a_suppressed_write_says_what_it_defers`.

## 10.5 Cheap corrections

* **B2** — `isolate_state` now clears both rate-limit buckets at **teardown** as
  well as setup, like every other global it snapshots.
* **B3** — the scan window no longer derives from a deep-link knob.
  `config/settings.py` gains `RATE_LIMIT_WINDOW_SECONDS` (its own setting, default
  60) and `DEEP_LINK_VERIFY_RATE_WINDOW_SECONDS` is **deleted**, so nothing can
  tune one endpoint's window and silently move another's. Asserted by
  `test_both_rate_limits_share_one_window_constant`, which checks the value and
  that the old derivation line is gone from the module source.
* **B4** — the throttle is now charged *below* both zero-work early returns and
  still above the browser work, so `?bookmaker=wwin` and "nothing to check" cost
  nothing and a UI probing the book list cannot self-DoS
  (`test_a_zero_work_call_does_not_spend_the_throttle_budget`,
  `test_an_empty_cache_call_does_not_spend_the_throttle_budget`).
* **B7** — `EVENT_ID_KEYS` was 4/5 redundant with `EVENT_ID_KEY_SUFFIXES`; it is
  now just `{"id"}`, and `test_the_key_sets_have_no_redundant_entries` asserts the
  two sets do not overlap and that every entry is accepted. The misnamed
  `test_keys_that_merely_end_in_id_are_not_accepted` is split into
  `test_keys_that_merely_look_like_id_keys_are_not_accepted` (the real
  `endswith("id")` impostors: `paid`, `valid`, `grid`, `void`, `uuid`,
  `selectionId`, `oddsId`) and `test_settings_keys_are_not_accepted`
  (`maxTotalOdd`, `displayNumberFormat`, `maxStake` — which do *not* end in `id`
  and are rejected by the key rule, not the float rule).
* **B8** — `test_a_zero_limit_disables_the_throttle` covers the documented
  `DEEP_LINK_VERIFY_RATE_LIMIT=0` path: six calls, all 200, the checker invoked
  six times. **Correction (fix round 3):** round 2 also claimed here that the other
  throttle tests no longer depend on the setting being non-zero. That was false —
  three of them still read the ambient value and all three failed under
  `DEEP_LINK_VERIFY_RATE_LIMIT=0`. They are pinned now; see §11.1.

## 10.6 Covering test files

`tests/test_verify_links.py` — **89 tests** (81 → 89). No other test file needed
changing: `config/settings.py` only swaps one constant for another, and the scan
endpoint's rate limiting is behaviourally unchanged (3/min, 429, same window).

## 10.7 Commands and output

### Failing first

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py
FAILED tests/test_verify_links.py::test_nothing_to_check_is_not_reported_as_a_suppressed_write
FAILED tests/test_verify_links.py::test_an_empty_cache_is_not_reported_as_a_suppressed_write
FAILED tests/test_verify_links.py::test_a_suppressed_write_says_what_it_defers
FAILED tests/test_verify_links.py::test_a_zero_work_call_does_not_spend_the_throttle_budget
FAILED tests/test_verify_links.py::test_an_empty_cache_call_does_not_spend_the_throttle_budget
FAILED tests/test_verify_links.py::test_the_key_sets_have_no_redundant_entries
FAILED tests/test_verify_links.py::test_both_rate_limits_share_one_window_constant
7 failed, 82 passed, 3 warnings in 3.76s
```

The rewritten `errored` test passed on the first run, because it asserts behaviour
that already existed; the mutation check above is what proves it covers anything.

### Two mutants on the endpoint, one run

```
$ …python.exe -m pytest tests/test_verify_links.py
MUTANTS applied: throttle charged before the early returns; applied=False in the skip
FAILED tests/test_verify_links.py::test_nothing_to_check_is_not_reported_as_a_suppressed_write
FAILED tests/test_verify_links.py::test_a_zero_work_call_does_not_spend_the_throttle_budget
FAILED tests/test_verify_links.py::test_an_empty_cache_call_does_not_spend_the_throttle_budget
3 failed, 86 passed, 3 warnings in 3.34s
--- restored ---
89 passed, 3 warnings in 2.68s
```

### This task's file, green

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py
89 passed, 3 warnings in 2.68s
```

### Live re-run after the round-2 changes (the real path is untouched)

```
SCRAPE mozzartbet: 624 matches, first ids ['9985390', '9985407', '9985416']
--- attempt 1: HTTP 200   "verified": 1, "errored": 0, "applied": true, "applied_note": ""
--- attempt 2: HTTP 200   verified 1, applied true
--- attempt 3: HTTP 429   detail: Rate limit exceeded: max 2 verify-links checks per 60 seconds
```

### Full suite, ruff, mypy — final

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
493 passed, 1 xfailed, 3 warnings in 15.68s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
Success: no issues found in 57 source files
```

**493 passed, 0 failed, 0 errors, 1 xfailed** (the pre-existing Premier live BTTS
xfail; 3 pre-existing FastAPI `on_event` warnings). Split: 404 pre-existing + 46
+ 35 (round 1) + **8 new this round** = 493. `tests/test_verify_links.py` is 89.

## 10.8 Concerns after this round

1. **The headline is still unchanged and still the important sentence:** MDShop
   and Admiralbet cannot be verified, so `verified` groups remain unreachable in
   production. Nothing in this round touched that, by design.
2. **Convergence is blocked by the missing cursor, not the throttle** (corrected in
   §9.7 #2). Until `build_targets` grows an offset or `skip_verified`, this
   endpoint can only ever prove the first `limit` events of a book. The throttle is
   a cost control against third-party sites, not a convergence mechanism, and the
   report now says so.
3. **`applied: None` is a small API change** to a response shape introduced in
   round 1 of this same task, so no released consumer can depend on the old
   `False`. It is documented in §10.4 and the three states are distinguishable.
4. **The float rule remains unexercised as a defence.** The key rule rejects every
   measured settings payload, so no test can distinguish "key rule" from "key +
   float rule" against live data; the float rule is retained as a cheap second line
   and stated as such, so nobody later credits it with a defence it did not
   perform.
5. **The fake-browser harness is a fake.** The rewritten `errored` test runs the
   real `verify_bookmaker` and the real `check_target`, but against a fake page
   whose `goto` raises `TimeoutError` rather than a real Playwright timeout. It
   proves the counting and the cleanup; it does not prove that a real timeout
   produces a `LinkOutcome` with `error` set. No live run in this task happened to
   hit a timeout either, so that path still has no live evidence.


---

# Fix round 3

Base commit `1dfb33a`, which the re-review accepted ("accept the fix"). Three
small closers: one false sentence of my own, two instances of the same
environment-coupling fragility, one misnamed mechanism in a user-visible string,
and one defence that was disclosed but never exercised.

Files: `tests/test_verify_links.py` (+48/−21), `server/api.py` (+3/−3).

## 11.1 Item 1 — I took the FIX, not the retraction

The reviewer is right and I should not have written that sentence. Round 2's B8
bullet claimed the other throttle tests "no longer depend on the setting's value
being non-zero"; they did, and all three failed under the documented disabled
path. I claimed the other half of a finding I had only half done.

**I pinned them rather than retracting**, because an environment-independent
suite is strictly better than a documented fragility:
`test_verify_links_is_throttled_with_a_429`,
`test_a_throttled_call_does_not_run_the_checker` and
`test_the_scan_and_verify_link_budgets_are_separate` now all
`monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 2)` and assert against
that literal, so they test the throttle's *behaviour* rather than the deployment's
configuration. The disabled path keeps its own test
(`test_a_zero_limit_disables_the_throttle`, which pins `0` deliberately).

The claim is now true, and here is the proof it is true — the same suite under the
documented env alternatives, before and after:

```
# before the fix
$ DEEP_LINK_VERIFY_RATE_LIMIT=0 RATE_LIMIT_WINDOW_SECONDS=30 …python.exe -m pytest tests/test_verify_links.py
FAILED tests/test_verify_links.py::test_verify_links_is_throttled_with_a_429
FAILED tests/test_verify_links.py::test_a_throttled_call_does_not_run_the_checker
FAILED tests/test_verify_links.py::test_the_scan_and_verify_link_budgets_are_separate
FAILED tests/test_verify_links.py::test_both_rate_limits_share_one_window_constant
4 failed, 85 passed, 3 warnings in 3.00s

# after the fix
$ DEEP_LINK_VERIFY_RATE_LIMIT=0 RATE_LIMIT_WINDOW_SECONDS=30 …python.exe -m pytest tests/test_verify_links.py
90 passed, 3 warnings in 2.57s
$ DEEP_LINK_VERIFY_RATE_LIMIT=7 …python.exe -m pytest tests/test_verify_links.py
90 passed, 3 warnings in 2.69s
```

## 11.2 Item 2 — the same fragility in the test I had just written

`test_both_rate_limits_share_one_window_constant` asserted
`… == 60` against `RATE_LIMIT_WINDOW_SECONDS`, which round 2 had just made
env-overridable — a deployment or CI that sets it failed the suite (visible in the
"before" output above, where `RATE_LIMIT_WINDOW_SECONDS=30` fails exactly that
test). Both sides are now pinned, `api` and `config.settings`, so the test still
asserts the substance of B3 — the scan window is the shared setting and the old
`= DEEP_LINK_VERIFY_RATE_WINDOW_SECONDS` derivation is gone from the source —
without depending on the ambient value.

## 11.3 Item 3 — `applied_note` named the wrong line

The note said "the store write is one-sided". The store write is **two**-sided:
`_record_deep_link_outcomes` pops a record on a completed-fail
(`api.py:370`). It is `_apply_deep_link_verifications` that only ever SETS a flag.
The consequence I stated was right; the named mechanism was wrong, and it was
wrong about a line I had just fixed elsewhere in the same diff. The note now reads:

```
"will apply it. Note the asymmetry: the store write is two-sided — a "
"completed-FAIL pops the record — but _apply_deep_link_verifications "
"only ever SETS a flag, so a stale deep_link_verified=True survives in "
"the cache until a scan rebuilds that list from the scrapers"
```

The test now asserts the *name* of the line, not the word "demote", so a future
edit cannot quietly re-point the explanation at the wrong mechanism.

## 11.4 Also cheap

* **Report** — the stale "and no test covered it" in §9.2's empty-neighbour
  paragraph is gone; the paragraph right below it names the test that does.
* **`tests/test_verify_links.py`** — "Neither of these ends in `id`" said
  "Neither" for a three-key parametrize; now "None of these".

## 11.5 The float clause is now exercised

The reviewer agreed keeping the float rule was right — it is one clause inside an
existing guard and it makes the "never a float" promise structural — and was also
right that disclosure was not the only option. One test closes the gap, with the
shape that actually reaches the clause (a decimal under a genuinely event-named
key, which Go/PHP backends really do emit):

```python
def test_a_decimal_under_an_event_key_is_not_the_event():
    assert json_event_paths(f'{{"match":{{"id":{EVENT_ID}.0}}}}', EVENT_ID) == []
    assert json_event_paths(f'{{"eventId":{EVENT_ID}.00,"betName":"x"}}', EVENT_ID) == []
    # The same payload with an INT under the same key is evidence …
    assert json_event_paths(f'{{"match":{{"id":{EVENT_ID}}}}}', EVENT_ID) != []
```

`maxTotalOdd` never reaches the float comparison because the key rule rejects it
first, so until this test the clause had no coverage at all. The third assertion
keeps the test honest: it is about the decimal, not about rejecting everything.

## 11.6 Covering test file

`tests/test_verify_links.py` — **90 tests** (89 → 90). No other test file needed
changing; `server/api.py` changed only a user-visible string.

## 11.7 Commands and output

### Before the pinning fix, under the documented env alternatives

```
$ DEEP_LINK_VERIFY_RATE_LIMIT=0 RATE_LIMIT_WINDOW_SECONDS=30 "…python.exe" -m pytest tests/test_verify_links.py
FAILED tests/test_verify_links.py::test_verify_links_is_throttled_with_a_429
FAILED tests/test_verify_links.py::test_a_throttled_call_does_not_run_the_checker
FAILED tests/test_verify_links.py::test_the_scan_and_verify_link_budgets_are_separate
FAILED tests/test_verify_links.py::test_both_rate_limits_share_one_window_constant
4 failed, 85 passed, 3 warnings in 3.00s
```

(The reworded `applied_note` also failed the first run of this round —
`test_a_suppressed_write_says_what_it_defers` asserted the old word "demote" —
and its assertion was updated to name the line instead.)

### This task's file, green, in three environments

```
$ "…python.exe" -m pytest tests/test_verify_links.py
90 passed, 3 warnings in 2.95s
$ DEEP_LINK_VERIFY_RATE_LIMIT=0 RATE_LIMIT_WINDOW_SECONDS=30 "…python.exe" -m pytest tests/test_verify_links.py
90 passed, 3 warnings in 2.57s
$ DEEP_LINK_VERIFY_RATE_LIMIT=7 "…python.exe" -m pytest tests/test_verify_links.py
90 passed, 3 warnings in 2.69s
```

### Full suite, ruff, mypy — final

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
494 passed, 1 xfailed, 3 warnings in 14.41s

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
Success: no issues found in 57 source files
```

**494 passed, 0 failed, 0 errors, 1 xfailed** (the pre-existing Premier live BTTS
xfail; 3 pre-existing FastAPI `on_event` warnings). And the whole suite, not just
this file, under the env alternatives:

```
$ DEEP_LINK_VERIFY_RATE_LIMIT=0 RATE_LIMIT_WINDOW_SECONDS=30 "…python.exe" -m pytest
494 passed, 1 xfailed, 3 warnings in 14.26s
```

## 11.8 Concerns after this round

1. **The headline is unchanged:** MDShop and Admiralbet cannot be verified, so
   `verified` groups remain unreachable in production. Untouched by design.
2. **Convergence is still blocked by `build_targets` having no cursor** (corrected
   in §9.7 #2), not by the throttle. Unchanged and still not implemented, as
   instructed.
3. **A third instance of the "claimed more than I did" class is now closed, and
   the pattern is worth naming:** three rounds, four times, a report sentence or a
   docstring asserted a property the code did not have. Every fix so far has been a
   mutation or an env-var run rather than a re-read, which is the only reason they
   were caught. The remaining unverified-by-mutation claim in this report is §10.1's
   "it also pins the `finally` cleanup", which the same mutant run does support
   (`playwright.stopped`).
4. **The float clause now has a test but still no live evidence.** No bookmaker
   payload measured in this task put a decimal under an event-named key; the test
   encodes the shape as a precaution, not as an observation.
5. **`applied_note` is now long prose in an API response.** It is accurate, but a
   client that surfaces it verbatim will show a paragraph of implementation detail.
   If a UI ever renders it, the string should probably be split into a code and a
   human sentence.
