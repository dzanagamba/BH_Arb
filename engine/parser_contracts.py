"""Dated parser contracts for the frozen market fixtures (N2-6).

A fixture proves the parser still reads a real payload. A *contract* records the
parts of that payload a parser depends on — the top-level keys, the source-id
set, the label set and the nested shape — so a feed changing one of them fails
with a diff instead of a vague parse error.

The contract is evidence about the feed, not a trust decision. A changed id or a
new market never enters the registry or the pricing path from here: the diff
only tells an operator that the book's payload moved and a human must re-capture
and re-admit it through the existing evidence path.

The expected contracts live next to the fixtures in
``tests/fixtures/markets/contracts.json``. They are updated by
``scripts/refresh_fixtures.py --write`` after a reviewed capture.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "markets"
CONTRACTS_PATH = FIXTURE_DIR / "contracts.json"

# Keys every capture must keep, whatever the book. A payload that loses one is
# no longer a usable dated capture. SR4-2 added the metadata header:
# ``recorded_at`` is provenance (with the source it came from) while
# ``captured_at`` remains the reviewed date the 120-day age policy reads.
REQUIRED_TOP_LEVEL_KEYS = (
    "bookmaker",
    "mode",
    "captured_at",
    "recorded_at",
    "recorded_at_source",
    "endpoint",
    "http_method",
    "http_status",
    "capture_tool_version",
    "source",
    "provenance",
    "payload_kind",
    "expected_markets",
    "bets",
)

# Where a ``recorded_at`` came from. ``capture`` is written by the capture tool;
# ``git_commit`` is the backfilled fallback for captures that predate SR4-2
# (marked with ``metadata_backfilled``); ``captured_at`` is the last resort when
# git history is unavailable.
RECORDED_AT_SOURCES = frozenset({"capture", "git_commit", "captured_at"})
HTTP_METHODS = frozenset({"GET", "POST"})
CAPTURE_TOOL_VERSION = "2"
# Fixtures captured before the tool wrote a version carry this marker instead
# of inventing a version number.
LEGACY_CAPTURE_TOOL_VERSION = "pre-metadata"

# Header/key names that must never be frozen into a fixture. Matching is exact
# and case-insensitive, so ``matchIdsToken`` (an event-id list in Betole's
# endpoint) is not mistaken for a credential.
SECRET_KEYS = frozenset(
    {
        "cookie",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "www-authenticate",
        "x-api-key",
        "api_key",
        "api-key",
        "bearer",
        "access_token",
        "refresh_token",
        "id_token",
        "csrf",
        "csrf_token",
        "xsrf",
        "session_id",
        "sessionid",
        "phpsessid",
        "cf_clearance",
    }
)

# Payloads whose parser emits an experimental market that has no registry row
# yet. The contract lists it separately so it is visible, never silently folded
# into the registry-declared set.
EXPERIMENTAL_MARKETS: dict[str, tuple[str, ...]] = {
    "betole": ("first_half_1x2",),
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(values: Iterable[str]) -> str:
    return hashlib.sha256(_canonical(sorted(set(values))).encode("utf-8")).hexdigest()[:16]


def _payload_paths(value: Any, prefix: str = "", depth: int = 0) -> set[str]:
    """Return a bounded, stable structural signature of a payload value."""
    if depth > 4 or len(prefix) > 160:
        return set()
    paths: set[str] = set()
    if isinstance(value, dict):
        for key in sorted(value)[:40]:
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.add(f"{child}:{type(value[key]).__name__}")
            paths.update(_payload_paths(value[key], child, depth + 1))
    elif isinstance(value, list):
        paths.add(f"{prefix}[]")
        if value:
            paths.update(_payload_paths(value[0], f"{prefix}[]", depth + 1))
    return paths


def _bets(data: dict[str, Any]) -> Any:
    return data.get("bets")


def event_count(data: dict[str, Any]) -> int:
    bets = _bets(data)
    if isinstance(bets, list):
        return len(bets)
    if isinstance(bets, dict):
        return len(bets)
    return 1 if bets is not None else 0


def market_ids(data: dict[str, Any]) -> list[str]:
    """The source ids the captured payload carries, independent of the parser."""
    book, bets = data["bookmaker"], _bets(data)
    if book in ("mdshop", "admiralbet") and isinstance(bets, list):
        return sorted({str(bet.get("betTypeId")) for bet in bets})
    if book == "wwin" and isinstance(bets, list):
        return sorted({str(bet.get("idBt")) for bet in bets})
    if book == "mbet" and isinstance(bets, dict):
        return sorted({":".join(key.split(":")[:2]) for key in bets})
    if book == "sportplus" and isinstance(bets, list):
        return sorted({str(bet.get("id")) for bet in bets})
    if book == "mozzartbet" and isinstance(bets, list):
        return sorted({str((bet.get("game") or {}).get("id")) for bet in bets})
    if book == "premier_kladionica":
        return sorted({str(row[1]) for row in (data.get("lookup") or {}).get("set_tip", [])})
    if book == "maxbet" and isinstance(bets, list):
        return sorted({str(bet.get("id")) for bet in bets})
    if book == "evlbet" and isinstance(bets, list):
        offer = (bets[0].get("BasicOffer") if bets else {}) or {}
        return sorted({str(offer.get("BetTypeKey") or offer.get("GameId") or "12005")})
    if book == "betole" and isinstance(bets, dict):
        return sorted(str(code) for code in bets)
    return []


def labels(data: dict[str, Any]) -> list[str]:
    """The human-readable strings a book's parser dispatches on."""
    book, bets = data["bookmaker"], _bets(data)
    found: set[str] = set()
    if book in ("mdshop", "admiralbet") and isinstance(bets, list):
        for bet in bets:
            found.add(str(bet.get("betTypeName") or ""))
            for outcome in bet.get("betOutcomes") or []:
                found.add(str(outcome.get("name") or ""))
    elif book == "wwin" and isinstance(bets, list):
        for bet in bets:
            for odd in bet.get("odds") or []:
                found.add(str(odd.get("t") or ""))
    elif book == "mbet" and isinstance(bets, dict):
        for key, value in bets.items():
            found.add(str(key))
            found.add(str((value or {}).get("market_key") or ""))
    elif book == "sportplus" and isinstance(bets, list):
        for bet in bets:
            found.add(str(bet.get("name") or ""))
            for odd in bet.get("odds") or []:
                found.add(str(odd.get("alias") or ""))
    elif book == "mozzartbet" and isinstance(bets, list):
        for bet in bets:
            found.add(str((bet.get("game") or {}).get("name") or ""))
            found.add(str((bet.get("subgame") or {}).get("name") or ""))
    elif book == "premier_kladionica":
        lookup = data.get("lookup") or {}
        for row in lookup.get("set_tip", []):
            found.add(str(row[2]))
        for row in lookup.get("set_tip_tip", []):
            found.add(str(row[4]))
    elif book == "maxbet" and isinstance(bets, list):
        for bet in bets:
            found.add(str(bet.get("name") or ""))
            for outcome in bet.get("outcomes") or []:
                found.add(str(outcome.get("outcome") or ""))
    elif book == "evlbet" and isinstance(bets, list):
        offer = (bets[0].get("BasicOffer") if bets else {}) or {}
        found.add(str(offer.get("Name") or ""))
        for odd in offer.get("Odds") or []:
            found.add(str(odd.get("Name") or ""))
    elif book == "betole" and isinstance(bets, dict):
        found.update(str(code) for code in bets)
    return sorted(value for value in found if value)


