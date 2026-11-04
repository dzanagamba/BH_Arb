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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCOPES = {"read", "scan", "admin"}
AUDIT_MAX = 500


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

    def has_keys(self) -> bool:
        return bool(self.active_keys())

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
        return token, self._public(record)

    def verify(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self._lock:
            data = self._load()
            for record in data["keys"]:
                if not isinstance(record, dict) or record.get("revoked_at"):
                    continue
                salt = str(record.get("salt") or "")
                expected = str(record.get("hash") or "")
                if salt and expected and hmac.compare_digest(
                    _hash(token, salt), expected
                ):
                    record["last_used_at"] = _now()
                    self._save(data)
                    return self._public(record)
        return None

    def revoke(self, key_id: str) -> bool:
        with self._lock:
            data = self._load()
            for record in data["keys"]:
                if isinstance(record, dict) and record.get("id") == key_id:
                    if record.get("revoked_at"):
                        return True
                    record["revoked_at"] = _now()
                    self._save(data)
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


api_key_store = ApiKeyStore(default_key_path())
