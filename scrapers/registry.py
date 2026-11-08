"""Lazy adapter registry derived from the single bookmaker declaration (SR6-1).

``config.bookmakers.DECLARATIONS`` names each adapter's module and class as
strings. This registry resolves them on first access, so importing the server,
a probe script or this module does not import ten scraper modules (or
Playwright). It is a ``MutableMapping`` so tests can still substitute a fake
class with ``monkeypatch.setitem``.

The registry deliberately does not define its own list of books: keys come from
the declaration, and an unknown key raises ``KeyError`` exactly like the old
hand-written dict.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator, MutableMapping
from typing import Any, cast

from config.bookmakers import DECLARATIONS, AdapterDeclaration
from scrapers.protocol import AdapterClass


class ScraperRegistry(MutableMapping[str, Any]):
    """``bookmaker -> adapter class``, imported only when read."""

    def __init__(self, declarations: dict[str, AdapterDeclaration] | None = None):
        self._declarations = dict(declarations or DECLARATIONS)
        self._loaded: dict[str, Any] = {}
        # Test substitution target; never used by production reads unless a
        # test explicitly sets it.
        self._overrides: dict[str, Any] = {}

    def __getitem__(self, bookmaker: str) -> AdapterClass:
        if bookmaker in self._overrides:
            return cast("AdapterClass", self._overrides[bookmaker])
        if bookmaker in self._loaded:
            return cast("AdapterClass", self._loaded[bookmaker])
        try:
            spec = self._declarations[bookmaker]
        except KeyError:
            raise KeyError(bookmaker) from None
        module = importlib.import_module(spec.module)
        adapter = getattr(module, spec.class_name)
        self._loaded[bookmaker] = adapter
        return cast("AdapterClass", adapter)

    def __setitem__(self, bookmaker: str, adapter: Any) -> None:
        self._overrides[bookmaker] = adapter

    def __delitem__(self, bookmaker: str) -> None:
        try:
            del self._overrides[bookmaker]
        except KeyError:
            raise KeyError(bookmaker) from None

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for bookmaker in self._declarations:
            seen.add(bookmaker)
            yield bookmaker
        for bookmaker in self._overrides:
            if bookmaker not in seen:
                yield bookmaker

    def __len__(self) -> int:
        return len(set(self._declarations) | set(self._overrides))

    def __contains__(self, bookmaker: object) -> bool:
        return bookmaker in self._overrides or bookmaker in self._declarations

    def declaration(self, bookmaker: str) -> AdapterDeclaration:
        """The declaration for a book; ``KeyError`` when it is unknown."""
        return self._declarations[bookmaker]

    def adapter(self, bookmaker: str) -> AdapterClass | None:
        """The declared adapter class, typed against ``BookAdapter`` (SR6-2).

        ``None`` for an unknown book, exactly like ``dict.get``; a known book
        resolves (and caches) its class on first read. Production call sites use
        this rather than ``get()`` so mypy checks ``scrape()`` against the
        protocol instead of ``Any``.
        """
        if bookmaker not in self:
            return None
        return self[bookmaker]

    @property
    def declared(self) -> frozenset[str]:
        """The declared book ids, without importing any adapter."""
        return frozenset(self._declarations)


# The process-wide map the scan, canary and probe scripts read. Keys match
# ``settings.BOOKMAKERS`` because both come from the same declaration.
SCRAPERS: ScraperRegistry = ScraperRegistry()


__all__ = ["SCRAPERS", "ScraperRegistry"]
