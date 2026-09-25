import asyncio
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.api import (
    _load_bookmaker_state,
    _load_cache,
    _load_history,
    _load_market_state,
    _load_suppressed_candidates,
    _suppressed_candidates,
    router,
)

# Fix Windows ProactorEventLoop policy for Playwright when running via uvicorn/fastapi CLI
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(
    title="Surebet Scanner",
    description="Arbitrage betting detector for the Bosnian market",
    version="1.0.0",
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


@app.on_event("startup")
async def on_startup() -> None:
    """Restore last scan results, runtime toggles, and scan history on boot."""
    _load_cache()
    _load_bookmaker_state()
    _load_market_state()
    _load_history()
    _suppressed_candidates.update(_load_suppressed_candidates())

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


@app.get("/demos", include_in_schema=False)
async def serve_demos():
    """Serve the UI directions demo gallery."""
    demos_path = os.path.join(FRONTEND_DIR, "demos", "index.html")
    if os.path.exists(demos_path):
        return FileResponse(demos_path)
    return {"message": "Demos gallery not found."}


@app.get("/demos/sportscast", include_in_schema=False)
async def serve_demo_sportscast():
    """Serve the refined Sportscast Scoreboard demo."""
    demo_path = os.path.join(FRONTEND_DIR, "demos", "sportscast.html")
    if os.path.exists(demo_path):
        return FileResponse(demo_path)
    return {"message": "Sportscast demo not found."}
