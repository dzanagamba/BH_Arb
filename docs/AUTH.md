# API keys and privileged actions (P3-5)

The env `API_KEY` remains the bootstrap/admin key. Named keys add rotation,
scopes and attribution without a user table or signup.

## Storage

`config/generated/api_keys.json` (gitignored, `API_KEYS_FILE` override) stores:

- `id`, `label`, `scopes`, `created_at`, `last_used_at`, `revoked_at`;
- a 16-byte salt and a PBKDF2-HMAC-SHA256 hash (200,000 iterations).

The plaintext token (`bh_…`) is returned once by `POST /api/keys` and never
persisted or logged. The store keeps the last 500 audit records.

## Scopes

| Scope | What it can do |
|---|---|
| `read` | Every `GET`/`HEAD`: results, status, config, groups, history, metrics, candidates, bets/paper reads and the CSV downloads. |
| `scan` | The write routes: `POST /api/scan`, `/api/verify`, `/api/recalculate`, `/api/verify-links`, `/api/surebets/{id}/check-links`, `/api/link-sweeps`, `/api/bets`, the bet/paper settle and closing writes. |
| `admin` | Toggle bookmakers/markets, shut down, create/list/revoke keys, read the audit log. |

The env key is admin. A key with only `read` cannot call `/api/scan` or
`/api/verify-links`; a key with only `scan` cannot read `/api/results`. The
rate-limit bucket is keyed by key id when a named key is used, by client IP
otherwise.

## Enforcement

One `api_key_guard` middleware (`server/app.py`) resolves the env `API_KEY` or a
named key for **every** `/api` route except `/api/health`, and sets the request's
key id and scopes. The route dependencies then check the scope (`read` for a
read, `scan`/`admin` for a write). The middleware and the dependencies share
`server.auth.resolve_api_key`, so they cannot disagree, and the env key is
compared with `hmac.compare_digest`.

Before M1-1 sixteen `/api` routes had no auth dependency (`/results`, `/status`,
`/config`, `/groups`, `/debug/*`, `/bets`, `/paper/*`, `/link-sweeps`), so with
`API_KEY` set they served data to anyone, and a valid named key was rejected
whenever a bootstrap key was also configured. Both are fixed by the middleware;
do not add an `/api` route that relies on a per-route dependency alone.

## Verification cache and failed-attempt throttle (M1-3)

A successful named-key verification costs one 200k-iteration PBKDF2 hash
(~85 ms measured on the operator host), and the dashboard polls. So
`ApiKeyStore.verify` caches a success in memory for `AUTH_CACHE_SECONDS`
(default 60, `0` disables) under `sha256(token)` — the token itself is never
held — together with the key's scope snapshot. A cache hit runs no PBKDF2 and
writes no file. `last_used_at` is persisted at most once per key per TTL instead
of on every request.

Invalidation is immediate, not TTL-based:

- `revoke()` clears every cached verification, so a revoked key answers 401 on
  its next request even inside the TTL; `create()` clears it too, so a new key
  works at once;
- a failed verification is never cached;
- every cache hit compares the store file's mtime+size, so a hand edit or a
  second process is noticed at once. The TTL therefore only bounds how long a
  record survives without any store change.

Wrong keys are throttled per client address: after `AUTH_FAILURE_RATE_LIMIT`
(default 10, `0` disables) failures inside `RATE_LIMIT_WINDOW_SECONDS`, further
`/api` requests from that address get `429` with `Retry-After` **before** any
PBKDF2 runs, so an exposed port cannot be made to burn CPU. A successful key
clears that address's counter. `/api/health` is never throttled. The budget and
the cache are per process, which matches this single-operator deployment.

## Revocation and no-reopen rule

A revoked key fails on its next request. If a store **has ever** had a key, the
API does not fall back to open mode when all keys are revoked; `has_any_keys()`
keeps authentication required. A fresh store with no keys and no env `API_KEY`
keeps the historical local-only open behavior, which is safe only because the
default bind is loopback.

## Endpoints

| Endpoint | Scope |
|---|---|
| `POST /api/keys` | admin; returns `{token, key}` once |
| `GET /api/keys` | admin; metadata only, no hashes |
| `DELETE /api/keys/{id}` | admin; immediate revocation |
| `GET /api/audit?limit=100` | admin; newest first |

Audit events currently include key creation/revocation, market/bookmaker toggles
and shutdown, with the acting key id (or `env`/empty for open local mode).

## Tests

`tests/test_auth_keys.py` covers one-time token return, hashed storage,
verification, revocation, scopes, env bootstrap, audit and the no-reopen rule.
`tests/test_api_key.py` pins the bootstrap key behavior,
`tests/test_api_auth.py` proves the middleware closes every `/api` route except
`/api/health` (enumerated from the OpenAPI schema), the read/scan matrix and the
local-only mode, and `tests/test_auth_limits.py` covers the verification cache
(hit spends no PBKDF2, TTL, disable, immediate revoke, out-of-band edit, no
negative cache, coalesced writes) and the failed-attempt throttle (N failures
then 429, success resets, disable, per-address isolation, no hashing while
blocked, public health). `tests/conftest.py` gives every test a private key
store and resets the process-wide failure budget, so the operator's file and a
previous test cannot decide the suite.
