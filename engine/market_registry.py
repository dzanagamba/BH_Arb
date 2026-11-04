"""Per-bookmaker market registry — the single source of truth for market IDs."""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from math import isclose
from typing import Any

from models.schemas import MarketType

REGISTRY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_markets.json")
)
GENERATED_REGISTRY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "config", "generated", "bookmaker_markets.json")
)

# Unknown source IDs are process-wide diagnostics.  Keeping this at module scope
# lets scrapers loaded independently by the API and worker processes publish the
# same health signal without threading a mutable counter through every parser.
unmapped_markets: dict[str, int] = {}
EXCLUDED_MARKETS: dict[str, set[str]] = {}


def _normalise_exclusion(value: object) -> str:
    return str(value).strip().casefold()


def _matches_exclusion(value: int | str, patterns: set[str]) -> bool:
    normalized = _normalise_exclusion(value)
    return any(
        fnmatch.fnmatchcase(normalized, pattern)
        for pattern in patterns
    )


def _is_excluded(
    bookmaker: str,
    source_id: int | str,
    context: int | str | None = None,
) -> bool:
    patterns = EXCLUDED_MARKETS.get(bookmaker, set())
    if _matches_exclusion(source_id, patterns):
        return True
    return context is not None and _matches_exclusion(context, patterns)


def record_unmapped(
    bookmaker: str,
    source_id: int | str,
    context: int | str | None = None,
) -> None:
    """Record a genuinely unknown source ID, ignoring declared exclusions."""
    if _is_excluded(bookmaker, source_id, context):
        return
    key = f"{bookmaker}:{source_id}"
    unmapped_markets[key] = unmapped_markets.get(key, 0) + 1


_DEFAULT_LABELS: dict[MarketType, set[str]] = {
    MarketType.MATCH_RESULT: {"1", "X", "2"},
    MarketType.DOUBLE_CHANCE: {"1X", "12", "X2"},
    MarketType.BTTS: {"GG", "NG"},
    MarketType.OVER_UNDER_0_5: {"Over 0.5", "Under 0.5"},
    MarketType.OVER_UNDER_1_5: {"Over 1.5", "Under 1.5"},
    MarketType.OVER_UNDER_2_5: {"Over 2.5", "Under 2.5"},
    MarketType.OVER_UNDER_3_5: {"Over 3.5", "Under 3.5"},
    MarketType.OVER_UNDER_4_5: {"Over 4.5", "Under 4.5"},
    MarketType.OVER_UNDER_5_5: {"Over 5.5", "Under 5.5"},
}


@dataclass
class MarketSpec:
    """The rules and source IDs for one bookmaker/mode/market entry."""

    bookmaker: str
    mode: str
    market_type: MarketType
    ids: set[int | str] = field(default_factory=set)
    labels: set[str] = field(default_factory=set)
    min_legs: int = 3
    line: float | None = None
    settlement: str = "full_time"
    # The only specifier value this market may be read at. NSoft's live
    # "rest of match" markets (1X2 id 6, BTTS id 995) carry the current score as
    # their specifier, and settle like the full-time market only from 0-0.
    requires_sbv: str | None = None
    # Machine-written rows carry the evidence that proved them. Hand-written
    # rows have an empty provenance.
    provenance: dict[str, Any] = field(default_factory=dict)
    generated: bool = False


