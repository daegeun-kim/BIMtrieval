"""OpenAPI exposes the frontend viewer contract accurately (Task 10 §8).

Task 11 generates TypeScript from this schema, so the new paths and bounded
request/response models must appear.
"""

from __future__ import annotations


def test_new_paths_are_documented(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/models" in paths
    assert "/api/models/{source_model_id}/viewer-asset" in paths
    assert "/api/models/{source_model_id}/entities/resolve" in paths
    assert "/api/query" in paths


def test_request_and_response_schemas_present(client):
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert "ModelListResponse" in schemas
    assert "ResolveEntitiesRequest" in schemas
    assert "ResolveEntitiesResponse" in schemas
    # Public browser selection field appears on the query request contract.
    assert "selected_global_ids" in schemas["SessionQueryRequest"]["properties"]
