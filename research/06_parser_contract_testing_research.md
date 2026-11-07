# Parser contract testing & drift detection — research brief

**Question:** which libraries and patterns should a Python sports-odds scanner use to detect
upstream parser drift early, in CI and at runtime, and to keep fixture-based tests trustworthy?

**Short answer:** validate the *wire shape* strictly (msgspec, or pydantic v2 with
`strict=True` + `extra="forbid"` on the fields we price from), snapshot the *normalised parser
output* (syrupy), keep capture fixtures with explicit metadata and an age check, and run a
scheduled live canary that compares a structural fingerprint against a stored baseline. Pact and
Schemathesis do not fit a provider you do not control; pandera/Great Expectations are the wrong
shape of tool.

Date of all version data: **2026-11-07**.

---

## 1. Scope and method

Read PyPI JSON metadata (version, upload date, licence, `requires_python`) and GitHub repo
metadata (last push, archived flag, licence) for every candidate, then read the primary docs or
CHANGELOG for the semantics that matter. Repo integration facts come from this checkout:
`requirements.txt` pins `pydantic==2.13.4`, `httpx==0.28.1`, `playwright==1.61.0`;
`requirements-dev.txt` pins `pytest==9.0.3`, `hypothesis==6.150.0`. Target Python is 3.11
(`pyproject.toml`). Fixtures already live in date-stamped directories
(`tests/fixtures/replay/2026-09-25/`, `2026-11-03/`, `2026-11-04/`).

## 2. Landscape at a glance

| Library | Latest | Released | Licence | Activity (12 mo) | Verdict |
|---|---|---|---|---|---|
| pydantic | 2.14.3 | 2026-11-05 | MIT | very high, weekly releases | **adopt** (already present) |
| msgspec | 0.22.0 | 2026-09-29 | BSD-3-Clause | high, active | **adopt** for hot-path wire decoding |
| cattrs | 26.2.1 | 2026-09-26 | MIT | active | avoid (adds a layer, no gain here) |
| attrs | 26.1.0 | 2026-03-19 | MIT | active | avoid (not the parser layer) |
| jsonschema | 4.26.0 | 2026-01-07 | MIT | maintained (last release 10 mo ago, commits current) | borrow (schema diffing only) |
| fastjsonschema | 2.22.3 | 2026-11-01 | BSD-3-Clause | active | avoid (draft-07 ceiling) |
| datamodel-code-generator | 0.90.0 | 2026-11-06 | MIT | very high | **adopt** as a bootstrap tool, generated code hand-edited |
| genson | 1.4.0 | 2026-07-06 | MIT | revived in 2026 | borrow (baseline schema generation) |
| syrupy | 6.1.1 | 2026-09-13 | MIT | active | **adopt** |
| inline-snapshot | 0.36.1 | 2026-10-12 | MIT | active | borrow (small assertions only) |
| pytest-snapshot | 0.9.0 | 2022-04-23 | MIT | stale (last push 2024-07) | avoid |
| approvaltests | 20.0.1 | 2026-10-25 | Apache-2.0 | active | avoid (py3.11+, external diff tool) |
| vcrpy | 9.4.2 | 2026-11-02 | MIT | very high | borrow (cassette metadata + scrubbing) |
| pytest-recording | 0.14.1 | 2026-11-02 | MIT | active | **adopt** (`--block-network`, record modes) |
| respx | 0.23.1 | 2026-04-08 | BSD-3-Clause | maintained | **adopt** (httpx is the client) |
| pytest-httpx | 0.36.2 | 2026-04-09 | MIT | active | alternative to respx |
| hypothesis | 6.170.15 | 2026-11-06 | MPL-2.0 | very high | **adopt** (already dev dep) |
| hypothesis-jsonschema | 0.23.2 | 2026-10-27 | MPL-2.0 | active | borrow (fuzz from schema) |
| pact-python | 4.2.0 | 2026-10-23 | MIT | active | avoid (provider must verify) |
| schemathesis | 4.33.1 | 2026-11-04 | MIT | very high | avoid (needs a published spec) |
| pandera | 0.35.0 | 2026-10-25 | MIT | active | avoid (dataframe-shaped) |
| great_expectations | 1.24.1 | 2026-10-22 | Apache-2.0 | active (Fivetran) | avoid (platform) |
| playwright | 1.64.1 | 2026-10-22 | Apache-2.0 | very high | borrow (HAR only for DOM pages) |

## 3. Runtime schema validation

### 3.1 pydantic v2 — https://github.com/pydantic/pydantic

