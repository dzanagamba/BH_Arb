"""Measure cross-book pairing quality from a saved scan.

The audit answers the question a surebet list cannot: how many offers did the
matcher leave unpaired even though another book listed the same fixture? It
reads the same cache the dashboard serves, so the number is reproducible and
not a hand-picked sample.

    python scripts/pairing_audit.py
    python scripts/pairing_audit.py --cache cache/last_scan.json --check
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine import name_identity  # noqa: E402

MAX_KICKOFF_MINUTES = 15.0
MIN_TEAM_SIMILARITY = 0.80
DEFAULT_MAX_MISS_RATE = 0.02


def _kickoff(match: dict[str, Any]) -> datetime | None:
    raw = match.get("kickoff")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _match_key(match: dict[str, Any]) -> tuple[str, str]:
    bookmaker = str(match.get("bookmaker", ""))
    event_id = str(match.get("event_id") or "")
    if event_id:
        return bookmaker, event_id
    # Older caches have no event id; keep the fallback unique per listing.
    return bookmaker, "|".join(
        str(match.get(field, ""))
        for field in ("home_team", "away_team", "league_normalized", "kickoff")
    )


def _league_related(left: str, right: str) -> bool:
    """Same league, or one name is a country-qualified form of the other."""
    if not left or not right:
        return False
    if left == right:
        return True
    return left.endswith(right) or right.endswith(left)


def _team_score(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Best whole-fixture similarity, direct or home/away swapped."""
    direct = min(
        name_identity.similarity(left.get("home_team", ""), right.get("home_team", "")),
        name_identity.similarity(left.get("away_team", ""), right.get("away_team", "")),
    )
    swapped = min(
        name_identity.similarity(left.get("home_team", ""), right.get("away_team", "")),
        name_identity.similarity(left.get("away_team", ""), right.get("home_team", "")),
    )
    return max(direct, swapped)


def _book_pair(row: dict[str, Any]) -> str:
    """The two books a strict miss sits between, order-independent."""
    return "|".join(
        sorted({str(row.get("bookmaker", "")), str(row.get("other_bookmaker", ""))})
    )


def _spelling_pattern(row: dict[str, Any]) -> str:
    """A stable signature of how the two books spell the same fixture.

    The same fixture missed by the same pair of books produces the same
    pattern across scans, which is what makes a recurring blocker visible. The
    identity normalizer is used so case, accents and org noise do not split one
    pattern into a dozen.
    """

    def side(left: Any, right: Any) -> str:
        return f"{name_identity.normalize(str(left or ''))}~{name_identity.normalize(str(right or ''))}"

    return (
        f"{side(row.get('home_team'), row.get('other_home'))}|"
        f"{side(row.get('away_team'), row.get('other_away'))}"
    )


