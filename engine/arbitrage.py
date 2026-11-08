"""
Arbitrage Engine — Surebet Detection & Stake Calculator

Core math:
  implied_probability_i = 1 / decimal_odds_i
  total_implied = Σ implied_probability_i
  surebet exists if total_implied < 1.0
  profit_percent = (1 / total_implied - 1) × 100

  Optimal stake_i = investment × (1/odds_i) / total_implied
  This guarantees equal return regardless of which outcome wins.

Sanity checks:
  - Price only groups the certainty gate verified
  - Reject profit > 20% (almost certainly a data/scraper error)
  - Reject if total_implied ≥ 1.0 (no arbitrage)
  - Require minimum number of outcomes for each market
"""

import logging
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from itertools import permutations

from config.settings import (
    DEFAULT_INVESTMENT,
    EXPIRY_BUFFER_MINUTES,
    LIVE_ODDS_TTL_SECONDS,
    MATCH_URL_TEMPLATES,
    MAX_SUREBET_PROFIT_PERCENT,
    MAX_TWO_SOURCE_PROFIT_PERCENT,
    MIN_PROFIT_PERCENT,
    ODDS_TTL_SECONDS,
    PREMATCH_EXPIRY_BUFFER_MINUTES,
    price_source,
)
from engine.ah_labels import ah_label, parse_ah_label
from engine.destinations import attach_destinations
from engine.opportunity_metrics import BoardObservation, ScanMetrics, event_identity
from engine.pricing_invariant import rounding_summary
from models.schemas import (
    Market,
    MarketType,
    Match,
    MatchGroup,
    RoundingSummary,
    Surebet,
    SurebetStake,
)


def _rounding_block(
    stakes: list[SurebetStake], investment: float
) -> RoundingSummary:
    """Exact vs realized profit for the stake rows about to be served."""
    return RoundingSummary.model_validate(
        rounding_summary(
            [stake.model_dump() for stake in stakes],
            investment=investment,
            rounding="exact",
        )
    )


logger = logging.getLogger(__name__)


def _too_good_for_two_sources(
    profit_percent: float,
    odds_map: dict[str, tuple[str, float]],
    available_books: int,
) -> bool:
    """Reject a large edge that only two independent price sources support.

    A 13% edge between two books is far more often one stale or suspended price
    than a placeable bet (research cited in docs/MULTISPORT_EVIDENCE.md). The
    rule does not lower the global cap and does not touch three-source edges.
    """
    sources = {price_source(bookmaker) for bookmaker, _ in odds_map.values()}
    return (
        profit_percent >= MAX_TWO_SOURCE_PROFIT_PERCENT
        and len(sources) < 3
        and available_books < 3
    )


def _collect_match_urls(group: MatchGroup) -> dict[str, str]:
    """Bookmaker → match page URL for every bookmaker in a group."""
    urls: dict[str, str] = {}
    for match in group.matches:
        urls[match.bookmaker] = match.url or MATCH_URL_TEMPLATES.get(match.bookmaker, "")
    return urls


def _collect_bet_urls(group: MatchGroup) -> dict[str, str]:
    """Bookmaker → bet-slip prefill URL for every bookmaker in a group.

    Empty when the bookmaker does not support URL-based ticket prefill —
    the frontend then falls back to the match page URL.
    """
    urls: dict[str, str] = {}
    for match in group.matches:
        urls[match.bookmaker] = match.bet_url or ""
    return urls


_EVIDENCE_TEXT = {
    "exact": "teams match exactly",
    "swapped": "teams match with home/away reversed",
    "allowlisted_alias": "a team spelling was approved in review",
    "league_unmapped_teams_exact": "league named differently, settled by exact teams and kickoff",
    "verified_link": "event link proven by a browser check",
    "no_event_link": "book has no per-event page (declared)",
}


def _collect_listings(group: MatchGroup) -> dict[str, dict[str, str]]:
    """Bookmaker → how that book lists the fixture (its own spelling)."""
    listings: dict[str, dict[str, str]] = {}
    for match in group.matches:
        listings[match.bookmaker] = {
            "home": match.home_team_source or match.home_team,
            "away": match.away_team_source or match.away_team,
            "league": match.league,
            "kickoff": match.kickoff.isoformat() if match.kickoff else "",
        }
    return listings


def _evidence_summary(group: MatchGroup) -> list[str]:
    """Distinct, human-readable statements of why the group is one match."""
    lines: list[str] = []
    for item in group.evidence:
        text = _EVIDENCE_TEXT.get(item.reason)
        if item.rule == "league_identity" and not item.reason and item.confidence >= 1.0:
            text = "same league"
        if item.rule == "kickoff" and item.kickoff_delta_minutes is not None:
            text = (
                "same kickoff"
                if item.kickoff_delta_minutes < 1
                else f"kickoffs {item.kickoff_delta_minutes:.0f} min apart"
            )
        if text and text not in lines:
            lines.append(text)
    return lines