- **Strict vs lax.** Lax mode coerces: `MyModel.model_validate({'x': '123'})` yields `x=123`,
  and `strict=True` rejects it (`docs/concepts/strict_mode.md`). This is the single most
  important fact for us: **lax mode silently hides a type change**, which is exactly a drift
  signal for odds fields. Strict-from-JSON is slightly looser than strict-from-Python: date/time
  types still accept ISO strings under `validate_json(..., strict=True)`.
- **Unknown fields.** Default is `extra='ignore'`; `'forbid'` errors; `'allow'` stores them in
  `__pydantic_extra__` / `model_extra` (`docs/concepts/models.md`). So the default configuration
  discards the evidence of a renamed field. For drift detection the useful setting is
  `extra='allow'` **plus** an explicit check of `model_extra` against an allow-list, or
  `extra='forbid'` on a "semantic" model. `forbid` on the raw upstream model will fire on every
  additive upstream change and train the operator to ignore alarms.
- **Performance.** Use `model_validate_json()` rather than `model_validate(json.loads(...))`,
  instantiate `TypeAdapter` / models once at import (per-call construction rebuilds the core
  schema), prefer `dict`/`list` over `Mapping`/`Sequence`, and use discriminated unions
  (`docs/concepts/performance.md`). For dozens of payloads per scan cycle pydantic is not the
  bottleneck; for per-runner-row validation of thousands of rows, msgspec is measurably faster.
- Maintenance: MIT, 2.14.3 on 2026-11-05, releases weekly, repo pushed today. **Adopt**, it is
  already pinned at 2.13.4.

### 3.2 msgspec — https://msgspec.dev / https://github.com/msgspec/msgspec

- Strict **by default**: no implicit `str`→`int`; `strict=False` opts into lax
  (`docs/usage.rst`, "Strict vs Lax Mode"). This matches the trust posture better than pydantic's
  default.
- `forbid_unknown_fields=True` on a `Struct` raises
  `ValidationError: Object contains unknown field ...` (`docs/structs.rst`); without it unknown
  keys are skipped efficiently — the schema-evolution page explicitly documents decoding newer
  messages with older structs.
- Decoding + validation is "zero added cost" over JSON parsing, and `msgspec.json.Decoder(T)`
  built once is the intended pattern.
- Maintenance: BSD-3-Clause, 0.22.0 on 2026-09-29, repo pushed 2026-11-06 (pre-1.0 API, so pin
  exactly). **Adopt** for the wire layer if we want one decoder object and no per-call cost;
  keep pydantic for config/API models that already exist.

### 3.3 attrs + cattrs — https://catt.rs

- `cattrs` structures dicts into attrs/dataclasses; it validates structure and types at
  conversion time but has no `extra="forbid"` equivalent by default (unknown keys are dropped
  unless a `forbid_extra_keys` strategy is configured) and no Rust core.
- Maintenance: MIT, 26.2.1 on 2026-09-26, active.
- **Avoid.** We would be adding a third modelling style with no validation advantage over
  pydantic/msgspec. Borrow nothing.

### 3.4 JSON Schema validators

- **jsonschema 4.26.0** (MIT, 2026-01-07): full Draft 2020-12 / 2019-09 / 7 / 6 / 4 / 3,
  lazy `iter_errors()`, programmatic error paths (`absolute_path`, `json_path`) — the last is
  what you want in an alert message ("missing `/events/0/markets/3/price`").
- **fastjsonschema 2.22.3** (BSD-3-Clause, 2026-11-01): compiles a schema to Python code, much
  faster than interpreter-mode jsonschema, **but supports only draft-04/06/07** (official docs).
  2019-09/2020-12 keywords (`unevaluatedProperties`, `dependentRequired`) are unavailable.
- **Fit:** borrow. Useful for a *language-neutral* fingerprint file checked into the repo and
  diffed in CI, not for the hot path. If we go pydantic/msgspec we already get the checks.

### 3.5 Generating models from samples

- **datamodel-code-generator 0.90.0** (MIT, 2026-11-06, releases every few days): converts
  OpenAPI/JSON Schema/raw JSON/CSV into pydantic v2, dataclasses, TypedDict, msgspec
  (`--input-file-type`, `--output-model-type pydantic_v2.BaseModel`). Use it once per book to get
  a first draft, then hand-edit: generated models encode a *snapshot* of one sample, including
  optionality that is accidental.
- **genson 1.4.0** (MIT, 2026-07-06 after a two-year gap): merges schemas across many JSON
  objects — "every object given must validate under the generated schema". Good for building the
  baseline fingerprint from a corpus of captures; it cannot know which fields are semantically
  required.
