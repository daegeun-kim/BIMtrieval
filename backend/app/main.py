"""Backend application entry point.

Authoritative dev command, from `backend/`:

    poetry run uvicorn app.main:app --reload

`app` is the same FastAPI application produced by the application factory in
`app.api.app` (public contract: POST /api/query plus /health and /ready).
"""

from __future__ import annotations

from app.api.app import app, create_app

__all__ = ["app", "create_app"]
