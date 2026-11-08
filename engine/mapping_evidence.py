"""Machine evidence ledger for mapping claims.

The ledger is the durable trust record for the autonomy plan. It replaces
``config/team_alias_reviewed.json`` and the human write path into
``config/team_alias_allowlist.json``: a claim authorizes a pairing only because
it carries evidence that proves it, not because a person or a hand edit said so.

A claim has a kind, a canonical key, a status, the evidence that produced it and
the contradictions that would revoke it. Only ``accepted`` and non-stale claims
authorize anything. ``quarantined`` means the evidence is insufficient or
contradictory; it is recorded and rechecked, never silently dropped.

Evidence weights are deliberately conservative:

======================  =====  =============================================
type                    weight what it proves
======================  =====  =============================================
betradar_shared_id      1.00   both books carry the same provider match id
exact_shared_fixture    0.95   same two raw teams, kickoff and category
repeated_shared_fixture 0.90   the exact-fixture observation repeated
cross_book_price        0.90   the mapped market agrees with other books
league_fingerprint      0.85   the same team set appears under both names
legacy_review           0.50   a person approved it; corroboration still needed
similarity              0.30   names look alike; never enough alone
======================  =====  =============================================

A claim needs at least ``MIN_ACCEPT_CONFIDENCE`` (0.80) to be accepted. That
means ``legacy_review`` and ``similarity`` can never accept on their own, which
is the point of the rewrite.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from engine.name_keys import raw_team_key

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_TTL_DAYS = 90
MIN_ACCEPT_CONFIDENCE = 0.80

CLAIM_KINDS = frozenset(
    {
        "team_alias",
        "league_equivalence",
        "league_fingerprint",
        "market_mapping",
        "book_absence",
        "market_absence",
    }
)
CLAIM_STATUSES = frozenset({"accepted", "rejected", "quarantined"})

EVIDENCE_WEIGHTS: dict[str, float] = {
    "betradar_shared_id": 1.00,
    "exact_shared_fixture": 0.95,
    "repeated_shared_fixture": 0.90,
    "cross_book_price": 0.90,
    "league_fingerprint": 0.85,
    "legacy_review": 0.50,
    "similarity": 0.30,
    "opponent_contradiction": 0.00,
}

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "generated" / "mapping_evidence.json"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


@dataclass(frozen=True)
class Evidence:
    """One observation supporting or contradicting a claim."""

    type: str
    detail: dict[str, Any] = field(default_factory=dict)
    scan: str = ""
    books: tuple[str, ...] = ()
    observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "detail": dict(self.detail),
            "scan": self.scan,
            "books": list(self.books),
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, raw: object) -> Evidence | None:
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            return None
        detail = raw.get("detail")
        books = raw.get("books")
        return cls(
            type=raw["type"],
            detail=detail if isinstance(detail, dict) else {},
            scan=str(raw.get("scan") or ""),
            books=tuple(str(book) for book in books) if isinstance(books, list) else (),
            observed_at=str(raw.get("observed_at") or ""),
        )

    @property
    def weight(self) -> float:
        return EVIDENCE_WEIGHTS.get(self.type, 0.0)


@dataclass
class MappingClaim:
    """A mapping claim with its evidence, contradictions and lifetime."""

    kind: str
    key: str
    status: str = "quarantined"
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    decided_at: str = ""
    reason: str = ""
    ttl_days: int = DEFAULT_TTL_DAYS

    def is_stale(self, now: datetime | None = None) -> bool:
        last = _parse_iso(self.last_seen)
        if last is None:
            return True
        return (_now() if now is None else now) - last > timedelta(days=self.ttl_days)

    def is_authoritative(self, now: datetime | None = None) -> bool:
        return self.status == "accepted" and not self.is_stale(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "evidence": [item.to_dict() for item in self.evidence],
            "contradictions": list(self.contradictions),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "ttl_days": self.ttl_days,
        }

    @classmethod
    def from_dict(cls, raw: object) -> MappingClaim | None:
        if not isinstance(raw, dict):
            return None
        kind = raw.get("kind")
        key = raw.get("key")
        if kind not in CLAIM_KINDS or not isinstance(key, str) or not key:
            return None
        status = raw.get("status")
        if status not in CLAIM_STATUSES:
            return None
        evidence = [
            item
            for item in (Evidence.from_dict(entry) for entry in raw.get("evidence", []))
            if item is not None
        ] if isinstance(raw.get("evidence"), list) else []
        contradictions = raw.get("contradictions")
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            ttl_days = int(raw.get("ttl_days", DEFAULT_TTL_DAYS))
        except (TypeError, ValueError):
            ttl_days = DEFAULT_TTL_DAYS
        return cls(
            kind=kind,
            key=key,
            status=status,
            confidence=max(0.0, min(1.0, confidence)),
            evidence=evidence,
            contradictions=[str(value) for value in contradictions]
            if isinstance(contradictions, list)
            else [],
            first_seen=str(raw.get("first_seen") or ""),
            last_seen=str(raw.get("last_seen") or ""),
            decided_at=str(raw.get("decided_at") or ""),
            reason=str(raw.get("reason") or ""),
            ttl_days=max(1, ttl_days),
        )


def claim_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _raw_key(name: str) -> str:
    return raw_team_key(name)


def team_alias_key(left: str, right: str) -> str:
    return "|".join(sorted((_raw_key(left), _raw_key(right))))


def league_equivalence_key(left: str, right: str) -> str:
    return "|".join(sorted((left.strip(), right.strip())))


def market_mapping_key(bookmaker: str, mode: str, source_id: object, labels: list[str] | None = None) -> str:
    label_key = ",".join(sorted(label.strip() for label in (labels or []) if label.strip()))
    return f"{bookmaker}|{mode}|{source_id}|{label_key}"


def _confidence(evidence: list[Evidence]) -> float:
    if not evidence:
        return 0.0
    return min(1.0, max(item.weight for item in evidence))


class MappingLedger:
    """A thread-safe, atomically written collection of mapping claims."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.claims: dict[str, MappingClaim] = {}
        self._lock = threading.RLock()
        self.load_error: str = ""

    # -- persistence -------------------------------------------------------

    def load(self) -> MappingLedger:
        with self._lock:
            self.claims = {}
            self.load_error = ""
            if not self.path.exists():
                return self
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.load_error = f"{self.path}: {exc}"
                logger.warning("mapping evidence unreadable, starting empty: %s", self.load_error)
                return self
            if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
                self.load_error = f"{self.path}: unsupported schema"
                logger.warning("mapping evidence ignored: %s", self.load_error)
                return self
            claims = raw.get("claims")
            if not isinstance(claims, dict):
                self.load_error = f"{self.path}: claims is not an object"
                logger.warning("mapping evidence ignored: %s", self.load_error)
                return self
            for key, value in claims.items():
                claim = MappingClaim.from_dict(value)
                if claim is None:
                    logger.warning("mapping evidence: ignored malformed claim %r", key)
                    continue
                if claim_id(claim.kind, claim.key) != key:
                    logger.warning(
                        "mapping evidence: claim key %r does not match its contents", key
                    )
                    continue
                self.claims[key] = claim
            return self

    def save(self) -> None:
        """Write the ledger as compact JSON (M2-5).

        The ledger is a machine trust record, not hand-edited config, and every
        reader goes through ``load()`` or ``json.load``. Indenting it cost 44 MB
        on the operator's 94 MB file and pushed it over
        ``MAPPING_LEDGER_BUDGET_BYTES`` without making it more usable, so the
        on-disk form is compact while the schema, claims and evidence are
        unchanged. Never delete evidence to meet a budget; change the
        representation.
        """
        with self._lock:
            payload = {
                "schema": SCHEMA_VERSION,
                "generated_at": _iso(),
                "claims": {key: claim.to_dict() for key, claim in sorted(self.claims.items())},
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        payload,
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

    # -- lookup ------------------------------------------------------------

    def get(self, kind: str, key: str) -> MappingClaim | None:
        with self._lock:
            return self.claims.get(claim_id(kind, key))

    def is_accepted(self, kind: str, key: str, now: datetime | None = None) -> bool:
        claim = self.get(kind, key)
        return claim is not None and claim.is_authoritative(now)

    # -- mutation ----------------------------------------------------------

    def _upsert(self, kind: str, key: str) -> MappingClaim:
        full_key = claim_id(kind, key)
        claim = self.claims.get(full_key)
        if claim is None:
            claim = MappingClaim(
                kind=kind,
                key=key,
                first_seen=_iso(),
                last_seen=_iso(),
            )
            self.claims[full_key] = claim
        return claim

    def _add_evidence(self, claim: MappingClaim, evidence: list[Evidence]) -> None:
        existing = {
            (item.type, item.scan, json.dumps(item.detail, sort_keys=True, default=str))
            for item in claim.evidence
        }
        for item in evidence:
            marker = (
                item.type,
                item.scan,
                json.dumps(item.detail, sort_keys=True, default=str),
            )
            if marker not in existing:
                claim.evidence.append(item)
                existing.add(marker)
        claim.last_seen = _iso()
        claim.confidence = _confidence(claim.evidence)

    def accept(
        self,
        kind: str,
        key: str,
        evidence: list[Evidence],
        reason: str = "",
    ) -> MappingClaim:
        """Record an accepted claim, unless its evidence cannot carry it.

        A claim whose best evidence is below ``MIN_ACCEPT_CONFIDENCE`` is stored
        as ``quarantined`` instead. Callers cannot bypass this by passing
        ``reason``.
        """
        if kind not in CLAIM_KINDS:
            raise ValueError(f"unknown claim kind: {kind}")
        with self._lock:
            claim = self._upsert(kind, key)
            self._add_evidence(claim, evidence)
            if claim.status == "rejected" and "opponent_contradiction" in claim.contradictions:
                # A contradiction is durable. New observations do not erase it;
                # a different spelling pair can form a new claim instead.
                claim.reason = "revoked_opponent_contradiction"
                claim.decided_at = _iso()
                return claim
            if claim.confidence < MIN_ACCEPT_CONFIDENCE:
                claim.status = "quarantined"
                claim.reason = reason or "insufficient_evidence"
            else:
                claim.status = "accepted"
                claim.reason = reason
                claim.contradictions.clear()
            claim.decided_at = _iso()
            return claim

    def quarantine(
        self,
        kind: str,
        key: str,
        evidence: list[Evidence],
        reason: str,
        *,
        force: bool = False,
    ) -> MappingClaim:
        """Record insufficient evidence without downgrading a proven claim.

        A weak observation must not erase a claim that already carries strong
        evidence. ``force=True`` is for a contradiction policy that really does
        override the claim (an ambiguous league name, for example).
        """
        if kind not in CLAIM_KINDS:
            raise ValueError(f"unknown claim kind: {kind}")
        with self._lock:
            claim = self._upsert(kind, key)
            self._add_evidence(claim, evidence)
            if claim.status == "accepted" and not force:
                return claim
            claim.status = "quarantined"
            claim.reason = reason
            claim.decided_at = _iso()
            return claim

    def reject(
        self,
        kind: str,
        key: str,
        evidence: list[Evidence],
        reason: str,
        contradiction: str = "",
    ) -> MappingClaim:
        if kind not in CLAIM_KINDS:
            raise ValueError(f"unknown claim kind: {kind}")
        with self._lock:
            claim = self._upsert(kind, key)
            self._add_evidence(claim, evidence)
            claim.status = "rejected"
            claim.reason = reason
            if contradiction and contradiction not in claim.contradictions:
                claim.contradictions.append(contradiction)
            claim.decided_at = _iso()
            return claim

    def revoke(self, kind: str, key: str, reason: str, evidence: list[Evidence] | None = None) -> MappingClaim:
        """Turn an accepted claim into a rejected tombstone.

        The claim is kept, with its history, so a re-observation can be compared
        against what was already disproved.
        """
        with self._lock:
            claim = self._upsert(kind, key)
            if evidence:
                self._add_evidence(claim, evidence)
            claim.status = "rejected"
            claim.reason = reason
            if reason and reason not in claim.contradictions:
                claim.contradictions.append(reason)
            claim.decided_at = _iso()
            return claim

    def prune(self, max_evidence: int = 8) -> int:
        """Keep the strongest, newest evidence per claim so the file stays bounded.

        A league fingerprint needs its whole team set, so those claims keep the
        union in one record instead of many. Returns the number of records
        dropped.
        """
        dropped = 0
        with self._lock:
            for claim in self.claims.values():
                if claim.kind == "league_fingerprint":
                    teams: set[str] = set()
                    for evidence in claim.evidence:
                        raw = evidence.detail.get("teams")
                        if isinstance(raw, list):
                            teams.update(str(team) for team in raw)
                    if claim.evidence:
                        latest = claim.evidence[-1]
                        claim.evidence = [
                            Evidence(
                                type=latest.type,
                                detail={"teams": sorted(teams)},
                                scan=latest.scan,
                                books=latest.books,
                                observed_at=latest.observed_at,
                            )
                        ]
                    continue
                if len(claim.evidence) <= max_evidence:
                    continue
                keep = sorted(
                    claim.evidence,
                    key=lambda item: (item.weight, item.observed_at),
                    reverse=True,
                )[:max_evidence]
                dropped += len(claim.evidence) - len(keep)
                claim.evidence = sorted(keep, key=lambda item: item.observed_at)
            return dropped

    # -- reporting ---------------------------------------------------------

    def diff(self, previous: MappingLedger | None) -> dict[str, Any]:
        old = previous.claims if previous is not None else {}
        new = self.claims
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = sorted(
            key
            for key in set(new) & set(old)
            if (new[key].status, new[key].confidence) != (old[key].status, old[key].confidence)
        )
        counts = {"accepted": 0, "rejected": 0, "quarantined": 0}
        for claim in new.values():
            counts[claim.status] = counts.get(claim.status, 0) + 1
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "counts": counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "generated_at": _iso(),
            "claims": {key: claim.to_dict() for key, claim in sorted(self.claims.items())},
        }