- **Fit:** adopt datamodel-code-generator as a dev-only bootstrap; borrow genson for baseline
  generation. Do not regenerate models in CI (the diff would be the alarm, not the test).

## 4. Snapshot / golden testing of parser output

- **syrupy 6.1.1** (MIT, 2026-09-13, active): pytest fixture `snapshot`, `.ambr` files under
  `__snapshots__/`, `pytest --snapshot-update`, `-m syrupy_snapshot` to update only snapshot
  tests, and a `matcher=` callback keyed by path
  (`(("events", list), ("0", dict), ("start", str))`) to normalise volatile fields before
  comparison. Serializable output only.
- **inline-snapshot 0.36.1** (MIT, 2026-10-12, active): stores expected values in the source,
  flags `--inline-snapshot=create,fix,trim,update,review`; `external("uuid:....json")` for big
  values. Great for small invariants (`assert parse(x) == snapshot({...})`), painful for a
  300-row normalised output; plugin depends on pytest assertion rewriting (disabled on old
  CPython for some flags).
- **pytest-snapshot 0.9.0** (MIT, last release 2022-04-23, last push 2024-07): functionally
  stale. Avoid.
- **approvaltests 20.0.1** (Apache-2.0, 2026-10-25, active): `.approved`/`.received` files, needs
  an external diff reporter for a good workflow, requires Python ≥3.11. Avoid; extra moving
  parts for the same result.
- **Fit:** adopt syrupy, snapshot the **normalised** parse result (book, sport, event key,
  market key, line, price, settlement) with a matcher that blanks timestamps and upstream IDs.
  Snapshotting raw payloads produces a diff on every unrelated upstream change and gets muted.

## 5. Record/replay HTTP fixtures

- **vcrpy 9.4.2** (MIT, 2026-11-02): cassettes, `record_mode` (`once`, `new_episodes`,
  `none`, `all`), `match_on` (`method`, `scheme`, `host`, `port`, `path`, `query`, `body`, ...),
  scrubbing via `filter_headers`, `filter_query_parameters`,
  `filter_post_data_parameters` (multipart since 9.4.0), `before_record_request`,
  `before_record_response`. 9.3.0 added **`Cassette.get_metadata(key, default)`** — the hook for a
  `recorded_at` stamp. 9.x is a very active line with real bug fixes (pool handling, urllib3 1.x,
  SOCKS, force_reset).
- **pytest-recording 0.14.1** (MIT, 2026-11-02): pytest wrapper; `--record-mode`, `rewrite`
  mode, `--block-network` with `allowed_hosts`, `vcr_config` fixture, `--disable-recording`.
  This is the CI guard that stops a test silently going to the network.
- **respx 0.23.1** (BSD-3-Clause, 2026-04-08) and **pytest-httpx 0.36.2** (MIT, 2026-04-09):
  httpx-native mocking, per-route responses, `assert_all_called`. Since scrapers use `httpx`,
  respx is the smallest tool that fits.
- **Playwright HAR** (`page.route_from_har`, `update=True` to re-record): replays the whole
  network log of a browser session; matching is strict on URL + method and, for POST, on the
  payload; nearest match wins on headers. Only relevant for the DOM-driven scrapers where
  Playwright is already installed. HARs contain cookies and auth headers — scrub before commit;
  dynamic query params (dates, event IDs) make replay brittle.
- **Freshness/expiry.** None of these tools has a TTL: a cassette is valid forever. The
  workable pattern is metadata (`recorded_at`, source URL, HTTP status, content-type) plus a
  pytest check that warns/fails past N days, plus a scheduled re-record. `tests/fixtures/replay/`
  is already date-partitioned, so the age check can read the directory name.
- **Fit:** adopt respx for httpx unit tests; adopt pytest-recording's `--block-network` as the CI
  default; borrow vcrpy's metadata + scrubbing ideas rather than adding a second recording format
  next to the existing JSON fixtures. Avoid HAR except for Playwright-only books.

## 6. Property-based / fuzz testing

- **hypothesis 6.170.15** (MPL-2.0, 2026-11-06): already a dev dependency at 6.150.0.
- **hypothesis-jsonschema 0.23.2** (MPL-2.0, 2026-10-27): `from_schema(schema)` gives a strategy
  for documents matching a JSON Schema, including `canonicalise` for round-trip tests.
- **What to assert (the valuable part):** the parser must never raise `KeyError`/`TypeError` on
  hostile input, must return an explicit "unparsed"/"suspended" outcome, must never emit a price
  lacking a required field, and must never produce a cross-sport or cross-settlement pair. Those
  are failure-mode assertions, independent of upstream shape.
