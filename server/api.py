"""
FastAPI Route Handlers

Endpoints:
  POST /api/scan       — Trigger a full scan (runs in background)
  GET  /api/status     — Poll scan status
  GET  /api/results    — Get cached results (surebets + matches)
  GET  /api/config     — Get bookmaker config for the frontend
  GET  /api/debug/report — Get match grouping debug report
  POST /api/recalculate — Recalculate stakes for a given investment
  POST /api/verify     — Re-verify a surebet's odds against fresh bookmaker data
  GET  /api/history    — Recent scan history
"""

import asyncio
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from config.settings import (
    API_KEY,
    BOOKMAKERS,
    BROWSER_CONCURRENCY,
    CACHE_DIR,
    DEFAULT_INVESTMENT,
    DUST_PROFIT_PERCENT,
    ENABLED_MARKETS,
    EXPERIMENTAL_MARKETS,
    MIN_PROFIT_PERCENT,
    ODDS_TTL_SECONDS,
    SCAN_RATE_LIMIT,
)
from engine.arbitrage import ArbitrageEngine
from engine.matcher import MatchMatcher
from models.schemas import MarketType, Match, ScanStatus
from scrapers.admiralbet import AdmiralbetScraper
from scrapers.betole import BetoleScraper
from scrapers.evlbet import EvlbetScraper
from scrapers.mbet import MBetScraper
from scrapers.mdshop import MDShopScraper
from scrapers.mozzartbet import MozzartbetScraper
from scrapers.premier_kladionica import PremierKladionicaScraper
from scrapers.sportplus import SportPlusScraper
from scrapers.wwin import WWINScraper

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_api_key(x_api_key: str = Header(default="")) -> None:
    """Optional API key auth — enforced when API_KEY is configured."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")

# ─── In-memory bookmaker enabled overrides ──────────────────────────────
# Start with settings.py defaults, modifiable via /api/config/toggle/<id>
# and persisted to a JSON state file so toggles survive restarts.
_BOOKMAKER_STATE_FILE = os.path.join(CACHE_DIR, "bookmaker_state.json")
_bookmaker_enabled: dict[str, bool] = {bid: bool(cfg.get("enabled", True)) for bid, cfg in BOOKMAKERS.items()}
# Per-mode locks — prematch and live scans run independently (P0-7).
# run_scan holds its mode lock for the whole scan so verify cannot overlap it.
_prematch_lock = asyncio.Lock()
_live_lock = asyncio.Lock()
_browser_sem = asyncio.Semaphore(BROWSER_CONCURRENCY)

PLAYWRIGHT_BOOKIES = {"mozzartbet", "admiralbet", "wwin"}

def _lock_for(mode: str) -> asyncio.Lock:
    return _live_lock if mode == "live" else _prematch_lock

# ─── Experimental market toggles ────────────────────────────────────────
# The markets in EXPERIMENTAL_MARKETS are OFF by default and only detected
# while checked in the dashboard (persisted to cache/market_state.json).
_MARKET_STATE_FILE = os.path.join(CACHE_DIR, "market_state.json")
_market_enabled: dict[str, bool] = {m: False for m in EXPERIMENTAL_MARKETS}


def _load_market_state() -> None:
    """Restore runtime experimental-market toggles from the state file."""
    global _market_enabled
    try:
        if os.path.exists(_MARKET_STATE_FILE):
            with open(_MARKET_STATE_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for market, state in saved.items():
                if market in _market_enabled and isinstance(state, bool):
                    _market_enabled[market] = state
            logger.info(f"Restored experimental market toggles: {_market_enabled}")
    except Exception as e:
        logger.warning(f"Market state load failed: {e}")


def _save_market_state() -> None:
    """Persist runtime experimental-market toggles to the state file."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_MARKET_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_market_enabled, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Market state save failed: {e}")


def _enabled_markets() -> set[str]:
    """Markets the engine should detect: ENABLED_MARKETS + toggled experimental."""
    return set(ENABLED_MARKETS) | {m for m, on in _market_enabled.items() if on}


