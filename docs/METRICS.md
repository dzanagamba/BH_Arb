# Metrics

`/api/metrics` renders the in-process registry in Prometheus text format. Every
series carries `book` (the adapter id) and/or `mode` (`prematch`/`live`) where
it is per-book. A series is absent until its first sample, except the baseline
series published at startup; an absent value is "not measured", never zero.

The registry is deliberately small (`server/observability.py`): counters,
gauges, one histogram type, and gauges computed at scrape time. No
multiprocess aggregation.

## Scan lifecycle

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_scans_started_total` | counter | `mode` | Scans entered. |
| `bh_scans_completed_total` | counter | `mode` | Scans that completed. |
| `bh_scans_failed_total` | counter | `mode` | Scans that raised. |
| `bh_scan_seconds_total` | counter | `mode` | Summed scan wall time. |
| `bh_scan_duration_seconds` | gauge | `mode` | Last scan duration. |
| `bh_last_scan_age_seconds` | gauge | — | Age of the last completed scan (computed at scrape). |
| `bh_rss_bytes` | gauge | — | Process RSS (computed at scrape). |
| `bh_cache_size_bytes` | gauge | — | Scan cache size (computed at scrape). |
| `bh_cache_budget_bytes` | gauge | — | Configured cache budget. |

## Per-book outcomes

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_book_results_total` | counter | `mode`, `book`, `outcome` | Historical outcome label (`success`, `empty`, `blocked`, `parse_error`, `skipped`). |
| `bh_book_kinds_total` | counter | `mode`, `book`, `kind` | The SR2-1 taxonomy (`ok`, `empty`, `blocked`, `rate_limited`, `timeout`, `transport`, `upstream_5xx`, `parse_error`, `schema_drift`, `skipped`). |
| `bh_book_failure_rate` | gauge | `mode`, `book` | Failure rate over the scan-cost history. |
| `bh_book_last_success_timestamp_seconds` | gauge | `mode`, `book` | Unix time of the last `ok` scrape; 0 at startup. |

## Transport and retries (SR5-1)

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_scraper_attempts_total` | counter | `book` | One per HTTP attempt, retries included. |
| `bh_scraper_retries_total` | counter | `book` | Attempts after the first. |
| `bh_scraper_attempt_seconds` | histogram | `book` | Per-attempt latency, cumulative buckets (`0.05 … 120 s`), `_sum`/`_count`. |
| `bh_http_status_total` | counter | `book`, `status` | Response status per attempt. |
| `bh_book_seconds` | gauge | `mode`, `book` | Last adapter wall time. |
| `bh_book_browser_seconds` | gauge | `mode`, `book` | Browser setup seconds, when measured. |
| `bh_book_requests` | gauge | `mode`, `book` | Requests in the last scan. |
| `bh_book_bytes` | gauge | `mode`, `book` | Response bytes in the last scan. |

## Circuit breaker

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_book_breaker_state` | gauge | `mode`, `book`, `state` | 1 for the current state, 0 otherwise (`closed`, `open`, `half_open`). |
| `bh_book_breaker_failures` | gauge | `mode`, `book` | Consecutive failures. |
| `bh_book_breaker_cooldown_seconds` | gauge | `mode`, `book` | Remaining cooldown. |

## Browser

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_browser_slots_in_use` | gauge | — | Browser books currently holding `BROWSER_CONCURRENCY` slots. |
| `bh_browser_recycles_total` | counter | `reason` | Pool recycles: `pages`, `age` or `crash` (SR3-3/SR5-1). |

## Wire shape and schema

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_wire_unknown_keys_total` | counter | `book`, `level`, `field` | Unknown keys kept by `extra="allow"`. |
| `bh_wire_structure_drift_total` | counter | `book`, `endpoint` | Structural fingerprint changed from its baseline. |
| `bh_schema_drift_total` | counter | `book` | A strict wire schema rejected a payload (the book drops). |

## Coverage and markets

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_coverage_flags` | gauge | `mode` | Coverage flags in the last scan. |
| `bh_coverage_flags_total` | counter | `mode` | Summed coverage flags. |
| `bh_cardinality_flags` | gauge | `mode` | Cardinality floors breached. |
| `bh_cardinality_flags_total` | counter | `mode` | Summed cardinality flags. |
| `bh_mapping_coverage_ratio` | gauge | `mode` | Mapping coverage ratio. |
| `bh_unmapped_market_rows_total` | counter | `mode` | Unmapped market rows seen. |

## Products, alerts and links

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `bh_surebets_found` | gauge | `mode` | Surebets in the last scan. |
| `bh_surebets_found_total` | counter | `mode` | Summed surebets. |
| `bh_surebets_dropped_total` | counter | `mode`, `reason` | Dropped by the price guard. |
| `bh_recorded_opportunities` | gauge | `mode` | Opportunity rows recorded. |
| `bh_candidate_queue_size` | gauge | `mode` | Candidate review queue. |
| `bh_alerts_sent_total` / `bh_alerts_failed_total` / `bh_alerts_suppressed_total` | counter | `kind` | Alert transport results. |
| `bh_link_checks_total` | counter | `outcome` | Deep-link checks by result. |

## Reading the histogram

`bh_scraper_attempt_seconds` renders cumulative buckets:

```text
bh_scraper_attempt_seconds_bucket{book="mbet",le="0.05"} 3
bh_scraper_attempt_seconds_bucket{book="mbet",le="0.1"} 5
bh_scraper_attempt_seconds_bucket{book="mbet",le="+Inf"} 5
bh_scraper_attempt_seconds_sum{book="mbet"} 0.31
bh_scraper_attempt_seconds_count{book="mbet"} 5
```

`histogram()` in PromQL (or the equivalent in the dashboard) turns those into
p50/p95. A bucket count is cumulative: it includes every observation at or below
that bound.