def _priced_markets(match: Match) -> list[Market]:
    """The markets a listing may be priced from.

    A market refused by the frozen-price quarantine is not a price at all: the
    book may still be healthy for other rows, but this one may not supply a leg
    (N0-2). The filter is here, before the ambiguity guard, so a stale copy of a
    market can never win a best-price comparison.

    One listing quoting the same outcome in two markets of one type is two
    different bets under one name (NSoft live once sent the match total and the
    home team's total both as "Over/Under 2.5"). Taking the better price would
    price a bet that does not exist, so the whole type is dropped for that
    listing instead.
    """
    markets = [market for market in match.markets if not market.stale_price]
    seen: dict[MarketType, set[str]] = {}
    ambiguous: set[MarketType] = set()
    for market in markets:
        # The multi-line non-football families legitimately repeat a type for
        # each line ("total" at 211.5, 212.5, ...). Their labels carry the line,
        # so a repeated label is the same bet and the engine takes the best
        # price; the football collision this guard exists for cannot occur.
        if market.market_type in (
            MarketType.MONEYLINE,
            MarketType.MONEYLINE_3WAY,
            MarketType.HANDICAP,
            MarketType.TOTAL,
        ):
            continue
        labels = {odd.label for odd in market.odds}
        quoted = seen.setdefault(market.market_type, set())
        if quoted & labels:
            ambiguous.add(market.market_type)
        quoted |= labels
    if not ambiguous:
        return markets
    logger.warning(
        f"[{match.bookmaker}] {match.home_team} - {match.away_team}: "
        f"{sorted(t.value for t in ambiguous)} quoted twice; not priced"
    )
    return [m for m in markets if m.market_type not in ambiguous]


def _oldest_fetch(group: MatchGroup) -> datetime | None:
    times = [m.fetched_at for m in group.matches if m.fetched_at]
    return min(times) if times else None


def _oldest_source_updated(group: MatchGroup) -> datetime | None:
    """The oldest feed-provided update time in the group, when any book has one.

    A group with no source timestamps returns None. It must not fall back to
    ``fetched_at``: that would turn "the book never said" into "the book said
    now", which is the failure mode this field exists to separate (N0-2).
    """
    times: list[datetime] = []
    for match in group.matches:
        if match.source_updated_at:
            times.append(match.source_updated_at)
        for market in match.markets:
            if market.source_updated_at:
                times.append(market.source_updated_at)
            for odd in market.odds:
                if odd.source_updated_at:
                    times.append(odd.source_updated_at)
    return min(times) if times else None


def _attach_stake_fetches(surebet: Surebet, group: MatchGroup) -> None:
    """Attach each winning leg's own collection time to its stake.

    A group may list a book more than once, so the earliest fetch wins: that is
    the conservative age for any price the book contributed. A leg whose book
    has no recorded fetch stays `None` rather than borrowing another book's
    timestamp, which would make an unknown-age leg look current.

    The feed's own ``source_updated_at`` is attached the same way and stays
    empty when the book publishes none. It is never copied from ``fetched_at``.
    """
    fetch_by_book: dict[str, datetime] = {}
    source_by_book: dict[str, datetime] = {}
    for match in group.matches:
        if match.fetched_at is not None:
            current = fetch_by_book.get(match.bookmaker)
            if current is None or match.fetched_at < current:
                fetch_by_book[match.bookmaker] = match.fetched_at
        source_times = [
            value
            for value in (
                match.source_updated_at,
                *(market.source_updated_at for market in match.markets),
                *(odd.source_updated_at for market in match.markets for odd in market.odds),
            )
            if value is not None
        ]
        if source_times:
            current_source = source_by_book.get(match.bookmaker)
            oldest = min(source_times)
            if current_source is None or oldest < current_source:
                source_by_book[match.bookmaker] = oldest
    for stake in surebet.stakes:
        stake.fetched_at = fetch_by_book.get(stake.bookmaker)
        stake.source_updated_at = source_by_book.get(stake.bookmaker)


def _settlement_for_market(market: Market) -> str:
    """Settlement is part of a market's identity, not a label detail."""
    return market.settlement or "full_time"


def _dominant_period(markets: list[tuple[str, Market]]) -> str:
    """The period most of a market's listings agree on, for the board key."""
    counts: dict[str, int] = {}
    for _bookmaker, market in markets:
        period = market.period or "full_time"
        counts[period] = counts.get(period, 0) + 1
    if not counts:
        return "full_time"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _record_board(
    metrics: ScanMetrics | None,
    group: MatchGroup,
    market_type: MarketType,
    *,
    line: str,
    period: str,
    settlement: str,
    margin: float,
    profit_percent: float,
    odds_map: dict[str, tuple[str, float]],
) -> None:
    """Append one evaluated board to the scan collector, before display filters."""
    if metrics is None:
        return
    metrics.boards.append(
        BoardObservation(
            event_key=event_identity(group),
            market_type=market_type.value,
            line=line,
            period=period,
            settlement=settlement,
            margin=margin,
            profit_percent=profit_percent,
            bookmakers=tuple(sorted({bookmaker for bookmaker, _ in odds_map.values()})),
        )
    )


def _dominant_settlement(markets: list[tuple[str, Market]]) -> str:
    """The settlement with the most distinct books for one market type.

    A listing that settles a bet differently is not a price for the same bet.
    The engine keeps the settlement the most price sources agree on and drops
    the rest; when two settlements tie, the lexicographically first is chosen
    so the result is deterministic, and the tie is surfaced in the log.
    """
    counts: dict[str, set[str]] = {}
    for bookmaker, market in markets:
        counts.setdefault(_settlement_for_market(market), set()).add(bookmaker)
    if not counts:
        return "full_time"
    ranked = sorted(counts.items(), key=lambda item: (-len(item[1]), item[0]))
    if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
        logger.warning(
            "Tied settlements %s; using %s",
            [name for name, _ in ranked[:2]],
            ranked[0][0],
        )
    return ranked[0][0]


