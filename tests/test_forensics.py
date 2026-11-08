"""SR3-4: failure artefacts, retention caps and the artefact log fragment.

The capture helper is pinned with a fake context: the trace and screenshot
files are written, the paths are returned and registered for the scan note, and
the prune step enforces both the age and the size budget without removing the
newest file.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from scrapers import forensics


class _Tracing:
    def __init__(self) -> None:
        self.started = False
        self.stopped_with: str | None = None

    async def start(self, **kwargs: Any) -> None:
        self.started = True

    async def stop(self, *, path: str | None = None) -> None:
        self.stopped_with = path
        if path:
            Path(path).write_bytes(b"trace")


class _Page:
    def __init__(self) -> None:
        self.path: str | None = None

    async def screenshot(self, *, path: str) -> None:
        self.path = path
        Path(path).write_bytes(b"png")


class _Context:
    def __init__(self) -> None:
        self.tracing = _Tracing()
        self.pages = [_Page()]


def test_a_failure_writes_a_trace_and_a_screenshot(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(forensics, "FORENSICS_ENABLED", True)
    context = _Context()

    async def scenario():
        paths = await forensics.capture_failure(
            context, context.pages[0], "mbet", root=tmp_path
        )
        return paths, forensics.take_artefacts(), forensics.take_artefacts()

    paths, taken, again = asyncio.run(scenario())

    assert set(paths) == {"trace", "screenshot"}
    assert Path(paths["trace"]).read_bytes() == b"trace"
    assert Path(paths["screenshot"]).read_bytes() == b"png"
    assert "mbet" in Path(paths["trace"]).parts
    assert taken == paths
    assert again == {}


def test_a_disabled_capture_writes_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(forensics, "FORENSICS_ENABLED", False)

    paths = asyncio.run(
        forensics.capture_failure(_Context(), None, "mbet", root=tmp_path)
    )

    assert paths == {}
    assert list(tmp_path.rglob("*")) == []


def test_prune_removes_old_files_and_then_the_oldest_until_the_budget(tmp_path: Path):
    now = time.time()
    book = tmp_path / "mbet" / "scan"
    book.mkdir(parents=True)
    old = book / "old.zip"
    middle = book / "middle.zip"
    newest = book / "newest.zip"
    for path, size, age_days in (
        (old, 10, 10),
        (middle, 10, 1),
        (newest, 10, 0),
    ):
        path.write_bytes(b"x" * size)
        stamp = now - age_days * 86400
        os.utime(path, (stamp, stamp))

    removed = forensics.prune(tmp_path, max_bytes=15, max_age_days=7, now=now)

    assert str(old) in removed
    assert not old.exists()
    assert newest.exists()
    assert sum(path.stat().st_size for path in tmp_path.rglob("*.zip")) <= 15


def test_prune_never_removes_the_last_file_even_over_budget(tmp_path: Path):
    only = tmp_path / "mbet" / "only.zip"
    only.parent.mkdir(parents=True)
    only.write_bytes(b"x" * 100)

    removed = forensics.prune(tmp_path, max_bytes=1, max_age_days=7)

    assert removed == []
    assert only.exists()


def test_the_artefact_summary_names_every_path():
    summary = forensics.artefact_summary(
        {"trace": "/cache/forensics/mbet/x/trace.zip", "screenshot": "/cache/forensics/mbet/x/screenshot.png"}
    )

    assert summary.startswith(" | forensics: ")
    assert "trace=" in summary
    assert "screenshot=" in summary
    assert forensics.artefact_summary({}) == ""
