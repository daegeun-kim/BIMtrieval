"""FastAPI application factory (spec_v002 Section 16).

The authoritative dev command, from `backend/`:

    poetry run uvicorn app.main:app --reload

The public frontend contract is POST /api/query plus /health and /ready.
Any future low-level dev/testing endpoints (spec_v002 Section 16, opening
sentence) should be added under a clearly separate prefix, not merged into
the public surface.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, models, query
from app.config.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="BIM RAG Query API", version="0.1.0")
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