def _strict_miss_groups(
    rows: list[dict[str, Any]], matches: int
) -> list[dict[str, Any]]:
    """Group repeated misses by book pair, league and spelling pattern.

    Denominators are explicit: ``share`` is over strict misses and
    ``match_share`` over all listings in the scan. A group is a ranking aid, not
    a coverage claim.
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            _book_pair(row),
            str(row.get("league", "")),
            _spelling_pattern(row),
        )
        groups.setdefault(key, []).append(row)
    total = len(rows)
    result: list[dict[str, Any]] = []
    for (book_pair, league, pattern), members in groups.items():
        example = members[0]
        result.append(
            {
                "book_pair": book_pair,
                "bookmakers": book_pair.split("|") if book_pair else [],
                "league": league,
                "pattern": pattern,
                "count": len(members),
                "share": round(len(members) / total, 4) if total else 0.0,
                "match_share": round(len(members) / matches, 4) if matches else 0.0,
                "example": {
                    "home_team": example.get("home_team", ""),
                    "away_team": example.get("away_team", ""),
                    "other_home": example.get("other_home", ""),
                    "other_away": example.get("other_away", ""),
                    "similarity": example.get("similarity", 0.0),
                },
            }
        )
    result.sort(key=lambda row: (-row["count"], row["book_pair"], row["league"], row["pattern"]))
    return result


def audit(cache: dict[str, Any]) -> dict[str, Any]:
    matches = [match for match in cache.get("matches", []) if isinstance(match, dict)]
    groups = [group for group in cache.get("match_groups", []) if isinstance(group, dict)]

    group_of: dict[tuple[str, str], dict[str, Any]] = {}
    group_books: dict[int, set[str]] = {}
    duplicate_book_groups: list[int] = []
    for group in groups:
        members = group.get("bookmakers", [])
        books = [str(member.get("bookmaker", "")) for member in members]
        group_books[id(group)] = set(books)
        if len(set(books)) != len(books):
            duplicate_book_groups.append(int(group.get("group_id", 0)))
        for member in members:
            group_of[(str(member.get("bookmaker", "")), str(member.get("event_id", "")))] = group

    by_kickoff: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        kickoff = _kickoff(match)
        if kickoff is not None:
            by_kickoff[kickoff].append(match)

    ungrouped = [match for match in matches if _match_key(match) not in group_of]
    strict_misses: list[dict[str, Any]] = []
    duplicates = 0
    for match in ungrouped:
        kickoff = _kickoff(match)
        if kickoff is None:
            continue
        best: dict[str, Any] | None = None
        for other_kickoff, candidates in by_kickoff.items():
            if abs((other_kickoff - kickoff).total_seconds()) > MAX_KICKOFF_MINUTES * 60:
                continue
            for other in candidates:
                if other.get("bookmaker") == match.get("bookmaker"):
                    continue
                if not _league_related(
                    str(match.get("league_normalized", "")),
                    str(other.get("league_normalized", "")),
                ):
                    continue
                if _team_score(match, other) < MIN_TEAM_SIMILARITY:
                    continue
                candidate_group = group_of.get(_match_key(other))
                if candidate_group is None:
                    continue
                if match.get("bookmaker") in group_books[id(candidate_group)]:
                    duplicates += 1
                elif best is None:
                    best = {
                        "bookmaker": match.get("bookmaker", ""),
                        "home_team": match.get("home_team", ""),
                        "away_team": match.get("away_team", ""),
                        "league": match.get("league_normalized", ""),
                        "kickoff": str(match.get("kickoff", "")),
                        "other_bookmaker": other.get("bookmaker", ""),
                        "other_home": other.get("home_team", ""),
                        "other_away": other.get("away_team", ""),
                        "other_league": other.get("league_normalized", ""),
                        "similarity": round(_team_score(match, other), 3),
                    }
        if best is not None:
            strict_misses.append(best)

    per_book: dict[str, dict[str, int]] = {}
    grouped_counts = Counter(
        str(member.get("bookmaker", ""))
        for group in groups
        for member in group.get("bookmakers", [])
    )
    for match in matches:
        book = str(match.get("bookmaker", ""))
        entry = per_book.setdefault(book, {"matches": 0, "grouped": 0})
        entry["matches"] += 1
    for book, entry in per_book.items():
        entry["grouped"] = grouped_counts.get(book, 0)

    sizes = Counter(len(group.get("bookmakers", [])) for group in groups)
    miss_rate = round(len(strict_misses) / len(matches), 4) if matches else 0.0
    strict_miss_groups = _strict_miss_groups(strict_misses, len(matches))
    return {
        "scan_time": cache.get("scan_time"),
        "matches": len(matches),
        "groups": len(groups),
        "group_sizes": {str(size): count for size, count in sorted(sizes.items())},
        "per_book": per_book,
        "ungrouped": len(ungrouped),
        "duplicate_listings": duplicates,
        "strict_misses": len(strict_misses),
        "strict_miss_rate": miss_rate,
        "strict_miss_examples": strict_misses[:25],
        "strict_miss_group_count": len(strict_miss_groups),
        "strict_miss_groups": strict_miss_groups[:25],
        "duplicate_book_groups": duplicate_book_groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="cache/last_scan.json")
    parser.add_argument("--max-miss-rate", type=float, default=DEFAULT_MAX_MISS_RATE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    report = audit(cache)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not args.check:
        return 0
    problems = []
    if report["strict_miss_rate"] > args.max_miss_rate:
        problems.append(
            f"strict miss rate {report['strict_miss_rate']:.2%} exceeds {args.max_miss_rate:.2%}"
        )
    if report["duplicate_book_groups"]:
        problems.append(f"{len(report['duplicate_book_groups'])} group(s) repeat a bookmaker")
    if problems:
        print("\nFAIL: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
