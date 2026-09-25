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
  POST /api/verify-links — On-demand deep-link proof for one bookmaker
  GET  /api/history    — Recent scan history
"""

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from rapidfuzz import fuzz

from config.settings import (
    API_KEY,
    BOOKMAKERS,
    BROWSER_CONCURRENCY,
    CACHE_DIR,
    DEEP_LINK_VERIFY_RATE_LIMIT,
    DEFAULT_INVESTMENT,
    DUST_PROFIT_PERCENT,
    ENABLED_MARKETS,
    EXPERIMENTAL_MARKETS,
    MIN_PROFIT_PERCENT,
    ODDS_TTL_SECONDS,
    RATE_LIMIT_WINDOW_SECONDS,
    SCAN_RATE_LIMIT,
)
from engine.ai import MatchAI, PairProposal
from engine.arbitrage import ArbitrageEngine
from engine.certainty import CertaintyGate
from engine.market_registry import unmapped_markets
from engine.matcher import MatchMatcher
from models.schemas import (
    CandidateReview,
    MarketType,
    Match,
    MatchGroup,
    PairSide,
    ScanStatus,
    TeamPositionPair,
)
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

pending_candidates: dict[str, CandidateReview] = {}
candidate_reviews: list[CandidateReview] = []
ALLOWLIST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "team_alias_allowlist.json",
)
_ALLOWLIST_LOCK = threading.Lock()

# Candidates a human has already decided on, keyed by the deterministic pair id.
# Without this a decided pair is rebuilt into the queue on every scan and can be
# approved again forever, so the review loop could never converge.
SUPPRESSED_CANDIDATES_FILE = os.path.join(CACHE_DIR, "suppressed_candidates.json")
_suppressed_candidates: dict[str, str] = {}
_SUPPRESSED_LOCK = threading.Lock()


def _atomic_write_json(path: str, payload: object, prefix: str) -> None:
    """Write JSON through a temp file so a reader never sees a partial document."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{prefix}.", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _load_allowlist() -> set[str]:
    try:
        with open(ALLOWLIST_FILE, encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict) or not isinstance(data.get("aliases"), list):
            return set()
        return {alias for alias in data["aliases"] if isinstance(alias, str)}
    except (OSError, TypeError, ValueError):
        return set()


def _save_allowlist(aliases: set[str]) -> None:
    _atomic_write_json(ALLOWLIST_FILE, {"aliases": sorted(aliases)}, "team_alias_allowlist")


