"""Narrow viewer-contract endpoints (Task 10 §1, §3, §4).

Offline: the DB session dependency is overridden and the catalog/entity query
functions are monkeypatched, so no PostgreSQL or OpenAI access occurs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import models as models_route
from app.query.sql import catalog as catalog_ops
from app.query.sql import entities as entity_ops
from app.viewer.assets import VIEWER_ASSET_SUFFIX


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("VIEWER_ASSET_ROOT", str(tmp_path))
    app.dependency_overrides[models_route.get_db] = lambda: object()
    client = TestClient(app)
    yield client, tmp_path
    app.dependency_overrides.pop(models_route.get_db, None)


# ---------------------------------------------------------------------------
# Model list
# ---------------------------------------------------------------------------


def test_model_list_ordering_default_name_and_status(api, monkeypatch):
    client, tmp_path = api
    # model 2 has a ready artifact; model 1 has a null display name + no artifact
    ready_dir = tmp_path / "2"
    ready_dir.mkdir()
    (ready_dir / f"fp2{VIEWER_ASSET_SUFFIX}").write_bytes(b"frag")

    rows = [
        SimpleNamespace(
            source_model_id=1, source_fingerprint="fp1", display_name=None, status="available"
        ),
        SimpleNamespace(
            source_model_id=2, source_fingerprint="fp2", display_name="Tower A", status="available"
        ),
    ]
    monkeypatch.setattr(catalog_ops, "list_selector_models", lambda _s: rows)

    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    ids = [m["source_model_id"] for m in body["models"]]
    assert ids == [1, 2]  # deterministic order
    assert body["models"][0]["display_name"] == "Model 1"  # safe default
    assert body["models"][0]["viewer_asset_status"] == "missing"
    assert body["models"][1]["viewer_asset_status"] == "ready"
    # field allowlist: exactly the contract fields, no path leakage
    assert set(body["models"][0].keys()) == {
        "source_model_id",
        "display_name",
        "source_fingerprint",
        "viewer_asset_status",
    }
    assert str(tmp_path) not in resp.text


def test_model_list_empty_catalog(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(catalog_ops, "list_selector_models", lambda _s: [])
    resp = client.get("/api/models")
    assert resp.status_code == 200
    assert resp.json() == {"models": []}


# ---------------------------------------------------------------------------
# Viewer asset
# ---------------------------------------------------------------------------


def _identity(fp="fp2", status="available", model_id=2):
    return SimpleNamespace(source_model_id=model_id, source_fingerprint=fp, status=status)


def test_viewer_asset_ready_streams_binary_with_etag(api, monkeypatch):
    client, tmp_path = api
    d = tmp_path / "2"
    d.mkdir()
    (d / f"fp2{VIEWER_ASSET_SUFFIX}").write_bytes(b"FRAGMENTS-BINARY")
    monkeypatch.setattr(catalog_ops, "get_model_asset_identity", lambda _s, _i: _identity())

    resp = client.get("/api/models/2/viewer-asset")
    assert resp.status_code == 200
    assert resp.content == b"FRAGMENTS-BINARY"
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["etag"] == '"fp2"'

    # conditional GET -> 304
    resp2 = client.get("/api/models/2/viewer-asset", headers={"If-None-Match": '"fp2"'})
    assert resp2.status_code == 304


def test_viewer_asset_missing_returns_bounded_404(api, monkeypatch):
    client, tmp_path = api
    monkeypatch.setattr(catalog_ops, "get_model_asset_identity", lambda _s, _i: _identity())
    resp = client.get("/api/models/2/viewer-asset")
    assert resp.status_code == 404
    assert resp.json()["detail"]["status"] == "missing"
    assert str(tmp_path) not in resp.text


def test_viewer_asset_stale_returns_409(api, monkeypatch):
    client, tmp_path = api
    d = tmp_path / "2"
    d.mkdir()
    (d / f"oldfp{VIEWER_ASSET_SUFFIX}").write_bytes(b"old")
    monkeypatch.setattr(catalog_ops, "get_model_asset_identity", lambda _s, _i: _identity())
    resp = client.get("/api/models/2/viewer-asset")
    assert resp.status_code == 409
    assert resp.json()["detail"]["status"] == "stale"


def test_viewer_asset_unknown_model_404(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(catalog_ops, "get_model_asset_identity", lambda _s, _i: None)
    resp = client.get("/api/models/123/viewer-asset")
    assert resp.status_code == 404
    assert resp.json()["detail"]["status"] == "unknown_model"


# ---------------------------------------------------------------------------
# GlobalId resolution
# ---------------------------------------------------------------------------


def test_resolve_success_order_dedupe_and_unresolved(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        catalog_ops, "get_model_asset_identity", lambda _s, _i: _identity(model_id=2)
    )
    rows = [
        SimpleNamespace(id=101, global_id="G1", ifc_class="IfcDoor", name="Door 1"),
        SimpleNamespace(id=102, global_id="G2", ifc_class="IfcWall", name=None),
    ]
    monkeypatch.setattr(
        entity_ops,
        "resolve_entities_by_global_ids",
        lambda _s, _i, gids: [r for r in rows if r.global_id in gids],
    )
    resp = client.post(
        "/api/models/2/entities/resolve",
        json={"global_ids": ["G2", "G1", "G2", "UNKNOWN"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [r["global_id"] for r in body["resolved"]] == ["G2", "G1"]  # order + dedupe
    assert body["resolved"][0]["entity_id"] == 102
    assert body["unresolved"] == ["UNKNOWN"]


def test_resolve_rejects_more_than_five(api):
    client, _ = api
    resp = client.post(
        "/api/models/2/entities/resolve",
        json={"global_ids": ["G1", "G2", "G3", "G4", "G5", "G6"]},
    )
    assert resp.status_code == 422


def test_resolve_unknown_model_404(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(catalog_ops, "get_model_asset_identity", lambda _s, _i: None)
    resp = client.post("/api/models/999/entities/resolve", json={"global_ids": ["G1"]})
    assert resp.status_code == 404
    assert resp.json()["detail"]["status"] == "unknown_model"
