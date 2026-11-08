"""M3-1 stage 1: candidate scoring lives in its own pure module.

The pair walk is run in a scan worker thread, so its scoring half must not reach
back into the server module that owns routes, caches and runtime state. These
tests pin the extraction: one definition, owned by the scoring module and
imported by ``server.api``, with no import back into it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from server import api, candidate_scoring

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "server" / "candidate_scoring.py").read_text(encoding="utf-8")


def test_the_scoring_module_never_imports_the_server_module():
    """The pure half must be importable without the routes and runtime state."""
    tree = ast.parse(SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(
        name == "server.api" or name.startswith("server.api.")
        for name in imported
    ), imported


def test_the_server_reuses_the_one_scoring_definition():
    """No second copy: api's name must be the scoring module's object."""
    for name in (
        "candidate_id",
        "canonical_pair_key",
        "kickoff_bucket",
        "kickoff_delta_minutes",
        "match_event_ref",
        "match_side_key",
        "pair_priority",
        "team_similarity",
    ):
        assert getattr(api, name) is getattr(candidate_scoring, name), name
        assert not hasattr(api, f"_{name}"), f"a private copy of {name} is back"