def _plausible_book_quotes(
    bookie_odds: dict[str, dict[str, float]],
    labels: list[str],
    *,
    min_margin: float = 1.0,
    enabled: bool = True,
) -> dict[str, dict[str, float]]:
    """Drop a book whose own complete set is already an arbitrage.

    A licensed book prices a complete market at a margin above 1.0. A book
    whose own two/three legs imply less than 1.0 is showing a stale or
    suspended price, not a gift: pairing it with another book's stale price is
    how a scanner manufactures a false surebet. The leg is dropped, and the
    book can still contribute a partial set if one is needed elsewhere.
    """
    if not enabled:
        return bookie_odds
    kept: dict[str, dict[str, float]] = {}
    for bookmaker, odds in bookie_odds.items():
        if all(label in odds and odds[label] > 1.0 for label in labels):
            margin = sum(1.0 / odds[label] for label in labels)
            if margin < min_margin:
                logger.warning(
                    "[%s] complete %s set implies %.3f (< %.2f); dropped as stale",
                    bookmaker,
                    labels,
                    margin,
                    min_margin,
                )
                continue
        kept[bookmaker] = odds
    return kept


def _consistent_book_quotes(
    bookie_odds: dict[str, dict[str, float]],
    labels: list[str],
    *,
    max_deviation: float = 0.20,
) -> dict[str, dict[str, float]]:
    """Drop a book whose side of a line is far from every peer's price.

    A skewed two-way market can manufacture a surebet from the *other* side:
    book A is far too short on away, book B far too short on home, and taking
    A's home plus B's away looks like a large edge. Each leg is the best price
    on its label, so the per-leg outlier guard never sees the broken side. With
    at least three books a label deviation beyond 20% from the peer median is
    evidence that the book's whole line is stale, so neither side may support
    an edge.
    """
    if len(bookie_odds) < 3:
        return bookie_odds
    kept: dict[str, dict[str, float]] = {}
    for bookmaker, odds in bookie_odds.items():
        if not all(label in odds for label in labels):
            kept[bookmaker] = odds
            continue
        stale = False
        for label in labels:
            # One vote per price source: MDShop and Admiralbet quote the same
            # feed, so two entries must not outweigh two independent books.
            peers_by_source: dict[str, list[float]] = {}
            for other_book, other in bookie_odds.items():
                if other_book == bookmaker or label not in other:
                    continue
                peers_by_source.setdefault(price_source(other_book), []).append(
                    other[label]
                )
            peers = [statistics.median(values) for values in peers_by_source.values()]
            if len(peers) < 2:
                continue
            median = statistics.median(peers)
            if median > 0 and abs(odds[label] - median) / median > max_deviation:
                stale = True
                break
        if stale:
            logger.warning(
                "[%s] line %s price deviates >%.0f%% from the peer median; "
                "dropped as stale",
                bookmaker,
                labels,
                max_deviation * 100,
            )
        else:
            kept[bookmaker] = odds
    return kept


# Required outcome labels for each market type
REQUIRED_LABELS: dict[MarketType, list[str]] = {
    MarketType.MATCH_RESULT: ["1", "X", "2"],
    MarketType.OVER_UNDER_0_5: ["Over 0.5", "Under 0.5"],
    MarketType.OVER_UNDER_1_5: ["Over 1.5", "Under 1.5"],
    MarketType.OVER_UNDER_2_5: ["Over 2.5", "Under 2.5"],
    MarketType.OVER_UNDER_3_5: ["Over 3.5", "Under 3.5"],
    MarketType.OVER_UNDER_4_5: ["Over 4.5", "Under 4.5"],
    MarketType.OVER_UNDER_5_5: ["Over 5.5", "Under 5.5"],
    MarketType.BTTS: ["GG", "NG"],
    MarketType.DOUBLE_CHANCE: [],  # Cross-market arb — handled by _check_cross_market_dc
    MarketType.FIRST_HALF_1X2: ["1", "X", "2"],
    MarketType.MONEYLINE: ["1", "2"],
    MarketType.MONEYLINE_3WAY: ["1", "X", "2"],
    # FIRST_HALF_OU / ASIAN_HANDICAP / HANDICAP / TOTAL: line-embedded labels —
    # handled by _check_line_market (labels carry the line).
}

# Market types whose outcome labels embed the line.
LINE_MARKETS = frozenset(
    {
        MarketType.FIRST_HALF_OU,
        MarketType.ASIAN_HANDICAP,
        MarketType.HANDICAP,
        MarketType.TOTAL,
    }
)

# First-half total-goal lines supported for FIRST_HALF_OU.
FIRST_HALF_OU_LINES = {"0.5", "1.5", "2.5"}

# Cross-market Double Chance partitions of the probability space.
# key = the 1X2 outcome label, value = the complementary DC pair.
DC_CROSS_PAIRS: dict[str, list[str]] = {
    "1": ["1", "X2"],  # home win  OR  draw/away
    "2": ["2", "1X"],  # away win  OR  home/draw
    "X": ["X", "12"],  # draw      OR  any side wins
}


