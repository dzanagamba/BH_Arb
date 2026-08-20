"""
Generate team mapping proposals from cached scan data.

Lists raw team names that did not hit an exact canonical mapping and
appear frequently, so they can be added to team_mappings.json.

Usage:
  python scripts/generate_team_mappings.py
  python scripts/generate_team_mappings.py --min 5
"""

import json
import pathlib
import collections
import sys
import re

MIN_FREQ = int(sys.argv[sys.argv.index("--min")+1]) if "--min" in sys.argv else 5

cache = pathlib.Path(__file__).parent.parent / "cache" / "last_scan.json"
if not cache.exists():
    print(f"No cache at {cache}")
    sys.exit(1)

# Load normalizer to test mapping
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from engine.normalizer import TeamNormalizer
norm = TeamNormalizer()

data = json.load(open(cache, encoding="utf-8"))
matches = data.get("matches", [])

counter = collections.Counter()
examples = {}
for m in matches:
    for raw in (m.get("home_team"), m.get("away_team")):
        if not raw:
            continue
        # Check if normalized is same as cleaned (fallback) vs canonical
        cleaned = norm._full_clean(raw)
        canonical = norm.normalize_team(raw)
        # If canonical == cleaned, it was fallback (no mapping hit)
        if canonical == cleaned:
            counter[raw] += 1
            examples[raw] = cleaned

print(f"Total team appearances: {sum(counter.values())} across {len(matches)} matches")
print(f"Candidates (fallback, freq >= {MIN_FREQ}): {len([k for k,v in counter.items() if v>=MIN_FREQ])} unique")
for raw, cnt in counter.most_common(30):
    if cnt >= MIN_FREQ:
        print(f"  {cnt:3d}x  {raw!r:35s} -> {examples[raw]!r}")
