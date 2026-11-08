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
| `scan` | The write routes: `POST /api/scan`, `/api/verify`, `/api/recalculate`, `/api/verify-links`, `/api/link-sweeps`, `/api/bets`, the bet/paper settle and closing writes. |
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
`tests/test_api_key.py` pins the bootstrap key behavior, and
`tests/test_api_auth.py` proves the middleware closes every `/api` route except
`/api/health` (enumerated from the OpenAPI schema), the read/scan matrix and the
local-only mode. `tests/conftest.py` gives every test a private key store, so
the operator's file cannot decide the suite.
