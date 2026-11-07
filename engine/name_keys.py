"""The shared raw team-name key used by identity, evidence and diagnostics.

The key intentionally folds only superficial spelling differences: unicode
compatibility forms, case, a few letters NFKD does not decompose, punctuation
and spacing. It never applies fuzzy matching, so two different raw spellings
still need an explicit alias or ledger claim unless this key makes them equal.
"""

from __future__ import annotations

import functools
import re
import unicodedata

# Characters a bookmaker uses as separators in a team name ("Bodo/Glimt",
# "St. Mirren", "Paris-SG"); they never distinguish two clubs.
_TEAM_PUNCTUATION = re.compile(r"[./\\\-\&'’`,()]+")
# Letters NFKD does not decompose.
_LETTER_FOLDS = str.maketrans({"đ": "dj", "ø": "o", "æ": "ae", "ß": "ss", "ł": "l"})


@functools.lru_cache(maxsize=65536)
def raw_team_key(name: str) -> str:
    """Make only lossless superficial raw-name comparisons.

    This deliberately does not call the normalizer's fuzzy fallback. Team
    identity decisions that see different raw forms must go through the
    explicit alias allowlist or the evidence ledger.

    The matcher asks for the same names thousands of times per scan, so the
    pure result is memoized. The cache is per process and never cleared by a
    caller: the function's output depends only on ``name``.
    """
    decomposed = unicodedata.normalize("NFKD", name.casefold().translate(_LETTER_FOLDS))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_TEAM_PUNCTUATION.sub(" ", plain).split())
