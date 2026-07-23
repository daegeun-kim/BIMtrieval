"""Offline unit tests for the task26 ingestion additions.

Covers the contract reader, the wrapper-key parser, the schedule-matrix
structure rule, floor-band derivation/classification, the unit registry
annotations, manifest v002 validation, and bounded semantic IDs. No database.
"""

from __future__ import annotations

import pytest

from bim_rag.contract import (
    accessor_declaration,
    load_access_contract,
    operators_for,
)
from bim_rag.ifc_parser import _annotate_measure
from bim_rag.semantic_manifest.builder_v002 import (
    _WRAPPER_KEY_RE,
    _bounded_id,
    _coverage_state,
)
from bim_rag.semantic_manifest.coverage import ContainerShape, classify_container_structure
from bim_rag.semantic_manifest.floors import (
    DerivedBand,
    StoreyFact,
    build_bands,
    classify_band,
)
from bim_rag.semantic_manifest.schema_v002 import (
    build_document_v002,
    validate_document_v002,
)

# ---------------------------------------------------------------------------
# Contract reader
# ---------------------------------------------------------------------------


def test_contract_loads_and_declares_core_accessors():
    contract = load_access_contract()
    assert contract["contract_version"] == "v001"
    for accessor in (
        "entity.class",
        "json.property_value",
        "json.material_name",
        "json.classification_field",
        "spatial.effective_membership",
        "relationship.member_edge",
        "derived.physical_floor",
        "derived.building_profile",
        "derived.thematic_profile",
    ):
        declaration = accessor_declaration(accessor)
        assert declaration["uses"], accessor


def test_contract_unknown_accessor_raises():
    with pytest.raises(KeyError):
        accessor_declaration("json.nonexistent")


def test_operators_per_data_type():
    assert "between" in operators_for("number")
    assert "contains" in operators_for("text")
    assert "contains" not in operators_for("boolean")


# ---------------------------------------------------------------------------
# Wrapper key parsing (reversible namespace syntax only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "ns", "field"),
    [
        ("[ArchiCADProperties]Layer", "ArchiCADProperties", "Layer"),
        (
            "[ArchiCADQuantities[IfcElementQuantity/ArchiCAD BIM Quantities]]Net Volume",
            "ArchiCADQuantities[IfcElementQuantity/ArchiCAD BIM Quantities]",
            "Net Volume",
        ),
        ("[Pset_WallCommon]IsExternal", "Pset_WallCommon", "IsExternal"),
    ],
)
def test_wrapper_key_parses(key, ns, field):
    match = _WRAPPER_KEY_RE.match(key)
    assert match is not None
    assert match.group("ns") == ns
    assert match.group("field") == field


@pytest.mark.parametrize("key", ["PlainField", "NoBracket]x", "[Unclosed"])
def test_wrapper_key_rejects_unparseable(key):
    assert _WRAPPER_KEY_RE.match(key) is None


# ---------------------------------------------------------------------------
# Schedule-matrix container rule (§4.4)
# ---------------------------------------------------------------------------


def test_per_instance_schedule_matrix_is_unreliable():
    # 415 field names carried by only 59 occurrences, each occurrence carrying
    # the whole matrix: ratio ~1.0 but structurally per-instance data.
    shape = ContainerShape(
        container="AC_Pset_R1_18",
        distinct_field_count=415,
        occurrence_count=59,
        field_instance_count=24485,
    )
    assert not classify_container_structure(shape).reliable


def test_stable_shared_schema_stays_reliable():
    shape = ContainerShape(
        container="Other",
        distinct_field_count=67,
        occurrence_count=18013,
        field_instance_count=280000,
    )
    assert classify_container_structure(shape).reliable


def test_small_containers_are_always_representable():
    shape = ContainerShape(
        container="Tiny", distinct_field_count=6, occurrence_count=2, field_instance_count=7
    )
    assert classify_container_structure(shape).reliable


# ---------------------------------------------------------------------------
# Floor bands (§5.5)
# ---------------------------------------------------------------------------


def _storeys(*elevations):
    return [StoreyFact(global_id=f"S{i}", name=None, elevation=e) for i, e in enumerate(elevations)]


def test_sublevels_group_into_one_band():
    bands = build_bands(_storeys(0.0, 0.05, 3.0, 3.05, 6.0))
    assert len(bands) == 3


def test_extreme_outlier_gap_does_not_merge_real_floors():
    # A detached site storey 500 units away must not inflate the reference gap
    # so far that the 3-unit floor separations merge.
    bands = build_bands(_storeys(0.0, 3.0, 6.0, 9.0, 500.0))
    assert len(bands) == 5


def _band(evidence, names=(None,)):
    band = DerivedBand(
        index=0,
        storeys=[
            StoreyFact(global_id=f"G{i}", name=name, elevation=0.0)
            for i, name in enumerate(names)
        ],
    )
    by_storey = {s.global_id: dict(evidence) for s in band.storeys}
    classify_band(band, by_storey)
    return band


def test_strong_occupancy_classifies_occupiable():
    band = _band({"entities": 100, "walls": 40, "doors": 5, "spaces": 10})
    assert band.classification == "occupiable"
    assert band.confidence == "high"


def test_spaces_without_corroboration_is_uncertain():
    band = _band({"entities": 6, "spaces": 6})
    assert band.classification == "uncertain"


def test_roof_named_band_without_occupancy_is_reference():
    band = _band({"entities": 2, "slabs": 2}, names=("Roof",))
    assert band.classification == "non_occupiable_reference"


