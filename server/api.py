"""FastAPI route handlers for the scanner, mounted under ``/api``.

This module is not an exhaustive route index: the running server documents every
route, its parameters and its response at ``/docs`` (OpenAPI). Read-only
diagnostics include ``/api/health``, ``/api/results``, ``/api/groups``,
``/api/candidates``, ``/api/history``, ``/api/mapping/coverage``,
``/api/debug/report`` and the ``/api/paper/*`` and ``/api/bets/*`` report views.
"""

import asyncio
import logging
import math
import os
import signal
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator, model_validator
from rapidfuzz import fuzz

from config.bookmakers import BROWSER_BOOKMAKERS
from config.settings import (
    API_KEY,
    AUTO_LEARN_MAPPINGS,
    AUTO_SCAN_LIVE_MINUTES,
    AUTO_SCAN_PREMATCH_MINUTES,
    BOOK_BACKOFF_AFTER_FAILURES,
    BOOK_BACKOFF_MAX_MINUTES,
    BOOK_STAKE_LIMITS,
    BOOKMAKERS,
    BROWSER_CONCURRENCY,
    CACHE_DIR,
    CACHE_SIZE_BUDGET_BYTES,
    CLOSING_CAPTURE_CUTOFF_MINUTES,
    COVERAGE_ALERT_CONSECUTIVE_SCANS,
    COVERAGE_FLAG_ALERT_THRESHOLD,
    DEEP_LINK_VERIFY_RATE_LIMIT,
    DEEPLINK_DECLARATION_MAX_AGE_DAYS,
    DEFAULT_INVESTMENT,
    DUST_PROFIT_PERCENT,
    ENABLED_MARKETS,
    ENABLED_SPORTS,
    EXPERIMENTAL_MARKETS,
    HEALTH_CACHE_SECONDS,
    LIVE_ODDS_TTL_SECONDS,
    MAPPING_COVERAGE_FLOOR,
    MAPPING_COVERAGE_MIN_ROWS,
    MIN_LEARN_MATCHES,
    MIN_PROFIT_PERCENT,
    ODDS_TTL_SECONDS,
    PRICE_GUARD_ENABLED,
    RATE_LIMIT_WINDOW_SECONDS,
    RSS_BUDGET_MB,
    SCAN_RATE_LIMIT,
    SCRAPER_SCAN_TIMEOUT_SECONDS,
    STALE_PRICE_UNCHANGED_SCANS,
    SUREBET_LINK_CHECK_MIN_INTERVAL_SECONDS,
    VERIFIED_KICKOFF_WINDOW_MINUTES,
    VERIFY_RATE_LIMIT,
    book_risk_profile,
)
from engine.admissibility import health_summary as admissibility_health
from engine.ai import MatchAI, PairProposal
from engine.arbitrage import ArbitrageEngine
from engine.candidate_remediation import (
    PROPOSAL_NOTE,
    alias_proposals,
    blocker_counts,
    group_candidates,
    league_proposal,
    remediation_counts,
    remediation_summary,
)
from engine.certainty import CertaintyGate
from engine.coverage_budget import (
    cardinality_book_reasons as cardinality_quarantine_reasons,
)
from engine.coverage_budget import (
    cardinality_snapshot,
    evaluate_cardinality,
    push_cardinality_history,
)
from engine.coverage_budget import (
    evaluate as evaluate_coverage_budget,
)
from engine.coverage_budget import (
    mapping_coverage as evaluate_mapping_coverage,
)
from engine.coverage_budget import (
    push_history as push_coverage_history,
)
from engine.coverage_budget import (
    snapshot as coverage_snapshot,
)
from engine.deeplinks import (
    declaration_audit,
    deeplink_declaration_source,
    effective_deeplink_declarations,
    settle_link,
)
from engine.feed_integrity import (
    compute_feed_integrity,
    priceable_groups,
    quarantined_books,
)
from engine.mapping_evidence import MappingLedger
from engine.mapping_learner import learn
from engine.market_registry import unmapped_by_book, unmapped_markets
from engine.matcher import MatchMatcher, swap_match_teams_and_odds
from engine.name_keys import raw_team_key
from engine.opportunity_metrics import (
    ScanMetrics,
    lifetime_distribution,
    summarize_scan,
    update_lifetimes,
)
from engine.parser_contracts import contract_health
from engine.price_guard import filter_price_outliers
from engine.pricing_invariant import (
    implied_sum,
    round_stake,
    rounding_summary,
)
from engine.skin_detection import (
    apply_measured_twins,
    declared_twin_warnings,
    measure_price_agreement,
)
from engine.skin_detection import (
    summary as skin_summary,
)
from engine.stale_price import REASON_LABEL as STALE_PRICE_LABEL
from engine.stale_price import evaluate_stale_prices
from engine.structural_drift import begin_scan as begin_structural_drift_scan
from models.schemas import (
    CandidateRemediation,
    CandidateReview,
    MarketType,
    Match,
    MatchGroup,
    PairSide,
    ScanStatus,
    TeamPositionPair,
)
from scrapers.breaker import CLOSED, HALF_OPEN, OPEN, BookCircuitBreaker, breaker_for
from scrapers.browser_pool import browser_pool
from scrapers.cost import (
    begin_book,
    build_scan_report,
    finish_book,
)
from scrapers.errors import (
    ScrapeKind,
    classify_exception,
    classify_scrape,
    legacy_outcome,
)
from scrapers.forensics import artefact_summary, take_artefacts
from scrapers.registry import SCRAPERS
from scrapers.transport import policy_for, transport_pool
from server.alerts import (
    AlertManager,
    book_failure_alert,
    configured_alert_manager,
    coverage_drop_alerts,
    current_rss_mb,
    feed_alerts,
    mapping_coverage_alert,
    quarantine_alerts,
    resource_alerts,
    surebet_alert,
    zero_result_alert,
)
from server.auth import SCOPES, api_key_store, resolve_api_key
from server.bets import BetStore
from server.book_health import build_book_health
from server.candidate_scoring import (
    FoundPair,
    TeamTokens,
    candidate_id,
    canonical_pair_key,
    kickoff_bucket,
    kickoff_delta_minutes,
    match_event_ref,
    match_side_key,
    pair_priority,
    team_similarity,
)
from server.json_store import atomic_write_json, read_json
from server.maintenance import maintenance_running, retention_health
from server.mapping_coverage import build_coverage, load_ledger
from server.observability import (
    metrics,
    new_request_id,
    reset_scan_id,
    set_scan_id,
)
from server.pairing_audit import audit as audit_pairing
from server.paper import PaperStore
from server.scan_cost import book_failure_rates
from server.storage import Storage, default_storage_path
from server.timeutil import naive_utc as _naive_utc
from server.timeutil import utcnow

logger = logging.getLogger(__name__)
router = APIRouter()
alert_manager: AlertManager = configured_alert_manager()

# The two independent feeds. A query parameter typed with this is validated by
# FastAPI (422 on anything else) instead of silently falling back to prematch.
ScanMode = Literal["prematch", "live"]


def _require_api_key(
    request: Request,
    x_api_key: str = Header(default=""),
) -> None:
    """Resolve the env bootstrap key or a named hashed key into request state.

    The `api_key_guard` middleware normally does this for every /api route; this
    dependency reuses its result and only resolves on its own when a route is
    exercised without the middleware (a direct call in a test). With neither key
    configured the historic local-only behaviour remains: the request gets every
    scope, which is safe only because the documented default bind is loopback.
    """
    if getattr(request.state, "api_key_scopes", None) is not None:
        return
    if not API_KEY and not api_key_store.has_any_keys():
        request.state.api_key_id = ""
        request.state.api_key_scopes = set(SCOPES)
        return
    resolved = resolve_api_key(x_api_key, env_key=API_KEY, store=api_key_store)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    request.state.api_key_id = resolved.key_id
    request.state.api_key_scopes = set(resolved.scopes)


def _require_scope(scope: str):
    """FastAPI dependency factory for a named-key/admin scope."""

    def dependency(
        request: Request,
        _auth: None = Depends(_require_api_key),
    ) -> None:
        if scope not in getattr(request.state, "api_key_scopes", set()):
            raise HTTPException(
                status_code=403,
                detail=f"This API key lacks the {scope!r} scope",
            )

    return dependency

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
# SR2-5: after the scan deadline cancels the books still running, wait only this
# long for their cleanup (a browser close). A wedged Playwright close must not
# turn the deadline into a second hang; the transport pool closes the HTTP
# clients regardless.
_DEADLINE_CLEANUP_SECONDS = 30.0

# SR6-1: derived from config/bookmakers.py, never a second list.
PLAYWRIGHT_BOOKIES = BROWSER_BOOKMAKERS

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
        saved = read_json(_MARKET_STATE_FILE)
        if saved is not None:
            for market, state in saved.items():
                if market in _market_enabled and isinstance(state, bool):
                    _market_enabled[market] = state
            logger.info(f"Restored experimental market toggles: {_market_enabled}")
    except Exception as e:
        logger.warning(f"Market state load failed: {e}")


def _save_market_state() -> None:
    """Persist runtime experimental-market toggles to the state file."""
    try:
        atomic_write_json(_MARKET_STATE_FILE, _market_enabled, "market_state")
    except Exception as e:
        logger.warning(f"Market state save failed: {e}")


def _enabled_markets() -> set[str]:
    """Markets the engine should detect: ENABLED_MARKETS + toggled experimental."""
    return set(ENABLED_MARKETS) | {m for m, on in _market_enabled.items() if on}


def _load_bookmaker_state() -> None:
    """Restore runtime bookmaker toggles from the state file on startup."""
    global _bookmaker_enabled
    try:
        saved = read_json(_BOOKMAKER_STATE_FILE)
        if saved is not None:
            for bid, state in saved.items():
                if bid in _bookmaker_enabled and isinstance(state, bool):
                    _bookmaker_enabled[bid] = state
            logger.info(f"Restored bookmaker toggles: {_bookmaker_enabled}")
    except Exception as e:
        logger.warning(f"Bookmaker state load failed: {e}")


def _save_bookmaker_state() -> None:
    """Persist runtime bookmaker toggles to the state file."""
    try:
        atomic_write_json(_BOOKMAKER_STATE_FILE, _bookmaker_enabled, "bookmaker_state")
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
_pairing_summary: dict[str, dict[str, Any]] = {}
# N2-3: bounded per-scan strict-miss trend, newest last. Each point carries the
# numerator and denominator of the scan it describes, so a drop cannot be read
# without its sample size.
_pairing_trend: dict[str, list[dict[str, Any]]] = {"prematch": [], "live": []}
_PAIRING_TREND_MAX = 100
# N2-3: bounded per-scan candidate blocker groups, newest last. A group is a
# review-work ranking, never a coverage-progress claim.
_candidate_blocker_trend: dict[str, list[dict[str, Any]]] = {
    "prematch": [],
    "live": [],
}
_CANDIDATE_TREND_MAX = 100
cached_per_bookie: dict[str, int] = {}  # bookmaker_id -> match count
cached_live_surebets: list[dict] = []
cached_live_matches: list[dict] = []
cached_live_match_groups_report: list[dict] = []
cached_live_per_bookie: dict[str, int] = {}
scan_history: list[dict] = []           # recent scan entries (newest first)

# One review queue per feed: a live scan rebuilds only the live queue, so it can
# no longer wipe the prematch queue a reviewer is working through.
pending_candidates: dict[str, CandidateReview] = {}        # prematch
pending_live_candidates: dict[str, CandidateReview] = {}   # live
# M2-4: the found/retained/dropped numbers of the last scan, per feed. The
# retained queue alone cannot answer "how many were found", and the cap must not
# be silent, so these are kept next to it.
candidate_totals: dict[str, dict[str, int]] = {}


def _candidates_for(mode: str) -> dict[str, CandidateReview]:
    return pending_live_candidates if mode == "live" else pending_candidates


def _find_pending_candidate(candidate_id: str) -> dict[str, CandidateReview] | None:
    """Return the queue that holds `candidate_id`, whichever feed it came from."""
    for queue in (pending_candidates, pending_live_candidates):
        if candidate_id in queue:
            return queue
    return None
last_learning_report: dict[str, Any] = {}
# Scheduled-scan per-book state lives in the SR2-6 breakers
# (`scrapers.breaker.breaker_for`); manual scans ignore it.
# Candidates a human has already decided on, keyed by the deterministic pair id.
# Without this a decided pair is rebuilt into the queue on every scan and can be
# approved again forever, so the review loop could never converge.
SUPPRESSED_CANDIDATES_FILE = os.path.join(CACHE_DIR, "suppressed_candidates.json")
_suppressed_candidates: dict[str, str] = {}
# The system-owned state each decision above was made on, so a record stops
# applying when the system moves that state on its own. See `_decision_premise`.
_suppressed_premises: dict[str, str] = {}
_SUPPRESSED_LOCK = threading.Lock()


def _using_default_decision_store() -> bool:
    """True when the process uses the shipped decision file, not a test temp."""
    return _storage is not None and os.path.abspath(SUPPRESSED_CANDIDATES_FILE) == os.path.abspath(
        os.path.join(CACHE_DIR, "suppressed_candidates.json")
    )


def _load_suppressed_candidates() -> dict[str, str]:
    """Return decided candidate ids mapped to the decision ("approved"/"rejected")."""
    if _using_default_decision_store():
        try:
            stored = _storage.decisions() if _storage is not None else {}
        except Exception as exc:
            logger.warning("Decision SQLite read failed: %s", exc)
        else:
            if stored:
                return stored
    data = read_json(SUPPRESSED_CANDIDATES_FILE)
    decisions = data.get("decisions") if isinstance(data, dict) else None
    if not isinstance(decisions, dict):
        # A file written before premises existed: a flat id -> decision map.
        decisions = data
    if not isinstance(decisions, dict):
        return {}
    return {
        candidate_id: decision
        for candidate_id, decision in decisions.items()
        if isinstance(candidate_id, str) and decision in ("approved", "rejected")
    }


def _load_suppressed_premises() -> dict[str, str]:
    """Return the premise each recorded decision was made on, where one was kept.

    Empty for a file written before premises existed, and such a record is then
    honoured exactly as it was written.
    """
    if _using_default_decision_store():
        try:
            stored = _storage.decision_premises() if _storage is not None else {}
        except Exception as exc:
            logger.warning("Decision premise SQLite read failed: %s", exc)
        else:
            if stored:
                return stored
    data = read_json(SUPPRESSED_CANDIDATES_FILE)
    premises = data.get("premises") if isinstance(data, dict) else None
    if not isinstance(premises, dict):
        return {}
    return {
        candidate_id: premise
        for candidate_id, premise in premises.items()
        if isinstance(candidate_id, str) and isinstance(premise, str)
    }


def _save_suppressed_candidates() -> None:
    atomic_write_json(
        SUPPRESSED_CANDIDATES_FILE,
        {
            "decisions": dict(sorted(_suppressed_candidates.items())),
            "premises": dict(sorted(_suppressed_premises.items())),
        },
        "suppressed_candidates",
    )


def _suppress_candidate(candidate_id: str, decision: str, premise: str = "") -> None:
    """Record a human decision so the pair is not re-queued on the next scan.

    `premise` is the system-owned state the decision was taken on, so the record
    stops applying once that state moves on its own. Pass "" to record a decision
    that holds unconditionally.
    """
    with _SUPPRESSED_LOCK:
        _suppressed_candidates[candidate_id] = decision
        if premise:
            _suppressed_premises[candidate_id] = premise
        else:
            _suppressed_premises.pop(candidate_id, None)
        if _using_default_decision_store() and _storage is not None:
            try:
                _storage.upsert_decision(candidate_id, decision, premise)
            except Exception as exc:  # the JSON export remains authoritative
                logger.warning("Decision SQLite write failed: %s", exc)
        _save_suppressed_candidates()


_HISTORY_FILE = os.path.join(CACHE_DIR, "scan_history.json")
_HISTORY_MAX = 50
# P3-1: SQLite is the query store; the JSON files stay compatibility exports.
_storage: Storage | None = None
_bet_store: BetStore | None = None
# P3-7: record-only and paper scans write here, never to the live surebet list.
_paper_store: PaperStore | None = None
# N0-4: last scan's closing-line capture counts, per feed.
_closing_capture: dict[str, dict[str, Any]] = {"prematch": {}, "live": {}}
RUN_MODES = ("advisory", "record_only", "paper")
_last_run_mode: dict[str, str] = {"prematch": "advisory", "live": "advisory"}
_recorded_counts: dict[str, int] = {"prematch": 0, "live": 0}
_LINK_SWEEP_FILE = os.path.join(CACHE_DIR, "link_sweeps.json")
_LINK_SWEEP_MAX = 200
_PREMATCH_CACHE_FILE = os.path.join(CACHE_DIR, "last_scan.json")
_LIVE_CACHE_FILE = os.path.join(CACHE_DIR, "last_live_scan.json")
# P0-6: compact per-scan aggregates plus the bounded crossing-key store. The
# full board remains in the scan cache; this file never duplicates it.
_OPPORTUNITY_METRICS_FILE = os.path.join(CACHE_DIR, "opportunity_metrics.json")
_opportunity_by_mode: dict[str, dict] = {}
_crossing_lifetimes: dict[str, dict[str, dict]] = {"prematch": {}, "live": {}}
# P0-7: per-book integrity state, one scorecard per feed, with bounded history.
_FEED_INTEGRITY_FILE = os.path.join(CACHE_DIR, "feed_integrity.json")
_COVERAGE_BUDGET_FILE = os.path.join(CACHE_DIR, "coverage_budget.json")
# N1-3: bounded per-scan per-book cost history. Counts/durations only.
_SCAN_COST_FILE = os.path.join(CACHE_DIR, "scan_cost.json")
# N0-2: bounded per-book price observations and the rows refused this scan.
_STALE_PRICE_FILE = os.path.join(CACHE_DIR, "stale_price_state.json")
_stale_price_store: dict[str, dict[str, dict]] = {"prematch": {}, "live": {}}
_stale_price_evidence: dict[str, list[dict]] = {"prematch": [], "live": []}
_stale_price_checked_at: dict[str, str] = {"prematch": "", "live": ""}
_coverage_budget: dict[str, dict[str, Any]] = {"prematch": {}, "live": {}}
_coverage_history: dict[str, list[dict[str, int]]] = {
    "prematch": [],
    "live": [],
}
_COVERAGE_HISTORY_MAX = 20
# SR4-5: event/market cardinality per book+sport, with the same bounded
# rolling history. A flag quarantines through feed integrity; never a second
# trust gate.
_cardinality: dict[str, dict[str, Any]] = {"prematch": {}, "live": {}}
_cardinality_history: dict[str, list[dict[str, dict[str, int]]]] = {
    "prematch": [],
    "live": [],
}
# N1-2: per-scan mapping coverage, the bounded trend and the consecutive
# zero-result counters. These are diagnostics, never trust inputs.
_mapping_coverage: dict[str, dict[str, Any]] = {"prematch": {}, "live": {}}
_coverage_trend: dict[str, list[dict[str, Any]]] = {"prematch": [], "live": []}
_COVERAGE_TREND_MAX = 30
_zero_result_streaks: dict[str, dict[str, int]] = {"prematch": {}, "live": {}}
_ZERO_RESULT_ALERT_REASONS = frozenset({"stale_data", "no_priced_boards"})
# N1-3: current scan cost per mode and a bounded newest-first history.
_scan_cost: dict[str, dict[str, Any]] = {"prematch": {}, "live": {}}
_scan_cost_history: list[dict[str, Any]] = []
_SCAN_COST_HISTORY_MAX = 500
_feed_integrity: dict[str, dict[str, dict]] = {"prematch": {}, "live": {}}
# P2-7: the measured price-agreement matrix and its config-mismatch warnings.
_skin_detection: dict[str, dict[str, Any]] = {"prematch": {}, "live": {}}
# Aggregates only, one compact row per completed scan. The cap is a storage
# bound, not a retention promise; the 7-day report filters by scan_time.
_OPPORTUNITY_HISTORY_MAX = 2_000
_opportunity_history: list[dict] = []


class FeedState(NamedTuple):
    """Everything one feed's last scan left in memory (M3-1 stage 2).

    The five values always travel together and every route answers for exactly
    one feed, so they are one named object rather than an anonymous tuple. A
    NamedTuple keeps tuple unpacking working for the scripts and tests written
    before this type existed, while new code reads `state.matches` directly.
    """

    status: ScanStatus
    surebets: list[dict]
    matches: list[dict]
    report: list[dict]
    per_bookie: dict[str, int]


def _state_for(mode: str) -> FeedState:
    """Return the state of one feed: status, results and per-book counts."""
    if mode == "live":
        return FeedState(
            live_status,
            cached_live_surebets,
            cached_live_matches,
            cached_live_match_groups_report,
            cached_live_per_bookie,
        )
    return FeedState(
        scan_status,
        cached_surebets,
        cached_matches,
        cached_match_groups_report,
        cached_per_bookie,
    )


def _paper_store_or_init() -> PaperStore:
    """Return the paper ledger, initializing it on first use."""
    global _paper_store
    if _paper_store is None:
        _paper_store = PaperStore(default_storage_path())
        _paper_store.initialize()
    return _paper_store