def compute_contract(fixture: Path) -> dict[str, Any]:
    """Compute the current contract for one fixture file."""
    data = json.loads(fixture.read_text(encoding="utf-8"))
    try:
        fixture_ref = str(fixture.relative_to(REPO_ROOT))
    except ValueError:
        fixture_ref = str(fixture)
    payload_shape = sorted(_payload_paths(_bets(data)))
    label_values = labels(data)
    ids = market_ids(data)
    contract = {
        "fixture": fixture_ref,
        "bookmaker": str(data.get("bookmaker") or ""),
        "mode": str(data.get("mode") or ""),
        "captured_at": str(data.get("captured_at") or ""),
        "payload_kind": str(data.get("payload_kind") or ""),
        "required_top_level_keys": list(REQUIRED_TOP_LEVEL_KEYS),
        "top_level_keys": sorted(data),
        "event_count": event_count(data),
        "market_ids": ids,
        "labels": label_values,
        "structure": payload_shape,
        "labels_fingerprint": _digest(label_values),
        "structure_fingerprint": _digest(payload_shape),
        "fingerprint": _digest(
            [*ids, *[f"label:{value}" for value in label_values],
             *[f"shape:{value}" for value in payload_shape]]
        ),
        "experimental_markets": list(EXPERIMENTAL_MARKETS.get(str(data.get("bookmaker")), ())),
    }
    return contract


def compute_all(fixture_dir: Path = FIXTURE_DIR) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for fixture in sorted(fixture_dir.glob("*.json")):
        if fixture.name == "contracts.json":
            continue
        contract = compute_contract(fixture)
        contracts[fixture.stem] = contract
    return contracts


