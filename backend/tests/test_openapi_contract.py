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


# ---------------------------------------------------------------------------
# Task 26 — the explanation-panel presentation contract
# ---------------------------------------------------------------------------


def test_answer_explanation_contract_is_documented(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in (
        "AnswerExplanation",
        "ExplanationPresentation",
        "ExplanationGroup",
        "ExplanationRow",
        "ExplanationBucket",
        "ExplanationAggregate",
    ):
        assert name in schemas, name

    props = schemas["AnswerExplanation"]["properties"]
    for field in (
        "part_id",
        "request_label",
        "operation",
        "result_status",
        "presentation",
        "answer_basis",
        "interpretation",
        "retrieval_modes",
        "exact_total",
        "class_breakdown",
        "distribution",
        "aggregate",
        "relationship_endpoint_total",
        "limitation",
        "known_parts",
        "unknown_parts",
        "shown_identity_count",
        "true_result_count",
        "identities_truncated",
        "groups",
        "rows",
    ):
        assert field in props, field

    # Additive on the existing envelope, so a client that ignores it still works.
    assert "answer_explanation" in schemas["QueryResponseEnvelope"]["properties"]
    assert "answer_explanation" not in schemas["QueryResponseEnvelope"].get("required", [])


def test_explanation_presentation_enum_is_documented(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["ExplanationPresentation"]["enum"]) == {
        "metric",
        "table",
        "distribution",
        "aggregate",
        "relationship",
        "partial",
    }


def test_only_selectable_groups_carry_identities(client):
    """A distribution bucket has no authoritative identity subset, so the
    contract gives it no way to claim one (task26 §1.1)."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "global_ids" in schemas["ExplanationGroup"]["properties"]
    assert "global_ids" not in schemas["ExplanationBucket"]["properties"]


# ---------------------------------------------------------------------------
# Task 28 — the read-only logical floor contract for the floor-plan control
# ---------------------------------------------------------------------------


def test_model_floors_path_is_documented_and_read_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    floors = "/api/models/{source_model_id}/floors"
    assert "get" in paths[floors]
    # Read-only: no mutating verb is part of the contract.
    assert not {"post", "put", "patch", "delete"} & set(paths[floors])
    # Source-model scoped: the id is a required path parameter.
    params = paths[floors]["get"]["parameters"]
    assert any(p["name"] == "source_model_id" and p["in"] == "path" for p in params)


def test_model_floors_schemas_present(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("ModelFloorsResponse", "FloorBandInfo", "FloorReferenceBasis"):
        assert name in schemas, name

    props = schemas["ModelFloorsResponse"]["properties"]
    for field in (
        "source_model_id",
        "available",
        "unavailable_reason",
        "reference_band_index",
        "reference_basis",
        "total_storeys",
        "floors",
    ):
        assert field in props, field

    band = schemas["FloorBandInfo"]["properties"]
    for field in (
        "band_index",
        "label",
        "is_reference",
        "storey_global_ids",
        "storey_names",
        "min_elevation",
        "max_elevation",
    ):
        assert field in band, field


def test_floor_reference_basis_enum_is_documented(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["FloorReferenceBasis"]["enum"]) == {
        "elevation_zero",
        "lowest_band",
        "none",
    }


def test_floor_contract_is_additive(client):
    """Existing clients that never call the endpoint keep working, so nothing
    was added to a shared response envelope (task28 §2.1)."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "floors" not in schemas["QueryResponseEnvelope"]["properties"]
    assert "floors" not in schemas["ModelListItem"]["properties"]


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
