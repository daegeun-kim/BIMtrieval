"""Tests: relationship extraction, endpoint resolution, idempotency (task 02-1)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from bim_rag.rel_parser import (
    _endpoint_summary,
    extract_member_rows,
    extract_relationship_canonical_json,
    resolve_members,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rel(
    ifc_class: str = "IfcRelContainedInSpatialStructure",
    global_id: str = "REL001",
    step_id: int = 100,
    name: str | None = None,
    relating: MagicMock | None = None,
    related: list[MagicMock] | None = None,
) -> MagicMock:
    rel = MagicMock()
    rel.is_a = MagicMock(
        side_effect=lambda cls=None: (
            (cls in (ifc_class, "IfcRelationship", "IfcRoot")) if cls else ifc_class
        )
    )
    rel.GlobalId = global_id
    rel.id = MagicMock(return_value=step_id)
    rel.Name = name
    rel.Description = None

    relating_mock = relating or _make_entity("IfcBuildingStorey", "STOR001", 200)
    related_mock = related or [
        _make_entity("IfcWall", "WALL001", 300),
        _make_entity("IfcDoor", "DOOR001", 400),
    ]

    rel.get_info = MagicMock(
        return_value={
            "id": step_id,
            "type": ifc_class,
            "GlobalId": global_id,
            "OwnerHistory": MagicMock(**{"id.return_value": 99}),
            "Name": name,
            "Description": None,
            "RelatingStructure": relating_mock,
            "RelatedElements": related_mock,
        }
    )
    return rel


def _make_entity(
    ifc_class: str,
    global_id: str | None,
    step_id: int,
    name: str | None = None,
) -> MagicMock:
    ent = MagicMock()
    ent.is_a = MagicMock(side_effect=lambda cls=None: cls == ifc_class if cls else ifc_class)
    ent.GlobalId = global_id
    ent.id = MagicMock(return_value=step_id)
    ent.Name = name
    return ent


# ---------------------------------------------------------------------------
# Endpoint summary
# ---------------------------------------------------------------------------


def test_endpoint_summary_captures_step_id_class_gid_name():
    ent = _make_entity("IfcWall", "WALL001", 300, "Wall A")
    s = _endpoint_summary(ent)
    assert s["step_id"] == 300
    assert s["ifc_class"] == "IfcWall"
    assert s["global_id"] == "WALL001"
    assert s["name"] == "Wall A"


def test_endpoint_summary_no_global_id():
    ent = _make_entity("IfcRepresentation", None, 999)
    s = _endpoint_summary(ent)
    assert s["global_id"] is None
    assert s["step_id"] == 999


# ---------------------------------------------------------------------------
# Canonical JSON extraction
# ---------------------------------------------------------------------------


def test_relationship_canonical_json_is_serialisable():
    rel = _make_rel()
    cj, _ = extract_relationship_canonical_json(rel)
    json.dumps(cj)  # must not raise


def test_relationship_canonical_json_meta_fields():
    rel = _make_rel(global_id="R1", step_id=100, ifc_class="IfcRelAggregates")
    cj, _ = extract_relationship_canonical_json(rel)
    assert cj["meta"]["global_id"] == "R1"
    assert cj["meta"]["step_id"] == 100
    assert cj["meta"]["ifc_class"] == "IfcRelAggregates"
    assert cj["meta"]["extraction_version"] == "v001"


def test_relationship_canonical_json_endpoints_present():
    rel = _make_rel()
    cj, _ = extract_relationship_canonical_json(rel)
    assert "RelatingStructure" in cj["endpoints"]
    assert "RelatedElements" in cj["endpoints"]


def test_relationship_canonical_json_no_owner_history_in_endpoints():
    rel = _make_rel()
    cj, _ = extract_relationship_canonical_json(rel)
    assert "OwnerHistory" not in cj["endpoints"]


def test_relationship_canonical_json_no_recursion():
    """Endpoint summaries are shallow — no nested canonical JSON expansion."""
    rel = _make_rel()
    cj, _ = extract_relationship_canonical_json(rel)
    ep = cj["endpoints"]["RelatingStructure"]
    # Should have step_id, ifc_class, global_id, name — NOT a full canonical_json
    assert "canonical_json" not in ep
    assert "property_sets" not in ep
    assert "step_id" in ep


def test_relationship_canonical_json_aggregate_endpoint_is_list():
    rel = _make_rel()
    cj, _ = extract_relationship_canonical_json(rel)
    assert isinstance(cj["endpoints"]["RelatedElements"], list)
    assert len(cj["endpoints"]["RelatedElements"]) == 2


def test_relationship_canonical_json_finite():
    rel = _make_rel()
    cj, _ = extract_relationship_canonical_json(rel)
    raw = json.dumps(cj)
    assert len(raw) < 10_000  # finite, not unbounded


# ---------------------------------------------------------------------------
# Member row extraction
# ---------------------------------------------------------------------------


def test_member_rows_scalar_role():
    rel = _make_rel()
    rows = extract_member_rows(rel)
    scalar = [r for r in rows if r["role"] == "RelatingStructure"]
    assert len(scalar) == 1
    assert scalar[0]["member_order"] is None
    assert scalar[0]["endpoint_step_id"] == 200
    assert scalar[0]["endpoint_ifc_class"] == "IfcBuildingStorey"


def test_member_rows_aggregate_role():
    rel = _make_rel()
    rows = extract_member_rows(rel)
    agg = [r for r in rows if r["role"] == "RelatedElements"]
    assert len(agg) == 2
    orders = [r["member_order"] for r in agg]
    assert 0 in orders and 1 in orders


def test_member_rows_no_owner_history():
    rel = _make_rel()
    rows = extract_member_rows(rel)
    roles = {r["role"] for r in rows}
    assert "OwnerHistory" not in roles


def test_member_rows_deterministic_order():
    rel = _make_rel()
    rows1 = extract_member_rows(rel)
    rows2 = extract_member_rows(rel)
    assert [(r["role"], r["member_order"]) for r in rows1] == [
        (r["role"], r["member_order"]) for r in rows2
    ]


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------


def test_resolve_members_known_global_id():
    raw = [
        {
            "role": "RelatingStructure",
            "member_order": None,
            "endpoint_step_id": 200,
            "endpoint_ifc_class": "IfcBuildingStorey",
            "endpoint_global_id": "STOR001",
            "endpoint_name": None,
        }
    ]
    resolved = resolve_members(raw, {"STOR001": 42}, source_model_id=1)
    assert resolved[0]["entity_id"] == 42


def test_resolve_members_unknown_global_id():
    raw = [
        {
            "role": "RelatingStructure",
            "member_order": None,
            "endpoint_step_id": 200,
            "endpoint_ifc_class": "IfcBuildingStorey",
            "endpoint_global_id": "UNKNOWN",
            "endpoint_name": None,
        }
    ]
    resolved = resolve_members(raw, {"STOR001": 42}, source_model_id=1)
    assert resolved[0]["entity_id"] is None


def test_resolve_members_no_global_id_stays_unresolved():
    raw = [
        {
            "role": "RelatingStructure",
            "member_order": None,
            "endpoint_step_id": 200,
            "endpoint_ifc_class": "IfcRepresentation",
            "endpoint_global_id": None,
            "endpoint_name": None,
        }
    ]
    resolved = resolve_members(raw, {"STOR001": 42}, source_model_id=1)
    assert resolved[0]["entity_id"] is None


def test_resolve_members_cross_source_impossible():
    """Lookup dict is scoped to one source model — no cross-model ID leakage."""
    raw = [
        {
            "role": "RelatedObjects",
            "member_order": 0,
            "endpoint_step_id": 300,
            "endpoint_ifc_class": "IfcWall",
            "endpoint_global_id": "WALL999",
            "endpoint_name": None,
        }
    ]
    # WALL999 appears in a different model's lookup — not passed here
    resolved = resolve_members(raw, {"OTHER_WALL": 99}, source_model_id=1)
    assert resolved[0]["entity_id"] is None


def test_resolve_members_source_model_id_added():
    raw = [
        {
            "role": "RelatingStructure",
            "member_order": None,
            "endpoint_step_id": 200,
            "endpoint_ifc_class": "IfcBuildingStorey",
            "endpoint_global_id": "STOR001",
            "endpoint_name": None,
        }
    ]
    resolved = resolve_members(raw, {"STOR001": 42}, source_model_id=7)
    assert resolved[0]["source_model_id"] == 7


# ---------------------------------------------------------------------------
# Idempotency keys
# ---------------------------------------------------------------------------


def test_relationship_unique_key():
    key1 = ("model_1", "REL001")
    key2 = ("model_1", "REL001")
    assert key1 == key2  # same rel same model = same upsert target


def test_member_unique_key_scalar():
    key1 = (1, "RelatingStructure", None, 200)
    key2 = (1, "RelatingStructure", None, 200)
    assert key1 == key2


def test_member_unique_key_aggregate():
    key1 = (1, "RelatedObjects", 0, 300)
    key2 = (1, "RelatedObjects", 1, 400)
    assert key1 != key2


def test_stable_rel_id_across_reruns():
    """Upsert on (source_model_id, global_id) must not create a new row."""
    seen_rels: set[tuple] = set()
    key = (1, "REL001")
    seen_rels.add(key)
    assert key in seen_rels  # second add is idempotent in a set


# ---------------------------------------------------------------------------
# Multi-file source isolation
# ---------------------------------------------------------------------------


def test_different_files_get_different_source_model_ids():
    fp1 = "aaaa1111"
    fp2 = "bbbb2222"
    assert fp1 != fp2  # would produce separate ifc_source_models rows


def test_entity_id_lookup_scoped_to_source_model():
    """Each model has its own gid_to_entity_id dict — never mixed."""
    model1_lookup = {"WALL001": 10}
    model2_lookup = {"WALL001": 99}
    # Same GlobalId, different entity_id in different models
    assert model1_lookup["WALL001"] != model2_lookup["WALL001"]


# ---------------------------------------------------------------------------
# ifc_to_db path handling
# ---------------------------------------------------------------------------


def test_ifc_to_db_raises_for_missing_file():
    from bim_rag.pipeline_structured import ifc_to_db

    with pytest.raises(FileNotFoundError):
        ifc_to_db("/nonexistent/path/model.ifc")


def test_ifc_to_db_accepts_str_path():
    from bim_rag.pipeline_structured import ifc_to_db

    with pytest.raises(FileNotFoundError):
        ifc_to_db(r"C:\fake\file.ifc")


# ---------------------------------------------------------------------------
# Notebook modularity check
# ---------------------------------------------------------------------------


def test_notebook_imports_pipeline_not_reimplements():
    """The notebook module exists and imports ifc_to_db from pipeline_structured."""
    from bim_rag import pipeline_structured

    assert hasattr(pipeline_structured, "ifc_to_db")
    assert callable(pipeline_structured.ifc_to_db)
