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
