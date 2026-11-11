"""SR8-4: `record_scan.py` restores persisted state before it scans.

WHAT THESE TESTS PROVE
----------------------
The 2026-11-11 test scan could not use `scripts/record_scan.py` directly: a
fresh process runs `api.run_scan` with empty diagnostic globals, so
`_finish_scan_cost` rewrote `cache/scan_cost.json` with only the new rows and
wiped the restored history. The driver worked around it by calling
`server.app._restore_state()` itself.

These tests run the script's own entry points with the real restore and a
stubbed scan:

* a seeded `cache/scan_cost.json` is in memory before the scan starts and its
  history row survives the scan's own `_finish_scan_cost` write;
* one invocation with several modes restores once, scans in order, and writes
  one `<mode>-scan.json` per mode.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
Nothing here starts a real scrape; the adapters never run and no traffic is
sent. The scan itself is covered by the adapter, matcher and e2e suites.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import record_scan
from server import api

OLD_ROW = {
    "mode": "prematch",
    "scan_time": "2026-11-01T09:00:00",
    "books": {"mozzartbet": {"outcome": "success"}},
    "totals": {"books": 1, "success": 1, "matches": 7},
}


def _seed_scan_cost() -> None:
    """Write a prior scan-cost history through the documented JSON shape."""
    Path(api._SCAN_COST_FILE).write_text(
        json.dumps({"last": {"prematch": OLD_ROW, "live": {}}, "history": [OLD_ROW]}),
        encoding="utf-8",
    )


def _empty_feed_state(monkeypatch) -> None:
    """Clear what another test may have left in the feed globals."""
    monkeypatch.setattr(api, "cached_matches", [])
    monkeypatch.setattr(api, "cached_surebets", [])
    monkeypatch.setattr(api, "cached_match_groups_report", [])
    monkeypatch.setattr(api, "cached_per_bookie", {})


def test_a_seeded_scan_cost_row_survives_the_script(monkeypatch):
    _seed_scan_cost()
    _empty_feed_state(monkeypatch)
    history_at_scan_start: list[int] = []

    async def fake_run_scan(mode: str) -> None:
        # The restore ran before the scan, so the seeded row is already here.
        history_at_scan_start.append(len(api._scan_cost_history))
        # A real scan ends here: append its row and persist the store.
        api._finish_scan_cost(mode, datetime.now(UTC), {})

    monkeypatch.setattr(api, "run_scan", fake_run_scan)

    report = asyncio.run(record_scan.run("prematch"))

    assert report["mode"] == "prematch"
    assert report["matches"] == 0
    assert history_at_scan_start == [1]
    assert api._scan_cost_history[0]["books"] == {}
    assert api._scan_cost_history[1] == OLD_ROW
    saved = json.loads(Path(api._SCAN_COST_FILE).read_text(encoding="utf-8"))
    assert OLD_ROW in saved["history"]
    assert len(saved["history"]) == 2


def test_several_modes_restore_once_and_write_one_report_each(monkeypatch, tmp_path):
    _empty_feed_state(monkeypatch)
    events: list[str] = []

    async def fake_run_scan(mode: str) -> None:
        events.append(mode)

    monkeypatch.setattr(record_scan, "_restore_state", lambda: events.append("restore"))
    monkeypatch.setattr(api, "run_scan", fake_run_scan)

    out = tmp_path / "scan"
    assert record_scan.main(["prematch", "live", "--out", str(out)]) == 0

    assert events == ["restore", "prematch", "live"]
    assert sorted(path.name for path in out.iterdir()) == [
        "live-scan.json",
        "prematch-scan.json",
    ]
    for mode in ("prematch", "live"):
        report = json.loads(
            (out / f"{mode}-scan.json").read_text(encoding="utf-8")
        )
        assert report["mode"] == mode
        assert report["matches"] == 0
        assert report["bookmakers"] == {}
