"""Measure non-football name identity on the live feeds.

The audit answers two questions separately:

* when two books carry the same provider id, are their listings in one verified
  group? (a missed provider pair is a matching bug)
* when two books spell both sides identically and kick off within the verified
  window, are they in one group? (a miss is a name-normalisation bug)

It also counts a group that holds two different non-empty provider ids, which is
a false merge. The output is dated evidence, not a gate: the certainty gate
remains the only authority.

    python scripts/audit_nonfootball_matching.py \
        --out docs/evidence/2026-11-04-team-matching-audit.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import VERIFIED_KICKOFF_WINDOW_MINUTES  # noqa: E402
from engine import name_identity, sports  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Match  # noqa: E402
from scrapers.maxbet import MaxBetScraper  # noqa: E402
from scrapers.mbet import MBetScraper  # noqa: E402
from scrapers.mdshop import MDShopScraper  # noqa: E402
from scrapers.sportplus import SportPlusScraper  # noqa: E402

BOOKS = (
    ("sportplus", SportPlusScraper),
    ("mbet", MBetScraper),
    ("mdshop", MDShopScraper),
    ("maxbet", MaxBetScraper),
)
SPORTS = (sports.BASKETBALL, sports.TENNIS)


def _key(match: Match) -> tuple[str, str]:
    return (
        name_identity.normalize(match.home_team),
        name_identity.normalize(match.away_team),
    )


def _swapped(match: Match) -> tuple[str, str]:
    home, away = _key(match)
    return away, home


def _identity(match: Match) -> tuple[str, str]:
    """Stable member key; a swapped copy keeps its event id."""
    return (match.bookmaker, match.event_id or f"{match.home_team}|{match.away_team}")


def _delta_minutes(left: Match, right: Match) -> float | None:
    if not left.kickoff or not right.kickoff:
        return None
    return abs((left.kickoff - right.kickoff).total_seconds()) / 60.0


def _pair_groups(matches: list[Match], groups: list) -> dict[tuple[str, str], int]:
    where: dict[tuple[str, str], int] = {}
    for index, group in enumerate(groups):
        for member in group.matches:
            where[_identity(member)] = index
    return where


def _provider_audit(
    matches: list[Match], groups: list
) -> dict[str, Any]:
    where = _pair_groups(matches, groups)
    by_id: dict[str, list[Match]] = collections.defaultdict(list)
    for match in matches:
        if match.betradar_id:
            by_id[match.betradar_id].append(match)

    paired = 0
    missed: list[dict[str, Any]] = []
    for provider_id, rows in by_id.items():
        by_book: dict[str, list[Match]] = collections.defaultdict(list)
        for row in rows:
            by_book[row.bookmaker].append(row)
        books = sorted(by_book)
        for left_index, left_book in enumerate(books):
            for right_book in books[left_index + 1:]:
                for left in by_book[left_book]:
                    for right in by_book[right_book]:
                        left_group = where.get(_identity(left))
                        right_group = where.get(_identity(right))
                        if left_group is not None and left_group == right_group:
                            paired += 1
                        else:
                            missed.append({
                                "provider_id": provider_id,
                                "left": {
                                    "bookmaker": left.bookmaker,
                                    "home": left.home_team,
                                    "away": left.away_team,
                                    "league": left.league,
                                    "kickoff": left.kickoff.isoformat() if left.kickoff else None,
                                },
                                "right": {
                                    "bookmaker": right.bookmaker,
                                    "home": right.home_team,
                                    "away": right.away_team,
                                    "league": right.league,
                                    "kickoff": right.kickoff.isoformat() if right.kickoff else None,
                                },
                            })

    false_merges: list[dict[str, Any]] = []
    for group in groups:
        ids = {member.betradar_id for member in group.matches if member.betradar_id}
        if len(ids) > 1:
            false_merges.append({
                "provider_ids": sorted(ids),
                "members": [
                    {
                        "bookmaker": member.bookmaker,
                        "home": member.home_team,
                        "away": member.away_team,
                    }
                    for member in group.matches
                ],
            })

    return {
        "provider_ids": len(by_id),
        "provider_pairs": paired + len(missed),
        "provider_pairs_paired": paired,
        "provider_pairs_missed": missed,
        "false_merges": false_merges,
    }


def _exact_name_audit(matches: list[Match], groups: list) -> dict[str, Any]:
    where = _pair_groups(matches, groups)
    checked = 0
    paired = 0
    missed: list[dict[str, Any]] = []
    clock_gap = 0
    seen: set[tuple[int, int]] = set()
    for left in matches:
        for right in matches:
            if left is right or left.bookmaker == right.bookmaker:
                continue
            pair_key = (min(id(left), id(right)), max(id(left), id(right)))
            if pair_key in seen:
                continue
            if not (_key(left) == _key(right) or _key(left) == _swapped(right)):
                continue
            seen.add(pair_key)
            delta = _delta_minutes(left, right)
            if delta is not None and delta > VERIFIED_KICKOFF_WINDOW_MINUTES:
                clock_gap += 1
                continue
            checked += 1
            left_group = where.get(_identity(left))
            right_group = where.get(_identity(right))
            if left_group is not None and left_group == right_group:
                paired += 1
            else:
                missed.append({
                    "left": {
                        "bookmaker": left.bookmaker,
                        "home": left.home_team,
                        "away": left.away_team,
                        "league": left.league,
                        "kickoff": left.kickoff.isoformat() if left.kickoff else None,
                    },
                    "right": {
                        "bookmaker": right.bookmaker,
                        "home": right.home_team,
                        "away": right.away_team,
                        "league": right.league,
                        "kickoff": right.kickoff.isoformat() if right.kickoff else None,
                    },
                })
    return {
        "exact_name_pairs_in_window": checked,
        "exact_name_pairs_paired": paired,
        "exact_name_pairs_missed": missed,
        "exact_name_pairs_outside_verified_window": clock_gap,
    }


async def run() -> dict[str, Any]:
    matches: list[Match] = []
    per_book: dict[str, int] = {}
    for name, scraper in BOOKS:
        rows = await scraper().scrape(live=False, sports_wanted=list(SPORTS))
        rows = [row for row in rows if row.sport in SPORTS]
        matches.extend(rows)
        per_book[name] = len(rows)

    groups = MatchMatcher().group_matches(matches)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "books": list(per_book),
        "matches_per_book": per_book,
        "sports": {},
    }
    for sport in SPORTS:
        sport_matches = [match for match in matches if match.sport == sport]
        sport_groups = [group for group in groups if group.sport == sport]
        if any(
            member.sport != sport
            for group in sport_groups
            for member in group.matches
        ):
            raise AssertionError("a group crossed the sport boundary")
        report["sports"][sport] = {
            "matches": len(sport_matches),
            "groups": len(sport_groups),
            **_provider_audit(sport_matches, sport_groups),
            **_exact_name_audit(sport_matches, sport_groups),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args(argv)
    report = asyncio.run(run())
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(text)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
