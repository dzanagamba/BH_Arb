"""One declaration per bookmaker (SR6-1).

Before this module, adding a book meant editing several hand-kept lists:
``settings.BOOKMAKERS``, the ``SCRAPERS`` dict in ``server/api.py``, the
``PLAYWRIGHT_BOOKIES`` set, the timeout table in ``scrapers/transport.py`` and
the market registry. Missing one produced ``no scraper registered`` at run time
instead of a failing test.

This is now the single per-book declaration: name and UI fields, the adapter
module and class (as strings, so nothing is imported until a scan uses the
book), the transport (``http`` or the shared Playwright browser), the default
enabled flag and the per-feed HTTP timeouts. ``config.settings.BOOKMAKERS``, the
lazy ``scrapers.registry.SCRAPERS`` map, ``PLAYWRIGHT_BOOKIES`` and
``scrapers.transport.POLICIES`` are all derived from it.

Keep this module dependency-free on purpose: it is imported by
``config.settings`` and by every test that needs the book list. The adapter
class names are strings; ``scrapers.registry`` imports them lazily.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Transport = Literal["http", "browser"]


@dataclass(frozen=True)
class AdapterDeclaration:
    """Everything the rest of the app needs to know about one bookmaker."""

    bookmaker: str
    name: str
    # Import path and class name; resolved lazily by scrapers.registry.
    module: str
    class_name: str
    transport: Transport
    enabled: bool
    base_url: str
    soccer_url: str
    color: str
    # One cap per feed; the shared TransportPolicy applies it to every phase.
    timeouts: dict[str, float] = field(default_factory=dict, repr=False)


DECLARATIONS: dict[str, AdapterDeclaration] = {
    "mozzartbet": AdapterDeclaration(
        bookmaker="mozzartbet",
        name="Mozzartbet",
        module="scrapers.mozzartbet",
        class_name="MozzartbetScraper",
        transport="browser",
        enabled=True,
        base_url="https://www.mozzartbet.ba",
        soccer_url="https://www.mozzartbet.ba/sr/kladjenje",
        color="#FF6B00",
        timeouts={"prematch": 30.0, "live": 30.0},
    ),
    "mdshop": AdapterDeclaration(
        bookmaker="mdshop",
        name="MDShop",
        module="scrapers.mdshop",
        class_name="MDShopScraper",
        transport="http",
        enabled=True,
        base_url="https://www.mdshop.ba",
        soccer_url="https://www.mdshop.ba/sport-prematch?sport=Fudbal",
        color="#1B5E20",
        timeouts={"prematch": 30.0, "live": 30.0},
    ),
    "admiralbet": AdapterDeclaration(
        bookmaker="admiralbet",
        name="Admiralbet",
        module="scrapers.admiralbet",
        class_name="AdmiralbetScraper",
        transport="browser",
        enabled=True,
        base_url="https://www.admiralbet.ba",
        soccer_url="https://www.admiralbet.ba/sport-prematch?sport=Fudbal",
        color="#0D47A1",
        timeouts={"prematch": 30.0, "live": 30.0},
    ),
    "betole": AdapterDeclaration(
        bookmaker="betole",
        name="Betole",
        module="scrapers.betole",
        class_name="BetoleScraper",
        transport="http",
        enabled=True,
        base_url="https://www.betole.ba",
        soccer_url="https://www.betole.ba",
        color="#B71C1C",
        timeouts={"prematch": 30.0, "live": 30.0},
    ),
    "mbet": AdapterDeclaration(
        bookmaker="mbet",
        name="MBet",
        module="scrapers.mbet",
        class_name="MBetScraper",
        transport="http",
        enabled=True,
        base_url="https://www.mbet.ba",
        soccer_url="https://www.mbet.ba",
        color="#E91E63",
        timeouts={"prematch": 30.0, "live": 30.0},
    ),
    "sportplus": AdapterDeclaration(
        bookmaker="sportplus",
        name="SportPlus",
        module="scrapers.sportplus",
        class_name="SportPlusScraper",
        transport="http",
        enabled=True,
        base_url="https://www.sportplus.ba",
        soccer_url="https://www.sportplus.ba/prematch/betting",
        color="#FF5722",
        # Its prematch feed has always used a wider cap than live.
        timeouts={"prematch": 120.0, "live": 60.0},
    ),
    "evlbet": AdapterDeclaration(
        bookmaker="evlbet",
        name="EVLBet",
        module="scrapers.evlbet",
        class_name="EvlbetScraper",
        transport="http",
        # Off since 2026-10-20: its offer API returns no football events for any
        # request variant tried, and no payload has ever been captured, so its
        # market mapping is untested. Re-enable only with a captured fixture.
        enabled=False,
        base_url="https://evlbet.com",
        soccer_url="https://evlbet.com",
        color="#9C27B0",
        timeouts={"prematch": 20.0, "live": 20.0},
    ),
    "premier_kladionica": AdapterDeclaration(
        bookmaker="premier_kladionica",
        name="Premier Kladionica",
        module="scrapers.premier_kladionica",
        class_name="PremierKladionicaScraper",
        transport="http",
        enabled=True,
        base_url="https://www.premier-kladionica.com",
        soccer_url="https://www.premier-kladionica.com/ponuda/",
        color="#16A34A",
        timeouts={"prematch": 60.0, "live": 60.0},
    ),
    "wwin": AdapterDeclaration(
        bookmaker="wwin",
        name="WWIN",
        module="scrapers.wwin",
        class_name="WWINScraper",
        transport="browser",
        enabled=True,
        base_url="https://wwin.ba",
        soccer_url="https://wwin.ba/kladjenje/",
        color="#EF4444",
        timeouts={"prematch": 30.0, "live": 30.0},
    ),
    "maxbet": AdapterDeclaration(
        bookmaker="maxbet",
        name="MaxBet",
        module="scrapers.maxbet",
        class_name="MaxBetScraper",
        transport="http",
        enabled=True,
        base_url="https://www.maxbet.ba",
        # Added 2026-10-27. It declares a per-event route, so its groups stay
        # unverified until scripts/verify_deeplinks.py proves its links.
        soccer_url="https://sportsbook.maxbet.ba/sport/1",
        color="#0F766E",
        timeouts={"prematch": 60.0, "live": 60.0},
    ),
}

# Derived view: the books that run through the shared Playwright browser.
BROWSER_BOOKMAKERS: frozenset[str] = frozenset(
    book for book, spec in DECLARATIONS.items() if spec.transport == "browser"
)

# Derived view: the same shape ``settings.BOOKMAKERS`` has always had.
BOOKMAKER_CONFIG: dict[str, dict[str, Any]] = {
    book: {
        "name": spec.name,
        "base_url": spec.base_url,
        "soccer_url": spec.soccer_url,
        "enabled": spec.enabled,
        "color": spec.color,
    }
    for book, spec in DECLARATIONS.items()
}

__all__ = [
    "AdapterDeclaration",
    "BOOKMAKER_CONFIG",
    "BROWSER_BOOKMAKERS",
    "DECLARATIONS",
    "Transport",
]
