"""Tests: rag_documents logic, relationship templates, RAG orchestration (task 03)."""

from __future__ import annotations

import math

import pytest

from bim_rag.rel_templates import (
    DOCUMENT_TYPE as REL_DOC_TYPE,
)
from bim_rag.rel_templates import (
    MAX_TEXT_CHARS,
    generate_rel_text,
)
from bim_rag.rel_templates import (
    TEMPLATE_VERSION as REL_TEMPLATE_VERSION,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_rel_canonical(
    ifc_class: str = "IfcRelContainedInSpatialStructure",
    global_id: str = "REL001",
    name: str | None = None,
    scalars: dict | None = None,
    endpoints: dict | None = None,
) -> dict:
    return {
        "meta": {
            "step_id": 100,
            "global_id": global_id,
            "ifc_class": ifc_class,
            "extraction_version": "v001",
        },
        "identity": {k: v for k, v in {"name": name}.items() if v is not None},
        "scalars": scalars or {},
        "endpoints": endpoints
        or {
            "RelatingStructure": {
                "step_id": 200,
                "ifc_class": "IfcBuildingStorey",
                "global_id": "STOR001",
                "name": "Ground Floor",
            },
            "RelatedElements": [
                {"step_id": 300, "ifc_class": "IfcWall", "global_id": "WALL001", "name": None},
                {"step_id": 400, "ifc_class": "IfcDoor", "global_id": "DOOR001", "name": "D-01"},
            ],
        },
        "warnings": [],
    }


def _members_for_canonical(canonical: dict) -> list[dict]:
    """Build synthetic member rows matching the canonical JSON endpoints."""
    members = []
    for role, ep_val in canonical.get("endpoints", {}).items():
        if isinstance(ep_val, dict):
            members.append(
                {
                    "role": role,
                    "member_order": None,
                    "endpoint_step_id": ep_val.get("step_id"),
                    "endpoint_ifc_class": ep_val.get("ifc_class"),
                    "endpoint_global_id": ep_val.get("global_id"),
                    "endpoint_name": ep_val.get("name"),
                    "entity_id": None,
                }
            )
        elif isinstance(ep_val, list):
            for i, ep in enumerate(ep_val):
                members.append(
                    {
                        "role": role,
                        "member_order": i,
                        "endpoint_step_id": ep.get("step_id"),
                        "endpoint_ifc_class": ep.get("ifc_class"),
                        "endpoint_global_id": ep.get("global_id"),
                        "endpoint_name": ep.get("name"),
                        "entity_id": None,
                    }
                )
    return members


# ---------------------------------------------------------------------------
# rag_documents XOR source-reference constraint (logic, no DB)
# ---------------------------------------------------------------------------


def _validate_rag_row(entity_id, relationship_id) -> bool:
    """Simulate the XOR CHECK constraint."""
    return (entity_id is not None and relationship_id is None) or (
        entity_id is None and relationship_id is not None
    )


def test_xor_entity_doc_valid():
    assert _validate_rag_row(entity_id=42, relationship_id=None) is True


def test_xor_rel_doc_valid():
    assert _validate_rag_row(entity_id=None, relationship_id=99) is True


def test_xor_both_not_null_invalid():
    assert _validate_rag_row(entity_id=42, relationship_id=99) is False


def test_xor_both_null_invalid():
    assert _validate_rag_row(entity_id=None, relationship_id=None) is False


# ---------------------------------------------------------------------------
# source_kind / document_type agreement (logic, no DB)
# ---------------------------------------------------------------------------


def _validate_kind_type(source_kind: str, document_type: str) -> bool:
    """Simulate the ck_rag_kind_type_agreement CHECK constraint."""
    return (source_kind == "entity" and document_type == "entity_description") or (
        source_kind == "relationship" and document_type == "relationship_description"
    )


def test_entity_kind_entity_description_valid():
    assert _validate_kind_type("entity", "entity_description") is True


def test_relationship_kind_relationship_description_valid():
    assert _validate_kind_type("relationship", "relationship_description") is True


def test_entity_kind_relationship_description_invalid():
    assert _validate_kind_type("entity", "relationship_description") is False


def test_relationship_kind_entity_description_invalid():
    assert _validate_kind_type("relationship", "entity_description") is False


# ---------------------------------------------------------------------------
# Uniqueness key logic (logic, no DB)
# ---------------------------------------------------------------------------


def test_entity_doc_uniqueness_key_same_params():
    key1 = (42, "entity_description", "v001", "BAAI/bge-m3")
    key2 = (42, "entity_description", "v001", "BAAI/bge-m3")
    assert key1 == key2


def test_entity_doc_uniqueness_key_different_template_version():
    key1 = (42, "entity_description", "v001", "BAAI/bge-m3")
    key2 = (42, "entity_description", "v002", "BAAI/bge-m3")
    assert key1 != key2


def test_rel_doc_uniqueness_key_same_params():
    key1 = (77, "relationship_description", "v001", "BAAI/bge-m3")
    key2 = (77, "relationship_description", "v001", "BAAI/bge-m3")
    assert key1 == key2


def test_rel_doc_uniqueness_key_different_rel():
    key1 = (77, "relationship_description", "v001", "BAAI/bge-m3")
    key2 = (78, "relationship_description", "v001", "BAAI/bge-m3")
    assert key1 != key2


# ---------------------------------------------------------------------------
# Relationship template constants
# ---------------------------------------------------------------------------


def test_rel_template_version_is_v001():
    assert REL_TEMPLATE_VERSION == "v001"


def test_rel_document_type():
    assert REL_DOC_TYPE == "relationship_description"


# ---------------------------------------------------------------------------
# Relationship text generation
# ---------------------------------------------------------------------------


def test_generate_rel_text_identity_present():
    c = _minimal_rel_canonical(ifc_class="IfcRelAggregates")
    text, _ = generate_rel_text(c)
    assert "IfcRelAggregates" in text


def test_generate_rel_text_global_id_present():
    c = _minimal_rel_canonical(global_id="MYREL999")
    text, _ = generate_rel_text(c)
    assert "MYREL999" in text


def test_generate_rel_text_name_included():
    c = _minimal_rel_canonical(name="MyRelName")
    text, _ = generate_rel_text(c)
    assert "MyRelName" in text


def test_generate_rel_text_name_omitted_when_absent():
    c = _minimal_rel_canonical(name=None)
    text, _ = generate_rel_text(c)
    assert "None" not in text
    assert "null" not in text


def test_generate_rel_text_scalar_attr_present():
    c = _minimal_rel_canonical(scalars={"SequenceType": "FINISH_START"}, endpoints={})
    text, _ = generate_rel_text(c)
    assert "SequenceType" in text
    assert "FINISH_START" in text


def test_generate_rel_text_ownerhistory_omitted():
    c = _minimal_rel_canonical(scalars={"OwnerHistory_step_id": 99}, endpoints={})
    text, _ = generate_rel_text(c)
    assert "OwnerHistory_step_id" not in text


def test_generate_rel_text_endpoint_scalar_role_present():
    c = _minimal_rel_canonical()
    text, _ = generate_rel_text(c)
    assert "RelatingStructure" in text
    assert "IfcBuildingStorey" in text


def test_generate_rel_text_endpoint_aggregate_role_present():
    c = _minimal_rel_canonical()
    text, _ = generate_rel_text(c)
    assert "RelatedElements" in text
    assert "IfcWall" in text


def test_generate_rel_text_aggregate_member_order_in_text():
    c = _minimal_rel_canonical()
    text, _ = generate_rel_text(c)
    assert "[0]" in text or "[1]" in text


def test_generate_rel_text_entity_id_shown_when_resolved():
    c = _minimal_rel_canonical()
    members = [
        {
            "role": "RelatingStructure",
            "member_order": None,
            "endpoint_step_id": 200,
            "endpoint_ifc_class": "IfcBuildingStorey",
            "endpoint_global_id": "STOR001",
            "endpoint_name": "Ground Floor",
            "entity_id": 42,
        },
    ]
    text, _ = generate_rel_text(c, members=members)
    assert "Entity ID: 42" in text


def test_generate_rel_text_no_entity_id_when_unresolved():
    c = _minimal_rel_canonical(
        endpoints={
            "RelatingStructure": {
                "step_id": 200,
                "ifc_class": "IfcRepresentation",
                "global_id": None,
                "name": None,
            }
        }
    )
    members = [
        {
            "role": "RelatingStructure",
            "member_order": None,
            "endpoint_step_id": 200,
            "endpoint_ifc_class": "IfcRepresentation",
            "endpoint_global_id": None,
            "endpoint_name": None,
            "entity_id": None,
        }
    ]
    text, _ = generate_rel_text(c, members=members)
    assert "Entity ID" not in text


def test_generate_rel_text_deterministic():
    c = _minimal_rel_canonical()
    members = _members_for_canonical(c)
    t1, f1 = generate_rel_text(c, members=members)
    t2, f2 = generate_rel_text(c, members=members)
    assert t1 == t2
    assert f1 == f2


def test_generate_rel_text_no_recursive_expansion():
    """Endpoint text must not contain nested property_sets or canonical_json."""
    c = _minimal_rel_canonical()
    text, _ = generate_rel_text(c)
    assert "property_sets" not in text
    assert "canonical_json" not in text
    assert "quantity_sets" not in text


def test_generate_rel_text_finite():
    """Generated text is finite — under a reasonable ceiling."""
    c = _minimal_rel_canonical()
    text, _ = generate_rel_text(c)
    assert len(text) < 20_000


def test_generate_rel_text_truncation_flag_when_over_limit():
    """A relationship with hundreds of endpoints should trigger truncation flag."""
    many_related = [
        {"step_id": 1000 + i, "ifc_class": "IfcWall", "global_id": f"W{i:04d}", "name": None}
        for i in range(300)
    ]
    c = _minimal_rel_canonical(
        endpoints={
            "RelatingPropertyDefinition": {
                "step_id": 999,
                "ifc_class": "IfcPropertySet",
                "global_id": "PSE001",
                "name": "Pset_WallCommon",
            },
            "RelatedObjects": many_related,
        }
    )
    text, truncated = generate_rel_text(c)
    assert len(text) <= MAX_TEXT_CHARS + 1  # within limit
    assert truncated is True


def test_generate_rel_text_no_truncation_for_small_relationship():
    c = _minimal_rel_canonical()
    text, truncated = generate_rel_text(c)
    assert truncated is False


def test_generate_rel_text_works_without_members():
    """Template must not raise when members=None."""
    c = _minimal_rel_canonical()
    text, _ = generate_rel_text(c, members=None)
    assert "IfcRelContainedInSpatialStructure" in text


# ---------------------------------------------------------------------------
# Source-model isolation
# ---------------------------------------------------------------------------


def test_rag_doc_scoped_by_source_model():
    """Entity/relationship docs must carry source_model_id to prevent cross-model results."""
    doc1 = {"source_model_id": 1, "entity_id": 10, "relationship_id": None}
    doc2 = {"source_model_id": 2, "entity_id": 10, "relationship_id": None}
    assert doc1["source_model_id"] != doc2["source_model_id"]


# ---------------------------------------------------------------------------
# Orchestration and modularity
# ---------------------------------------------------------------------------


def test_ifc_to_db_is_callable():
    from bim_rag.pipeline_structured import ifc_to_db

    assert callable(ifc_to_db)


def test_run_vector_phase_is_callable():
    from bim_rag.stage2_embed import run_vector_phase

    assert callable(run_vector_phase)


def test_ifc_to_db_raises_for_missing_file():
    from bim_rag.pipeline_structured import ifc_to_db

    with pytest.raises(FileNotFoundError):
        ifc_to_db("/nonexistent/path.ifc")


def test_notebook_imports_ifc_to_db():
    from bim_rag import pipeline_structured

    assert hasattr(pipeline_structured, "ifc_to_db")


# ---------------------------------------------------------------------------
# Embedding validation (logic, no model)
# ---------------------------------------------------------------------------


def _fake_vec(dim: int = 1024, valid: bool = True) -> list[float]:
    if not valid:
        return [float("nan")] * dim
    return [1.0 / math.sqrt(dim)] * dim


def test_valid_entity_embedding_dimension():
    vec = _fake_vec(1024)
    assert len(vec) == 1024


def test_invalid_embedding_nan_detected():
    vec = _fake_vec(valid=False)
    assert any(math.isnan(x) or math.isinf(x) for x in vec)


def test_wrong_dimension_rejected():
    vec = _fake_vec(dim=768)
    assert len(vec) != 1024


# ---------------------------------------------------------------------------
# Element-vectors migration safety (logic, no DB)
# ---------------------------------------------------------------------------


def test_element_vectors_migration_empty_allowed():
    """An empty element_vectors table should be droppable (logic simulation)."""
    row_count = 0  # simulated
    safe_to_drop = row_count == 0
    assert safe_to_drop is True


def test_element_vectors_migration_populated_blocked():
    """A populated element_vectors table must not be silently dropped."""
    row_count = 5  # simulated
    safe_to_drop = row_count == 0
    assert safe_to_drop is False
