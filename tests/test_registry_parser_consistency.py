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


# --- registry <-> parser reachability ---------------------------------------


def _parser_probes() -> dict[str, Any]:
    """Map each bookmaker to *its own* parser module's registry-resolution call.

    Every entry below is the function that module's market parsing actually
    invokes; the refactor that lifted them to module scope is behaviour
    preserving and covered by the rest of the suite.  Books whose resolver was
    already a module-level ``_registered_spec`` are used as-is.
    """
    from scrapers.betole import betole_registered_spec
    from scrapers.common import nsoft_registered_spec
    from scrapers.evlbet import evlbet_registered_spec
    from scrapers.mbet import _registered_spec as mbet_spec
    from scrapers.mozzartbet import _registered_spec as mozzartbet_spec
    from scrapers.premier_kladionica import _registered_spec as premier_spec
    from scrapers.sportplus import _registered_spec as sportplus_spec
    from scrapers.wwin import wwin_registered_spec

    def adapt(fn: Any) -> Any:
        """Normalise a (mode, source_id, market_type, line=) resolver."""

        def resolve(mode: str, source_id: Any, market_type: Any, line: Any) -> Any:
            return fn(mode, source_id, market_type, line=line)

        return resolve

    def nsoft(bookmaker: str) -> Any:
        """NSoft resolves by ID + threshold, with no market type argument.

        One ID pair is shared by every Over/Under line, so the line is part of
        the lookup key rather than the market type.
        """

        def resolve(mode: str, source_id: Any, market_type: Any, line: Any) -> Any:
            return nsoft_registered_spec(bookmaker, mode, source_id, sbv=line)

        return resolve

    def mozzart(mode: str, source_id: Any, market_type: Any, line: Any) -> Any:
        # mozzartbet's resolver takes the bookmaker explicitly: the prematch and
        # live builders share it and pass the id they were called with.
        return mozzartbet_spec("mozzartbet", mode, source_id, market_type, line=line)

    return {
        "betole": adapt(betole_registered_spec),
        "evlbet": adapt(evlbet_registered_spec),
        "mbet": adapt(mbet_spec),
        "premier_kladionica": adapt(premier_spec),
        "sportplus": adapt(sportplus_spec),
        "wwin": adapt(wwin_registered_spec),
        "mozzartbet": mozzart,
        "mdshop": nsoft("mdshop"),
        "admiralbet": nsoft("admiralbet"),
    }


def test_every_bookmaker_has_a_parser_resolution_probe():
    """A new registry book must come with a probe, or this file goes blind."""
    from config.settings import BOOKMAKERS

    probes = _parser_probes()
    for bid in BOOKMAKERS:
        assert bid in probes, f"{bid} has no parser resolution probe"


def _registry_declarations() -> list[tuple[str, str, MarketType, tuple[str, ...], Any]]:
    """One tuple per registry market declaration, with its resolved spec."""
    registry = MarketRegistry()
    rows: list[tuple[str, str, MarketType, tuple[str, ...], Any]] = []
    for book, mode, market_type in _iter_market_types(_registry_json()):
        for spec in _declared(registry, book, mode, market_type):
            rows.append(
                (
                    book,
                    mode,
                    market_type,
                    tuple(sorted(str(i) for i in spec.ids)),
                    spec,
                )
            )
    return rows


_DECLARATIONS = _registry_declarations()
_DECLARATION_IDS = [row[:4] for row in _DECLARATIONS]


