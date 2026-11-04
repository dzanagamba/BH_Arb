"""Regenerate the generated section of ``MARKET_MAPPING.md`` from the registry.

``config/bookmaker_markets.json`` is the single source of truth for per-bookmaker
source market IDs, so the ID tables in ``MARKET_MAPPING.md`` are machine-written
from it and cannot drift from the code.

Only the block between ``BEGIN_MARKER`` and ``END_MARKER`` is written.  The
hand-written analysis above it (live-feed notes, settlement rationale, per-book
audit tables) is preserved verbatim: :func:`splice` raises rather than guessing
when the markers are missing, unbalanced or duplicated, so a regeneration can
never truncate the narrative.  :func:`splice` is the only thing that touches the
file.

Usage:
    python scripts/generate_market_mapping_doc.py          # rewrite the block
    python scripts/generate_market_mapping_doc.py --check   # fail if stale
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.market_registry import MarketRegistry, MarketSpec  # noqa: E402
from models.schemas import MarketType  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(REPO_ROOT, "config", "bookmaker_markets.json")
DOC_PATH = os.path.join(REPO_ROOT, "MARKET_MAPPING.md")

# The brief's exact marker string; the test module asserts on it independently.
BEGIN_MARKER = "<!-- GENERATED FROM bookmaker_markets.json -->"
END_MARKER = "<!-- END GENERATED FROM bookmaker_markets.json -->"
EM_DASH = "—"

MARKET_TYPE_LABEL: dict[MarketType, str] = {
    MarketType.MATCH_RESULT: "Full-time 1X2",
    MarketType.DOUBLE_CHANCE: "Double Chance",
    MarketType.BTTS: "BTTS",
    MarketType.OVER_UNDER_0_5: "Over/Under 0.5",
    MarketType.OVER_UNDER_1_5: "Over/Under 1.5",
    MarketType.OVER_UNDER_2_5: "Over/Under 2.5",
    MarketType.OVER_UNDER_3_5: "Over/Under 3.5",
    MarketType.OVER_UNDER_4_5: "Over/Under 4.5",
    MarketType.OVER_UNDER_5_5: "Over/Under 5.5",
    MarketType.FIRST_HALF_1X2: "First-half 1X2",
    MarketType.FIRST_HALF_OU: "First-half Over/Under",
    MarketType.ASIAN_HANDICAP: "Asian Handicap",
    MarketType.MONEYLINE: "Moneyline (two-way)",
    MarketType.MONEYLINE_3WAY: "Moneyline (three-way)",
    MarketType.HANDICAP: "Handicap",
    MarketType.TOTAL: "Total",
}

MAPPED_HEADER = "| Bookmaker | Mode | Market | Source IDs | Outcome labels | Min legs | Line | Settlement |"
EXCLUDED_HEADER = "| Bookmaker | Excluded IDs / name patterns |"

class MarkerError(RuntimeError):
    """The doc does not carry exactly one well-formed generated-section marker pair."""


def _id_sort_key(value: int | str) -> tuple[int, int, str]:
    text = str(value)
    if text.lstrip("-").isdigit():
        return (0, int(text), "")
    return (1, 0, text)


def _sorted_ids(ids: Any) -> list[str]:
    """Stable, readable ID ordering: numbers numerically, then names."""
    return [str(value) for value in sorted((str(i) for i in ids), key=_id_sort_key)]


def _code_list(values: Any) -> str:
    tokens = _sorted_ids(values)
    return ", ".join(f"`{token}`" for token in tokens) if tokens else EM_DASH


def _label_list(labels: Any) -> str:
    tokens = sorted({str(label) for label in labels})
    return ", ".join(tokens) if tokens else EM_DASH


def _line_cell(line: float | None) -> str:
    return EM_DASH if line is None else f"{line:g}"


def _settlement_cell(spec: MarketSpec) -> str:
    if spec.requires_sbv is None:
        return spec.settlement
    return f"{spec.settlement}, only at specifier {spec.requires_sbv}"


def _specs_for(
    registry: MarketRegistry, book: str, mode: str, market_type: MarketType
) -> list[MarketSpec]:
    """Return the registry specs for one book/mode/market type.

    Uses only the public API: ``ids_for`` gives the registered IDs for the type
    and ``specs_for`` resolves each of them.  A source ID shared by several
    lines/types yields one spec per declaration, so the declarations are
    de-duplicated and any disagreement is a registry bug we refuse to paper over.
    """
    specs: dict[tuple[Any, ...], MarketSpec] = {}
    for source_id in sorted(registry.ids_for(book, mode, market_type), key=_id_sort_key):
        for spec in registry.specs_for(book, mode, source_id):
            if spec.market_type is not market_type:
                continue
            key = (
                frozenset(str(i) for i in spec.ids),
                frozenset(spec.labels),
                spec.min_legs,
                spec.line,
                spec.settlement,
                spec.requires_sbv,
            )
            specs.setdefault(key, spec)
    return list(specs.values())


def _load(registry_path: str) -> dict[str, Any]:
    with open(registry_path, encoding="utf-8") as file:
        data: Any = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{registry_path} must contain a JSON object")
    return data


def _bookmakers(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Registry books in declaration order, skipping the reserved ``_`` keys."""
    return [(str(book), modes) for book, modes in data.items() if not str(book).startswith("_")]


