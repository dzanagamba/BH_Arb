# Task 8 Report — Review tab and status badges

**Commit:** `8e9da284ba1ab1272df2183b3618d427edd56477`  
**Commit message:** `feat(frontend): add Review tab for pending match candidates and status badges`

## What changed

- Added an accessible `Surebets` / `Review` tablist to `frontend/index.html`.
  - The existing empty state, no-results state, and results grid were moved into the `surebets-panel` so the new panel follows the same content flow.
  - Added the required identifiers: `id="review-tab"`, `id="review-panel"`, `id="review-count"`, and `id="candidates-list"`.
  - Added `role`, `aria-selected`, `aria-controls`, `hidden`, and left/right/Home/End keyboard navigation.
- Added candidate queue loading and rendering in `frontend/js/app.js`.
  - Fetches `GET /api/candidates`.
  - Sorts pending candidates by AI confidence descending without treating the score as an approval.
  - Renders teams, league, kickoff, bookmakers, gate reasons, AI explanation, and confidence.
  - Escapes API text before inserting it into candidate HTML.
  - Uses the existing empty-state structure for empty and failed queue loads.
- Added approve/reject actions.
  - Approve uses `window.confirm` and explains that it writes a reviewed alias to the trading allowlist.
  - Both actions POST to the Task 7 endpoints, disable card actions while pending, reload the queue, and show an inline retryable error on failure.
- Added a status badge to the surebet card template.
  - The default is `✓ Verified` because only verified match groups produce surebets.
  - If a future result payload supplies a supported status, the badge also handles `suggested` and `rejected` with text labels.
- Added `tests/test_frontend_review.py`.

## Existing design-system classes and patterns reused

The implementation stays within the existing terminal/signal/portfolio design language:

- Reused `.btn` with `.btn-primary` for **Approve pairing** and `.btn-mute` for **Reject pairing**. No `.btn-approve` or `.btn-reject` classes were introduced.
- Reused `.empty-state`, `.empty-state-icon`, `.empty-state-title`, and `.empty-state-desc` for Review empty and error states.
- Reused `.results-grid`, `.surebet-card`, `.card-market`, and the existing market/card layout for surebet status placement.
- Added a visible `:focus-visible` outline for keyboard users.
- Used existing tokens: `--bg-card`, `--border`, `--border-soft`, `--text`, `--text-2`, `--text-3`, `--accent`, `--accent-2`, `--accent-soft`, `--accent-border`, `--red`, `--red-soft`, `--green`, `--green-soft`, `--gold`, `--gold-soft`, `--radius`, and `--radius-sm`.
- Added `.results-tabs`, `.tab-btn`, `.tab-count`, `.tab-panel`, `.candidate-card`, `.status-badge`, and state classes only because those specific structures did not exist. Their spacing, surfaces, borders, typography, and states follow the surrounding CSS.
- Status, reason, button, and confidence meaning is carried by text; color is supplementary rather than the only signal.

## Reason-code label mapping

`frontend/js/app.js` defines `REASON_LABELS` as a data lookup object:

| Gate code | Reviewer-facing label |
|---|---|
| `league_mismatch` | Different league |
| `kickoff_delta` | Kickoff too far apart |
| `link_unverified` | Link not verified |
| `team_unresolved` | Teams do not match |
| `category_mismatch` | Different match category |
| `kickoff_missing` | Kickoff time missing |
| `orientation_unresolved` | Home/away order unclear |
| `no_event_link` | No event link |

The last two cover additional reasons emitted by the certainty gate. Each rendered reason keeps the raw code in a `title` attribute and as a secondary `<code>` value for debugging; unknown codes fall back to their raw value.

## Polling and behavior

- The existing 30-second health poll was not duplicated. `refreshDiagnostics()` calls both `loadHealth()` and `loadCandidates()` from the same `setInterval` cadence.
- The queue is also refreshed when the Review tab is opened and after a completed scan; those are event-driven refreshes, not another polling loop.
- AI confidence is sorted and shown with “Suggestion only — a human must decide.” Approval is always an explicit `window.confirm` followed by a POST; AI confidence never calls an approval endpoint.

## TDD and verification

### RED — failing test first

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v
```

The initial run failed for the intended reason. Full pytest result:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 2 items

tests\test_frontend_review.py FF                                         [100%]

=================================== FAILURES ===================================
__________________________ test_index_has_review_tab __________________________

    def test_index_has_review_tab():
>       assert 'id="review-tab"' in HTML
E       AssertionError: `id="review-tab"` was not present in the pre-change index.html.

____________________________ test_js_has_candidate_hooks ____________________________

    def test_js_has_candidate_hooks():
>       assert "loadCandidates" in JS
E       AssertionError: `loadCandidates` was not present in the pre-change app.js.

=========================== short test summary info ============================
FAILED tests/test_frontend_review.py::test_index_has_review_tab
FAILED tests/test_frontend_review.py::test_js_has_candidate_hooks
============================== 2 failed in 0.22s ==============================
```

