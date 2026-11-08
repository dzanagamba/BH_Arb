"""The adapter contract every bookmaker scraper implements (SR6-2).

``config.bookmakers`` declares each adapter as a module and class name, because
``scrapers.registry`` imports the module lazily; mypy cannot see through those
strings. ``BookAdapter`` is the shape those classes must have, so the registry
can type a resolved class as ``AdapterClass`` and mypy checks the ``scrape()``
call sites (and a deliberately broken adapter in the suite) against it.

The signature is the widest one the scan uses: ``run_scan`` passes all three
keywords. An adapter that has no use for ``sports_wanted`` still accepts it and
ignores it, exactly as the old ``TypeError`` fallback in ``server/api.py`` made
it run before this module existed, so no feed asks for fewer events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeAlias, runtime_checkable

from models.schemas import Match


@runtime_checkable
class BookAdapter(Protocol):
    """One bookmaker's scraper: no-argument construction, async ``scrape()``."""

    def __init__(self) -> None: ...

    async def scrape(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]: ...


#: What ``scrapers.registry`` resolves a declaration to.
AdapterClass: TypeAlias = type[BookAdapter]


__all__ = ["AdapterClass", "BookAdapter"]
