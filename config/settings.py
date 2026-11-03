import os

from dotenv import load_dotenv

load_dotenv()

# --- Bookmaker Configuration ---
BOOKMAKERS = {
    "mozzartbet": {
        "name": "Mozzartbet",
        "base_url": "https://www.mozzartbet.ba",
        "soccer_url": "https://www.mozzartbet.ba/sr/kladjenje",
        "enabled": True,
        "color": "#FF6B00",
    },
    "mdshop": {
        "name": "MDShop",
        "base_url": "https://www.mdshop.ba",
        "soccer_url": "https://www.mdshop.ba/sport-prematch?sport=Fudbal",
        "enabled": True,
        "color": "#1B5E20",
    },
    "admiralbet": {
        "name": "Admiralbet",
        "base_url": "https://www.admiralbet.ba",
        "soccer_url": "https://www.admiralbet.ba/sport-prematch?sport=Fudbal",
        "enabled": True,
        "color": "#0D47A1",
    },
    "betole": {
        "name": "Betole",
        "base_url": "https://www.betole.ba",
        "soccer_url": "https://www.betole.ba",
        "enabled": True,
        "color": "#B71C1C",
    },
    "mbet": {
        "name": "MBet",
        "base_url": "https://www.mbet.ba",
        "soccer_url": "https://www.mbet.ba",
        "enabled": True,
        "color": "#E91E63",
    },
    "sportplus": {
        "name": "SportPlus",
        "base_url": "https://www.sportplus.ba",
        "soccer_url": "https://www.sportplus.ba/prematch/betting",
        "enabled": True,
        "color": "#FF5722",
    },
    "evlbet": {
        "name": "EVLBet",
        "base_url": "https://evlbet.com",
        "soccer_url": "https://evlbet.com",
        # Off since 2026-10-20: its offer API returns no football events for any
        # request variant tried, and no payload has ever been captured, so its
        # market mapping is untested. Re-enable only with a captured fixture.
        "enabled": False,
        "color": "#9C27B0",
    },
    "premier_kladionica": {
        "name": "Premier Kladionica",
        "base_url": "https://www.premier-kladionica.com",
        "soccer_url": "https://www.premier-kladionica.com/ponuda/",
        "enabled": True,
        "color": "#16A34A",
    },
    "wwin": {
        "name": "WWIN",
        "base_url": "https://wwin.ba",
        "soccer_url": "https://wwin.ba/kladjenje/",
        "enabled": True,
        "color": "#EF4444",
    },
    "maxbet": {
        "name": "MaxBet",
        "base_url": "https://www.maxbet.ba",
        "soccer_url": "https://sportsbook.maxbet.ba/sport/1",
        # Added 2026-10-27. It declares a per-event route, so its groups stay
        # unverified until scripts/verify_deeplinks.py proves its links.
        "enabled": True,
        "color": "#0F766E",
    },
}

# --- Market Configuration ---
ENABLED_MARKETS = [
    "1x2",
    "over_under_1_5",
    "over_under_2_5",
    "over_under_3_5",
    "btts",
    "double_chance",
    # Proven on the 2026-11-03 real scan: 1,875 first-half 1X2 rows and 1,368
    # Asian-handicap rows, 0 price outliers across 4,374 comparisons.
    "first_half_1x2",
    "asian_handicap",
]

# Experimental markets — OFF by default, toggleable from the dashboard checkbox.
# They are parsed and detected only while enabled (persisted per-scan via the
# server's market_state.json toggle). Add new markets here instead of
# ENABLED_MARKETS until they have proven live against real payloads.
EXPERIMENTAL_MARKETS = [
    "first_half_ou",
]

# --- Arbitrage Settings ---
MIN_PROFIT_PERCENT = 0.5       # Minimum profit % to show as surebet
DUST_PROFIT_PERCENT = 0.2      # Lower bound for "dust" (low-value) surebets shown in separate tab
DEFAULT_INVESTMENT = 100.0     # Default total investment (BAM/KM)
EXPIRY_BUFFER_MINUTES = 15     # Grace period (min) before treating a match as expired
# Books that run on one odds feed quote identical prices, so a bet at one and a
# bet at the other is not two independent prices: the engine takes at most one
# leg per price source. MDShop and Admiralbet are both NSoft (see MARKET_MAPPING.md).
PRICE_SOURCES = {"mdshop": "nsoft", "admiralbet": "nsoft"}


def price_source(bookmaker: str) -> str:
    return PRICE_SOURCES.get(bookmaker, bookmaker)


