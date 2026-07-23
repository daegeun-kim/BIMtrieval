"""Shared fixtures for backend/tests.

No fixture here connects to a real database or calls OpenAI. The `backend/`
project root reaches this test suite via the `pythonpath = ["."]` pytest ini
option (pyproject.toml), so imports use the `app.*` package (`app.config`,
`app.db`, `app.api`, ...), matching how backend modules import each other.
"""

from __future__ import annotations

import pytest

from app.config.settings import get_settings


@pytest.fixture(autouse=True)
def _isolate_query_trace(tmp_path_factory, monkeypatch):
    """Redirect the permanent query trace to a temp file for every test.

    task26 §14 makes `backend/app/evaluation/query_trace.jsonl` a Git-tracked
    append-only log. Tests exercise `QueryService.handle_query`, which appends a
    record on every request, so without this redirect the suite would pollute
    the committed file. The override is via the settings field, exactly the
    mechanism production uses.
    """
    trace_file = tmp_path_factory.mktemp("query_trace") / "trace.jsonl"
    monkeypatch.setenv("query_trace_path", str(trace_file))


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Prevent one test's monkeypatched env vars from leaking into another."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.api.app import app

    return TestClient(app)
