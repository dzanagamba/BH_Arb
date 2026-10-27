"""Derive league mappings and team aliases from fixtures the books share.

Two listings from different books that name the SAME two teams (exact raw
spelling, either orientation), kick off within 15 minutes of each other and
carry the same category tags are the same fixture, so their two league names
name the same competition. Once the leagues agree, a fixture whose kickoff,
league and one team match tells us the other team's two spellings are one club.

Nothing here is fuzzy-guessed: every proposal is backed by fixtures, and the
report lists them.

* Leagues. Each league name is a node and each shared fixture an edge. A name
  is *ambiguous* when, inside one other book, it pairs with names of two
  different competitions (Admiralbet's old "Serija A" paired with both
  "ITALY 1" and "BRAZIL 1"); ambiguous names are never mapped. The remaining
  names are joined into components: a component whose already-mapped members
  agree on one canonical id gives that id to its unmapped members, one with no
  mapped member gets a new ``auto_`` id, and one whose members disagree is
  reported as a conflict: its names stay where they are, and its ids are
  proposed as equivalent pairs for ``config/league_equivalences.json``.
* Teams. With leagues resolved, a fixture in the same league and kickoff whose
  one slot matches exactly and whose other slot does not yields an alias pair
  for ``config/team_alias_allowlist.json``. The gate still requires a 90
  similarity on an allowlisted pair, so pairs below that are only reported.
* Betradar ids. Books that carry the Betradar match id (MDShop, Admiralbet,
  SportPlus, WWIN) are paired on it directly: those pairs feed both the league
  components and the team aliases, whatever the books call the teams.

Usage:
    python scripts/derive_mappings.py cache/last_scan.json [more scans ...]
    python scripts/derive_mappings.py scan.json --report out.json
    python scripts/derive_mappings.py scan.json --apply

Inputs are scan caches (``{"matches": [...]}``) or ``{bookmaker: [...]}``
dumps. ``--apply`` writes the proposals into ``config/league_mappings.json``,
``config/league_equivalences.json`` and ``config/team_alias_allowlist.json``;
without it nothing is written.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
from datetime import datetime
from typing import Any

from rapidfuzz import fuzz

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.certainty import CertaintyGate  # noqa: E402
from engine.normalizer import TeamNormalizer, canonicalize_fixture  # noqa: E402

LEAGUE_FILE = REPO_ROOT / "config" / "league_mappings.json"
ALLOWLIST_FILE = REPO_ROOT / "config" / "team_alias_allowlist.json"
EQUIVALENCE_FILE = REPO_ROOT / "config" / "league_equivalences.json"
KICKOFF_WINDOW_MIN = 15
ALIAS_MIN_SIMILARITY = 90  # the gate's own floor for an allowlisted pair

# Side markers: a youth, reserve or women's side is a different club from the
# first team, even when one book drops the marker inside a youth league.
_MARKERS = {
    "youth": re.compile(r"\bu-?\d{2}\b|/\d{2}\b|^ml/|\bmladi\b|\byouth\b|\bjun", re.I),
    "reserve": re.compile(
        r"\bii\b|\[b\]|\(b\)|\bb$|\(a\)|\(am\.?\)|\bam\.?$|rezerv|reserve|\s2$", re.I
    ),
    "women": re.compile(r"\(ž\)|\bž$|\(w\)|\bw$|women|žene", re.I),
}


def side_markers(name: str) -> frozenset[str]:
    return frozenset(kind for kind, pattern in _MARKERS.items() if pattern.search(name.strip()))


raw_key = CertaintyGate._raw_team_key
surface_key = CertaintyGate._surface_team_key


class Listing:
    __slots__ = ("book", "event", "home", "away", "league", "kickoff", "tags", "lkey", "br")

    def __init__(self, raw: dict, normalizer: TeamNormalizer) -> None:
        self.book = str(raw.get("bookmaker", ""))
        self.event = str(raw.get("event_id", ""))
        self.league = str(raw.get("league", "")).strip()
        # Teams and tags in the canonical form the matcher compares, read from
        # the book's own spelling (a cache written since 2026-10-27 stores the
        # canonical name and keeps the book's in *_source).
        fixture = canonicalize_fixture(
            str(raw.get("home_team_source") or raw.get("home_team", "")).strip(),
            str(raw.get("away_team_source") or raw.get("away_team", "")).strip(),
            self.league,
        )
        self.home = fixture.home.strip()
        self.away = fixture.away.strip()
        kickoff = raw.get("kickoff")
        self.kickoff = datetime.fromisoformat(kickoff) if kickoff else None
        self.tags = frozenset(fixture.tags)
        self.lkey = normalizer._league_clean(self.league)
        self.br = str(raw.get("betradar_id") or "")


def load_listings(paths: list[str], normalizer: TeamNormalizer) -> list[Listing]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[Listing] = []
    for path in paths:
        data: Any = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        rows: list[dict] = (
            list(data["matches"]) if "matches" in data
            else [row for book_rows in data.values() for row in book_rows]
        )
        for row in rows:
            listing = Listing(row, normalizer)
            if not (listing.home and listing.away and listing.kickoff):
                continue
            key = (listing.book, listing.event, listing.home, listing.league)
            if key in seen:
                continue
            seen.add(key)
            out.append(listing)
    return out


def _close(a: Listing, b: Listing) -> bool:
    assert a.kickoff and b.kickoff
    return abs((a.kickoff - b.kickoff).total_seconds()) <= KICKOFF_WINDOW_MIN * 60


def exact_fixture_pairs(listings: list[Listing]) -> list[tuple[Listing, Listing]]:
    """Cross-book pairs naming the same two teams at the same kickoff."""
    index: dict[frozenset[str], list[Listing]] = collections.defaultdict(list)
    for listing in listings:
        index[frozenset((raw_key(listing.home), raw_key(listing.away)))].append(listing)
    pairs = []
    for bucket in index.values():
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if a.book != b.book and a.tags == b.tags and _close(a, b):
                    pairs.append((a, b))
    return pairs


def betradar_pairs(listings: list[Listing]) -> list[tuple[Listing, Listing]]:
    """Cross-book pairs that carry the same Betradar match id.

    The id is the feeds' own statement that two listings are one match, so it
    holds whatever the books call the teams. The kickoff must still agree.
    """
    index: dict[str, list[Listing]] = collections.defaultdict(list)
    for listing in listings:
        if listing.br:
            index[listing.br].append(listing)
    pairs = []
    for bucket in index.values():
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if a.book != b.book and _close(a, b):
                    pairs.append((a, b))
    return pairs


def derive_leagues(
    pairs: list[tuple[Listing, Listing]], normalizer: TeamNormalizer
) -> dict[str, Any]:
    generic = normalizer.GENERIC_LEAGUE_RAW
    spelling: dict[str, str] = {}
    edges: collections.Counter[tuple[str, str]] = collections.Counter()
    partners: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    for a, b in pairs:
        if not a.lkey or not b.lkey or a.lkey in generic or b.lkey in generic:
            continue
        spelling.setdefault(a.lkey, a.league)
        spelling.setdefault(b.lkey, b.league)
        partners[a.lkey][b.book].add(b.lkey)
        partners[b.lkey][a.book].add(a.lkey)
        if a.lkey != b.lkey:
            x, y = sorted((a.lkey, b.lkey))
            edges[(x, y)] += 1

    # An existing id is over-merged when one book uses two of its names for
    # fixtures no other book ever puts together: "Brazil 1" and "Brazil 2" were
    # both brazil_serie_a. Such an id's names are re-derived from evidence.
    reverse = dict(normalizer.league_reverse_map)
    degree: collections.Counter[str] = collections.Counter()
    for (x, y), count in edges.items():
        degree[x] += count
        degree[y] += count
    seen_in: dict[str, set[str]] = collections.defaultdict(set)
    for a, b in pairs:
        seen_in[a.book].add(a.lkey)
        seen_in[b.book].add(b.lkey)

    def reach(name: str) -> set[str]:
        return {n for names in partners[name].values() for n in names}

    over_merged: dict[str, list[list[str]]] = {}
    for names in seen_in.values():
        by_id: dict[str, list[str]] = collections.defaultdict(list)
        for name in names:
            if name in reverse and degree[name] >= 2:
                by_id[reverse[name]].append(name)
        for canonical, same in by_id.items():
            for i, x in enumerate(same):
                for y in same[i + 1:]:
                    if not (reach(x) & reach(y)) and y not in reach(x):
                        over_merged.setdefault(canonical, []).append(sorted((x, y)))
    previous = {name: reverse.pop(name) for name in list(reverse)
                if reverse[name] in over_merged}

    def identity(name: str) -> str:
        return reverse.get(name, name)

    ambiguous = {
        name: {book: sorted(names) for book, names in by_book.items()
               if len({identity(n) for n in names}) > 1}
        for name, by_book in partners.items()
        if any(len({identity(n) for n in names}) > 1 for names in by_book.values())
    }

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (x, y), _count in edges.items():
        if x in ambiguous or y in ambiguous:
            continue
        parent[find(x)] = find(y)

    components: dict[str, list[str]] = collections.defaultdict(list)
    for name in list(parent):
        components[find(name)].append(name)

    add: dict[str, list[str]] = collections.defaultdict(list)
    new: dict[str, list[str]] = {}
    remove: dict[str, list[str]] = collections.defaultdict(list)
    conflicts = []
    equivalences: list[list[str]] = []
    taken = set(normalizer.league_mappings)

    def support_of(members: list[str]) -> int:
        return sum(c for (x, y), c in edges.items() if x in members and y in members)

    # Each over-merged id stays with the best-supported component that held one
    # of its names; its names in other components move out.
    keeper: dict[str, int] = {}
    ordered = list(components.values())
    for canonical in over_merged:
        holders = [i for i, members in enumerate(ordered)
                   if any(previous.get(m) == canonical for m in members)]
        if holders:
            keeper[canonical] = max(holders, key=lambda i: support_of(ordered[i]))
    kept_members = {c: set(ordered[i]) for c, i in keeper.items()}
    for name, canonical in previous.items():
        if name in kept_members.get(canonical, set()) or name not in spelling:
            reverse[name] = canonical  # kept, or no evidence either way
        else:
            remove[canonical].append(spelling[name])

    for members in ordered:
        anchors = {reverse[m] for m in members if m in reverse}
        unmapped = sorted(m for m in members if m not in reverse)
        support = sum(c for (x, y), c in edges.items() if x in members and y in members)
        if len(anchors) > 1:
            # Two ids for one competition: shared fixtures join them, and no
            # member is ambiguous (those never reach a component). The names
            # stay where they are; the ids are declared equivalent instead.
            conflicts.append({
                "members": {m: reverse.get(m) for m in sorted(members)},
                "fixtures": support,
            })
            ids = sorted(anchors)
            equivalences.extend(
                [x, y] for i, x in enumerate(ids) for y in ids[i + 1:]
            )
            continue
        if not unmapped:
            continue
        if anchors:
            add[next(iter(anchors))].extend(spelling[m] for m in unmapped)
            continue
        base = max(unmapped, key=lambda m: (bool(re.search(r"[a-z]{3}", m)), len(m)))
        slug = "auto_" + re.sub(r"[^a-z0-9]+", "_", base).strip("_")
        while slug in taken:
            slug += "_x"
        taken.add(slug)
        new[slug] = [spelling[m] for m in unmapped]

    return {
        "add_to_existing": {k: sorted(set(v)) for k, v in sorted(add.items())},
        "remove_from_existing": {k: sorted(set(v)) for k, v in sorted(remove.items()) if v},
        "over_merged": over_merged,
        "new_leagues": dict(sorted(new.items())),
        "ambiguous": {spelling.get(k, k): v for k, v in sorted(ambiguous.items())},
        "conflicts": conflicts,
        "equivalences": equivalences,
    }


def league_resolver(normalizer: TeamNormalizer, leagues: dict[str, Any]):
    mapping = dict(normalizer.league_reverse_map)
    for names in leagues["remove_from_existing"].values():
        for name in names:
            mapping.pop(normalizer._league_clean(name), None)
    for canonical, names in leagues["add_to_existing"].items():
        for name in names:
            mapping[normalizer._league_clean(name)] = canonical
    for canonical, names in leagues["new_leagues"].items():
        for name in names:
            mapping[normalizer._league_clean(name)] = canonical
    ambiguous = {normalizer._league_clean(n) for n in leagues["ambiguous"]}

    def resolve(listing: Listing) -> str | None:
        if listing.lkey in ambiguous or listing.lkey in normalizer.GENERIC_LEAGUE_RAW:
            return None
        return mapping.get(listing.lkey)

    return resolve


def derive_aliases(
    listings: list[Listing], resolve, existing: set[frozenset[str]]
) -> tuple[dict[frozenset[str], dict[str, Any]], dict[frozenset[str], dict[str, Any]]]:
    by_slot: dict[tuple[str, str], list[Listing]] = collections.defaultdict(list)
    for listing in listings:
        league = resolve(listing)
        if league:
            for team in (listing.home, listing.away):
                by_slot[(league, raw_key(team))].append(listing)

    found: dict[frozenset[str], dict[str, Any]] = {}
    low: dict[frozenset[str], dict[str, Any]] = {}
    for (_league, team), bucket in by_slot.items():
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if a.book == b.book or a.tags != b.tags or not _close(a, b):
                    continue
                a_other = a.away if raw_key(a.home) == team else a.home
                b_other = b.away if raw_key(b.home) == team else b.home
                # The fixed team must sit in the same slot, or both sides flip.
                a_home_fixed = raw_key(a.home) == team
                b_home_fixed = raw_key(b.home) == team
                if raw_key(a_other) == raw_key(b_other) or raw_key(a_other) == team:
                    continue
                if "|" in a_other or "|" in b_other:
                    continue
                if side_markers(a_other) != side_markers(b_other):
                    continue
                pair = frozenset((a_other, b_other))
                if frozenset(raw_key(n) for n in pair) in existing:
                    continue
                score = max(
                    fuzz.token_set_ratio(surface_key(a_other), surface_key(b_other)),
                    fuzz.partial_ratio(surface_key(a_other), surface_key(b_other)),
                )
                target = found if score >= ALIAS_MIN_SIMILARITY else low
                entry = target.setdefault(pair, {
                    "alias": "|".join(sorted(pair)), "similarity": round(score),
                    "fixtures": [], "swapped": a_home_fixed != b_home_fixed,
                })
                entry["fixtures"].append(
                    f"{a.book}: {a.home} - {a.away} ({a.league}) | "
                    f"{b.book}: {b.home} - {b.away} ({b.league}) @ {a.kickoff:%Y-%m-%d %H:%M}"
                )
    return found, low


def derive_aliases_from_ids(
    pairs: list[tuple[Listing, Listing]],
    existing: set[frozenset[str]],
    found: dict[frozenset[str], dict[str, Any]],
    low: dict[frozenset[str], dict[str, Any]],
) -> None:
    """Both team slots of a Betradar-matched pair name the same two clubs.

    Not when the two books put the fixture in different categories (MDShop's
    "Gent U23" is WWIN's "Gent/21"): the gate refuses such a pair whatever the
    allowlist says, so an alias would only record a disagreement as a fact.
    """
    for a, b in pairs:
        if a.tags != b.tags:
            continue
        swapped = (
            raw_key(a.home) in (raw_key(b.away),) or raw_key(a.away) in (raw_key(b.home),)
        ) and not (raw_key(a.home) == raw_key(b.home) or raw_key(a.away) == raw_key(b.away))
        slots = [(a.home, b.away), (a.away, b.home)] if swapped else [
            (a.home, b.home), (a.away, b.away)
        ]
        for x, y in slots:
            if raw_key(x) == raw_key(y) or "|" in x or "|" in y:
                continue
            if side_markers(x) != side_markers(y):
                continue
            pair = frozenset((x, y))
            if frozenset(raw_key(n) for n in pair) in existing:
                continue
            score = max(
                fuzz.token_set_ratio(surface_key(x), surface_key(y)),
                fuzz.partial_ratio(surface_key(x), surface_key(y)),
            )
            target = found if score >= ALIAS_MIN_SIMILARITY else low
            entry = target.setdefault(pair, {
                "alias": "|".join(sorted(pair)), "similarity": round(score),
                "fixtures": [], "swapped": swapped,
            })
            entry["fixtures"].append(
                f"betradar {a.br}: {a.book}: {a.home} - {a.away} | {b.book}: {b.home} - {b.away}"
            )


def alias_report(found, low) -> dict[str, Any]:
    return {
        "aliases": sorted(found.values(), key=lambda e: e["alias"]),
        "below_gate_similarity": sorted(low.values(), key=lambda e: e["similarity"]),
    }


def apply(leagues: dict[str, Any], aliases: dict[str, Any]) -> None:
    data = json.loads(LEAGUE_FILE.read_text(encoding="utf-8"))
    cleaner = TeamNormalizer()
    for canonical, names in leagues["remove_from_existing"].items():
        gone = {cleaner._league_clean(n) for n in names}
        data[canonical] = [n for n in data.get(canonical, []) if cleaner._league_clean(n) not in gone]
    for canonical, names in leagues["add_to_existing"].items():
        current = data.setdefault(canonical, [])
        current.extend(n for n in names if n not in current)
    for canonical, names in leagues["new_leagues"].items():
        data[canonical] = names
    LEAGUE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")

    equivalences = json.loads(EQUIVALENCE_FILE.read_text(encoding="utf-8"))
    pairs = [list(p) for p in equivalences.get("pairs", [])]
    known = {frozenset(p) for p in pairs}
    for pair in leagues.get("equivalences", []):
        if frozenset(pair) not in known:
            pairs.append(list(pair))
            known.add(frozenset(pair))
    equivalences["pairs"] = pairs
    EQUIVALENCE_FILE.write_text(
        json.dumps(equivalences, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    allow = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))
    entries = set(allow.get("aliases", []))
    entries.update(entry["alias"] for entry in aliases["aliases"])
    allow["aliases"] = sorted(entries)
    ALLOWLIST_FILE.write_text(json.dumps(allow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--report", help="write the full proposal report to this JSON file")
    parser.add_argument("--apply", action="store_true", help="write proposals into config/")
    args = parser.parse_args()

    normalizer = TeamNormalizer()
    listings = load_listings(args.inputs, normalizer)
    pairs = exact_fixture_pairs(listings)
    id_pairs = betradar_pairs(listings)
    seen = {frozenset((id(a), id(b))) for a, b in pairs}
    league_pairs = pairs + [
        (a, b) for a, b in id_pairs if frozenset((id(a), id(b))) not in seen and a.tags == b.tags
    ]
    leagues = derive_leagues(league_pairs, normalizer)
    allow = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8")).get("aliases", [])
    existing = {frozenset(raw_key(p) for p in a.split("|")) for a in allow}
    found, low = derive_aliases(listings, league_resolver(normalizer, leagues), existing)
    derive_aliases_from_ids(id_pairs, existing, found, low)
    aliases = alias_report(found, low)

    print(f"{len(listings)} listings, {len(pairs)} exact cross-book fixtures, "
          f"{len(id_pairs)} Betradar-id pairs")
    print(f"leagues: {sum(len(v) for v in leagues['add_to_existing'].values())} names onto "
          f"{len(leagues['add_to_existing'])} existing ids, {len(leagues['new_leagues'])} new ids, "
          f"{len(leagues['ambiguous'])} ambiguous names, {len(leagues['conflicts'])} conflicts "
          f"({len(leagues['equivalences'])} equivalence pairs)")
    print(f"teams: {len(aliases['aliases'])} aliases, "
          f"{len(aliases['below_gate_similarity'])} pairs below the gate's similarity floor")
    if args.report:
        pathlib.Path(args.report).write_text(
            json.dumps({"leagues": leagues, "teams": aliases}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.apply:
        apply(leagues, aliases)
        print("written to config/league_mappings.json and config/team_alias_allowlist.json")


if __name__ == "__main__":
    main()
