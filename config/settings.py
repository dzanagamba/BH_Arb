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
    # First-half 1X2 and Asian handicap were proven on the 2026-11-03 real
    # scan (1,875 and 1,368 rows, 0 outliers across 4,374 comparisons).
    # First-half O/U is enabled but had no offer in that scan; the price guard
    # still applies if a book starts publishing it.
    "first_half_1x2",
    "first_half_ou",
    "asian_handicap",
    # Admitted 2026-11-04 from measured label/structure classification and
    # cross-book price consensus (docs/MULTISPORT_EVIDENCE.md). The 0.5/4.5/5.5
    # lines are complete two-way partitions and price with the same math.
    "over_under_0_5",
    "over_under_4_5",
    "over_under_5_5",
    # Non-football families. Sport identity on the group prevents any pairing
    # across sports; these names only describe the market shape.
    "moneyline",
    "moneyline_3way",
    "handicap",
    "total",
]

# Which sports the scan parses. Football is the original path and must stay
# first; the rest are admitted only by the measurement in
# scripts/measure_sports.py (three books, three comparable markets).
ENABLED_SPORTS: list[str] = ["football", "basketball", "tennis"]

# Experimental markets — OFF by default, toggleable from the dashboard checkbox.
# They are parsed and detected only while enabled (persisted per-scan via the
# server's market_state.json toggle). Add new markets here instead of
# ENABLED_MARKETS until they have proven live against real payloads.
EXPERIMENTAL_MARKETS: list[str] = []

# --- Arbitrage Settings ---
MIN_PROFIT_PERCENT = 0.5       # Minimum profit % to show as surebet
DUST_PROFIT_PERCENT = 0.2      # Lower bound for "dust" (low-value) surebets shown in separate tab
DEFAULT_INVESTMENT = 100.0     # Default total investment (BAM/KM)
EXPIRY_BUFFER_MINUTES = 15     # Grace period (min) before treating a match as expired
PREMATCH_EXPIRY_BUFFER_MINUTES = 2  # Clock tolerance after the latest member kickoff
# Books that run on one odds feed quote identical prices, so a bet at one and a
# bet at the other is not two independent prices: the engine takes at most one
# leg per price source. MDShop and Admiralbet are both NSoft (see MARKET_MAPPING.md).
PRICE_SOURCES = {"mdshop": "nsoft", "admiralbet": "nsoft"}


def price_source(bookmaker: str) -> str:
    return PRICE_SOURCES.get(bookmaker, bookmaker)


MAX_SUREBET_PROFIT_PERCENT = 20.0  # Sanity cap — reject higher profits (likely scraper/data errors)
# A two-source edge above this is treated as a stale price, not a gift. Real
# reachable arbitrage is usually 1–5%; research on stale lines puts the
# suspicious band above 5% and the book-error band far higher. Three or more
# independent sources can still show a large edge because the median test has
# something to compare against.
MAX_TWO_SOURCE_PROFIT_PERCENT = 10.0
# Freshness policy, shared by the pricing engine and the API/dashboard. A scan
# is current only while every leg it serves is inside its feed's budget. Live
# prices move far faster than prematch, so the live budget is deliberately tight.
ODDS_TTL_SECONDS = 600         # Prematch: max age of odds before considered stale (10 min)
LIVE_ODDS_TTL_SECONDS = 60     # Live: in-play odds expire after one minute

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

# --- Feed integrity (P0-7) ---
# A book is quarantined from pricing when its feed cannot be trusted for this
# scan. Recovery is deliberately slower than failure: a book must produce this
# many consecutive clean scans before it is priced again.
FEED_INTEGRITY_RECOVERY_SCANS = int(os.getenv("FEED_INTEGRITY_RECOVERY_SCANS", "3"))
FEED_INTEGRITY_HISTORY = int(os.getenv("FEED_INTEGRITY_HISTORY", "20"))
FEED_INTEGRITY_MISSING_DEGRADED_RATE = 0.35
FEED_INTEGRITY_OUTLIER_DEGRADED_RATE = 0.10
FEED_INTEGRITY_OUTLIER_QUARANTINE_RATE = 0.25

# --- Cache ---
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
# P0-1 guard: a nine-book scan cache was 218 MB because every allowlisted team
# evidence record carried the whole alias allowlist. With only the proving
# entries the same scan is tens of MB. Exceeding this budget means the payload
# regressed, not that the feed grew, so `/api/health` and the cache writer both
# report it.
CACHE_SIZE_BUDGET_BYTES = int(os.getenv("CACHE_SIZE_BUDGET_BYTES", str(40 * 1024 * 1024)))

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
