"""SR3-4: failure artefacts for browser books.

A browser scrape that fails leaves nothing behind today: the book drops out and
the scan log says only that it failed. This module keeps a Playwright trace and
a screenshot under ``cache/forensics/<book>/<scan_id>/`` when a browser session
raises, and prunes that directory by age and total size.

What is deliberately absent: no ``storage_state``, no cookies and no
``browser.new_context(storage_state=...)`` call, so an artefact can never carry
a live session. Tracing snapshots are DOM snapshots, not credentials.

Tracing must be started before the failure, so ``begin()`` runs when the
context is created and ``discard()`` stops it without a path on success. The
overhead is the reason ``FORENSICS_ENABLED`` exists: a deployment that does not
want it sets the variable to ``false`` and pays nothing.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import (
    FORENSICS_DIR,
    FORENSICS_ENABLED,
    FORENSICS_MAX_AGE_DAYS,
    FORENSICS_MAX_BYTES,
)
from server.observability import current_scan_id

logger = logging.getLogger(__name__)

_ARTEFACTS: ContextVar[dict[str, str] | None] = ContextVar(
    "bh_forensics_artefacts", default=None
)


def take_artefacts() -> dict[str, str]:
    """Paths captured by the last failure in this task, then clear them."""
    paths = _ARTEFACTS.get() or {}
    _ARTEFACTS.set(None)
    return paths


async def begin(context: Any) -> None:
    """Start tracing for a context that may fail later."""
    if not FORENSICS_ENABLED:
        return
    try:
        await context.tracing.start(screenshots=False, snapshots=True, sources=False)
    except Exception as exc:  # noqa: BLE001 - forensics must never fail a scrape
        logger.warning("forensics tracing did not start: %s", exc)


async def discard(context: Any) -> None:
    """Stop tracing after a successful scrape without keeping the data."""
    if not FORENSICS_ENABLED:
        return
    try:
        await context.tracing.stop()
    except Exception as exc:  # noqa: BLE001 - the scrape already succeeded
        logger.debug("forensics tracing stop failed: %s", exc)


async def capture_failure(
    context: Any,
    page: Any,
    bookmaker: str,
    *,
    root: str | Path | None = None,
    now: float | None = None,
) -> dict[str, str]:
    """Write a screenshot and a trace for a failed browser session.

    Never raises: the scrape is already failing, and a forensics error must not
    replace the real one. Returns the paths that were written.
    """
    if not FORENSICS_ENABLED:
        return {}
    base = Path(root) if root is not None else Path(FORENSICS_DIR)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = base / (bookmaker or "unknown") / f"{current_scan_id()}-{stamp}"
    paths: dict[str, str] = {}
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("forensics directory not created: %s", exc)
        return paths

    if page is not None:
        screenshot = target / "screenshot.png"
        try:
            await page.screenshot(path=str(screenshot))
            paths["screenshot"] = str(screenshot)
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.warning("forensics screenshot failed: %s", exc)

    trace = target / "trace.zip"
    try:
        await context.tracing.stop(path=str(trace))
        paths["trace"] = str(trace)
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("forensics trace failed: %s", exc)

    if paths:
        _ARTEFACTS.set(paths)
        logger.warning(
            "[%s] forensics: %s",
            bookmaker or "unknown",
            ", ".join(f"{name}={path}" for name, path in sorted(paths.items())),
        )
    prune(base, now=now)
    return paths


def prune(
    root: str | Path | None = None,
    *,
    max_bytes: int | None = None,
    max_age_days: int | None = None,
    now: float | None = None,
) -> list[str]:
    """Delete old artefacts, then the oldest files until the size fits.

    Returns the paths removed, so a caller (and a test) can see the decision.
    The newest file is never removed, even when it alone exceeds the budget.
    """
    base = Path(root) if root is not None else Path(FORENSICS_DIR)
    budget = FORENSICS_MAX_BYTES if max_bytes is None else max_bytes
    max_age = FORENSICS_MAX_AGE_DAYS if max_age_days is None else max_age_days
    current = time.time() if now is None else now
    cutoff = current - max_age * 86400

    files: list[tuple[float, int, Path]] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((stat.st_mtime, stat.st_size, path))

    removed: list[str] = []
    for mtime, _size, path in sorted(files):
        if mtime < cutoff:
            try:
                path.unlink()
                removed.append(str(path))
            except OSError:
                continue

    remaining = [
        (mtime, size, path) for mtime, size, path in files if path.exists()
    ]
    total = sum(size for _mtime, size, _path in remaining)
    alive = len(remaining)
    for _mtime, size, path in sorted(remaining):
        if total <= budget or alive <= 1:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        alive -= 1
        removed.append(str(path))
    _prune_empty_dirs(base)
    return removed


def _prune_empty_dirs(base: Path) -> None:
    for directory in sorted(base.rglob("*"), reverse=True):
        if directory.is_dir():
            try:
                next(directory.iterdir())
            except StopIteration:
                directory.rmdir()
            except OSError:
                continue


def artefact_summary(paths: dict[str, str]) -> str:
    """One log-line fragment naming the artefacts (empty when there are none)."""
    if not paths:
        return ""
    return " | forensics: " + ", ".join(f"{name}={value}" for name, value in sorted(paths.items()))


__all__ = [
    "artefact_summary",
    "begin",
    "capture_failure",
    "discard",
    "prune",
    "take_artefacts",
]