def _load_suppressed_candidates() -> dict[str, str]:
    """Return decided candidate ids mapped to the decision ("approved"/"rejected")."""
    try:
        with open(SUPPRESSED_CANDIDATES_FILE, encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {}
        return {
            candidate_id: decision
            for candidate_id, decision in data.items()
            if isinstance(candidate_id, str) and decision in ("approved", "rejected")
        }
    except (OSError, TypeError, ValueError):
        return {}


def _save_suppressed_candidates() -> None:
    _atomic_write_json(
        SUPPRESSED_CANDIDATES_FILE, dict(sorted(_suppressed_candidates.items())),
        "suppressed_candidates",
    )


def _suppress_candidate(candidate_id: str, decision: str) -> None:
    """Record a human decision so the pair is not re-queued on the next scan."""
    with _SUPPRESSED_LOCK:
        _suppressed_candidates[candidate_id] = decision
        _save_suppressed_candidates()


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


# ---------------------------------------------------------------------------
# Deep-link verifications (Task 12)
#
# `deep_link_verified` is the only flag that lets a pair reach `verified`, and
# it may only be set from a real check. The check itself costs a browser
# navigation per event, so it is on-demand and never part of a scan; its RESULT
# is stored here so the next scan's gate can see it without scraping again.
#
# A scan rebuilds every match from the scrapers, which all hardcode
# `deep_link_verified=False`, so a write into the cached matches alone would be
# wiped by the next scan within minutes. The store is therefore the durable
# record, keyed per mode (a live event id is not a prematch one) and bounded by
# a TTL: a bookmaker can retire an event at any time, and a dead link must stop
# unblocking `verified` on its own.
# ---------------------------------------------------------------------------
DEEP_LINK_VERIFICATIONS_FILE = os.path.join(CACHE_DIR, "deep_link_verifications.json")
DEEP_LINK_VERIFICATION_TTL_SECONDS = 3600
DEEP_LINK_VERIFY_DEFAULT_LIMIT = 5
DEEP_LINK_VERIFY_MAX_LIMIT = 20
_deep_link_verifications: dict[str, dict[str, dict]] = {}
_DEEP_LINK_LOCK = threading.Lock()
# One browser at a time: the check is the most expensive thing this server does.
# Serialising is not throttling, hence DEEP_LINK_VERIFY_RATE_LIMIT as well.
_deep_link_check_lock = asyncio.Lock()
# Per-client-IP window for the deep-link check, separate from the scan's.
_verify_link_request_times: dict[str, list[float]] = {}


def _deep_link_key(bookmaker: str, event_id: str) -> str:
    """Return the store key for one bookmaker's one event."""
    return f"{bookmaker}|{event_id}"


def _deep_link_record_is_fresh(record: dict, now: datetime | None = None) -> bool:
    """Return whether a stored verification is still inside its TTL."""
    if not isinstance(record, dict) or record.get("verified") is not True:
        return False
    raw = record.get("checked_at")
    if not isinstance(raw, str):
        return False
    try:
        checked_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if checked_at.tzinfo is not None:
        checked_at = checked_at.astimezone(UTC).replace(tzinfo=None)
    reference = now or datetime.now(UTC).replace(tzinfo=None)
    age = (reference - checked_at).total_seconds()
    return 0 <= age <= DEEP_LINK_VERIFICATION_TTL_SECONDS


def _load_deep_link_verifications() -> dict[str, dict[str, dict]]:
    """Load the store, dropping entries that are malformed or past their TTL."""
    state: dict[str, dict[str, dict]] = {}
    try:
        with open(DEEP_LINK_VERIFICATIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, TypeError, ValueError):
        return state
    if not isinstance(data, dict):
        return state
    for mode, entries in data.items():
        if not isinstance(mode, str) or not isinstance(entries, dict):
            continue
        fresh = {k: v for k, v in entries.items() if isinstance(k, str)
                 and _deep_link_record_is_fresh(v)}
        if fresh:
            state[mode] = fresh
    return state


def _save_deep_link_verifications(state: dict[str, dict[str, dict]]) -> None:
    _atomic_write_json(DEEP_LINK_VERIFICATIONS_FILE, state, "deep_link_verifications")


def _record_deep_link_outcomes(mode: str, bookmaker: str, outcomes: list) -> None:
    """Store what a verification run proved, per mode.

    A proven link is recorded with a timestamp. A COMPLETED check that found
    nothing removes the entry, which is how a stale verification is cleared. A
    check that errored is ignored: absence of evidence is not evidence of
    absence, so a timeout must never revoke a proof.
    """
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    with _DEEP_LINK_LOCK:
        entries = _deep_link_verifications.setdefault(mode, {})
        for outcome in outcomes:
            if outcome.error:
                continue
            if outcome.verified:
                entries[_deep_link_key(bookmaker, outcome.event_id)] = {
                    "verified": True,
                    "checked_at": now,
                    "url": outcome.url,
                }
            else:
                key = _deep_link_key(bookmaker, outcome.event_id)
                entries.pop(key, None)
        _save_deep_link_verifications(_deep_link_verifications)


def _apply_deep_link_verifications(
    matches: list, mode: str, now: datetime | None = None
) -> int:
    """Mark matches whose link has a fresh stored verification; return the count.

    Only ever SETS the flag. Clearing happens where a completed check said the
    link is dead, so an unrelated stale store entry can never silently demote a
    match that a check has just proven. Entries that have aged past their TTL
    are pruned here, so a proof cannot outlive its window just because the
    server stayed up.
    """
    reference = now or datetime.now(UTC).replace(tzinfo=None)
    with _DEEP_LINK_LOCK:
        entries = _deep_link_verifications.get(mode)
        if not entries:
            return 0
        fresh = {k: v for k, v in entries.items() if _deep_link_record_is_fresh(v, reference)}
        pruned = len(fresh) != len(entries)
        entries.clear()
        entries.update(fresh)
    applied = 0
    for match in matches:
        is_dict = isinstance(match, dict)
        bookmaker = match.get("bookmaker") if is_dict else getattr(match, "bookmaker", "")
        raw_id = match.get("event_id") if is_dict else getattr(match, "event_id", "")
        event_id = "" if raw_id is None else str(raw_id)
        if not bookmaker or not event_id:
            continue
        record = fresh.get(_deep_link_key(str(bookmaker), event_id))
        if record is None:
            continue
        current = bool(match.get("deep_link_verified") if is_dict
                       else getattr(match, "deep_link_verified", False))
        if current:
            continue
        if is_dict:
            match["deep_link_verified"] = True
        else:
            match.deep_link_verified = True
        applied += 1
    if pruned:
        _save_deep_link_verifications(_deep_link_verifications)
    return applied


async def _run_link_verification(
    bookmaker: str,
    matches: list,
    mode: str = "prematch",
    live: bool = False,
    limit: int | None = None,
):
    """Run the Playwright deep-link check. The endpoint's only browser seam."""
    from scripts.verify_deeplinks import verify_bookmaker

    return await verify_bookmaker(bookmaker, matches, mode=mode, live=live, limit=limit)


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
# Candidate generation
# ---------------------------------------------------------------------------
# A candidate is a same-event claim the certainty gate refused. It is queued for
# a human reviewer; nothing in this section can approve one, and the AI adapter
# only attaches an opinion to a pairing that already exists.

CANDIDATE_KICKOFF_WINDOW_MIN = 30   # wider than verified (15) so near-misses become review items
CANDIDATE_TEAM_SIM_MIN = 70
CANDIDATE_BUCKET_SECONDS = 1800
# The AI is one network call per candidate with a 10s timeout, so a busy scan
# must not fan out without bound: 20 sequential calls is the ceiling, and the
# most *actionable* candidates are ranked first so a cap drops the ones a human
# could not have closed anyway.
AI_CANDIDATE_RANK_CAP = 20
# Wall-clock ceiling. It is checked before each call, so it can overshoot by at
# most one in-flight call (`MatchAI.timeout`, 10s by default).
AI_RANK_TIME_BUDGET_SECONDS = 90.0
# The queue can hold five figures after a full scan and the review tab polls
# every 30s, so the endpoint serves a bounded page. 100 cards is a payload a
# browser re-renders comfortably, and because the queue is ordered by
# actionability the first page is the part a reviewer actually works through.
CANDIDATE_PAGE_SIZE = 100
CANDIDATE_PAGE_MAX = 500
CANDIDATE_REVIEW_HISTORY_MAX = 200   # in-memory log; the allowlist file is the durable record
# Reasons the gate raises only because a bookmaker's event link is unproven.
# They come from the per-book deep-link system check, never from a name, so no
# human decision can clear them.
LINK_REJECTION_REASONS = frozenset({"link_unverified", "no_event_link"})


class _TeamTokens(NamedTuple):
    """Pre-computed team strings and their token sets for the cheap prefilter."""

    home: str
    away: str
    home_tokens: frozenset[str]
    away_tokens: frozenset[str]
    all_tokens: frozenset[str]
    home_bigrams: frozenset[str]
    away_bigrams: frozenset[str]
    all_bigrams: frozenset[str]

    @classmethod
    def of(cls, match: Match) -> "_TeamTokens":
        home = match.home_team_normalized or match.home_team
        away = match.away_team_normalized or match.away_team
        home_tokens, away_tokens = frozenset(home.split()), frozenset(away.split())
        home_bigrams, away_bigrams = _bigrams(home), _bigrams(away)
        return cls(
            home, away, home_tokens, away_tokens, home_tokens | away_tokens,
            home_bigrams, away_bigrams, home_bigrams | away_bigrams,
        )


class _FoundPair(NamedTuple):
    """A queued candidate plus the evidence used to rank it."""

    candidate: CandidateReview
    alias_actionable: bool
    human_blockers: int
    kickoff_delta_minutes: float
    team_similarity: float
    left: Match
    right: Match


def _kickoff_bucket(match: Match) -> int | None:
    """Return the kickoff bucket a match belongs to, or None when it has no kickoff."""
    kickoff = match.kickoff
    if not kickoff:
        return None
    if kickoff.tzinfo is None:  # naive kickoffs are UTC wall-clock
        kickoff = kickoff.replace(tzinfo=UTC)
    return int(kickoff.timestamp() // CANDIDATE_BUCKET_SECONDS)


def _match_event_ref(match: Match) -> str:
    """Return the book's own identifier for a fixture."""
    return match.match_code or match.event_id


def _match_side_key(match: Match) -> str:
    """Identify one book's fixture inside a pair or a match group."""
    return f"{match.bookmaker}|{_match_event_ref(match)}"


def _kickoff_delta_minutes(left: Match, right: Match) -> float:
    """Return the absolute kickoff gap used to rank candidates."""
    if not left.kickoff or not right.kickoff:
        return float("inf")
    first = left.kickoff if left.kickoff.tzinfo else left.kickoff.replace(tzinfo=UTC)
    second = right.kickoff if right.kickoff.tzinfo else right.kickoff.replace(tzinfo=UTC)
    return abs((first - second).total_seconds()) / 60.0


def _bigrams(text: str) -> frozenset[str]:
    """Return the character bigrams of a team string."""
    padded = f" {text} "
    return frozenset(padded[index:index + 2] for index in range(len(padded) - 1))


def _shares_any_signal(left: _TeamTokens, right: _TeamTokens) -> bool:
    """Cheap "this pair is not hopeless" test, run before the fuzzy scorer.

    True when the two fixtures share a token, one team name contains the other,
    or they share a character bigram. It exists only to skip the ~730k fuzzy
    calls of a 7k-match scan; the decision itself is still the fuzzy rule in
    `_team_similarity`, so this test must never admit-or-veto on its own. The
    bigram clause is what keeps a pure typo ("Millonarios" vs "Millionarios")
    in the queue — it shares no token at all, and a token-only gate drops it.
    """
    return bool(
        left.all_tokens & right.all_tokens
        or left.all_bigrams & right.all_bigrams
        or _token_run_shared(left, right)
    )


def _team_similarity(left: _TeamTokens, right: _TeamTokens) -> float:
    """The brief's plausibility rule: best token-set overlap over both orders.

    The inner gate applies the *same* test as `_shares_any_signal`, per team
    slot, so it can only skip a slot the outer gate already ruled hopeless. The
    two therefore agree exactly, and the returned score is the plain
    ``max(token_set_ratio(...))`` over the four combinations whenever the pair
    is not hopeless at all.
    """
    if not _shares_any_signal(left, right):
        return 0.0
    best = 0.0
    for first, second, first_tokens, second_tokens, first_bigrams, second_bigrams in (
        (left.home, right.home, left.home_tokens, right.home_tokens,
         left.home_bigrams, right.home_bigrams),
        (left.home, right.away, left.home_tokens, right.away_tokens,
         left.home_bigrams, right.away_bigrams),
        (left.away, right.home, left.away_tokens, right.home_tokens,
         left.away_bigrams, right.home_bigrams),
        (left.away, right.away, left.away_tokens, right.away_tokens,
         left.away_bigrams, right.away_bigrams),
    ):
        if not (
            first_tokens & second_tokens
            or first_bigrams & second_bigrams
            or first in second
            or second in first
        ):
            continue
        score = fuzz.token_set_ratio(first, second)
        if score > best:
            best = score
            if best == 100.0:  # the scorer cannot return more
                break
    return best


def _token_run_shared(left: _TeamTokens, right: _TeamTokens) -> bool:
    """Return whether one team string is a prefix/substring of the other's."""
    return (
        left.home in right.home or right.home in left.home
        or left.home in right.away or right.away in left.home
        or left.away in right.home or right.home in left.away
        or left.away in right.away or right.away in left.away
    )


def _canonical_pair_key(left: Match, right: Match) -> str:
    """Return the order-independent identity of a pair from both raw claims."""
    def side(match: Match) -> str:
        return f"{_match_side_key(match)}|{match.home_team}|{match.away_team}"

    return "||".join(sorted((side(left), side(right))))


def _candidate_id(canonical_key: str) -> str:
    """Return a stable id for a pair so a re-scan does not churn the queue.

    The queue is keyed by this id and the review UI approves by it, so it has to
    be reproducible from the pair itself and free of truncation collisions.
    """
    return hashlib.sha1(canonical_key.encode("utf-8")).hexdigest()[:16]


def _verified_group_index(groups: list[MatchGroup]) -> dict[str, int]:
    """Map each match the matcher verified to the group that verified it."""
    index: dict[str, int] = {}
    for number, group in enumerate(groups):
        for match in group.matches:
            index.setdefault(_match_side_key(match), number)
    return index


def _alias_name_key(name: str) -> str:
    """The form a name is compared in inside the reviewed allowlist.

    Mirrors ``CertaintyGate._raw_team_key`` (case, spacing and a trailing dot),
    which is what the gate normalises both sides of an entry through.
    """
    return " ".join(name.strip().casefold().split()).rstrip(".")


def _slot_agreement(left_home: str, left_away: str, right_home: str, right_away: str) -> float:
    """Score one home/away orientation of a pair on its normalized names."""
    return (
        fuzz.token_set_ratio(left_home, right_home)
        + fuzz.token_set_ratio(left_away, right_away)
    )


def _team_positions(left: Match, right: Match) -> list[TeamPositionPair]:
    """Pair each team slot of the fixture with the slot the other book uses.

    A bookmaker may publish the fixture flipped, so the better-agreeing
    orientation wins. The raw spellings of both sides are kept because that is
    what a reviewed alias entry is made of; the decision is taken once, here, so
    approval never has to re-derive it.
    """
    left_home = left.home_team_normalized or left.home_team
    left_away = left.away_team_normalized or left.away_team
    right_home = right.home_team_normalized or right.home_team
    right_away = right.away_team_normalized or right.away_team
    direct = _slot_agreement(left_home, left_away, right_home, right_away)
    swapped = _slot_agreement(left_home, left_away, right_away, right_home)
    home_b, away_b = (right.home_team, right.away_team) if direct >= swapped else (
        right.away_team, right.home_team
    )
    return [
        TeamPositionPair(position="home", team_a=left.home_team, team_b=home_b),
        TeamPositionPair(position="away", team_a=left.away_team, team_b=away_b),
    ]


def _alias_entries(positions: list[TeamPositionPair]) -> list[str]:
    """Return one allowlist entry per team slot the two books spell differently.

    Both halves of one fixture are different clubs, so a fixture can never be a
    single alias entry. A slot whose two spellings already agree needs none, and
    a slot the gate could not pair to the same club would poison the allowlist,
    so only real disagreements are written.
    """
    entries = {
        "|".join(sorted((position.team_a.strip(), position.team_b.strip())))
        for position in positions
        if _alias_name_key(position.team_a) != _alias_name_key(position.team_b)
        and "|" not in position.team_a
        and "|" not in position.team_b
        and position.team_a.strip()
        and position.team_b.strip()
    }
    return sorted(entries)


def _alias_actionable(
    reasons: list[str],
    positions: list[TeamPositionPair],
    left: Match,
    right: Match,
    gate: CertaintyGate,
) -> bool:
    """Would the aliases this candidate implies clear every blocker a human owns?

    Asked of the certainty gate itself rather than of a copy of its rules: the
    pair is re-evaluated with only those aliases granted and with both links
    marked verified, which is the state the per-book deep-link system check
    (Task 12) produces. Anything short of ``verified`` is not something an
    approval can fix, so the candidate is not advertised as actionable.
    """
    if not set(reasons) <= LINK_REJECTION_REASONS | {"team_unresolved"}:
        return False
    entries = _alias_entries(positions)
    if not entries:
        return False
    gate.alias_allowlist = set(entries)
    linked = [match.model_copy(update={"deep_link_verified": True}) for match in (left, right)]
    return gate.evaluate_pair(linked[0], linked[1]).status == "verified"


def _shared_client_ai() -> MatchAI | None:
    """Return an AI adapter that reuses one HTTP client for the whole scan.

    ``MatchAI`` builds a fresh ``httpx.AsyncClient`` per call, so 20 sequential
    calls would pay 20 TLS handshakes. Returns ``None`` when no API key is
    configured, so the AI path is never entered without one.
    """
    ai = MatchAI()
    if not ai.available:
        return None
    return ai.with_shared_client()


def _proposal_for_submitted_pair(
    proposals: list[PairProposal], left: Match, right: Match
) -> PairProposal | None:
    """Return the proposal that answers the pair we actually submitted.

    A hosted model can invent pairings that were never asked about. Anything
    that does not echo back the two bookmakers we sent is dropped, so model
    output can never create a pairing of its own.
    """
    submitted = {left.bookmaker, right.bookmaker}
    for proposal in proposals:
        if {proposal.match_a_book, proposal.match_b_book} == submitted:
            return proposal
    return None


async def _rank_candidates_with_ai(ai: MatchAI, found: list[_FoundPair]) -> None:
    """Attach AI opinions to the most plausible candidates. It never approves."""
    if not found:
        return
    if len(found) > AI_CANDIDATE_RANK_CAP:
        logger.warning(
            f"AI ranking capped at {AI_CANDIDATE_RANK_CAP} of {len(found)} candidates — "
            f"{len(found) - AI_CANDIDATE_RANK_CAP} stay unranked this scan"
        )
    deadline = time.monotonic() + AI_RANK_TIME_BUDGET_SECONDS
    for position, pair in enumerate(found[:AI_CANDIDATE_RANK_CAP]):
        if time.monotonic() > deadline:
            logger.warning(
                f"AI ranking budget of {AI_RANK_TIME_BUDGET_SECONDS:.0f}s exhausted after "
                f"{position} candidates — the rest stay unranked this scan"
            )
            return
        left, right = pair.left, pair.right
        proposals = await ai.suggest_pairs([{
            "a": left.bookmaker, "b": right.bookmaker,
            "a_event": _match_event_ref(left), "b_event": _match_event_ref(right),
            "a_home": left.home_team, "a_away": left.away_team, "a_league": left.league,
            "b_home": right.home_team, "b_away": right.away_team, "b_league": right.league,
        }])
        proposal = _proposal_for_submitted_pair(proposals, left, right)
        if proposal is None:
            continue
        pair.candidate.ai_same_event = proposal.same_event
        if not proposal.same_event:
            # A negative verdict is a reason to deprioritise, never a confidence.
            pair.candidate.ai_confidence = 0.0
            pair.candidate.ai_reason = f"AI says not the same event: {proposal.reason}".strip()
            continue
        pair.candidate.ai_confidence = proposal.confidence
        pair.candidate.ai_reason = proposal.reason


async def _collect_candidates(
    all_matches: list[Match],
    matcher: MatchMatcher,
    groups: list[MatchGroup] | None = None,
) -> dict[str, CandidateReview]:
    """Find plausible same-event pairs the matcher could not verify and queue
    them for review.

    Pairs are discovered with a kickoff-bucket index (not an O(n^2) sweep) and a
    cheap team-token prefilter before the full gate runs. AI only ranks; it never
    approves. A pair a human already decided on is never re-queued.
    """
    gate = CertaintyGate(
        kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN,
        league_equivalences=getattr(matcher, "_equivalences", set()),
    )
    # Second gate, reused for the "would an approval fix this?" question. It only
    # ever answers with the aliases of the candidate under test.
    what_if_gate = CertaintyGate(
        kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN,
        league_equivalences=getattr(matcher, "_equivalences", set()),
    )
    gate.normalize(all_matches)

    buckets: dict[int, list[Match]] = {}
    for match in all_matches:
        bucket = _kickoff_bucket(match)
        if bucket is not None:
            buckets.setdefault(bucket, []).append(match)

    # The candidate gate carries no alias allowlist on purpose: an allowlisted
    # alias is already proven, so those pairs must not come back for review.
    verified_in_group = _verified_group_index(groups or [])
    decided = set(_suppressed_candidates)
    seen_pairs: set[str] = set()
    found: list[_FoundPair] = []

    for index in sorted(buckets):
        here = [(match, _TeamTokens.of(match)) for match in buckets[index]]
        # Same and next bucket only: every pair inside the 30-minute candidate
        # window lands in the same or an adjacent bucket, and this compares each
        # adjacent pair exactly once.
        following = [(match, _TeamTokens.of(match)) for match in buckets.get(index + 1, [])]
        for position, (left, left_teams) in enumerate(here):
            for right, right_teams in here[position + 1:] + following:
                if left.bookmaker == right.bookmaker:
                    continue
                similarity = _team_similarity(left_teams, right_teams)
                if similarity < CANDIDATE_TEAM_SIM_MIN:
                    continue
                pair_key = _canonical_pair_key(left, right)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                candidate_id = _candidate_id(pair_key)
                if candidate_id in decided:
                    continue  # a human already decided this exact pair
                left_group = verified_in_group.get(_match_side_key(left))
                if left_group is not None and left_group == verified_in_group.get(
                    _match_side_key(right)
                ):
                    continue  # the matcher already proved this pairing
                result = gate.evaluate_pair(left, right)
                if result.status == "verified":
                    continue  # already handled by the matcher's verified group
                positions = _team_positions(left, right)
                actionable = _alias_actionable(
                    result.reasons, positions, left, right, what_if_gate
                )
                found.append(_FoundPair(
                    candidate=CandidateReview(
                        id=candidate_id,
                        home_team=left.home_team,
                        away_team=left.away_team,
                        league=left.league,
                        kickoff=left.kickoff,
                        bookmakers=sorted([left.bookmaker, right.bookmaker]),
                        side_a=PairSide(
                            bookmaker=left.bookmaker,
                            event_ref=_match_event_ref(left),
                            home_team=left.home_team,
                            away_team=left.away_team,
                            link_verified=left.deep_link_verified,
                        ),
                        side_b=PairSide(
                            bookmaker=right.bookmaker,
                            event_ref=_match_event_ref(right),
                            home_team=right.home_team,
                            away_team=right.away_team,
                            link_verified=right.deep_link_verified,
                        ),
                        team_positions=positions,
                        alias_actionable=actionable,
                        link_blocked=bool(set(result.reasons) & LINK_REJECTION_REASONS),
                        ai_confidence=0.0,
                        ai_reason="",
                        rule_rejections=result.reasons,
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                    ),
                    alias_actionable=actionable,
                    human_blockers=len(
                        [r for r in result.reasons if r not in LINK_REJECTION_REASONS]
                    ),
                    kickoff_delta_minutes=_kickoff_delta_minutes(left, right),
                    team_similarity=similarity,
                    left=left,
                    right=right,
                ))

    # What a reviewer can act on first, then the fewest remaining blockers, then
    # the tightest kickoff and closest names. The AI cap is taken from the top of
    # this order, so the hosted calls land on pairs a human could actually close.
    found.sort(key=lambda pair: (
        not pair.alias_actionable,
        pair.human_blockers,
        pair.kickoff_delta_minutes,
        -pair.team_similarity,
        pair.candidate.id,
    ))
    candidates = {pair.candidate.id: pair.candidate for pair in found}
    logger.info(
        f"Review candidates: {len(candidates)} unverified pairs from {len(all_matches)} matches "
        f"({sum(1 for pair in found if pair.alias_actionable)} alias-actionable, "
        f"{len(decided)} suppressed by earlier decisions)"
    )

    ai = _shared_client_ai() if found else None
    if ai is None:
        return candidates
    try:
        await _rank_candidates_with_ai(ai, found)
    finally:
        await ai.aclose()
    return candidates


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

        # Links already proven by an on-demand check are re-applied here. This
        # is a dict lookup, never a browser: the check itself stays out of the
        # scan path, but its proof must survive into the gate, or every group
        # would be `link_unverified` again on the very next scan.
        proven = _apply_deep_link_verifications(all_matches, mode)
        if proven:
            logger.info(f"Applied {proven} stored deep-link verification(s) to {mode} matches")

        matcher = MatchMatcher()
        groups = matcher.group_matches(all_matches)
        report_cache.clear()
        report_cache.extend(matcher.get_match_report(groups))

        # Ambiguous pairings the gate refused become review items. The queue is
        # rebuilt every scan so it only ever mirrors the current feed.
        status.current_bookmaker = "Collecting review candidates..."
        try:
            pending_candidates.clear()
            pending_candidates.update(
                await _collect_candidates(all_matches, matcher, groups)
            )
        except Exception as e:
            pending_candidates.clear()
            logger.error(f"❌ Candidate collection failed: {e}", exc_info=True)
            status.errors.append(f"Candidate review failed: {str(e)[:200]}")

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
            # A restored cache is re-stamped with any link proof that is still
            # inside its TTL, so a restart does not silently demote every group.
            _apply_deep_link_verifications(matches_cache, mode)
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

# Per-client-IP rate limiting (in-memory, sliding window). The scan window and
# the deep-link window are separate buckets so one cannot exhaust the other, and
# they share ONE window length, which is a setting in its own right rather than
# something derived from an endpoint-specific knob.
_scan_request_times: dict[str, list[float]] = {}


def _enforce_sliding_window(
    request: Request,
    bucket: dict[str, list[float]],
    limit: int,
    what: str,
) -> None:
    """Record one request per client IP in a sliding window, or refuse it.

    A lock only SERIALISES expensive runs, so a flood of them queues N full
    browser sessions instead of being turned away; this is what actually
    throttles. Each caller owns its own bucket, so spending the scan budget
    cannot exhaust the deep-link budget or the reverse.
    """
    if limit <= 0:
        return
    client_ip = request.client.host if request.client else "unknown"
    now_ts = time.time()
    window = [t for t in bucket.get(client_ip, []) if now_ts - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {limit} {what} per "
                f"{RATE_LIMIT_WINDOW_SECONDS} seconds"
            ),
        )
    window.append(now_ts)
    bucket[client_ip] = window


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
        _enforce_sliding_window(request, _scan_request_times, SCAN_RATE_LIMIT, "scans")

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
        "unmapped_markets": dict(unmapped_markets),
        "verified_groups": sum(
            1
            for report in cached_match_groups_report
            if report.get("status") == "verified"
        ),
        "pending_candidates": len(pending_candidates),
        "suppressed_candidates": len(_suppressed_candidates),
        "unverified_links": sum(
            1
            for match in cached_matches
            if match.get("event_id") and not match.get("deep_link_verified")
        ),
        "ai_available": MatchAI().available,
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
    status, surebets_cache, matches_cache, report_cache, _ = _state_for(mode)
    group_statuses: dict[str, int] = {}
    for report in report_cache:
        group_status = str(report.get("status", "unknown"))
        group_statuses[group_status] = group_statuses.get(group_status, 0) + 1
    return {
        "surebets": surebets_cache,
        "total_matches": len(matches_cache),
        "surebets_count": len(surebets_cache),
        "mode": mode,
        "match_groups": len(report_cache),
        "group_statuses": group_statuses,
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


@router.get("/candidates")
async def get_candidates(
    limit: int = CANDIDATE_PAGE_SIZE,
    offset: int = 0,
    _auth: None = Depends(_require_api_key),
):
    """List match candidates awaiting human review, one bounded page at a time.

    The queue is ordered by actionability, so the first page is the part a
    reviewer can actually work through. `total` is the full queue size so a UI
    can say "showing N of M" instead of pretending the page is the queue.
    """
    page = max(1, min(limit, CANDIDATE_PAGE_MAX))
    start = max(0, offset)
    window = list(pending_candidates.values())[start:start + page]
    return {
        "total": len(pending_candidates),
        "count": len(window),
        "limit": page,
        "offset": start,
        "candidates": [candidate.model_dump(mode="json") for candidate in window],
    }


def _resolve_candidate(
    candidate: CandidateReview, decision: Literal["approved", "rejected"]
) -> None:
    """Record a human decision and take the candidate out of the queue for good."""
    candidate.status = decision
    candidate.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    candidate.resolved_by = "human"
    pending_candidates.pop(candidate.id, None)
    candidate_reviews.insert(0, candidate.model_copy(deep=True))
    del candidate_reviews[CANDIDATE_REVIEW_HISTORY_MAX:]
    _suppress_candidate(candidate.id, decision)


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str,
    _auth: None = Depends(_require_api_key),
):
    """Approve a candidate by granting the reviewed team aliases it implies.

    What an approval grants, precisely: one allowlist entry per team slot whose
    two spellings differ, so the certainty gate will trust that those two names
    are the same club. It grants nothing about the event link. A candidate is
    queued precisely because `deep_link_verified` is False on at least one side,
    and that flag is a per-book system check (deep-link verification), so the
    pair stays unverified until that check runs. Approving the *pair* here would
    forge a machine result from a name judgement.
    """
    candidate = pending_candidates.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    entries = _alias_entries(candidate.team_positions)
    if not entries:
        raise HTTPException(
            status_code=400,
            detail=(
                "Candidate carries no cross-bookmaker team names to alias; "
                "re-run a scan to regenerate it"
            ),
        )
    with _ALLOWLIST_LOCK:
        aliases = _load_allowlist()
        aliases.update(entries)
        _save_allowlist(aliases)

    _resolve_candidate(candidate, "approved")
    link_pending = candidate.link_blocked
    return {
        "status": "approved",
        "allowlist_entries": entries,
        "link_verified": not link_pending,
        "link_state": "pending_system_check" if link_pending else "verified",
        "note": (
            "Team aliases granted. The deep-link check is a separate system "
            "verification and is still pending, so this pair is not verified yet."
            if link_pending else
            "Team aliases granted."
        ),
    }


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    _auth: None = Depends(_require_api_key),
):
    """Reject a pending match candidate without changing alias mappings."""
    candidate = pending_candidates.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    _resolve_candidate(candidate, "rejected")
    return {"status": "rejected"}


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