- **Caveat:** generating from a schema inferred from our own fixtures is circular — it explores
  the shape we already accept. Use it for *mutation* (wrong types, nulls, empty arrays, huge
  arrays, Unicode, duplicate keys), not as evidence of upstream conformance.
- **Fit:** adopt. Highest value per line of test code of anything in this brief.

## 7. Consumer-driven contract testing

- **pact-python 4.2.0** (MIT, 2026-10-23): v4 uses the Rust `pact-reference` FFI core, requires
  Python ≥3.11; consumer tests run an in-process mock (`with pact.serve() as srv`), write a pact
  file, and the *provider* runs `Verifier(...).add_transport(url=...).add_source(...)` to prove
  conformance. Matchers (`match.like`, `each_like`, `regex`) are the good idea.
- The model assumes a provider team that runs the verifier in their pipeline. A bookmaker will
  never do that, so the contract has no counterparty: the consumer test degenerates into "our
  mock agrees with our client", which is what respx already gives us. Technically one could point
  `Verifier` at the live bookmaker URL as a canary, but provider states, broker semantics and the
  FFI binary buy nothing there.
- **schemathesis 4.33.1** (MIT, 2026-11-04): property-based testing *of a server* from an
  OpenAPI/GraphQL/gRPC schema ("point it at your schema"). Bookmaker endpoints are undocumented,
  and fuzzing a third party's API is active probing — against the project's "never evade account
  limits / no hostile traffic" posture and a ToS risk.
- **Fit:** avoid both. Borrow exactly one idea: the *canary contract* — a small recorded
  expectation set replayed against live endpoints on a schedule, with a field-level diff.

## 8. Runtime drift detection patterns

Not libraries; these are the patterns that actually catch silent breakage.

1. **Schema fingerprint.** Canonicalise a payload to sorted key paths + JSON types + array
   length buckets, hash it (SHA-256), store one baseline per `(book, endpoint)`. On change, emit
   a diff of added/removed/type-changed paths. Store the baseline in `config/`, not in `cache/`.
   Generate the first baseline with genson or a 20-line walker; `jsonschema`'s
   `iter_errors` is only needed if you want validation, not a hash.
2. **Unknown-field alerting with an allow-list.** Unknown key on an object we price from is a
   *rename* until proven otherwise (upstream often keeps the old key as `null`). Log the key set
   hash; alert on a *new* unknown key, not on a count.
3. **Sentinel detection.** Drift frequently arrives as valid JSON: `0`, `-1`, `"N/A"`, `null`,
   empty `markets: []`. Validate domain ranges (`1.0 < decimal_odds < 1000`) and treat the rest
   as suspended, never as a price. A price of `0` is the classic "parser didn't break, it lied".
4. **Row/market-count anomaly vs rolling baseline.** Per `(book, sport, hour-of-day)` trailing
   median and MAD over ~14 days; alert when today is below, say, median − 3·MAD. Two guards are
   essential: seasonality (no games at 04:00, off-season sports) and cross-book correlation — if
   two books show normal volume and one is empty, suspect the parser; if all are empty, it is
   the calendar.
5. **Fail-closed runtime switch.** A payload that fails wire validation marks that book's groups
   `unverified` and, past a threshold (e.g. >30% failures over 5 minutes), stops pricing that
   book. This is the only pattern that protects money in the window before a human reads an alert.
6. **Raw-bytes ring buffer.** Keep the last N failing payloads (scrubbed) on disk so the alert
   can be reproduced as a new fixture without a re-scrape.