MAX_SUREBET_PROFIT_PERCENT = 20.0  # Sanity cap — reject higher profits (likely scraper/data errors)
ODDS_TTL_SECONDS = 600         # Max age of odds before considered stale (prematch 10 min, live 60s enforced in engine)

# --- Scraper Settings ---
NAVIGATION_TIMEOUT_MS = 60000  # Max navigation time (ms)
# Headless browsers by default; set HEADLESS=false in .env to watch them
# (e.g. to solve a CAPTCHA by hand).
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() not in ("0", "false", "no")
# Verify TLS certificates on direct httpx API calls (set VERIFY_SSL=true in .env to enforce)
VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() in ("1", "true", "yes")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# --- Matching Settings ---
KICKOFF_WINDOW_MINUTES = 120   # Max kickoff time diff (minutes) to consider same match — HARD gate
VERIFIED_KICKOFF_WINDOW_MINUTES = 15  # Max kickoff delta for a `verified` group
FUZZY_MATCH_THRESHOLD = 80     # Min similarity score (0-100) for a team pairing to group (overall confidence)
TEAM_MATCH_MIN_PERCENT = 70    # Min similarity (0-100) required for EACH team in a pairing
BROWSER_CONCURRENCY = 3        # Max concurrent Playwright browsers (one per browser bookmaker)

# --- Server Settings ---
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
# Comma-separated allowed origins. Empty means same-origin only (the dashboard
# is served by this process); set it only when a separate frontend needs access.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
# Optional API key — when set, POST /api/scan, /api/config/toggle, /api/recalculate,
# /api/verify and GET /api/history require an `X-API-Key` header.
API_KEY = os.getenv("API_KEY", "")
# Max scan triggers per minute per client IP (0 disables the limit)
SCAN_RATE_LIMIT = int(os.getenv("SCAN_RATE_LIMIT", "3"))
# Scheduled scans (0 = off). Prematch is the production feed; live is deferred.
AUTO_SCAN_PREMATCH_MINUTES = int(os.getenv("AUTO_SCAN_PREMATCH_MINUTES", "0"))
AUTO_SCAN_LIVE_MINUTES = int(os.getenv("AUTO_SCAN_LIVE_MINUTES", "0"))
# Learn team/league/market claims from each real scan before matching. Tiny
# scans (tests, a two-book smoke run) are ignored so they cannot rewrite the
# shipped ledger.
AUTO_LEARN_MAPPINGS = os.getenv("AUTO_LEARN_MAPPINGS", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MIN_LEARN_MATCHES = int(os.getenv("MIN_LEARN_MATCHES", "50"))
# Drop a surebet whose leg is a price outlier against the other books.
PRICE_GUARD_ENABLED = os.getenv("PRICE_GUARD_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Scheduled scans skip a book after this many consecutive empty/error runs, with
# exponential backoff capped at BOOK_BACKOFF_MAX_MINUTES. Manual scans ignore it.
BOOK_BACKOFF_AFTER_FAILURES = int(os.getenv("BOOK_BACKOFF_AFTER_FAILURES", "3"))
BOOK_BACKOFF_MAX_MINUTES = int(os.getenv("BOOK_BACKOFF_MAX_MINUTES", "60"))
# Max on-demand deep-link checks per minute per client IP (0 disables the limit).
# A check drives a real browser against a bookmaker's site for seconds per event,
# and API_KEY is empty by default, so the endpoint throttles itself: a lock only
# serialises runs, it does not refuse them.
DEEP_LINK_VERIFY_RATE_LIMIT = int(os.getenv("DEEP_LINK_VERIFY_RATE_LIMIT", "2"))
# Sliding window shared by every per-client-IP rate limit, so tuning one endpoint
# cannot silently move another's. It is NOT a per-endpoint knob.
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# --- Cache ---
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

# --- Match page URL templates (best-effort; scrapers may override with real per-match URLs) ---
MATCH_URL_TEMPLATES: dict[str, str] = {
    "mozzartbet": "https://www.mozzartbet.ba/sr/kladjenje/sport/1",
    "mdshop": "https://www.mdshop.ba/sport-prematch?sport=Fudbal",
    "admiralbet": "https://www.admiralbet.ba/sport-prematch?sport=Fudbal",
    "betole": "https://www.betole.ba/ba/sport/S",
    "mbet": "https://www.mbet.ba/",
    "sportplus": "https://www.sportplus.ba/prematch/betting",
    "evlbet": "https://evlbet.com/",
    "premier_kladionica": "https://www.premier-kladionica.com/ponuda/",
    "wwin": "https://wwin.ba/kladjenje/",
    "maxbet": "https://sportsbook.maxbet.ba/sport/1",
}
