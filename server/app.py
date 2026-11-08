import asyncio
import logging
import math
import os
import secrets
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config.settings import (
    AUTO_SCAN_LIVE_MINUTES,
    AUTO_SCAN_PREMATCH_MINUTES,
    CORS_ORIGINS,
    MAINTENANCE_ENABLED,
)
from server import api as api_module
from server.api import (
    _deep_link_decisions,
    _deep_link_verifications,
    _load_bookmaker_state,
    _load_cache,
    _load_deep_link_decisions,
    _load_deep_link_verifications,
    _load_history,
    _load_market_state,
    _load_stale_price_state,
    _load_suppressed_candidates,
    _load_suppressed_premises,
    _suppressed_candidates,
    _suppressed_premises,
    router,
)
from server.auth import SCOPES, resolve_api_key
from server.observability import (
    REQUEST_ID_HEADER,
    new_request_id,
    reset_request_id,
    set_request_id,
    valid_request_id,
)
from server.scheduler import maintenance_loop, scan_loop

# Fix Windows ProactorEventLoop policy for Playwright when running via uvicorn/fastapi CLI
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


#: The header both the middleware and the dashboard use for the API key.
X_API_KEY_HEADER = "X-API-Key"


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
    if MAINTENANCE_ENABLED:
        tasks.append(asyncio.create_task(maintenance_loop()))
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


def _json_safe_validation(value: object) -> object:
    """Replace non-finite floats so a 422 can be serialized.

    Pydantic echoes the rejected input in ``RequestValidationError``. Python's
    JSON parser accepts ``1e400``/``NaN``/``Infinity`` as non-finite floats, and
    the default handler then fails while serializing the error itself, turning a
    validation error into a 500. The detail shape is otherwise unchanged.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe_validation(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_validation(item) for item in value]
    return value


async def _validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe_validation(jsonable_encoder(exc.errors()))},
    )


app.add_exception_handler(RequestValidationError, _validation_error_handler)

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
    """Require the configured key on every /api route except health (M1-1).

    One resolver handles the env ``API_KEY`` and the named hashed store, so a
    deployment with both accepts either. The per-route dependency then checks
    the scope: every read needs ``read`` (or ``admin``), and the write routes
    ask for ``scan`` or ``admin`` themselves. This closes the read routes too,
    so an exposed deployment does not leak results, config, bets or history.

    With no bootstrap key and no key record at all the historical local-only
    behaviour remains (the documented default bind is loopback): the API is
    open and the request gets every scope.
    """
    path = request.url.path
    if not path.startswith("/api") or path == "/api/health":
        return await call_next(request)

    env_key = api_module.API_KEY
    store = api_module.api_key_store
    if not env_key and not store.has_any_keys():
        request.state.api_key_id = ""
        request.state.api_key_scopes = set(SCOPES)
        return await call_next(request)

    resolved = resolve_api_key(
        request.headers.get(X_API_KEY_HEADER, ""), env_key=env_key, store=store
    )
    if resolved is None:
        return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
    request.state.api_key_id = resolved.key_id
    request.state.api_key_scopes = set(resolved.scopes)
    if request.method in {"GET", "HEAD"} and not resolved.scopes & {"read", "admin"}:
        return JSONResponse(
            {"detail": "This API key lacks the 'read' scope"}, status_code=403
        )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    """Add the browser-side hardening headers the dashboard can live with.

    Defined last so it wraps the guards too: a 401 or a refused cross-origin
    write carries the same headers as a normal page. Every request gets a fresh
    nonce, and the dashboard's two script tags are stamped with it by
    `serve_dashboard`, so `script-src` no longer needs `'unsafe-inline'`.

    `style-src` also has no `'unsafe-inline'`: the dashboard writes colours and
    progress widths through the CSSOM (`element.style.setProperty`), which CSP
    does not treat as an inline style attribute. The only external stylesheet is
    the Google Fonts link; no inline `<style>` block is shipped.
    """
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'",
    )
    return response


# Include API routes
app.include_router(router, prefix="/api")


request_logger = logging.getLogger("server.request")


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """Correlate every log line with the request that caused it.

    An incoming `X-Request-ID` is trusted only when it is short and log-safe;
    otherwise a fresh id is generated, so a caller cannot forge extra log
    fields. The id is returned on the response and is available to endpoints as
    `request.state.request_id`. Defined last so it wraps the guards: a 401 or a
    refused cross-origin write still gets an id and a completion log.
    """
    incoming = request.headers.get(REQUEST_ID_HEADER)
    request_id = incoming if valid_request_id(incoming) else new_request_id()
    token = set_request_id(request_id)
    request.state.request_id = request_id
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        request_logger.debug(
            "request complete",
            extra={
                "request_method": request.method,
                "request_path": request.url.path,
                "status_code": status_code,
                "duration_seconds": round(time.perf_counter() - started, 4),
            },
        )
        reset_request_id(token)


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
    _load_stale_price_state()
    _suppressed_candidates.update(_load_suppressed_candidates())
    _suppressed_premises.update(_load_suppressed_premises())

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(os.path.join(FRONTEND_DIR, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
if os.path.exists(os.path.join(FRONTEND_DIR, "js")):
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def serve_manifest() -> FileResponse:
    """Serve the PWA manifest from the frontend directory."""
    return FileResponse(
        os.path.join(FRONTEND_DIR, "manifest.webmanifest"),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js", include_in_schema=False)
async def serve_service_worker() -> FileResponse:
    """Serve the service worker at the scope root; it is not under /js."""
    return FileResponse(
        os.path.join(FRONTEND_DIR, "sw.js"),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/", include_in_schema=False)
async def serve_dashboard(request: Request):
    """Serve the dashboard with this request's CSP nonce on its script tags."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_path):
        return {"message": "Surebet Scanner API running. Frontend index.html not found."}
    nonce = getattr(request.state, "csp_nonce", "") or secrets.token_urlsafe(16)
    with open(index_path, encoding="utf-8") as file:
        html = file.read()
    return HTMLResponse(
        html.replace("__CSP_NONCE__", nonce),
        headers={"Cache-Control": "no-store"},
    )
