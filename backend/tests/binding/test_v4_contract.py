"""task26 §17.1 — contract, manifest reader, and projection tests (offline).

No database: these build v002 documents in memory and assert the reader,
projection, and bidirectional contract/adapter completeness invariants.
"""

from __future__ import annotations

import pytest

from app.query.binding.compile_v2 import COMPILER_ADAPTERS
from app.query.semantic.contract import (
    accessor_declaration,
    declared_accessors,
    load_access_contract,
)
from app.query.semantic.manifest_v002.projection import build_binder_projection
from app.query.semantic.manifest_v002.schema import (
    NON_QUERYABLE_COVERAGE,
    parse_manifest_v002,
)


# ---------------------------------------------------------------------------
# Contract loads and matches the compiler adapter registry (§3.3)
# ---------------------------------------------------------------------------


def test_contract_loads_v001():
    contract = load_access_contract()
    assert contract["contract_version"] == "v001"


def test_every_declared_accessor_has_a_compiler_adapter():
    """§3.3 direction 2: every backend compiler capability is in the contract,
    and every declared accessor has a registered adapter."""
    for accessor in declared_accessors():
        assert accessor in COMPILER_ADAPTERS, accessor


def test_no_adapter_accepts_an_undeclared_accessor():
    """§3.3 direction 1: no compiler adapter exists for an accessor the contract
    does not declare."""
    declared = set(declared_accessors())
    for accessor in COMPILER_ADAPTERS:
        assert accessor in declared, accessor


def test_adapter_uses_and_operators_are_a_subset_of_the_contract():
    for accessor, adapter in COMPILER_ADAPTERS.items():
        declaration = accessor_declaration(accessor)
        assert adapter.uses <= set(declaration["uses"]), accessor
        assert adapter.result_shapes <= set(declaration["result_shapes"]), accessor


# ---------------------------------------------------------------------------
# Manifest reader + projection over a small synthetic model
# ---------------------------------------------------------------------------


def _document():
    content = {
        "entity_total": 100,
        "class_inventory": [
            {"ifc_class": "IfcWall", "count": 52},
            {"ifc_class": "IfcWallStandardCase", "count": 48},
        ],
        "capabilities": [
            {
                "id": "cls:IfcWall",
                "kind": "class",
                "label": "Wall",
                "aliases": ["wall"],
                "grain": "entity",
                "uses": ["target", "topic_context"],
                "accessor": "entity.class",
                "executable": True,
                "applicability": [
                    {
                        "subject": "cls:IfcWall",
                        "coverage": "present_complete",
                        "known_count": 52,
                        "eligible_count": 52,
                        "can_prove_absence": True,
                    }
                ],
                "value_policy": "none",
                "values": [],
                "provenance": [],
            },
            {
                "id": "prop:Pset_WallCommon.FireRating",
                "kind": "field",
                "label": "Pset_WallCommon.FireRating",
                "aliases": ["fire rating", "fire rated"],
                "grain": "entity",
                "uses": ["filter", "group", "report"],
                "data_type": "text",
                "operators": ["equals", "is_present", "is_missing"],
                "accessor": "json.property_value",
                "executable": True,
                "applicability": [
                    {
                        "subject": "cls:IfcWall",
                        "coverage": "present_partial",
                        "known_count": 4,
                        "eligible_count": 52,
                    },
                    {
                        "subject": "cls:IfcWallStandardCase",
                        "coverage": "present_partial",
                        "known_count": 716,
                        "eligible_count": 1929,
                    },
                ],
                "value_policy": "enumerated",
                "values": [{"value": "EI60", "count": 720}],
                "provenance": ["property_sets.Pset_WallCommon.FireRating"],
                "physical": {
                    "source": "property_sets",
                    "set": "Pset_WallCommon",
                    "field": "FireRating",
                },
            },
            {
                "id": "prop:Other.Weird",
                "kind": "field",
                "label": "Other.Weird",
                "aliases": [],
                "grain": "entity",
                "uses": [],
                "accessor": "json.property_value",
                "executable": False,
                "limitation": "unsupported source structure",
                "applicability": [
                    {
                        "subject": "cls:*",
                        "coverage": "source_unresolvable",
                        "known_count": 0,
                        "eligible_count": 100,
                    }
                ],
                "value_policy": "none",
                "values": [],
                "provenance": [],
            },
        ],
        "traversals": [],
        "derived_floors": {
            "derivation_version": "floors_v001",
            "reference_index": 0,
            "reference_basis": "lowest_band",
            "bands": [],
        },
        "profiles": [],
        "spatial_membership": {"by_class": []},
        "storeys": [],
    }
    return {
        "identity": {
            "source_model_id": 7,
            "file_fingerprint": "f" * 64,
            "file_name": "syn.ifc",
            "ifc_schema": "IFC4",
            "extraction_version": "v002",
            "manifest_schema_version": "v002",
            "builder_version": "v002",
            "contract_version": "v001",
            "content_hash": "deadbeef",
        },
        "content": content,
    }


def test_applicability_is_kept_per_class():
    manifest = parse_manifest_v002(_document())
    fire = manifest.capabilities["prop:Pset_WallCommon.FireRating"]
    wall = fire.applicability_for("cls:IfcWall")
    std = fire.applicability_for("cls:IfcWallStandardCase")
    assert (wall.known_count, wall.eligible_count) == (4, 52)
    assert (std.known_count, std.eligible_count) == (716, 1929)
    # The distinction the v001 container-union lost is preserved.
    assert not wall.complete and not std.complete


def test_descriptive_only_concept_is_non_queryable():
    manifest = parse_manifest_v002(_document())
    weird = manifest.capabilities["prop:Other.Weird"]
    assert not weird.executable
    assert weird.applicability[0].coverage in NON_QUERYABLE_COVERAGE
    assert not weird.applicability[0].queryable


def test_projection_omits_descriptive_uses_and_stays_small():
    manifest = parse_manifest_v002(_document())
    projection = build_binder_projection(manifest)
    assert projection.estimated_tokens < 5000
    # The descriptive-only concept is present but flagged, not silently dropped.
    ids = {c["id"] for c in projection.payload["capabilities"]}
    assert "prop:Other.Weird" in ids
    weird = next(c for c in projection.payload["capabilities"] if c["id"] == "prop:Other.Weird")
    assert weird["executable"] is False
    # A full applicability with equal known/eligible collapses to a single int.
    wall = next(c for c in projection.payload["capabilities"] if c["id"] == "cls:IfcWall")
    assert wall["applies"]["IfcWall"] == 52


def test_projection_is_deterministic():
    manifest = parse_manifest_v002(_document())
    a = build_binder_projection(manifest)
    b = build_binder_projection(manifest)
    assert a.projection_hash == b.projection_hash
    assert a.json_text == b.json_text


def test_semantic_ids_up_to_120_chars_are_accepted():
    from app.llm.schemas_v2 import SEMANTIC_ID_MAX_LENGTH, TargetNode

    long_id = "prop:" + "X" * 110
    assert len(long_id) <= SEMANTIC_ID_MAX_LENGTH
    node = TargetNode(node_id="t1", semantic_id=long_id)
    assert node.semantic_id == long_id


def test_id_over_120_chars_is_rejected_by_the_schema():
    from pydantic import ValidationError

    from app.llm.schemas_v2 import TargetNode

    with pytest.raises(ValidationError):
        TargetNode(node_id="t1", semantic_id="p:" + "Y" * 200)
