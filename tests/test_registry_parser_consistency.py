"""The generated registry table in ``MARKET_MAPPING.md`` cannot drift.

``config/bookmaker_markets.json`` is the single source of truth for per-bookmaker
source market IDs, and ``MARKET_MAPPING.md`` carries a machine-generated table of
that registry. These tests cover the *documentation* side of that contract:

* the generated table matches the registry, in both directions;
* the committed file is in sync with the registry, so a registry edit without a
  regeneration is a test failure rather than silent drift;
* a regeneration can never clobber the hand-written field notes;
* the generated table states the scope of its own authority.

Registry <-> parser behaviour lives in ``tests/test_market_registry_wiring.py``.
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


# --- mapped and excluded must not overlap ----------------------------------


def _mapped_declarations() -> list[tuple[str, str, str, tuple[str, ...]]]:
    """(book, mode, market_type_value, source_ids) for every declared market.

    Read straight from the registry JSON so these tests do not depend on the
    parser modules at all.  ``market_type_value`` is ``MarketType.value`` and not
    ``str(member)``: ``MarketType`` is a str-mixin enum whose ``__str__`` is
    ``Enum.__str__``, so ``str`` yields ``"MarketType.BTTS"``.
    """
    rows: list[tuple[str, str, str, tuple[str, ...]]] = []
    for book, modes in _registry_json().items():
        if str(book).startswith("_"):
            continue
        for mode, markets in modes.items():
            for value, spec in markets.items():
                ids = tuple(sorted(str(i) for i in spec.get("ids", [])))
                rows.append((str(book), str(mode), MarketType(value).value, ids))
    return rows


def test_mapped_and_excluded_ids_are_disjoint():
    """An ID cannot be both mapped and deliberately unmapped.

    ``_excluded`` suppresses the unmapped-market diagnostic; it is not itself a
    rejection mechanism, so a registry that both maps and excludes an ID would
    silently make the mapping untestable and the exclusion meaningless.
    """
    registry = MarketRegistry()
    data = _registry_json()
    overlaps: list[str] = []
    for book, mode, market_type, ids in _mapped_declarations():
        for source_id in ids:
            if registry.is_excluded(book, mode, source_id):
                overlaps.append(f"{book}/{mode}/{market_type}/{source_id}")
    assert not overlaps, f"IDs are both mapped and excluded: {overlaps}"
    assert data.get("_excluded"), "registry lost its _excluded block"


# --- intro claims must not rot ---------------------------------------------


def _intro() -> str:
    """The hand-written text above the generated block."""
    return _split_section(_doc())[0]


def test_intro_bookmaker_count_matches_settings():
    """The intro used to claim seven bookmakers while nine were configured."""
    from config.settings import BOOKMAKERS

    documented = {str(row["bookmaker"]) for row in _documented_market_rows(
        _split_section(_doc())[1]
    )}
    expected = len(BOOKMAKERS)
    match = re.search(r"(\w+)\s+configured bookmakers", _intro())
    assert match, "the intro no longer states a bookmaker count"
    number_words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    stated = match.group(1).lower()
    claimed = number_words.get(stated, None)
    assert claimed is not None, f"unparseable bookmaker count {stated!r}"
    assert claimed == expected, (
        f"intro says {stated} configured bookmakers, settings has {expected}"
    )
    assert documented == set(BOOKMAKERS), (
        "the generated table and settings.BOOKMAKERS disagree on the book list"
    )


def test_intro_market_type_claims_match_the_registry():
    """The intro used to claim six MarketType values; schemas defines nine."""
    registry_types = {value for _b, _m, value, _ids in _mapped_declarations()}
    all_types = {member.value for member in MarketType}
    assert len(all_types) == 9, "MarketType grew; revisit the intro wording"
    assert len(registry_types) == 6, (
        "the registry now maps a different number of MarketType values; "
        "the intro states how many it maps"
    )
    unmapped = sorted(all_types - registry_types)
    for value in unmapped:
        assert value in _intro(), (
            f"MarketType `{value}` is not registry-backed but the intro does not "
            "say so, which is what made the old 'six values' claim wrong"
        )


# --- the generated table must not overstate its own authority --------------


def test_generated_table_states_the_scope_of_its_authority():
    """The table is authoritative about the *registry*, not about parser dispatch.

    A registry row may declare a superset of the IDs a book's parser actually
    reads -- betole's Over/Under rows do -- so an unqualified "this table tells
    you which IDs the parser uses" claim would be false. The generated block must
    therefore say what it is authoritative about, inside the block itself rather
    than in a caveat placed after it.
    """
    _, block = _split_section(_doc())
    body = block.lower()
    assert "registry" in body
    assert "dispatch" in body, (
        "the generated block must acknowledge that a parser's dispatch may read a "
        "subset of the declared IDs"
    )
    # The caveat has to live inside the markers, next to the table it qualifies.
    # Searching within `block` is what makes that structural rather than textual.
    assert "subset" in body, "the scope statement must say the parser may read a subset"
    # And the concrete case the caveat refers to must be named in the field notes,
    # so a reader who hits the over-broad row can find out which book it affects.
    notes = _narrative().lower()
    assert "betole" in notes and "superset" in notes, (
        "the field notes must identify betole as the book whose registry rows "
        "declare more IDs than its parser reads"
    )


# --- regeneration must not clobber the hand-written narrative ---------------


def _narrative() -> str:
    """The hand-written text OUTSIDE the generated markers (head + tail)."""
    doc = _doc()
    start = doc.find(BEGIN_MARKER)
    end = doc.find(END_MARKER)
    assert start != -1 and end != -1
    return doc[:start] + doc[end + len(END_MARKER) :]


def test_splice_preserves_narrative_around_the_markers():
    doc = _doc()
    _narrative_block, block = _split_section(doc)
    assert _narrative().strip(), "no hand-written narrative outside the markers"
    assert _generator().splice(doc, block) == doc, "splice is not a no-op on the current doc"


# Irreplaceable knowledge the registry cannot hold: feed endpoints, label
# vocabularies, filtering rules and the post-mortems.  Asserted by phrase so a
# regeneration cannot quietly pass by deleting the narrative, and so a wholesale
# narrative rewrite has to update this list deliberately.
NARRATIVE_ANCHORS = [
    "getwebevents?isLive=true",          # NSoft live feed
    "events_cached?live=true",           # MBet live feed
    "betting/matches",                   # Mozzartbet live feed
    "15 minutes",                        # prematch expiry window
    "sport-livecontent",                 # WWIN platform
    "svc-test.premier-kladionica.com/PrSync/PrSync.ashx",  # PrSync endpoint
    "execRes, tipIgre, sport",           # PrSync positional section order
    "grupaTipID=2",                      # PK football tip group
    "o-da",                              # PK BTTS outcome spelling
    "o<sport>:<market>:<outcome>",       # MBet odds key shape
    "ofb:fts",                           # MBet look-alike market
    "sportName=NOGOMET",                 # SportPlus football marker
    "RASPON GOLOVA",                     # SportPlus goal-range block
    "betting: false",                    # SportPlus suspended matches
    "gg3+",                              # Mozzartbet excluded combo
    "SportIds=388",                      # EVLBet feed
    "Ishod meca",                        # EVLBet offer description
    "esMatches[].odds",                  # Betole odds shape
    "/restapi/offer/ba/sport/S/desk",    # Betole endpoint
    "KI_1",                              # Betole result labels
    "real Admiralbet 1X2 offer",         # the 136 -> double_chance post-mortem
]


@pytest.mark.parametrize("anchor", NARRATIVE_ANCHORS)
def test_hand_written_narrative_anchor_survives(anchor: str):
    """Each anchor is knowledge no generated table can reproduce."""
    assert anchor in _narrative(), (
        f"hand-written narrative lost the anchor {anchor!r}; the generated "
        "table cannot supply it, so this is a real deletion"
    )


# Table headers of the per-book ID maps that used to duplicate the registry.
# If one of these reappears outside the markers, a second hand-maintained
# source of truth has crept back in next to the generated one.
RETIRED_TABLE_HEADERS = [
    "| Source offer |",
    "| Source key |",
    "| Source market |",
    "| Source game |",
    "| Source offer (football",
    "| Pick codes |",
    "| Internal type |",
    "| Bookmaker | Live feed | Mapped markets |",
]


@pytest.mark.parametrize("header", RETIRED_TABLE_HEADERS)
def test_no_hand_maintained_id_table_survives_beside_the_generated_one(header: str):
    assert header not in _narrative(), (
        f"{header!r} is a hand-maintained copy of registry data; the generated "
        "table is the authority and this header must not come back"
    )


def test_generated_table_is_the_authority_and_comes_first():
    """The canonical mapping must precede the hand-written notes."""
    doc = _doc()
    assert doc.index(BEGIN_MARKER) < doc.index(END_MARKER)
    notes = doc.index("## Per-book field notes")
    assert doc.index(BEGIN_MARKER) < notes, (
        "the generated mapping must come before the hand-written field notes so "
        "a reader meets the authority first"
    )
    intro = doc[: doc.index(BEGIN_MARKER)]
    assert "authority" in intro.lower(), (
        "the text before the table must state that the table is authoritative"
    )


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


def test_generated_market_names_are_human_readable_and_carry_the_enum_key():
    """The Market cell must give a human label *and* the MarketType value.

    An operator reads "Over/Under 2.5"; a developer greps
    ``over_under_2_5``. The retired hand-written "Supported Internal Markets"
    table carried the enum values, so dropping them from the generated table
    would have been a silent documentation loss.
    """
    _, block = _split_section(_doc())
    cells = {str(row["market"]) for row in _documented_market_rows(block)}
    for label in ("Full-time 1X2", "Double Chance", "BTTS", "Over/Under 2.5"):
        assert any(c.startswith(f"{label} (") for c in cells), (
            f"market cell lost the human label {label!r}"
        )
    values = {member.value for member in MarketType}

    def enum_key(cell: str) -> str:
        return cell.rsplit("(", 1)[1].rstrip(")").strip("`")

    for cell in cells:
        assert enum_key(cell) in values, (
            f"market cell {cell!r} does not carry a MarketType value"
        )
    # Every registry-backed type must be named, and nothing else invented.
    declared = {value for _b, _m, value, _ids in _mapped_declarations()}
    assert {enum_key(cell) for cell in cells} == declared


def test_generator_never_emits_a_table_row_for_a_dashed_key():
    _, block = _split_section(_doc())
    assert not re.search(r"^\| `_[^`]+` \|", block, flags=re.MULTILINE)