def _load_bookmaker_state() -> None:
    """Restore runtime bookmaker toggles from the state file on startup."""
    global _bookmaker_enabled
    try:
        if os.path.exists(_BOOKMAKER_STATE_FILE):
            with open(_BOOKMAKER_STATE_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for bid, state in saved.items():
                if bid in _bookmaker_enabled and isinstance(state, bool):
                    _bookmaker_enabled[bid] = state
            logger.info(f"Restored bookmaker toggles: {_bookmaker_enabled}")
    except Exception as e:
        logger.warning(f"Bookmaker state load failed: {e}")


def _save_bookmaker_state() -> None:
    """Persist runtime bookmaker toggles to the state file."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_BOOKMAKER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_bookmaker_enabled, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Bookmaker state save failed: {e}")


def _is_enabled(bookie_id: str) -> bool:
    """Check if a bookmaker is enabled (respects runtime toggles)."""
    return _bookmaker_enabled.get(bookie_id, True)

# ---------------------------------------------------------------------------
# Global state (in-memory for MVP)
# ---------------------------------------------------------------------------
# Two independent result sets: prematch (future matches) and live (in-play).
scan_status = ScanStatus()               # prematch scans
live_status = ScanStatus(mode="live")    # live scans
cached_surebets: list[dict] = []
cached_matches: list[dict] = []
cached_match_groups_report: list[dict] = []
cached_per_bookie: dict[str, int] = {}  # bookmaker_id -> match count
cached_live_surebets: list[dict] = []
cached_live_matches: list[dict] = []
cached_live_match_groups_report: list[dict] = []
cached_live_per_bookie: dict[str, int] = {}
scan_history: list[dict] = []           # recent scan entries (newest first)

_HISTORY_FILE = os.path.join(CACHE_DIR, "scan_history.json")
_HISTORY_MAX = 50
_PREMATCH_CACHE_FILE = os.path.join(CACHE_DIR, "last_scan.json")
_LIVE_CACHE_FILE = os.path.join(CACHE_DIR, "last_live_scan.json")


def _state_for(mode: str) -> tuple[ScanStatus, list, list, list, dict]:
    """Return (status, surebets, matches, report, per_bookie) for a mode."""
    if mode == "live":
        return (live_status, cached_live_surebets, cached_live_matches,
                cached_live_match_groups_report, cached_live_per_bookie)
    return (scan_status, cached_surebets, cached_matches,
            cached_match_groups_report, cached_per_bookie)


def _load_history() -> None:
    """Restore scan history from disk on startup."""
    global scan_history
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE, encoding="utf-8") as f:
                scan_history = json.load(f)
            logger.info(f"Loaded {len(scan_history)} scan history entries")
    except Exception as e:
        logger.warning(f"History load failed: {e}")


def _save_history() -> None:
    """Persist scan history to disk."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(scan_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"History save failed: {e}")


def _append_history(num_groups: int, mode: str) -> None:
    """Record the completed scan in history (newest first)."""
    status, _, _, _, per_bookie = _state_for(mode)
    entry = {
        "mode": mode,
        "scan_time": status.last_scan_time.isoformat() if status.last_scan_time else datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "total_matches": status.total_matches,
        "match_groups": num_groups,
        "surebets_found": status.surebets_found,
        "per_bookie": dict(per_bookie),
        "errors": list(status.errors),
    }
    scan_history.insert(0, entry)
    del scan_history[_HISTORY_MAX:]
    _save_history()

SCRAPERS: dict[str, Any] = {
    "mozzartbet": MozzartbetScraper,
    "mdshop": MDShopScraper,
    "admiralbet": AdmiralbetScraper,
    "betole": BetoleScraper,
    "mbet": MBetScraper,
    "sportplus": SportPlusScraper,
    "evlbet": EvlbetScraper,
    "premier_kladionica": PremierKladionicaScraper,
    "wwin": WWINScraper,
}


# ---------------------------------------------------------------------------
# Background scan task
# ---------------------------------------------------------------------------

async def run_scan(mode: str = "prematch"):
    """Execute a full scan of all enabled bookmakers concurrently.

    `mode` selects the feed: "prematch" (future matches) or "live" (in-play).
    Each mode has its own status object and cache file.
    Uniform `scan_started_at` (naive UTC) is passed to all scrapers so date
    windows are identical (P0-5) and odds can be age-checked (P0-1).
    """
    is_live = mode == "live"
    status, surebets_cache, matches_cache, report_cache, per_bookie = _state_for(mode)
    scan_started_at = datetime.now(UTC).replace(tzinfo=None)

    status.is_scanning = True
    status.bookmakers_done = []
    status.bookmaker_progress = {}
    status.errors = []
    status.total_matches = 0
    status.surebets_found = 0
    status.current_bookmaker = "Starting..."

    try:
        all_matches: list[Match] = []

        # --- Scrape each enabled bookmaker (P2: browser concurrency cap) ---
        async def scrape_one(bookie_id: str, config: dict) -> list[Match]:
            if not _is_enabled(bookie_id):
                status.bookmaker_progress[bookie_id] = "skipped"
                return []

            status.bookmaker_progress[bookie_id] = "scraping"
            status.current_bookmaker = f"Scraping {config['name']}..."
            # Limit concurrent Playwright browsers
            sem = _browser_sem if bookie_id in PLAYWRIGHT_BOOKIES else None
            if sem:
                await sem.acquire()
            try:
                scraper_class = SCRAPERS.get(bookie_id)
                if not scraper_class:
                    status.bookmaker_progress[bookie_id] = "error"
                    return []

                scraper = scraper_class()
                # Pass uniform scan_time for window consistency; fallback only
                # when the scraper signature lacks scan_time (not on internal errors)
                try:
                    matches = await scraper.scrape(live=is_live, scan_time=scan_started_at)
                except TypeError as te:
                    if "scan_time" not in str(te):
                        raise
                    matches = await scraper.scrape(live=is_live)
                # Stamp fetched_at if scraper missed it (defense in depth)
                for m in matches:
                    if not m.fetched_at:
                        m.fetched_at = scan_started_at

                status.bookmaker_progress[bookie_id] = "done"
                status.bookmakers_done.append(config["name"])
                status.total_matches += len(matches)
                per_bookie[bookie_id] = len(matches)
                logger.info(f"✅ {config['name']}: {len(matches)} {'live' if is_live else 'prematch'} matches scraped")
                return matches

            except Exception as e:
                error_msg = f"{config['name']}: {str(e)[:200]}"
                status.bookmaker_progress[bookie_id] = "error"
                status.errors.append(error_msg)
                logger.error(f"❌ Scrape error — {error_msg}", exc_info=True)
                return []
            finally:
                if sem:
                    sem.release()

        # Run all scrapers concurrently
        status.current_bookmaker = "Scraping all bookmakers..."
        tasks = [scrape_one(bid, cfg) for bid, cfg in BOOKMAKERS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                all_matches.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Scraper gather exception: {res}")
                status.errors.append(f"Scraper error: {str(res)[:200]}")

        # Age spread guard (P0-1): warn if scrapers' fetched_at diverge >90s
        if all_matches:
            times = [
                m.fetched_at.astimezone(UTC).replace(tzinfo=None)
                if m.fetched_at and m.fetched_at.tzinfo
                else m.fetched_at
                for m in all_matches if m.fetched_at
            ]
            if times:
                spread = (max(times) - min(times)).total_seconds()  # type: ignore[operator]
                if spread > 90:
                    logger.warning(f"Odds age spread {spread:.0f}s exceeds 90s — results may be stale")
                    status.errors.append(f"Odds age spread {spread:.0f}s — verify before betting")

        # --- Match and find surebets ---
        status.current_bookmaker = "Analysing matches..."
        logger.info(f"Total {'live' if is_live else 'prematch'} matches collected: {len(all_matches)}. Running matcher...")

        matcher = MatchMatcher()
        groups = matcher.group_matches(all_matches)
        report_cache.clear()
        report_cache.extend(matcher.get_match_report(groups))

        status.current_bookmaker = "Detecting surebets..."
        engine = ArbitrageEngine()
        # P1-6: include dust (0.2%) — frontend filters/highlights by tier
        surebets = engine.find_surebets(
            groups,
            min_profit=DUST_PROFIT_PERCENT,
            investment=DEFAULT_INVESTMENT,
            allow_past_kickoffs=is_live,
            enabled_markets=_enabled_markets(),
        )

        # --- Update state ---
        status.surebets_found = len(surebets)
        status.last_scan_time = datetime.now(UTC).replace(tzinfo=None)

        # Serialize to dict for JSON responses
        surebets_cache[:] = [s.model_dump(mode="json") for s in surebets]
        matches_cache[:] = [m.model_dump(mode="json") for m in all_matches]

        # Persist to cache file
        _save_cache(mode)
        _append_history(len(groups), mode)

        logger.info(
            f"🎯 {'Live' if is_live else 'Prematch'} scan complete: {len(all_matches)} matches scraped, "
            f"{len(groups)} match groups, {len(surebets)} surebets found"
        )
    except Exception as e:
        logger.error(f"❌ Scan failed: {e}", exc_info=True)
        status.errors.append(f"Scan error: {str(e)[:200]}")
    finally:
        status.is_scanning = False
        status.current_bookmaker = ""


def _save_cache(mode: str = "prematch"):
    """Persist last scan results to JSON cache files (with TTL metadata P0-6)."""
    status, surebets_cache, matches_cache, _, _ = _state_for(mode)
    cache_file = _LIVE_CACHE_FILE if mode == "live" else _PREMATCH_CACHE_FILE
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        # Include fetched_at spread for staleness UI
        fetched_times = []
        for m in matches_cache:
            ft = m.get("fetched_at") if isinstance(m, dict) else getattr(m, "fetched_at", None)
            if ft:
                fetched_times.append(str(ft))
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "surebets": surebets_cache,
                "matches": matches_cache,
                "matches_count": len(matches_cache),
                "mode": mode,
                "scan_time": status.last_scan_time.isoformat() if status.last_scan_time else None,
                "fetched_at": status.last_scan_time.isoformat() if status.last_scan_time else None,
            }, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Cache save failed: {e}")


def _load_cache():
    """Restore last scan results from the JSON cache files on startup (TTL 30min P0-6)."""
    for mode, cache_file, state_fields in (
        ("prematch", _PREMATCH_CACHE_FILE, (scan_status, cached_surebets, cached_matches)),
        ("live", _LIVE_CACHE_FILE, (live_status, cached_live_surebets, cached_live_matches)),
    ):
        status, surebets_cache, matches_cache = state_fields
        try:
            if not os.path.exists(cache_file):
                continue
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
            scan_time = data.get("scan_time")
            # TTL: discard cache older than 30 minutes (stale cache replay guard)
            if scan_time:
                try:
                    parsed = datetime.fromisoformat(scan_time)
                    # Handle naive UTC stored
                    if parsed.tzinfo is None:
                        age = (datetime.now(UTC).replace(tzinfo=None) - parsed).total_seconds()
                    else:
                        age = (datetime.now(UTC) - parsed).total_seconds()
                    if age > 1800:
                        logger.info(f"Cache {mode} expired ({age/60:.0f}min old) — discarding")
                        continue
                    status.last_scan_time = parsed
                except ValueError:
                    pass
            surebets_cache[:] = data.get("surebets", [])
            matches_cache[:] = data.get("matches", [])
            status.total_matches = len(matches_cache)
            status.surebets_found = len(surebets_cache)
            logger.info(
                f"Loaded cached {'live' if mode == 'live' else 'prematch'} scan: "
                f"{len(surebets_cache)} surebets, {len(matches_cache)} matches from {scan_time}"
            )
        except Exception as e:
            logger.warning(f"Cache load failed ({mode}): {e}")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

# Per-client-IP scan rate limiting (in-memory, sliding 60s window)
_scan_request_times: dict[str, list[float]] = {}


@router.post("/scan")
async def trigger_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    mode: str = "prematch",
    _auth: None = Depends(_require_api_key),
):
    """Trigger a new scan of all bookmakers (mode=prematch|live). P0-7 per-mode lock."""
    if mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'prematch' or 'live'")

    status, _, _, _, _ = _state_for(mode)
    mode_lock = _lock_for(mode)

    # Fast-path: verify holds the mode lock during its scrape — don't block
    # for the whole verify, return immediately instead.
    if mode_lock.locked() or status.is_scanning:
        return {
            "status": "already_scanning",
            "message": f"A {mode} scan is already in progress. Please wait.",
        }

    if SCAN_RATE_LIMIT > 0:
        client_ip = request.client.host if request.client else "unknown"
        now_ts = time.time()
        window = [t for t in _scan_request_times.get(client_ip, []) if now_ts - t < 60]
        if len(window) >= SCAN_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {SCAN_RATE_LIMIT} scans per minute",
            )
        window.append(now_ts)
        _scan_request_times[client_ip] = window

    async with mode_lock:
        if status.is_scanning:
            return {
                "status": "already_scanning",
                "message": f"A {mode} scan is already in progress. Please wait.",
            }
        status.is_scanning = True

    background_tasks.add_task(run_scan, mode)
    return {
        "status": "started",
        "mode": mode,
        "message": "Scan started. Poll /api/status for progress.",
    }


