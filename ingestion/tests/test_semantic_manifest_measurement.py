"""Manifest measurement facts and unit state (task27 §3, §7.2).

Deterministic and offline: the classification these tests exercise takes the
observed `(measure_type, unit_override_key, count)` groups and the model's own
unit registry, which is exactly what the builder reads out of the database. No
IFC is re-opened, no field name is consulted, and no production model appears.
"""

from __future__ import annotations

import pytest

from bim_rag.semantic_manifest.measurement import (
    MAX_UNIT_VARIANTS,
    UnitRegistryView,
    build_measure_facts,
    empty_measure_facts,
)
from bim_rag.semantic_manifest.schema import (
    MANIFEST_SCHEMA_VERSION,
    UNIT_STATE_MIXED,
    UNIT_STATE_UNIFORM,
    UNIT_STATE_UNKNOWN,
    build_document,
    validate_document,
)

MM = "lengthunit:mm"
M = "lengthunit:m"
M2 = "areaunit:m²"
FOOT = "lengthunit:foot"


def _registry(defaults: dict | None = None, unresolved: dict | None = None) -> UnitRegistryView:
    return UnitRegistryView(
        {
            "contract_version": "v001",
            "defaults": defaults
            if defaults is not None
            else {"length": MM, "area": M2, "volume": None},
            "definitions": {
                MM: {"unit_kind": "si", "symbol": "mm", "resolved": True},
                M: {"unit_kind": "si", "symbol": "m", "resolved": True},
                M2: {"unit_kind": "si", "symbol": "m²", "resolved": True},
                FOOT: {"unit_kind": "conversion_based", "symbol": "foot", "resolved": True},
                "volumeunit:unresolved": {"unit_kind": "derived", "resolved": False},
            },
            "unresolved_defaults": unresolved or {},
        }
    )


def _facts(rows, registry=None, source="property", label="Pset_Any.Field"):
    return build_measure_facts(rows, registry or _registry(), measure_source=source, label=label)


# ---------------------------------------------------------------------------
# Uniform
# ---------------------------------------------------------------------------


def test_a_field_with_one_effective_unit_is_uniform_and_executable():
    facts = _facts([("length", None, 120)])
    assert facts.unit_state == UNIT_STATE_UNIFORM
    assert facts.measure_type == "length"
    assert facts.unit_symbol == "mm"
    assert facts.comparison_safe is True
    assert facts.limitation is None


def test_an_explicit_override_shared_by_every_value_is_still_uniform():
    facts = _facts([("length", M, 40)])
    assert facts.unit_state == UNIT_STATE_UNIFORM
    # The override wins over the model default, exactly as the query path
    # resolves it: `unit_override_key` otherwise `defaults[measure_type]`.
    assert facts.unit_symbol == "m"


def test_the_record_reports_measure_type_source_unit_and_safety():
    record = _facts([("area", None, 9)], source="quantity", label="Qto_Any.GrossArea").to_record()
    assert record["measure_type"] == "area"
    assert record["measure_source"] == "quantity"
    assert record["unit_state"] == UNIT_STATE_UNIFORM
    assert record["unit_symbol"] == "m²"
    assert record["unit_key"] == M2
    assert record["numeric_comparison_safe"] is True


def test_classification_is_deterministic():
    rows = [("length", None, 3), ("length", M, 2)]
    assert _facts(rows).to_record() == _facts(rows).to_record()


# ---------------------------------------------------------------------------
# Mixed
# ---------------------------------------------------------------------------


def test_values_in_two_units_are_mixed_and_unsafe():
    facts = _facts([("length", None, 30), ("length", M, 12)])
    assert facts.unit_state == UNIT_STATE_MIXED
    assert facts.comparison_safe is False
    assert "not on one scale" in facts.limitation
    assert facts.unit_symbol is None


def test_a_mixed_field_lists_its_observed_units_with_exact_counts():
    facts = _facts([("length", None, 30), ("length", M, 12), ("length", FOOT, 1)])
    variants = {v["symbol"]: v["count"] for v in facts.variants}
    assert variants == {"mm": 30, "m": 12, "foot": 1}


def test_the_variant_list_is_bounded_but_the_state_is_not_softened():
    rows = [("length", f"lengthunit:u{i}", 1) for i in range(MAX_UNIT_VARIANTS + 5)]
    facts = _facts(rows)
    assert facts.unit_state == UNIT_STATE_MIXED
    assert facts.comparison_safe is False
    assert len(facts.variants) == MAX_UNIT_VARIANTS
    # The COUNT stays exact even though the enumeration is capped.
    assert facts.typed_count == MAX_UNIT_VARIANTS + 5


# ---------------------------------------------------------------------------
# Unknown
# ---------------------------------------------------------------------------


def test_a_measure_type_with_no_project_default_is_unknown_not_assumed():
    registry = _registry(unresolved={"volume": "IfcProject.UnitsInContext declares no VOLUMEUNIT"})
    facts = _facts([("volume", None, 50)], registry=registry)
    assert facts.unit_state == UNIT_STATE_UNKNOWN
    assert facts.comparison_safe is False
    assert "VOLUMEUNIT" in facts.limitation


