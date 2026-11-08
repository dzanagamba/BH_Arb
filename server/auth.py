"""Named API keys with hashed storage, scopes, rotation and an audit log (P3-5).

The environment ``API_KEY`` remains the bootstrap/admin key. Named keys live in
a gitignored JSON store; only a PBKDF2 hash and salt are persisted. A key can be
revoked immediately, and privileged actions append an audit record.

This is a single-operator tool: there is no signup, no user table and no session
cookie. A named key is a bearer token with a scope, nothing more.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from config.settings import (
    AUTH_CACHE_SECONDS,
    AUTH_FAILURE_RATE_LIMIT,
    RATE_LIMIT_WINDOW_SECONDS,
)

SCOPES = {"read", "scan", "admin"}
AUDIT_MAX = 500
#: Cached verifications kept before the oldest is dropped; a single operator has
#: a handful of keys, so this only guards a pathological caller.
AUTH_CACHE_MAX = 256
#: Failed-attempt buckets kept before the oldest is pruned (one per address).
AUTH_FAILURE_MAX_CLIENTS = 4096


def default_key_path() -> str:
    return os.getenv(
        "API_KEYS_FILE",
        str(
            Path(__file__).resolve().parent.parent
            / "config"
            / "generated"
            / "api_keys.json"
        ),
    )


def _hash(token: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", token.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class ApiKeyStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        # Successful verifications keyed by sha256(token): the plaintext key is
        # never held here. digest -> (expires_at, public record, file stamp).
        self._verified: dict[
            str, tuple[float, dict[str, Any], tuple[int, int] | None]
        ] = {}
        self._last_used_write: dict[str, float] = {}

    def _stamp(self) -> tuple[int, int] | None:
        """The store file's (mtime_ns, size), to notice an out-of-band edit."""
        try:
            stat = Path(self.path).stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def invalidate(self) -> None:
        """Drop every cached verification; a create or a revoke changes the set."""
        with self._lock:
            self._verified.clear()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"keys": [], "audit": []}
        if not isinstance(data, dict):
            return {"keys": [], "audit": []}
        keys = data.get("keys")
        audit = data.get("audit")
        return {
            "keys": keys if isinstance(keys, list) else [],
            "audit": audit if isinstance(audit, list) else [],
        }

    def _save(self, data: dict[str, Any]) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)

    def has_any_keys(self) -> bool:
        """True even when every key is revoked, so revocation cannot reopen the API."""
        return any(isinstance(record, dict) for record in self._load()["keys"])

    def active_keys(self) -> list[dict[str, Any]]:
        return [
            record
            for record in self._load()["keys"]
            if isinstance(record, dict) and not record.get("revoked_at")
        ]

    def create(
        self,
        label: str,
        scopes: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        scopes = sorted(set(scopes or ["read"]))
        if not scopes or not set(scopes) <= SCOPES:
            raise ValueError(f"scopes must be a subset of {sorted(SCOPES)}")
        token = f"bh_{secrets.token_urlsafe(32)}"
        salt = secrets.token_hex(16)
        record = {
            "id": secrets.token_hex(6),
            "label": label.strip() or "unnamed",
            "salt": salt,
            "hash": _hash(token, salt),
            "scopes": scopes,
            "created_at": _now(),
            "last_used_at": "",
            "revoked_at": "",
        }
        with self._lock:
            data = self._load()
            data["keys"].append(record)
            self._save(data)
        self.audit("key_created", str(record["id"]), str(record["label"]))
        self.invalidate()
        return token, self._public(record)

    def verify(self, token: str) -> dict[str, Any] | None:
        """Return the public key record for ``token``, or ``None``.

        A successful verification is cached (``AUTH_CACHE_SECONDS``) under
        ``sha256(token)``: the 200k-iteration PBKDF2 costs ~85 ms, and the
        dashboard polls. A cache hit does no hashing and no store write. The
        store file's mtime+size is checked on every hit, so an out-of-band
        edit is seen at once rather than after the TTL.
        """
        if not token:
            return None
        ttl = AUTH_CACHE_SECONDS
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            if ttl > 0:
                cached = self._verified.get(digest)
                if cached is not None:
                    expires_at, record, stamp = cached
                    if expires_at > time.monotonic() and stamp == self._stamp():
                        return dict(record)
                    self._verified.pop(digest, None)
            data = self._load()
            for record in data["keys"]:
                if not isinstance(record, dict) or record.get("revoked_at"):
                    continue
                salt = str(record.get("salt") or "")
                expected = str(record.get("hash") or "")
                if salt and expected and hmac.compare_digest(
                    _hash(token, salt), expected
                ):
                    public = self._public(record)
                    self._touch_last_used(record, data, ttl)
                    if ttl > 0:
                        self._remember(digest, public, ttl)
                    return dict(public)
        return None

    def _touch_last_used(
        self, record: dict[str, Any], data: dict[str, Any], ttl: float
    ) -> None:
        """Persist ``last_used_at`` at most once per key per cache TTL.

        The value is informational, and rewriting the store on every poll (the
        old behaviour) cost a parse, a serialise and an atomic replace per
        request. With the cache disabled the old write-per-request remains.
        """
        key_id = str(record.get("id") or "")
        now = time.monotonic()
        last = self._last_used_write.get(key_id)
        if ttl > 0 and last is not None and now - last < ttl:
            return
        record["last_used_at"] = _now()
        self._save(data)
        self._last_used_write[key_id] = now

    def _remember(self, digest: str, record: dict[str, Any], ttl: float) -> None:
        if len(self._verified) >= AUTH_CACHE_MAX:
            now = time.monotonic()
            for key in [k for k, v in self._verified.items() if v[0] <= now]:
                self._verified.pop(key, None)
            while len(self._verified) >= AUTH_CACHE_MAX:
                self._verified.pop(next(iter(self._verified)))
        # Read the stamp after any write, so our own save does not look like an
        # out-of-band edit on the next hit.
        self._verified[digest] = (time.monotonic() + ttl, dict(record), self._stamp())

    def revoke(self, key_id: str) -> bool:
        with self._lock:
            data = self._load()
            for record in data["keys"]:
                if isinstance(record, dict) and record.get("id") == key_id:
                    if record.get("revoked_at"):
                        return True
                    record["revoked_at"] = _now()
                    self._save(data)
                    self.invalidate()
                    self.audit("key_revoked", key_id, str(record.get("label") or ""))
                    return True
        return False

    def _public(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key not in {"salt", "hash"}
        }

    def list_keys(self) -> list[dict[str, Any]]:
        return [self._public(record) for record in self._load()["keys"] if isinstance(record, dict)]

    def audit(self, event: str, key_id: str, detail: str = "") -> None:
        with self._lock:
            data = self._load()
            data["audit"].append(
                {
                    "at": _now(),
                    "event": event,
                    "key_id": key_id,
                    "detail": detail[:500],
                }
            )
            data["audit"] = data["audit"][-AUDIT_MAX:]
            self._save(data)

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._load()["audit"][-max(1, min(limit, AUDIT_MAX)):][::-1]


class ResolvedKey(NamedTuple):
    """What a request's key resolved to: the audit id and its scopes."""

    key_id: str
    scopes: frozenset[str]


def resolve_api_key(
    presented: str, *, env_key: str, store: ApiKeyStore
) -> ResolvedKey | None:
    """Resolve the bootstrap key or a named key; ``None`` means not authorized.

    One resolver for the middleware and the route dependencies, so a bootstrap
    key that is also configured cannot make a valid named key unusable: the env
    key is tried first (constant-time), then the hashed store (which refuses a
    revoked record on its next request).
    """
    if env_key and presented and hmac.compare_digest(presented, env_key):
        return ResolvedKey("env", frozenset(SCOPES))
    record = store.verify(presented)
    if record is None:
        return None
    return ResolvedKey(str(record["id"]), frozenset(record.get("scopes") or []))


class FailureLimiter:
    """Throttle failed key attempts per client address (M1-3).

    A wrong key costs one PBKDF2 run, so an unthrottled flood of them is a CPU
    denial of service against an exposed deployment. The check runs before the
    key is resolved: a blocked client spends no hashing at all. A success clears
    the counter, so a dashboard that once had a stale key is not locked out.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _window(self, client: str) -> list[float]:
        cutoff = time.monotonic() - RATE_LIMIT_WINDOW_SECONDS
        window = [at for at in self._failures.get(client, []) if at >= cutoff]
        if window:
            self._failures[client] = window
        else:
            self._failures.pop(client, None)
        return window

    def blocked(self, client: str) -> bool:
        if AUTH_FAILURE_RATE_LIMIT <= 0:
            return False
        with self._lock:
            return len(self._window(client)) >= AUTH_FAILURE_RATE_LIMIT

    def failed(self, client: str) -> None:
        if AUTH_FAILURE_RATE_LIMIT <= 0:
            return
        with self._lock:
            window = self._window(client)
            window.append(time.monotonic())
            self._failures[client] = window
            if len(self._failures) > AUTH_FAILURE_MAX_CLIENTS:
                for key in list(self._failures)[: len(self._failures) // 2]:
                    self._failures.pop(key, None)

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


#: Process-wide failure budget, shared by every route (the middleware consults it).
auth_failures = FailureLimiter()


api_key_store = ApiKeyStore(default_key_path())
