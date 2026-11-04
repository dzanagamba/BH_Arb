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
| `read` | Read diagnostics and the review/evidence endpoints. |
| `scan` | Trigger a scan or a link sweep. |
| `admin` | Toggle bookmakers/markets, shut down, create/list/revoke keys, read the audit log. |

The env key is admin. A key with only `read` cannot call `/api/keys`, `/api/scan`
or `/api/verify-links`. The rate-limit bucket is keyed by key id when a named key
is used, by client IP otherwise.

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
`tests/test_api_key.py` keeps the old single-key behavior pinned.
