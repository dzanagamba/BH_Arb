"""Classify a book's raw market labels into the nine supported market types.

The classifier is the machine replacement for a hand-written registry row. It
reads the outcome labels a book publishes, not the book's own ID, so a new book
can be onboarded without editing ``config/bookmaker_markets.json``.

It is strict on purpose:

* a 1X2 market needs all three of ``1``, ``X``, ``2``;
* an over/under market needs both sides and a supported line (1.5/2.5/3.5);
* BTTS needs both ``GG/NG`` or ``Yes/No`` (``Da/Ne``);
* a first-half marker changes the type, never the line;
* an Asian handicap needs an explicit line and both sides.

An incomplete or unknown label set returns ``None``. It is counted as a gap by
the caller, not guessed into a market.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from models.schemas import Market, MarketType, OddsValue

_SUPPORTED_LINES = {1.5: MarketType.OVER_UNDER_1_5, 2.5: MarketType.OVER_UNDER_2_5, 3.5: MarketType.OVER_UNDER_3_5}
_FIRST_HALF_MARKERS = (
    "1st half",
    "first half",
    "ht",
    "half time",
    "poluvreme",
    "poluvrijeme",
    "1. poluvreme",
    "1. poluvrijeme",
    "prvo poluvreme",
)
_OU_LABEL = re.compile(r"^(over|under|vise|više|manje)\s*(\d+(?:[.,]\d+)?)?$")
_AH_LABEL = re.compile(r"^(?:[12]|home|away|domacin|gost)\s*[\(\s]*([+-]?\d+(?:[.,]\d+)?)")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _float(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _period_is_first_half(period: str, market_key: str, labels: list[str]) -> bool:
    haystack = _fold(" ".join([period.replace("_", " "), market_key, *labels]))
    return any(marker in haystack for marker in _FIRST_HALF_MARKERS)


@dataclass(frozen=True)
class MarketClassification:
    market_type: MarketType
    line: float | None
    period: str
    confidence: float
    evidence: str


def classify(
    labels: list[str],
    *,
    line: float | None = None,
    period: str = "full_time",
    market_key: str = "",
) -> MarketClassification | None:
    """Return the market a label set describes, or ``None`` if it is not one."""
    folded = [_fold(label) for label in labels if label.strip()]
    if not folded:
        return None
    unique = set(folded)
    first_half = _period_is_first_half(period, market_key, labels)
    resolved_period = "first_half" if first_half else "full_time"

    if unique == {"1", "x", "2"}:
        market_type = MarketType.FIRST_HALF_1X2 if first_half else MarketType.MATCH_RESULT
        return MarketClassification(market_type, None, resolved_period, 1.0, "labels:1/X/2")

    if unique == {"1x", "12", "x2"}:
        return MarketClassification(MarketType.DOUBLE_CHANCE, None, resolved_period, 1.0, "labels:1X/12/X2")

    if unique in ({"gg", "ng"}, {"yes", "no"}, {"da", "ne"}):
        return MarketClassification(MarketType.BTTS, None, resolved_period, 1.0, "labels:BTTS")

    over_under: dict[str, float] = {}
    for label in folded:
        match = _OU_LABEL.match(label)
        if match:
            value = _float(match.group(2)) if match.group(2) else line
            if value is not None:
                over_under[match.group(1)] = value
    if over_under and len(over_under) == 2:
        sides = set(over_under)
        if sides == {"over", "under"} or sides == {"vise", "manje"}:
            values = set(over_under.values())
            if len(values) == 1:
                resolved = values.pop()
                if resolved in _SUPPORTED_LINES:
                    market_type = (
                        MarketType.FIRST_HALF_OU if first_half else _SUPPORTED_LINES[resolved]
                    )
                    return MarketClassification(
                        market_type, resolved, resolved_period, 0.95, f"labels:O/U {resolved}"
                    )

    if first_half and "handicap" in _fold(market_key):
        return None

    if any(marker in _fold(market_key) for marker in ("handicap", "hendikep")):
        handicap = line
        if handicap is None:
            for label in folded:
                match = _AH_LABEL.match(label)
                if match:
                    handicap = _float(match.group(1))
                    break
        if handicap is not None and len(folded) >= 2:
            return MarketClassification(
                MarketType.ASIAN_HANDICAP, handicap, resolved_period, 0.9, f"labels:AH {handicap}"
            )

    return None


def classify_market(market: Market) -> MarketClassification | None:
    """Classify an already-parsed ``Market`` from its outcome labels."""
    return classify([odds.label for odds in market.odds])


def classification_odds(market: Market, classification: MarketClassification) -> list[OddsValue]:
    """Return the market's odds unchanged; kept as a seam for future filtering."""
    return list(market.odds)
