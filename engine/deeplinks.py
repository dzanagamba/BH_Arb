"""Deep-link declarations: the per-book route store the certainty gate reads.

A book either declares a per-event route (``supports_event_id: true`` with a
template containing ``{event_id}``), declares that it has none
(``supports_event_id: false``), or declares nothing. Only the explicit boolean
``false`` proves there is no link to check; a missing key, a string or a null
must all fail safe and keep the book blocking.

The file is read on first use and whenever its signature (mtime, size) changes,
so an edit takes effect on the next gate lookup or health call without a
restart. A malformed or missing file grants no declarations. This store is a
config reader beside the gate that trusts it, not scraper I/O; it used to live in
``scrapers.common`` and made ``engine`` depend on ``scrapers``.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import NamedTuple
from urllib.parse import quote

logger = logging.getLogger(__name__)


_DEEPLINK_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_deeplinks.json")
_deeplink_cache: dict | None = None
# The file signature the cached map was loaded from. A cache injected directly
# by a test has no loaded_at, and is treated as an explicit override rather than
# something the file is allowed to overwrite.
_DeeplinkSignature = tuple[int, int]
_deeplink_cache_signature: _DeeplinkSignature | None = None
_deeplink_source_mtime: float | None = None
_deeplink_loaded_at: datetime | None = None
_deeplink_load_error: str | None = None


def _deeplink_file_signature() -> tuple[_DeeplinkSignature | None, float | None]:
    """Return ((mtime_ns, size), mtime_seconds) for the declaration file.

    A missing/unreadable file has no signature. That is different from a file
    that is present but empty: the first is a config that cannot be trusted, the
    second is a valid (if useless) declaration map.
    """
    try:
        stat = os.stat(_DEEPLINK_CONFIG_PATH)
    except OSError:
        return None, None
    return (stat.st_mtime_ns, stat.st_size), stat.st_mtime


def _reload_deeplink_config(
    signature: _DeeplinkSignature | None,
    mtime: float | None,
) -> None:
    """Read the declaration file and replace the cache, failing safe on error."""
    global _deeplink_cache, _deeplink_cache_signature
    global _deeplink_source_mtime, _deeplink_loaded_at, _deeplink_load_error
    data: dict = {}
    error: str | None = None
    try:
        with open(_DEEPLINK_CONFIG_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("declaration file must contain a JSON object")
        data = loaded
    except (OSError, ValueError) as exc:
        # A malformed or missing file grants no declarations. That is the safe
        # direction: every book blocks until the file is fixed, rather than
        # continuing to trust a map that no longer matches the file.
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Deep-link declaration config could not be loaded: %s", error)
    _deeplink_cache = data
    _deeplink_cache_signature = signature
    _deeplink_source_mtime = mtime
    _deeplink_loaded_at = datetime.now(UTC)
    _deeplink_load_error = error


def _load_deeplink_config() -> dict:
    """Return the declaration map, reloading when the file signature changes.

    The file is read only on first use and when its mtime/size changes, so a
    declaration edit takes effect on the next gate lookup or health call without
    a process restart. A map injected directly (no ``loaded_at``) is left alone;
    that is the seam tests use to exercise a synthetic declaration set.
    """
    global _deeplink_cache
    signature, mtime = _deeplink_file_signature()
    if _deeplink_cache is None or (
        _deeplink_loaded_at is not None and signature != _deeplink_cache_signature
    ):
        _reload_deeplink_config(signature, mtime)
    return _deeplink_cache if _deeplink_cache is not None else {}


def deeplink_declaration_source() -> dict:
    """Describe the declaration file the gate is currently reading.

    ``stale`` means the loaded map is not the map on disk: the file changed
    since the last successful read, the last read failed, or no file could be
    read at all. ``loaded_at`` and ``source_mtime`` make a restart-free edit
    observable in `/api/health`.
    """
    _load_deeplink_config()
    current_signature, current_mtime = _deeplink_file_signature()
    stale = _deeplink_load_error is not None or current_signature != _deeplink_cache_signature
    return {
        "path": os.path.abspath(_DEEPLINK_CONFIG_PATH),
        "loaded_at": _deeplink_loaded_at.isoformat() if _deeplink_loaded_at else None,
        "source_mtime": _deeplink_source_mtime,
        "current_mtime": current_mtime,
        "source_size": _deeplink_cache_signature[1] if _deeplink_cache_signature else None,
        "stale": stale,
        "error": _deeplink_load_error,
    }


def _declared_config(bookmaker: str) -> dict:
    """Return a bookmaker's declaration, or an empty mapping when it is absent."""
    value = _load_deeplink_config().get(bookmaker)
    return value if isinstance(value, dict) else {}