@router.get("/health")
async def health():
    """Health + per-bookie diagnostics (P1-6)."""
    def age_sec(dt):
        if not dt:
            return None
        try:
            # Handle naive UTC stored
            if dt.tzinfo is None:
                return (datetime.now(UTC).replace(tzinfo=None) - dt).total_seconds()
            return (datetime.now(UTC) - dt).total_seconds()
        except Exception:
            return None
    return {
        "status": "ok",
        "scanning": scan_status.is_scanning or live_status.is_scanning,
        "surebets_cached": len(cached_surebets),
        "matches_cached": len(cached_matches),
        "live_surebets_cached": len(cached_live_surebets),
        "live_matches_cached": len(cached_live_matches),
        "prematch": {
            "last_scan_age_sec": age_sec(scan_status.last_scan_time),
            "per_bookie": dict(cached_per_bookie),
            "errors": list(scan_status.errors),
        },
        "live": {
            "last_scan_age_sec": age_sec(live_status.last_scan_time),
            "per_bookie": dict(cached_live_per_bookie),
            "errors": list(live_status.errors),
        },
        "odds_ttl_sec": ODDS_TTL_SECONDS,
    }


@router.get("/status")
async def get_status(mode: str = "prematch"):
    """Get the current scan status (mode=prematch|live)."""
    status, _, _, _, _ = _state_for(mode)
    return status.model_dump(mode="json")


