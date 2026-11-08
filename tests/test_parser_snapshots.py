"""SR4-6: snapshots of the normalised parser output.

WHAT THESE TESTS PROVE
----------------------
The contract suite (N2-6) records which ids, labels and key paths a fixture
depends on. This suite records what the real parser *emits* from every dated
capture: the market types, settlement/period and price rows, in order. A
snapshot diff therefore shows the exact normalised change a parser edit makes,
instead of leaving it to a reviewer to imagine it from the code.

Raw payloads are deliberately not snapshotted. The fixtures already pin the raw
shape (SR4-2/SR4-3) and the contract pins the ids/labels; a raw snapshot would
only duplicate those and churn on every capture.

BOOK IDs AND TIMESTAMPS ARE NOT IN THE SNAPSHOT
-----------------------------------------------
Only ``market_type``, ``settlement``, ``period`` and the ``label``/``value``
rows are written. Source ids, source context, outcome ids and update times are
book-specific identity data; snapshotting them would make every capture look
like a parser change.

UPDATING A SNAPSHOT
-------------------
``pytest --snapshot-update`` rewrites the snapshot, but it is a human action.
The commit that updates one must say why the normalised output changed (a fixed
parser, a re-captured feed or an intentional market change). CI never runs
``--snapshot-update``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_market_fixtures import FIXTURES, _run_parser

SNAPSHOT_CASES = [
    path
    for path in FIXTURES
    if json.loads(path.read_text(encoding="utf-8")).get("expected_markets")
]


def _normalised(markets: list) -> list[dict[str, Any]]:
    """The identity-bearing, value-only view of a parser's output."""
    return [
        {
            "market_type": market.market_type.value,
            "settlement": market.settlement,
            "period": market.period,
            "odds": [
                {"label": odd.label, "value": odd.value} for odd in market.odds
            ],
        }
        for market in markets
    ]


@pytest.mark.parametrize(
    "fixture", SNAPSHOT_CASES, ids=[path.stem for path in SNAPSHOT_CASES]
)
def test_the_normalised_parser_output_matches_its_snapshot(fixture: Path, snapshot):
    data = json.loads(fixture.read_text(encoding="utf-8"))

    normalised = _normalised(_run_parser(data))

    assert normalised == snapshot


def test_every_fixture_with_expected_markets_has_a_snapshot_case():
    snapshotted = {path.stem for path in SNAPSHOT_CASES}
    declared = {
        path.stem
        for path in FIXTURES
        if json.loads(path.read_text(encoding="utf-8")).get("expected_markets")
    }

    assert snapshotted == declared
