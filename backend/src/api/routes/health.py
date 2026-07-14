"""Health/readiness routes (spec_v002 Section 16.3).

`/health` is pure liveness — no dependency access, always 200. `/ready`
attempts a database connectivity check but never raises (`check_connectivity`
catches and sanitizes everything), so this route is safe to test without a
real database and never exposes credentials or unsanitized errors.
"""

from __future__ import annotations

from db.session import check_connectivity
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    db_ok, db_error = check_connectivity()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": {"ok": db_ok, "error": db_error},
    }
