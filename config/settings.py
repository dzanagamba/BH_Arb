import json
import os
from typing import TypedDict

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

# --- Advisory book risk profiles (P3-6) ---
# Operator guidance only. These fields are read by /api/config and the dashboard;
# the certainty gate, matcher, price-source rule and stake math never import them.
RISK_PROFILE_VALUES = ("sharp", "soft", "exchange", "unknown")
_RISK_PROFILE_FILE = os.path.join(os.path.dirname(__file__), "bookmaker_risk.json")


class BookRiskProfile(TypedDict):
    profile: str
    advisory_max_stake: int
    typical_max_stake_note: str
    limit_risk: str


def _unknown_risk_profile() -> BookRiskProfile:
    return {
        "profile": "unknown",
        "advisory_max_stake": 500,
        "typical_max_stake_note": "No typical stake recorded; check the book's own limits.",
        "limit_risk": "Unknown risk profile: the operator must check the book's limit policy.",
    }


def load_book_risk_profiles(path: str = _RISK_PROFILE_FILE) -> dict[str, BookRiskProfile]:
    """Load advisory profiles, failing safe to `unknown` for a missing/bad file."""
    profiles = {book: _unknown_risk_profile() for book in BOOKMAKERS}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        books = payload.get("books", payload) if isinstance(payload, dict) else {}
        if not isinstance(books, dict):
            return profiles
        for book in BOOKMAKERS:
            entry = books.get(book)
            if not isinstance(entry, dict):
                continue
            raw_profile = entry.get("profile", "unknown")
            profile = raw_profile if raw_profile in RISK_PROFILE_VALUES else "unknown"
            try:
                max_stake = int(entry.get("advisory_max_stake", 500))
            except (TypeError, ValueError):
                max_stake = 500
            profiles[book] = {
                "profile": profile,
                "advisory_max_stake": max(1, max_stake),
                "typical_max_stake_note": str(
                    entry.get("typical_max_stake_note")
                    or "No typical stake recorded; check the book's own limits."
                ),
                "limit_risk": str(
                    entry.get("limit_risk")
                    or "Unknown risk profile: the operator must check the book's limit policy."
                ),
            }
    except (OSError, ValueError, TypeError):
        pass
    return profiles


BOOK_RISK_PROFILES: dict[str, BookRiskProfile] = load_book_risk_profiles()


def book_risk_profile(bookmaker: str) -> BookRiskProfile:
    """Return the advisory profile, or an explicit unknown for an unlisted book."""
    return BOOK_RISK_PROFILES.get(bookmaker, _unknown_risk_profile())