@router.get("/results")
async def get_results(mode: str = "prematch"):
    """Get the cached results from the last scan (mode=prematch|live)."""
    status, surebets_cache, matches_cache, _, _ = _state_for(mode)
    return {
        "surebets": surebets_cache,
        "total_matches": len(matches_cache),
        "surebets_count": len(surebets_cache),
        "mode": mode,
        "last_scan_time": (
            status.last_scan_time.isoformat()
            if status.last_scan_time
            else None
        ),
    }


@router.get("/config")
async def get_config():
    """Get current configuration for the frontend (reflects runtime toggles)."""
    return {
        "bookmakers": {
            k: {
                "name": v["name"],
                "enabled": _is_enabled(k),
                "color": v["color"],
            }
            for k, v in BOOKMAKERS.items()
        },
        "experimental_markets": {m: _market_enabled.get(m, False) for m in EXPERIMENTAL_MARKETS},
        "min_profit_percent": MIN_PROFIT_PERCENT,
        "dust_profit_percent": DUST_PROFIT_PERCENT,
        "default_investment": DEFAULT_INVESTMENT,
    }


@router.post("/config/toggle_market/{market}")
async def toggle_market(
    market: str,
    _auth: None = Depends(_require_api_key),
):
    """Enable or disable an experimental market for future scans."""
    if market not in _market_enabled:
        raise HTTPException(status_code=404, detail=f"Unknown experimental market: {market}")

    _market_enabled[market] = not _market_enabled[market]
    new_state = _market_enabled[market]
    _save_market_state()

    logger.info(f"Experimental market '{market}' toggled {'ON' if new_state else 'OFF'}")
    return {
        "status": "ok",
        "market": market,
        "enabled": new_state,
    }