@router.post("/verify-links")
async def verify_links(
    request: Request,
    bookmaker: str = "",
    mode: str = "prematch",
    limit: int = DEEP_LINK_VERIFY_DEFAULT_LIMIT,
    _auth: None = Depends(_require_api_key),
):
    """Prove — or fail to prove — one bookmaker's per-event deep links.

    ON-DEMAND BY DESIGN. This navigates a real browser to real bookmaker pages,
    seconds per event, so it is never triggered from `run_scan` and never runs
    while a scan holds the mode. The response states what it cost and what it
    did NOT cover, because a check that silently skipped events would read as a
    clean bill of health.

    A bookmaker that declares no per-event route (`supports_event_id: false`)
    has nothing to check and is reported as skipped, never as a failure.

    Cost control, because `API_KEY` is empty by default on most deployments:
    a per-client sliding window refuses a flood with 429, `_browser_sem` keeps
    total browser concurrency inside `BROWSER_CONCURRENCY`, and the scan state
    is re-checked AFTER the multi-minute await so a scan that started meanwhile
    is never overwritten.
    """
    from scripts.verify_deeplinks import (
        CRITERION,
        apply_report,
        build_targets,
        supports_event_id,
    )

    if not bookmaker or not bookmaker.strip():
        raise HTTPException(
            status_code=400,
            detail="bookmaker is required, e.g. /api/verify-links?bookmaker=mozzartbet",
        )
    bookmaker = bookmaker.strip()
    if bookmaker not in BOOKMAKERS:
        raise HTTPException(status_code=404, detail=f"Unknown bookmaker: {bookmaker}")
    if mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'prematch' or 'live'")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be at least 1")
    limit = min(limit, DEEP_LINK_VERIFY_MAX_LIMIT)

    status, _, matches_cache, _, _ = _state_for(mode)
    if _lock_for(mode).locked() or status.is_scanning:
        raise HTTPException(
            status_code=409,
            detail=f"A {mode} scan is in progress — retry after it finishes",
        )

    base_url = str(BOOKMAKERS[bookmaker]["base_url"])
    if not supports_event_id(bookmaker):
        return {
            "bookmaker": bookmaker,
            "mode": mode,
            "status": "skipped",
            "skip_reason": f"{bookmaker} declares no declared event route — nothing to verify",
            "criterion": CRITERION,
            "available": 0,
            "checked": 0,
            "verified": 0,
            "failed": 0,
            "errored": 0,
            "unchecked": 0,
            "duration_seconds": 0.0,
            # None, not False: nothing was written because nothing needed to be,
            # which is not the same as a write being suppressed.
            "applied": None,
            "applied_note": "",
            "details": [],
        }

    available = len(build_targets(matches_cache, bookmaker, base_url, live=mode == "live"))
    if available == 0:
        return {
            "bookmaker": bookmaker,
            "mode": mode,
            "status": "checked",
            "skip_reason": (
                f"no {bookmaker} match in the {mode} cache carries an event id — "
                "run a scan first"
            ),
            "criterion": CRITERION,
            "available": 0,
            "checked": 0,
            "verified": 0,
            "failed": 0,
            "errored": 0,
            "unchecked": 0,
            "duration_seconds": 0.0,
            "applied": None,
            "applied_note": "",
            "details": [],
        }

    # Charged here, not above: a book that declares no route and a cache with no
    # event ids both return without touching a browser, and a UI that probes
    # either would otherwise spend the budget doing nothing.
    _enforce_sliding_window(
        request, _verify_link_request_times, DEEP_LINK_VERIFY_RATE_LIMIT, "verify-links checks"
    )

    # One browser at a time, and never more than BROWSER_CONCURRENCY across the
    # whole server: a scan that starts after the 409 check above still finds its
    # browser budget respected here.
    async with _deep_link_check_lock:
        async with _browser_sem:
            report = await _run_link_verification(
                bookmaker, matches_cache, mode=mode, live=mode == "live", limit=limit
            )

    # A completed check is worth keeping even if a scan overtook us: the store is
    # per-event, TTL'd and written atomically, and the next scan applies it.
    _record_deep_link_outcomes(mode, bookmaker, report.outcomes)

    # Re-check AFTER the multi-minute await. The 409 above is a snapshot taken
    # minutes before the writes below, and overwriting a running scan's cache
    # would publish a half-written snapshot of a different feed.
    status_after, _, _, _, _ = _state_for(mode)
    scan_underway = _lock_for(mode).locked() or status_after.is_scanning
    applied = not scan_underway
    applied_note = ""
    if applied:
        apply_report(matches_cache, report)
        _apply_deep_link_verifications(matches_cache, mode)
        _save_cache(mode)
    else:
        applied_note = (
            f"a {mode} scan started while this check was running, so the cached "
            "matches were left untouched; the proof is stored and the next scan "
            "will apply it. Note the asymmetry: the store write is two-sided — a "
            "completed-FAIL pops the record — but _apply_deep_link_verifications "
            "only ever SETS a flag, so a stale deep_link_verified=True survives in "
            "the cache until a scan rebuilds that list from the scrapers"
        )

    logger.info(
        f"Deep-link check {bookmaker}/{mode}: {report.verified} verified, "
        f"{report.failed} failed, {report.errored} errored of {report.checked} checked "
        f"({report.unchecked} of {available} not checked) in {report.duration_seconds}s"
        f"{'' if applied else ' — cache write skipped'}"
    )
    return {
        "bookmaker": bookmaker,
        "mode": mode,
        "status": report.status,
        "skip_reason": report.skip_reason,
        "criterion": CRITERION,
        "available": available,
        "checked": report.checked,
        "verified": report.verified,
        "failed": report.failed,
        "errored": report.errored,
        "unchecked": report.unchecked,
        "duration_seconds": report.duration_seconds,
        "applied": applied,
        "applied_note": applied_note,
        "details": [
            {
                "event_id": outcome.event_id,
                "url": outcome.url,
                "verified": outcome.verified,
                "evidence": outcome.evidence,
                "error": outcome.error,
            }
            for outcome in report.outcomes
        ],
    }
