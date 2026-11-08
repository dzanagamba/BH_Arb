"""SR3-4: a forced browser failure writes a real trace and screenshot.

Opt-in with the other Chromium checks (``BH_ARB_TEST_BROWSER=1``). The session
is the production ``browser_session()``: tracing starts with the context, the
exception is raised through it, and the capture stops the trace before the
private pool closes the context.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import pytest

from scrapers import forensics
from scrapers.base import browser_session

pytestmark = pytest.mark.skipif(
    os.getenv("BH_ARB_TEST_BROWSER") != "1",
    reason="needs Chromium; set BH_ARB_TEST_BROWSER=1 to run the forensics check",
)


def test_a_forced_failure_writes_a_trace_and_a_screenshot(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.setattr(forensics, "FORENSICS_DIR", tmp_path)
    monkeypatch.setattr(forensics, "FORENSICS_ENABLED", True)

    async def scenario():
        with pytest.raises(RuntimeError, match="forced"):
            async with browser_session("mbet") as context:
                page = await context.new_page()
                await page.goto("data:text/html,<h1>forced failure</h1>")
                raise RuntimeError("forced")
        return forensics.take_artefacts()

    with caplog.at_level(logging.WARNING, logger="scrapers.forensics"):
        artefacts = asyncio.run(scenario())

    traces = list(tmp_path.rglob("trace.zip"))
    screenshots = list(tmp_path.rglob("screenshot.png"))
    assert len(traces) == 1
    assert len(screenshots) == 1
    assert traces[0].stat().st_size > 0
    assert "mbet" in traces[0].parts
    assert "mbet" in caplog.text
    assert str(traces[0]) in caplog.text

    assert set(artefacts) == {"trace", "screenshot"}
    assert Path(artefacts["trace"]) == traces[0]
