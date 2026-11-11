"""SR4-4 / SR4-12: runtime structural fingerprint and drift alarm.

The wire schemas (SR4-3) fail a book closed when a payload it models moves.  They
cannot see a change *outside* the modelled fields — a renamed team key, a new
envelope level, an emptied array — because ``extra="allow"`` deliberately keeps
such payloads parsing.  This module closes that gap at the raw-response
boundary:

* ``fingerprint(payload)`` hashes a stable *structural* signature of a payload:
  every key path with its JSON type, array indices collapsed, and maps keyed by
  numeric ids collapsed to ``<id>``.  Values are deliberately ignored, so the
  same shape with different prices has the same fingerprint.
* Lists are heterogeneous in real feeds: an optional per-item key
  (``items[].matchComment``) is carried by only some rows.  The signature keeps
  the paths *common to every item* (SR4-12), unions the types a common path
  shows across items, and records the per-item-only paths separately.  A key on
  only some items therefore does not alert; a key removed from every item still
  does.  A path that was optional may become common without an alert, but a
  common path may not disappear or change type.  ``null`` is treated as "no
  value", so a nullable field does not flip the digest on a page where no row
  happens to be null.
* ``observe(book, endpoint, payload)`` compares one response with the baseline
  stored per ``(book, endpoint)`` in ``config/generated/wire_fingerprints.json``.
  The first informative response records a baseline; a later response with a
  different structure increments ``bh_wire_structure_drift_total`` and logs the
  added/removed paths.  The baseline is **not** overwritten on drift: it stays
  the last good shape until an operator reviews the change and deletes that
  entry to record the new one.
* An empty response never alerts: a payload without items (``[]`` or
  ``{"events": []}``) carries no shape to compare, so it neither records nor
  drifts.  A feed that goes empty is reported by the scan's own book status, not
  by this alarm.
* The warning is logged at most once per book, endpoint and diff in a scan
  (``begin_scan()``, called by ``run_scan``).  A page of 173 suspended offers is
  one line, not 173; the counter still counts every occurrence.

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

# Bumped when the signature semantics change. An older entry is re-recorded
# without alerting once, so an upgrade does not look like drift on every book.
FINGERPRINT_VERSION = 2

# Bounds keep the signature deterministic and cheap on a large page.
_MAX_DEPTH = 6
_MAX_KEYS = 60
_MAX_ARRAY_ITEMS = 50
_MAX_DIFF_PATHS = 12

_LOCK = threading.Lock()

# Drift warnings already logged in this scan, keyed by book, endpoint and diff.
# One line per signature per scan; cleared by ``begin_scan()``.
_WARNED: set[tuple[str, str, str]] = set()


def begin_scan() -> None:
    """Start a scan's alarm window: log each drift signature once more."""
    with _LOCK:
        _WARNED.clear()


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


def _normalise_types(types: set[str]) -> tuple[str, ...]:
    """Drop ``null`` when the path also carries a real value type.

    A nullable field shows up as both ``null`` and, say, ``string`` depending on
    the rows a page happens to contain. That is data variation, not a shape
    change; keep ``null`` only when it is the only type observed.
    """
    non_null = types - {"null"}
    return tuple(sorted(non_null or types))


def _structure(
    value: Any, prefix: str = "", depth: int = 0
) -> tuple[dict[str, set[str]], set[str]]:
    """Return ``(required path -> types, optional path names)`` for a value.

    A dict's keys are all required for that object. A list keeps only the path
    names common to every item; the others are optional. Types are unioned
    across the items that carry a common path, then normalised by
    ``_normalise_types``.
    """
    if depth > _MAX_DEPTH or len(prefix) > 200:
        return {}, set()

    if isinstance(value, dict):
        required: dict[str, set[str]] = {}
        optional: set[str] = set()
        for raw_key in sorted(value)[:_MAX_KEYS]:
            key = _key_name(raw_key)
            child = f"{prefix}.{key}" if prefix else key
            child_required, child_optional = _structure(
                value[raw_key], child, depth + 1
            )
            required.setdefault(child, set()).add(_json_type(value[raw_key]))
            for name, types in child_required.items():
                required.setdefault(name, set()).update(types)
            optional |= child_optional
        return required, optional

    if isinstance(value, list):
        child = f"{prefix}[]" if prefix else "[]"
        list_required: dict[str, set[str]] = {child: {"array"}}
        list_optional: set[str] = set()
        item_shapes: list[dict[str, set[str]]] = []
        all_names: set[str] = set()
        for item in value[:_MAX_ARRAY_ITEMS]:
            item_required, item_optional = _structure(item, child, depth + 1)
            item_shapes.append(item_required)
            all_names |= set(item_required)
            list_optional |= item_optional
        if item_shapes:
            common = set.intersection(*(set(shape) for shape in item_shapes))
            for name in common:
                item_types: set[str] = set()
                for shape in item_shapes:
                    item_types |= shape[name]
                list_required[name] = item_types
            list_optional |= all_names - common
        return list_required, list_optional

    return {}, set()


def _entries(required: dict[str, set[str]]) -> set[str]:
    """Flatten the required map into ``path:type`` strings."""
    return {
        f"{name}:{type_name}"
        for name, types in required.items()
        for type_name in _normalise_types(types)
    }


def structural_paths(payload: Any) -> set[str]:
    """The ``path:type`` set common to every item of one payload (SR4-12)."""
    required, _optional = _structure(payload)
    return _entries(required)


def optional_paths(payload: Any) -> set[str]:
    """Path names carried by only some list items; diagnostics and tests."""
    _required, optional = _structure(payload)
    return set(optional)


