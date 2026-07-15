"""FastAPI health/readiness routes pass without database or OpenAI access
(tasks/task04.md required verification)."""

from __future__ import annotations


def test_health_is_always_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_reports_ok_without_touching_real_database(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.health.check_connectivity", lambda: (True, None))
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == {"ok": True, "error": None}


def test_ready_degrades_gracefully_and_sanitizes_error(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.health.check_connectivity",
        lambda: (False, "connection failed: postgresql://user:<credentials>@host/db"),
    )
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"]["ok"] is False
    assert "<credentials>" in body["database"]["error"]