@router.post("/config/toggle/{bookmaker_id}")
async def toggle_bookmaker(
    bookmaker_id: str,
    _auth: None = Depends(_require_api_key),
):
    """Enable or disable a bookmaker for future scans."""
    if bookmaker_id not in BOOKMAKERS:
        raise HTTPException(status_code=404, detail=f"Unknown bookmaker: {bookmaker_id}")

    current = _is_enabled(bookmaker_id)
    _bookmaker_enabled[bookmaker_id] = not current
    new_state = _bookmaker_enabled[bookmaker_id]
    _save_bookmaker_state()

    logger.info(f"Bookmaker '{bookmaker_id}' toggled {'ON' if new_state else 'OFF'}")
    return {
        "status": "ok",
        "bookmaker_id": bookmaker_id,
        "enabled": new_state,
    }


@router.get("/debug/matches")
async def get_matches_breakdown(mode: str = "prematch"):
    """Debug endpoint: show match counts per bookmaker and all raw match data."""
    from collections import defaultdict
    _, _, matches_cache, _, _ = _state_for(mode)
    by_bookie = defaultdict(list)
    for m in matches_cache:
        by_bookie[m.get("bookmaker", "unknown")].append(
            f"{m.get('home_team')} vs {m.get('away_team')} [{m.get('league','')}]"
        )
    return {
        "mode": mode,
        "totals": {k: len(v) for k, v in by_bookie.items()},
        "grand_total": len(matches_cache),
        "matches_by_bookmaker": dict(by_bookie),
    }