def declares_route_pattern_verified(bookmaker: str) -> bool:
    """Whether the book's per-event route pattern has a dated browser proof.

    The route embeds the book's own event id. A sampled browser check proves the
    pattern serves the event for that id; the feed then supplies the id for every
    listing. This is the industry norm for path-based bookmaker routes and is
    recorded with a date and a sample in ``config/bookmaker_deeplinks.json``.
    """
    return _declared_config(bookmaker).get("route_pattern_verified") is True


def supports_event_id(bookmaker: str) -> bool:
    """Return whether a bookmaker declares a per-event deep-link route.

    A book that declares ``supports_event_id: false`` has no per-event route by
    definition, so a link check for it is meaningless: it must be reported as
    "no declared event route", never as a failure. Undeclared books are treated
    the same way — the route is unknown, which is not the same as proven.
    """
    return _declared_config(bookmaker).get("supports_event_id") is True


def declares_no_event_id(bookmaker: str) -> bool:
    """Return whether a bookmaker explicitly declares ``supports_event_id: false``.

    Only the boolean ``False`` counts, and that strictness is the point: the
    certainty gate accepts this declaration as proof that there is no per-event
    link to prove, so a missing key, a typo, a quoted ``"false"`` or a config file
    that failed to load must all answer False here and leave the book blocking.
    ``supports_event_id`` cannot be used for the question — it answers False for
    a declaration that is absent, which is the opposite of what the gate needs to
    tell apart.
    """
    return _declared_config(bookmaker).get("supports_event_id") is False


class LinkSettlement(NamedTuple):
    """Whether one listing's per-event link is settled, and the reason.

    ``reason`` is the gate's evidence vocabulary: ``verified_link``,
    ``route_pattern_verified`` and ``no_event_link`` settle a link, while
    ``link_unverified`` and ``no_event_link`` (the silent case) block it.
    """

    settled: bool
    reason: str


def settle_link(
    bookmaker: str,
    *,
    event_id: str | None = None,
    url: str = "",
    proof: bool = False,
) -> LinkSettlement:
    """Decide whether a listing's per-event link is settled, and why.

    One answer for the gate, the cache restore and the dashboard counter: they
    used to each spell out the same four cases and could drift apart, which is
    exactly how a restore resurrects a `verified` group the gate would refuse.

    ``proof`` is the caller's evidence that this exact link was browser-checked.
    The gate passes the match's ``deep_link_verified`` flag, which
    `_apply_deep_link_verifications` set from the store during the scan; a cache
    restore passes a FRESH entry it read from the store itself, never the cached
    flag, because a stored flag is a snapshot that outlives its proof.

    The rest, in the gate's order:

    1. A proof settles the link, whatever the declarations say.
    2. A dated route-pattern proof plus an event id settles a path-based route.
    3. ``supports_event_id: false`` settles it: the book declares there is no
       per-event link to prove, so the declaration is the proof.
    4. Anything else is open. A declared route, a captured id or a captured URL
       is ``link_unverified``; complete silence is ``no_event_link``. Both
       block: silence is not proof of absence.
    """
    normalized_event_id = "" if event_id is None else str(event_id)
    if proof:
        return LinkSettlement(True, "verified_link")
    if declares_route_pattern_verified(bookmaker) and normalized_event_id:
        return LinkSettlement(True, "route_pattern_verified")
    if declares_no_event_id(bookmaker):
        return LinkSettlement(True, "no_event_link")
    if supports_event_id(bookmaker) or normalized_event_id or url:
        return LinkSettlement(False, "link_unverified")
    return LinkSettlement(False, "no_event_link")


def declaration_verified_at(bookmaker: str) -> str:
    """The date the declaration was last manually checked, or ``""``."""
    raw = _declared_config(bookmaker).get("verified_at")
    return raw if isinstance(raw, str) else ""


def declaration_audit(
    bookmakers: Iterable[str],
    max_age_days: int,
    *,
    today: date | None = None,
) -> list[dict]:
    """Return one dated row per book, marking stale or undated declarations.

    Missing or malformed dates are stale, not silently exempt: a declaration
    with no date is exactly the trust assumption this audit exists to expose.
    """
    now = today or datetime.now(UTC).date()
    rows: list[dict] = []
    for bookmaker in bookmakers:
        raw = declaration_verified_at(bookmaker)
        try:
            checked = date.fromisoformat(raw)
        except ValueError:
            checked = None
        age_days = (now - checked).days if checked is not None else None
        rows.append(
            {
                "bookmaker": bookmaker,
                "verified_at": raw,
                "age_days": age_days,
                "max_age_days": max_age_days,
                "stale": age_days is None or age_days > max_age_days,
            }
        )
    return rows


