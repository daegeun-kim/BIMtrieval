"""Lazy SQLAlchemy engine/session management for the query backend.

No engine is created at import time. `check_connectivity()` is the only
function that opens a connection, and it always catches/sanitizes failures
rather than raising — this is what backs the `/ready` health endpoint, which
must respond even when the database is unreachable (spec_v002 Section 16.3,
tasks/task04.md required verification: "FastAPI health tests pass without
database or OpenAI access").
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from app.config.database import sanitize_db_error
from app.config.settings import get_settings

_log = logging.getLogger("bim_rag_backend.db")

#: pgvector 0.8 index-scan settings applied to every backend connection.
#:
#: `rag_documents` carries ONE global HNSW index across every imported model,
#: but the RAG path always searches a filtered slice of it (source_model_id +
#: source_kind + document_type + embedding model/dim) — for the corpus this was
#: measured on, ~2.7% of the table. With `hnsw.iterative_scan` off, an HNSW scan
#: collects `ef_search` neighbours GLOBALLY and only then applies the WHERE
#: clause, so a filtered search can return fewer rows than exist — measured
#: returning ZERO candidates for top_k<10 against 6,989 matching documents,
#: while the same query at top_k=10 returned the correct ten because the planner
#: happened to choose a sequential scan instead.
#:
#: Silently retrieving nothing is the worst possible failure for this pipeline:
#: it looks like "the model contains no such objects". `strict_order` keeps exact
#: distance ordering (which `per_kind_rank` and the similarity thresholds both
#: depend on), the raised `ef_search` restores full recall on the filtered slice,
#: and `max_scan_tuples` keeps the scan bounded so it can never run away.
_HNSW_SCAN_SETTINGS = {
    "hnsw.iterative_scan": "strict_order",
    "hnsw.ef_search": "400",
    "hnsw.max_scan_tuples": "1000000",
}


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(
        settings.get_database_url(),
        echo=False,
        connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
    )
    _register_vector_scan_settings(engine)
    return engine


def _register_vector_scan_settings(engine: Engine) -> None:
    """Apply `_HNSW_SCAN_SETTINGS` once per new connection.

    Set at connection level rather than per query so a search costs no extra
    round trips. A database without pgvector accepts these as placeholder GUCs;
    if one is genuinely rejected the connection stays usable and the reason is
    logged, because non-RAG queries must not fail over a vector tuning knob.

    The commit is required, not tidiness: a plain `SET` is transactional, so
    without it the very first `ROLLBACK` on the connection silently reverts every
    setting and the filtered-search defect returns for the rest of its life.
    """

    @event.listens_for(engine, "connect")
    def _apply(dbapi_connection, _record):  # pragma: no cover - exercised live
        try:
            with dbapi_connection.cursor() as cursor:
                for name, value in _HNSW_SCAN_SETTINGS.items():
                    cursor.execute(f"SET {name} = {value}")
            dbapi_connection.commit()
        except Exception as exc:  # noqa: BLE001 - tuning must never break a connection
            dbapi_connection.rollback()
            _log.warning("could not apply pgvector scan settings: %s", sanitize_db_error(str(exc)))


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
