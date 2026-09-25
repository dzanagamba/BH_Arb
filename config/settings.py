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
        "enabled": False,
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
        "enabled": True,
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
}

# --- Market Configuration ---
ENABLED_MARKETS = [
    "1x2",
    "over_under_1_5",
    "over_under_2_5",
    "over_under_3_5",
    "btts",
    "double_chance",
]

# Experimental markets — OFF by default, toggleable from the dashboard checkbox.
# They are parsed and detected only while enabled (persisted per-scan via the
# server's market_state.json toggle). Add new markets here instead of
# ENABLED_MARKETS until they have proven live against real payloads.
EXPERIMENTAL_MARKETS = [
    "first_half_1x2",
    "first_half_ou",
    "asian_handicap",
]

# --- Arbitrage Settings ---
MIN_PROFIT_PERCENT = 0.5       # Minimum profit % to show as surebet
DUST_PROFIT_PERCENT = 0.2      # Lower bound for "dust" (low-value) surebets shown in separate tab
DEFAULT_INVESTMENT = 100.0     # Default total investment (BAM/KM)
EXPIRY_BUFFER_MINUTES = 15     # Grace period (min) before treating a match as expired
MAX_SUREBET_PROFIT_PERCENT = 20.0  # Sanity cap — reject higher profits (likely scraper/data errors)
ODDS_TTL_SECONDS = 600         # Max age of odds before considered stale (prematch 10 min, live 60s enforced in engine)

# --- Scraper Settings ---
SCRAPE_TIMEOUT_MS = 30000      # Max time to wait for JSON payloads (ms)
NAVIGATION_TIMEOUT_MS = 60000  # Max navigation time (ms)
# Set True for headless browser execution
HEADLESS = True
SLOW_MO = 0
# Verify TLS certificates on direct httpx API calls (set VERIFY_SSL=true in .env to enforce)
VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() in ("1", "true", "yes")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
BLOCKED_URL_FRAGMENTS = [
    "google-analytics", "facebook", "doubleclick", "adsystem",
    "hotjar", "sentry", "intercom", "crisp", "zendesk",
    "livechat", "analytics", "tracking", "telemetry",
    "casino", "slots", "poker", "jackpot", "virtual"
]


# --- Matching Settings ---
KICKOFF_WINDOW_MINUTES = 120   # Max kickoff time diff (minutes) to consider same match — HARD gate
VERIFIED_KICKOFF_WINDOW_MINUTES = 15  # Max kickoff delta for a `verified` group
FUZZY_MATCH_THRESHOLD = 80     # Min similarity score (0-100) for a team pairing to group (overall confidence)
TEAM_MATCH_MIN_PERCENT = 70    # Min similarity (0-100) required for EACH team in a pairing
BROWSER_CONCURRENCY = 2        # Max concurrent Playwright browsers (P2)

# --- Server Settings ---
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
# Optional API key — when set, POST /api/scan, /api/config/toggle, /api/recalculate,
# /api/verify and GET /api/history require an `X-API-Key` header.
API_KEY = os.getenv("API_KEY", "")
# Max scan triggers per minute per client IP (0 disables the limit)
SCAN_RATE_LIMIT = int(os.getenv("SCAN_RATE_LIMIT", "3"))

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
}