def _bet_store_or_init() -> BetStore:
    """Return the manual bet log, initializing it on first use."""
    global _bet_store
    if _bet_store is None:
        _bet_store = BetStore(default_storage_path())
        _bet_store.initialize()
    return _bet_store


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
#
# TWO STORES, because the check answers two different questions and the sweep
# needs both:
#
# * `_deep_link_verifications` — PROOFS. "This link served this event." A
#   completed check that found nothing DELETES the entry, which is how a stale
#   proof is cleared. So this store cannot answer "did we look at it?", only
#   "did it pass?".
# * `_deep_link_decisions` — DECISIONS. "We looked at this event and reached a
#   verdict", including a verdict of `verified=False`. Without it, a book whose
#   links do not verify stores nothing at all and the sweep re-checks its first
#   `limit` events forever — the defect this store exists to close.
#
# Both are keyed `bookmaker|event_id`, both expire — on DIFFERENT clocks, and
# asymmetrically, because they are not the same kind of claim (see the lifetimes
# below) — and neither may be written from an ERRORED check: a navigation that
# never completed is neither a proof nor a failure, and treating it as either
# would drop an event that still needs checking.
# ---------------------------------------------------------------------------
DEEP_LINK_VERIFICATIONS_FILE = os.path.join(CACHE_DIR, "deep_link_verifications.json")
DEEP_LINK_DECISIONS_FILE = os.path.join(CACHE_DIR, "deep_link_decisions.json")
# A stored record may only keep unblocking `verified` while it is inside its
# lifetime, and BOTH lifetimes below are chosen against ONE measured number: how
# long a full pass over a book costs.
#
# THE MEASUREMENT (2026-09-26, from the live store): mozzartbet published 1,236
# prematch events with per-event ids; the sweep decided exactly 20 per call across
# 21 calls; the gap between one call finishing and the next had a median of 89.6s
# and spanned 83.6s-302.2s, the top two being operator pauses. So a pass is ~92
# minutes, and at 02:44 the newest of 412 stored proofs was 75 minutes old. Both
# lifetimes were then 60 minutes. A pass therefore could not hold its own result:
# the first proof a pass wrote died 32 minutes before the pass ended, the last
# proof died 32 minutes after, and at every moment in between no book held a
# complete set — so no group could reach `verified` and no surebet could exist.
# The pipeline was correct and unreachable.
#
# So the requirement is the same for both stores and it is not negotiable: one
# pass must fit inside the lifetime of what that pass writes. Both are stated in
# hours because the fact being certified — "this book still serves a per-event
# route for this id" — is a structural fact about a bookmaker's site, not a
# per-minute market reading, and it is the only thing either lifetime is guarding.
#
#   decision 6h  — a decision carries no verdict, only "a check completed", so it
#                  needs to outlive one pass and nothing more. It has a hard
#                  functional cost when it is too short: `_decided_event_ids`
#                  reads it, so a book whose first decisions expire mid-pass is
#                  offered them again before the pass reaches the back, and the
#                  sweep walks in circles and never reports itself converged. It
#                  has no safety cost at any length, because granting nothing is
#                  what a decision does.
#   proof     24h  — a proof is a POSITIVE fact and outlives the decision that
#                  produced it by 4x. A book's routes changing is a site change,
#                  not a market tick; a day is the order of magnitude, and it is
#                  15.6x the measured pass, so it absorbs a book growing to ~19,000
#                  events before it stops being true. The sweep, not the TTL, is
#                  what keeps this honest: a book that is being swept has its
#                  whole decision set expire every 6h, so a route that dies is
#                  caught within one decision lifetime plus one pass, and the 24h
#                  ceiling only ever binds on a book nobody has swept.
#
# What this does NOT buy, stated plainly: for a book nobody sweeps, a proof that
# has stopped being true can keep a group `verified` for up to 24h where it was
# 1h. The four things that stay in place are what keep that from being a wrong
# bet rather than a dead link — a retired event drops out of the feed on the next
# scan, a completed check that finds nothing POPS the proof, `?recheck=1` is the
# way back to a decided event, and the surebet itself is separately bounded by
# `EXPIRY_BUFFER_MINUTES` on kickoff and by `ODDS_TTL_SECONDS` on every leg.
DEEP_LINK_VERIFICATION_TTL_SECONDS = 24 * 3600
DEEP_LINK_DECISION_TTL_SECONDS = 6 * 3600
DEEP_LINK_VERIFY_DEFAULT_LIMIT = 5
DEEP_LINK_VERIFY_MAX_LIMIT = 20
_deep_link_verifications: dict[str, dict[str, dict]] = {}
_deep_link_decisions: dict[str, dict[str, dict]] = {}
_DEEP_LINK_LOCK = threading.Lock()
# One browser at a time: the check is the most expensive thing this server does.
# Serialising is not throttling, hence DEEP_LINK_VERIFY_RATE_LIMIT as well.
_deep_link_check_lock = asyncio.Lock()
# Per-client-IP window for the deep-link check, separate from the scan's.
_verify_link_request_times: dict[str, list[float]] = {}


def _deep_link_key(bookmaker: str, event_id: str) -> str:
    """Return the store key for one bookmaker's one event."""
    return f"{bookmaker}|{event_id}"


def _deep_link_record_is_fresh(record: dict | None, now: datetime | None = None) -> bool:
    """Return whether a stored verification is still inside its TTL.

    `None` is accepted so a caller may pass a lookup that missed without
    pre-checking it: a missing record is not a fresh record, and that is the
    whole answer.
    """
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
        checked_at = _naive_utc(checked_at)
    reference = now or utcnow()
    age = (reference - checked_at).total_seconds()
    return 0 <= age <= DEEP_LINK_VERIFICATION_TTL_SECONDS


def _load_deep_link_verifications() -> dict[str, dict[str, dict]]:
    """Load the store, dropping entries that are malformed or past their TTL."""
    state: dict[str, dict[str, dict]] = {}
    data = read_json(DEEP_LINK_VERIFICATIONS_FILE)
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
    atomic_write_json(DEEP_LINK_VERIFICATIONS_FILE, state, "deep_link_verifications")


def _record_deep_link_outcomes(mode: str, bookmaker: str, outcomes: list) -> None:
    """Store what a verification run proved, per mode.

    A proven link is recorded with a timestamp. A COMPLETED check that found
    nothing removes the entry, which is how a stale verification is cleared. A
    check that errored is ignored: absence of evidence is not evidence of
    absence, so a timeout must never revoke a proof.
    """
    now = utcnow().isoformat()
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


def _deep_link_decision_is_fresh(record: dict, now: datetime | None = None) -> bool:
    """Return whether a stored DECISION is still inside its TTL.

    A decision carries no verdict, so there is nothing to check but the
    timestamp — the point of the record is that a check COMPLETED, and that is
    only true for as long as the operator is expected to trust it.
    """
    if not isinstance(record, dict):
        return False
    raw = record.get("checked_at")
    if not isinstance(raw, str):
        return False
    try:
        checked_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if checked_at.tzinfo is not None:
        checked_at = _naive_utc(checked_at)
    reference = now or utcnow()
    age = (reference - checked_at).total_seconds()
    return 0 <= age <= DEEP_LINK_DECISION_TTL_SECONDS


def _load_deep_link_decisions() -> dict[str, dict[str, dict]]:
    """Load the decision store, dropping entries that are malformed or past TTL."""
    state: dict[str, dict[str, dict]] = {}
    data = read_json(DEEP_LINK_DECISIONS_FILE)
    if not isinstance(data, dict):
        return state
    for mode, entries in data.items():
        if not isinstance(mode, str) or not isinstance(entries, dict):
            continue
        fresh = {k: v for k, v in entries.items() if isinstance(k, str)
                 and _deep_link_decision_is_fresh(v)}
        if fresh:
            state[mode] = fresh
    return state


def _save_deep_link_decisions(state: dict[str, dict[str, dict]]) -> None:
    atomic_write_json(DEEP_LINK_DECISIONS_FILE, state, "deep_link_decisions")


def _record_deep_link_decisions(mode: str, bookmaker: str, outcomes: list) -> None:
    """Record which events a run reached a VERDICT on, per mode.

    Completed checks only. An errored check is recorded nowhere, which is what
    keeps the event eligible: a navigation that never completed decided nothing,
    so the next call must offer it again.

    Expired decisions are dropped on the way out, so a long-lived server's file
    cannot grow without bound.
    """
    now = utcnow()
    now_iso = now.isoformat()
    with _DEEP_LINK_LOCK:
        entries = _deep_link_decisions.setdefault(mode, {})
        for outcome in outcomes:
            if outcome.error:
                continue
            entries[_deep_link_key(bookmaker, outcome.event_id)] = {"checked_at": now_iso}
        fresh = {k: v for k, v in entries.items() if _deep_link_decision_is_fresh(v, now)}
        if len(fresh) != len(entries):
            entries.clear()
            entries.update(fresh)
        _save_deep_link_decisions(_deep_link_decisions)


def _decided_event_ids(
    mode: str, bookmaker: str, now: datetime | None = None
) -> set[str]:
    """Return the event ids this book has already been CHECKED on, in one mode.

    Read from the DECISION store and from nothing else — deliberately. A proof
    says the check passed, but the sweep's question is "did we look at it?", and
    conflating the two takes away a capability the store depends on: a link that
    has been proven can only STOP unblocking a `verified` group if it can be
    checked again and fail, so a decided event must be re-offered deliberately
    (`?recheck=1`) rather than being unable to be re-checked at all. The two
    stores now expire on different clocks, and that is no reason to read both:
    a completed check writes both, so the decision store alone still knows
    everything the sweep needs.

    Book-scoped (`bookmaker|event_id`), per mode, and TTL-filtered: another
    book's decisions, another mode's, and anything stale are all absent. The TTL
    is also what makes a pass finishable — see `DEEP_LINK_DECISION_TTL_SECONDS`,
    which is longer than a measured pass for exactly this reason.
    """
    reference = now or utcnow()
    prefix = f"{bookmaker}|"
    return {
        key[len(prefix):]
        for key, record in (_deep_link_decisions.get(mode) or {}).items()
        if key.startswith(prefix) and _deep_link_decision_is_fresh(record, reference)
    }


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
    reference = now or utcnow()
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
    offset: int = 0,
    settled: set[str] | frozenset[str] = frozenset(),
):
    """Run the Playwright deep-link check. The endpoint's only browser seam."""
    from server.deeplink_verifier import verify_bookmaker

    return await verify_bookmaker(
        bookmaker, matches, mode=mode, live=live, limit=limit, offset=offset, settled=settled
    )


def _load_history() -> None:
    """Restore scan history, migrating the JSON store into SQLite once."""
    global scan_history, _storage, _bet_store, _paper_store
    try:
        if _bet_store is None:
            _bet_store = BetStore(default_storage_path())
            _bet_store.initialize()
        if _paper_store is None:
            _paper_store = PaperStore(default_storage_path())
            _paper_store.initialize()
        if _storage is None:
            _storage = Storage(default_storage_path())
            _storage.initialize()
            migrated = _storage.migrate_json(
                history_path=_HISTORY_FILE,
                decisions_path=SUPPRESSED_CANDIDATES_FILE,
            )
            logger.info(
                "Storage ready: %s scan rows, %s decisions migrated",
                migrated["scans"],
                migrated["decisions"],
            )
        rows = _storage.list_scans(limit=_HISTORY_MAX)
        if rows:
            scan_history = rows
        elif os.path.exists(_HISTORY_FILE):
            loaded = read_json(_HISTORY_FILE)
            if isinstance(loaded, list):
                scan_history = loaded
        logger.info("Loaded %s scan history entries", len(scan_history))
    except Exception as e:
        logger.warning(f"History load failed: {e}")


def _save_history() -> None:
    """Persist the JSON compatibility export."""
    try:
        atomic_write_json(_HISTORY_FILE, scan_history, "scan_history")
    except Exception as e:
        logger.warning(f"History save failed: {e}")


def _append_history(num_groups: int, mode: str) -> None:
    """Record the completed scan in history (newest first)."""
    state = _state_for(mode)
    entry = {
        "mode": mode,
        "scan_time": state.status.last_scan_time.isoformat() if state.status.last_scan_time else utcnow().isoformat(),
        "total_matches": state.status.total_matches,
        "match_groups": num_groups,
        "surebets_found": state.status.surebets_found,
        "per_bookie": dict(state.per_bookie),
        "errors": list(state.status.errors),
        # M2-4: `candidate_queue` keeps its old meaning — every pair the walk
        # found, not the capped queue — so old and new rows stay comparable. The
        # retained split lives in `candidate_retained` (JSON export; the SQLite
        # schema keeps its fixed columns).
        "candidate_queue": int(
            (candidate_totals.get(mode) or {}).get("found")
            or len(_candidates_for(mode))
        ),
        "candidate_actionable": int(
            (candidate_totals.get(mode) or {}).get("actionable_found")
            or sum(
                1
                for candidate in _candidates_for(mode).values()
                if candidate.alias_actionable
            )
        ),
        "candidate_retained": len(_candidates_for(mode)),
    }
    scan_history.insert(0, entry)
    del scan_history[_HISTORY_MAX:]
    if _storage is not None:
        try:
            _storage.append_scan(entry)
        except Exception as exc:  # the JSON export still carries the row
            logger.warning("Scan history SQLite append failed: %s", exc)
    _save_history()


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------
# A candidate is a same-event claim the certainty gate refused. It is queued for
# a human reviewer; nothing in this section can approve one, and the AI adapter
# only attaches an opinion to a pairing that already exists.

CANDIDATE_KICKOFF_WINDOW_MIN = 30   # wider than verified (15) so near-misses become review items
CANDIDATE_TEAM_SIM_MIN = 70
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
# M2-4: the RETAINED queue is capped. The operator's history peaked at 14,249
# pairs of which at most 473 were actionable, and every poll walked all of them.
# The cap keeps the top N in the existing priority order and the found/retained/
# dropped numbers are reported, so nothing is trimmed silently. 0 disables it.
CANDIDATE_QUEUE_MAX = int(os.getenv("CANDIDATE_QUEUE_MAX", "2000"))
# The pair walk trims its transient list to this multiple of the cap, so a
# 14k-pair scan does not have to hold every Pair before it is trimmed once. The
# trim uses the same total order, so the final top N is identical.
CANDIDATE_TRIM_FACTOR = 4

# Reasons the gate raises only because a bookmaker's event link is unproven.
# They come from the per-book deep-link system check, never from a name, so no
# human decision can clear them.
LINK_REJECTION_REASONS = frozenset({"link_unverified", "no_event_link"})
RemediationAction = Literal["alias", "league", "alias+league", "none"]


def _decision_premise(link_blocked: bool) -> str:
    """The system-owned state a human decision about a pair was taken on.

    Only state the system changes by itself belongs here. Anything the decision
    itself changes must stay out: an approval grants the team aliases, which
    clears `team_unresolved` from the next scan's reason list, so recording that
    would make every approval contradict its own record and the pair would never
    leave the queue.

    `link_blocked` is the opposite case. It moves when the per-book deep-link
    check passes, with no human involved, and it is the state a reviewer is most
    likely to have decided against — a card that said only the system check could
    clear the pair. Once the check has passed, the pair is one an approval really
    does clear, so the old decision no longer describes it.
    """
    return f"link_blocked={int(link_blocked)}"


def _decision_still_stands(candidate_id: str, link_blocked: bool) -> bool:
    """Whether a recorded decision still describes the claim the pair makes now.

    A record with no premise was written before this check existed; it is honoured
    exactly as it was.
    """
    recorded = _suppressed_premises.get(candidate_id)
    return recorded is None or recorded == _decision_premise(link_blocked)


def _verified_group_index(groups: list[MatchGroup]) -> dict[str, int]:
    """Map each match the matcher verified to the group that verified it."""
    index: dict[str, int] = {}
    for number, group in enumerate(groups):
        for match in group.matches:
            index.setdefault(match_side_key(match), number)
    return index


def _alias_name_key(name: str) -> str:
    """The form a name is compared in inside the reviewed allowlist.

    It is the gate's own key, so an entry the reviewer writes is compared
    exactly as the gate will compare it.
    """
    return raw_team_key(name)


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

    Asked of `gate` itself rather than of a copy of its rules, with only those
    aliases granted and with both links marked verified, which is the state the
    per-book deep-link system check produces. True means the gate answers
    ``verified`` for that state, so the human sees the same verdict the next scan
    gives. Anything short of ``verified`` — a kickoff no approval can move, a
    league mismatch, a name pair the reviewed-alias similarity cannot carry — is
    not something an approval fixes, so the candidate is not advertised as
    actionable.

    `gate` must therefore be built by `_what_if_gate`, which is configured exactly
    as the gate the scan decides with — same kickoff window, same league
    equivalences. A wider window here would answer "yes" for a pair the real gate
    still refuses, and the card would promise a fix that does not exist.
    """
    if not set(reasons) <= LINK_REJECTION_REASONS | {"team_unresolved"}:
        return False
    entries = _alias_entries(positions)
    if not entries:
        return False
    gate.alias_allowlist = set(entries)
    linked = [match.model_copy(update={"deep_link_verified": True}) for match in (left, right)]
    return gate.evaluate_pair(linked[0], linked[1]).status == "verified"


def _what_if_action(
    reasons: list[str],
    alias_entries: list[str],
    league_pair: tuple[str, str] | None,
    left: Match,
    right: Match,
    gate: CertaintyGate,
    *,
    alias_actionable: bool,
    base_equivalences: set[tuple[str, str]],
) -> RemediationAction:
    """Which mapping, if either, would clear the pair — as a proposal only.

    ``alias_actionable`` is the existing, conservative answer for a team-alias
    approval. A league equivalence is a second kind of mapping a human can
    supply, so it is asked the same way: grant only that mapping, mark both
    links verified (the state the system check produces), and read the gate's
    verdict. The gate instance is reused, so every evaluation resets the
    aliases and equivalences to a known base; nothing is persisted.
    """
    human = set(reasons) - LINK_REJECTION_REASONS
    if not human <= {"team_unresolved", "league_mismatch"}:
        return "none"
    if alias_actionable:
        return "alias"
    if league_pair is None or "league_mismatch" not in reasons:
        return "none"

    def verified_with(aliases: list[str], league: tuple[str, str] | None) -> bool:
        gate.alias_allowlist = set(aliases)
        gate.league_equivalences = set(base_equivalences)
        if league is not None:
            gate.league_equivalences.add(league)
        linked = [
            match.model_copy(update={"deep_link_verified": True})
            for match in (left, right)
        ]
        return gate.evaluate_pair(linked[0], linked[1]).status == "verified"

    league_ok = verified_with([], league_pair)
    both_ok = verified_with(alias_entries, league_pair)
    if both_ok and league_ok:
        return "league"
    if both_ok:
        return "alias+league"
    return "none"


def _build_remediation(
    *,
    reasons: list[str],
    entries: list[str],
    league_pair: tuple[str, str] | None,
    action: RemediationAction,
    left: Match,
    right: Match,
    ledger: MappingLedger | None,
    confidence: float,
) -> CandidateRemediation:
    """Assemble the inert proposal block for one candidate.

    Everything here is read-only: the ledger is queried, the raw spellings are
    copied, and no allowlist, claim or gate verdict is written. ``action`` is
    the hypothetical verdict computed by ``_what_if_action``.
    """
    proposals = (
        alias_proposals(entries, ledger, confidence) if action != "none" else []
    )
    if action != "none" and league_pair is not None:
        proposal = league_proposal(
            left.league,
            right.league,
            ledger,
            normalized_left=left.league_normalized,
            normalized_right=right.league_normalized,
            confidence=confidence,
        )
        if proposal is not None:
            proposals.append(proposal)
    notes = [PROPOSAL_NOTE]
    if action == "none":
        notes.append(
            "No team alias or league mapping clears the remaining gate reasons."
        )
    if action != "none" and league_pair is not None:
        notes.append(
            "A league equivalence is a proposal for review; it is not written by "
            "this queue and only evidence can accept it."
        )
    if set(reasons) & LINK_REJECTION_REASONS:
        notes.append(
            "The link half is a separate machine check; no alias or league "
            "proposal clears it."
        )
    return CandidateRemediation(
        action=action,
        closeable=action in {"alias", "league", "alias+league"},
        gate_reasons=list(reasons),
        proposals=proposals,
        notes=notes,
    )


def _what_if_gate(matcher: MatchMatcher) -> CertaintyGate:
    """Build the gate that answers "would an approval clear this pair?".

    It has to be configured exactly as the gate the scan decides with, because
    its verdict is the one the reviewer will live with, so the kickoff window is
    left at the `CertaintyGate` default — `VERIFIED_KICKOFF_WINDOW_MINUTES`, the
    same value `MatchMatcher` takes. The wider `CANDIDATE_KICKOFF_WINDOW_MIN`
    exists to *find* near-misses and says nothing about whether a human can close
    one: nothing an approval grants can move a kickoff.

    A second instance, not the collection gate itself, for two reasons. The two
    jobs want different windows. And `_alias_actionable` overwrites
    `alias_allowlist` on the gate it is handed, so a shared gate would judge the
    next pair spelling the same two clubs with the previous candidate's aliases
    already granted: its recorded reasons would lose `team_unresolved`, and once
    the deep-link check has passed it would verify itself and never reach the
    queue. Both are pinned by
    `test_a_candidate_never_inherits_another_candidate_s_approved_aliases`.
    """
    return CertaintyGate(league_equivalences=getattr(matcher, "_equivalences", set()))


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


async def _rank_candidates_with_ai(ai: MatchAI, found: list[FoundPair]) -> None:
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
            "a_event": match_event_ref(left), "b_event": match_event_ref(right),
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


def _build_candidates(
    all_matches: list[Match],
    matcher: MatchMatcher,
    groups: list[MatchGroup] | None = None,
) -> tuple[dict[str, CandidateReview], list[FoundPair], dict[str, int]]:
    """Find plausible same-event pairs the matcher could not verify (M2-1).

    Pure CPU over the scan's matches, so `_collect_candidates` runs it in a
    worker thread: the pair walk and the gate calls were part of the ~100 s
    block that used to hold the event loop. Returns the retained queue, the
    ordered `FoundPair`s it was cut from (only the top is worth an AI call),
    and the found/retained/dropped numbers the cap must report (M2-4).

    Pairs are discovered with a kickoff-bucket index (not an O(n^2) sweep) and a
    cheap team-token prefilter before the full gate runs. AI only ranks; it never
    approves. A pair a human already decided on is not re-queued while the state
    that decision was taken on still holds.
    """
    gate = CertaintyGate(
        kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN,
        league_equivalences=getattr(matcher, "_equivalences", set()),
    )
    # Second gate, reused for the "would an approval fix this?" question. Built by
    # `_what_if_gate` so it decides with the verified window, not this wider one.
    what_if_gate = _what_if_gate(matcher)
    # The declared equivalences are the base every hypothetical resets to; the
    # gate object is reused, so a proposal can never leak into the next pair.
    base_equivalences = set(what_if_gate.league_equivalences)
    ledger = getattr(matcher, "_ledger", None)
    gate.normalize(all_matches)

    buckets: dict[int, list[Match]] = {}
    for match in all_matches:
        bucket = kickoff_bucket(match)
        if bucket is not None:
            buckets.setdefault(bucket, []).append(match)

    # The candidate gate carries no alias allowlist on purpose: an allowlisted
    # alias is already proven, so those pairs must not come back for review.
    verified_in_group = _verified_group_index(groups or [])
    decided = set(_suppressed_candidates)
    seen_pairs: set[str] = set()
    found: list[FoundPair] = []
    # M2-4: how many pairs the walk produced versus how many survive the cap.
    # Counted as pairs are found, because the transient list may be trimmed.
    found_count = 0
    actionable_found = 0
    closeable_found = 0
    cap = CANDIDATE_QUEUE_MAX

    for index in sorted(buckets):
        here = [(match, TeamTokens.of(match)) for match in buckets[index]]
        # Same and next bucket only: every pair inside the 30-minute candidate
        # window lands in the same or an adjacent bucket, and this compares each
        # adjacent pair exactly once.
        following = [(match, TeamTokens.of(match)) for match in buckets.get(index + 1, [])]
        for position, (left, left_teams) in enumerate(here):
            for right, right_teams in here[position + 1:] + following:
                if left.bookmaker == right.bookmaker:
                    continue
                similarity = team_similarity(left_teams, right_teams)
                if similarity < CANDIDATE_TEAM_SIM_MIN:
                    continue
                pair_key = canonical_pair_key(left, right)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                review_id = candidate_id(pair_key)
                left_group = verified_in_group.get(match_side_key(left))
                if left_group is not None and left_group == verified_in_group.get(
                    match_side_key(right)
                ):
                    continue  # the matcher already proved this pairing
                result = gate.evaluate_pair(left, right)
                if result.status == "verified":
                    continue  # already handled by the matcher's verified group
                # Read the premise off the verdict rather than off the card, so a
                # decided pair is judged on the same facts the card showed.
                link_blocked = bool(set(result.reasons) & LINK_REJECTION_REASONS)
                if review_id in decided and _decision_still_stands(
                    review_id, link_blocked
                ):
                    continue  # a human already decided this exact pair
                positions = _team_positions(left, right)
                entries = _alias_entries(positions)
                actionable = _alias_actionable(
                    result.reasons, positions, left, right, what_if_gate
                )
                league_labels = (
                    left.league_normalized or left.league,
                    right.league_normalized or right.league,
                )
                league_pair = (
                    (
                        (league_labels[0], league_labels[1])
                        if league_labels[0] < league_labels[1]
                        else (league_labels[1], league_labels[0])
                    )
                    if "league_mismatch" in result.reasons
                    and all(league_labels)
                    and league_labels[0] != league_labels[1]
                    else None
                )
                action = _what_if_action(
                    result.reasons,
                    entries,
                    league_pair,
                    left,
                    right,
                    what_if_gate,
                    alias_actionable=actionable,
                    base_equivalences=base_equivalences,
                )
                remediation = _build_remediation(
                    reasons=result.reasons,
                    entries=entries,
                    league_pair=league_pair,
                    action=action,
                    left=left,
                    right=right,
                    ledger=ledger,
                    confidence=similarity / 100.0,
                )
                found.append(FoundPair(
                    candidate=CandidateReview(
                        id=review_id,
                        home_team=left.home_team,
                        away_team=left.away_team,
                        league=left.league,
                        kickoff=left.kickoff,
                        bookmakers=sorted([left.bookmaker, right.bookmaker]),
                        side_a=PairSide(
                            bookmaker=left.bookmaker,
                            event_ref=match_event_ref(left),
                            home_team=left.home_team,
                            away_team=left.away_team,
                            league=left.league,
                            league_normalized=left.league_normalized,
                            link_verified=left.deep_link_verified,
                        ),
                        side_b=PairSide(
                            bookmaker=right.bookmaker,
                            event_ref=match_event_ref(right),
                            home_team=right.home_team,
                            away_team=right.away_team,
                            league=right.league,
                            league_normalized=right.league_normalized,
                            link_verified=right.deep_link_verified,
                        ),
                        team_positions=positions,
                        alias_actionable=actionable,
                        link_blocked=link_blocked,
                        ai_confidence=0.0,
                        ai_reason="",
                        rule_rejections=result.reasons,
                        remediation=remediation,
                        created_at=utcnow(),
                    ),
                    alias_actionable=actionable,
                    closeable=remediation.closeable,
                    human_blockers=len(
                        [r for r in result.reasons if r not in LINK_REJECTION_REASONS]
                    ),
                    kickoff_delta_minutes=kickoff_delta_minutes(left, right),
                    team_similarity=similarity,
                    left=left,
                    right=right,
                ))
                found_count += 1
                if actionable:
                    actionable_found += 1
                if remediation.closeable:
                    closeable_found += 1
                # M2-4: bound the transient list while walking, with the same
                # total order the final cut uses, so a five-figure scan does not
                # hold every pair at once. A total order makes the trim exact:
                # an entry dropped here can never be in the final top N.
                if cap > 0 and len(found) > cap * CANDIDATE_TRIM_FACTOR:
                    found.sort(key=pair_priority)
                    del found[cap:]

    # What a reviewer can act on first, then the fewest remaining blockers, then
    # the tightest kickoff and closest names. The AI cap is taken from the top of
    # this order, so the hosted calls land on pairs a human could actually close.
    found.sort(key=pair_priority)
    kept = found[:cap] if cap > 0 else found
    candidates = {pair.candidate.id: pair.candidate for pair in kept}
    logger.info(
        f"Review candidates: {len(candidates)} retained of {found_count} unverified "
        f"pairs from {len(all_matches)} matches "
        f"({actionable_found} alias-actionable, {closeable_found} closeable by a "
        f"proposed mapping, {len(decided)} suppressed by earlier decisions, "
        f"cap {cap or 'off'})"
    )
    stats = {
        "found": found_count,
        "retained": len(kept),
        "dropped": found_count - len(kept),
        "cap": cap,
        "actionable_found": actionable_found,
        "closeable_found": closeable_found,
    }
    return candidates, kept, stats


async def _collect_candidates(
    all_matches: list[Match],
    matcher: MatchMatcher,
    groups: list[MatchGroup] | None = None,
    *,
    rank_with_ai: bool = True,
    stats: dict[str, int] | None = None,
) -> dict[str, CandidateReview]:
    """Build the review queue off the event loop, then rank it with AI (M2-1).

    The pair walk is CPU; the AI ranking is the only network step and is already
    async. ``rank_with_ai=False`` lets an offline report build the same queue
    without a network call; it changes nothing about the verdicts or proposals.

    ``stats`` receives the found/retained/dropped numbers (M2-4) when the caller
    has somewhere to keep them; it is optional so the offline callers and the
    tests that only care about the queue stay unchanged.
    """
    candidates, kept, build_stats = await asyncio.to_thread(
        _build_candidates, all_matches, matcher, groups
    )
    if stats is not None:
        stats.update(build_stats)
    ai = _shared_client_ai() if (kept and rank_with_ai) else None
    if ai is None:
        return candidates
    try:
        await _rank_candidates_with_ai(ai, kept)
    finally:
        await ai.aclose()
    return candidates


# ---------------------------------------------------------------------------
# Background scan task
# ---------------------------------------------------------------------------

def _book_backoff_interval(mode: str) -> int:
    """The mode's scan interval in minutes, never zero.

    A disabled feed (``AUTO_SCAN_*_MINUTES=0``) still needs a positive base
    cooldown: the breaker opens when a manual scan keeps failing too.
    """
    configured = AUTO_SCAN_LIVE_MINUTES if mode == "live" else AUTO_SCAN_PREMATCH_MINUTES
    return configured or 5


def _breaker(mode: str, bookmaker: str) -> BookCircuitBreaker:
    """The process-wide SR2-6 breaker for one feed of one book.

    The base cooldown is the mode's scan interval, so an open breaker skips the
    next scheduled scans rather than firing between them; it doubles on every
    consecutive open and caps at `BOOK_BACKOFF_MAX_MINUTES`.
    """
    return breaker_for(
        mode,
        bookmaker,
        failure_threshold=BOOK_BACKOFF_AFTER_FAILURES,
        open_seconds=_book_backoff_interval(mode) * 60.0,
        max_open_seconds=BOOK_BACKOFF_MAX_MINUTES * 60.0,
    )


def _breaker_snapshots(mode: str) -> dict[str, dict[str, Any]]:
    """Every book's breaker state for one feed, keyed by book id."""
    return {book: _breaker(mode, book).snapshot() for book in BOOKMAKERS}


