"""Team-name identity rules for cross-book matching.

Derived from production entity-resolution practice: normalize hard, but keep the
tokens that distinguish a roster (``academy``, ``junior``, ``youth``, ``women``,
digits). Remove only organisation noise (``fc``, ``club``, ``gaming``). Then:

* an initialism matches only when one side is exactly the initials of every
  token on the other side, and both names are at least five characters;
* a differing marker from the block list is a different team, even at high
  string similarity (``Evil Geniuses`` vs ``Evil Geniuses GC``);
* a one-sided addition is vetoed when the extra token is a marker or colour;
* otherwise normalized Levenshtein / token-set similarity decides.

This module is deliberately independent of the certainty gate. The gate still
requires proof; these rules only stop the candidate scorer from pruning a pair
the gate could have proven, and stop it from proposing a merge that the block
list forbids.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

# Tokens that do not identify a roster.
# "fc"/"cf"/"sc" are deliberately kept: "Yokohama" and "Yokohama FC" are
# different clubs, so a club designator can be the only distinguishing token.
_ORG_TOKENS = {
    "club",
    "team",
    "the",
    "gaming",
    "esports",
    "esport",
    "and",
}

# Tokens that DO identify a different side. A differing one is a veto.
_MARKER_TOKENS = {
    "academy",
    "academia",
    "junior",
    "juniors",
    "youth",
    "women",
    "womens",
    "ladies",
    "reserve",
    "reserves",
    "ii",
    "b",
    "u17",
    "u19",
    "u20",
    "u21",
    "u23",
    "gc",
}

_COLOUR_TOKENS = {"blue", "white", "red", "black", "green", "yellow", "orange"}

_PUNCT = re.compile(r"[./\\\-\&'’`,()]+")
_DIGITS = re.compile(r"\d+")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_PUNCT.sub(" ", plain).split())


def tokens(name: str) -> list[str]:
    return [token for token in _fold(name).split() if token not in _ORG_TOKENS]


def normalize(name: str) -> str:
    return " ".join(tokens(name))


def _initials_match(left: list[str], right: list[str]) -> bool:
    left_norm, right_norm = " ".join(left), " ".join(right)
    if len(left) == 1 and len(right) > 1:
        acronym = "".join(token[0] for token in right)
        return len(left[0]) >= 2 and left[0] == acronym and len(right_norm) >= 5
    if len(right) == 1 and len(left) > 1:
        acronym = "".join(token[0] for token in left)
        return len(right[0]) >= 2 and right[0] == acronym and len(left_norm) >= 5
    return False


def similarity(left: str, right: str) -> float:
    """Return a 0..1 identity score with the production vetoes applied."""
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    left_markers = set(left_tokens) & _MARKER_TOKENS
    right_markers = set(right_tokens) & _MARKER_TOKENS
    if left_markers != right_markers:
        return 0.0

    left_set, right_set = set(left_tokens), set(right_tokens)
    extra_left = left_set - right_set
    extra_right = right_set - left_set
    if (extra_left and not extra_right) or (extra_right and not extra_left):
        extra = extra_left or extra_right
        if extra & (_MARKER_TOKENS | _COLOUR_TOKENS):
            return 0.0

    if _initials_match(left_tokens, right_tokens):
        return 1.0

    left_norm, right_norm = " ".join(left_tokens), " ".join(right_tokens)
    # Partial ratio is deliberately not used: on short names it turns two
    # unrelated clubs into a 0.6 match ("Arsenal" / "Chelsea").
    return max(
        fuzz.token_set_ratio(left_norm, right_norm),
        fuzz.ratio(left_norm, right_norm),
    ) / 100.0
