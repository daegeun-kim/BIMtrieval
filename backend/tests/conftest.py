"""Shared fixtures for backend/tests.

No fixture here connects to a real database or calls OpenAI. `backend/src`
reaches this test suite via the `pythonpath` pytest ini option
(pyproject.toml), so imports use plain top-level names (`config`, `db`,
`api`, ...), matching how backend/src modules import each other.
"""

from __future__ import annotations

import pytest
from config.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Prevent one test's monkeypatched env vars from leaking into another."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client():
    from api.app import app
    from fastapi.testclient import TestClient

    return TestClient(app)