def _record_book_result(mode: str, bookmaker: str, kind: ScrapeKind) -> None:
    """Feed one completed attempt's kind to the book's breaker."""
    _breaker(mode, bookmaker).record(kind)


def _record_breaker_metrics(mode: str) -> None:
    """Publish every book's breaker state as gauges after a scan.

    One gauge per (book, state) with value 1 for the current state and 0 for
    the others, so a dashboard can alert on `state="open"` without decoding
    numbers. The failure and cooldown gauges are diagnostics.
    """
    for book, snapshot in _breaker_snapshots(mode).items():
        for state in (CLOSED, OPEN, HALF_OPEN):
            metrics.set_gauge(
                "bh_book_breaker_state",
                1.0 if snapshot["state"] == state else 0.0,
                mode=mode,
                book=book,
                state=state,
            )
        metrics.set_gauge(
            "bh_book_breaker_failures",
            snapshot["consecutive_failures"],
            mode=mode,
            book=book,
        )
        metrics.set_gauge(
            "bh_book_breaker_cooldown_seconds",
            snapshot["cooldown_remaining_seconds"],
            mode=mode,
            book=book,
        )


def _metric_book(
    mode: str,
    bookmaker: str,
    kind: ScrapeKind,
    *,
    legacy: str | None = None,
) -> None:
    """Count one book's result in both the old outcome and the new kind.

    ``bh_book_results_total`` keeps its historical ``outcome`` label so
    existing dashboards do not change meaning; ``bh_book_kinds_total`` is the
    SR2-1 taxonomy. An exception is still counted as ``outcome="error"`` in the
    old metric while its exact kind is ``timeout``, ``blocked`` and so on.
    """
    metrics.inc(
        "bh_book_results_total",
        mode=mode,
        book=bookmaker,
        outcome=legacy or legacy_outcome(kind),
    )
    metrics.inc("bh_book_kinds_total", mode=mode, book=bookmaker, kind=kind.value)


def _metric_browser_opened(delta: int) -> None:
    """Track how many browser slots are in use against BROWSER_CONCURRENCY."""
    metrics.add_gauge("bh_browser_slots_in_use", delta)


def _init_metric_baseline() -> None:
    """Publish zero-valued series so a fresh process is scrapable immediately.

    Without this, a counter that has not been touched yet is absent from the
    exposition, and an alert expression cannot distinguish "zero" from "this
    build never registered the metric".
    """
    for metric_mode in ("prematch", "live"):
        metrics.inc("bh_scans_started_total", 0, mode=metric_mode)
        metrics.inc("bh_scans_completed_total", 0, mode=metric_mode)
        metrics.inc("bh_scans_failed_total", 0, mode=metric_mode)
        metrics.inc("bh_scan_seconds_total", 0, mode=metric_mode)
        metrics.set_gauge("bh_scan_duration_seconds", 0, mode=metric_mode)
        metrics.inc("bh_surebets_found_total", 0, mode=metric_mode)
        metrics.set_gauge("bh_surebets_found", 0, mode=metric_mode)
        metrics.inc(
            "bh_surebets_dropped_total", 0, mode=metric_mode, reason="price_outlier"
        )
        metrics.set_gauge("bh_candidate_queue_size", 0, mode=metric_mode)
        metrics.set_gauge("bh_candidates_found", 0, mode=metric_mode)
        metrics.set_gauge("bh_coverage_flags", 0, mode=metric_mode)
        metrics.inc("bh_coverage_flags_total", 0, mode=metric_mode)
        metrics.set_gauge("bh_cardinality_flags", 0, mode=metric_mode)
        metrics.inc("bh_cardinality_flags_total", 0, mode=metric_mode)
        metrics.set_gauge("bh_mapping_coverage_ratio", 0, mode=metric_mode)
        metrics.inc("bh_unmapped_market_rows_total", 0, mode=metric_mode)
    for book in BOOKMAKERS:
        for metric_mode in ("prematch", "live"):
            metrics.set_gauge(
                "bh_book_last_success_timestamp_seconds",
                0,
                mode=metric_mode,
                book=book,
            )
    metrics.set_gauge("bh_browser_slots_in_use", 0)
    metrics.set_gauge("bh_cache_budget_bytes", CACHE_SIZE_BUDGET_BYTES)


_init_metric_baseline()


def _record_coverage_metrics(
    mode: str,
    coverage_report: dict[str, Any],
    mapping_report: dict[str, Any],
    cardinality_report: dict[str, Any],
) -> None:
    """Publish the coverage-budget, mapping and cardinality series for one scan."""
    flags = int(coverage_report.get("flag_count") or 0)
    metrics.set_gauge("bh_coverage_flags", flags, mode=mode)
    metrics.inc("bh_coverage_flags_total", flags, mode=mode)
    cardinality_flags = int(cardinality_report.get("flag_count") or 0)
    metrics.set_gauge("bh_cardinality_flags", cardinality_flags, mode=mode)
    metrics.inc("bh_cardinality_flags_total", cardinality_flags, mode=mode)
    ratio = mapping_report.get("coverage")
    metrics.set_gauge(
        "bh_mapping_coverage_ratio",
        float(ratio) if ratio is not None else 0.0,
        mode=mode,
    )
    metrics.inc(
        "bh_unmapped_market_rows_total",
        int(mapping_report.get("unmapped_total") or 0),
        mode=mode,
    )


def _track_zero_result(mode: str, reason: str) -> int:
    """Count consecutive scans with a watched zero-result reason."""
    streaks = _zero_result_streaks.setdefault(mode, {})
    for key in list(streaks):
        if key != reason:
            streaks[key] = 0
    if reason in _ZERO_RESULT_ALERT_REASONS:
        streaks[reason] = streaks.get(reason, 0) + 1
        return streaks[reason]
    return 0


def _record_scan_cost_metrics(report: dict[str, Any]) -> None:
    """Publish per-book cost gauges; an unmeasured value is absent, not zero."""
    mode = str(report.get("mode") or "")
    rates = book_failure_rates(_scan_cost_history, mode)
    for book, record in (report.get("books") or {}).items():
        if not isinstance(record, dict):
            continue
        metrics.set_gauge(
            "bh_book_seconds",
            float(record.get("wall_seconds") or 0.0),
            mode=mode,
            book=book,
        )
        for field, metric in (
            ("browser_seconds", "bh_book_browser_seconds"),
            ("requests", "bh_book_requests"),
            ("bytes", "bh_book_bytes"),
        ):
            value = record.get(field)
            if value is not None:
                metrics.set_gauge(metric, float(value), mode=mode, book=book)
        rate = rates.get(book)
        if rate is not None:
            metrics.set_gauge(
                "bh_book_failure_rate", float(rate), mode=mode, book=book
            )