def diff_contract(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Return an actionable diff between two contracts, or ``{}`` when equal."""
    changed: dict[str, Any] = {}
    for key in ("bookmaker", "mode", "payload_kind"):
        if expected.get(key) != actual.get(key):
            changed[key] = {"expected": expected.get(key), "actual": actual.get(key)}
    if expected.get("fingerprint") != actual.get("fingerprint"):
        changed["fingerprint"] = {
            "expected": expected.get("fingerprint"),
            "actual": actual.get("fingerprint"),
        }
    for key in ("top_level_keys", "market_ids", "labels", "structure"):
        before, after = set(expected.get(key) or []), set(actual.get(key) or [])
        if before != after:
            changed[key] = {
                "removed": sorted(before - after),
                "added": sorted(after - before),
            }
    if expected.get("event_count") != actual.get("event_count"):
        changed["event_count"] = {
            "expected": expected.get("event_count"),
            "actual": actual.get("event_count"),
        }
    return changed


def diff_all(
    expected: dict[str, dict[str, Any]], actual: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {"added": [], "removed": [], "changed": {}}
    result["added"] = sorted(set(actual) - set(expected))
    result["removed"] = sorted(set(expected) - set(actual))
    for name in sorted(set(expected) & set(actual)):
        change = diff_contract(expected[name], actual[name])
        if change:
            result["changed"][name] = change
    return result


def load_contracts(path: Path = CONTRACTS_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": 1, "max_age_days": 120, "contracts": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("contracts"), dict):
        return {"schema": 1, "max_age_days": 120, "contracts": {}}
    return payload


def save_contracts(
    contracts: dict[str, dict[str, Any]],
    path: Path = CONTRACTS_PATH,
    *,
    max_age_days: int = 120,
) -> None:
    payload = {
        "schema": 1,
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "max_age_days": max_age_days,
        "contracts": contracts,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _secret_key_paths(value: Any, prefix: str = "") -> list[str]:
    """Every path whose key is a header/credential name, recursively."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in SECRET_KEYS:
                found.append(path)
            found.extend(_secret_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_key_paths(child, f"{prefix}[{index}]"))
    return found


def scrub_secrets(value: Any) -> Any:
    """Return ``value`` without any header/credential key (SR4-2).

    The capture tool trims payloads to the data a parser reads, but it earlier
    kept whatever the source object carried. Scrubbing by key name means a
    future capture cannot freeze a cookie, bearer token or CSRF value into the
    repository.
    """
    if isinstance(value, dict):
        return {
            key: scrub_secrets(child)
            for key, child in value.items()
            if str(key).lower() not in SECRET_KEYS
        }
    if isinstance(value, list):
        return [scrub_secrets(child) for child in value]
    return value


def http_method_for(endpoint: Any) -> str:
    """The request method an endpoint string records (``POST ...`` or GET)."""
    return "POST" if str(endpoint or "").strip().upper().startswith("POST ") else "GET"


def metadata_issues(data: dict[str, Any]) -> list[str]:
    """Reasons one fixture's metadata header is not usable, if any."""
    issues: list[str] = []
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in data]
    if missing:
        issues.append("missing metadata: " + ", ".join(missing))

    for key in (
        "bookmaker",
        "mode",
        "endpoint",
        "source",
        "payload_kind",
        "provenance",
        "recorded_at_source",
        "capture_tool_version",
    ):
        if key in data and not str(data.get(key) or "").strip():
            issues.append(f"{key} is empty")

    try:
        date.fromisoformat(str(data.get("captured_at") or ""))
    except ValueError:
        issues.append("captured_at is not an ISO date (YYYY-MM-DD)")

    recorded = str(data.get("recorded_at") or "")
    try:
        recorded_at = datetime.fromisoformat(recorded)
    except ValueError:
        issues.append("recorded_at is not an ISO 8601 timestamp")
    else:
        if recorded_at.tzinfo is None:
            issues.append("recorded_at has no timezone")

    source = str(data.get("recorded_at_source") or "")
    if source and source not in RECORDED_AT_SOURCES:
        issues.append(
            "recorded_at_source must be one of "
            + ", ".join(sorted(RECORDED_AT_SOURCES))
        )
    if source == "git_commit" and not str(data.get("recorded_at_commit") or "").strip():
        issues.append("recorded_at_source is git_commit but recorded_at_commit is empty")

    method = str(data.get("http_method") or "").upper()
    if method and method not in HTTP_METHODS:
        issues.append("http_method must be GET or POST")

    status = data.get("http_status")
    if (
        not isinstance(status, int)
        or isinstance(status, bool)
        or not 200 <= status <= 299
    ):
        issues.append("http_status is not a 2xx integer")

    if "metadata_backfilled" in data and not isinstance(
        data["metadata_backfilled"], bool
    ):
        issues.append("metadata_backfilled must be a boolean")

    for path in _secret_key_paths(data):
        issues.append(f"secret-bearing metadata at {path}")
    return issues