@router.get("/debug/report")
async def get_match_report(mode: str = "prematch"):
    """Get match grouping debug report — verify correct cross-bookmaker pairings."""
    _, _, _, report_cache, _ = _state_for(mode)
    return {
        "mode": mode,
        "total_groups": len(report_cache),
        "groups": report_cache,
    }


class RecalculateRequest(BaseModel):
    surebet_id: str
    investment: float
    mode: str = "prematch"


class VerifyRequest(BaseModel):
    surebet_id: str
    mode: str = "prematch"


@router.get("/history")
async def get_history(_auth: None = Depends(_require_api_key)):
    """Recent scan history (newest first)."""
    return {"count": len(scan_history), "entries": scan_history}


@router.post("/verify")
async def verify_surebet(req: VerifyRequest, _auth: None = Depends(_require_api_key)):
    """
    Live odds verification: re-scrape ONLY the bookmakers involved in a surebet,
    re-group the match, and compare current odds against the cached ones.
    Returns whether the surebet is still profitable.
    """
    is_live = req.mode == "live"
    surebets_cache, _, _, _ = _state_for(req.mode)[1:]
    target = next((s for s in surebets_cache if s.get("id") == req.surebet_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Surebet not found")

    mode_lock = _lock_for(req.mode)
    status_for_mode, _, _, _, _ = _state_for(req.mode)
    async with mode_lock:
        if status_for_mode.is_scanning:
            raise HTTPException(
                status_code=409,
                detail="A scan is in progress — retry after it finishes",
            )

        bookie_ids = sorted({s["bookmaker"] for s in target["stakes"] if _is_enabled(s["bookmaker"])})
        if not bookie_ids:
            raise HTTPException(status_code=400, detail="All involved bookmakers are disabled")

        fresh_matches: list[Match] = []
        errors: list[str] = []
        for bookie_id in bookie_ids:
            scraper_class = SCRAPERS.get(bookie_id)
            if not scraper_class:
                continue
            try:
                scraper = scraper_class()
                fresh_matches.extend(await scraper.scrape(live=is_live))
            except Exception as e:
                errors.append(f"{bookie_id}: {str(e)[:150]}")

    # Re-group the fresh data and find the same real-world match
    groups = MatchMatcher().group_matches(fresh_matches)
    target_home = (target.get("home_team") or "").lower()
    target_away = (target.get("away_team") or "").lower()
    group = None
    for g in groups:
        gh = (g.canonical_home or "").lower()
        ga = (g.canonical_away or "").lower()
        if (gh == target_home and ga == target_away) or (gh == target_away and ga == target_home):
            group = g
            break

    if group is None:
        return {
            "surebet_id": target["id"],
            "message": "Match not found in fresh data (removed or renamed)",
            "cached_margin": target["total_margin"],
            "cached_profit_percent": target["profit_percent"],
            "still_profitable": None,
            "errors": errors,
        }

    engine = ArbitrageEngine()
    try:
        market_type = MarketType(target["market_type"])
    except ValueError:
        market_type = None

    current = engine.evaluate_market(group, market_type) if market_type else None
    if current is None:
        return {
            "surebet_id": target["id"],
            "message": "No profitable combination remains in current odds",
            "cached_margin": target["total_margin"],
            "cached_profit_percent": target["profit_percent"],
            "still_profitable": False,
            "errors": errors,
        }

    old_by_label = {s["outcome_label"]: s["odds"] for s in target["stakes"]}
    drift = {}
    for label, old_odds in old_by_label.items():
        new = current["odds"].get(label)
        drift[label] = {
            "old_odds": old_odds,
            "new_odds": new["odds"] if new else None,
            "new_bookmaker": new["bookmaker"] if new else None,
            "changed": (new is None or abs(new["odds"] - old_odds) > 0.001),
        }

    return {
        "surebet_id": target["id"],
        "match": f"{target['home_team']} vs {target['away_team']}",
        "market_type": target["market_type"],
        "cached": {
            "margin": target["total_margin"],
            "profit_percent": target["profit_percent"],
        },
        "current": {
            "margin": current["margin"],
            "profit_percent": current["profit_percent"],
        },
        "drift": drift,
        "still_profitable": current["profit_percent"] >= MIN_PROFIT_PERCENT,
        "errors": errors,
    }


@router.post("/recalculate")
async def recalculate_stakes(
    req: RecalculateRequest,
    _auth: None = Depends(_require_api_key),
):
    """Recalculate optimal stakes for a given investment amount."""
    if req.investment <= 0:
        raise HTTPException(status_code=400, detail="Investment must be positive")
    if req.investment > 1_000_000:
        raise HTTPException(status_code=400, detail="Investment too large")

    # Find the surebet in the mode-specific cache
    surebets_cache, _, _, _ = _state_for(req.mode)[1:]
    target = next(
        (s for s in surebets_cache if s.get("id") == req.surebet_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Surebet not found")

    # Recalculate stakes
    total_margin = target["total_margin"]
    if total_margin >= 1.0 or total_margin <= 0:
        raise HTTPException(status_code=400, detail="Not a valid surebet")

    new_stakes = []
    for stake in target["stakes"]:
        odds = stake["odds"]
        implied = 1.0 / odds
        new_stake = req.investment * (implied / total_margin)
        potential_return = new_stake * odds
        new_stakes.append({
            "bookmaker": stake["bookmaker"],
            "outcome_label": stake["outcome_label"],
            "odds": odds,
            "stake": round(new_stake, 2),
            "potential_return": round(potential_return, 2),
        })

    guaranteed_return = round(req.investment / total_margin, 2)
    profit = round(guaranteed_return - req.investment, 2)

    return {
        "stakes": new_stakes,
        "investment": req.investment,
        "guaranteed_return": guaranteed_return,
        "guaranteed_profit": profit,
    }