def test_roof_named_band_with_occupancy_is_uncertain():
    band = _band({"entities": 50, "walls": 15, "doors": 13, "slabs": 20}, names=("Roof floor",))
    assert band.classification == "uncertain"


def test_empty_band_is_reference():
    band = _band({})
    assert band.classification == "non_occupiable_reference"


# ---------------------------------------------------------------------------
# Unit annotations (§4.3)
# ---------------------------------------------------------------------------

_REGISTRY = {"LENGTHUNIT": {"factor": 0.001, "unit": "m"}, "AREAUNIT": {"factor": 1e-6, "unit": "m2"}}


def test_known_unit_normalizes():
    entry = {"value": 2500.0}
    _annotate_measure(entry, "IfcLengthMeasure", _REGISTRY)
    assert entry["unit_state"] == "known"
    assert entry["normalized_value"] == 2.5
    assert entry["normalized_unit"] == "m"


def test_area_uses_area_unit():
    entry = {"value": 5_000_000.0}
    _annotate_measure(entry, "IfcAreaMeasure", _REGISTRY)
    assert entry["unit_state"] == "known"
    assert entry["normalized_unit"] == "m2"
    assert entry["normalized_value"] == 5.0


def test_ratio_measure_is_unitless():
    entry = {"value": 0.4}
    _annotate_measure(entry, "IfcRatioMeasure", _REGISTRY)
    assert entry["unit_state"] == "unitless"
    assert "normalized_value" not in entry


def test_unknown_measure_keeps_unknown_unit_state():
    entry = {"value": 12.0}
    _annotate_measure(entry, "IfcThermalTransmittanceMeasure", _REGISTRY)
    assert entry["unit_state"] == "unknown"
    assert "normalized_value" not in entry


def test_missing_registry_entry_is_unknown_not_guessed():
    entry = {"value": 3.0}
    _annotate_measure(entry, "IfcVolumeMeasure", _REGISTRY)  # no VOLUMEUNIT in registry
    assert entry["unit_state"] == "unknown"


def test_text_values_are_untouched():
    entry = {"value": "EI60"}
    _annotate_measure(entry, "IfcLabel", _REGISTRY)
    assert "unit_state" not in entry


# ---------------------------------------------------------------------------
# v002 document validation (§5, §3.3 ingestion half)
# ---------------------------------------------------------------------------


def _minimal_content(**overrides):
    content = {
        "entity_total": 1,
        "class_inventory": [{"ifc_class": "IfcWall", "count": 1}],
        "capabilities": [
            {
                "id": "cls:IfcWall",
                "kind": "class",
                "label": "Wall",
                "aliases": ["wall"],
                "grain": "entity",
                "uses": ["target"],
                "accessor": "entity.class",
                "executable": True,
                "applicability": [
                    {
                        "subject": "cls:IfcWall",
                        "coverage": "present_complete",
                        "known_count": 1,
                        "eligible_count": 1,
                        "can_prove_absence": True,
                    }
                ],
                "value_policy": "none",
                "values": [],
                "provenance": ["ifc_entities.ifc_class=IfcWall"],
            }
        ],
        "traversals": [],
        "derived_floors": {
            "derivation_version": "floors_v001",
            "reference_index": None,
            "reference_basis": "none",
            "bands": [],
        },
        "profiles": [],
        "spatial_membership": {"by_class": []},
        "storeys": [],
    }
    content.update(overrides)
    return content


def _document(content):
    return build_document_v002(
        source_model_id=1,
        file_fingerprint="f" * 64,
        file_name="test.ifc",
        ifc_schema="IFC4",
        extraction_version="v002",
        content=content,
    )


def test_valid_minimal_document_passes():
    assert validate_document_v002(_document(_minimal_content())) == []


def test_executable_capability_with_undeclared_accessor_fails():
    content = _minimal_content()
    content["capabilities"][0]["accessor"] = "json.made_up"
    problems = validate_document_v002(_document(content))
    assert any("undeclared" in p for p in problems)


def test_use_not_permitted_by_accessor_fails():
    content = _minimal_content()
    content["capabilities"][0]["uses"] = ["aggregate"]  # entity.class cannot aggregate
    problems = validate_document_v002(_document(content))
    assert any("not permitted" in p for p in problems)


def test_descriptive_capability_requires_limitation():
    content = _minimal_content()
    content["capabilities"][0]["executable"] = False
    problems = validate_document_v002(_document(content))
    assert any("limitation" in p for p in problems)


def test_duplicate_semantic_ids_fail():
    content = _minimal_content()
    content["capabilities"].append(dict(content["capabilities"][0]))
    problems = validate_document_v002(_document(content))
    assert any("duplicate" in p for p in problems)


def test_tampered_content_hash_fails():
    document = _document(_minimal_content())
    document["content"]["entity_total"] = 2
    problems = validate_document_v002(document)
    assert any("content_hash" in p for p in problems)


# ---------------------------------------------------------------------------
# Bounded IDs and coverage states
# ---------------------------------------------------------------------------


def test_long_ids_are_bounded_and_stable():
    raw = "prop:" + "X" * 200
    first = _bounded_id(raw)
    assert len(first) <= 120
    assert first == _bounded_id(raw)
    assert first != _bounded_id(raw + "Y")


def test_coverage_states():
    assert _coverage_state(0, 10) == "checked_absent"
    assert _coverage_state(3, 10) == "present_partial"
    assert _coverage_state(10, 10) == "present_complete"
