"""FastAPI application factory (spec_v002 Section 16).

Run for manual dev smoke-checks with (from repo root):

    PYTHONPATH=backend/src uvicorn api.app:app --reload

The public frontend contract is POST /api/query plus /health and /ready.
Any future low-level dev/testing endpoints (spec_v002 Section 16, opening
sentence) should be added under a clearly separate prefix, not merged into
the public surface.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes import health, query
from config.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="BIM RAG Query API", version="0.1.0")
    app.include_router(health.router)
    app.include_router(query.router)
    # Lower-level endpoints stay development-only (spec_v005 §15).
    if get_settings().enable_dev_endpoints:
        from api.routes import dev

        app.include_router(dev.router)
    return app


app = create_app()
