"""Engine package.

The re-exported classes are loaded on first use (PEP 562) so importing
``engine`` does not pull in the matcher, the scrapers or Playwright.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.arbitrage import ArbitrageEngine
    from engine.matcher import MatchMatcher
    from engine.normalizer import TeamNormalizer

__all__ = ["TeamNormalizer", "MatchMatcher", "ArbitrageEngine"]

_EXPORTS = {
    "ArbitrageEngine": "engine.arbitrage",
    "MatchMatcher": "engine.matcher",
    "TeamNormalizer": "engine.normalizer",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
