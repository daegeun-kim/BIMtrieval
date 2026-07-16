"""Terminal output: always-on statement/error/usage records + opt-in trace mode
(tasks/task13.md §1 as amended by tasks/task15.md §1).

Offline: uses an in-memory SQLite engine to exercise the statement hook (the
listener is registered on the SQLAlchemy `Engine` class, so any engine triggers
it) and the FastAPI TestClient for API records. No PostgreSQL, no OpenAI, no
embedding model.

The central claims under test:

- submitted SQL/RAG statements print exactly once, parameterized, with or
  without BIM_RAG_TRACE — and parameter VALUES never do;
- API status records appear ONLY for HTTP 400–599, trace on or off;
- trace summaries carry timing/counts but never repeat the statements;
- request bodies, chat history, query strings, vectors, and secrets never
  reach the terminal.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.app import app, create_app
from app.api.routes import models as models_route
from app.config import trace
from app.config.settings import get_settings

SECRET_VALUE = "SUPER-SECRET-PARAMETER-VALUE"


@pytest.fixture()
def logs(caplog):
    """Capture both the trace and the always-on db/error output."""
    caplog.set_level(logging.INFO, logger="bim_rag_backend")
    return caplog


@pytest.fixture()
def traced(monkeypatch, logs):
    monkeypatch.setenv("BIM_RAG_TRACE", "1")
    get_settings.cache_clear()
    return logs


@pytest.fixture()
def untraced(monkeypatch, logs):
    monkeypatch.delenv("BIM_RAG_TRACE", raising=False)
    get_settings.cache_clear()
    return logs


@pytest.fixture()
def sqlite_engine():
    engine = create_engine("sqlite://")
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Opt-in trace flag
# ---------------------------------------------------------------------------


def test_trace_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BIM_RAG_TRACE", raising=False)
    get_settings.cache_clear()
    assert get_settings().bim_rag_trace is False
    assert trace.trace_enabled() is False


@pytest.mark.parametrize("value,expected", [("1", True), ("0", False), ("true", True)])
def test_trace_is_enabled_only_by_the_env_var(monkeypatch, value, expected):
    monkeypatch.setenv("BIM_RAG_TRACE", value)
    get_settings.cache_clear()
    assert trace.trace_enabled() is expected


# ---------------------------------------------------------------------------
# Always-on statement output (task15 §1)
# ---------------------------------------------------------------------------


def test_submitted_sql_prints_even_without_trace(untraced, sqlite_engine):
    with sqlite_engine.connect() as conn:
        conn.execute(text("SELECT :v"), {"v": SECRET_VALUE})

    out = untraced.text
    assert "[SQL]" in out
    # The parameterized form is shown...
    assert "SELECT ?" in out
    # ...and the bound value is not, because it is never collected at all.
    assert SECRET_VALUE not in out


def test_rag_statements_are_labelled_rag_even_without_trace(untraced, sqlite_engine):
    query_vector = [0.1234567] * 1024
    with trace.trace_rag_search(
        semantic_query="q", document_kinds=["entity"], top_k=30, minimum_similarity=0.5
    ):
        with sqlite_engine.connect() as conn:
            conn.execute(text("SELECT :embedding"), {"embedding": str(query_vector)})

    out = untraced.text
    assert "[RAG]" in out
    assert "SELECT ?" in out
    assert "0.1234567" not in out  # the embedding vector never prints


def test_statement_label_returns_to_sql_after_a_rag_search(untraced, sqlite_engine):
    with trace.trace_rag_search(
        semantic_query="q", document_kinds=["entity"], top_k=30, minimum_similarity=0.5
    ):
        pass
    with sqlite_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert "[SQL]" in untraced.text


def test_each_statement_prints_exactly_once_with_trace_enabled(traced, sqlite_engine):
    """Trace mode must not duplicate statement output (task15 §1)."""
    marker = "SELECT 42 AS once_marker"
    with trace.trace_sql_operation("count_entities") as rec:
        with sqlite_engine.connect() as conn:
            conn.execute(text(marker))
        rec.exact_count = 1

    assert traced.text.count(marker) == 1


def test_no_statement_output_for_sql_that_was_never_submitted(untraced):
    """Planned-but-unsubmitted SQL must not print: only the cursor-execute hook
    emits, and it fires solely on real submission."""
    with trace.trace_sql_operation("count_entities"):
        pass  # an operation that ends up submitting nothing
    assert "[SQL]" not in untraced.text


# ---------------------------------------------------------------------------
# Trace summary records (task13 §1, minus the statements)
# ---------------------------------------------------------------------------


def test_no_trace_summaries_when_disabled(untraced, sqlite_engine):
    with trace.trace_sql_operation("count_entities") as rec:
        with sqlite_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        rec.exact_count = 205

    assert "[trace]" not in untraced.text  # statements still printed, summaries not
    assert "[SQL]" in untraced.text


def test_sql_summary_reports_counts_and_histogram_but_never_the_statements(traced, sqlite_engine):
    marker = "SELECT 7 AS histogram_marker"
    with trace.trace_sql_operation("filter_entities") as rec:
        with sqlite_engine.connect() as conn:
            conn.execute(text(marker))
        rec.exact_count = 8
        rec.row_count = 8
        rec.result_histogram = {"IfcDoor": 5, "IfcWindow": 3}

    out = traced.text
    assert "[trace] sql" in out
    assert "filter_entities" in out
    assert "exact_count: 8" in out
    assert "IfcDoor: 5, IfcWindow: 3" in out
    # The statement appears once via [SQL], not again inside the summary.
    summary = out[out.index("[trace] sql") :]
    assert marker not in summary


def test_sql_elapsed_time_is_reported_in_seconds_not_milliseconds(traced, sqlite_engine):
    with trace.trace_sql_operation("count_entities"):
        with sqlite_engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    assert "elapsed_s:" in traced.text
    assert "elapsed_ms" not in traced.text
    # A trivial local query is far below one second — proves the unit is seconds.
    assert "elapsed_s: 0." in traced.text


def test_rag_summary_has_the_required_nested_fields_and_no_vector(traced, sqlite_engine):
    query_vector = [0.1234567] * 1024

    with trace.trace_rag_search(
        semantic_query="components related to fire separation",
        document_kinds=["entity", "relationship"],
        top_k=30,
        minimum_similarity=0.5,
    ) as rec:
        with sqlite_engine.connect() as conn:
            conn.execute(text("SELECT :embedding"), {"embedding": str(query_vector)})
        rec.retrieved_count = 12
        rec.similarity_min = 0.5121
        rec.similarity_max = 0.7834
        rec.result_histogram = {"entity_description": 9, "relationship_description": 3}

    out = traced.text
    assert "[trace] rag" in out
    assert "components related to fire separation" in out
    assert "top_k: 30" in out
    assert "minimum_similarity: 0.5" in out
    assert "retrieved_count: 12" in out
    assert "similarity_range: 0.5121 - 0.7834" in out
    assert "entity_description: 9, relationship_description: 3" in out
    assert "elapsed_s:" in out
    assert "0.1234567" not in out
    # The vector SQL printed once via [RAG]; the summary does not repeat it.
    summary = out[out.index("[trace] rag") :]
    assert "SELECT ?" not in summary


def test_rag_summary_omits_the_similarity_range_when_nothing_was_retrieved(traced):
    with trace.trace_rag_search(
        semantic_query="q", document_kinds=["entity"], top_k=30, minimum_similarity=0.5
    ) as rec:
        rec.retrieved_count = 0

    assert "similarity_range" not in traced.text


def test_sub_records_share_the_requests_correlation_id(traced, sqlite_engine):
    with trace.request_context("req-abc123"):
        with trace.trace_sql_operation("count_entities"):
            with sqlite_engine.connect() as conn:
                conn.execute(text("SELECT 1"))

    assert "request_id: req-abc123" in traced.text


# ---------------------------------------------------------------------------
# API status records: errors only (task15 §1)
# ---------------------------------------------------------------------------


def test_no_api_record_for_a_successful_call_even_with_trace_enabled(traced):
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert "[API error]" not in traced.text
    assert "[trace] api" not in traced.text
    assert "/health" not in traced.text


def test_uvicorn_access_lines_are_quieted_for_successful_calls():
    """Successful calls print nothing anywhere (task15 §1): uvicorn's own
    per-request access lines are raised above INFO; errors remain visible via
    the bounded [API error] records."""
    create_app()
    assert logging.getLogger("uvicorn.access").level >= logging.WARNING


def test_no_api_record_for_redirects_or_not_modified(untraced):
    """3xx (including 304) is not an error and prints nothing (task15 §1)."""
    test_app = create_app()

    @test_app.get("/__test/redirect", status_code=307)
    def _redirect():  # pragma: no cover - trivial
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/health", status_code=307)

    @test_app.get("/__test/notmodified")
    def _notmodified():
        from fastapi import Response

        return Response(status_code=304)

    client = TestClient(test_app)
    assert client.get("/__test/redirect", follow_redirects=False).status_code == 307
    assert client.get("/__test/notmodified").status_code == 304
    assert "[API error]" not in untraced.text


def test_one_bounded_api_record_for_a_4xx(untraced, monkeypatch):
    monkeypatch.setattr(models_route.entity_ops, "get_entity_canonical", lambda *_a: None)
    app.dependency_overrides[models_route.get_db] = lambda: object()
    try:
        client = TestClient(app)
        resp = client.get("/api/models/1/entities/NOPE/details")
    finally:
        app.dependency_overrides.pop(models_route.get_db, None)

    assert resp.status_code == 404
    out = untraced.text
    assert out.count("[API error]") == 1
    assert "method: GET" in out
    assert "status: 404" in out
    assert "elapsed_s:" in out
    assert "elapsed_ms" not in out


def test_one_bounded_api_record_for_a_5xx_without_exception_details(untraced):
    test_app = create_app()

    @test_app.get("/__test/boom")
    def _boom():
        raise RuntimeError("internal detail with a path C:/secret/place and sk-key")

    client = TestClient(test_app, raise_server_exceptions=False)
    assert client.get("/__test/boom").status_code == 500

    out = untraced.text
    assert out.count("[API error]") == 1
    assert "status: 500" in out
    # bounded: no exception internals, no paths, no key-shaped strings
    assert "internal detail" not in out
    assert "C:/secret/place" not in out
    assert "sk-key" not in out


def test_api_error_record_logs_the_route_template_not_the_raw_url(untraced, monkeypatch):
    """Query strings may carry user data, so only the route template is logged."""
    monkeypatch.setattr(models_route.entity_ops, "get_entity_canonical", lambda *_a: None)
    app.dependency_overrides[models_route.get_db] = lambda: object()
    try:
        client = TestClient(app)
        client.get(f"/api/models/1/entities/SOME-GID/details?q={SECRET_VALUE}")
    finally:
        app.dependency_overrides.pop(models_route.get_db, None)

    out = untraced.text
    assert "route: /api/models/{source_model_id}/entities/{global_id}/details" in out
    assert SECRET_VALUE not in out


def test_api_error_record_never_logs_the_request_body(untraced, monkeypatch):
    """Chat history and question text live in request bodies (task13 §1)."""
    monkeypatch.setattr(models_route.entity_ops, "get_entity_canonical", lambda *_a: None)
    app.dependency_overrides[models_route.get_db] = lambda: object()
    try:
        client = TestClient(app)
        client.post(
            "/api/models/1/entities/highlight-group",
            json={"selected_global_id": SECRET_VALUE, "scope": "instance"},
        )
    finally:
        app.dependency_overrides.pop(models_route.get_db, None)

    assert "[API error]" in untraced.text  # the 404 itself is recorded
    assert SECRET_VALUE not in untraced.text


# ---------------------------------------------------------------------------
# Redaction / rendering (unchanged from task13)
# ---------------------------------------------------------------------------


def test_records_are_passed_through_the_existing_secret_redaction(traced):
    trace.emit(
        "[trace] test",
        {
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz123456",
            "database_url": "postgresql://user:pw@localhost/db",
            "nested": {"authorization": "Bearer abc123"},
            "safe": "kept",
        },
    )
    out = traced.text
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "user:pw" not in out
    assert "Bearer abc123" not in out
    assert "REDACTED" in out
    assert "kept" in out


def test_token_usage_metrics_are_not_over_redacted(traced):
    """Guards the task08 regression: `token_usage`/`total_tokens` must survive."""
    trace.emit("[trace] test", {"token_usage": {"total_tokens": 10500}})
    assert "10500" in traced.text


def test_emit_renders_an_indented_nested_structure_not_dense_json(traced):
    trace.emit("[trace] test", {"operation": "count_entities", "nested": {"inner": "value"}})
    out = traced.text
    assert "  operation: count_entities" in out
    assert "  nested:" in out
    assert "    inner: value" in out
    # Not a one-line JSON blob.
    assert '{"operation"' not in out


def test_empty_and_null_fields_are_omitted_rather_than_printed_as_noise(traced):
    trace.emit("[trace] test", {"present": "yes", "nothing": None, "empty": [], "blank": {}})
    out = traced.text
    assert "present: yes" in out
    assert "nothing" not in out
    assert "empty" not in out
    assert "blank" not in out
