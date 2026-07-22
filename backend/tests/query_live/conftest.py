"""Live, read-only database tests (spec_v003 §16, tasks/task05.md required
validation). All queries here run through `db.session.get_engine()`, which
uses `DATABASE_URL` when set — the dedicated `bim_rag_query_ro` read-only
role created by the ingestion-owned `bim_rag.db_admin.bootstrap_readonly_role`,
not the ingestion superuser connection. Every test in this package is read-only.

The whole package skips (not fails) if the database is unreachable, so
`pytest` stays green in environments without this project's local Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.session import check_connectivity, get_engine

SOURCE_MODEL_ID = 1  # the single ingested Schependomlaan model


def pytest_collection_modifyitems(config, items):
    ok, _ = check_connectivity()
    if ok:
        return
    skip_marker = pytest.mark.skip(reason="live database not reachable")
    for item in items:
        if "query_live" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture(scope="module")
def live_session():
    engine = get_engine()
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _contain_failed_transactions(live_session):
    """Roll back after every test so one failure cannot cascade.

    `live_session` is module-scoped for speed, which means a single statement
    that errors — most realistically a `statement_timeout` on an expensive
    traversal — leaves the transaction aborted and every SUBSEQUENT test in that
    module fails with `InFailedSqlTransaction`. That turns one honest failure
    into a cluster of misleading ones, which is actively harmful when reading a
    suite.

    This does not hide anything: the test that genuinely failed still fails. It
    only stops the damage spreading. Rolling back is safe here because every
    test in this package is read-only.
    """
    yield
    try:
        live_session.rollback()
    except Exception:  # noqa: BLE001 - teardown must never mask a real failure
        pass


@pytest.fixture(scope="session")
def embedding_service():
    """Loads BAAI/bge-m3 once for the whole test session (spec_v004 §4: the
    service is persistent, not reloaded per request). Skips the RAG live
    tests, not the whole suite, if the model genuinely can't load."""
    from app.query.rag.embedding_service import EmbeddingService

    svc = EmbeddingService()
    try:
        svc.ensure_loaded()
    except Exception as exc:  # noqa: BLE001 - degraded-mode skip, not a hard failure
        pytest.skip(f"embedding service not available: {exc}")
    return svc
