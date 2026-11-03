"""Audit the league labels that block otherwise-identical match pairs.

Reads the real cached scan feed (``cache/last_scan.json``), reproduces the
candidate-pair discovery that ``server/api._collect_candidates`` performs, and
reports every pair whose two sides carry *different* normalized league labels.

No network, no Playwright: the cache file is the whole input.

Usage:
    python scripts/audit_league_pairs.py
    python scripts/audit_league_pairs.py --min-count 1
    python scripts/audit_league_pairs.py --json out.json

The output is the reproducible basis for every decision in
``config/league_mappings.json`` and ``config/league_equivalences.json``: a pair
listed here is a pair the league gate is currently refusing to let through.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.certainty import CertaintyGate  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Match  # noqa: E402
from server.api import (  # noqa: E402
    CANDIDATE_KICKOFF_WINDOW_MIN,
    CANDIDATE_TEAM_SIM_MIN,
    _canonical_pair_key,
    _kickoff_bucket,
    _team_similarity,
    _TeamTokens,
)

CACHE_FILE = REPO_ROOT / "cache" / "last_scan.json"


def load_matches(path: pathlib.Path) -> list[Match]:
    """Load cached matches as schema objects with no inherited normalization.

    ``cache/last_scan.json`` stores whatever ``league_normalized`` the previous
    scan produced. Leaving it in place would measure the old mapping file, so
    every derived field is cleared and re-derived from the config on disk —
    which is exactly what a fresh scrape does.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    derived = (
        "league_normalized",
        "country_normalized",
        "home_team_normalized",
        "away_team_normalized",
        "category_tags",
    )
    matches = []
    for raw in data.get("matches", []):
        clean = {key: value for key, value in raw.items() if key not in derived}
        matches.append(Match(**clean))
    return matches


def candidate_pairs(matches: list[Match]) -> list[tuple[Match, Match]]:
    """Pairs the candidate sweep would consider, on canonical teams + kickoff.

    The bucket walk, the prefilter and its threshold are the product's own
    functions, imported rather than reimplemented, so the pair set this script
    reports is the pair set ``server/api._collect_candidates`` builds.
    """
    buckets: dict[int, list[Match]] = {}
    for match in matches:
        bucket = _kickoff_bucket(match)
        if bucket is not None:
            buckets.setdefault(bucket, []).append(match)

    pairs: list[tuple[Match, Match]] = []
    seen: set[str] = set()
    for index in sorted(buckets):
        here = [(m, _TeamTokens.of(m)) for m in buckets[index]]
        following = [(m, _TeamTokens.of(m)) for m in buckets.get(index + 1, [])]
        for position, (left, left_teams) in enumerate(here):
            for right, right_teams in here[position + 1:] + following:
                if left.bookmaker == right.bookmaker:
                    continue
                if _team_similarity(left_teams, right_teams) < CANDIDATE_TEAM_SIM_MIN:
                    continue
                pair_key = _canonical_pair_key(left, right)
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                if (
                    left.home_team_normalized
                    and left.home_team_normalized == right.home_team_normalized
                    and left.away_team_normalized
                    and left.away_team_normalized == right.away_team_normalized
                ):
                    pairs.append((left, right))
    return pairs


def measure_outcome(matches: list[Match]) -> tuple[int, int, int]:
    """Return ``(verified groups, groups with 2+ books, priced surebets)``.

    The pair counts above say how many claims stopped being refused. This says
    how many of them became a group a surebet can be priced from, which is the
    only number that matters.
    """
    from config.settings import (
        DEFAULT_INVESTMENT,
        DUST_PROFIT_PERCENT,
        ENABLED_MARKETS,
    )
    from engine.arbitrage import ArbitrageEngine

    groups = MatchMatcher().group_matches(list(matches))
    surebets = ArbitrageEngine().find_surebets(
        groups,
        min_profit=DUST_PROFIT_PERCENT,
        investment=DEFAULT_INVESTMENT,
        allow_past_kickoffs=False,
        enabled_markets=set(ENABLED_MARKETS),
    )
    return len(groups), sum(1 for g in groups if g.matches), len(surebets)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=pathlib.Path, default=CACHE_FILE)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    parser.add_argument(
        "--outcome",
        action="store_true",
        help="also run the matcher and the arbitrage engine over the feed",
    )
    args = parser.parse_args()

    if not args.cache.exists():
        print(f"No cache at {args.cache}")
        return 1

    matches = load_matches(args.cache)
    matcher = MatchMatcher()
    gate = CertaintyGate(
        kickoff_window_minutes=CANDIDATE_KICKOFF_WINDOW_MIN,
        league_equivalences=matcher._equivalences,
    )
    gate.normalize(matches)

    pairs = candidate_pairs(matches)
    verified = [p for p in pairs if gate.evaluate_pair(*p).status == "verified"]
    blocked = [p for p in pairs if gate.evaluate_pair(*p).status != "verified"]

    reason_counts: collections.Counter[str] = collections.Counter()
    for left, right in blocked:
        reason_counts.update(gate.evaluate_pair(left, right).reasons)

    # The pair of normalized league labels, keyed unordered so the report is
    # stable regardless of which side the sweep reached first.
    league_pairs: collections.Counter[tuple[str, str]] = collections.Counter()
    raw_by_pair: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for left, right in blocked:
        pair_result = gate.evaluate_pair(left, right)
        if "league_mismatch" not in pair_result.reasons:
            continue
        key: tuple[str, str] = tuple(sorted((left.league_normalized, right.league_normalized)))  # type: ignore[assignment]
        league_pairs[key] += 1
        raw_by_pair[key][f"{left.league} | {right.league}"] += 1

    print(f"matches in feed:        {len(matches)}")
    print(f"identical-team pairs:   {len(pairs)}")
    print(f"  gate verified:        {len(verified)}")
    print(f"  gate blocked:         {len(blocked)}")
    print("blocked pair reasons (a pair can carry several):")
    for reason, count in reason_counts.most_common():
        print(f"  {count:5d}  {reason}")

    league_blocked = sum(league_pairs.values())
    print()
    print(f"blocked by league_mismatch:        {league_blocked}")
    print(f"distinct mismatching league pairs: {len(league_pairs)}")

    rows: list[dict[str, object]] = []
    for (left_league, right_league), count in league_pairs.most_common():
        if count < args.min_count:
            continue
        rows.append(
            {
                "a": left_league,
                "b": right_league,
                "count": count,
                "raw_forms": dict(raw_by_pair[(left_league, right_league)].most_common()),
            }
        )

    width_a = max((len(str(row["a"])) for row in rows), default=0)
    width_b = max((len(str(row["b"])) for row in rows), default=0)
    print()
    print("count  canonical-a" + " " * (width_a - 11) + "canonical-b")
    for row in rows:
        print(f"{row['count']:5d}  {row['a']:<{width_a}}  {row['b']:<{width_b}}")

    if args.outcome:
        verified_groups, populated, surebets = measure_outcome(load_matches(args.cache))
        print()
        print(f"verified match groups:            {verified_groups}")
        print(f"  of which carry >=1 fixture:    {populated}")
        print(f"surebets priced from them:       {surebets}")

    if args.json:
        args.json.write_text(
            json.dumps({"rows": rows, "totals": {
                "matches": len(matches),
                "pairs": len(pairs),
                "verified": len(verified),
                "blocked": len(blocked),
                "league_mismatch_pairs": league_blocked,
                "distinct_league_pairs": len(league_pairs),
            }}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
