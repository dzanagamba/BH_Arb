"""Scraper package.

Each scraper is loaded on first use (PEP 562) so importing ``scrapers.common``
does not import every book's scraper or Playwright. The exported names are
derived from the single bookmaker declaration (SR6-1), not kept here by hand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from config.bookmakers import DECLARATIONS

_EXPORTS = {
    spec.class_name: spec.module for spec in DECLARATIONS.values()
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
