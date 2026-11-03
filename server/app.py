import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import AUTO_SCAN_LIVE_MINUTES, AUTO_SCAN_PREMATCH_MINUTES
from server.api import (
    _deep_link_decisions,
    _deep_link_verifications,
    _load_bookmaker_state,
    _load_cache,
    _load_deep_link_decisions,
    _load_deep_link_verifications,
    _load_history,
    _load_market_state,
    _load_suppressed_candidates,
    _load_suppressed_premises,
    _suppressed_candidates,
    _suppressed_premises,
    router,
)
from server.scheduler import scan_loop

# Fix Windows ProactorEventLoop policy for Playwright when running via uvicorn/fastapi CLI
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Restore state, start any scheduled feeds, and stop them on shutdown."""
    _restore_state()
    tasks: list[asyncio.Task] = []
    for mode, minutes in (
        ("prematch", AUTO_SCAN_PREMATCH_MINUTES),
        ("live", AUTO_SCAN_LIVE_MINUTES),
    ):
        if minutes > 0:
            tasks.append(asyncio.create_task(scan_loop(mode, minutes)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Surebet Scanner",
    description="Arbitrage betting detector for the Bosnian market",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow any origin for local use (allow_credentials must be False when allow_origins=["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")


def _restore_state() -> None:
    """Load every persisted store back into memory."""
    # Proven deep links first: `_load_cache` re-stamps the restored matches
    # with them, so without them every group reads `link_unverified` until the
    # next on-demand check.
    _deep_link_verifications.update(_load_deep_link_verifications())
    # And which events have already been decided, so a restart does not restart
    # a link sweep from the book's first event.
    _deep_link_decisions.update(_load_deep_link_decisions())
    _load_cache()
    _load_bookmaker_state()
    _load_market_state()
    _load_history()
    _suppressed_candidates.update(_load_suppressed_candidates())
    _suppressed_premises.update(_load_suppressed_premises())

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(os.path.join(FRONTEND_DIR, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
if os.path.exists(os.path.join(FRONTEND_DIR, "js")):
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Surebet Scanner API running. Frontend index.html not found."}
