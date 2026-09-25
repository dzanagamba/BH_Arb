"""Registry <-> doc consistency: no orphan IDs, no undocumented parser IDs.

``config/bookmaker_markets.json`` is the single source of truth for per-bookmaker
source market IDs.  ``MARKET_MAPPING.md`` carries a machine-generated table of
that registry, so a registry change without a doc regeneration is a test
failure rather than silent documentation drift.

The hand-written analysis above the generated markers is deliberately NOT
covered here except for one regression: a regeneration must never clobber it.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.market_registry import MarketRegistry  # noqa: E402
from models.schemas import MarketType  # noqa: E402

DOC_PATH = REPO_ROOT / "MARKET_MAPPING.md"
REGISTRY_PATH = REPO_ROOT / "config" / "bookmaker_markets.json"
MAPPED_HEADER = (
    "| Bookmaker | Mode | Market | Source IDs | Outcome labels | Min legs | Line | Settlement |"
)
EXCLUDED_HEADER = "| Bookmaker | Excluded IDs / name patterns |"
EM_DASH = "—"
# The generator is imported lazily so that a missing script shows up as a
# failing generator test rather than a collection error that hides whether the
# documentation actually carries the generated section.
BEGIN_MARKER = "<!-- GENERATED FROM bookmaker_markets.json -->"
END_MARKER = "<!-- END GENERATED FROM bookmaker_markets.json -->"


def _generator() -> ModuleType:
    return importlib.import_module("scripts.generate_market_mapping_doc")


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _registry_json() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _split_section(doc: str) -> tuple[str, str]:
    """Return (narrative, generated block) around the GENERATED markers."""
    start = doc.find(BEGIN_MARKER)
    end = doc.find(END_MARKER)
    assert start != -1, f"{BEGIN_MARKER} missing from {DOC_PATH.name}"
    assert end != -1, f"{END_MARKER} missing from {DOC_PATH.name}"
    return doc[:start], doc[start : end + len(END_MARKER)]


def _rows(block: str, header: str) -> list[list[str]]:
    """Parse the generated markdown table that follows ``header``."""
    lines = block.splitlines()
    index = lines.index(header)
    rows: list[list[str]] = []
    for line in lines[index + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(_cells(line))
    return rows


def _tokens(cell: str) -> list[str]:
    return [token.strip().strip("`") for token in cell.split(",") if token.strip()]


def _plain(cell: str) -> str:
    """Strip the code ticks the generator wraps IDs and book names in."""
    return cell.strip().strip("`")


def _documented_market_rows(block: str) -> list[dict[str, Any]]:
    rows = []
    for book, mode, market, ids, labels, min_legs, line, settlement in _rows(
        block, MAPPED_HEADER
    ):
        rows.append(
            {
                "bookmaker": _plain(book),
                "mode": _plain(mode),
                "market": _plain(market),
                "ids": _tokens(ids),
                "labels": _tokens(labels),
                "min_legs": min_legs,
                "line": line,
                "settlement": _plain(settlement),
            }
        )
    return rows


# --- brief-prescribed checks ------------------------------------------------


def test_registry_file_is_valid_and_complete():
    r = MarketRegistry()
    from config.settings import BOOKMAKERS

    for bid in BOOKMAKERS:
        ids = r.ids_for(bid, "prematch", MarketType.MATCH_RESULT)
        assert ids, f"{bid} has no prematch 1X2 in registry"


def test_nsoft_advance_id_136_not_in_registry():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 136) is None
    assert r.lookup("admiralbet", "prematch", 136) is None


def test_registry_matches_documented_market_mapping():
    doc = _doc()
    r = MarketRegistry()
    # Every registry ID for mdshop prematch must appear somewhere in the doc.
    for sid in sorted(str(x) for x in r.ids_for("mdshop", "prematch", MarketType.MATCH_RESULT)):
        assert sid in doc, f"mdshop 1X2 id {sid} not documented"


def test_generated_section_marker_is_present():
    """The doc carries the marker the generator splices on."""
    assert BEGIN_MARKER in _doc()
    assert END_MARKER in _doc()


# --- strengthened: every bookmaker, every mode ------------------------------


def _iter_market_types(data: dict):
    """Yield (book, mode, MarketType) per declared market, skipping ``_`` keys."""
    for book, modes in data.items():
        if str(book).startswith("_"):
            continue
        for mode, markets in modes.items():
            for market_type_value in markets:
                yield str(book), str(mode), MarketType(market_type_value)


def _declared(registry: MarketRegistry, book: str, mode: str, market_type: MarketType):
    """Resolve one book/mode/market through the loader, without the generator.

    ``ids_for`` plus ``specs_for`` are the public API.  A source ID shared by
    several lines yields one spec per declaration, so de-duplicate them here
    exactly as a correct generator must.
    """
    declarations: dict = {}
    for source_id in registry.ids_for(book, mode, market_type):
        for spec in registry.specs_for(book, mode, source_id):
            if spec.market_type is not market_type:
                continue
            key = (frozenset(str(i) for i in spec.ids), spec.line)
            declarations.setdefault(key, spec)
    return list(declarations.values())


def _line_text(line: float | None) -> str:
    return EM_DASH if line is None else f"{line:g}"


def _expected_row_tuples(data: dict) -> Counter:
    """Re-derive the table the generator owes, straight from the loader."""
    registry = MarketRegistry()
    expected: Counter = Counter()
    for book, mode, market_type in _iter_market_types(data):
        specs = _declared(registry, book, mode, market_type)
        assert specs, f"{book}/{mode}/{market_type.value} resolved to no MarketSpec"
        assert len(specs) == 1, f"{book}/{mode}/{market_type.value} has conflicting specs"
        spec = specs[0]
        expected[
            (
                book,
                mode,
                tuple(sorted(str(i) for i in spec.ids)),
                tuple(sorted(spec.labels)),
                spec.min_legs,
                _line_text(spec.line),
                spec.settlement,
            )
        ] += 1
    return expected


def _documented_row_tuples(block: str) -> Counter:
    rows = _documented_market_rows(block)
    assert rows, "generated market table is empty"
    return Counter(
        (
            str(row["bookmaker"]),
            str(row["mode"]),
            tuple(sorted(str(sid) for sid in row["ids"])),
            tuple(sorted(str(label) for label in row["labels"])),
            int(str(row["min_legs"])),
            str(row["line"]),
            str(row["settlement"]),
        )
        for row in rows
    )


def test_documented_market_rows_match_registry_defaults():
    """Every documented row equals a registry row: book, mode, ids, labels, legs, line.

    The comparison is bidirectional (Counter equality), so a table row the
    registry does not declare fails just as loudly as a missing registry row.
    It deliberately does not import the generator's market-name labels: the
    market name is prose, the numbers are the contract.
    """
    expected = _expected_row_tuples(_registry_json())
    actual = _documented_row_tuples(_split_section(_doc())[1])
    assert actual == expected, (
        f"{sum((expected - actual).values())} registry rows undocumented, "
        f"{sum((actual - expected).values())} documented rows not in the registry"
    )


def test_every_bookmaker_mode_and_market_id_is_documented():
    """Every registry bookmaker is represented, in prematch and in live."""
    registry = MarketRegistry()
    data = _registry_json()
    _, block = _split_section(_doc())
    rows_by_book_mode: dict[tuple[str, str], list[dict]] = {}
    for row in _documented_market_rows(block):
        rows_by_book_mode.setdefault((str(row["bookmaker"]), str(row["mode"])), []).append(row)

    for book, modes in data.items():
        if str(book).startswith("_"):
            continue
        for mode in modes:
            rows = rows_by_book_mode.get((str(book), str(mode)), [])
            expected_ids: set[str] = set()
            for market_type_value in modes[mode]:
                market_type = MarketType(market_type_value)
                ids = {str(i) for i in registry.ids_for(book, mode, market_type)}
                assert ids, f"{book}/{mode}/{market_type_value} has no registry ids"
                expected_ids |= ids
            if not expected_ids:
                # A declared-but-empty mode (EVLBet/Betole live) has no IDs to
                # represent; the hand-written narrative explains why.
                assert not rows, f"{book}/{mode} is empty in the registry but documented"
                continue
            documented_ids = {str(sid) for row in rows for sid in row["ids"]}
            assert documented_ids == expected_ids, (
                f"{book}/{mode} documented ids {sorted(documented_ids)} "
                f"!= registry ids {sorted(expected_ids)}"
            )
            assert len(rows) == len(modes[mode]), (
                f"{book}/{mode} documents {len(rows)} markets, "
                f"registry has {len(modes[mode])}"
            )


def test_every_bookmaker_appears_in_the_generated_table():
    _, block = _split_section(_doc())
    books = {str(row["bookmaker"]) for row in _documented_market_rows(block)}
    for book in _registry_json():
        if str(book).startswith("_"):
            continue
        assert str(book) in books, f"{book} missing from generated table"


# --- _excluded handling -----------------------------------------------------


def test_excluded_block_is_not_rendered_as_a_bookmaker():
    _, block = _split_section(_doc())
    books = {str(row["bookmaker"]) for row in _documented_market_rows(block)}
    assert "_excluded" not in books
    assert "| `_excluded` |" not in block


def test_excluded_market_ids_are_documented():
    """Deliberately-unmapped IDs are surfaced for the operator."""
    excluded = _registry_json().get("_excluded", {})
    _, block = _split_section(_doc())
    documented = {
        _plain(str(row[0])): _tokens(str(row[1]))
        for row in _rows(block, EXCLUDED_HEADER)
    }
    for book, values in excluded.items():
        assert str(book) in documented, f"{book} exclusions not documented"
        assert set(str(v) for v in values) == set(documented[str(book)]), (
            f"{book} exclusions in the doc differ from the registry `_excluded` block"
        )


def test_excluded_ids_do_not_leak_into_mapped_rows():
    _, block = _split_section(_doc())
    for row in _documented_market_rows(block):
        book = str(row["bookmaker"])
        # 136 is "Ide dalje" for every NSoft book and must never be mapped.
        if book in {"mdshop", "admiralbet"}:
            assert "136" not in row["ids"], f"{book} documents excluded id 136 as mapped"


# --- regeneration must not clobber the hand-written narrative ---------------


def test_splice_preserves_narrative_around_the_markers():
    doc = _doc()
    narrative, block = _split_section(doc)
    assert narrative.strip(), "no hand-written narrative above the generated section"
    assert _generator().splice(doc, block) == doc, "splice is not a no-op on the current doc"


def test_splice_replaces_only_the_generated_block():
    splice = _generator().splice
    existing = (
        "# Title\n\nHand-written prose that must survive.\n\n"
        f"{BEGIN_MARKER}\nold generated body\n{END_MARKER}\n\nTrailing note.\n"
    )
    updated = splice(existing, f"{BEGIN_MARKER}\nnew body\n{END_MARKER}")
    assert "Hand-written prose that must survive." in updated
    assert "Trailing note." in updated
    assert "old generated body" not in updated
    assert "new body" in updated
    assert updated.count(BEGIN_MARKER) == 1
    assert updated.count(END_MARKER) == 1


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param("# Title\n\nno markers at all\n", id="no-markers"),
        pytest.param(f"# Title\n\n{BEGIN_MARKER}\nbody without an end\n", id="no-end"),
        pytest.param(f"# Title\n\n{END_MARKER}\nbody without a begin\n", id="no-begin"),
        pytest.param(
            f"{END_MARKER}\nreversed order\n{BEGIN_MARKER}\n", id="reversed"
        ),
        pytest.param(
            f"{BEGIN_MARKER}\na\n{END_MARKER}\n{BEGIN_MARKER}\nb\n{END_MARKER}\n",
            id="duplicated",
        ),
    ],
)
def test_splice_refuses_to_touch_a_doc_without_exactly_one_marker_pair(existing):
    """Without a clean marker pair the generator aborts instead of truncating."""
    with pytest.raises(RuntimeError):
        _generator().splice(existing, f"{BEGIN_MARKER}\nnew\n{END_MARKER}")


def test_build_section_is_deterministic():
    module = _generator()
    assert module.build_section(module.REGISTRY_PATH) == module.build_section(
        module.REGISTRY_PATH
    )


def test_committed_doc_is_up_to_date_with_the_registry():
    """`python scripts/generate_market_mapping_doc.py --check` must pass."""
    module = _generator()
    doc = _doc()
    assert doc == module.splice(doc, module.build_section(module.REGISTRY_PATH))


def test_generated_market_names_are_human_readable():
    _, block = _split_section(_doc())
    labels = {str(row["market"]) for row in _documented_market_rows(block)}
    assert "Full-time 1X2" in labels
    assert "Double Chance" in labels
    assert "BTTS" in labels
    assert "Over/Under 2.5" in labels
    # Raw enum values leaking into the table mean a label is missing.
    assert not labels & {member.value for member in MarketType}


def test_generator_never_emits_a_table_row_for_a_dashed_key():
    _, block = _split_section(_doc())
    assert not re.search(r"^\| `_[^`]+` \|", block, flags=re.MULTILINE)