class MarketRegistry:
    """Load market IDs and resolve them without embedding bookmaker constants."""

    def __init__(
        self,
        path: str = REGISTRY_PATH,
        generated_path: str | None = None,
    ) -> None:
        self.path = path
        self.generated_path = generated_path or GENERATED_REGISTRY_PATH
        self.generated_rows: set[str] = set()
        # A source ID can legitimately identify more than one market (for
        # example, NSoft's 137/138 total-goals IDs are shared by all lines and
        # MBet/SportPlus may use one block for several outcome families).  Keep
        # all candidates so line/type-aware callers can select the right one.
        self._index: dict[tuple[str, str, str], list[MarketSpec]] = {}
        self._by_type: dict[tuple[str, str, str], set[int | str]] = {}
        self._modes: set[tuple[str, str]] = set()
        # Expose the same process-wide counter as the module-level API.  The
        # alias is intentional: /api/health and diagnostic callers should see
        # records made through any registry instance.
        self.unmapped = unmapped_markets

        with open(path, encoding="utf-8") as file:
            data: Any = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("market registry must contain a JSON object")

        raw_excluded = data.get("_excluded", {})
        if not isinstance(raw_excluded, dict):
            raise ValueError("registry _excluded must be an object")
        self.excluded: dict[str, set[str]] = {}
        for bookmaker, values in raw_excluded.items():
            if not isinstance(values, list):
                raise ValueError(f"excluded IDs for {bookmaker!r} must be a list")
            normalized = {_normalise_exclusion(value) for value in values}
            self.excluded[str(bookmaker)] = normalized
            EXCLUDED_MARKETS.setdefault(str(bookmaker), set()).update(normalized)

        for bookmaker, modes in data.items():
            if str(bookmaker).startswith("_"):
                continue
            if not isinstance(modes, dict):
                raise ValueError(f"registry modes for {bookmaker!r} must be an object")
            for mode, markets in modes.items():
                self._modes.add((str(bookmaker), str(mode)))
                if not isinstance(markets, dict):
                    raise ValueError(
                        f"registry markets for {bookmaker}/{mode} must be an object"
                    )
                for market_type_value, raw_spec in markets.items():
                    if not isinstance(raw_spec, dict):
                        raise ValueError(
                            f"registry market {bookmaker}/{mode}/{market_type_value} "
                            "must be an object"
                        )
                    market_type = MarketType(market_type_value)
                    raw_line = raw_spec.get("line")
                    line = None if raw_line is None else float(raw_line)
                    labels = {
                        str(label) for label in raw_spec.get("labels", [])
                    }
                    if not labels:
                        labels = set(_DEFAULT_LABELS.get(market_type, set()))
                    spec = MarketSpec(
                        bookmaker=str(bookmaker),
                        mode=str(mode),
                        market_type=market_type,
                        ids=set(raw_spec.get("ids", [])),
                        labels=labels,
                        min_legs=int(raw_spec.get("min_legs", 3)),
                        line=line,
                        settlement=str(raw_spec.get("settlement", "full_time")),
                        requires_sbv=(
                            None
                            if raw_spec.get("requires_sbv") is None
                            else str(raw_spec["requires_sbv"])
                        ),
                    )
                    for source_id in spec.ids:
                        key = (str(bookmaker), str(mode), str(source_id))
                        self._index.setdefault(key, []).append(spec)
                    type_key = (str(bookmaker), str(mode), market_type.value)
                    self._by_type.setdefault(type_key, set()).update(spec.ids)

        self._load_generated()

    def _load_generated(self) -> None:
        """Merge machine-written rows, but only rows that carry provenance."""
        if not os.path.exists(self.generated_path):
            return
        try:
            with open(self.generated_path, encoding="utf-8") as file:
                data: Any = json.load(file)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for bookmaker, modes in data.items():
            if str(bookmaker).startswith("_") or not isinstance(modes, dict):
                continue
            for mode, markets in modes.items():
                if not isinstance(markets, dict):
                    continue
                self._modes.add((str(bookmaker), str(mode)))
                for market_type_value, raw_spec in markets.items():
                    if not isinstance(raw_spec, dict):
                        continue
                    provenance = raw_spec.get("_provenance")
                    if not isinstance(provenance, dict) or not provenance:
                        continue
                    try:
                        market_type = MarketType(market_type_value)
                    except ValueError:
                        continue
                    raw_line = raw_spec.get("line")
                    try:
                        line = None if raw_line is None else float(raw_line)
                    except (TypeError, ValueError):
                        line = None
                    labels = {
                        str(label) for label in raw_spec.get("labels", [])
                    } or set(_DEFAULT_LABELS.get(market_type, set()))
                    spec = MarketSpec(
                        bookmaker=str(bookmaker),
                        mode=str(mode),
                        market_type=market_type,
                        ids=set(raw_spec.get("ids", [])),
                        labels=labels,
                        min_legs=int(raw_spec.get("min_legs", 3)),
                        line=line,
                        settlement=str(raw_spec.get("settlement", "full_time")),
                        requires_sbv=(
                            None
                            if raw_spec.get("requires_sbv") is None
                            else str(raw_spec["requires_sbv"])
                        ),
                        provenance=provenance,
                        generated=True,
                    )
                    for source_id in spec.ids:
                        key = (str(bookmaker), str(mode), str(source_id))
                        # A generated row is inserted first so `lookup` prefers
                        # the machine-proven mapping over the hand-written one.
                        self._index.setdefault(key, []).insert(0, spec)
                        self.generated_rows.add(f"{bookmaker}/{mode}/{source_id}")
                    type_key = (str(bookmaker), str(mode), market_type.value)
                    self._by_type.setdefault(type_key, set()).update(spec.ids)

    def has_mode(self, bookmaker: str, mode: str) -> bool:
        """Return whether the registry explicitly defines this book/mode."""
        return (bookmaker, mode) in self._modes

    def has_source_id(self, bookmaker: str, mode: str, source_id: int | str) -> bool:
        """Return whether an ID is registered for this bookmaker/mode."""
        return (bookmaker, mode, str(source_id)) in self._index

    def is_excluded(
        self,
        bookmaker: str,
        mode: str,
        source_id: int | str,
        context: int | str | None = None,
    ) -> bool:
        """Return whether a source ID/name is explicitly excluded.

        ``mode`` is accepted for symmetry with the lookup API and for future
        mode-specific exclusions; the current JSON namespace is book-scoped.
        """
        del mode
        patterns = self.excluded.get(bookmaker, set())
        return (
            _matches_exclusion(source_id, patterns)
            or (context is not None and _matches_exclusion(context, patterns))
        )

    def specs_for(
        self, bookmaker: str, mode: str, source_id: int | str
    ) -> list[MarketSpec]:
        """Return all registry specs associated with a source ID."""
        return list(self._index.get((bookmaker, mode, str(source_id)), ()))

    def lookup(
        self,
        bookmaker: str,
        mode: str,
        source_id: int | str,
        line: float | None = None,
    ) -> MarketSpec | None:
        """Look up a source ID, optionally disambiguating a shared O/U ID."""
        specs = self.specs_for(bookmaker, mode, source_id)
        if not specs:
            return None
        if line is not None:
            for spec in specs:
                if spec.line is not None and isclose(float(spec.line), float(line)):
                    return spec
            for spec in specs:
                if spec.line is None:
                    return spec
        # Without a line, return the first declaration.  Callers handling a
        # market type with shared IDs should use specs_for/lookup_type instead.
        return specs[0]

    def lookup_type(
        self,
        bookmaker: str,
        mode: str,
        source_id: int | str,
        market_type: MarketType,
        line: float | None = None,
    ) -> MarketSpec | None:
        """Look up a source ID within a specific market type."""
        specs = [
            spec
            for spec in self.specs_for(bookmaker, mode, source_id)
            if spec.market_type == market_type
        ]
        if not specs:
            return None
        if line is not None:
            for spec in specs:
                if spec.line is None or isclose(float(spec.line), float(line)):
                    return spec
            return None
        return specs[0]

    def ids_for(
        self, bookmaker: str, mode: str, market_type: MarketType
    ) -> set[int | str]:
        """Return the source IDs registered for one market type."""
        return set(self._by_type.get((bookmaker, mode, market_type.value), set()))


MARKET_REGISTRY = MarketRegistry()
