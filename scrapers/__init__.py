"""Scraper package.

Each scraper is loaded on first use (PEP 562) so importing ``scrapers.common``
does not import every book's scraper or Playwright.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scrapers.admiralbet import AdmiralbetScraper
    from scrapers.betole import BetoleScraper
    from scrapers.evlbet import EvlbetScraper
    from scrapers.maxbet import MaxBetScraper
    from scrapers.mbet import MBetScraper
    from scrapers.mdshop import MDShopScraper
    from scrapers.mozzartbet import MozzartbetScraper
    from scrapers.sportplus import SportPlusScraper

__all__ = [
    "MozzartbetScraper",
    "MDShopScraper",
    "AdmiralbetScraper",
    "BetoleScraper",
    "MBetScraper",
    "SportPlusScraper",
    "EvlbetScraper",
    "MaxBetScraper",
]

_EXPORTS = {
    "MozzartbetScraper": "scrapers.mozzartbet",
    "MDShopScraper": "scrapers.mdshop",
    "AdmiralbetScraper": "scrapers.admiralbet",
    "BetoleScraper": "scrapers.betole",
    "MBetScraper": "scrapers.mbet",
    "SportPlusScraper": "scrapers.sportplus",
    "EvlbetScraper": "scrapers.evlbet",
    "MaxBetScraper": "scrapers.maxbet",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