7. **Data-quality platforms.** pandera 0.35.0 (MIT, active) validates dataframes (pandas, Polars,
   PyArrow, Ibis, DataFusion) with `DataFrameSchema`/checks; Great Expectations 1.24.1
   (Apache-2.0) is a validation platform with Expectations, Checkpoints and Data Docs. Both are
   built for batch tabular data and bring configuration and dependency weight that a scanner with
   a handful of JSON endpoints does not need. **Avoid**; borrow the vocabulary (an "expectation
   suite" with severity levels) if the alert list grows.

## 9. Recommended layered strategy

### CI, every PR, no network

1. **Wire-shape gate.** Decode each capture with a per-book `msgspec.Struct` (strict default,
   `forbid_unknown_fields=True` only on the fields we price from; permissive capture struct for
   the rest). Fail on missing required field, type change, or unknown key on a priced object.
   pydantic equivalent if we prefer one library: `ConfigDict(strict=True, extra="allow")` plus an
   explicit `model_extra` allow-list check.
2. **Snapshot gate.** Run the real parser over the capture, snapshot the *normalised* output with
   syrupy; `matcher` blanks IDs and timestamps. Any diff is a reviewed change, not an
   auto-update: `--snapshot-update` is a human action, never a CI step.
3. **Cardinality floor.** `len(events) >= k`, canonical market keys present, at least one price
   per market. Cheap tripwire that catches "everything parsed, nothing found".
4. **Property gate.** Hypothesis mutations: never raise, never emit an incomplete price, never
   cross sport or settlement.
5. **Fixture metadata gate.** Every capture carries `recorded_at`, `source_url`, `status`,
   `content_type`; fail if a replay fixture is older than the agreed window (the date-stamped
   `tests/fixtures/replay/<date>/` layout already provides the date).
6. **`--block-network`** via pytest-recording so a broken mock cannot silently pass by hitting
   the live site.

### Scheduled (nightly / hourly), network allowed

7. **Canary scrape.** One event per book, rate-limited, same wire gate as CI, plus fingerprint
   comparison against the stored baseline; on mismatch, open an issue with the field-level diff
   and save the scrubbed payload as a candidate fixture. Treat 403/451/timeout as "unknown", not
   as "empty".
8. **Baseline refresh.** Re-record fixtures for one rotating book per night; update
   `recorded_at`; never auto-commit a changed baseline — the diff is the review.

### Runtime, every payload

9. Validate with a decoder built once at import (`msgspec.json.Decoder(BookPayload)`), fail
   closed, count by `(book, endpoint, error_kind)`, keep the raw bytes ring buffer, and trip the
   per-book circuit breaker on sustained failure.
10. Fingerprint and sentinel checks run on the same decoded object; alerts are telemetry, never
    a reason to price.

## 10. Risks and uncertainties

- **`extra="forbid"` too strict.** Bookmakers add fields routinely; a forbidding model turns
  every additive change into a red build and the alarm gets muted. Use two tiers (permissive
  capture, strict semantic) and alert on new unknown keys instead.
- **pydantic lax coercion masks drift.** `'1.95'` accepted as `1.95` is indistinguishable from a
  genuine string field at the call site. Prices must be strict or explicitly validated.
- **Fixture rot is the dominant failure mode.** Green CI proves the parser matches *old* bytes.
  Only the scheduled canary says anything about today. The date-stamped fixture dirs must be
  paired with an age assertion or they become archaeology.
- **Snapshot churn.** Raw-payload snapshots diff on every irrelevant upstream change; normalise
  first, and keep snapshots small.
- **Empty vs broken is ambiguous.** `[]` means both "no games" and "API changed". Only cross-book
  comparison and the rolling baseline can separate them; no single-endpoint assertion can.
- **Canary scraping** must respect rate limits and the project's no-evasion invariant; a canary
  that logs in or rotates proxies breaks the trust rules.
- **Not verified in this brief:** actual throughput of pydantic vs msgspec on our payloads (no
  benchmark run); respx/vcrpy behaviour against the exact httpx transport setup in
  `scrapers/base.py`; wheel availability of the pact FFI on target platforms; GX dependency
  footprint. I read repository structure and pinned versions, not the parser internals.
- **Version drift note:** `requirements.txt` pins pydantic 2.13.4 while 2.14.3 is current; the
  brief's semantics are stable across 2.13/2.14, but a bump should be its own change.

## 11. Conclusions

1. The highest-value, lowest-cost layer is strict wire validation plus property tests: it catches
   renames, type changes and crashes without any new infrastructure.
2. pydantic is already installed and adequate; msgspec is the better wire decoder because it is
   strict by default and free at the call site — choose one per layer, not both everywhere.
3. Snapshot only normalised parser output (syrupy); snapshotting raw JSON creates churn that
   destroys the signal.
4. Record/replay tooling (respx, pytest-recording) protects test hermeticity but never freshness:
   no cassette has a TTL, so metadata plus a scheduled canary is mandatory.
5. Pact and Schemathesis assume a cooperative provider or a published spec; for a third-party
   bookmaker they add ceremony and false confidence. Borrow the canary-contract idea only.
6. pandera and Great Expectations are dataframe/batch tools; the drift signals that matter here
   are field paths, sentinels and row counts, not statistical expectations over tables.
7. Fail closed at runtime: a failed wire check must mark the book unverified and trip a circuit
   breaker, because an alert read tomorrow does not protect today's prices.
