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
import uuid
from datetime import UTC, datetime, timedelta
from itertools import permutations

from config.settings import (
    DEFAULT_INVESTMENT,
    EXPIRY_BUFFER_MINUTES,
    MATCH_URL_TEMPLATES,
    MAX_SUREBET_PROFIT_PERCENT,
    MIN_PROFIT_PERCENT,
    ODDS_TTL_SECONDS,
)
from models.schemas import MarketType, MatchGroup, Surebet, SurebetStake
from scrapers.common import parse_ah_label

logger = logging.getLogger(__name__)


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


# Required outcome labels for each market type
REQUIRED_LABELS: dict[MarketType, list[str]] = {
    MarketType.MATCH_RESULT: ["1", "X", "2"],
    MarketType.OVER_UNDER_1_5: ["Over 1.5", "Under 1.5"],
    MarketType.OVER_UNDER_2_5: ["Over 2.5", "Under 2.5"],
    MarketType.OVER_UNDER_3_5: ["Over 3.5", "Under 3.5"],
    MarketType.BTTS: ["GG", "NG"],
    MarketType.DOUBLE_CHANCE: [],  # Cross-market arb — handled by _check_cross_market_dc
    MarketType.FIRST_HALF_1X2: ["1", "X", "2"],
    # FIRST_HALF_OU / ASIAN_HANDICAP: line-embedded labels — handled by
    # _check_line_market (labels carry the line: "Over 1.5" / "1 -0.5").
}

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

    def find_surebets(
        self,
        groups: list[MatchGroup],
        min_profit: float = MIN_PROFIT_PERCENT,
        investment: float = DEFAULT_INVESTMENT,
        allow_past_kickoffs: bool = False,
        enabled_markets: set[str] | None = None,
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
        ttl = 60 if allow_past_kickoffs else ODDS_TTL_SECONDS  # live tight, prematch looser

        for group in groups:
            # Only a group the certainty gate VERIFIED may be priced. The matcher
            # already returns only those, but "never show a surebet built on two
            # different matches" is this product's central safety property, so it
            # is enforced here too rather than resting on one caller.
            if group.status != "verified":
                logger.debug(
                    f"Skipping {group.status} group: {group.canonical_home} vs {group.canonical_away}"
                )
                continue
            # Skip matches whose kickoff has already passed (prematch mode only;
            # live matches are in play right now and remain actionable)
            if not allow_past_kickoffs and self._is_expired(group.kickoff):
                logger.debug(f"Skipping expired match group: {group.canonical_home} vs {group.canonical_away} ({group.kickoff})")
                continue
            # P2: reject groups with stale odds (any leg older than TTL)
            def _fetched_age_sec(fetched_at: datetime | None) -> float:
                if not fetched_at:
                    return 0.0
                fa = fetched_at.astimezone(UTC).replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
                return (now_utc_naive - fa).total_seconds()

            if any(_fetched_age_sec(m.fetched_at) > ttl for m in group.matches):
                logger.debug(f"Skipping stale odds group: {group.canonical_home} vs {group.canonical_away} (age >{ttl}s)")
                continue

            for market_type in MarketType:
                if enabled_markets is not None and market_type.value not in enabled_markets:
                    continue
                if market_type == MarketType.DOUBLE_CHANCE:
                    # Cross-market 1X2 + Double Chance arbitrage
                    result = self._check_cross_market_dc(group, min_profit, investment)
                elif market_type in (MarketType.FIRST_HALF_OU, MarketType.ASIAN_HANDICAP):
                    result = self._check_line_market(group, market_type, min_profit, investment)
                else:
                    required = REQUIRED_LABELS.get(market_type, [])
                    if not required:
                        continue  # Skip markets with no defined outcome set
                    result = self._check_market(group, market_type, min_profit, investment)

                if result:
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

        # Build bookie -> outcome_label -> odds mapping
        bookie_odds: dict[str, dict[str, float]] = {}
        for match in group.matches:
            bm = match.bookmaker
            for market in match.markets:
                if market.market_type == market_type:
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

        best = self._best_combination(bookie_odds, required_labels)
        if best is None:
            return None
        best_implied, best_odds_map = best

        profit_percent = (1.0 / best_implied - 1.0) * 100.0

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
            home_team=group.canonical_home,
            away_team=group.canonical_away,
            league=group.league,
            kickoff=group.kickoff,
            market_type=market_type,
            profit_percent=round(profit_percent, 2),
            total_margin=round(best_implied, 4),
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
        bookie_odds: dict[str, dict[str, float]] = {}
        for match in group.matches:
            bm = match.bookmaker
            for market in match.markets:
                if market.market_type != market_type:
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

        best_overall: tuple[float, dict[str, tuple[str, float]], list[str]] | None = None
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
            best = self._best_combination(restricted, labels)
            if best is None:
                continue
            if best_overall is None or best[0] < best_overall[0]:
                best_overall = (best[0], best[1], labels)

        if best_overall is None:
            return None

        best_implied, best_odds_map, labels = best_overall
        profit_percent = (1.0 / best_implied - 1.0) * 100.0

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
            home_team=group.canonical_home,
            away_team=group.canonical_away,
            league=group.league,
            kickoff=group.kickoff,
            market_type=market_type,
            profit_percent=round(profit_percent, 2),
            total_margin=round(best_implied, 4),
            stakes=stakes,
            match_urls=_collect_match_urls(group),
            bet_urls=_collect_bet_urls(group),
            found_at=datetime.now(UTC).replace(tzinfo=None),
        )

    @staticmethod
    def _line_key(market_type: MarketType, label: str) -> str | None:
        """Map a line-embedded label to its complementary-line key."""
        if market_type == MarketType.FIRST_HALF_OU:
            low = label.lower()
            if low.startswith("over "):
                line = label[5:].strip()
                return line if line in FIRST_HALF_OU_LINES else None
            if low.startswith("under "):
                line = label[6:].strip()
                return line if line in FIRST_HALF_OU_LINES else None
            return None
        if market_type == MarketType.ASIAN_HANDICAP:
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
        if market_type == MarketType.FIRST_HALF_OU:
            return [f"Over {line_key}", f"Under {line_key}"]
        if market_type == MarketType.ASIAN_HANDICAP:
            from scrapers.common import ah_label

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
            for market in match.markets:
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
            if best_overall is None or best[0] < best_overall[0]:
                best_overall = (best[0], best[1], label)

        if best_overall is None:
            return None

        best_implied, best_odds_map, label = best_overall
        profit_percent = (1.0 / best_implied - 1.0) * 100.0

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
            home_team=group.canonical_home,
            away_team=group.canonical_away,
            league=group.league,
            kickoff=group.kickoff,
            market_type=MarketType.DOUBLE_CHANCE,
            profit_percent=round(profit_percent, 2),
            total_margin=round(best_implied, 4),
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
                for market in match.markets:
                    if market.market_type not in source_types:
                        continue
                    for ov in market.odds:
                        if ov.label in wanted and ov.value > 1.0:
                            book = pinned.setdefault(match.bookmaker, {})
                            book[ov.label] = max(book.get(ov.label, 0.0), ov.value)
            pinned_best = self._best_combination(pinned, list(labels))
            if pinned_best is None:
                return None
            best_implied, best_odds_map = pinned_best
        elif market_type in (MarketType.FIRST_HALF_OU, MarketType.ASIAN_HANDICAP):
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
                for market in match.markets:
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
                for market in match.markets:
                    if market.market_type != market_type:
                        continue
                    for ov in market.odds:
                        if ov.label in required and ov.value > 1.0:
                            bookie_odds.setdefault(match.bookmaker, {}).setdefault(ov.label, 0.0)
                            bookie_odds[match.bookmaker][ov.label] = max(
                                bookie_odds[match.bookmaker][ov.label], ov.value
                            )
            best = self._best_combination(bookie_odds, required)
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
