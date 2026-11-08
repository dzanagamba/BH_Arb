"""The JSON-store layer: one atomic write, one forgiving read (M3-1 stage 3).

The layer owns file I/O only. These tests pin the two promises every caller
relies on: a document is replaced whole (a failure leaves the old one), and a
missing or malformed document reads as "no document" rather than an exception.
"""

from __future__ import annotations

import json
from pathlib import Path

from server.json_store import atomic_write_json, read_json


def test_a_compact_write_has_no_layout_and_round_trips(tmp_path: Path):
    path = tmp_path / "state.json"

    atomic_write_json(str(path), {"b": 2, "a": [1, 2]}, "state", indent=None)

    text = path.read_text(encoding="utf-8")
    assert "\n" not in text
    assert json.loads(text) == {"b": 2, "a": [1, 2]}


def test_the_default_write_stays_human_readable(tmp_path: Path):
    path = tmp_path / "state.json"

    atomic_write_json(str(path), {"a": 1}, "state")

    assert "\n" in path.read_text(encoding="utf-8")


def test_a_replacement_is_whole_and_leaves_no_temp_file(tmp_path: Path):
    path = tmp_path / "state.json"
    atomic_write_json(str(path), {"version": 1}, "state")

    atomic_write_json(str(path), {"version": 2}, "state")

    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 2}
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]


def test_a_failed_write_keeps_the_previous_document(tmp_path: Path):
    path = tmp_path / "state.json"
    atomic_write_json(str(path), {"version": 1}, "state")

    class Unserialisable:
        def __str__(self) -> str:
            raise RuntimeError("no string form")

    try:
        atomic_write_json(str(path), {"bad": Unserialisable()}, "state")
    except RuntimeError:
        pass
    else:  # pragma: no cover - the payload is deliberately unserialisable
        raise AssertionError("the write should have failed")

    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]


def test_a_missing_or_malformed_document_reads_as_none(tmp_path: Path):
    missing = tmp_path / "missing.json"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")

    assert read_json(str(missing)) is None
    assert read_json(str(malformed)) is None


def test_read_json_returns_the_document_and_leaves_shape_to_the_caller(
    tmp_path: Path,
):
    path = tmp_path / "state.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    # Shape validation belongs to the store's owner, not to this layer.
    assert read_json(str(path)) == [1, 2, 3]
