"""SR4-4: runtime structural fingerprint and drift alarm.

The wire schemas (SR4-3) fail a book closed when a payload it models moves.  They
cannot see a change *outside* the modelled fields — a renamed team key, a new
envelope level, an emptied array — because `extra="allow"` deliberately keeps
such payloads parsing.  This module closes that gap at the raw-response
boundary:

* ``fingerprint(payload)`` hashes a stable *structural* signature of a payload:
  every key path with its JSON type, array indices collapsed, and maps keyed by
  numeric ids collapsed to ``<id>``.  Values are deliberately ignored, so the
  same shape with different prices has the same fingerprint.
* ``observe(book, endpoint, payload)`` compares one response with the baseline
  stored per ``(book, endpoint)`` in ``config/generated/wire_fingerprints.json``.
  The first informative response records a baseline; a later response with a
  different structure increments ``bh_wire_structure_drift_total`` and logs the
  added/removed paths.  The baseline is **not** overwritten on drift: it stays
  the last good shape until an operator reviews the change and deletes that
  entry to record the new one.

This is alert-only telemetry.  It never rejects a payload, changes a price or
touches the certainty gate; the wire schemas own fail-closed behaviour.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.observability import metrics

logger = logging.getLogger(__name__)

METRIC_STRUCTURE_DRIFT = "bh_wire_structure_drift_total"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "config" / "generated" / "wire_fingerprints.json"

# Bounds keep the signature deterministic and cheap on a large page.
_MAX_DEPTH = 6
_MAX_KEYS = 60
_MAX_ARRAY_ITEMS = 50
_MAX_DIFF_PATHS = 12

_LOCK = threading.Lock()


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unknown"


def _key_name(key: Any) -> str:
    """Collapse an id-keyed map key so per-event ids are structure-free.

    ``headerBets`` is ``{"<eventId>": bet}`` and other feeds use the same
    pattern.  A numeric key is data, not a field name, so it must not enter the
    fingerprint or every new event would look like a rename.
    """
    text = str(key)
    return "<id>" if text.isdigit() else text


def _walk(value: Any, prefix: str, depth: int, paths: set[str]) -> None:
    if depth > _MAX_DEPTH or len(prefix) > 200:
        return
    if isinstance(value, dict):
        for raw_key in sorted(value)[:_MAX_KEYS]:
            key = _key_name(raw_key)
            child = f"{prefix}.{key}" if prefix else key
            paths.add(f"{child}:{_json_type(value[raw_key])}")
            _walk(value[raw_key], child, depth + 1, paths)
    elif isinstance(value, list):
        child = f"{prefix}[]" if prefix else "[]"
        paths.add(f"{child}:array")
        for item in value[:_MAX_ARRAY_ITEMS]:
            _walk(item, child, depth + 1, paths)


def structural_paths(payload: Any) -> set[str]:
    """The sorted-by-construction structural path set of one payload."""
    paths: set[str] = set()
    _walk(payload, "", 0, paths)
    return paths


def _digest(paths: set[str]) -> str:
    canonical = json.dumps(sorted(paths), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def fingerprint(payload: Any) -> str:
    """A stable structural hash: same shape and types, different values, match."""
    return _digest(structural_paths(payload))


def _informative(payload: Any) -> bool:
    """Whether a payload can establish a baseline.

    An empty page (``[]`` or ``{"events": []}``) has no element shape to learn;
    recording it would make the first real page look like drift.  A payload with
    at least one non-empty container is representative.
    """
    if isinstance(payload, list):
        return bool(payload)
    if isinstance(payload, dict):
        return any(
            (isinstance(value, list | dict) and bool(value))
            for value in payload.values()
        )
    return False


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": 1, "baselines": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("baselines"), dict):
        return {"schema": 1, "baselines": {}}
    return payload


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _diff(previous: set[str], current: set[str]) -> str:
    added = sorted(current - previous)
    removed = sorted(previous - current)
    parts = []
    if added:
        parts.append("added=" + ",".join(added[:_MAX_DIFF_PATHS]))
    if removed:
        parts.append("removed=" + ",".join(removed[:_MAX_DIFF_PATHS]))
    return " ".join(parts)


def observe(
    book: str,
    endpoint: str,
    payload: Any,
    *,
    path: Path | None = None,
) -> str:
    """Compare one raw response with its baseline. Returns ``new``/``match``/``drift``.

    Never raises and never changes the payload: a failed read or write only logs
    a warning, because this alarm must not turn into a second failure mode.
    """
    points = structural_paths(payload)
    current = _digest(points)
    state_path = Path(path) if path is not None else DEFAULT_PATH
    key = f"{book}|{endpoint}"
    try:
        with _LOCK:
            state = _load(state_path)
            baselines = state["baselines"]
            previous = baselines.get(key)
            if previous is None:
                if not _informative(payload):
                    return "empty"
                baselines[key] = {
                    "fingerprint": current,
                    "paths": sorted(points),
                    "updated_at": datetime.now(UTC)
                    .replace(tzinfo=None)
                    .isoformat(timespec="seconds"),
                }
                _save(state_path, state)
                logger.info(
                    "[%s] structural baseline recorded for %s (%s)",
                    book,
                    endpoint,
                    current,
                )
                return "new"
            if previous.get("fingerprint") == current:
                return "match"
            previous_paths = set(previous.get("paths") or ())
            metrics.inc(
                METRIC_STRUCTURE_DRIFT, 1, book=book, endpoint=endpoint
            )
            logger.warning(
                "[%s] structural drift at %s (was %s, now %s): %s",
                book,
                endpoint,
                previous.get("fingerprint"),
                current,
                _diff(previous_paths, points) or "no path diff",
            )
            # Deliberately keep the last good baseline: the alarm stays until an
            # operator reviews the change and removes the entry.
            return "drift"
    except OSError as exc:  # pragma: no cover - read-only fs is operator-specific
        logger.warning(
            "[%s] structural drift check skipped for %s: %s", book, endpoint, exc
        )
        return "error"


def baseline(path: Path | None = None) -> dict[str, Any]:
    """The stored baselines, for diagnostics and tests."""
    state = _load(Path(path) if path is not None else DEFAULT_PATH)
    return state["baselines"]


__all__ = [
    "DEFAULT_PATH",
    "METRIC_STRUCTURE_DRIFT",
    "baseline",
    "fingerprint",
    "observe",
    "structural_paths",
]
