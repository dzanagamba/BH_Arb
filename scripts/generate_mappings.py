"""
Generate league mapping proposals from cached scan data.

Reads cache/last_scan.json (or last_live_scan.json) and lists raw league
names that fell back to generic/cleaned lowercase (i.e. not in league_mappings.json).

Usage:
  python scripts/generate_mappings.py
  python scripts/generate_mappings.py --live
"""

import collections
import json
import pathlib
import sys

CACHE_FILE = pathlib.Path(__file__).parent.parent / "cache" / "last_scan.json"
GENERIC_LEAGUES = {
    "football", "fudbal", "soccer", "unknown_league", "", "2.liga", "3.liga",
    "kup", "klubovi", "1.liga",
}

def main():
    live = "--live" in sys.argv
    cache = pathlib.Path(__file__).parent.parent / "cache" / ("last_live_scan.json" if live else "last_scan.json")
    if not cache.exists():
        print(f"No cache at {cache}")
        sys.exit(1)
    data = json.load(open(cache, encoding="utf-8"))
    matches = data.get("matches", [])

    # Load existing normalized mapping keys for reference
    league_map_path = pathlib.Path(__file__).parent.parent / "config" / "league_mappings.json"
    existing = set()
    if league_map_path.exists():
        j = json.load(open(league_map_path, encoding="utf-8"))
        for v in j.values():
            if isinstance(v, list):
                for name in v:
                    existing.add(name.lower().strip())
        # also add canonical ids
        existing.update(k.lower() for k in j.keys())

    counter = collections.Counter()
    examples = {}
    for m in matches:
        raw = (m.get("league") or "").strip()
        norm = (m.get("league_normalized") or "").strip()
        # generic fallback = norm is lowercase raw or in GENERIC_LEAGUES
        if norm in GENERIC_LEAGUES or norm == raw.lower():
            if raw and raw.lower() not in existing:
                counter[raw] += 1
                examples.setdefault(raw, norm)

    print(f"Total matches: {len(matches)}")
    print(f"Candidates (generic fallback, not in mapping): {len(counter)} unique")
    print("Top 20 by frequency:")
    for league, cnt in counter.most_common(20):
        print(f"  {cnt:4d}x  {league!r:40s} -> {examples[league]!r}")

    # Propose JSON snippet for the most frequent (>3)
    proposals = {k: [k] for k, cnt in counter.items() if cnt >= 5}
    if proposals:
        print("\n--- Proposed snippet for config/league_mappings.json (freq >=5) ---")
        print(json.dumps(proposals, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    main()
