"""M1-3: the failed-key throttle and the verification cache.

WHAT THESE TESTS PROVE
----------------------
One wrong key costs a 200k-iteration PBKDF2 hash (~85 ms measured on this host),
so: a successful verification is cached under `sha256(token)` and a hit spends no
hashing and no store write, the cache dies immediately on a revocation through
the store and inside the TTL on an out-of-band edit, and a client that burned its
failed-attempt budget gets 429 before any hashing happens. `/api/health` is never
throttled.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not measure the real HTTP latency saving (the roadmap log records that
measurement separately), and they do not prove a distributed deployment: the
cache and the failure budget are per process, which is what this single-operator
tool runs.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import api, auth
from server import app as app_module
from server.auth import ApiKeyStore, FailureLimiter


def _store(tmp_path: Path) -> ApiKeyStore:
    return ApiKeyStore(str(tmp_path / "api_keys.json"))


@pytest.fixture
def hashes(monkeypatch):
    """Count the real PBKDF2 runs a test path performs."""
    calls: list[str] = []
    real = auth._hash

    def counting(token: str, salt: str) -> str:
        calls.append(token)
        return real(token, salt)

    monkeypatch.setattr(auth, "_hash", counting)
    return calls


@pytest.fixture
def keyed_api(tmp_path, monkeypatch):
    """An API whose store holds one key, so authentication is switched on."""
    store = _store(tmp_path)
    store.create("laptop", ["read", "scan"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    return store


# ─── The verification cache ─────────────────────────────────────────────────


def test_a_repeated_verification_spends_no_pbkdf2(tmp_path, hashes):
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read"])
    hashes.clear()

    assert store.verify(token)["id"] == record["id"]
    assert len(hashes) == 1
    assert store.verify(token)["id"] == record["id"]
    assert len(hashes) == 1, "the second verify must come from the cache"


def test_the_cache_expires_after_its_ttl(tmp_path, hashes, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_CACHE_SECONDS", 0.05)
    store = _store(tmp_path)
    token, _ = store.create("laptop", ["read"])
    hashes.clear()

    assert store.verify(token) is not None
    assert store.verify(token) is not None
    assert len(hashes) == 1

    time.sleep(0.07)
    assert store.verify(token) is not None
    assert len(hashes) == 2, "an expired entry must be re-verified"


def test_zero_disables_the_cache(tmp_path, hashes, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_CACHE_SECONDS", 0)
    store = _store(tmp_path)
    token, _ = store.create("laptop", ["read"])
    hashes.clear()

    assert store.verify(token) is not None
    assert store.verify(token) is not None
    assert len(hashes) == 2


def test_revocation_drops_the_cache_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_CACHE_SECONDS", 3600)
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read"])

    assert store.verify(token) is not None
    assert store.revoke(record["id"])
    assert store.verify(token) is None, "a revoked key must fail at once"


def test_a_new_key_is_usable_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_CACHE_SECONDS", 3600)
    store = _store(tmp_path)
    first, _ = store.create("laptop", ["read"])
    assert store.verify(first) is not None

    second, record = store.create("phone", ["read"])
    assert store.verify(first) is not None
    assert store.verify(second)["id"] == record["id"]


def test_an_out_of_band_revoke_is_seen_inside_the_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_CACHE_SECONDS", 3600)
    path = str(tmp_path / "api_keys.json")
    reader = ApiKeyStore(path)
    writer = ApiKeyStore(path)
    token, record = writer.create("laptop", ["read"])

    assert reader.verify(token) is not None
    assert writer.revoke(record["id"])
    assert reader.verify(token) is None


def test_a_wrong_token_is_never_cached(tmp_path, hashes):
    store = _store(tmp_path)
    store.create("laptop", ["read"])
    hashes.clear()

    assert store.verify("bh_not-a-real-token") is None
    assert len(hashes) == 1
    assert store.verify("bh_not-a-real-token") is None
    assert len(hashes) == 2, "a failure must not short-circuit the next attempt"


def test_last_used_at_is_not_rewritten_on_every_request(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_CACHE_SECONDS", 3600)
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read"])

    assert store.verify(token) is not None
    stamp = Path(store.path).stat().st_mtime_ns
    assert store.list_keys()[0]["last_used_at"]

    time.sleep(0.01)
    assert store.verify(token) is not None
    assert Path(store.path).stat().st_mtime_ns == stamp, (
        "a cache hit must not rewrite the store for last_used_at"
    )


# ─── The failed-attempt throttle ────────────────────────────────────────────


def test_failed_attempts_are_throttled(keyed_api, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FAILURE_RATE_LIMIT", 3)
    client = TestClient(app_module.app)

    for _ in range(3):
        assert client.get("/api/results", headers={"X-API-Key": "wrong"}).status_code == 401

    blocked = client.get("/api/results", headers={"X-API-Key": "wrong"})
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == str(auth.RATE_LIMIT_WINDOW_SECONDS)
    assert "Too many failed API-key attempts" in blocked.json()["detail"]

    # The budget is per address, so a valid key from the same address waits too;
    # health is never throttled, which keeps a load balancer happy.
    assert client.get("/api/health").status_code == 200


def test_a_valid_key_clears_the_failure_budget(keyed_api, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FAILURE_RATE_LIMIT", 3)
    token, _ = keyed_api.create("second", ["read"])
    client = TestClient(app_module.app)
    wrong = {"X-API-Key": "wrong"}

    assert client.get("/api/results", headers=wrong).status_code == 401
    assert client.get("/api/results", headers=wrong).status_code == 401
    assert client.get("/api/results", headers={"X-API-Key": token}).status_code == 200

    # Counter cleared: two more failures are still answered, not blocked.
    assert client.get("/api/results", headers=wrong).status_code == 401
    assert client.get("/api/results", headers=wrong).status_code == 401


def test_zero_disables_the_failure_limit(keyed_api, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FAILURE_RATE_LIMIT", 0)
    client = TestClient(app_module.app)

    for _ in range(30):
        assert client.get("/api/results", headers={"X-API-Key": "wrong"}).status_code == 401


def test_a_blocked_client_spends_no_pbkdf2(keyed_api, monkeypatch, hashes):
    monkeypatch.setattr(auth, "AUTH_FAILURE_RATE_LIMIT", 1)
    client = TestClient(app_module.app)

    assert client.get("/api/results", headers={"X-API-Key": "wrong"}).status_code == 401
    hashes.clear()

    assert client.get("/api/results", headers={"X-API-Key": "wrong"}).status_code == 429
    assert hashes == [], "a blocked attempt must not run PBKDF2"


def test_the_budget_is_per_client_address(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FAILURE_RATE_LIMIT", 2)
    limiter = FailureLimiter()

    limiter.failed("10.0.0.1")
    limiter.failed("10.0.0.1")
    assert limiter.blocked("10.0.0.1")
    assert not limiter.blocked("10.0.0.2")

    limiter.succeeded("10.0.0.1")
    assert not limiter.blocked("10.0.0.1")


def test_the_window_slides(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FAILURE_RATE_LIMIT", 1)
    monkeypatch.setattr(auth, "RATE_LIMIT_WINDOW_SECONDS", 0.05)
    limiter = FailureLimiter()

    limiter.failed("10.0.0.1")
    assert limiter.blocked("10.0.0.1")
    time.sleep(0.07)
    assert not limiter.blocked("10.0.0.1"), "an old failure must leave the window"
