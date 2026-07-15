"""Lazy SQLAlchemy engine/session management for the query backend.

No engine is created at import time. `check_connectivity()` is the only
function that opens a connection, and it always catches/sanitizes failures
rather than raising — this is what backs the `/ready` health endpoint, which
must respond even when the database is unreachable (spec_v002 Section 16.3,
tasks/task04.md required verification: "FastAPI health tests pass without
database or OpenAI access").
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config.database import sanitize_db_error
from app.config.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.get_database_url(),
        echo=False,
        connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a Session bound to the lazily-created engine."""
    with Session(get_engine()) as session:
        yield session


def check_connectivity(timeout_s: float = 3.0) -> tuple[bool, str | None]:
    """Attempt a single `SELECT 1`. Never raises.

    Returns (ok, sanitized_error). `sanitized_error` is None on success.
    """
    try:
        engine = create_engine(
            get_settings().get_database_url(),
            echo=False,
            connect_args={"connect_timeout": int(timeout_s)},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, None
    except Exception as exc:  # noqa: BLE001 - readiness probe must never raise
        return False, sanitize_db_error(str(exc))
