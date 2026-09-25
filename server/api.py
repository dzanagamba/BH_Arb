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
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from typing import Any, NamedTuple

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from rapidfuzz import fuzz

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
from engine.ai import MatchAI, PairProposal
from engine.arbitrage import ArbitrageEngine
from engine.certainty import CertaintyGate
from engine.market_registry import unmapped_markets
from engine.matcher import MatchMatcher
from models.schemas import CandidateReview, MarketType, Match, MatchGroup, ScanStatus
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
    directory = os.path.dirname(ALLOWLIST_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=".team_alias_allowlist.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"aliases": sorted(aliases)}, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, ALLOWLIST_FILE)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


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
# most plausible candidates are ranked first so a cap drops the weakest ones.
AI_CANDIDATE_RANK_CAP = 20
# Hard wall-clock ceiling so slow or timing-out calls cannot stall a scan.
AI_RANK_TIME_BUDGET_SECONDS = 90.0


class _TeamTokens(NamedTuple):
    """Pre-computed team strings and their token sets for the cheap prefilter."""

    home: str
    away: str
    home_tokens: frozenset[str]
    away_tokens: frozenset[str]
    all_tokens: frozenset[str]
    bigrams: frozenset[str]

    @classmethod
    def of(cls, match: Match) -> "_TeamTokens":
        home = match.home_team_normalized or match.home_team
        away = match.away_team_normalized or match.away_team
        home_tokens, away_tokens = frozenset(home.split()), frozenset(away.split())
        return cls(
            home, away, home_tokens, away_tokens, home_tokens | away_tokens,
            _bigrams(f"{home} {away}"),
        )


class _FoundPair(NamedTuple):
    """A queued candidate plus the evidence used to rank it."""

    candidate: CandidateReview
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
    """Return the character bigrams of a fixture string."""
    padded = f" {text} "
    return frozenset(padded[index:index + 2] for index in range(len(padded) - 1))


def _team_similarity(left: _TeamTokens, right: _TeamTokens) -> float:
    """Cheap prefilter: the best token-set overlap over both home/away orders.

    The token/bigram gate is what makes the ~745k cross-bookmaker comparisons of
    a real 7k-match scan affordable: it skips the fuzzy scorer for pairs sharing
    no token, no substring run and no character bigram. The bigram term is what
    keeps a single typo ("Millonarios" vs "Millionarios") in the queue, which a
    token-only gate would drop. On a real 7k-match scan the gate discarded 1,669
    pairs that the raw fuzzy score would have admitted; a sample of 25 were all
    different real-world fixtures ("Bury Town" vs "Exeter"), i.e. fuzzy
    false positives on short names, so nothing reviewable is lost.
    """
    if not (
        left.all_tokens & right.all_tokens
        or _token_run_shared(left, right)
        or left.bigrams & right.bigrams
    ):
        return 0.0
    best = 0.0
    for first, second, first_tokens, second_tokens in (
        (left.home, right.home, left.home_tokens, right.home_tokens),
        (left.home, right.away, left.home_tokens, right.away_tokens),
        (left.away, right.home, left.away_tokens, right.home_tokens),
        (left.away, right.away, left.away_tokens, right.away_tokens),
    ):
        if not (
            first_tokens & second_tokens
            or first_tokens <= second_tokens
            or second_tokens <= first_tokens
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
    approves.
    """
    gate = CertaintyGate(
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
                left_group = verified_in_group.get(_match_side_key(left))
                if left_group is not None and left_group == verified_in_group.get(
                    _match_side_key(right)
                ):
                    continue  # the matcher already proved this pairing
                result = gate.evaluate_pair(left, right)
                if result.status == "verified":
                    continue  # already handled by the matcher's verified group
                found.append(_FoundPair(
                    candidate=CandidateReview(
                        id=_candidate_id(pair_key),
                        home_team=left.home_team,
                        away_team=left.away_team,
                        league=left.league,
                        kickoff=left.kickoff,
                        bookmakers=sorted([left.bookmaker, right.bookmaker]),
                        ai_confidence=0.0,
                        ai_reason="",
                        rule_rejections=result.reasons,
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                    ),
                    kickoff_delta_minutes=_kickoff_delta_minutes(left, right),
                    team_similarity=similarity,
                    left=left,
                    right=right,
                ))

    # Tightest kickoff first, then the closest team strings: both the review
    # queue and the AI cap see the most plausible pairs at the top.
    found.sort(key=lambda pair: (
        pair.kickoff_delta_minutes, -pair.team_similarity, pair.candidate.id,
    ))
    candidates = {pair.candidate.id: pair.candidate for pair in found}
    logger.info(
        f"Review candidates: {len(candidates)} unverified pairs from {len(all_matches)} matches"
    )

    ai = MatchAI()
    if not ai.available:
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
        "unmapped_markets": dict(unmapped_markets),
        "verified_groups": sum(
            1
            for report in cached_match_groups_report
            if report.get("status") == "verified"
        ),
        "pending_candidates": len(pending_candidates),
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
async def get_candidates(mode: str = "prematch"):
    """List match candidates awaiting human review."""
    return {
        "count": len(pending_candidates),
        "candidates": [candidate.model_dump(mode="json") for candidate in pending_candidates.values()],
    }


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str,
    _auth: None = Depends(_require_api_key),
):
    """Approve a candidate as a human-reviewed team alias."""
    candidate = pending_candidates.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    alias = "|".join(sorted({candidate.home_team, candidate.away_team}))
    with _ALLOWLIST_LOCK:
        aliases = _load_allowlist()
        aliases.add(alias)
        _save_allowlist(aliases)

    candidate.status = "approved"
    candidate.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    candidate.resolved_by = "human"
    pending_candidates.pop(candidate_id, None)
    candidate_reviews.insert(0, candidate.model_copy(deep=True))
    return {"status": "approved", "allowlist_entries": [alias]}


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    _auth: None = Depends(_require_api_key),
):
    """Reject a pending match candidate without changing alias mappings."""
    candidate = pending_candidates.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate.status = "rejected"
    candidate.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    candidate.resolved_by = "human"
    pending_candidates.pop(candidate_id, None)
    candidate_reviews.insert(0, candidate.model_copy(deep=True))
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
