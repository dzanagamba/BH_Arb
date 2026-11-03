import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config.settings import (
    API_KEY,
    AUTO_SCAN_LIVE_MINUTES,
    AUTO_SCAN_PREMATCH_MINUTES,
    CORS_ORIGINS,
)
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

# Same-origin by default: the dashboard is served by this process. A separate
# frontend must be listed explicitly in CORS_ORIGINS; a wildcard is never used.
_cors_origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

@app.middleware("http")
async def same_origin_guard(request, call_next):
    """Refuse a cross-origin browser write even when no API key is configured.

    A form POST is not subject to CORS, so the key guard alone does not stop a
    malicious page from triggering a scan or a toggle. Requests without an
    Origin header (curl, a scheduled task) are unchanged.
    """
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def api_key_guard(request, call_next):
    """Require the configured API key on every /api route except health.

    State-changing routes also check the key through their dependency; this
    guard closes the read routes too, so an exposed deployment does not leak
    results, candidates or history.
    """
    if (
        API_KEY
        and request.url.path.startswith("/api")
        and request.url.path != "/api/health"
        and request.headers.get("X-API-Key") != API_KEY
    ):
        return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
    return await call_next(request)


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