def _digest(paths: set[str]) -> str:
    canonical = json.dumps(sorted(paths), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def fingerprint(payload: Any) -> str:
    """A stable structural hash: same required shape, different values, match."""
    return _digest(structural_paths(payload))


def _informative(payload: Any) -> bool:
    """Whether a payload carries a shape worth learning or comparing.

    An empty page (``[]`` or ``{"events": []}``) has no element shape to learn;
    recording it would make the first real page look like drift, and comparing a
    later empty page against a real baseline would alarm on the feed simply
    being empty.  A dict with list values is representative only when at least
    one list carries an item, so an empty item list next to non-empty metadata
    (``{"events": [], "filters": {...}}``) stays silent.  A dict with no list at
    all is an id-keyed map and needs a non-empty object.
    """
    if isinstance(payload, list):
        return bool(payload)
    if isinstance(payload, dict):
        lists = [value for value in payload.values() if isinstance(value, list)]
        if lists:
            return any(bool(value) for value in lists)
        return any(
            isinstance(value, dict) and bool(value) for value in payload.values()
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


def _record(
    baselines: dict[str, Any], key: str, paths: set[str], optional: set[str]
) -> None:
    """Write the current shape as the last good baseline."""
    baselines[key] = {
        "version": FINGERPRINT_VERSION,
        "fingerprint": _digest(paths),
        "paths": sorted(paths),
        "optional": sorted(optional),
        "updated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
    }


def _by_name(entries: set[str]) -> dict[str, set[str]]:
    """Group ``path:type`` strings by path; a path name may contain ``:``."""
    grouped: dict[str, set[str]] = {}
    for entry in entries:
        name, separator, type_name = entry.rpartition(":")
        if separator:
            grouped.setdefault(name, set()).add(type_name)
    return grouped


def _changes(
    previous: dict[str, set[str]],
    current: dict[str, set[str]],
    previous_optional: set[str],
) -> tuple[list[str], list[str], list[str]]:
    """Drift between two shapes: removed, unexpected additions, type changes.

    An added path that was optional in the baseline is a promotion, not drift:
    it was already part of the feed's shape, just not carried by every row.
    """
    removed = sorted(set(previous) - set(current))
    added = sorted(set(current) - set(previous))
    unexpected = [name for name in added if name not in previous_optional]
    changed = sorted(
        name
        for name in set(previous) & set(current)
        if previous[name] != current[name]
    )
    return removed, unexpected, changed


def _entries_for(by_name: dict[str, set[str]], names: list[str]) -> str:
    return ",".join(
        f"{name}:{type_name}"
        for name in names
        for type_name in sorted(by_name.get(name, ()))
    )


def _diff(
    previous: dict[str, set[str]],
    current: dict[str, set[str]],
    removed: list[str],
    unexpected: list[str],
    changed: list[str],
) -> str:
    parts = []
    if removed:
        parts.append("removed=" + _entries_for(previous, removed[:_MAX_DIFF_PATHS]))
    if unexpected:
        parts.append("added=" + _entries_for(current, unexpected[:_MAX_DIFF_PATHS]))
    if changed:
        parts.append(
            "changed="
            + ",".join(
                f"{name}:{'|'.join(sorted(previous[name]))}"
                f"->{'|'.join(sorted(current[name]))}"
                for name in changed[:_MAX_DIFF_PATHS]
            )
        )
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
    if not _informative(payload):
        return "empty"
    required, optional = _structure(payload)
    points = _entries(required)
    current = _digest(points)
    state_path = Path(path) if path is not None else DEFAULT_PATH
    key = f"{book}|{endpoint}"
    try:
        with _LOCK:
            state = _load(state_path)
            baselines = state["baselines"]
            previous = baselines.get(key)
            if previous is None:
                _record(baselines, key, points, optional)
                _save(state_path, state)
                logger.info(
                    "[%s] structural baseline recorded for %s (%s)",
                    book,
                    endpoint,
                    current,
                )
                return "new"
            if int(previous.get("version") or 1) != FINGERPRINT_VERSION:
                # SR4-12 changed the signature. Re-record once without an alert
                # so an upgrade does not look like drift on every book.
                _record(baselines, key, points, optional)
                _save(state_path, state)
                logger.info(
                    "[%s] structural baseline upgraded to v%d for %s",
                    book,
                    FINGERPRINT_VERSION,
                    endpoint,
                )
                return "new"
            if previous.get("fingerprint") == current:
                return "match"
            previous_paths = set(previous.get("paths") or ())
            previous_optional = set(previous.get("optional") or ())
            before = _by_name(previous_paths)
            after = _by_name(points)
            removed, unexpected, changed = _changes(
                before, after, previous_optional
            )
            if not removed and not unexpected and not changed:
                # Only previously known optional paths became common. Keep the
                # shape current so a later removal of one is still an alert.
                _record(baselines, key, points, optional)
                _save(state_path, state)
                return "match"
            metrics.inc(
                METRIC_STRUCTURE_DRIFT, 1, book=book, endpoint=endpoint
            )
            diff = _diff(before, after, removed, unexpected, changed) or "no path diff"
            signature = (book, endpoint, diff)
            if signature in _WARNED:
                # One line per book/endpoint/diff per scan; the counter above
                # still counts every occurrence.
                return "drift"
            _WARNED.add(signature)
            logger.warning(
                "[%s] structural drift at %s (was %s, now %s): %s",
                book,
                endpoint,
                previous.get("fingerprint"),
                current,
                diff,
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
    "FINGERPRINT_VERSION",
    "METRIC_STRUCTURE_DRIFT",
    "baseline",
    "begin_scan",
    "fingerprint",
    "observe",
    "optional_paths",
    "structural_paths",
]