def learn_scan_mappings(
    matches: list[Match],
    scan: str,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Learn from one real scan and persist the ledger before matching.

    The matcher is constructed after this call, so the aliases learned from this
    very scan are available to it. A failure is reported to the caller and never
    stops the scan.
    """
    ledger = MappingLedger(ledger_path).load() if ledger_path else MappingLedger().load()
    ledger, report = learn(matches, ledger, scan=scan)
    ledger.prune()
    ledger.save()
    return report.to_dict()


def _finish_scan_cost(
    mode: str, scan_started_at: datetime, scan_costs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build, remember and persist the per-book cost record (M2-1 worker)."""
    report = build_scan_report(mode, scan_started_at, scan_costs)
    _scan_cost[mode] = report
    _scan_cost_history.insert(0, report)
    del _scan_cost_history[_SCAN_COST_HISTORY_MAX:]
    _save_scan_cost()
    return report


def _evaluate_feed_diagnostics(
    mode: str,
    all_matches: list[Match],
    unmapped_before: dict[str, int],
    unmapped_now: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Coverage, cardinality and mapping diagnostics for one scan (M2-1 worker).

    P2-9: compare with the rolling median before the matcher runs; a
    peer-populated zero is a flag, not a quiet day. SR4-5: a feed that keeps a
    few events but loses most of them is a silent drop, quarantined through feed
    integrity below. N1-2: mapped rows / (mapped + newly unmapped rows) is why
    the cumulative counter's delta is passed in. Each walks every match's
    markets, so this is the kind of CPU that must not run on the event loop
    while the dashboard polls.
    """
    coverage_counts = coverage_snapshot(all_matches)
    coverage_report = evaluate_coverage_budget(
        coverage_counts, _coverage_history[mode]
    )
    _coverage_budget[mode] = coverage_report
    _coverage_history[mode] = push_coverage_history(
        _coverage_history[mode], coverage_counts
    )
    cardinality_counts = cardinality_snapshot(all_matches)
    cardinality_report = evaluate_cardinality(
        cardinality_counts, _cardinality_history[mode]
    )
    _cardinality[mode] = cardinality_report
    _cardinality_history[mode] = push_cardinality_history(
        _cardinality_history[mode], cardinality_counts
    )
    mapping_report = evaluate_mapping_coverage(
        all_matches,
        unmapped_before,
        unmapped_now,
        floor=MAPPING_COVERAGE_FLOOR,
        min_rows=MAPPING_COVERAGE_MIN_ROWS,
    )
    _mapping_coverage[mode] = mapping_report
    return coverage_report, cardinality_report, mapping_report


def _summarize_pricing(
    scan_metrics: ScanMetrics,
    surebets: list[Any],
    price_dropped: list[dict[str, Any]],
    mode: str,
    scan_finished_at: datetime,
) -> dict[str, Any]:
    """Aggregate the priced boards and their lifetime crossings (M2-1 worker)."""
    summary = summarize_scan(
        scan_metrics,
        surebets,
        price_dropped,
        mode=mode,
        scan_time=scan_finished_at,
        floor_profit_percent=DUST_PROFIT_PERCENT,
    )
    tracked = _crossing_lifetimes.setdefault(mode, {})
    update_lifetimes(tracked, scan_metrics.boards, scan_finished_at)
    summary["lifetime"] = lifetime_distribution(tracked, scan_finished_at)
    summary["tracked_crossings"] = len(tracked)
    return summary


def _serialise_scan_caches(
    live_surebets: list[Any], all_matches: list[Match]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dump the served payloads once, off the loop (M2-1 worker).

    A real scan's matches dump to a ~27 MB JSON document; doing that per model on
    the event loop was part of the block.
    """
    return (
        [surebet.model_dump(mode="json") for surebet in live_surebets],
        [match.model_dump(mode="json") for match in all_matches],
    )


def _persist_scan_state(
    mode: str,
    group_count: int,
    scan_finished_at: datetime,
    matches_cache: list[dict[str, Any]],
    report_cache: list[dict[str, Any]],
) -> None:
    """Write the scan's caches and diagnostics (M2-1 worker).

    The cache write is tens of megabytes plus several sibling JSON files. A
    cancelled scan can leave an in-flight worker finishing after the await is
    cancelled; every write here re-reads the shared state at call time and is
    idempotent, so it cannot publish an older result than the state already
    holds.
    """
    _save_cache(mode)
    _save_opportunity_metrics()
    _save_feed_integrity()
    _save_stale_price_state()
    _append_history(group_count, mode)
    _record_candidate_trend(mode, scan_finished_at)
    _refresh_pairing_summary(mode, matches_cache, report_cache, scan_finished_at)


async def run_scan(
    mode: str = "prematch",
    scheduled: bool = False,
    run_mode: str = "advisory",
):
    """Execute a full scan of all enabled bookmakers concurrently.

    `mode` selects the feed: "prematch" (future matches) or "live" (in-play).
    Each mode has its own status object and cache file.
    `run_mode` selects what the completed scan may publish: the normal advisory
    path, a record-only snapshot, or a paper-trading scan. A non-advisory scan
    never writes a live surebet; the compact rows go to the paper ledger.
    Uniform `scan_started_at` (naive UTC) is passed to all scrapers so date
    windows are identical (P0-5) and odds can be age-checked (P0-1).
    """
    if run_mode not in RUN_MODES:
        run_mode = "advisory"
    is_live = mode == "live"
    # SR8-2: each scan logs a drift signature once, not once per response.
    begin_structural_drift_scan()
    state = _state_for(mode)
    status = state.status
    surebets_cache = state.surebets
    matches_cache = state.matches
    report_cache = state.report
    per_bookie = state.per_bookie
    scan_started_at = utcnow()
    scan_started_monotonic = time.perf_counter()
    scan_id = new_request_id()
    scan_token = set_scan_id(scan_id)
    metrics.inc("bh_scans_started_total", mode=mode)
    # N1-2: the unmapped counter is cumulative, so this snapshot lets the scan
    # measure its own unmapped market rows without a process restart.
    unmapped_before = dict(unmapped_markets)

    status.is_scanning = True
    status.bookmakers_done = []
    status.bookmaker_progress = {}
    status.errors = []
    status.total_matches = 0
    status.surebets_found = 0
    status.recorded_opportunities = 0
    # M2-3: the cached health summary describes the previous scan; drop it so
    # the new scan's progress is visible on the next poll.
    _reset_health_cache()
    status.run_mode = run_mode
    status.current_bookmaker = "Starting..."
    # Counts are rebuilt per scan; a book disabled since the last scan must not
    # keep reporting its old count.
    per_bookie.clear()

    try:
        all_matches: list[Match] = []
        scan_costs: dict[str, dict[str, Any]] = {}
        # Filled by each book as it finishes, so a scan-level deadline can price
        # the books that returned instead of losing the whole gather.
        book_matches: dict[str, list[Match]] = {}

        # --- Scrape each enabled bookmaker (P2: browser concurrency cap) ---
        async def scrape_one(bookie_id: str, config: dict) -> list[Match]:
            uses_browser = bookie_id in PLAYWRIGHT_BOOKIES
            if not _is_enabled(bookie_id):
                begin_book(bookie_id, mode, uses_browser=uses_browser)
                scan_costs[bookie_id] = (
                    finish_book(
                        ScrapeKind.SKIPPED.value,
                        kind=ScrapeKind.SKIPPED.value,
                        note="disabled by runtime toggle",
                    )
                    or {}
                )
                status.bookmaker_progress[bookie_id] = "skipped"
                _metric_book(mode, bookie_id, ScrapeKind.SKIPPED)
                return []
            breaker = _breaker(mode, bookie_id)
            if scheduled and not breaker.allow():
                begin_book(bookie_id, mode, uses_browser=uses_browser)
                scan_costs[bookie_id] = (
                    finish_book(
                        ScrapeKind.SKIPPED.value,
                        kind=ScrapeKind.SKIPPED.value,
                        note="circuit breaker open",
                    )
                    or {}
                )
                status.bookmaker_progress[bookie_id] = "skipped"
                _metric_book(mode, bookie_id, ScrapeKind.SKIPPED)
                status.errors.append(
                    f"{config['name']}: circuit breaker open, next probe in "
                    f"{breaker.snapshot()['cooldown_remaining_seconds']:.0f}s"
                )
                return []

            begin_book(bookie_id, mode, uses_browser=uses_browser)
            matches: list[Match] = []
            kind = ScrapeKind.PARSE_ERROR
            outcome = legacy_outcome(kind)
            note = ""
            status.bookmaker_progress[bookie_id] = "scraping"
            status.current_bookmaker = f"Scraping {config['name']}..."
            # Limit concurrent Playwright browsers
            sem = _browser_sem if bookie_id in PLAYWRIGHT_BOOKIES else None
            if sem:
                await sem.acquire()
                _metric_browser_opened(1)
            try:
                scraper_class = SCRAPERS.adapter(bookie_id)
                if not scraper_class:
                    note = "no scraper registered"
                    kind = ScrapeKind.PARSE_ERROR
                    status.bookmaker_progress[bookie_id] = "error"
                    _metric_book(mode, bookie_id, kind, legacy="error")
                    return []

                scraper = scraper_class()
                policy = policy_for(bookie_id, mode)
                # SR2-5: one adapter may not run longer than its policy budget.
                # The timeout cancels the scrape; a browser book closes its
                # context in its own finally, so nothing is left running.
                try:
                    async with asyncio.timeout(policy.adapter_deadline):
                        # Pass uniform scan_time for window consistency; fallback only
                        # when the scraper signature lacks scan_time (not on internal errors)
                        try:
                            matches = await scraper.scrape(
                                live=is_live,
                                scan_time=scan_started_at,
                                sports_wanted=ENABLED_SPORTS,
                            )
                        except TypeError as te:
                            if "sports_wanted" in str(te):
                                matches = await scraper.scrape(
                                    live=is_live, scan_time=scan_started_at
                                )
                            elif "scan_time" not in str(te):
                                raise
                            else:
                                matches = await scraper.scrape(live=is_live)
                except TimeoutError:
                    kind = ScrapeKind.TIMEOUT
                    outcome = legacy_outcome(kind)
                    note = f"adapter deadline {policy.adapter_deadline:g}s exceeded"
                    status.bookmaker_progress[bookie_id] = "error"
                    status.errors.append(f"{config['name']}: {note}")
                    _record_book_result(mode, bookie_id, kind)
                    _metric_book(mode, bookie_id, kind, legacy="error")
                    logger.warning("⏱ Scrape deadline — %s: %s", config["name"], note)
                    return []
                # Stamp fetched_at if scraper missed it (defense in depth)
                for m in matches:
                    if not m.fetched_at:
                        m.fetched_at = scan_started_at

                kind = classify_scrape(matches)
                outcome = legacy_outcome(kind)
                status.bookmaker_progress[bookie_id] = "done"
                status.bookmakers_done.append(config["name"])
                status.total_matches += len(matches)
                per_bookie[bookie_id] = len(matches)
                book_matches[bookie_id] = matches
                _record_book_result(mode, bookie_id, kind)
                _metric_book(mode, bookie_id, kind)
                if kind is ScrapeKind.OK:
                    metrics.set_gauge(
                        "bh_book_last_success_timestamp_seconds",
                        datetime.now(UTC).timestamp(),
                        mode=mode,
                        book=bookie_id,
                    )
                logger.info(f"✅ {config['name']}: {len(matches)} {'live' if is_live else 'prematch'} matches scraped")
                return matches

            except asyncio.CancelledError:
                # The scan-level deadline (or shutdown) cancelled this book.
                # It is missing from the scan; the others still price. This is
                # not charged to the book's breaker: our own deadline is not
                # the book failing. A half-open probe this attempt reserved is
                # released (a neutral kind does that), or a cancelled scan
                # would keep the book benched forever.
                kind = ScrapeKind.TIMEOUT
                outcome = legacy_outcome(kind)
                note = "cancelled at the scan deadline"
                status.bookmaker_progress[bookie_id] = "error"
                _record_book_result(mode, bookie_id, ScrapeKind.SKIPPED)
                _metric_book(mode, bookie_id, kind, legacy="error")
                logger.warning("⏱ Scrape cancelled — %s: %s", config["name"], note)
                raise
            except Exception as e:
                kind = classify_exception(e)
                outcome = legacy_outcome(kind)
                artefacts = artefact_summary(take_artefacts())
                note = f"{type(e).__name__}: {str(e)[:200]}{artefacts}"
                error_msg = f"{config['name']}: {str(e)[:200]}{artefacts}"
                status.bookmaker_progress[bookie_id] = "error"
                status.errors.append(error_msg)
                _record_book_result(mode, bookie_id, kind)
                _metric_book(mode, bookie_id, kind, legacy="error")
                logger.error(f"❌ Scrape error — {error_msg}", exc_info=True)
                return []
            finally:
                scan_costs[bookie_id] = (
                    finish_book(
                        outcome,
                        kind=kind.value,
                        note=note,
                        matches=len(matches),
                        markets=sum(len(m.markets) for m in matches),
                    )
                    or {}
                )
                if sem:
                    sem.release()
                    _metric_browser_opened(-1)

        # Run all scrapers concurrently. The transport pool owns one HTTP
        # client per book for this scan and closes them when the gather
        # returns, so pagination and retries reuse the same connection.
        status.current_bookmaker = "Scraping all bookmakers..."
        results: list[Any] = []
        # SR3-3: one Chromium for the whole scan; every book gets a fresh
        # context. The pool recycles the browser on its page/age budget.
        async with transport_pool(), browser_pool():
            # Tasks are created inside the pool so each one inherits the pool's
            # context: a context var copied at creation is how the shared
            # per-book HTTP client reaches the adapter.
            tasks = [
                asyncio.create_task(scrape_one(bid, cfg), name=f"scan:{mode}:{bid}")
                for bid, cfg in BOOKMAKERS.items()
            ]
            try:
                async with asyncio.timeout(SCRAPER_SCAN_TIMEOUT_SECONDS):
                    results = await asyncio.gather(*tasks, return_exceptions=True)
            except TimeoutError:
                # Cancel what is still running and wait for its cleanup (a
                # browser book releases its context) before the pools close the
                # shared browser and HTTP clients. Books that returned still price.
                for task in tasks:
                    task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=_DEADLINE_CLEANUP_SECONDS,
                    )
                except TimeoutError:
                    logger.warning(
                        "⏱ scan deadline: %d book(s) did not finish cleanup in %gs",
                        sum(1 for task in tasks if not task.done()),
                        _DEADLINE_CLEANUP_SECONDS,
                    )
                note = (
                    f"scan deadline {SCRAPER_SCAN_TIMEOUT_SECONDS:g}s reached; "
                    "books still running were cancelled"
                )
                logger.warning("⏱ %s", note)
                status.errors.append(note)

        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Scraper gather exception: {res}")
                status.errors.append(f"Scraper error: {str(res)[:200]}")
        # Built from the books that finished, in config order. A cancelled
        # gather must never lose what the other books already returned.
        all_matches = [
            match
            for bookie_id in BOOKMAKERS
            for match in book_matches.get(bookie_id, [])
        ]

        # N1-3: one bounded per-book cost record for this scan. The history is
        # newest-first so the CLI and the failure-rate window can read it
        # without scanning the whole file.
        scan_cost_report = await asyncio.to_thread(
            _finish_scan_cost, mode, scan_started_at, scan_costs
        )
        _record_scan_cost_metrics(scan_cost_report)
        _record_breaker_metrics(mode)

        # A book that "succeeds" with nothing is usually a blocked or changed
        # feed, not an empty market. Say so while other books did return data,
        # so it is not mistaken for a quiet day (e.g. no live games at night).
        if all_matches:
            for bookie_id, config in BOOKMAKERS.items():
                if status.bookmaker_progress.get(bookie_id) == "done" and not per_bookie.get(bookie_id):
                    status.errors.append(
                        f"{config['name']}: returned no matches (feed empty, blocked or changed?)"
                    )
                    logger.warning(f"⚠️ {config['name']} returned no {mode} matches")

        # Age spread guard (P0-1): warn if scrapers' fetched_at diverge >90s
        if all_matches:
            times = [
                _naive_utc(m.fetched_at)
                if m.fetched_at and m.fetched_at.tzinfo
                else m.fetched_at
                for m in all_matches if m.fetched_at
            ]
            if times:
                spread = (max(times) - min(times)).total_seconds()  # type: ignore[operator]
                if spread > 90:
                    logger.warning(f"Odds age spread {spread:.0f}s exceeds 90s — results may be stale")
                    status.errors.append(f"Odds age spread {spread:.0f}s — verify before betting")

        # P2-9: a whole feed can disappear while the remaining books still
        # price a clean-looking scan. These are the CPU diagnostics, so they run
        # in a worker: a real scan spent its analysis half here (M2-1).
        coverage_report, cardinality_report, mapping_report = await asyncio.to_thread(
            _evaluate_feed_diagnostics,
            mode,
            all_matches,
            unmapped_before,
            dict(unmapped_markets),
        )
        _coverage_trend[mode] = (
            _coverage_trend[mode]
            + [
                {
                    "scan_time": scan_started_at.isoformat(timespec="seconds"),
                    "flag_count": coverage_report["flag_count"],
                    "unmapped_rows": mapping_report["unmapped_total"],
                    "mapping_coverage": mapping_report["coverage"],
                    "denominator": mapping_report["denominator"],
                }
            ]
        )[-_COVERAGE_TREND_MAX:]
        _record_coverage_metrics(
            mode, coverage_report, mapping_report, cardinality_report
        )
        _save_coverage_budget()
        if cardinality_report["flag_count"]:
            logger.warning(
                "Cardinality floor: %s book/sport feed(s) below baseline in %s",
                cardinality_report["flag_count"],
                mode,
            )
        if coverage_report["flag_count"]:
            logger.warning(
                "Coverage budget: %s material drop(s) in %s",
                coverage_report["flag_count"],
                mode,
            )
        if mapping_report["below_floor"]:
            logger.warning(
                "Mapping coverage: %s/%s rows mapped in %s (floor %.2f)",
                mapping_report["numerator"],
                mapping_report["denominator"],
                mode,
                MAPPING_COVERAGE_FLOOR,
            )

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

        # Learn from this scan before grouping, so the aliases and league
        # equivalences it proves are available to the matcher in the same pass.
        # Tiny scans are ignored so a test or a smoke run cannot rewrite the
        # shipped ledger.
        if AUTO_LEARN_MAPPINGS and len(all_matches) >= MIN_LEARN_MATCHES:
            global last_learning_report
            try:
                learned = await asyncio.to_thread(
                    learn_scan_mappings,
                    all_matches,
                    scan_started_at.isoformat(timespec="seconds"),
                )
                diff = learned.get("diff", {})
                last_learning_report = {
                    "scan": learned.get("scan", ""),
                    "matches": learned.get("matches", 0),
                    "pairs_considered": learned.get("pairs_considered", 0),
                    "counts": learned.get("counts", {}),
                    "diff": {
                        "counts": diff.get("counts", {}),
                        "added": len(diff.get("added", [])),
                        "changed": len(diff.get("changed", [])),
                    },
                }
                logger.info(
                    "Mapping learning: %s accepted, %s quarantined",
                    last_learning_report["counts"].get("accepted", 0),
                    last_learning_report["counts"].get("quarantined", 0),
                )
            except Exception as exc:
                logger.error("Mapping learning failed: %s", exc, exc_info=True)
                status.errors.append(f"Mapping learning failed: {str(exc)[:200]}")

        # M2-1: the matcher loads the evidence ledger and groups every match;
        # both are CPU/I/O, so they run in the worker.
        matcher = await asyncio.to_thread(MatchMatcher)
        groups = await asyncio.to_thread(matcher.group_matches, all_matches)
        # P2-7: measure which books are actually one price source before the
        # engine prices anything. The registration is intentionally after the
        # grouping pass: a measured twin changes pricing, not event identity.
        skin_matrix = await asyncio.to_thread(measure_price_agreement, groups)
        new_twins = await asyncio.to_thread(apply_measured_twins, skin_matrix)
        _skin_detection[mode] = {
            "matrix": skin_matrix,
            "summary": skin_summary(skin_matrix),
            "warnings": declared_twin_warnings(skin_matrix),
            "new_twins": [list(pair) for pair in new_twins],
        }
        if new_twins:
            logger.warning(
                "Measured identical price sources: %s",
                ", ".join(f"{left}+{right}" for left, right in new_twins),
            )
        report_cache.clear()
        report_cache.extend(await asyncio.to_thread(matcher.get_match_report, groups))

        # P0-7: score every enabled book before pricing. A quarantined book is
        # removed from the copies used by the engine and price guard; the full
        # group stays available for diagnostics and evidence.
        status.current_bookmaker = "Checking feed integrity..."
        integrity_now = utcnow()
        # N0-2: update the per-book price observations and refuse frozen rows
        # before the integrity scorecard and the pricing pass read the groups.
        stale_result = await asyncio.to_thread(
            evaluate_stale_prices,
            groups,
            _stale_price_store.get(mode) or {},
            mode=mode,
            now=integrity_now,
            ttl_sec=LIVE_ODDS_TTL_SECONDS if is_live else ODDS_TTL_SECONDS,
        )
        _stale_price_store[mode] = stale_result.store
        _stale_price_evidence[mode] = stale_result.evidence
        _stale_price_checked_at[mode] = stale_result.checked_at.isoformat()
        if stale_result.evidence:
            logger.warning(
                "Frozen-price quarantine: %s row(s) refused (%s)",
                len(stale_result.evidence),
                ", ".join(
                    f"{book}={count}"
                    for book, count in sorted(stale_result.by_book.items())
                ),
            )
        enabled_bookmakers = {
            bookmaker: str(config["name"])
            for bookmaker, config in BOOKMAKERS.items()
            if _is_enabled(bookmaker)
        }
        _feed_integrity[mode] = await asyncio.to_thread(
            compute_feed_integrity,
            mode=mode,
            bookmakers=enabled_bookmakers,
            matches=all_matches,
            groups=groups,
            progress=dict(status.bookmaker_progress),
            counts=dict(per_bookie),
            errors=list(status.errors),
            previous=_feed_integrity.get(mode) or {},
            now=integrity_now,
            ttl_sec=LIVE_ODDS_TTL_SECONDS if is_live else ODDS_TTL_SECONDS,
            stale_price_rows=stale_result.by_book,
            cardinality_flags=cardinality_quarantine_reasons(
                _cardinality.get(mode) or {}
            ),
        )
        quarantined = quarantined_books(_feed_integrity[mode])
        pricing_groups = priceable_groups(groups, quarantined)
        if quarantined:
            logger.warning(
                "Quarantined from pricing: %s",
                ", ".join(sorted(quarantined)),
            )

        # Ambiguous pairings the gate refused become review items. The queue is
        # rebuilt every scan so it only ever mirrors the current feed.
        status.current_bookmaker = "Collecting review candidates..."
        try:
            queue = _candidates_for(mode)
            queue.clear()
            candidate_stats: dict[str, int] = {}
            queue.update(
                await _collect_candidates(
                    all_matches, matcher, groups, stats=candidate_stats
                )
            )
            candidate_totals[mode] = candidate_stats
        except Exception as e:
            _candidates_for(mode).clear()
            candidate_totals[mode] = {}
            logger.error(f"❌ Candidate collection failed: {e}", exc_info=True)
            status.errors.append(f"Candidate review failed: {str(e)[:200]}")

        status.current_bookmaker = "Detecting surebets..."
        engine = ArbitrageEngine()
        # P0-6: the same pricing pass fills the denominator: every board it
        # evaluates is observed before the display filters run.
        scan_metrics = ScanMetrics()
        # P1-6: include dust (0.2%) — frontend filters/highlights by tier
        surebets = await asyncio.to_thread(
            engine.find_surebets,
            pricing_groups,
            min_profit=DUST_PROFIT_PERCENT,
            investment=DEFAULT_INVESTMENT,
            allow_past_kickoffs=is_live,
            enabled_markets=_enabled_markets(),
            mode=mode,
            metrics=scan_metrics,
        )
        price_dropped = []
        if PRICE_GUARD_ENABLED:
            surebets, price_dropped = await asyncio.to_thread(
                filter_price_outliers, surebets, pricing_groups
            )
        if price_dropped:
            detail = ", ".join(
                f"{item['surebet'].home_team}-{item['surebet'].away_team} "
                f"({item['outlier']['bookmaker']} {item['outlier']['label']})"
                for item in price_dropped[:5]
            )
            logger.warning("Dropped %s surebet(s) with a price outlier: %s", len(price_dropped), detail)
            status.errors.append(
                f"{len(price_dropped)} surebet(s) dropped: a leg was a price outlier"
            )

        # --- Update state ---
        scan_finished_at = utcnow()
        status.last_scan_time = scan_finished_at

        # N0-4: capture the last pre-kickoff price for every open logged bet.
        # This is a measurement, never a settlement; a failure must not stop the
        # scan or change what is priced.
        try:
            _closing_capture[mode] = await asyncio.to_thread(
                _bet_store_or_init().capture_closing,
                groups,
                now=scan_finished_at,
                mode=mode,
                cutoff_minutes=CLOSING_CAPTURE_CUTOFF_MINUTES,
                excluded_books=quarantined,
            )
        except Exception as exc:
            logger.warning("Closing-line capture failed: %s", exc)
            status.errors.append(f"Closing-line capture failed: {str(exc)[:200]}")

        # P3-7: a record-only or paper scan is still a real scan, but its
        # opportunities belong to the paper ledger, not the live surebet list.
        # Advisory is the default and keeps the previous behavior exactly.
        recorded: list[dict] = []
        paper_marks: dict[str, int] = {}
        if run_mode == "advisory":
            live_surebets = surebets
            status.surebets_found = len(surebets)
            status.recorded_opportunities = 0
            _last_run_mode[mode] = "advisory"
            _recorded_counts[mode] = 0
        else:
            store = _paper_store_or_init()
            recorded = await asyncio.to_thread(
                store.record_opportunities,
                surebets,
                feed_mode=mode,
                run_mode=run_mode,
                scan_time=scan_finished_at,
            )
            if run_mode == "paper":
                paper_marks = await asyncio.to_thread(
                    store.open_positions_from_scan,
                    recorded,
                    scan_time=scan_finished_at,
                )
            live_surebets = []
            status.surebets_found = 0
            status.recorded_opportunities = len(recorded)
            _last_run_mode[mode] = run_mode
            _recorded_counts[mode] = len(recorded)
            logger.info(
                "recorded %s verified opportunit%s in %s mode (%s)",
                len(recorded),
                "y" if len(recorded) == 1 else "ies",
                run_mode,
                paper_marks or "no paper positions",
            )

        # P0-6: aggregates from the boards this scan actually priced, and the
        # bounded lifetime store keyed by event+market+line+period+settlement.
        summary = await asyncio.to_thread(
            _summarize_pricing,
            scan_metrics,
            surebets,
            price_dropped,
            mode,
            scan_finished_at,
        )
        summary["zero_result_streak"] = _track_zero_result(
            mode, str(summary.get("zero_result_reason") or "")
        )
        _opportunity_by_mode[mode] = summary
        _opportunity_history.insert(0, summary)
        del _opportunity_history[_OPPORTUNITY_HISTORY_MAX:]
        # The streak is part of the persisted coverage state, so save after it.
        _save_coverage_budget()

        # Serialize to dict for JSON responses. A non-advisory run deliberately
        # writes an empty live list, so the dashboard cannot present a recorded
        # opportunity as current.
        surebets_payload, matches_payload = await asyncio.to_thread(
            _serialise_scan_caches, live_surebets, all_matches
        )
        surebets_cache[:] = surebets_payload
        matches_cache[:] = matches_payload

        # Persist to cache file and the sibling diagnostics (worker thread:
        # the cache alone is tens of megabytes).
        await asyncio.to_thread(
            _persist_scan_state,
            mode,
            len(groups),
            scan_finished_at,
            matches_cache,
            report_cache,
        )

        duration_seconds = round(time.perf_counter() - scan_started_monotonic, 3)
        cache_file = _LIVE_CACHE_FILE if is_live else _PREMATCH_CACHE_FILE
        cache_bytes = _cache_size(cache_file)
        books_ok = sorted({match.bookmaker for match in all_matches})
        metrics.set_gauge("bh_scan_duration_seconds", duration_seconds, mode=mode)
        metrics.inc("bh_scan_seconds_total", duration_seconds, mode=mode)
        metrics.inc("bh_scans_completed_total", mode=mode)
        metrics.inc("bh_surebets_found_total", len(live_surebets), mode=mode)
        metrics.set_gauge("bh_surebets_found", len(live_surebets), mode=mode)
        metrics.set_gauge("bh_recorded_opportunities", len(recorded), mode=mode)
        metrics.inc(
            "bh_surebets_dropped_total",
            len(price_dropped),
            mode=mode,
            reason="price_outlier",
        )
        metrics.set_gauge(
            "bh_candidate_queue_size", len(_candidates_for(mode)), mode=mode
        )
        metrics.set_gauge(
            "bh_candidates_found",
            int((candidate_totals.get(mode) or {}).get("found") or len(_candidates_for(mode))),
            mode=mode,
        )
        metrics.set_gauge("bh_cache_size_bytes", cache_bytes, mode=mode)
        metrics.set_gauge("bh_cache_budget_bytes", CACHE_SIZE_BUDGET_BYTES)

        # One completion line an operator or a log collector can act on. The
        # fields are the scan's shape, never a secret or an odds payload.
        logger.info(
            "scan complete",
            extra={
                "mode": mode,
                "run_mode": run_mode,
                "duration_seconds": duration_seconds,
                "books": len(books_ok),
                "books_total": sum(1 for book in BOOKMAKERS if _is_enabled(book)),
                "groups": len(groups),
                "surebets": len(live_surebets),
                "recorded_opportunities": len(recorded),
                "drops": len(price_dropped),
                "cache_bytes": cache_bytes,
            },
        )
        # P1-5/N1-2: decide what is worth saying, then queue it. Delivery is
        # off the scan path; an alert failure must never fail the scan that
        # found it. Non-advisory runs skip the surebet alert (no live bet was
        # published) but still report feed, coverage and resource problems.
        _notify_scan_alerts(
            mode,
            surebets,
            status,
            matches_cache,
            cache_bytes=cache_bytes,
            run_mode=run_mode,
        )
    except Exception as e:
        metrics.inc("bh_scans_failed_total", mode=mode)
        logger.error(
            "scan failed",
            extra={
                "mode": mode,
                "duration_seconds": round(
                    time.perf_counter() - scan_started_monotonic, 3
                ),
            },
            exc_info=True,
        )
        status.errors.append(f"Scan error: {str(e)[:200]}")
    finally:
        status.is_scanning = False
        status.current_bookmaker = ""
        # M2-3: the scan's results are in memory now; the next poll must see
        # them rather than the pre-scan summary.
        _reset_health_cache()
        reset_scan_id(scan_token)


def _notify_scan_alerts(
    mode: str,
    surebets: list[Any],
    status: ScanStatus,
    matches_cache: list[dict],
    *,
    cache_bytes: int,
    run_mode: str = "advisory",
) -> None:
    """Queue operator alerts for one completed scan.

    Every builder is pure and every transport runs on the alert worker, so this
    function only decides. It also swallows its own errors: alert evaluation is
    diagnostics and must not change a scan's outcome.
    """
    if not alert_manager.enabled:
        return
    try:
        if run_mode == "advisory":
            for surebet in surebets:
                payload = (
                    surebet.model_dump(mode="json")
                    if hasattr(surebet, "model_dump")
                    else surebet
                )
                alert = surebet_alert(
                    payload,
                    mode=mode,
                    min_profit_percent=alert_manager.min_profit_percent,
                )
                if alert is not None:
                    alert_manager.notify(alert)

        freshness = _freshness_block(mode, status, matches_cache)
        alert_manager.notify_many(feed_alerts(mode, freshness))
        alert_manager.notify_many(
            quarantine_alerts(mode, _feed_integrity.get(mode) or {})
        )

        coverage_report = _coverage_budget.get(mode) or {}
        flag_count = int(coverage_report.get("flag_count") or 0)
        if (
            COVERAGE_FLAG_ALERT_THRESHOLD > 0
            and flag_count >= COVERAGE_FLAG_ALERT_THRESHOLD
        ):
            alert_manager.notify_many(coverage_drop_alerts(mode, coverage_report))
        mapping_alert = mapping_coverage_alert(
            mode, _mapping_coverage.get(mode) or {}
        )
        if mapping_alert is not None:
            alert_manager.notify(mapping_alert)

        summary = _opportunity_by_mode.get(mode) or {}
        zero_alert = zero_result_alert(
            mode,
            str(summary.get("zero_result_reason") or ""),
            int(summary.get("zero_result_streak") or 0),
            COVERAGE_ALERT_CONSECUTIVE_SCANS,
            summary,
        )
        if zero_alert is not None:
            alert_manager.notify(zero_alert)

        for book, snapshot in _breaker_snapshots(mode).items():
            alert = book_failure_alert(
                mode,
                book,
                snapshot["consecutive_failures"],
                BOOK_BACKOFF_AFTER_FAILURES,
            )
            if alert is not None:
                alert_manager.notify(alert)

        alert_manager.notify_many(
            resource_alerts(
                mode,
                cache_bytes=cache_bytes,
                cache_budget_bytes=CACHE_SIZE_BUDGET_BYTES,
                rss_mb=current_rss_mb(),
                rss_budget_mb=RSS_BUDGET_MB,
            )
        )
    except Exception:  # noqa: BLE001 - alert evaluation is best effort
        logger.warning("alert evaluation failed", exc_info=True)


def _refresh_pairing_summary(
    mode: str,
    matches: list[dict],
    groups: list[dict],
    scan_time: datetime | None = None,
) -> None:
    """Recompute the pairing health metric from the rows being served.

    Called after a scan and after a cache restore. The audit reads the same
    rows the dashboard serves, so the number cannot drift from the list it
    describes; a restart recomputes it after stale groups are dropped.

    N2-3 adds the grouped strict misses and appends one bounded trend point per
    scan. The point keeps its own numerator and denominator, so a quieter scan
    is never mistaken for an improvement.
    """
    try:
        pairing = audit_pairing({"matches": matches, "match_groups": groups})
        summary = {
            key: pairing.get(key)
            for key in (
                "matches",
                "groups",
                "ungrouped",
                "duplicate_listings",
                "strict_misses",
                "strict_miss_rate",
                "strict_miss_group_count",
                "strict_miss_groups",
                "duplicate_book_groups",
            )
        }
        _pairing_summary[mode] = summary
        point = {
            "scan_time": _naive_utc(
                scan_time or datetime.now(UTC)
            ).isoformat(timespec="seconds"),
            "matches": int(pairing.get("matches") or 0),
            "strict_misses": int(pairing.get("strict_misses") or 0),
            "strict_miss_rate": float(pairing.get("strict_miss_rate") or 0.0),
            "strict_miss_group_count": int(
                pairing.get("strict_miss_group_count") or 0
            ),
            "top_groups": [
                {
                    "book_pair": row.get("book_pair", ""),
                    "league": row.get("league", ""),
                    "count": row.get("count", 0),
                    "share": row.get("share", 0.0),
                }
                for row in (pairing.get("strict_miss_groups") or [])[:5]
            ],
        }
        trend = _pairing_trend.setdefault(mode, [])
        if trend and trend[-1].get("scan_time") == point["scan_time"]:
            trend[-1] = point
        else:
            trend.append(point)
            del trend[:-_PAIRING_TREND_MAX]
    except Exception as exc:  # a metric must never stop a scan
        logger.warning("Pairing audit failed: %s", exc)
        _pairing_summary[mode] = {"error": str(exc)[:200]}


def _record_candidate_trend(mode: str, scan_time: datetime | None = None) -> None:
    """Append the current queue's blocker groups and their denominators.

    Best effort, off the scan's critical path: a trend failure must not turn a
    successful scan into an error.
    """
    try:
        queue = list(_candidates_for(mode).values())
        counts = remediation_counts(queue)
        stats = candidate_totals.get(mode) or {}
        point = {
            "scan_time": _naive_utc(
                scan_time or datetime.now(UTC)
            ).isoformat(timespec="seconds"),
            # M2-4: `total` stays the found denominator; the retained queue and
            # the cap that produced it travel with it.
            "total": int(stats.get("found") or len(queue)),
            "retained": int(stats.get("retained") or len(queue)),
            "dropped": int(stats.get("dropped") or 0),
            "cap": int(stats.get("cap") or CANDIDATE_QUEUE_MAX),
            "closeable": (
                counts["alias"] + counts["league"] + counts["alias+league"]
            ),
            "groups": group_candidates(queue, limit=10),
        }
        trend = _candidate_blocker_trend.setdefault(mode, [])
        if trend and trend[-1].get("scan_time") == point["scan_time"]:
            trend[-1] = point
        else:
            trend.append(point)
            del trend[:-_CANDIDATE_TREND_MAX]
    except Exception as exc:  # diagnostics must never stop a scan
        logger.warning("Candidate blocker trend failed: %s", exc)


def _cache_size(path: str) -> int:
    """Return a cache file's size in bytes, or 0 when it does not exist."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _age_seconds(value: datetime | None, now: datetime | None = None) -> float | None:
    """Age of a stored timestamp in seconds, or None when it is unknown."""
    if value is None:
        return None
    reference = now or utcnow()
    try:
        return (reference - _naive_utc(value)).total_seconds()
    except Exception:
        return None


def _parse_timestamp(value: object) -> datetime | None:
    """Read an ISO timestamp from a cached row, or None when absent/malformed."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _freshness_block(mode: str, status: ScanStatus, matches: list[dict]) -> dict[str, Any]:
    """Summarize whether the served feed can still be called current.

    `stale` is deliberately conservative. It is true when the scan itself is
    older than the feed's TTL, and also when any book that supplied a listing
    cannot prove it was fetched inside that TTL. The cached rows stay in the
    payload: the dashboard must still be able to diagnose a stale feed. What
    changes is that they are labelled historical instead of current.
    """
    ttl = LIVE_ODDS_TTL_SECONDS if mode == "live" else ODDS_TTL_SECONDS
    now = utcnow()
    scan_age = _age_seconds(status.last_scan_time, now)
    per_book: dict[str, dict[str, Any]] = {}
    for row in matches:
        if not isinstance(row, dict):
            continue
        bookmaker = str(row.get("bookmaker") or "")
        if not bookmaker:
            continue
        entry = per_book.setdefault(
            bookmaker,
            {
                "bookmaker": bookmaker,
                "matches": 0,
                "oldest_fetched_at": None,
                "newest_fetched_at": None,
                "oldest_age_sec": None,
                "newest_age_sec": None,
                "missing_fetched_at": 0,
                "stale": True,
            },
        )
        entry["matches"] += 1
        fetched_at = _parse_timestamp(row.get("fetched_at"))
        if fetched_at is None:
            entry["missing_fetched_at"] += 1
            continue
        fetched_at = _naive_utc(fetched_at)
        if entry["oldest_fetched_at"] is None or fetched_at < entry["_oldest"]:
            entry["_oldest"] = fetched_at
            entry["oldest_fetched_at"] = fetched_at.isoformat()
        if entry["newest_fetched_at"] is None or fetched_at > entry["_newest"]:
            entry["_newest"] = fetched_at
            entry["newest_fetched_at"] = fetched_at.isoformat()

    stale_books: list[str] = []
    for bookmaker, entry in per_book.items():
        oldest = entry.pop("_oldest", None)
        newest = entry.pop("_newest", None)
        entry["oldest_age_sec"] = _age_seconds(oldest, now)
        entry["newest_age_sec"] = _age_seconds(newest, now)
        # No timestamp is not proof of freshness. A book that cannot state when
        # it fetched a price is treated as stale until it can.
        entry["stale"] = entry["oldest_age_sec"] is None or entry["oldest_age_sec"] > ttl
        if entry["stale"]:
            stale_books.append(bookmaker)

    if scan_age is None:
        state = "never_scanned"
        stale = True
    elif scan_age > ttl:
        state = "scan_older_than_ttl"
        stale = True
    elif stale_books:
        state = "book_older_than_ttl"
        stale = True
    else:
        state = "fresh"
        stale = False

    return {
        "mode": mode,
        "as_of": now.isoformat(),
        "scan_time": status.last_scan_time.isoformat() if status.last_scan_time else None,
        "age_sec": scan_age,
        "ttl_sec": ttl,
        "stale": stale,
        "state": state,
        "stale_books": sorted(stale_books),
        "per_book": dict(sorted(per_book.items())),
    }


def _load_opportunity_metrics() -> None:
    """Restore the last aggregate summary and bounded crossing-key store."""
    global _opportunity_by_mode, _crossing_lifetimes, _opportunity_history
    data = read_json(_OPPORTUNITY_METRICS_FILE)
    if not isinstance(data, dict):
        return
    last = data.get("last")
    if isinstance(last, dict):
        _opportunity_by_mode = {
            mode: value for mode, value in last.items() if isinstance(value, dict)
        }
    lifetimes = data.get("lifetimes")
    if isinstance(lifetimes, dict):
        restored: dict[str, dict[str, dict]] = {"prematch": {}, "live": {}}
        for mode in ("prematch", "live"):
            records = lifetimes.get(mode)
            if isinstance(records, dict):
                restored[mode] = {
                    key: value
                    for key, value in records.items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
        _crossing_lifetimes = restored
    history = data.get("history")
    if isinstance(history, list):
        _opportunity_history = [
            row for row in history if isinstance(row, dict)
        ][:_OPPORTUNITY_HISTORY_MAX]


def _save_opportunity_metrics() -> None:
    """Persist only aggregates and crossing keys, never the full board."""
    try:
        atomic_write_json(
            _OPPORTUNITY_METRICS_FILE,
            {
                "last": _opportunity_by_mode,
                "lifetimes": _crossing_lifetimes,
                "history": _opportunity_history,
            },
            "opportunity_metrics",
            indent=None,
        )
    except Exception as exc:  # a metric must never stop a scan
        logger.warning("Opportunity metrics save failed: %s", exc)


def _load_feed_integrity() -> None:
    """Restore the per-book scorecards and their bounded recent history."""
    global _feed_integrity
    data = read_json(_FEED_INTEGRITY_FILE)
    if not isinstance(data, dict):
        return
    restored: dict[str, dict[str, dict]] = {"prematch": {}, "live": {}}
    for mode in ("prematch", "live"):
        books = data.get(mode)
        if isinstance(books, dict):
            restored[mode] = {
                book: entry
                for book, entry in books.items()
                if isinstance(book, str) and isinstance(entry, dict)
            }
    _feed_integrity = restored


def _save_feed_integrity() -> None:
    """Persist the scorecard; history is already bounded per book."""
    try:
        atomic_write_json(
            _FEED_INTEGRITY_FILE,
            _feed_integrity,
            "feed_integrity",
            indent=None,
        )
    except Exception as exc:  # a metric must never stop a scan
        logger.warning("Feed integrity save failed: %s", exc)


def _load_stale_price_state() -> None:
    """Restore the bounded observation store and last scan's refusals."""
    global _stale_price_store, _stale_price_evidence, _stale_price_checked_at
    data = read_json(_STALE_PRICE_FILE)
    if not isinstance(data, dict):
        return
    stores = data.get("stores")
    evidence = data.get("evidence")
    checked = data.get("checked_at")
    for mode in ("prematch", "live"):
        rows = stores.get(mode) if isinstance(stores, dict) else None
        if isinstance(rows, dict):
            _stale_price_store[mode] = {
                str(key): row
                for key, row in rows.items()
                if isinstance(row, dict)
            }
        last = evidence.get(mode) if isinstance(evidence, dict) else None
        if isinstance(last, list):
            _stale_price_evidence[mode] = [
                row for row in last if isinstance(row, dict)
            ]
        stamp = checked.get(mode) if isinstance(checked, dict) else None
        if isinstance(stamp, str):
            _stale_price_checked_at[mode] = stamp


def _save_stale_price_state() -> None:
    """Persist only the bounded store and the compact refusal evidence."""
    try:
        atomic_write_json(
            _STALE_PRICE_FILE,
            {
                "stores": _stale_price_store,
                "evidence": _stale_price_evidence,
                "checked_at": _stale_price_checked_at,
            },
            "stale_price_state",
            indent=None,
        )
    except Exception as exc:  # a diagnostic must never stop a scan
        logger.warning("Stale-price state save failed: %s", exc)


def _stale_price_payload(mode: str, *, include_rows: bool = True) -> dict[str, Any]:
    """The frozen-price evidence for one feed, bounded by the scan's rows."""
    rows = _stale_price_evidence.get(mode) or []
    by_book: dict[str, int] = {}
    for row in rows:
        book = str(row.get("bookmaker") or "")
        if book:
            by_book[book] = by_book.get(book, 0) + 1
    payload: dict[str, Any] = {
        "mode": mode,
        "count": len(rows),
        "books": dict(sorted(by_book.items())),
        "threshold_scans": STALE_PRICE_UNCHANGED_SCANS,
        "checked_at": _stale_price_checked_at.get(mode) or None,
        "label": STALE_PRICE_LABEL,
        "rule": (
            "refuse a row when the feed's own update time is older than the "
            "mode's TTL, or when its price has not moved for the threshold "
            "scans while an independent peer did move"
        ),
    }
    if include_rows:
        payload["rows"] = rows
    return payload


def _load_coverage_budget() -> None:
    """Restore the rolling coverage, mapping and zero-result state."""
    global _coverage_budget, _coverage_history, _mapping_coverage
    global _coverage_trend, _zero_result_streaks
    global _cardinality, _cardinality_history
    data = read_json(_COVERAGE_BUDGET_FILE)
    if not isinstance(data, dict):
        return
    last = data.get("last")
    if isinstance(last, dict):
        _coverage_budget = {
            mode: last[mode]
            for mode in ("prematch", "live")
            if isinstance(last.get(mode), dict)
        }
    history = data.get("history")
    if isinstance(history, dict):
        _coverage_history = {
            mode: [
                {
                    str(key): int(value)
                    for key, value in sample.items()
                    if isinstance(value, int)
                }
                for sample in history.get(mode, [])
                if isinstance(sample, dict)
            ][-_COVERAGE_HISTORY_MAX:]
            for mode in ("prematch", "live")
        }
    mapping = data.get("mapping")
    if isinstance(mapping, dict):
        _mapping_coverage = {
            mode: mapping[mode]
            for mode in ("prematch", "live")
            if isinstance(mapping.get(mode), dict)
        }
    trend = data.get("trend")
    if isinstance(trend, dict):
        _coverage_trend = {
            mode: [
                point
                for point in trend.get(mode, [])
                if isinstance(point, dict)
            ][-_COVERAGE_TREND_MAX:]
            for mode in ("prematch", "live")
        }
    streaks = data.get("streaks")
    if isinstance(streaks, dict):
        _zero_result_streaks = {
            mode: {
                str(reason): int(count)
                for reason, count in (streaks.get(mode) or {}).items()
                if isinstance(count, int)
            }
            for mode in ("prematch", "live")
        }
    cardinality = data.get("cardinality")
    if isinstance(cardinality, dict):
        _cardinality = {
            mode: cardinality[mode]
            for mode in ("prematch", "live")
            if isinstance(cardinality.get(mode), dict)
        }
    cardinality_history = data.get("cardinality_history")
    if isinstance(cardinality_history, dict):
        _cardinality_history = {
            mode: [
                {
                    str(key): {
                        str(field): int(value)
                        for field, value in entry.items()
                        if isinstance(value, int)
                    }
                    for key, entry in sample.items()
                    if isinstance(entry, dict)
                }
                for sample in cardinality_history.get(mode, [])
                if isinstance(sample, dict)
            ][-_COVERAGE_HISTORY_MAX:]
            for mode in ("prematch", "live")
        }


def _save_coverage_budget() -> None:
    try:
        atomic_write_json(
            _COVERAGE_BUDGET_FILE,
            {
                "last": _coverage_budget,
                "history": _coverage_history,
                "mapping": _mapping_coverage,
                "trend": _coverage_trend,
                "streaks": _zero_result_streaks,
                "cardinality": _cardinality,
                "cardinality_history": _cardinality_history,
            },
            "coverage_budget",
            indent=None,
        )
    except Exception as exc:  # diagnostics must never stop a scan
        logger.warning("Coverage budget save failed: %s", exc)


def _load_scan_cost() -> None:
    """Restore the bounded per-scan per-book cost history."""
    global _scan_cost, _scan_cost_history
    data = read_json(_SCAN_COST_FILE)
    if not isinstance(data, dict):
        return
    last = data.get("last")
    if isinstance(last, dict):
        _scan_cost = {
            mode: last[mode]
            for mode in ("prematch", "live")
            if isinstance(last.get(mode), dict)
        }
    history = data.get("history")
    if isinstance(history, list):
        _scan_cost_history = [
            entry for entry in history if isinstance(entry, dict)
        ][:_SCAN_COST_HISTORY_MAX]


def _save_scan_cost() -> None:
    try:
        atomic_write_json(
            _SCAN_COST_FILE,
            {"last": _scan_cost, "history": _scan_cost_history},
            "scan_cost",
            indent=None,
        )
    except Exception as exc:  # diagnostics must never stop a scan
        logger.warning("Scan cost save failed: %s", exc)


def _feed_integrity_payload(mode: str) -> dict[str, Any]:
    """Compact scorecard for one feed plus the books that are priced out."""
    books = _feed_integrity.get(mode) or {}
    quarantined = sorted(quarantined_books(books))
    return {
        "mode": mode,
        "books": books,
        "quarantined": quarantined,
        "healthy": sorted(
            book for book, entry in books.items() if entry.get("state") == "healthy"
        ),
        "degraded": sorted(
            book for book, entry in books.items() if entry.get("state") == "degraded"
        ),
        "stale_prices": _stale_price_payload(mode, include_rows=False),
        "checked_at": max(
            (
                str(entry.get("scan_time"))
                for entry in books.values()
                if entry.get("scan_time")
            ),
            default=None,
        ),
    }


def _save_cache(mode: str = "prematch"):
    """Persist last scan results to JSON cache files (with TTL metadata P0-6).

    The match report goes out with the rest of it. It is the diagnostic the
    dashboard counts `match_groups` and `verified_groups` from, so persisting the
    surebets and the odds while dropping it left the operator reading 0 verified
    groups for as long as the cache file stayed inside its own 30-minute TTL.
    """
    state = _state_for(mode)
    status = state.status
    surebets_cache = state.surebets
    matches_cache = state.matches
    report_cache = state.report
    cache_file = _LIVE_CACHE_FILE if mode == "live" else _PREMATCH_CACHE_FILE
    try:
        scan_time = status.last_scan_time.isoformat() if status.last_scan_time else None
        # `atomic_write_json` uses `default=str`, so the payload is written
        # directly. Round-tripping it through `json.dumps`/`json.loads` first
        # built two full-size strings for a 180 MB cache and left the RSS
        # high-water mark behind after every scan.
        payload = {
            "surebets": surebets_cache,
            "matches": matches_cache,
            "matches_count": len(matches_cache),
            "match_groups": list(report_cache),
            "mode": mode,
            "run_mode": _last_run_mode.get(mode, "advisory"),
            "recorded_opportunities": _recorded_counts.get(mode, 0),
            "per_bookie": dict(
                cached_live_per_bookie if mode == "live" else cached_per_bookie
            ),
            "scan_time": scan_time,
            "fetched_at": scan_time,
        }
        atomic_write_json(
            cache_file, payload, os.path.basename(cache_file), indent=None
        )
        size = _cache_size(cache_file)
        if size > CACHE_SIZE_BUDGET_BYTES:
            logger.warning(
                "Cache %s is %.1f MB, over the %.1f MB budget — the evidence "
                "payload may have regressed",
                os.path.basename(cache_file),
                size / 1e6,
                CACHE_SIZE_BUDGET_BYTES / 1e6,
            )
    except Exception as e:
        logger.warning(f"Cache save failed: {e}")


def _restorable_match_groups(report: object, mode: str) -> list[dict]:
    """Return the stored report rows a restart is still entitled to show.

    A persisted `verified` row is a snapshot of a decision another process made,
    so it can be older than the store it rests on: a proof may have been cleared
    by a completed check, or aged out, since the scan wrote it. Restoring such a
    row would put back a `verified` claim the store no longer supports — the
    staleness the link TTL exists to prevent, arriving through the cache file
    instead of the store. So a `verified` row survives only while EVERY one of
    its legs is still settled.

    "Settled" is `engine.deeplinks.settle_link` — the gate's own predicate, so the
    two cannot disagree — and this restore supplies one input differently: the
    proof is a FRESH store entry keyed `bookmaker|event_id`, never the cached
    match's flag. `_apply_deep_link_verifications` only ever sets a flag, so a
    restored `deep_link_verified=True` is a scan's snapshot that outlives its
    proof and would make this a copy of the very staleness it is here to catch.

    The predicate's settled cases therefore keep a row:

    * a fresh proof in the store (the gate's case 1, and why `get_match_report`
      emits the id);
    * a dated route-pattern proof plus an event id; and
    * a book that DECLARES no per-event route, where the declaration is itself
      the proof. Six of the nine books are in that case, so demanding a proof of
      their legs would drop every group they belong to, which is the opposite of
      what the restore is for.

    Everything else is `link_unverified` or `no_event_link`, which both block, so
    the row is dropped. That is also why a leg carrying no `event_id`, or a book
    with no declaration at all, drops the row: silence is not proof of absence,
    and a restore must not be the one place that treats it as one.

    A row that fails is DROPPED rather than demoted, and that is the only honest
    option: `group_matches` returns only accepted groups, so a group whose links
    are unproven is not a group the matcher reports at all. Inventing a status for
    it here would put a word in the report's vocabulary that no scan can produce.
    """
    if not isinstance(report, list):
        return []
    with _DEEP_LINK_LOCK:
        entries = dict(_deep_link_verifications.get(mode) or {})
    reference = utcnow()
    kept: list[dict] = []
    for row in report:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "verified":
            kept.append(row)
            continue
        legs = row.get("bookmakers")
        if not isinstance(legs, list) or not legs:
            continue
        proven = True
        for leg in legs:
            if not isinstance(leg, dict):
                proven = False
                break
            bookmaker = str(leg.get("bookmaker") or "")
            if not bookmaker:
                proven = False
                break
            event_id = str(leg.get("event_id") or "")
            record = entries.get(_deep_link_key(bookmaker, event_id)) if event_id else None
            settlement = settle_link(
                bookmaker,
                event_id=event_id,
                # The store, never the cached flag: a restored flag is a
                # snapshot that outlives its proof.
                proof=_deep_link_record_is_fresh(record, reference),
            )
            if not settlement.settled:
                proven = False
                break
        if proven:
            kept.append(row)
        else:
            logger.info(
                f"Dropped a restored {mode} match group: the link store no longer "
                f"settles every leg of '{row.get('canonical_match', '?')}'"
            )
    return kept


def _clear_stale_deep_link_flags(matches: list, mode: str) -> int:
    """Clear a cached `deep_link_verified=True` that no fresh proof backs (M2-2).

    `/api/verify-links` no longer rewrites the scan cache, and a completed failed
    check only REMOVES the proof from the store while clearing the in-memory
    flag. The persisted cache can therefore still carry `deep_link_verified:
    true` from the scan that preceded the check, and trusting it on restart
    would resurrect a link a browser check found dead — the exact staleness the
    link TTL exists to prevent.

    The store is the authority: `_apply_deep_link_verifications` re-applies every
    proof that is still fresh, and this clears every other True. A book the gate
    settles by declaration — a verified route pattern or no per-event route —
    does not need the flag (see `CertaintyGate._link_evidence` cases 2-3), so
    clearing it neither blocks nor unblocks such a group.
    """
    with _DEEP_LINK_LOCK:
        entries = dict(_deep_link_verifications.get(mode) or {})
    reference = utcnow()
    cleared = 0
    for match in matches:
        is_dict = isinstance(match, dict)
        current = bool(
            match.get("deep_link_verified")
            if is_dict
            else getattr(match, "deep_link_verified", False)
        )
        if not current:
            continue
        bookmaker = str(
            (match.get("bookmaker") if is_dict else getattr(match, "bookmaker", ""))
            or ""
        )
        raw_id = match.get("event_id") if is_dict else getattr(match, "event_id", "")
        event_id = "" if raw_id is None else str(raw_id)
        record = (
            entries.get(_deep_link_key(bookmaker, event_id))
            if bookmaker and event_id
            else None
        )
        if _deep_link_record_is_fresh(record, reference):
            continue
        if is_dict:
            match["deep_link_verified"] = False
        else:
            match.deep_link_verified = False
        cleared += 1
    return cleared


def _load_cache():
    """Restore last scan results from the JSON cache files on startup (TTL 30min P0-6)."""
    _load_opportunity_metrics()
    _load_feed_integrity()
    _load_coverage_budget()
    _load_scan_cost()
    for mode, cache_file, state_fields in (
        ("prematch", _PREMATCH_CACHE_FILE,
         (scan_status, cached_surebets, cached_matches, cached_match_groups_report)),
        ("live", _LIVE_CACHE_FILE,
         (live_status, cached_live_surebets, cached_live_matches, cached_live_match_groups_report)),
    ):
        status, surebets_cache, matches_cache, report_cache = state_fields
        try:
            data = read_json(cache_file)
            if not isinstance(data, dict):
                continue
            scan_time = data.get("scan_time")
            # TTL: discard cache older than 30 minutes (stale cache replay guard)
            if scan_time:
                try:
                    parsed = datetime.fromisoformat(scan_time)
                    # Handle naive UTC stored
                    if parsed.tzinfo is None:
                        age = (utcnow() - parsed).total_seconds()
                    else:
                        age = (datetime.now(UTC) - parsed).total_seconds()
                    if age > 1800:
                        logger.info(f"Cache {mode} expired ({age/60:.0f}min old) — discarding")
                        continue
                    status.last_scan_time = parsed
                except ValueError:
                    pass
            _last_run_mode[mode] = (
                data.get("run_mode") if data.get("run_mode") in RUN_MODES else "advisory"
            )
            _recorded_counts[mode] = int(data.get("recorded_opportunities") or 0)
            status.run_mode = _last_run_mode[mode]
            status.recorded_opportunities = _recorded_counts[mode]
            surebets_cache[:] = data.get("surebets", [])
            matches_cache[:] = data.get("matches", [])
            # A restored cache is re-stamped with any link proof that is still
            # inside its TTL, so a restart does not silently demote every group.
            # M2-2: it is re-derived, not trusted — a cached flag can be older
            # than a completed check that removed the proof, because the check
            # no longer rewrites this file.
            _clear_stale_deep_link_flags(matches_cache, mode)
            _apply_deep_link_verifications(matches_cache, mode)
            # And the report is re-checked against that store rather than trusted:
            # see `_restorable_match_groups` for why a stored `verified` row can
            # be older than the proofs it was decided on.
            report_cache[:] = _restorable_match_groups(data.get("match_groups"), mode)
            cached_scan_time: datetime | None = None
            if scan_time:
                try:
                    cached_scan_time = datetime.fromisoformat(str(scan_time).replace("Z", "+00:00"))
                except ValueError:
                    cached_scan_time = None
            _refresh_pairing_summary(mode, matches_cache, report_cache, cached_scan_time)
            # Restore the per-book counts the scan wrote. Deriving them from the
            # cached rows alone would drop a book that was scraped successfully
            # but returned zero matches.
            per_bookie_cache = (
                cached_live_per_bookie if mode == "live" else cached_per_bookie
            )
            stored_per_bookie = data.get("per_bookie")
            if isinstance(stored_per_bookie, dict):
                per_bookie = {
                    str(book): int(count)
                    for book, count in stored_per_bookie.items()
                    if isinstance(count, int)
                }
            else:
                per_bookie = {}
                for row in matches_cache:
                    if not isinstance(row, dict):
                        continue
                    bookmaker = row.get("bookmaker")
                    if isinstance(bookmaker, str) and bookmaker:
                        per_bookie[bookmaker] = per_bookie.get(bookmaker, 0) + 1
            per_bookie_cache.clear()
            per_bookie_cache.update(per_bookie)
            status.total_matches = len(matches_cache)
            status.surebets_found = len(surebets_cache)
            logger.info(
                f"Loaded cached {'live' if mode == 'live' else 'prematch'} scan: "
                f"{len(surebets_cache)} surebets, {len(matches_cache)} matches, "
                f"{len(report_cache)} match groups from {scan_time}"
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
# A verify has its own window; spending it must not spend the scan or deep-link
# budget, and a flood of verifies must not hold the mode lock all afternoon.
_verify_request_times: dict[str, list[float]] = {}
# SR9-3: the leg-link check is bounded PER SUREBET, not per client, because the
# same operator often checks several cards in a row while a double-click on one
# card must not queue two browser runs for it.
_surebet_link_check_times: dict[str, float] = {}


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
    # A named key gets its own bucket; open/local mode still keys on the client.
    state = getattr(request, "state", None)
    client = getattr(state, "api_key_id", "") or (
        request.client.host if request.client else "unknown"
    )
    now_ts = time.time()
    window = [t for t in bucket.get(client, []) if now_ts - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {limit} {what} per "
                f"{RATE_LIMIT_WINDOW_SECONDS} seconds"
            ),
        )
    window.append(now_ts)
    bucket[client] = window


def _enforce_surebet_link_window(mode: str, surebet_id: str) -> None:
    """Refuse a second leg-link check of the same surebet inside the interval.

    The window is charged before any browser work, and it is keyed by the
    surebet rather than the client: checking card A then card B is normal, while
    a double-click on card A must not queue a second Chromium run for it. A 429
    carries Retry-After so the dashboard can say how long to wait.
    """
    interval = SUREBET_LINK_CHECK_MIN_INTERVAL_SECONDS
    if interval <= 0:
        return
    now_ts = time.time()
    for stale in [key for key, at in _surebet_link_check_times.items() if now_ts - at >= interval]:
        del _surebet_link_check_times[stale]
    key = f"{mode}|{surebet_id}"
    last = _surebet_link_check_times.get(key)
    if last is not None:
        remaining = interval - (now_ts - last)
        retry_after = max(1, int(remaining) + (1 if remaining % 1 else 0))
        raise HTTPException(
            status_code=429,
            detail=(
                "This surebet's links were checked moments ago; wait "
                f"{retry_after}s before checking again"
            ),
            headers={"Retry-After": str(retry_after)},
        )
    _surebet_link_check_times[key] = now_ts


async def start_scan_if_idle(mode: str) -> bool:
    """Mark a feed as scanning if no scan or verify already holds it.

    The caller starts `run_scan` only when this returns True. The status flag is
    set under the per-mode lock, so a manual trigger and a scheduler tick cannot
    both claim the same feed.
    """
    status = _state_for(mode).status
    mode_lock = _lock_for(mode)
    if maintenance_running() or mode_lock.locked() or status.is_scanning:
        return False
    async with mode_lock:
        if maintenance_running() or status.is_scanning:
            return False
        status.is_scanning = True
    return True


@router.post("/scan")
async def trigger_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    mode: str = "prematch",
    run_mode: str = "advisory",
    _auth: None = Depends(_require_scope("scan")),
):
    """Trigger a scan (mode=prematch|live, run_mode=advisory|record_only|paper)."""
    if mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'prematch' or 'live'")
    if run_mode not in RUN_MODES:
        raise HTTPException(
            status_code=400,
            detail="run_mode must be 'advisory', 'record_only' or 'paper'",
        )

    status = _state_for(mode).status
    mode_lock = _lock_for(mode)

    if maintenance_running():
        return {
            "status": "maintenance",
            "message": "A bounded maintenance run is in progress. Retry shortly.",
        }

    # Fast-path: verify holds the mode lock during its scrape — don't block
    # for the whole verify, return immediately instead.
    if mode_lock.locked() or status.is_scanning:
        return {
            "status": "already_scanning",
            "message": f"A {mode} scan is already in progress. Please wait.",
        }

    if SCAN_RATE_LIMIT > 0:
        _enforce_sliding_window(request, _scan_request_times, SCAN_RATE_LIMIT, "scans")

    if not await start_scan_if_idle(mode):
        return {
            "status": "already_scanning",
            "message": f"A {mode} scan is already in progress. Please wait.",
        }

    background_tasks.add_task(run_scan, mode, False, run_mode)
    return {
        "status": "started",
        "mode": mode,
        "run_mode": run_mode,
        "message": "Scan started. Poll /api/status for progress.",
    }


def _unverified_link_count(matches: list[dict]) -> int:
    """Matches whose per-event link is unproven AND can still block.

    The predicate is `engine.deeplinks.settle_link`, the same one the gate and
    the cache restore use, with the match's `deep_link_verified` flag as the
    proof. It cannot be reduced to `supports_event_id(book)`: that disagrees with
    the gate exactly on a book with no declaration at all, which is the one case
    where the gate blocks everything and this diagnostic is the reason an
    operator needs. Under it a removed declaration would report 0 unverified
    links while the gate refused every group. A book that declares
    `supports_event_id: false` is excluded by the shared predicate either way:
    the gate settles its link from that declaration, so counting it would report
    thousands of blockers that block nothing.

    One function for both feeds, because the live counter exists only so the
    dashboard can answer for the feed it is showing: a live empty state that
    quoted the prematch count would be quoting a different scan than the one on
    screen.
    """
    return sum(
        1
        for match in matches
        if match.get("event_id")
        and not settle_link(
            str(match.get("bookmaker", "")),
            event_id=str(match.get("event_id") or ""),
            url=str(match.get("url") or ""),
            proof=bool(match.get("deep_link_verified")),
        ).settled
    )


def _last_scan_age_samples() -> list[tuple[dict[str, object], float]]:
    """Age of each feed's last completed scan, computed at scrape time."""
    now = utcnow()
    samples: list[tuple[dict[str, object], float]] = []
    for mode, status in (("prematch", scan_status), ("live", live_status)):
        if status.last_scan_time:
            age = (now - _naive_utc(status.last_scan_time)).total_seconds()
            samples.append(({"mode": mode}, max(0.0, age)))
    return samples


def _cache_size_samples() -> list[tuple[dict[str, object], float]]:
    return [
        ({"mode": "prematch"}, float(_cache_size(_PREMATCH_CACHE_FILE))),
        ({"mode": "live"}, float(_cache_size(_LIVE_CACHE_FILE))),
    ]


metrics.register_gauge_provider(
    "bh_last_scan_age_seconds",
    "Seconds since the last completed scan for each feed.",
    _last_scan_age_samples,
)
metrics.register_gauge_provider(
    "bh_cache_size_bytes",
    "Size of the persisted scan cache for each feed.",
    _cache_size_samples,
)


@router.get("/metrics")
async def get_metrics(_auth: None = Depends(_require_api_key)):
    """Prometheus text exposition. Protected like every other /api route."""
    return PlainTextResponse(
        metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# M2-3: /api/health is polled every few seconds, and every call used to re-read
# the parser contracts, the admissibility baseline and the retention store, then
# walk every cached match, group and candidate. Those blocks are cached for
# `HEALTH_CACHE_SECONDS`; the live fields (scanning state, counters, breakers,
# book health, memory, alerts and the deep-link declaration source) are built per
# request, so a scan in progress and a finished scan are never hidden. The build
# is synchronous, so inside the event loop it cannot interleave with itself; a
# deployment with several workers keeps one cache per worker.
_health_cache: tuple[dict[str, Any], float, str] | None = None
_health_clock = time.monotonic


def _reset_health_cache() -> None:
    """Drop the cached summary (a scan starts or finishes; tests)."""
    global _health_cache
    _health_cache = None


def _health_summary() -> tuple[dict[str, Any], dict[str, Any]]:
    """The expensive part of /api/health, cached for ``HEALTH_CACHE_SECONDS``."""
    global _health_cache
    now = _health_clock()
    cached = _health_cache
    if HEALTH_CACHE_SECONDS > 0 and cached is not None:
        body, built_at, generated_at = cached
        if now - built_at < HEALTH_CACHE_SECONDS:
            return body, {
                "ttl_seconds": HEALTH_CACHE_SECONDS,
                "generated_at": generated_at,
                "age_seconds": round(now - built_at, 3),
            }
    body = {
        "pairing": _pairing_summary.get("prematch") or {},
        "live_pairing": _pairing_summary.get("live") or {},
        # P0-6: a zero-surebet scan must be distinguishable from a broken feed.
        "opportunity_metrics": {
            "prematch": _opportunity_by_mode.get("prematch") or {},
            "live": _opportunity_by_mode.get("live") or {},
        },
        "feed_integrity": {
            "prematch": _feed_integrity_payload("prematch"),
            "live": _feed_integrity_payload("live"),
        },
        # N0-2: rows refused because the book's feed shows a frozen price.
        # The full row list stays in /api/results; health keeps the counts.
        "stale_prices": {
            "prematch": _stale_price_payload("prematch", include_rows=False),
            "live": _stale_price_payload("live", include_rows=False),
        },
        # N0-4: last scan's closing-line capture counts per feed.
        "closing_capture": _closing_capture,
        # P2-7: measured price agreement and any config-declared twin that the
        # scan did not reproduce. Low-sample pairs say insufficient_data.
        "skin_detection": _skin_detection,
        "coverage_budget": _coverage_budget,
        # SR4-5: per book+sport event/market cardinality against the rolling
        # median. A flag quarantines through feed integrity; it never prices.
        "cardinality_floor": _cardinality,
        # N1-2: per-scan mapping coverage with its numerator/denominator, the
        # bounded trend the dashboard draws, and the repeated-zero counters.
        "mapping_coverage": _mapping_coverage,
        "coverage_trend": _coverage_trend,
        "zero_result_streaks": _zero_result_streaks,
        "coverage_slo": {
            "flag_alert_threshold": COVERAGE_FLAG_ALERT_THRESHOLD,
            "mapping_coverage_floor": MAPPING_COVERAGE_FLOOR,
            "mapping_min_rows": MAPPING_COVERAGE_MIN_ROWS,
            "consecutive_scans": COVERAGE_ALERT_CONSECUTIVE_SCANS,
        },
        # N1-3: the last scan's per-book cost, with explicit totals. Only
        # durations, counts, sizes and outcomes are served.
        "scan_cost": {
            "prematch": _scan_cost.get("prematch") or {},
            "live": _scan_cost.get("live") or {},
        },
        # N2-6: dated parser contracts. The payload is a freshness/coverage
        # diagnostic; a changed feed still needs a human re-capture and the
        # existing admissibility evidence before any market is priced.
        "parser_contracts": contract_health(
            enabled_books=[
                book for book, config in BOOKMAKERS.items() if config.get("enabled")
            ]
        ),
        # N3-2: the dated sport/market admissibility audit. It reports the
        # shipped baseline's status; it never enables a sport or market.
        "admissibility_audit": admissibility_health(),
        "unmapped_markets": dict(unmapped_markets),
        "unmapped_markets_by_book": unmapped_by_book(),
        "verified_groups": sum(
            1
            for report in cached_match_groups_report
            if report.get("status") == "verified"
        ),
        "pending_candidates": len(pending_candidates),
        "live_pending_candidates": len(pending_live_candidates),
        # M2-4: the review queue is capped, so the found denominator and the
        # dropped tail sit next to the retained count; nothing is trimmed
        # silently.
        "candidate_queue": {
            "prematch": candidate_totals.get("prematch") or {},
            "live": candidate_totals.get("live") or {},
        },
        "candidate_blockers": {
            "prematch": blocker_counts(pending_candidates.values()),
            "live": blocker_counts(pending_live_candidates.values()),
        },
        # N2-3: ranked, proposal-only remediation. The queue total is the
        # denominator; groups are review-work ranking, never coverage progress.
        "candidate_remediation": {
            "prematch": remediation_summary(list(pending_candidates.values()), limit=10),
            "live": remediation_summary(list(pending_live_candidates.values()), limit=10),
        },
        "candidate_blocker_trend": _candidate_blocker_trend,
        # N2-3: strict-miss groups and their per-scan trend, each point with its
        # own matches/strict-misses denominator.
        "pairing_trend": _pairing_trend,
        "suppressed_candidates": len(_suppressed_candidates),
        # Matches whose per-event link is unproven AND can still block. See
        # `_unverified_link_count` for why the predicate is the gate's and why
        # the live feed is counted separately rather than answered from this one.
        "unverified_links": _unverified_link_count(cached_matches),
        "live_unverified_links": _unverified_link_count(cached_live_matches),
        # The same freshness policy the results payload serves. Health is where
        # an operator checks whether a quiet scan is fresh data or a stale feed.
        "freshness": {
            "prematch": _freshness_block("prematch", scan_status, cached_matches),
            "live": _freshness_block("live", live_status, cached_live_matches),
        },
        # P0-1 guard. A scan cache that outgrows the budget means the persisted
        # evidence payload regressed to carrying data it does not need; the size
        # is reported rather than hidden so the regression is visible without a
        # filesystem check.
        "cache": {
            "prematch_bytes": _cache_size(_PREMATCH_CACHE_FILE),
            "live_bytes": _cache_size(_LIVE_CACHE_FILE),
            "budget_bytes": CACHE_SIZE_BUDGET_BYTES,
            "over_budget": max(
                _cache_size(_PREMATCH_CACHE_FILE), _cache_size(_LIVE_CACHE_FILE)
            ) > CACHE_SIZE_BUDGET_BYTES,
        },
        # N1-1: every runtime store's size, its budget and the last bounded
        # maintenance run. A crossed budget is a warning, never a scan stop.
        "retention": retention_health()
    }
    generated_at = utcnow().isoformat(timespec="seconds")
    if HEALTH_CACHE_SECONDS > 0:
        _health_cache = (body, now, generated_at)
    return body, {
        "ttl_seconds": HEALTH_CACHE_SECONDS,
        "generated_at": generated_at,
        "age_seconds": 0.0,
    }


@router.get("/health")
async def health() -> dict[str, Any]:
    """Health + per-bookie diagnostics (P1-6)."""
    def age_sec(dt):
        if not dt:
            return None
        try:
            # Handle naive UTC stored
            if dt.tzinfo is None:
                return (utcnow() - dt).total_seconds()
            return (datetime.now(UTC) - dt).total_seconds()
        except Exception:
            return None

    rss_mb = current_rss_mb()
    book_health = {
        mode: build_book_health(
            mode,
            bookmakers=BOOKMAKERS,
            enabled=_bookmaker_enabled,
            breakers=_breaker_snapshots(mode),
            scan_cost=_scan_cost.get(mode),
            failure_rates=book_failure_rates(_scan_cost_history, mode),
        )
        for mode in ("prematch", "live")
    }
    summary, cache_meta = _health_summary()
    return {
        **summary,
        "health_cache": cache_meta,
        "status": "ok",
        "scanning": scan_status.is_scanning or live_status.is_scanning,
        "surebets_cached": len(cached_surebets),
        "matches_cached": len(cached_matches),
        "live_surebets_cached": len(cached_live_surebets),
        "live_matches_cached": len(cached_live_matches),
        # SR5-2: one state per book and feed, reduced from the SR2-1 kind, the
        # SR2-6 breaker and the runtime toggle. It is a diagnostic: pricing
        # still reads feed integrity and the certainty gate, never this field.
        "book_health": book_health,
        # The declaration map the gate is actually reading, not the one in the
        # file on disk. The map reloads when the file's mtime/size changes, and
        # `deep_link_declaration_source` carries loaded_at/source_mtime/stale so
        # a failed reload or a file edit is visible. `configured: false` marks a
        # book the gate is silently failing safe on, which is the other thing
        # this map has to be able to say.
        "deep_link_declarations": effective_deeplink_declarations(BOOKMAKERS),
        "deep_link_declaration_source": deeplink_declaration_source(),
        "deep_link_declaration_audit": declaration_audit(
            BOOKMAKERS, DEEPLINK_DECLARATION_MAX_AGE_DAYS
        ),
        "scheduler": {
            "prematch_minutes": AUTO_SCAN_PREMATCH_MINUTES,
            "live_minutes": AUTO_SCAN_LIVE_MINUTES,
            # SR2-6: one circuit breaker per (mode, book). `state` is closed,
            # open or half_open; an open breaker skips the book on scheduled
            # scans until `cooldown_remaining_seconds` reaches zero, then one
            # probe decides whether it closes. Manual scans always try.
            "breakers": {
                f"{mode}/{book}": _breaker(mode, book).snapshot()
                for mode in ("prematch", "live")
                for book in BOOKMAKERS
            },
        },
        "mapping_learning": last_learning_report,
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
        # P1-5/P1-6: delivery counters and the soft resource budget. The
        # snapshot names transports, never their URLs or tokens.
        "alerts": alert_manager.snapshot(),
        "memory": {
            "rss_mb": rss_mb,
            "budget_mb": RSS_BUDGET_MB,
            "over_budget": rss_mb is not None and rss_mb > RSS_BUDGET_MB,
        },
    }


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@router.post("/shutdown")
async def shutdown_server(request: Request, _auth: None = Depends(_require_scope("admin"))):
    """Stop the server process (the dashboard's "Stop server" button).

    Only a client on this machine may call it: HOST defaults to 0.0.0.0, so
    without the loopback check anyone on the LAN could kill the scanner.
    The SIGINT is raised after a short delay so this response reaches the
    browser first; uvicorn's own handler then runs a clean lifespan shutdown.
    """
    client = request.client.host if request.client else ""
    api_key_store.audit("shutdown", getattr(request.state, "api_key_id", ""), client)
    if client not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="Shutdown is only allowed from this computer")
    logger.info("Shutdown requested from the dashboard")
    asyncio.get_running_loop().call_later(0.5, signal.raise_signal, signal.SIGINT)
    return {"status": "stopping"}


@router.get("/status")
async def get_status(mode: str = "prematch"):
    """Get the current scan status (mode=prematch|live)."""
    return _state_for(mode).status.model_dump(mode="json")


GROUP_PAGE_SIZE = 50
GROUP_PAGE_MAX = 200


def _group_summary(row: dict) -> dict:
    """One report row without the potentially large evidence trail."""
    evidence = row.get("evidence")
    evidence_rows = evidence if isinstance(evidence, list) else []
    reasons = sorted(
        {
            str(item.get("reason"))
            for item in evidence_rows
            if isinstance(item, dict) and item.get("reason")
        }
    )
    bookmakers = row.get("bookmakers")
    legs = bookmakers if isinstance(bookmakers, list) else []
    return {
        "group_id": row.get("group_id"),
        "sport": row.get("sport", "football"),
        "canonical_match": row.get("canonical_match", ""),
        "league": row.get("league", ""),
        "kickoff": row.get("kickoff", ""),
        "status": row.get("status", ""),
        "bookmakers": [
            {
                "bookmaker": leg.get("bookmaker", ""),
                "event_id": leg.get("event_id", ""),
                "num_markets": leg.get("num_markets", 0),
            }
            for leg in legs
            if isinstance(leg, dict)
        ],
        "evidence_count": len(evidence_rows),
        "reasons": reasons,
    }


def _group_page(
    mode: str,
    *,
    status: str,
    sport: str,
    search: str,
    limit: int,
    offset: int,
) -> dict:
    """Filter and page the cached report, never returning the whole list by default."""
    report_cache = _state_for(mode).report
    rows = list(report_cache)
    if status:
        rows = [row for row in rows if str(row.get("status", "")) == status]
    if sport:
        rows = [
            row for row in rows if str(row.get("sport") or "football") == sport
        ]
    if search:
        needle = search.casefold()
        rows = [
            row
            for row in rows
            if needle
            in f"{row.get('canonical_match', '')} {row.get('league', '')}".casefold()
        ]
    page = max(1, min(limit, GROUP_PAGE_MAX))
    start = max(0, offset)
    total = len(rows)
    window = rows[start : start + page]
    return {
        "mode": mode,
        "total": total,
        "count": len(window),
        "limit": page,
        "offset": start,
        "has_more": start + len(window) < total,
        "groups": [_group_summary(row) for row in window],
    }


def _sport_summary(
    matches: list[dict], report: list[dict], surebets: list[dict]
) -> dict[str, dict[str, int]]:
    """Per-sport match/group/verified/surebet counts for the results payload."""
    summary: dict[str, dict[str, int]] = {}
    for match in matches:
        sport = str(match.get("sport") or "football")
        bucket = summary.setdefault(
            sport, {"matches": 0, "groups": 0, "verified_groups": 0, "surebets": 0}
        )
        bucket["matches"] += 1
    for group in report:
        sport = str(group.get("sport") or "football")
        bucket = summary.setdefault(
            sport, {"matches": 0, "groups": 0, "verified_groups": 0, "surebets": 0}
        )
        bucket["groups"] += 1
        if group.get("status") == "verified":
            bucket["verified_groups"] += 1
    for surebet in surebets:
        sport = str(surebet.get("sport") or "football")
        bucket = summary.setdefault(
            sport, {"matches": 0, "groups": 0, "verified_groups": 0, "surebets": 0}
        )
        bucket["surebets"] += 1
    return dict(sorted(summary.items()))


@router.get("/results")
async def get_results(mode: str = "prematch"):
    """Get the cached results from the last scan (mode=prematch|live)."""
    state = _state_for(mode)
    status = state.status
    surebets_cache = state.surebets
    matches_cache = state.matches
    report_cache = state.report
    group_statuses: dict[str, int] = {}
    for report in report_cache:
        group_status = str(report.get("status", "unknown"))
        group_statuses[group_status] = group_statuses.get(group_status, 0) + 1
    return {
        "surebets": surebets_cache,
        "total_matches": len(matches_cache),
        "surebets_count": len(surebets_cache),
        "mode": mode,
        # P3-7: a record-only or paper run publishes no live surebet, so the
        # dashboard can state what the last scan was instead of guessing.
        "run_mode": _last_run_mode.get(mode, "advisory"),
        "recorded_opportunities": _recorded_counts.get(mode, 0),
        "match_groups": len(report_cache),
        "group_statuses": group_statuses,
        "sport_stats": _sport_summary(matches_cache, report_cache, surebets_cache),
        "unmapped_markets": dict(unmapped_markets),
        "pairing": _pairing_summary.get(mode) or {},
        "last_scan_time": (
            status.last_scan_time.isoformat()
            if status.last_scan_time
            else None
        ),
        # P0-4: cached rows stay here for diagnosis, but the feed's age is now
        # a first-class state. A stale result is labelled, not silently shown as
        # a current opportunity.
        "freshness": _freshness_block(mode, status, matches_cache),
        # P0-6: the denominator behind the surebet count, plus the bounded
        # lifetime distribution. Empty before the first scan of a mode.
        "opportunity_metrics": _opportunity_by_mode.get(mode) or {},
        # P0-7: which books were priced this scan, and why a refused book was
        # refused. The certainty gate's identity verdicts are separate.
        "feed_integrity": _feed_integrity_payload(mode),
        # N0-2: the exact rows refused as frozen, with the feed timestamp and
        # peer-movement evidence that refused them.
        "stale_prices": _stale_price_payload(mode),
    }


@router.get("/mapping/coverage")
async def get_mapping_coverage(mode: str = "prematch"):
    """Read-only mapping coverage and quarantined claims for Diagnostics."""
    state = _state_for(mode)
    matches_cache = state.matches
    report_cache = state.report
    ledger = load_ledger()
    return build_coverage(
        ledger,
        matches_cache,
        report_cache,
        mode=mode,
        unmapped_markets=dict(unmapped_markets),
    )


@router.get("/config")
async def get_config():
    """Get current configuration for the frontend (reflects runtime toggles)."""
    return {
        "bookmakers": {
            k: {
                "name": v["name"],
                "enabled": _is_enabled(k),
                "color": v["color"],
                "max_stake": BOOK_STAKE_LIMITS.get(k, 500),
                "risk_profile": book_risk_profile(k)["profile"],
                "typical_max_stake_note": book_risk_profile(k)["typical_max_stake_note"],
                "limit_risk": book_risk_profile(k)["limit_risk"],
            }
            for k, v in BOOKMAKERS.items()
        },
        "experimental_markets": {m: _market_enabled.get(m, False) for m in EXPERIMENTAL_MARKETS},
        "sports": [
            {"id": sport, "label": sport.replace("_", " ").title()}
            for sport in ENABLED_SPORTS
        ],
        "min_profit_percent": MIN_PROFIT_PERCENT,
        "dust_profit_percent": DUST_PROFIT_PERCENT,
        "default_investment": DEFAULT_INVESTMENT,
    }


@router.post("/config/toggle_market/{market}")
async def toggle_market(
    market: str,
    request: Request,
    _auth: None = Depends(_require_scope("admin")),
):
    """Enable or disable an experimental market for future scans."""
    if market not in _market_enabled:
        raise HTTPException(status_code=404, detail=f"Unknown experimental market: {market}")

    _market_enabled[market] = not _market_enabled[market]
    new_state = _market_enabled[market]
    _save_market_state()

    logger.info(f"Experimental market '{market}' toggled {'ON' if new_state else 'OFF'}")
    api_key_store.audit("toggle_market", getattr(request.state, "api_key_id", ""), market)
    return {
        "status": "ok",
        "market": market,
        "enabled": new_state,
    }


@router.post("/config/toggle/{bookmaker_id}")
async def toggle_bookmaker(
    bookmaker_id: str,
    request: Request,
    _auth: None = Depends(_require_scope("admin")),
):
    """Enable or disable a bookmaker for future scans."""
    if bookmaker_id not in BOOKMAKERS:
        raise HTTPException(status_code=404, detail=f"Unknown bookmaker: {bookmaker_id}")

    current = _is_enabled(bookmaker_id)
    _bookmaker_enabled[bookmaker_id] = not current
    new_state = _bookmaker_enabled[bookmaker_id]
    _save_bookmaker_state()

    logger.info(f"Bookmaker '{bookmaker_id}' toggled {'ON' if new_state else 'OFF'}")
    api_key_store.audit("toggle_bookmaker", getattr(request.state, "api_key_id", ""), bookmaker_id)
    return {
        "status": "ok",
        "bookmaker_id": bookmaker_id,
        "enabled": new_state,
    }


@router.get("/debug/matches")
async def get_matches_breakdown(mode: str = "prematch"):
    """Debug endpoint: show match counts per bookmaker and all raw match data."""
    from collections import defaultdict
    matches_cache = _state_for(mode).matches
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


@router.get("/groups")
async def get_groups(
    mode: ScanMode = "prematch",
    status: str = "",
    sport: str = "",
    search: str = "",
    limit: int = GROUP_PAGE_SIZE,
    offset: int = 0,
):
    """List bounded group summaries; use `/api/groups/{group_id}` for evidence."""
    return _group_page(
        mode,
        status=status,
        sport=sport,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/groups/{group_id}")
async def get_group(group_id: int, mode: ScanMode = "prematch"):
    """Return exactly one group's full evidence trail, or 404."""
    report_cache = _state_for(mode).report
    for row in report_cache:
        try:
            if int(row.get("group_id", -1)) == group_id:
                return {"mode": mode, "group": row}
        except (TypeError, ValueError):
            continue
    raise HTTPException(status_code=404, detail=f"Unknown group_id {group_id}")


@router.get("/debug/report")
async def get_match_report(
    mode: ScanMode = "prematch",
    limit: int = GROUP_PAGE_SIZE,
    offset: int = 0,
):
    """Deprecated compatibility alias for the bounded group list.

    It no longer returns every group by default. New callers should use
    `/api/groups` and `/api/groups/{group_id}` for the full evidence.
    """
    page = _group_page(
        mode, status="", sport="", search="", limit=limit, offset=offset
    )
    return {
        **page,
        "total_groups": page["total"],
        "deprecated": (
            "use /api/groups for summaries and /api/groups/{group_id} for evidence"
        ),
    }


def _finite_number(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    return value


def _positive_investment(value: float) -> float:
    value = _finite_number(value)
    if value <= 0:
        raise ValueError("investment must be positive")
    if value > 1_000_000:
        raise ValueError("investment must be at most 1000000")
    return value


class RecalculateRequest(BaseModel):
    surebet_id: str
    investment: float
    mode: str = "prematch"
    rounding: Literal["exact", "1", "5"] = "exact"

    @field_validator("investment")
    @classmethod
    def _validate_investment(cls, value: float) -> float:
        return _positive_investment(value)


class VerifyRequest(BaseModel):
    surebet_id: str
    mode: str = "prematch"


class BetLegPayload(BaseModel):
    bookmaker: str
    outcome_label: str
    odds: float
    stake: float
    accepted_odds: float | None = None
    accepted_stake: float | None = None
    closing_odds: float | None = None
    result: str = ""
    # The exact source market of this leg, used by closing-line capture (N0-4).
    market_type: str = ""
    line: str = ""
    settlement: str = ""
    period: str = ""

    @field_validator("odds", "closing_odds")
    @classmethod
    def _validate_odds(cls, value: float | None) -> float | None:
        if value is None:
            return value
        value = _finite_number(value)
        if value <= 1:
            raise ValueError("odds must be greater than 1")
        if value > 1_000:
            raise ValueError("odds must be at most 1000")
        return value

    @field_validator("accepted_odds")
    @classmethod
    def _validate_accepted_odds(cls, value: float | None) -> float | None:
        if value is None:
            return value
        value = _finite_number(value)
        # Zero is the explicit "this leg was not placed" sentinel, matching a
        # zero accepted stake; every other value must be a real price.
        if value == 0:
            return value
        if value <= 1:
            raise ValueError("accepted odds must be 0 or greater than 1")
        if value > 1_000:
            raise ValueError("accepted odds must be at most 1000")
        return value

    @field_validator("stake", "accepted_stake")
    @classmethod
    def _validate_stake(cls, value: float | None) -> float | None:
        if value is None:
            return value
        value = _finite_number(value)
        if value < 0:
            raise ValueError("stake must not be negative")
        if value > 1_000_000_000:
            raise ValueError("stake must be at most 1000000000")
        return value

    @model_validator(mode="after")
    def _a_stake_needs_a_price(self) -> "BetLegPayload":
        """Refuse a positive accepted stake at accepted odds 0 (M1-2).

        Zero is the explicit "not placed" sentinel, but it is a sentinel on
        BOTH fields: a stake the book accepted at no price is an impossible
        claim, and the settle path would silently neutralise it, dropping the
        operator's money from P/L with no warning. ``accepted_odds=None`` still
        means "price not typed" and keeps the planned-odds fallback, so only the
        zero-with-stake pair is refused.
        """
        if self.accepted_stake and self.accepted_odds == 0:
            raise ValueError(
                "accepted_stake cannot be positive when accepted_odds is 0: "
                "0 means the leg was not placed, so record 0 for both"
            )
        return self


class BetCreateRequest(BaseModel):
    surebet_id: str = ""
    mode: str = "prematch"
    home_team: str = ""
    away_team: str = ""
    market_type: str = ""
    investment: float
    legs: list[BetLegPayload]
    notes: str = ""
    # Stable event identity and kickoff, so a later scan can capture a closing
    # line without guessing which fixture this bet was on (N0-4).
    event_key: str = ""
    kickoff: datetime | None = None
    league: str = ""
    sport: str = "football"

    @field_validator("investment")
    @classmethod
    def _validate_investment(cls, value: float) -> float:
        return _positive_investment(value)


class BetSettlementLeg(BaseModel):
    outcome_label: str
    result: Literal["won", "lost", "void"]


class BetSettlementRequest(BaseModel):
    legs: list[BetSettlementLeg]


class BetClosingLeg(BaseModel):
    outcome_label: str
    closing_odds: float

    @field_validator("closing_odds")
    @classmethod
    def _validate_closing_odds(cls, value: float) -> float:
        value = _finite_number(value)
        if value <= 1:
            raise ValueError("closing odds must be greater than 1")
        if value > 1_000:
            raise ValueError("closing odds must be at most 1000")
        return value


class BetClosingRequest(BaseModel):
    legs: list[BetClosingLeg]


class LinkSweepReport(BaseModel):
    """One completed sweep, as written by scripts/sweep_links.py."""
    bookmaker: str
    mode: str = "prematch"
    started_at: str = ""
    ended_at: str = ""
    status: str = "running"
    calls: int = 0
    available: int = 0
    checked: int = 0
    verified: int = 0
    failed: int = 0
    errored: int = 0
    unchecked: int = 0
    remaining: int = 0
    last_next_offset: int = 0
    rate_limit_waits: int = 0
    http_error: str = ""
    calls_detail: list[dict[str, Any]] = []


@router.get("/candidates")
async def get_candidates(
    limit: int = CANDIDATE_PAGE_SIZE,
    offset: int = 0,
    mode: ScanMode = "prematch",
    actionable_only: bool = False,
    closeable_only: bool = False,
    _auth: None = Depends(_require_api_key),
):
    """List match candidates awaiting human review, one bounded page at a time.

    The queue is ordered by actionability, so the first page is the part a
    reviewer can actually work through. `total` is the full queue size so a UI
    can say "showing N of M" instead of pretending the page is the queue.

    ``actionable_only`` draws the page from the pairs an approval can actually
    close (``alias_actionable``), which is what the Review tab used to ask for.
    ``closeable_only`` is the N2-3 form: it also includes pairs a league
    equivalence would close, because a league mapping is a second kind of human
    action. ``actionable_total`` and ``closeable_total`` are always reported, so
    the tab can state what it is not showing.
    """
    page = max(1, min(limit, CANDIDATE_PAGE_MAX))
    start = max(0, offset)
    queue = list(_candidates_for(mode).values())
    total = len(queue)
    actionable_total = sum(1 for candidate in queue if candidate.alias_actionable)
    blockers = blocker_counts(queue)
    counts = remediation_counts(queue)
    closeable_total = counts["alias"] + counts["league"] + counts["alias+league"]
    # M2-4: `total` is the retained queue the page is drawn from; `found` is the
    # denominator (every unverified pair the scan's walk produced). A capped
    # queue that reported only `total` would read as "that is all there was".
    stats = candidate_totals.get(mode) or {}
    found = int(stats.get("found") or total)
    dropped = int(stats.get("dropped") or 0)
    cap = int(stats.get("cap") or CANDIDATE_QUEUE_MAX)
    if closeable_only:
        queue = [candidate for candidate in queue if _candidate_closeable(candidate)]
    elif actionable_only:
        queue = [candidate for candidate in queue if candidate.alias_actionable]
    window = queue[start:start + page]
    return {
        "mode": mode,
        "total": total,
        "found": found,
        "retained": total,
        "dropped": dropped,
        "cap": cap,
        "actionable_total": actionable_total,
        "closeable_total": closeable_total,
        # The same two answers over the FOUND set, so a cap that ever drops an
        # actionable pair does not hide it behind a retained-set count.
        "actionable_found": int(stats.get("actionable_found") or actionable_total),
        "closeable_found": int(stats.get("closeable_found") or closeable_total),
        "blocker_counts": blockers,
        "remediation_counts": counts,
        "actionable_only": actionable_only,
        "closeable_only": closeable_only,
        "count": len(window),
        "limit": page,
        "offset": start,
        "candidates": [
            {**candidate.model_dump(mode="json"), "name_score": _name_score(candidate)}
            for candidate in window
        ],
    }


def _candidate_closeable(candidate: CandidateReview) -> bool:
    """Whether an alias or league mapping could still close the pair.

    Production candidates carry the assessed ``remediation`` block. A
    candidate built before this field existed falls back to the alias answer,
    which is the only human action the old queue knew about.
    """
    if candidate.remediation is not None:
        return candidate.remediation.closeable
    return candidate.alias_actionable


def _name_score(candidate: CandidateReview) -> int:
    """How alike the two spellings are in the weakest team slot (0–100).

    A ranking aid for the reviewer, never a decision: approval is still a human
    act. "Slavia P." / "Slavia Prague" scores high; "Sabah" / "Dortmund" low.
    """
    scores = [
        max(
            fuzz.token_set_ratio(position.team_a.casefold(), position.team_b.casefold()),
            fuzz.partial_ratio(position.team_a.casefold(), position.team_b.casefold()),
        )
        for position in candidate.team_positions
        if position.team_a and position.team_b
    ]
    return int(min(scores)) if scores else 0


@router.get("/history")
async def get_history(
    days: int = Query(30, ge=0, le=3650),
    mode: str = "",
    limit: int = _HISTORY_MAX,
    _auth: None = Depends(_require_api_key),
):
    """Scan history queried from SQLite (newest first).

    ``days=0`` returns the in-memory recent list; a positive window answers the
    P3-1 question without reading a large JSON file.
    """
    if days > 0 and _storage is not None:
        entries = _storage.list_scans(days=days, mode=mode, limit=limit)
    else:
        entries = [
            row for row in scan_history if not mode or row.get("mode") == mode
        ][: max(1, min(limit, _HISTORY_MAX))]
    return {"count": len(entries), "entries": entries, "days": days}


def _find_surebet_group(
    groups: list[MatchGroup], target: dict
) -> MatchGroup | None:
    """Find the fresh group for a cached surebet, in the cached orientation.

    The surebet stores the canonical names of the group it was built on. A fresh
    grouping can anchor the same fixture on a different book, so a member
    match's normalized names are accepted as well as the group's canonical
    ones. When the fixture comes back with home and away reversed, every member
    is flipped into the cached frame, so outcome "1" still means the same team
    the cached stake backed. Kickoff must agree within the verified window.
    """
    home = (target.get("home_team") or "").lower()
    away = (target.get("away_team") or "").lower()
    if not home or not away:
        return None
    kickoff = target.get("kickoff")
    target_kickoff: datetime | None = None
    if isinstance(kickoff, str):
        try:
            target_kickoff = datetime.fromisoformat(kickoff)
        except ValueError:
            target_kickoff = None
    if target_kickoff is not None and target_kickoff.tzinfo is not None:
        target_kickoff = target_kickoff.astimezone(UTC).replace(tzinfo=None)

    for group in groups:
        names = {((group.canonical_home or "").lower(), (group.canonical_away or "").lower())}
        names.update(
            ((m.home_team_normalized or "").lower(), (m.away_team_normalized or "").lower())
            for m in group.matches
        )
        if (home, away) in names:
            reversed_frame = False
        elif (away, home) in names:
            reversed_frame = True
        else:
            continue
        if target_kickoff is not None and group.kickoff is not None:
            group_kickoff = group.kickoff
            if group_kickoff.tzinfo is not None:
                group_kickoff = group_kickoff.astimezone(UTC).replace(tzinfo=None)
            delta = abs((group_kickoff - target_kickoff).total_seconds()) / 60.0
            if delta > VERIFIED_KICKOFF_WINDOW_MINUTES:
                continue
        if reversed_frame:
            return group.model_copy(update={
                "canonical_home": group.canonical_away,
                "canonical_away": group.canonical_home,
                "matches": [swap_match_teams_and_odds(m) for m in group.matches],
            })
        return group
    return None


@router.post("/verify")
async def verify_surebet(
    req: VerifyRequest,
    request: Request,
    _auth: None = Depends(_require_scope("scan")),
):
    """
    Live odds verification: re-scrape ONLY the bookmakers involved in a surebet,
    re-group the match, and re-price the exact outcome set the surebet was built
    on. Returns whether that bet is still an arbitrage.

    The fresh matches go through the same pipeline a scan uses — stored
    deep-link proofs are applied before grouping, so a group the scan verified
    on a proven link is verified here too, and only `verified` groups are ever
    priced.
    """
    if req.mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'prematch' or 'live'")
    is_live = req.mode == "live"
    surebets_cache = _state_for(req.mode).surebets
    target = next((s for s in surebets_cache if s.get("id") == req.surebet_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Surebet not found")

    # Charged before the lock and the scrape: a repeated caller must be refused
    # instead of queueing more full browser runs behind the mode lock.
    _enforce_sliding_window(
        request, _verify_request_times, VERIFY_RATE_LIMIT, "verifications"
    )

    mode_lock = _lock_for(req.mode)
    status_for_mode = _state_for(req.mode).status
    async with mode_lock:
        if status_for_mode.is_scanning:
            raise HTTPException(
                status_code=409,
                detail="A scan is in progress — retry after it finishes",
            )

        bookie_ids = sorted({s["bookmaker"] for s in target["stakes"] if _is_enabled(s["bookmaker"])})
        if not bookie_ids:
            raise HTTPException(status_code=400, detail="All involved bookmakers are disabled")

        fetched_at = utcnow()
        fresh_matches: list[Match] = []
        errors: list[str] = []
        for bookie_id in bookie_ids:
            scraper_class = SCRAPERS.adapter(bookie_id)
            if not scraper_class:
                continue
            # Same browser budget as a scan: a verify must not open a third
            # Chromium alongside a running deep-link check.
            sem = _browser_sem if bookie_id in PLAYWRIGHT_BOOKIES else None
            if sem:
                await sem.acquire()
                _metric_browser_opened(1)
            try:
                scraper = scraper_class()
                fresh_matches.extend(await scraper.scrape(live=is_live, scan_time=fetched_at))
            except Exception as e:
                errors.append(f"{bookie_id}: {str(e)[:150]}")
            finally:
                if sem:
                    sem.release()
                    _metric_browser_opened(-1)

    for match in fresh_matches:
        if not match.fetched_at:
            match.fetched_at = fetched_at
    missing = sorted(set(bookie_ids) - {m.bookmaker for m in fresh_matches})
    for bookie_id in missing:
        if not any(e.startswith(f"{bookie_id}:") for e in errors):
            errors.append(f"{bookie_id}: returned no matches")

    # Proofs first, exactly as run_scan does, or every group holding a book
    # with a declared per-event route would be refused as `link_unverified`.
    _apply_deep_link_verifications(fresh_matches, req.mode)
    groups = MatchMatcher().group_matches(fresh_matches)
    group = _find_surebet_group(groups, target)

    if group is None:
        return {
            "surebet_id": target["id"],
            "message": "Match not found in fresh data (removed, renamed or no longer verified)",
            "cached_margin": target["total_margin"],
            "cached_profit_percent": target["profit_percent"],
            "still_profitable": None,
            "errors": errors,
        }

    # The fixture can verify without one of the bet's books (its fresh listing
    # failed the gate, e.g. an unproven link, or the book is now disabled).
    # Re-pricing would then silently swap that leg for another book's price —
    # a verdict on a different bet. The leg this surebet was built on is
    # unknown, so the answer is too.
    unverified_books = sorted(
        {s["bookmaker"] for s in target["stakes"]} - {m.bookmaker for m in group.matches}
    )
    if unverified_books:
        return {
            "surebet_id": target["id"],
            "message": (
                "Not every leg's bookmaker is in the verified fresh group "
                f"({', '.join(unverified_books)})"
            ),
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

    # N0-2: a verify is a pricing pass too. Apply the frozen-price rule against
    # the last scan's observations, but do not persist a partial observation
    # store: this scrape covered only the books in this bet.
    stale_result = evaluate_stale_prices(
        [group],
        dict(_stale_price_store.get(req.mode) or {}),
        mode=req.mode,
        now=utcnow(),
        ttl_sec=LIVE_ODDS_TTL_SECONDS if is_live else ODDS_TTL_SECONDS,
    )
    stale_rows = stale_result.evidence

    labels = [s["outcome_label"] for s in target["stakes"]]
    current = engine.evaluate_market(group, market_type, labels=labels) if market_type else None
    if current is None:
        return {
            "surebet_id": target["id"],
            "message": (
                "A leg's price is frozen and was refused"
                if stale_rows
                else "The outcomes this surebet needs are no longer all offered"
            ),
            "cached_margin": target["total_margin"],
            "cached_profit_percent": target["profit_percent"],
            "still_profitable": False,
            "stale_prices": stale_rows,
            "errors": errors,
        }

    old_by_label = {s["outcome_label"]: s for s in target["stakes"]}
    drift = {}
    for label, old in old_by_label.items():
        new = current["odds"].get(label)
        drift[label] = {
            "old_odds": old["odds"],
            "old_bookmaker": old["bookmaker"],
            "new_odds": new["odds"] if new else None,
            "new_bookmaker": new["bookmaker"] if new else None,
            "changed": (
                new is None
                or abs(new["odds"] - old["odds"]) > 0.001
                or new["bookmaker"] != old["bookmaker"]
            ),
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
        # Any positive margin is still a guaranteed profit. The scan lists
        # surebets down to DUST_PROFIT_PERCENT, so judging them against the
        # higher MIN_PROFIT_PERCENT would report an unchanged dust bet as gone.
        "still_profitable": current["margin"] < 1.0,
        "meets_min_profit": current["profit_percent"] >= MIN_PROFIT_PERCENT,
        "stale_prices": stale_rows,
        "errors": errors,
    }


@router.post("/surebets/{surebet_id}/check-links")
async def check_surebet_links(
    surebet_id: str,
    mode: str = "prematch",
    _auth: None = Depends(_require_scope("scan")),
):
    """Open one served surebet's leg links and report what each one showed.

    ON-DEMAND BY DESIGN. Each check opens up to one page per leg in a real
    browser for several seconds, so it never runs inside a scan and is refused
    while the mode is scanning. It is bounded per SUREBET rather than per client
    (a double-click on one card must not queue two browser runs, while checking
    several cards in a row is normal) and shares the deep-link checker's
    one-browser lock, so the two on-demand browsers never run together.

    It is ADVISORY: the result says whether the page showed both team names
    (book spelling) and, for a ticket rung, whether the slip repeated the pick
    after the page's own slip wording. It never sets `deep_link_verified`,
    never changes a group's status and never submits anything. A surebet whose
    legs are all search/competition fallbacks is reported as skipped without
    touching a browser, because there is no per-fixture page to open.

    The response carries `checked_at` and the cost, so the dashboard can show
    how old the result is instead of presenting it as live.
    """
    from server.leg_link_check import build_targets, report_for, skip_reason

    if mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'prematch' or 'live'")
    target = next(
        (s for s in _state_for(mode).surebets if str(s.get("id") or "") == surebet_id),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Surebet not found")
    status = _state_for(mode).status
    if _lock_for(mode).locked() or status.is_scanning:
        raise HTTPException(
            status_code=409,
            detail=f"A {mode} scan is in progress — retry after it finishes",
        )
    if not build_targets(target):
        # No per-fixture rung to open: report it, and do not charge the window
        # or a browser for a check that could not learn anything.
        return report_for(target, mode, utcnow(), [], "skipped", skip_reason(target))

    _enforce_surebet_link_window(mode, surebet_id)
    async with _deep_link_check_lock:
        async with _browser_sem:
            _metric_browser_opened(1)
            try:
                return await _run_leg_link_check(target, mode)
            finally:
                _metric_browser_opened(-1)


async def _run_leg_link_check(surebet: dict, mode: str) -> dict:
    """Run the SR9-3 browser check. The endpoint's only browser seam."""
    from server.leg_link_check import check_surebet

    return await check_surebet(surebet, mode=mode)


@router.post("/recalculate")
async def recalculate_stakes(
    req: RecalculateRequest,
    _auth: None = Depends(_require_scope("scan")),
):
    """Recalculate optimal stakes for a given investment amount."""
    if req.investment <= 0:
        raise HTTPException(status_code=400, detail="Investment must be positive")
    if req.investment > 1_000_000:
        raise HTTPException(status_code=400, detail="Investment too large")

    # Find the surebet in the mode-specific cache
    surebets_cache = _state_for(req.mode).surebets
    target = next(
        (s for s in surebets_cache if s.get("id") == req.surebet_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Surebet not found")

    # Recalculate from the served odds, not from the cached rounded margin.
    # That is the same source a reviewer recomputes by hand.
    odds = [float(stake["odds"]) for stake in target["stakes"]]
    raw_margin = implied_sum(odds)
    if raw_margin >= 1.0 or raw_margin <= 0:
        raise HTTPException(status_code=400, detail="Not a valid surebet")

    new_stakes = []
    for stake in target["stakes"]:
        leg_odds = float(stake["odds"])
        raw_stake = req.investment * (1.0 / leg_odds) / raw_margin
        rounded_stake = round_stake(raw_stake, req.rounding)
        new_stakes.append({
            "bookmaker": stake["bookmaker"],
            "outcome_label": stake["outcome_label"],
            "odds": leg_odds,
            "stake": rounded_stake,
            "potential_return": round(rounded_stake * leg_odds, 2),
        })

    summary = rounding_summary(
        new_stakes,
        investment=req.investment,
        rounding=req.rounding,
    )
    exact = {
        "return": summary["exact_return"],
        "profit": summary["exact_profit"],
        "profit_percent": summary["exact_profit_percent"],
    }
    return {
        "stakes": new_stakes,
        "investment": req.investment,
        "raw_margin": raw_margin,
        "implied_sum": raw_margin,
        "exact": exact,
        "realized": summary,
        # Kept for older clients; these are the exact, not realized, values.
        "guaranteed_return": summary["exact_return"],
        "guaranteed_profit": summary["exact_profit"],
    }


@router.post("/verify-links")
async def verify_links(
    request: Request,
    bookmaker: str = "",
    mode: str = "prematch",
    limit: int = DEEP_LINK_VERIFY_DEFAULT_LIMIT,
    offset: int = 0,
    recheck: bool = False,
    _auth: None = Depends(_require_scope("scan")),
):
    """Prove — or fail to prove — one bookmaker's per-event deep links.

    ON-DEMAND BY DESIGN. This navigates a real browser to real bookmaker pages,
    seconds per event, so it is never triggered from `run_scan` and never runs
    while a scan holds the mode. The response states what it cost and what it
    did NOT cover, because a check that silently skipped events would read as a
    clean bill of health.

    A bookmaker that declares no per-event route (`supports_event_id: false`)
    has nothing to check and is reported as skipped, never as a failure.

    THE SWEEP SELF-ADVANCES, and that is the point. The events this book has
    already been CHECKED on — every completed check, whether it proved the link
    or not, from :func:`_decided_event_ids` — are skipped before the window is
    cut, so a run always spends its budget on events nobody has looked at, and
    repeated calls walk the book instead of replaying its first `limit` events.
    The caller keeps no state and holds no cursor; the store does. When every
    event has been decided the call reports `remaining: 0` and checks nothing,
    so a sweep loop can stop. A stored PROOF does not by itself settle an event
    (see :func:`_decided_event_ids` for why), so a proven link can still be
    checked again and fail.

    `offset` is the OTHER mechanism, for a caller with no store of the server's
    verdicts: it resumes at the Nth undecided event. It is a position in the
    POST-skip ordering and the skip set grows as the sweep proceeds, so a cursor
    carried over from an earlier call skips further ahead than the number says.
    Leave it at 0 here. The response echoes `offset` and `settled_count` so the
    composition is visible rather than something a caller has to know.

    `recheck=1` ignores the recorded decisions for one call, which is the only
    way back to an event this server has already decided — needed because a
    proven link stops unblocking a `verified` group only by being checked again
    and failing. A sweep should not pay for that, so it is opt-in.

    Cost control, because `API_KEY` is empty by default on most deployments:
    a per-client sliding window refuses a flood with 429, `_browser_sem` keeps
    total browser concurrency inside `BROWSER_CONCURRENCY`, and the scan state
    is re-checked AFTER the multi-minute await so a scan that started meanwhile
    is never overwritten. The window is charged before the browser work, so the
    rate limit is what paces a sweep — raising it means a browser per call, and
    the cursor is what made those calls worth making.
    """
    from server.deeplink_verifier import (
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
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be at least 0")
    limit = min(limit, DEEP_LINK_VERIFY_MAX_LIMIT)

    state = _state_for(mode)
    status = state.status
    matches_cache = state.matches
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
            "remaining": 0,
            "offset": offset,
            "settled_count": 0,
            "next_offset": 0,
            "duration_seconds": 0.0,
            # None, not False: nothing was written because nothing needed to be,
            # which is not the same as a write being suppressed.
            "applied": None,
            "applied_note": "",
            "details": [],
        }

    live = mode == "live"
    published = len(build_targets(matches_cache, bookmaker, base_url, live=live))
    if published == 0:
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
            "remaining": 0,
            "offset": offset,
            "settled_count": 0,
            "next_offset": 0,
            "duration_seconds": 0.0,
            "applied": None,
            "applied_note": "",
            "details": [],
        }

    settled: set[str] = set() if recheck else _decided_event_ids(mode, bookmaker)
    available = len(
        build_targets(
            matches_cache, bookmaker, base_url, live=live, offset=offset, settled=settled
        )
    )
    if available == 0:
        # Converged. Saying so — and checking nothing — is what lets a sweep
        # loop stop instead of re-checking the book until the throttle cuts it.
        return {
            "bookmaker": bookmaker,
            "mode": mode,
            "status": "checked",
            "skip_reason": (
                f"every {bookmaker} event in the {mode} cache has already been decided "
                f"({len(settled)} settled, {published} published) — nothing left to check"
            ),
            "criterion": CRITERION,
            "available": 0,
            "checked": 0,
            "verified": 0,
            "failed": 0,
            "errored": 0,
            "unchecked": 0,
            "remaining": 0,
            "offset": offset,
            "settled_count": len(settled),
            "next_offset": 0,
            "duration_seconds": 0.0,
            "applied": None,
            "applied_note": "",
            "details": [],
        }

    # Charged here, not above: a book that declares no route, a cache with no
    # event ids, and a book that is already fully decided all return without
    # touching a browser, and a UI that probes any of them would otherwise spend
    # the budget doing nothing.
    _enforce_sliding_window(
        request, _verify_link_request_times, DEEP_LINK_VERIFY_RATE_LIMIT, "verify-links checks"
    )

    # One browser at a time, and never more than BROWSER_CONCURRENCY across the
    # whole server: a scan that starts after the 409 check above still finds its
    # browser budget respected here.
    async with _deep_link_check_lock:
        async with _browser_sem:
            _metric_browser_opened(1)
            try:
                report = await _run_link_verification(
                    bookmaker,
                    matches_cache,
                    mode=mode,
                    live=live,
                    limit=limit,
                    offset=offset,
                    settled=settled,
                )
            finally:
                _metric_browser_opened(-1)

    if report.checked:
        for outcome_name, count in (
            ("verified", report.verified),
            ("failed", report.failed),
            ("errored", report.errored),
        ):
            metrics.inc(
                "bh_link_checks_total",
                count,
                mode=mode,
                book=bookmaker,
                outcome=outcome_name,
            )

    # A completed check is worth keeping even if a scan overtook us: the store is
    # per-event, TTL'd and written atomically, and the next scan applies it.
    _record_deep_link_outcomes(mode, bookmaker, report.outcomes)
    # And so is the fact that the events were DECIDED, which is what keeps the
    # next call off them. Outside the `applied` branch for the same reason.
    _record_deep_link_decisions(mode, bookmaker, report.outcomes)

    # Re-check AFTER the multi-minute await. The 409 above is a snapshot taken
    # minutes before the writes below, and overwriting a running scan's cache
    # would publish a half-written snapshot of a different feed.
    status_after = _state_for(mode).status
    scan_underway = _lock_for(mode).locked() or status_after.is_scanning
    applied = not scan_underway
    applied_note = ""
    if applied:
        # M2-2: update the in-memory cache, never `_save_cache`. A check
        # changes a handful of `deep_link_verified` flags, and serialising the
        # whole 27 MB scan cache per call to persist that is the cost this row
        # removes. The verdict is durable already: `_record_deep_link_outcomes`
        # writes or removes the proof and `_record_deep_link_decisions` records
        # the event, both small atomic files. `_load_cache` re-derives the flag
        # from that store, so the next start cannot resurrect a cleared proof.
        apply_report(matches_cache, report)
        _apply_deep_link_verifications(matches_cache, mode)
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
        f"{'' if applied else ' — cache left to the scan'}"
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
        # Undecided events this run did not reach, and where to resume. `remaining`
        # counts from `offset` onwards, so it is the same number as `unchecked` here;
        # an event this run reached and could not complete is in `errored` and is
        # still undecided, which is why `remaining` can read 0 with work left.
        "remaining": report.remaining,
        "offset": offset,
        "settled_count": len(settled),
        "next_offset": report.next_offset,
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


def _load_link_sweeps() -> dict[str, Any]:
    loaded = read_json(_LINK_SWEEP_FILE)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("sweeps"), list):
        return {"sweeps": []}
    return loaded


@router.post("/link-sweeps")
async def save_link_sweep(
    report: LinkSweepReport,
    _auth: None = Depends(_require_scope("scan")),
):
    """Persist one completed link sweep for the Diagnostics view."""
    payload = _load_link_sweeps()
    payload["sweeps"].append(report.model_dump(mode="json"))
    payload["sweeps"] = payload["sweeps"][-_LINK_SWEEP_MAX:]
    atomic_write_json(_LINK_SWEEP_FILE, payload, "link_sweeps")
    return {"saved": True, "count": len(payload["sweeps"])}


@router.get("/link-sweeps")
async def get_link_sweeps(
    bookmaker: str = "",
    mode: str = "",
    limit: int = 20,
):
    """Read the last sweeps, newest last, optionally filtered by book/mode."""
    rows = [
        row
        for row in _load_link_sweeps()["sweeps"]
        if isinstance(row, dict)
        and (not bookmaker or row.get("bookmaker") == bookmaker)
        and (not mode or row.get("mode") == mode)
    ]
    limit = max(1, min(limit, _LINK_SWEEP_MAX))
    return {"sweeps": rows[-limit:], "count": len(rows[-limit:])}


def _require_bet_store() -> BetStore:
    if _bet_store is None:
        raise HTTPException(status_code=503, detail="Bet store is not initialized")
    return _bet_store


def _enrich_bet_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill event and market identity from the cached surebet when omitted.

    The dashboard sends these fields; this keeps older clients and manual API
    callers capturable instead of silently producing a bet with no kickoff or no
    source market. It never overwrites a value the caller supplied (N0-4).
    """
    surebet_id = str(payload.get("surebet_id") or "")
    if not surebet_id:
        return payload
    mode = str(payload.get("mode") or "prematch")
    cache = cached_live_surebets if mode == "live" else cached_surebets
    target = next((item for item in cache if item.get("id") == surebet_id), None)
    if target is None:
        return payload
    for key in ("event_key", "kickoff", "league", "sport"):
        if not payload.get(key):
            payload[key] = target.get(key) or ""
    stakes = {
        (str(stake.get("bookmaker") or ""), str(stake.get("outcome_label") or "")): stake
        for stake in target.get("stakes") or []
    }
    for leg in payload.get("legs") or []:
        stake = stakes.get(
            (str(leg.get("bookmaker") or ""), str(leg.get("outcome_label") or ""))
        )
        if stake is None:
            continue
        for key in ("market_type", "line", "settlement", "period"):
            if not leg.get(key):
                leg[key] = stake.get(key) or ""
    return payload


@router.post("/bets")
async def create_bet(
    req: BetCreateRequest,
    _auth: None = Depends(_require_scope("scan")),
):
    """Log a manually placed bet. The scanner never places it."""
    if req.investment <= 0:
        raise HTTPException(status_code=400, detail="Investment must be positive")
    if not req.legs:
        raise HTTPException(status_code=400, detail="A bet needs at least one leg")
    payload = _enrich_bet_payload(req.model_dump(mode="json"))
    payload["legs"] = [
        {**leg, "result": leg.get("result") or ""} for leg in payload["legs"]
    ]
    return _require_bet_store().create(payload)


@router.get("/bets")
async def get_bets(days: int = Query(30, ge=0, le=3650), limit: int = 200):
    """Read the bet log window; settled and open bets are both returned."""
    return {"bets": _require_bet_store().list_bets(days=max(1, days), limit=limit)}


@router.get("/bets/summary")
async def get_bet_summary(days: int = Query(30, ge=0, le=3650)):
    """Bankroll, ROI, CLV and closing-capture denominators."""
    summary = _require_bet_store().summary(days=max(1, days))
    summary["last_capture"] = {
        "prematch": _closing_capture.get("prematch") or {},
        "live": _closing_capture.get("live") or {},
    }
    return summary


@router.get("/bets/export.csv")
async def export_bets_csv(days: int = Query(30, ge=0, le=3650)):
    """CSV round-trip export of the bet log."""
    csv_text = _require_bet_store().export_csv(days=max(1, days))
    return PlainTextResponse(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bh-arb-bets.csv"'},
    )


@router.get("/paper/opportunities")
async def get_paper_opportunities(
    days: int = Query(30, ge=0, le=3650),
    limit: int = 200,
    offset: int = 0,
    run_mode: str = "",
    feed_mode: str = "",
):
    """Compact snapshots recorded by record-only and paper scans."""
    if run_mode and run_mode not in RUN_MODES:
        raise HTTPException(status_code=400, detail="Unknown run_mode")
    if feed_mode and feed_mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="Unknown feed_mode")
    store = _paper_store_or_init()
    window = max(1, days)
    return {
        "opportunities": store.list_opportunities(
            days=window,
            limit=limit,
            run_mode=run_mode,
            feed_mode=feed_mode,
            offset=max(0, offset),
        ),
        "total": store.count_opportunities(
            days=window, run_mode=run_mode, feed_mode=feed_mode
        ),
        "limit": max(1, min(limit, 5000)),
        "offset": max(0, offset),
        "run_mode": run_mode or "all",
        "feed_mode": feed_mode or "all",
        "no_bet_placed": True,
    }


@router.get("/paper/positions")
async def get_paper_positions(
    days: int = Query(30, ge=0, le=3650),
    limit: int = 200,
    offset: int = 0,
    status: Literal["", "open", "settled"] = "",
    feed_mode: str = "",
):
    """Virtual positions; their entry legs are paper, not accepted bets."""
    if feed_mode and feed_mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="Unknown feed_mode")
    store = _paper_store_or_init()
    window = max(1, days)
    return {
        "positions": store.list_positions(
            days=window,
            limit=limit,
            status=status,
            feed_mode=feed_mode,
            offset=max(0, offset),
        ),
        "total": store.count_positions(
            days=window, status=status, feed_mode=feed_mode
        ),
        "limit": max(1, min(limit, 5000)),
        "offset": max(0, offset),
        "status": status or "all",
        "feed_mode": feed_mode or "all",
        "no_bet_placed": True,
    }


@router.get("/paper/summary")
async def get_paper_summary(days: int = Query(30, ge=0, le=3650)):
    """Simulated ROI, hit rate and CLV with explicit denominators."""
    store = _paper_store_or_init()
    summary = store.summary(days=max(1, days))
    retention = retention_health(storage_path=store.path)
    tables = retention["tables"]
    summary["store"] = {
        "path": store.path,
        "bytes": retention["sqlite"]["bytes"],
        "rows": {
            "recorded_opportunities": int(
                tables.get("recorded_opportunities", {}).get("rows", 0)
            ),
            "paper_positions": int(
                tables.get("paper_positions", {}).get("rows", 0)
            ),
        },
        "retention": {
            "paper_days": retention["windows"]["paper_days"],
            "paper_max_rows": retention["windows"]["paper_max_rows"],
        },
        "last_maintenance": retention["last_maintenance"],
    }
    return summary


@router.get("/paper/export.csv")
async def export_paper_csv(
    days: int = Query(30, ge=0, le=3650),
    run_mode: str = "",
    feed_mode: str = "",
    status: Literal["", "open", "settled"] = "",
):
    """CSV round-trip of recorded opportunities and paper positions."""
    if run_mode and run_mode not in RUN_MODES:
        raise HTTPException(status_code=400, detail="Unknown run_mode")
    if feed_mode and feed_mode not in ("prematch", "live"):
        raise HTTPException(status_code=400, detail="Unknown feed_mode")
    csv_text = _paper_store_or_init().export_csv(
        days=max(1, days),
        run_mode=run_mode,
        feed_mode=feed_mode,
        status=status,
    )
    return PlainTextResponse(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bh-arb-paper.csv"'},
    )


@router.post("/paper/positions/{position_id}/settle")
async def settle_paper_position(
    position_id: str,
    req: BetSettlementRequest,
    _auth: None = Depends(_require_scope("scan")),
):
    """Settle a paper position from operator-entered results; no bet exists."""
    result = _paper_store_or_init().settle(
        position_id, [leg.model_dump() for leg in req.legs]
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Paper position not found")
    return result


@router.post("/bets/{bet_id}/settle")
async def settle_bet(
    bet_id: str,
    req: BetSettlementRequest,
    _auth: None = Depends(_require_scope("scan")),
):
    """Settle every leg; the realized P/L is computed from accepted amounts."""
    result = _require_bet_store().settle(
        bet_id, [leg.model_dump() for leg in req.legs]
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Bet not found")
    return result


@router.post("/bets/{bet_id}/closing")
async def set_bet_closing(
    bet_id: str,
    req: BetClosingRequest,
    _auth: None = Depends(_require_scope("scan")),
):
    """Record closing prices for CLV without changing the bet's state."""
    result = _require_bet_store().set_closing(
        bet_id, [leg.model_dump() for leg in req.legs]
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Bet not found")
    return result


class ApiKeyCreateRequest(BaseModel):
    label: str = "operator"
    scopes: list[str] = ["read", "scan"]


@router.post("/keys")
async def create_api_key(
    req: ApiKeyCreateRequest,
    request: Request,
    _auth: None = Depends(_require_scope("admin")),
):
    """Create a named key. The plaintext token is returned exactly once."""
    try:
        token, record = api_key_store.create(req.label, req.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api_key_store.audit(
        "key_created_via_api",
        getattr(request.state, "api_key_id", ""),
        record["id"],
    )
    return {"token": token, "key": record}


@router.get("/keys")
async def list_api_keys(_auth: None = Depends(_require_scope("admin"))):
    """List key metadata; hashes and salts are never returned."""
    return {"keys": api_key_store.list_keys()}


@router.delete("/keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    request: Request,
    _auth: None = Depends(_require_scope("admin")),
):
    """Revoke a key immediately; the next request using it answers 401."""
    if not api_key_store.revoke(key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    api_key_store.audit(
        "key_revoked_via_api",
        getattr(request.state, "api_key_id", ""),
        key_id,
    )
    return {"revoked": True, "id": key_id}


@router.get("/audit")
async def get_audit_log(limit: int = 100, _auth: None = Depends(_require_scope("admin"))):
    """Privileged-action audit trail, newest first."""
    return {"entries": api_key_store.audit_log(limit)}