The original pytest output also printed the complete pre-change HTML/JavaScript as the long assertion representation; the relevant failure is the missing required Review tab identifier and missing JavaScript hooks.

### GREEN — focused test

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 2 items

tests\test_frontend_review.py ..                                         [100%]

============================== 2 passed in 0.04s ==============================
```

### Full suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output:

```text
........................................................................ [ 33%]
........................................................................ [ 67%]
......................................................................   [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
          @app.on_event("startup")

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
          return self.router.on_event(event_type)  # ty: ignore[deprecated]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
214 passed, 3 warnings in 5.23s
```

The full suite explicitly passed **214 tests**. The three warnings are existing Starlette/FastAPI deprecations unrelated to this frontend change.

### Ruff

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m ruff check .
```

Full output:

```text
All checks passed!
```

### Mypy

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m mypy .
```

Full output:

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:204: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:249: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 48 source files
```

The mypy notes are existing `annotation-unchecked` informational notes; mypy reports success.

### Additional frontend checks

Command:

```text
node --check frontend/js/app.js
```

Full output:

```text
```

Exit code: `0` (no syntax errors).

Command:

```text
git diff --check
```

Full output:

```text
```

Exit code: `0` (no whitespace errors).

A headless Playwright smoke check was also run against a temporary local uvicorn instance with mocked API responses. It verified tab switching, AI-confidence ordering, human-readable reason labels, raw-code titles, keyboard tab navigation, and the approve confirmation. Output:

```text
frontend_review_playwright: passed
confirm: trading allowlist confirmation was shown
queue ordering: AI confidence descending
reason labels: human-readable with raw-code titles
```

## Deviations from the brief

1. The brief refers to existing result tabs and a dust tab, but this checkout had no existing `.tab-btn`, tab panel, or tab-switching markup. I added a small standards-based tablist around the existing results content rather than inventing a separate visual shell. This preserves the current empty/no-results/results flow and adds the requested Review view.
2. The illustrative brief CSS used new `.btn-approve`/`.btn-reject` colors and a separate candidate interval. The design direction explicitly overrides that example, so the implementation reuses `.btn-primary`/`.btn-mute` and shares the existing 30-second health cadence.
3. The illustrative empty-state snippet used a single paragraph. The implementation uses the existing empty-state title/description structure while retaining `candidates-list` and an honest no-queue message.
4. No application modal was present, so `window.confirm` was used as explicitly permitted by the brief.

## Concerns

- The original round-1 implementation inferred `✓ Verified` when no status was present; fix round 1 removes that unsafe default and renders a badge only for an explicit backend status.
- The Review queue is loaded from the global `/api/candidates` endpoint because the Task 7 candidate record has no mode field; this matches the endpoint contract in the brief.
- A desktop browser session was not connected in the harness, so visual inspection through the Review pane was unavailable. The headless Playwright smoke test above exercised the actual DOM and JavaScript with mocked API data and passed.
- The full suite reports three pre-existing deprecation warnings; no new Python warnings or lint/type errors were introduced.

## Fix round 1

**Commit:** `752d32a11f474f0ba320f4501f731ddb081f5cc1` (`fix(frontend): make review status and auth explicit`)

### Controller ruling and empty state

The missing production producer remains intentionally out of scope. The controller ruled that Task 10 will generate `CandidateReview` records; no producer was added in this round. The empty state now says exactly:

- **Title:** `Nothing to review yet.`
- **Description:** `No pairing candidates are queued for human review.`

This is honest about the current queue and does not promise that candidates will appear before the producer exists.

### Finding 1 — chose option (b): do not infer a backend status

I chose the smaller, better-scoped option (b) because the backend `Surebet` model and results payload do not carry a status field. Adding a schema/server change would expand this UI fix into producer/status plumbing without a backend source of truth yet.

The status badge now starts hidden and is populated only when the result explicitly contains `status` or `match_status` with a supported value. There is no fallback to `verified`; unsupported or absent statuses render no badge. Explicit `verified`, `suggested`, and `rejected` values use the existing text-labelled status styles.

### Finding 2 — behavioral Python coverage without adding a JS runner

There is no JavaScript test runner configured, and none was added. `tests/test_frontend_review.py` now contains five tests. The new reason-coverage test imports `CertaintyGate` and `HARD_REJECT_REASONS`, exercises real pair evaluations that emit the gate reason codes, parses the actual `REASON_LABELS` object from `frontend/js/app.js`, and asserts that every emitted reason has a non-blank human label. This catches a future missing reason mapping without duplicating the list in the test.

The same test file also asserts that the surebet template has no default verified badge and that candidate actions use the existing API-key header path.

### Finding 3 — no existing frontend API-key mechanism

A search of `frontend/js/app.js` found no existing API-key state, storage, prompt, or header helper. The backend already uses the established `X-API-Key` header, so I reused that contract rather than inventing a second authentication scheme. Candidate approve/reject requests now use `candidateActionFetch`; if a configured deployment returns 401 and no key is held, the UI prompts once for the key, keeps it in memory for the page session, and retries with `X-API-Key`. The key is not persisted or exposed in the DOM.

### Fix-round verification

**Focused test (red before implementation):**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v
```

The pre-fix run failed for the two intended new contracts: the default verified badge and missing API-key path. It reported `2 failed, 3 passed`.

**Focused test (green after implementation):**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 5 items

tests\test_frontend_review.py .....                                      [100%]

============================== 5 passed in 0.67s ==============================
```

**Full suite:**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output:

```text
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
.                                                                        [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
          @app.on_event("startup")

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
          return self.router.on_event(event_type)  # ty: ignore[deprecated]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
217 passed, 3 warnings in 4.83s
```

**Ruff:**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m ruff check .
```

Full output:

```text
All checks passed!
```

**Mypy:**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m mypy .
```

Full output:

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:204: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:249: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 48 source files
```

**JavaScript syntax:**

```text
node --check frontend/js/app.js
```

Full output: empty; exit code `0`.

**Whitespace check:**

```text
git diff --check
```

Full output: empty; exit code `0`.

A headless Playwright smoke check against a temporary local server also passed after the fix. It verified the exact empty-state copy, no status badge when the backend sends no status, a visible `Suggested` badge when that status is sent, and a 401-to-prompt-to-`X-API-Key` retry. Output:

```text
frontend_review_fix_round: passed
empty_state: honest no-queue copy
status_badge: absent without backend status; suggested shown when sent
api_key: 401 prompted then X-API-Key retry succeeded
```

### Fix-round concerns

- The production candidate producer remains intentionally deferred to Task 10 per the controller ruling.
- The frontend still has no key for other pre-existing authenticated endpoints; this fix is limited to the Review approve/reject mutations identified by the finding.
- The full suite continues to report three pre-existing Starlette/FastAPI deprecation warnings.

## Fix round 2

**Commit:** `c187e067cc4228401440134c0ac6ea43fab2882b` (`test(frontend): derive reason labels from certainty source`)

### Covering test and extraction rule

The covering file remains `tests/test_frontend_review.py`. The previous fixed-scenario `CertaintyGate` construction was removed. The test now parses `engine/certainty.py` as a Python AST and extracts literals only from reason-producing sinks:

- assignments to `HARD_REJECT_REASONS`;
- calls to `reasons.append(...)` / `reasons.extend(...)`;
- calls to `result.reasons.append(...)` / `result.reasons.extend(...)`;
- calls to `link_reasons.add(...)`, which is the collection later extended into `reasons`; and
- `GateResult(..., reasons=[...])` reason arguments.

This is intentionally narrower than grepping every quoted string in the file: unrelated evidence values such as `swapped` and `allowlisted_alias` do not become reason codes. The extractor asserts that its result is non-empty and contains the documented known reason set, so a broken extractor cannot silently pass. The actual `REASON_LABELS` object remains inline in `app.js`, as documented in the prior report; no JSON indirection was introduced.

The mapping test also uses a set difference to report missing/blank labels and includes a deliberate missing-label sentinel assertion, proving that the detector reports an absent label.

### Fix-round verification

The first red run after adding the source-extraction test failed because the extractor was not implemented:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v
```

```text
collected 6 items
tests\test_frontend_review.py .....F                                     [100%]
FAILED tests/test_frontend_review.py::test_source_reason_extraction_is_nonempty
1 failed, 5 passed
```

With a deliberately empty extractor, the focused test failed for the intended reason:

```text
E       AssertionError: assert set()
E        +  where set() = _source_reason_codes()
1 failed, 5 passed
```

After implementing the AST extraction, the focused test passed:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 6 items

tests\test_frontend_review.py ......                                     [100%]

============================== 6 passed in 0.10s ==============================
```

**Full suite:**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest
```

Full output:

```text
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
============================== warnings summary ===============================
..\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

server\app.py:35
  C:\Users\harun\OneDrive\Documenti\surebetmuse12\server\app.py:35: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
          @app.on_event("startup")

..\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675
  C:\Users\harun\OneDrive\Documenti\claudesurebet\venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
          
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
          return self.router.on_event(event_type)  # ty: ignore[deprecated]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
218 passed, 3 warnings in 4.97s
```

**Ruff:**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output:

```text
All checks passed!
```

**Mypy:**

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output:

```text
engine\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\base.py:111: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:204: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\test_candidates_api.py:249: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 48 source files
```

**JavaScript syntax and whitespace:**

```text
node --check frontend/js/app.js
```

Full output: empty; exit code `0`.

```text
git diff --check
```

Full output: empty; exit code `0`.

A source-extraction probe also passed by adding a temporary `reasons.append("new_reason_for_extractor_probe")` literal to a temporary copy of `certainty.py`; the extractor found the new code. Output:

```text
source_extractor_probe: passed
probe_code_found: new_reason_for_extractor_probe; extracted_codes: 9
```

### Fix-round concerns

- No production UI behavior changed in this round; the accepted status, auth, empty-state, escaping, tab, confirm, design-system, and polling work remains intact.
- The three Starlette/FastAPI deprecation warnings remain pre-existing.