def metadata_report(fixture_dir: Path = FIXTURE_DIR) -> dict[str, Any]:
    """The fixture metadata gate: one entry per fixture with an issue."""
    fixtures = sorted(
        path for path in fixture_dir.glob("*.json") if path.name != "contracts.json"
    )
    issues: dict[str, list[str]] = {}
    for fixture in fixtures:
        try:
            data = json.loads(fixture.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues[fixture.stem] = [f"unreadable fixture: {exc}"]
            continue
        if not isinstance(data, dict):
            issues[fixture.stem] = ["fixture is not a JSON object"]
            continue
        found = metadata_issues(data)
        if found:
            issues[fixture.stem] = found
    return {
        "ok": not issues,
        "checked": len(fixtures),
        "required": list(REQUIRED_TOP_LEVEL_KEYS),
        "issues": issues,
    }


def backfill_metadata(
    data: dict[str, Any],
    *,
    recorded_at: str,
    commit: str = "",
    source: str = "git_commit",
) -> dict[str, Any]:
    """Fill the SR4-2 header on an older capture without changing its payload.

    The caller supplies the timestamp (from git history) and marks the source,
    so a backfilled fixture is never presented as a fresh capture. Existing
    values win; the payload, endpoint and provenance are untouched.
    """
    result = deepcopy(data)
    if recorded_at:
        result.setdefault("recorded_at", recorded_at)
    result.setdefault("recorded_at_source", source)
    if commit:
        result.setdefault("recorded_at_commit", commit)
    result.setdefault("http_method", http_method_for(result.get("endpoint")))
    result.setdefault("http_status", 200)
    result.setdefault("capture_tool_version", LEGACY_CAPTURE_TOOL_VERSION)
    result.setdefault("metadata_backfilled", True)
    return scrub_secrets(result)


def stale_contracts(
    contracts: dict[str, dict[str, Any]],
    *,
    max_age_days: int,
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or date.today()
    stale: list[dict[str, Any]] = []
    for name, contract in sorted(contracts.items()):
        try:
            captured = date.fromisoformat(str(contract.get("captured_at")))
        except ValueError:
            stale.append({"contract": name, "captured_at": contract.get("captured_at"), "age_days": None})
            continue
        age = (today - captured).days
        if age > max_age_days:
            stale.append(
                {
                    "contract": name,
                    "bookmaker": contract.get("bookmaker"),
                    "mode": contract.get("mode"),
                    "captured_at": captured.isoformat(),
                    "age_days": age,
                    "max_age_days": max_age_days,
                }
            )
    return stale


def coverage(
    contracts: dict[str, dict[str, Any]], enabled_books: Iterable[str]
) -> dict[str, Any]:
    """Which enabled books have a dated contract, and which modes are missing.

    A missing book is a declared gap, never an implicit one: the health payload
    lists it so an operator can see it without reading the test suite.
    """
    enabled = sorted(set(enabled_books))
    books = sorted({str(contract.get("bookmaker") or "") for contract in contracts.values()})
    modes: dict[str, list[str]] = {}
    for contract in contracts.values():
        book = str(contract.get("bookmaker") or "")
        modes.setdefault(book, []).append(str(contract.get("mode") or ""))
    missing_books = [book for book in enabled if book not in books]
    missing_modes = {
        book: sorted({"prematch", "live"} - set(modes.get(book, [])))
        for book in enabled
        if book in books and {"prematch", "live"} - set(modes.get(book, []))
    }
    return {
        "enabled_books": enabled,
        "books_with_contract": books,
        "missing_books": missing_books,
        "missing_modes": missing_modes,
        "contracts": len(contracts),
    }


def contract_health(
    path: Path = CONTRACTS_PATH,
    *,
    enabled_books: Iterable[str] = (),
    today: date | None = None,
) -> dict[str, Any]:
    """The bounded health block: counts, gaps, stale captures and their ages."""
    payload = load_contracts(path)
    contracts = payload.get("contracts") or {}
    max_age = int(payload.get("max_age_days") or 120)
    stale = stale_contracts(contracts, max_age_days=max_age, today=today)
    captures = [
        str(contract.get("captured_at"))
        for contract in contracts.values()
        if contract.get("captured_at")
    ]
    result = {
        "contracts": len(contracts),
        "max_age_days": max_age,
        "generated_at": payload.get("generated_at") or "",
        "oldest_capture": min(captures) if captures else "",
        "latest_capture": max(captures) if captures else "",
        "stale": stale,
        "stale_count": len(stale),
        "checked_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
    }
    result.update(coverage(contracts, enabled_books))
    return result