class ArbitrageEngine:
    """Detects surebet (arbitrage) opportunities across bookmaker groups."""

    @staticmethod
    def _is_expired(kickoff: datetime | None, buffer_minutes: int = EXPIRY_BUFFER_MINUTES) -> bool:
        if not kickoff:
            return False
        # Scrapers store naive UTC kickoffs. Compare against UTC, never local time,
        # otherwise matches expire ~2h early on machines outside UTC.
        if kickoff.tzinfo is not None:
            now = datetime.now(UTC)
            return kickoff < (now - timedelta(minutes=buffer_minutes))
        now_utc_naive = datetime.now(UTC).replace(tzinfo=None)
        return kickoff < (now_utc_naive - timedelta(minutes=buffer_minutes))

    @staticmethod
    def _latest_kickoff(group: MatchGroup) -> datetime | None:
        """The last kickoff any book in the group claims, as naive UTC.

        Bookmakers disagree by up to the gate's kickoff window. Using the
        canonical (often earliest) time expired a fixture before the book that
        starts later had kicked off; using the latest member time is the
        conservative prematch choice.
        """
        kickoffs = []
        for match in group.matches:
            if match.kickoff is None:
                continue
            kickoffs.append(
                match.kickoff.astimezone(UTC).replace(tzinfo=None)
                if match.kickoff.tzinfo is not None
                else match.kickoff
            )
        return max(kickoffs) if kickoffs else group.kickoff

    def find_surebets(
        self,
        groups: list[MatchGroup],
        min_profit: float = MIN_PROFIT_PERCENT,
        investment: float = DEFAULT_INVESTMENT,
        allow_past_kickoffs: bool = False,
        enabled_markets: set[str] | None = None,
        mode: str = "prematch",
        metrics: ScanMetrics | None = None,
    ) -> list[Surebet]:
        """
        Scan all match groups for arbitrage opportunities.
        Returns list of Surebet objects sorted by profit_percent descending.

        `allow_past_kickoffs=True` (live mode) keeps in-play groups whose
        kickoff has already passed — in-play odds are still live and valid.

        `enabled_markets` restricts detection to the given market ids (strings).
        When None, all markets defined in REQUIRED_LABELS are checked (used by
        tests and the verify endpoint). The server passes ENABLED_MARKETS plus
        the experimental markets the user toggled on.
        """
        surebets: list[Surebet] = []
        now_utc_naive = datetime.now(UTC).replace(tzinfo=None)
        ttl = LIVE_ODDS_TTL_SECONDS if allow_past_kickoffs else ODDS_TTL_SECONDS
        if metrics is not None:
            metrics.groups_total = len(groups)

        for group in groups:
            # Only a group the certainty gate VERIFIED may be priced. The matcher
            # already returns only those, but "never show a surebet built on two
            # different matches" is this product's central safety property, so it
            # is enforced here too rather than resting on one caller.
            if group.status != "verified":
                if metrics is not None:
                    metrics.groups_unverified += 1
                logger.debug(
                    f"Skipping {group.status} group: {group.canonical_home} vs {group.canonical_away}"
                )
                continue
            if metrics is not None:
                metrics.groups_verified += 1
            # Skip matches whose latest member kickoff has already passed
            # (prematch mode only; live matches are in play right now and
            # remain actionable). The two-minute buffer is clock tolerance, not
            # a window to keep pricing a match that has started.
            latest_kickoff = self._latest_kickoff(group)
            if (
                not allow_past_kickoffs
                and self._is_expired(
                    latest_kickoff, buffer_minutes=PREMATCH_EXPIRY_BUFFER_MINUTES
                )
            ):
                if metrics is not None:
                    metrics.groups_expired += 1
                logger.debug(
                    "Skipping expired match group: %s vs %s (%s)",
                    group.canonical_home,
                    group.canonical_away,
                    latest_kickoff,
                )
                continue
            # P2: reject groups with stale odds (any leg older than TTL)
            def _fetched_age_sec(fetched_at: datetime | None) -> float:
                if not fetched_at:
                    return 0.0
                fa = fetched_at.astimezone(UTC).replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
                return (now_utc_naive - fa).total_seconds()

            if any(_fetched_age_sec(m.fetched_at) > ttl for m in group.matches):
                if metrics is not None:
                    metrics.groups_stale += 1
                logger.debug(f"Skipping stale odds group: {group.canonical_home} vs {group.canonical_away} (age >{ttl}s)")
                continue

            for market_type in MarketType:
                if enabled_markets is not None and market_type.value not in enabled_markets:
                    continue
                if market_type == MarketType.DOUBLE_CHANCE:
                    # Cross-market 1X2 + Double Chance arbitrage
                    result = self._check_cross_market_dc(
                        group, min_profit, investment, metrics=metrics
                    )
                elif market_type in LINE_MARKETS:
                    result = self._check_line_market(
                        group, market_type, min_profit, investment, metrics=metrics
                    )
                else:
                    required = REQUIRED_LABELS.get(market_type, [])
                    if not required:
                        continue  # Skip markets with no defined outcome set
                    result = self._check_market(
                        group, market_type, min_profit, investment, metrics=metrics
                    )

                if result:
                    result.listings = _collect_listings(group)
                    result.evidence = _evidence_summary(group)
                    result.event_key = event_identity(group)
                    result.odds_fetched_at = _oldest_fetch(group)
                    result.odds_source_updated_at = _oldest_source_updated(group)
                    _attach_stake_fetches(result, group)
                    attach_destinations(result, group, mode=mode)
                    surebets.append(result)
                    logger.info(
                        f"🎯 SUREBET: {group.canonical_home} vs {group.canonical_away} | "
                        f"{market_type.value} | {result.profit_percent:.2f}% profit"
                    )

        surebets.sort(key=lambda s: s.profit_percent, reverse=True)
        return surebets

    def _check_market(
        self,
        group: MatchGroup,
        market_type: MarketType,
        min_profit: float,
        investment: float,
        *,
        metrics: ScanMetrics | None = None,
    ) -> Surebet | None:
        """
        Check a specific market type across all bookmakers in a match group.
        Finds the optimal combination of DISTINCT bookmakers (one bookmaker per outcome).
        It is strictly forbidden to place 2 or more bets on the same game with the same bookmaker.
        """
        required_labels = REQUIRED_LABELS.get(market_type, [])
        if not required_labels:
            return None

        n = len(required_labels)

        # Build bookie -> outcome_label -> odds mapping. Markets of one type
        # whose settlement differs are not comparable: keep the settlement the
        # most books agree on.
        typed = [
            (match.bookmaker, market)
            for match in group.matches
            for market in _priced_markets(match)
            if market.market_type == market_type
        ]
        settlement = _dominant_settlement(typed)
        bookie_odds: dict[str, dict[str, float]] = {}
        for match in group.matches:
            bm = match.bookmaker
            for market in _priced_markets(match):
                if market.market_type == market_type:
                    if _settlement_for_market(market) != settlement:
                        continue
                    if bm not in bookie_odds:
                        bookie_odds[bm] = {}
                    for odds_val in market.odds:
                        if odds_val.label in required_labels and odds_val.value > 1.0:
                            bookie_odds[bm][odds_val.label] = max(
                                bookie_odds[bm].get(odds_val.label, 0.0), odds_val.value
                            )

        available_bms = list(bookie_odds.keys())

        # HARD REQUIREMENT: Need at least n distinct bookmakers for an n-way market
        if len(available_bms) < n:
            return None

        if group.sport != "football":
            bookie_odds = _consistent_book_quotes(bookie_odds, required_labels)
        bookie_odds = _plausible_book_quotes(
            bookie_odds, required_labels, enabled=group.sport != "football"
        )
        best = self._best_combination(bookie_odds, required_labels)
        if best is None:
            return None
        best_implied, best_odds_map = best

        profit_percent = (1.0 / best_implied - 1.0) * 100.0
        _record_board(
            metrics,
            group,
            market_type,
            line="",
            period=_dominant_period(typed),
            settlement=settlement,
            margin=best_implied,
            profit_percent=profit_percent,
            odds_map=best_odds_map,
        )

        if group.sport != "football":
            # A book whose own set was dropped as stale does not support the
            # edge. Counting it would let two live books look like three
            # price sources. Football keeps its original count untouched.
            available_books = len({
                price_source(bookmaker)
                for bookmaker, odds in bookie_odds.items()
                if all(label in odds for label in required_labels)
            })
        else:
            available_books = len(
                {
                    match.bookmaker
                    for match in group.matches
                    if any(
                        market.market_type == market_type
                        for market in _priced_markets(match)
                    )
                }
            )
        if _too_good_for_two_sources(profit_percent, best_odds_map, available_books):
            logger.warning(
                "Rejected %.1f%% edge supported by fewer than three price sources "
                "(stale-price guard) — %s vs %s",
                profit_percent,
                group.canonical_home,
                group.canonical_away,
            )
            return None

        # Minimum profit threshold
        if profit_percent < min_profit:
            return None

        # Sanity check: reject unrealistically high profits (scraper errors)
        if profit_percent > MAX_SUREBET_PROFIT_PERCENT:
            logger.warning(
                f"Rejected surebet with {profit_percent:.1f}% profit "
                f"(likely data error) — {group.canonical_home} vs {group.canonical_away}"
            )
            return None

        stakes = self._calculate_stakes(best_odds_map, required_labels, investment, best_implied)

        return Surebet(
            id=str(uuid.uuid4())[:8],
            sport=group.sport,
            home_team=group.canonical_home,
            away_team=group.canonical_away,
            league=group.league,
            kickoff=group.kickoff,
            market_type=market_type,
            profit_percent=round(profit_percent, 2),
            total_margin=round(best_implied, 4),
            raw_margin=best_implied,
            realized=_rounding_block(stakes, investment),
            stakes=stakes,
            match_urls=_collect_match_urls(group),
            bet_urls=_collect_bet_urls(group),
            found_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def _check_line_market(
        self,
        group: MatchGroup,
        market_type: MarketType,
        min_profit: float,
        investment: float,
        max_profit: float = MAX_SUREBET_PROFIT_PERCENT,
        *,
        metrics: ScanMetrics | None = None,
    ) -> Surebet | None:
        """
        Check a line-embedded market (FIRST_HALF_OU, ASIAN_HANDICAP) across all
        bookmakers in a match group. Outcome labels carry the line — "Over 1.5" /
        "Under 1.5" for first-half totals, "1 -0.5" / "2 +0.5" for Asian handicap.

        Labels are grouped into complementary lines; for each line the best
        combination of DISTINCT bookmakers (one per side) is found, and the
        best line wins. Requires the full complementary pair on a line.
        """
        # bookie -> label -> best odds
        typed = [
            (match.bookmaker, market)
            for match in group.matches
            for market in _priced_markets(match)
            if market.market_type == market_type
        ]
        settlement = _dominant_settlement(typed)
        bookie_odds: dict[str, dict[str, float]] = {}
        for match in group.matches:
            bm = match.bookmaker
            for market in _priced_markets(match):
                if market.market_type != market_type:
                    continue
                if _settlement_for_market(market) != settlement:
                    continue
                for ov in market.odds:
                    if ov.value > 1.0:
                        bookie_odds.setdefault(bm, {})
                        bookie_odds[bm][ov.label] = max(bookie_odds[bm].get(ov.label, 0.0), ov.value)

        if len(bookie_odds) < 2:
            return None

        # line key -> {label: best odds across bookies}
        lines: dict[str, dict[str, float]] = {}
        for odds_map in bookie_odds.values():
            for label, odd in odds_map.items():
                line_key = self._line_key(market_type, label)
                if line_key is None:
                    continue
                bucket = lines.setdefault(line_key, {})
                bucket[label] = max(bucket.get(label, 0.0), odd)

        best_overall: (
            tuple[float, dict[str, tuple[str, float]], list[str], int] | None
        ) = None
        for line_key, bucket in lines.items():
            labels = self._line_labels(market_type, line_key)
            if any(lbl not in bucket for lbl in labels):
                continue
            # Restrict the bookie map to this line's two labels
            restricted = {
                bm: {lbl: odd for lbl, odd in odds_map.items() if lbl in labels}
                for bm, odds_map in bookie_odds.items()
            }
            restricted = {bm: om for bm, om in restricted.items() if om}
            if len(restricted) < 2:
                continue
            if group.sport != "football":
                restricted = _consistent_book_quotes(restricted, labels)
            restricted = _plausible_book_quotes(
                restricted, labels, enabled=group.sport != "football"
            )
            best = self._best_combination(restricted, labels)
            if best is None:
                continue
            supporting = len({
                price_source(bookmaker)
                for bookmaker, odds in restricted.items()
                if all(label in odds for label in labels)
            })
            _record_board(
                metrics,
                group,
                market_type,
                line=line_key,
                period=_dominant_period(typed),
                settlement=settlement,
                margin=best[0],
                profit_percent=(1.0 / best[0] - 1.0) * 100.0,
                odds_map=best[1],
            )
            if best_overall is None or best[0] < best_overall[0]:
                best_overall = (best[0], best[1], labels, supporting)

        if best_overall is None:
            return None

        best_implied, best_odds_map, labels, supporting_books = best_overall
        profit_percent = (1.0 / best_implied - 1.0) * 100.0

        if group.sport != "football":
            available_books = supporting_books
        else:
            available_books = len(
                {
                    match.bookmaker
                    for match in group.matches
                    if any(
                        market.market_type == market_type
                        for market in _priced_markets(match)
                    )
                }
            )
        if _too_good_for_two_sources(profit_percent, best_odds_map, available_books):
            logger.warning(
                "Rejected %.1f%% line-market edge supported by fewer than three "
                "price sources (stale-price guard) — %s vs %s",
                profit_percent,
                group.canonical_home,
                group.canonical_away,
            )
            return None

        if profit_percent < min_profit:
            return None
        if profit_percent > max_profit:
            logger.warning(
                f"Rejected line-market surebet with {profit_percent:.1f}% profit "
                f"(likely data error) — {group.canonical_home} vs {group.canonical_away}"
            )
            return None

        stakes = self._calculate_stakes(best_odds_map, labels, investment, best_implied)

        return Surebet(
            id=str(uuid.uuid4())[:8],
            sport=group.sport,
            home_team=group.canonical_home,
            away_team=group.canonical_away,
            league=group.league,
            kickoff=group.kickoff,
            market_type=market_type,
            profit_percent=round(profit_percent, 2),
            total_margin=round(best_implied, 4),
            raw_margin=best_implied,
            realized=_rounding_block(stakes, investment),
            stakes=stakes,
            match_urls=_collect_match_urls(group),
            bet_urls=_collect_bet_urls(group),
            found_at=datetime.now(UTC).replace(tzinfo=None),
        )

    @staticmethod
    def _line_key(market_type: MarketType, label: str) -> str | None:
        """Map a line-embedded label to its complementary-line key."""
        if market_type in (MarketType.FIRST_HALF_OU, MarketType.TOTAL):
            low = label.lower()
            line = ""
            if low.startswith("over "):
                line = label[5:].strip()
            elif low.startswith("under "):
                line = label[6:].strip()
            if market_type == MarketType.FIRST_HALF_OU and line not in FIRST_HALF_OU_LINES:
                return None
            return line or None
        if market_type in (MarketType.ASIAN_HANDICAP, MarketType.HANDICAP):
            parsed = parse_ah_label(label)
            if parsed is None:
                return None
            idx, ah_line = parsed
            # Key by the signed HOME line so the complementary pair shares a key.
            key = f"{ah_line if idx == '1' else -ah_line:g}"
            return "0" if key == "-0" else key
        return None

    @staticmethod
    def _line_labels(market_type: MarketType, line_key: str) -> list[str]:
        """The two complementary labels for a line key."""
        if market_type in (MarketType.FIRST_HALF_OU, MarketType.TOTAL):
            return [f"Over {line_key}", f"Under {line_key}"]
        if market_type in (MarketType.ASIAN_HANDICAP, MarketType.HANDICAP):

            line = float(line_key)
            return [ah_label("1", line), ah_label("2", -line)]
        return []

    @staticmethod
    def _best_combination(
        bookie_odds: dict[str, dict[str, float]],
        labels: list[str],
    ) -> tuple[float, dict[str, tuple[str, float]]] | None:
        """
        Find the combination of DISTINCT bookmakers (one per label) that minimizes
        total implied probability. Returns (total_implied, {label: (bookie, odd)}).
        """
        available_bms = list(bookie_odds.keys())
        n = len(labels)
        if len(available_bms) < n:
            return None

        best_implied = 999.0
        best_odds_map: dict[str, tuple[str, float]] | None = None

        for perm in permutations(available_bms, n):
            # One leg per price source: two books on the same feed are one price.
            if len({price_source(bm) for bm in perm}) < n:
                continue
            valid = True
            total_implied = 0.0
            odds_map: dict[str, tuple[str, float]] = {}

            for idx, label in enumerate(labels):
                bm = perm[idx]
                odd = bookie_odds[bm].get(label)
                if not odd or odd <= 1.0:
                    valid = False
                    break
                total_implied += 1.0 / odd
                odds_map[label] = (bm, odd)

            if valid and total_implied < best_implied:
                best_implied = total_implied
                best_odds_map = odds_map

        if not best_odds_map or best_implied >= 999.0:
            return None
        return best_implied, best_odds_map

    def _check_cross_market_dc(
        self,
        group: MatchGroup,
        min_profit: float,
        investment: float,
        *,
        metrics: ScanMetrics | None = None,
    ) -> Surebet | None:
        """
        Cross-market Double Chance arbitrage: combine a 1X2 outcome with the
        complementary Double Chance outcome across DISTINCT bookmakers, e.g.
        bookie A on "1" (home win) + bookie B on "X2" (draw or away win).
        The three probability-space partitions are: (1, X2), (2, 1X), (X, 12).
        """
        # Merge 1X2 and DC odds per bookmaker
        merged: dict[str, dict[str, float]] = {}
        for match in group.matches:
            bm = match.bookmaker
            for market in _priced_markets(match):
                if market.market_type not in (MarketType.MATCH_RESULT, MarketType.DOUBLE_CHANCE):
                    continue
                for odds_val in market.odds:
                    if odds_val.value <= 1.0:
                        continue
                    merged.setdefault(bm, {}).setdefault(odds_val.label, 0.0)
                    merged[bm][odds_val.label] = max(merged[bm][odds_val.label], odds_val.value)

        best_overall: tuple[float, dict[str, tuple[str, float]], str] | None = None

        for label, pair in DC_CROSS_PAIRS.items():
            best = self._best_combination(merged, pair)
            if best is None:
                continue
            _record_board(
                metrics,
                group,
                MarketType.DOUBLE_CHANCE,
                line=label,
                period="full_time",
                settlement="full_time",
                margin=best[0],
                profit_percent=(1.0 / best[0] - 1.0) * 100.0,
                odds_map=best[1],
            )
            if best_overall is None or best[0] < best_overall[0]:
                best_overall = (best[0], best[1], label)

        if best_overall is None:
            return None

        best_implied, best_odds_map, label = best_overall
        profit_percent = (1.0 / best_implied - 1.0) * 100.0

        available_books = len(
            {
                match.bookmaker
                for match in group.matches
                if any(
                    market.market_type
                    in (MarketType.MATCH_RESULT, MarketType.DOUBLE_CHANCE)
                    for market in _priced_markets(match)
                )
            }
        )
        if _too_good_for_two_sources(profit_percent, best_odds_map, available_books):
            logger.warning(
                "Rejected %.1f%% cross-market edge supported by fewer than three "
                "price sources (stale-price guard) — %s vs %s",
                profit_percent,
                group.canonical_home,
                group.canonical_away,
            )
            return None

        if profit_percent < min_profit:
            return None
        if profit_percent > MAX_SUREBET_PROFIT_PERCENT:
            logger.warning(
                f"Rejected cross-market surebet with {profit_percent:.1f}% profit "
                f"(likely data error) — {group.canonical_home} vs {group.canonical_away}"
            )
            return None

        stakes = self._calculate_stakes(best_odds_map, DC_CROSS_PAIRS[label], investment, best_implied)

        return Surebet(
            id=str(uuid.uuid4())[:8],
            sport=group.sport,
            home_team=group.canonical_home,
            away_team=group.canonical_away,
            league=group.league,
            kickoff=group.kickoff,
            market_type=MarketType.DOUBLE_CHANCE,
            profit_percent=round(profit_percent, 2),
            total_margin=round(best_implied, 4),
            raw_margin=best_implied,
            realized=_rounding_block(stakes, investment),
            stakes=stakes,
            match_urls=_collect_match_urls(group),
            bet_urls=_collect_bet_urls(group),
            found_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def evaluate_market(
        self,
        group: MatchGroup,
        market_type: MarketType,
        labels: list[str] | None = None,
    ) -> dict | None:
        """
        Evaluate the current best combination for a market without profit filtering.
        Used by the live odds verification endpoint. Returns
        {margin, profit_percent, odds: {label: {bookmaker, odds}}} or None.

        `labels` pins the evaluation to one exact outcome set — the one a cached
        surebet was built on, e.g. ["Over 1.5", "Under 1.5"] or ["1", "X2"] — so
        verification answers "is THIS bet still an arbitrage" rather than
        silently switching to a different line or partition. The one-bet-per-
        bookmaker rule still applies. A group the gate has not verified is never
        priced.
        """
        if group.status != "verified":
            return None
        if labels:
            source_types = (
                (MarketType.MATCH_RESULT, MarketType.DOUBLE_CHANCE)
                if market_type == MarketType.DOUBLE_CHANCE
                else (market_type,)
            )
            wanted = set(labels)
            pinned: dict[str, dict[str, float]] = {}
            for match in group.matches:
                for market in _priced_markets(match):
                    if market.market_type not in source_types:
                        continue
                    for ov in market.odds:
                        if ov.label in wanted and ov.value > 1.0:
                            book = pinned.setdefault(match.bookmaker, {})
                            book[ov.label] = max(book.get(ov.label, 0.0), ov.value)
            pinned_best = self._best_combination(
                _plausible_book_quotes(
                    pinned, list(labels), enabled=group.sport != "football"
                ),
                list(labels),
            )
            if pinned_best is None:
                return None
            best_implied, best_odds_map = pinned_best
        elif market_type in LINE_MARKETS:
            line_result = self._check_line_market(
                group, market_type, min_profit=-100.0, investment=DEFAULT_INVESTMENT,
                max_profit=float("inf"),
            )
            if line_result is None:
                return None
            best_odds_map = {s.outcome_label: (s.bookmaker, s.odds) for s in line_result.stakes}
            best_implied = sum(1.0 / odd for _book, odd in best_odds_map.values())
        elif market_type == MarketType.DOUBLE_CHANCE:
            merged: dict[str, dict[str, float]] = {}
            for match in group.matches:
                for market in _priced_markets(match):
                    if market.market_type not in (MarketType.MATCH_RESULT, MarketType.DOUBLE_CHANCE):
                        continue
                    for ov in market.odds:
                        if ov.value <= 1.0:
                            continue
                        merged.setdefault(match.bookmaker, {}).setdefault(ov.label, 0.0)
                        merged[match.bookmaker][ov.label] = max(merged[match.bookmaker][ov.label], ov.value)

            best_overall: tuple[float, dict[str, tuple[str, float]], list[str]] | None = None
            for pair in DC_CROSS_PAIRS.values():
                best = self._best_combination(merged, pair)
                if best is not None and (best_overall is None or best[0] < best_overall[0]):
                    best_overall = (best[0], best[1], pair)
            if best_overall is None:
                return None
            best_implied, best_odds_map, _pair = best_overall
        else:
            required = REQUIRED_LABELS.get(market_type, [])
            if not required:
                return None
            bookie_odds: dict[str, dict[str, float]] = {}
            for match in group.matches:
                for market in _priced_markets(match):
                    if market.market_type != market_type:
                        continue
                    for ov in market.odds:
                        if ov.label in required and ov.value > 1.0:
                            bookie_odds.setdefault(match.bookmaker, {}).setdefault(ov.label, 0.0)
                            bookie_odds[match.bookmaker][ov.label] = max(
                                bookie_odds[match.bookmaker][ov.label], ov.value
                            )
            best = self._best_combination(
                _plausible_book_quotes(
                    bookie_odds, required, enabled=group.sport != "football"
                ),
                required,
            )
            if best is None:
                return None
            best_implied, best_odds_map = best

        profit = (1.0 / best_implied - 1.0) * 100.0
        return {
            "margin": round(best_implied, 4),
            "profit_percent": round(profit, 2),
            "odds": {
                label: {"bookmaker": bm, "odds": odd}
                for label, (bm, odd) in best_odds_map.items()
            },
        }

    def _calculate_stakes(
        self,
        best_odds: dict[str, tuple[str, float]],
        labels: list[str],
        investment: float,
        total_implied: float,
    ) -> list[SurebetStake]:
        """
        Calculate optimal stake distribution using Kelly-like formula.

        Formula: stake_i = investment × (1/odds_i) / Σ(1/odds_j)

        This guarantees equal return from all outcomes = (investment / total_implied).
        """
        stakes = []
        for label in labels:
            bookmaker, odds = best_odds[label]
            implied_prob = 1.0 / odds
            stake = investment * (implied_prob / total_implied)
            potential_return = stake * odds

            stakes.append(SurebetStake(
                bookmaker=bookmaker,
                outcome_label=label,
                odds=odds,
                stake=round(stake, 2),
                potential_return=round(potential_return, 2),
            ))

        return stakes
