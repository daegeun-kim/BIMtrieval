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
    assert "/api/query/render-timing" in paths


def test_request_and_response_schemas_present(client):
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert "ModelListResponse" in schemas
    assert "ResolveEntitiesRequest" in schemas
    assert "ResolveEntitiesResponse" in schemas
    # Public browser selection field appears on the query request contract.
    assert "selected_global_ids" in schemas["SessionQueryRequest"]["properties"]


# ---------------------------------------------------------------------------
# Task 13 additions — the contract Task 14 generates its TypeScript from
# ---------------------------------------------------------------------------


def test_component_detail_and_group_paths_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    details = "/api/models/{source_model_id}/entities/{global_id}/details"
    group = "/api/models/{source_model_id}/entities/highlight-group"
    assert "get" in paths[details]
    assert "post" in paths[group]


def test_detail_and_group_schemas_present(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in (
        "EntityDetailsResponse",
        "InstanceDetails",
        "TypeDetails",
        "FamilyDetails",
        "DetailAvailability",
        "DetailValue",
        "HighlightGroupRequest",
        "HighlightGroupResponse",
        "HighlightScope",
    ):
        assert name in schemas, name


def test_highlight_scope_enum_is_documented(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["HighlightScope"]["enum"]) == {"instance", "type", "family"}


def test_result_summary_contract_is_documented(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "ResultSummary" in schemas
    assert "SampleDetail" in schemas
    props = schemas["ResultSummary"]["properties"]
    for field in (
        "exact_total",
        "viewer_match_count",
        "viewer_matches_total",
        "truncated",
        "class_counts",
        "sample_detail",
    ):
        assert field in props, field
    # Additive on the existing envelope, so the pre-Task-14 frontend still works.
    assert "result_summary" in schemas["QueryResponseEnvelope"]["properties"]


def test_viewer_truncation_contract_is_documented(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    props = schemas["ViewerActions"]["properties"]
    assert "viewer_matches_total" in props
    assert "viewer_matches_truncated" in props


def test_no_schema_exposes_canonical_json_or_trace_internals_as_a_field(client):
    """Tracing is local terminal observability, not a client response feature,
    and raw canonical JSON is never part of the API contract (task13 §6).

    Checks declared *properties*, not the raw text: several schema descriptions
    legitimately mention canonical_json to say they exclude it.
    """
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    forbidden = {"canonical_json", "sql", "raw_sql", "embedding", "trace", "prompt"}
    for name, schema in schemas.items():
        exposed = set(schema.get("properties", {})) & forbidden
        assert not exposed, f"{name} exposes {exposed}"