def test_a_partially_typed_field_is_unknown_rather_than_measured():
    """Some occurrences typed, some not — the remainder cannot be resolved.

    Treating this as measured would put untyped numbers on a scale they were
    never declared to be on.
    """
    facts = _facts([("length", None, 30), (None, None, 4)])
    assert facts.unit_state == UNIT_STATE_UNKNOWN
    assert facts.comparison_safe is False
    assert facts.untyped_count == 4
    assert "no IFC measure type" in facts.limitation


def test_conflicting_measure_types_on_one_field_are_unknown():
    facts = _facts([("length", None, 10), ("area", None, 3)])
    assert facts.unit_state == UNIT_STATE_UNKNOWN
    assert facts.measure_type is None
    assert facts.measure_type_variants == ("area", "length")
    assert "more than one IFC measure type" in facts.limitation


def test_a_unit_definition_that_cannot_be_displayed_is_unknown():
    facts = _facts([("volume", "volumeunit:unresolved", 8)])
    assert facts.unit_state == UNIT_STATE_UNKNOWN
    assert facts.comparison_safe is False


# ---------------------------------------------------------------------------
# Not dimensional at all
# ---------------------------------------------------------------------------


def test_an_untyped_numeric_field_gets_no_measurement_record():
    """§1.2 in the manifest: a name never promotes a number to a dimension."""
    facts = _facts([(None, None, 900)])
    assert facts.is_measured is False
    assert facts.to_record() == {}


def test_empty_measure_facts_are_not_measured():
    assert empty_measure_facts().is_measured is False
    assert empty_measure_facts().to_record() == {}


# ---------------------------------------------------------------------------
# Document-level validation
# ---------------------------------------------------------------------------


def _document(field_record: dict) -> dict:
    return build_document(
        source_model_id=1,
        file_fingerprint="f" * 64,
        file_name="synthetic.ifc",
        ifc_schema="IFC4",
        extraction_version="v002",
        content={
            "object_level": {"classes": [{"id": "cls:IfcWall", "ifc_class": "IfcWall"}]},
            "type_property_level": {
                "property_containers": [
                    {"id": "propset:Pset_Any", "container": "Pset_Any", "fields": [field_record]}
                ]
            },
            "relationship_level": {"relationship_classes": []},
            "global_level": {"entity_total": 1, "missing_capabilities": []},
        },
    )


def test_a_valid_measured_field_passes_document_validation():
    record = {"id": "prop:Pset_Any.Width", "field": "Width"}
    record.update(_facts([("length", None, 5)]).to_record())
    assert validate_document(_document(record)) == []


def test_an_unknown_unit_state_is_rejected():
    problems = validate_document(
        _document({"id": "prop:Pset_Any.Width", "field": "Width", "unit_state": "probably_mm"})
    )
    assert any("unknown unit state" in p for p in problems)


def test_claiming_uniform_without_naming_a_unit_is_rejected():
    """ "Safe to aggregate" with no unit to report is not a state that may exist."""
    problems = validate_document(
        _document(
            {
                "id": "prop:Pset_Any.Width",
                "field": "Width",
                "unit_state": UNIT_STATE_UNIFORM,
                "numeric_comparison_safe": True,
            }
        )
    )
    assert any("names no unit symbol" in p for p in problems)


def test_claiming_uniform_without_being_comparison_safe_is_rejected():
    problems = validate_document(
        _document(
            {
                "id": "prop:Pset_Any.Width",
                "field": "Width",
                "unit_state": UNIT_STATE_UNIFORM,
                "unit_symbol": "mm",
                "numeric_comparison_safe": False,
            }
        )
    )
    assert any("not marked comparison-safe" in p for p in problems)


def test_a_manifest_from_the_previous_contract_is_rejected_as_stale():
    """A v001 artifact predates measure types entirely (§3).

    Reading one would present numeric fields whose unit state is simply unknown
    as though they had been checked.
    """
    document = _document({"id": "prop:Pset_Any.Width", "field": "Width"})
    document["identity"]["manifest_schema_version"] = "v001"
    problems = validate_document(document)
    assert any("manifest_schema_version" in p for p in problems)
    assert MANIFEST_SCHEMA_VERSION != "v001"


# ---------------------------------------------------------------------------
# Registry view
# ---------------------------------------------------------------------------


def test_an_unresolved_definition_yields_no_symbol():
    assert _registry().symbol("volumeunit:unresolved") is None


def test_an_unknown_unit_key_yields_no_symbol():
    assert _registry().symbol("lengthunit:parsec") is None
    assert _registry().symbol(None) is None


def test_the_registry_content_is_key_sorted():
    content = _registry().to_content()
    assert list(content["definitions"]) == sorted(content["definitions"])
    assert list(content["defaults"]) == sorted(content["defaults"])


@pytest.mark.parametrize("measure_type", ["length", "area", "volume"])
def test_the_default_key_lookup_never_invents_one(measure_type):
    registry = UnitRegistryView({"defaults": {}, "definitions": {}})
    assert registry.default_key(measure_type) is None
