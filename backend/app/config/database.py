"""Backend-owned database configuration primitives.

Intentionally independent of the ingestion project (Task 09): the backend must
not import `bim_rag`. This module re-implements only the small, stable pieces
the query backend needs — the read-only `db_url` loader, credential
sanitization, and the query-embedding thread limit. The values mirror the
ingestion runtime's behavior on purpose (shared database contract), but the
code is owned here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Same conservative thread ceiling the ingestion embedding runtime used after
# the Task 03 CUDA stability incident. The backend embeds one query at a time,
# but keeps the same cap so a shared GPU workload can't saturate every core.
THREAD_LIMIT = 4

# app/config/database.py -> config -> app -> backend -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"

_URL_CRED_RE = re.compile(
    r"(postgresql(?:\+\w+)?://)([^:@/]+:[^@]+@)",
    re.IGNORECASE,
)


def get_db_url() -> str:
    """Load the shared `db_url` from the repository `.env` without exposing it.

    Backend fallback used only when the dedicated read-only `DATABASE_URL` is
    not configured. Never prints or logs the value. Raises if missing.
    """
    load_dotenv(_ENV_FILE, override=False)
    url = os.environ.get("db_url") or os.environ.get("DB_URL")
    if not url:
        raise RuntimeError(
            "db_url not found in .env. "
            "Add `db_url=postgresql://...` to the .env file at the repository root, "
            "or set DATABASE_URL to the read-only backend role DSN."
        )
    return url


def sanitize_db_error(msg: str) -> str:
    """Remove embedded DSN credentials from an error string before logging."""
    return _URL_CRED_RE.sub(r"\1<credentials>@", msg)