# --- Advisory stake limits (P3-3, sourced from the P3-6 profiles) ---
# A soft, per-book ceiling shown in the slip. It never blocks a scan or a bet;
# the operator can still record whatever was accepted.
BOOK_STAKE_LIMITS: dict[str, int] = {
    book: int(
        os.getenv(
            f"BOOK_MAX_STAKE_{book.upper()}",
            str(book_risk_profile(book)["advisory_max_stake"]),
        )
    )
    for book in BOOKMAKERS
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
# Measured twins are added at runtime by engine.skin_detection after a scan.
# Seeded config stays authoritative; a measured pair only joins books that the
# data proves quote the same prices.
MEASURED_PRICE_SOURCES: dict[str, str] = {}


def register_price_source_twin(left: str, right: str) -> str:
    """Make two books one price source and return the source id."""
    source = f"twin:{'|'.join(sorted((left, right)))}"
    MEASURED_PRICE_SOURCES[left] = source
    MEASURED_PRICE_SOURCES[right] = source
    return source


def reset_measured_price_sources() -> None:
    """Test seam; production registration is append-only for the process."""
    MEASURED_PRICE_SOURCES.clear()


def price_source(bookmaker: str) -> str:
    if bookmaker in MEASURED_PRICE_SOURCES:
        return MEASURED_PRICE_SOURCES[bookmaker]
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

# --- Frozen-price quarantine (N0-2) ---
# A book's row is refused when its own feed timestamp says the price is older
# than the mode's TTL, or when the price has not moved for this many scans while
# at least one independent peer did move. The second rule is deliberately not a
# "price did not move" rule: a stable market with stable peers is normal.
STALE_PRICE_UNCHANGED_SCANS = int(os.getenv("STALE_PRICE_UNCHANGED_SCANS", "3"))
# Bounded per-book observation store: keep the newest rows and drop observations
# not seen for a week. This is runtime state, not a trust record.
STALE_PRICE_MAX_ROWS = int(os.getenv("STALE_PRICE_MAX_ROWS", "50000"))
STALE_PRICE_RETENTION_SECONDS = int(
    os.getenv("STALE_PRICE_RETENTION_SECONDS", str(7 * 24 * 3600))
)

# --- Automatic closing-line capture (N0-4) ---
# A logged bet's closing line is the last matching price before kickoff. The
# cutoff is minutes before kickoff; 0 means "up to kickoff". Capture never
# invents a price after this point and never touches a settled bet.
CLOSING_CAPTURE_CUTOFF_MINUTES = int(os.getenv("CLOSING_CAPTURE_CUTOFF_MINUTES", "0"))

# --- Retention and maintenance (N1-1) ---
# Runtime stores grow forever unless a bounded job trims them. These windows are
# deliberately generous: they keep a season of scans, a full paper history and
# the complete bet log while bounding the files a long-running deployment must
# back up. Bets are never deleted by default; only settled rows past the archive
# window are copied to a dated archive file.
RETENTION_SCANS_DAYS = int(os.getenv("RETENTION_SCANS_DAYS", "90"))
RETENTION_LINK_SWEEPS_DAYS = int(os.getenv("RETENTION_LINK_SWEEPS_DAYS", "90"))
RETENTION_PAPER_DAYS = int(os.getenv("RETENTION_PAPER_DAYS", "180"))
# The row cap is the second bound: a busy paper ledger is trimmed oldest-first
# even when it is inside the date window.
RETENTION_PAPER_MAX_ROWS = int(os.getenv("RETENTION_PAPER_MAX_ROWS", "200000"))
RETENTION_BETS_ARCHIVE_DAYS = int(os.getenv("RETENTION_BETS_ARCHIVE_DAYS", "365"))
RETENTION_LOG_DAYS = int(os.getenv("RETENTION_LOG_DAYS", "30"))
# Generated logs are optional (the default deployment logs to stdout). When a
# log directory exists, maintenance only removes old *.log files from it.
LOG_DIR = os.getenv(
    "LOG_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"),
)
# The daily job runs off the scan path. A scan starter refuses to begin while a
# maintenance run holds the process-wide guard, so a prune or VACUUM cannot
# overlap a scan write.
MAINTENANCE_ENABLED = os.getenv("MAINTENANCE_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MAINTENANCE_INTERVAL_HOURS = float(os.getenv("MAINTENANCE_INTERVAL_HOURS", "24"))
MAINTENANCE_STARTUP_DELAY_SECONDS = float(
    os.getenv("MAINTENANCE_STARTUP_DELAY_SECONDS", "60")
)
# Soft budgets reported by /api/health. Crossing one is a warning, not a scan
# stop; retention is what brings the store back under the line.
SQLITE_SIZE_BUDGET_BYTES = int(
    os.getenv("SQLITE_SIZE_BUDGET_BYTES", str(256 * 1024 * 1024))
)
PAPER_ROWS_BUDGET = int(
    os.getenv("PAPER_ROWS_BUDGET", str(RETENTION_PAPER_MAX_ROWS))
)

# --- Paper fills (N2-2) ---
# A paper position is a simulation, not a proven acceptance. Fill rules are
# deterministic: a price that moved beyond the tolerance is rejected, a missing
# leg is missing, and a planned stake above the book's advisory cap is partially
# filled at that cap. No probability model and no account/cash effect is used.
PAPER_FILL_ENABLED = os.getenv("PAPER_FILL_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
PAPER_FILL_PRICE_TOLERANCE = float(
    os.getenv("PAPER_FILL_PRICE_TOLERANCE", "0.0")
)
PAPER_FILL_PARTIAL_ENABLED = os.getenv(
    "PAPER_FILL_PARTIAL_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
BETS_ROWS_BUDGET = int(os.getenv("BETS_ROWS_BUDGET", "50000"))
MAPPING_LEDGER_BUDGET_BYTES = int(
    os.getenv("MAPPING_LEDGER_BUDGET_BYTES", str(64 * 1024 * 1024))
)
LOG_SIZE_BUDGET_BYTES = int(
    os.getenv("LOG_SIZE_BUDGET_BYTES", str(50 * 1024 * 1024))
)

# --- Coverage and mapping SLOs (N1-2) ---
# A coverage alert is a warning, never a trust rule: no group is dropped or
# merged because one fired. The peer/baseline evidence in the report is what
# keeps a legitimate all-zero seasonal feed quiet.
COVERAGE_FLAG_ALERT_THRESHOLD = int(
    os.getenv("COVERAGE_FLAG_ALERT_THRESHOLD", "1")
)
# Mapping coverage is mapped market rows / (mapped + newly unmapped rows) for
# one scan. A small scan is not judged: the denominator must clear this floor
# before a low ratio can alert.
MAPPING_COVERAGE_FLOOR = float(os.getenv("MAPPING_COVERAGE_FLOOR", "0.95"))
MAPPING_COVERAGE_MIN_ROWS = int(os.getenv("MAPPING_COVERAGE_MIN_ROWS", "20"))
# A repeated zero result must persist for this many consecutive scans before it
# alerts. A one-off quiet scan is not a feed loss.
COVERAGE_ALERT_CONSECUTIVE_SCANS = int(
    os.getenv("COVERAGE_ALERT_CONSECUTIVE_SCANS", "2")
)

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
# Outgoing politeness ceiling per bookmaker, in requests per second (0 disables
# it). Every scan attempt waits its slot, retries included. No book publishes a
# quota, so this is a ceiling derived from a recorded scan, not a measured
# limit: on 2026-11-06 the whole prematch scan made 187 requests and the
# busiest book (mozzartbet) made 101 in 57 s (1.8/s), so 5/s leaves every book
# at least as fast as it was measured. Tune it down on 429s; raising it is an
# operator decision.
SCRAPER_REQUESTS_PER_SECOND = float(os.getenv("SCRAPER_REQUESTS_PER_SECOND", "5"))
# One adapter must finish within this budget; a book that does not is reported
# `timeout` and missing from the scan, while the others still price. The slowest
# book in the recorded 2026-11-06 scans took 72.6 s prematch and 100.7 s live,
# so 240 s leaves a 2.4x margin without letting a hung book block the scan
# forever.
SCRAPER_BOOK_TIMEOUT_SECONDS = float(
    os.getenv("SCRAPER_BOOK_TIMEOUT_SECONDS", "240")
)
# The whole scraping phase must finish within this budget. Books still running
# then are cancelled (their browser closed) and the scan continues with the
# books that did return and price. This also bounds the wait for a browser slot,
# which the per-book deadline does not cover. A scan is scheduled every few
# minutes at most, so ten minutes is a backstop, not a normal duration.
SCRAPER_SCAN_TIMEOUT_SECONDS = float(
    os.getenv("SCRAPER_SCAN_TIMEOUT_SECONDS", "600")
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
# "text" keeps the readable log line; "json" emits one JSON object per line for
# a log collector. Both carry the request/scan correlation id.
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").strip().lower()
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
# Max on-demand surebet re-verifications per minute per client (0 disables the
# limit). A verify scrapes every book in the bet while holding the mode lock, so
# repeated calls can block the scheduler and hit the bookmakers.
VERIFY_RATE_LIMIT = int(os.getenv("VERIFY_RATE_LIMIT", "10"))
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

# --- Deep-link declarations (P1-5/P2-2) ---
# A no-event declaration is a human check with a date. Warn when it is older
# than this; the gate still uses the declaration, the audit only makes it
# visible.
DEEPLINK_DECLARATION_MAX_AGE_DAYS = int(
    os.getenv("DEEPLINK_DECLARATION_MAX_AGE_DAYS", "180")
)

# --- Push feeds (P2-10) ---
# No book qualified in the 2026-11-04 transport capture, so every flag is off
# and the scan keeps polling. An adapter must be enabled per book, and the scan
# path must be wired to it, before a stream can influence pricing.
LIVE_FEED_FLAGS: dict[str, bool] = {
    book: os.getenv(f"LIVE_FEED_{book.upper()}_ENABLED", "false").strip().lower()
    in ("1", "true", "yes")
    for book in (
        "mozzartbet",
        "mdshop",
        "admiralbet",
        "betole",
        "mbet",
        "sportplus",
        "evlbet",
        "premier_kladionica",
        "wwin",
        "maxbet",
    )
}

# --- Alerts (P1-5) ---
# Empty URLs mean no transport: the manager stays a null transport, so a fresh
# checkout never tries to send anything. Secrets are read here from the
# environment and are never logged or exposed by /api/health.
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()
ALERT_TELEGRAM_BOT_TOKEN = os.getenv("ALERT_TELEGRAM_BOT_TOKEN", "").strip()
ALERT_TELEGRAM_CHAT_ID = os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()
ALERT_MIN_PROFIT_PERCENT = float(os.getenv("ALERT_MIN_PROFIT_PERCENT", "3.0"))
ALERT_DEDUPE_MINUTES = int(os.getenv("ALERT_DEDUPE_MINUTES", "60"))
# Delivery is retried off the scan path. Tests set these to zero.
ALERT_RETRY_ATTEMPTS = int(os.getenv("ALERT_RETRY_ATTEMPTS", "3"))
ALERT_RETRY_BASE_SECONDS = float(os.getenv("ALERT_RETRY_BASE_SECONDS", "1.0"))

# --- Resource budgets (P1-6) ---
# The measured soak plateau is ~767 MB; 1 GB leaves headroom while still
# catching a leak. Cache size is guarded by CACHE_SIZE_BUDGET_BYTES below.
RSS_BUDGET_MB = int(os.getenv("RSS_BUDGET_MB", "1024"))

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
