"""FastAPI application factory (spec_v002 Section 16).

The authoritative dev command, from `backend/`:

    poetry run uvicorn app.main:app --reload

The public frontend contract is POST /api/query plus /health and /ready.
Any future low-level dev/testing endpoints (spec_v002 Section 16, opening
sentence) should be added under a clearly separate prefix, not merged into
the public surface.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, models, query
from app.config import trace
from app.config.settings import get_settings


async def _request_records(request: Request, call_next):
    """Establish the request id that [SQL]/[RAG] statement lines correlate with,
    and emit one bounded API status record ONLY for HTTP 400–599 (task15 §1).

    Successful 2xx, redirect 3xx, and 304 responses print nothing — with or
    without BIM_RAG_TRACE. Logs the route *template* rather than the raw URL, so
    query strings that may contain user data never reach the terminal; request
    bodies, chat history, headers, credentials, filesystem paths, and exception
    internals are never logged.
    """
    request_id = trace.new_request_id()
    started = time.perf_counter()

    def route_path() -> str:
        # Resolved lazily: the route template is only populated after routing.
        return getattr(request.scope.get("route"), "path", None) or "(unmatched)"

    with trace.request_context(request_id):
        try:
            response = await call_next(request)
        except Exception:
            # An unhandled crash still yields one bounded record — status only,
            # never the exception detail — and then propagates unchanged.
            trace.emit_api_error_record(
                request_id=request_id,
                method=request.method,
                route=route_path(),
                status=500,
                elapsed_s=time.perf_counter() - started,
            )
            raise
        if 400 <= response.status_code <= 599:
            trace.emit_api_error_record(
                request_id=request_id,
                method=request.method,
                route=route_path(),
                status=response.status_code,
                elapsed_s=time.perf_counter() - started,
            )
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    # Successful API calls must print nothing (task15 §1) — that includes
    # uvicorn's own per-request access lines ("GET /health 200 OK"). Errors stay
    # visible through the bounded [API error] records the middleware emits.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    app = FastAPI(title="BIM RAG Query API", version="0.1.0")
    app.middleware("http")(_request_records)
    # Explicit local-frontend allowlist (spec_v006 §10.5). No wildcard origin,
    # and credentials are disabled — the frontend carries no cookies/auth.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(query.router)
    # Narrow read-only viewer contracts for the frontend (spec_v006 §10; Task 10).
    app.include_router(models.router)
    # Lower-level endpoints stay development-only (spec_v005 §15).
    if settings.enable_dev_endpoints:
        from app.api.routes import dev

        app.include_router(dev.router)
    return app


app = create_app()