def effective_deeplink_declarations(bookmakers: Iterable[str] | None = None) -> dict:
    """Return the declaration each book's link question is actually answered by.

    Built from the same cached config the certainty gate reads, so it reports
    what the gate is *using* rather than what the file on disk says. A file edit
    is picked up when its mtime/size changes, and the ``stale``/``loaded_at``
    fields say whether the map in force still matches the file.

    ``bookmakers`` defaults to the keys of the loaded config. A book the config
    holds but the caller did not ask about is added anyway: a caller that names
    some books and silently loses a configured one is the mistake worth surfacing.

    Each entry carries the declaration fields plus the provenance of the file
    the map came from:

    * ``loaded_at`` — when the current map was read (ISO UTC, or ``None`` for a
      synthetic map injected without a file load).
    * ``source_mtime`` — the declaration file's mtime at that read, in epoch
      seconds.
    * ``stale`` — whether the map in force differs from the file on disk (the
      file changed, or the last read failed). A stale map is still the map the
      gate uses; the flag makes the restart-free reload visible.
    * ``configured`` — whether the config holds a declaration for this book at
      all. It is the only field that can distinguish "declares no per-event
      route" from "declares nothing", and those two land on opposite sides of the
      gate.
    * ``supports_event_id`` — the declared boolean, or ``None`` when the book is
      unconfigured or its value is not a boolean. This is the same answer
      :func:`supports_event_id` gives, spelled so ``false`` survives.
    * ``declared_no_event_id`` — the gate's own predicate, and the field to read
      for anything about what blocks. ``None`` is deliberately not available here:
      a book that declares neither value answers False and still blocks, so this
      field is a real two-state answer.

    A caller wanting a plain ``{book: bool}`` map should read
    ``supports_event_id`` out of this; a caller asking what can still block must
    read ``declared_no_event_id``, because the two disagree for every book that
    declares nothing.
    """
    config = _load_deeplink_config()
    source = deeplink_declaration_source()
    names = list(bookmakers) if bookmakers is not None else list(config)
    for name in config:
        if name not in names:
            names.append(name)
    result: dict = {}
    for name in names:
        declared = config.get(name)
        raw = declared.get("supports_event_id") if isinstance(declared, dict) else None
        result[name] = {
            "loaded_at": source["loaded_at"],
            "source_mtime": source["source_mtime"],
            "stale": source["stale"],
            "configured": isinstance(declared, dict),
            # `isinstance(raw, bool)` and not `raw is True`, because the
            # declared-false case has to come back as False: mapping it to None
            # would report a book that plainly says `false` as one that says
            # nothing, which is the one distinction this map exists to make.
            "supports_event_id": raw if isinstance(raw, bool) else None,
            "declared_no_event_id": raw is False,
        }
    return result


def _base_url(base_url: str) -> str:
    """Return a normalized non-event URL for a book's base site."""
    return f"{base_url.rstrip('/')}/"


def _fallback_url(bookmaker: str, base_url: str) -> str:
    """Return the declared non-event fallback, or the normalized site base."""
    cfg = _declared_config(bookmaker)
    fallback = cfg.get("fallback")
    return fallback if isinstance(fallback, str) and fallback else _base_url(base_url)


def _event_template(bookmaker: str, live: bool) -> str:
    """Return the event template for a mode, or an empty string when none exists."""
    cfg = _declared_config(bookmaker)
    key = "template_live" if live else "template"
    template = cfg.get(key)
    if template is None and live:
        return ""
    if not isinstance(template, str) or not template:
        raise ValueError(f"Deep-link config for {bookmaker} is missing {key}")
    if "{event_id}" not in template:
        raise ValueError(
            f"Deep-link config for {bookmaker} must contain an event_id placeholder"
        )
    return template


def build_event_url(
    bookmaker: str,
    event_id: str | None,
    base_url: str,
    live: bool = False,
) -> str:
    """Build a declared per-event URL, or a non-event fallback when unavailable."""
    cfg = _declared_config(bookmaker)
    normalized_event_id = "" if event_id is None else str(event_id)
    if not cfg.get("supports_event_id"):
        template = (cfg.get("template_live") if live else None) or cfg.get("template")
        return template if isinstance(template, str) and template else _base_url(base_url)
    if not normalized_event_id:
        return _fallback_url(bookmaker, base_url)

    template = _event_template(bookmaker, live)
    if not template:
        return _fallback_url(bookmaker, base_url)
    encoded_event_id = quote(normalized_event_id, safe="")
    try:
        return template.format(event_id=encoded_event_id)
    except (IndexError, KeyError, ValueError) as exc:
        raise ValueError(
            f"Invalid deep-link template for {bookmaker}: {template!r}"
        ) from exc