def build_section(registry_path: str = REGISTRY_PATH) -> str:
    """Render the generated block (markers included) for the given registry."""
    data = _load(registry_path)
    registry = MarketRegistry(registry_path)

    mapped_rows = 0
    market_lines: list[str] = []
    excluded_lines: list[str] = []
    book_count = 0

    for book, modes in _bookmakers(data):
        book_count += 1
        for mode, markets in modes.items():
            for market_type_value in markets:
                market_type = MarketType(market_type_value)
                specs = _specs_for(registry, book, str(mode), market_type)
                if not specs:
                    raise ValueError(
                        f"registry entry {book}/{mode}/{market_type_value} resolved "
                        "to no MarketSpec; the JSON and the loader disagree"
                    )
                if len(specs) > 1:
                    raise ValueError(
                        f"registry entry {book}/{mode}/{market_type_value} has "
                        f"{len(specs)} conflicting declarations; the JSON and the "
                        "loader disagree"
                    )
                spec = specs[0]
                # Both the human label and the MarketType value: an operator
                # reads "Over/Under 2.5", a developer greps "over_under_2_5".
                label = MARKET_TYPE_LABEL.get(market_type, market_type.value)
                market_lines.append(
                    f"| `{book}` | {mode} | {label} (`{market_type.value}`) | "
                    f"{_code_list(spec.ids)} | "
                    f"{_label_list(spec.labels)} | {spec.min_legs} | "
                    f"{_line_cell(spec.line)} | {_settlement_cell(spec)} |"
                )
                mapped_rows += 1

    for book, values in sorted(data.get("_excluded", {}).items()):
        excluded_lines.append(f"| `{book}` | {_code_list(values)} |")

    lines = [
        BEGIN_MARKER,
        "",
        "<!-- Everything between these two markers is written by",
        "     scripts/generate_market_mapping_doc.py.  Do not edit it by hand:",
        "     hand edits here are lost on the next regeneration. -->",
        "",
        "Regenerate: `python scripts/generate_market_mapping_doc.py`  ",
        "Verify without writing: `python scripts/generate_market_mapping_doc.py --check`",
        "",
        "## Registry table (generated)",
        "",
        "Source of truth: `config/bookmaker_markets.json`, loaded by",
        "`engine/market_registry.py`. Values below are resolved through the loader,",
        "so registry defaults (outcome labels, min legs, settlement) are included.",
        f"Covers {book_count} bookmakers and {mapped_rows} book/mode/market rows.",
        "",
        "Scope: these are the IDs the **registry declares**. It is the authority on",
        "the declared mapping, not on parser dispatch — a book's parser may read a",
        "subset of the IDs listed for it, because some parsers dispatch on a",
        "hardcoded pick table rather than iterating the registry. Where a row lists",
        "more IDs than the book actually consumes, the per-book field notes at the",
        "bottom of this file say so.",
        "",
        "### Mapped markets",
        "",
        MAPPED_HEADER,
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        *market_lines,
        "",
        "### Deliberately unmapped source IDs",
        "",
        "The `_excluded` block of the registry: offers that are recognised and",
        "deliberately not mapped, mostly advance/qualification, half-time,",
        "handicap, period and combination markets. Listing an ID here suppresses",
        "the unmapped-market health diagnostic for it, so an operator does not",
        "chase a market the project intends to ignore. It is a declaration of",
        "intent, not a rejection mechanism: a parser still has to decline the",
        "offer on its own, and no ID may appear both here and in the table above.",
        "A name pattern applies to any source ID that matches it.",
        "",
        EXCLUDED_HEADER,
        "| --- | --- |",
        *excluded_lines,
        END_MARKER,
    ]
    return "\n".join(lines)


