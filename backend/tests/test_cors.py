"""CORS allowlist behavior (spec_v006 §10.5; Task 10 §7).

The configured local frontend origin is allowed; an unconfigured origin is not
echoed. No wildcard-with-credentials.
"""

from __future__ import annotations


def test_configured_origin_is_allowed(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
    # never wildcard-with-credentials
    assert resp.headers.get("access-control-allow-credentials") != "true"


def test_unconfigured_origin_is_not_echoed(client):
    resp = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example.com"