@pytest.mark.parametrize(("book", "mode", "market_type", "ids"), _DECLARATION_IDS)
def test_registered_ids_resolve_through_their_own_books_parser(
    book: str, mode: str, market_type: MarketType, ids: tuple[str, ...]
):
    """Every registered source ID is reachable by that book's parser.

    WHAT THIS PROVES: for each book/mode/market declaration in the registry,
    asking that bookmaker's parser module to resolve each of its source IDs
    returns a MarketSpec instead of None, and that spec is the one the registry
    declares (type, line, labels, min legs, settlement).  Equivalently: no
    registry entry is an orphan that only the registry knows about.

    WHAT THIS DOES NOT PROVE: that a real bookmaker feed emits these IDs, that
    the surrounding payload shape is right, or that the resulting market is
    economically usable.  It is a wiring check on IDs, not end-to-end market
    coverage; captured-payload coverage is Task 11's job.
    """
    from engine.market_registry import unmapped_markets

    before = dict(unmapped_markets)
    probes = _parser_probes()
    assert book in probes, f"{book} has no parser resolution probe"
    resolve = probes[book]

    for raw_id in ids:
        # The parser sees the registry's own id type (int for NSoft/Mozzartbet,
        # str for the name-keyed books); the doc only has the string form.
        candidates: list[Any] = [raw_id]
        try:
            candidates.append(int(raw_id))
        except ValueError:
            pass
        spec = None
        for candidate in candidates:
            spec = resolve(mode, candidate, market_type, _line_of(book, mode, market_type))
            if spec is not None:
                break
        assert spec is not None, (
            f"{book} parser cannot resolve registered {mode}/{market_type.value} "
            f"id {raw_id!r}: reachable registry lookup is required"
        )
        assert spec.market_type is market_type
        assert str(spec.bookmaker) == book
        assert str(spec.mode) == mode

    assert dict(unmapped_markets) == before, (
        "resolving registered IDs must not record unmapped-market diagnostics"
    )


def _line_of(book: str, mode: str, market_type: MarketType) -> Any:
    """The declared line for a book/mode/market, or None."""
    registry = MarketRegistry()
    for spec in _declared(registry, book, mode, market_type):
        return spec.line
    return None


def test_parser_resolution_returns_the_declared_spec_not_just_any_spec():
    """A resolver must return the declared labels/min legs/settlement too.

    Without this, a parser resolving an ID to a *different* market's spec (the
    NSoft 136 bug shape) would still pass the reachability test above.
    """
    probes = _parser_probes()
    mismatches: list[str] = []
    for book, mode, market_type, ids, spec in _DECLARATIONS:
        resolve = probes[book]
        line = spec.line
        for raw_id in ids:
            candidates: list[Any] = [raw_id]
            try:
                candidates.append(int(raw_id))
            except ValueError:
                pass
            for candidate in candidates:
                got = resolve(mode, candidate, market_type, line)
                if got is None:
                    continue
                if (
                    got.market_type is not market_type
                    or got.labels != spec.labels
                    or got.min_legs != spec.min_legs
                    or got.line != spec.line
                    or got.settlement != spec.settlement
                ):
                    mismatches.append(f"{book}/{mode}/{market_type.value}/{raw_id}")
                break
    assert not mismatches, f"parser resolved a different spec than declared: {mismatches}"


# --- mapped and excluded must not overlap ----------------------------------


def test_mapped_and_excluded_ids_are_disjoint():
    """An ID cannot be both mapped and deliberately unmapped.

    ``_excluded`` suppresses the unmapped-market diagnostic; it is not itself a
    rejection mechanism, so a registry that both maps and excludes an ID would
    silently make the mapping untestable and the exclusion meaningless.
    """
    registry = MarketRegistry()
    data = _registry_json()
    overlaps: list[str] = []
    for book, mode, market_type, ids, _spec in _DECLARATIONS:
        for source_id in ids:
            if registry.is_excluded(book, mode, source_id):
                overlaps.append(f"{book}/{mode}/{market_type.value}/{source_id}")
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
    registry_types = {
        mt.value for book, _mode, mt, _ids, _spec in _registry_declarations()
    }
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
    assert {enum_key(cell) for cell in cells} == {
        mt.value for _b, _m, mt, _i, _s in _registry_declarations()
    }


def test_generator_never_emits_a_table_row_for_a_dashed_key():
    _, block = _split_section(_doc())
    assert not re.search(r"^\| `_[^`]+` \|", block, flags=re.MULTILINE)