def splice(existing: str, block: str) -> str:
    """Return ``existing`` with only the generated block replaced by ``block``.

    Raises :class:`MarkerError` unless ``existing`` holds exactly one
    ``BEGIN_MARKER`` followed later by exactly one ``END_MARKER``.  Failing loud
    is the whole point: a silent fallback would risk deleting the hand-written
    narrative above the block.
    """
    start = existing.find(BEGIN_MARKER)
    end = existing.find(END_MARKER)
    if start == -1 or end == -1:
        missing = BEGIN_MARKER if start == -1 else END_MARKER
        raise MarkerError(
            f"{missing} is missing from MARKET_MAPPING.md; refusing to rewrite the "
            "file because the hand-written sections have no protected boundary"
        )
    if end < start:
        raise MarkerError(f"{END_MARKER} appears before {BEGIN_MARKER}")
    if existing.find(BEGIN_MARKER, start + 1) != -1:
        raise MarkerError(f"{BEGIN_MARKER} appears more than once")
    if existing.find(END_MARKER, end + 1) != -1:
        raise MarkerError(f"{END_MARKER} appears more than once")
    return existing[:start] + block + existing[end + len(END_MARKER) :]


def render(doc_path: str = DOC_PATH, registry_path: str = REGISTRY_PATH) -> str:
    """Return the full new contents of ``doc_path``."""
    with open(doc_path, encoding="utf-8") as file:
        existing = file.read()
    return splice(existing, build_section(registry_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if MARKET_MAPPING.md is not in sync with the registry",
    )
    args = parser.parse_args(argv)

    try:
        updated = render()
    except (MarkerError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    with open(DOC_PATH, encoding="utf-8") as file:
        existing = file.read()

    if args.check:
        if existing != updated:
            print(
                "error: MARKET_MAPPING.md is out of date; run "
                "`python scripts/generate_market_mapping_doc.py`",
                file=sys.stderr,
            )
            return 1
        print("MARKET_MAPPING.md is in sync with config/bookmaker_markets.json")
        return 0

    if existing == updated:
        print("MARKET_MAPPING.md already in sync; no write needed")
        return 0
    # Keep whatever line ending the file already uses.  core.autocrlf=true can
    # hand us a CRLF file on Windows, and rewriting it as LF would show up as a
    # whole-file diff on a doc whose narrative is hand-written.
    with open(DOC_PATH, "rb") as raw:
        newline = "\r\n" if b"\r\n" in raw.read() else "\n"
    with open(DOC_PATH, "w", encoding="utf-8", newline=newline) as file:
        file.write(updated)
    print(f"Wrote {DOC_PATH} ({len(updated.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
