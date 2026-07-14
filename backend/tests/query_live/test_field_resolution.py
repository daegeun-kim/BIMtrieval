"""Deterministic field resolution across attributes/dimensions/quantities/
properties/type_facts, with provenance, plus ambiguous-concept resolution
(spec_v003 §8), live."""

from __future__ import annotations

import pytest
from query.sql.errors import AmbiguousFieldError, FieldNotFoundError
from query.sql.field_registry import (
    build_schema_catalog,
    resolve_concept,
    resolve_field,
)
from query.sql.schemas import FieldKind, FieldRef

from .conftest import SOURCE_MODEL_ID


def test_schema_catalog_reflects_real_sparse_data(live_session):
    """This model's ingestion output has exactly one property-set bucket and
    no quantity data — the catalog must report that honestly, not assume a
    clean Pset_XxxCommon/BaseQuantities structure."""
    catalog = build_schema_catalog(live_session, SOURCE_MODEL_ID)
    assert catalog.property_sets.keys() == {"SynchroResourceProperty"}
    assert (
        catalog.property_sets_truncated["SynchroResourceProperty"] is True
    )  # >500 real property names
    assert catalog.quantity_sets == {}
    assert "IfcDoor" in catalog.entity_classes
    assert "IfcRelContainedInSpatialStructure" in catalog.relationship_classes


def test_resolve_attribute_field_with_provenance(live_session):
    resolved = resolve_field(
        live_session, SOURCE_MODEL_ID, FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name")
    )
    assert resolved.provenance == "ifc_extracted"
    assert resolved.access_kind == "jsonb"
    assert resolved.json_path == ("identity", "name")


def test_resolve_direct_column_attribute(live_session):
    resolved = resolve_field(
        live_session,
        SOURCE_MODEL_ID,
        FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="global_id"),
    )
    assert resolved.access_kind == "column"
    assert resolved.column_name == "global_id"


def test_resolve_real_property_field_with_provenance(live_session):
    catalog = build_schema_catalog(live_session, SOURCE_MODEL_ID)
    sample_prop = catalog.property_sets["SynchroResourceProperty"][0]
    resolved = resolve_field(
        live_session,
        SOURCE_MODEL_ID,
        FieldRef(
            field_kind=FieldKind.PROPERTY,
            set_name="SynchroResourceProperty",
            field_name=sample_prop,
        ),
    )
    assert resolved.provenance == "ifc_extracted"
    assert resolved.json_path == ("property_sets", "SynchroResourceProperty", sample_prop, "value")


def test_resolve_nonexistent_property_raises(live_session):
    with pytest.raises(FieldNotFoundError):
        resolve_field(
            live_session,
            SOURCE_MODEL_ID,
            FieldRef(
                field_kind=FieldKind.PROPERTY,
                set_name="SynchroResourceProperty",
                field_name="does-not-exist",
            ),
        )


def test_resolve_quantity_absent_in_this_model_raises(live_session):
    """Honest 'absent', not a fabricated match — this model's ingestion output
    has zero populated quantity_sets."""
    with pytest.raises(FieldNotFoundError):
        resolve_field(
            live_session,
            SOURCE_MODEL_ID,
            FieldRef(field_kind=FieldKind.QUANTITY, set_name="BaseQuantities", field_name="Width"),
        )


def test_resolve_dimension_absent_in_this_model_raises(live_session):
    with pytest.raises(FieldNotFoundError):
        resolve_field(
            live_session,
            SOURCE_MODEL_ID,
            FieldRef(field_kind=FieldKind.DIMENSION, field_name="Width"),
        )


def test_resolve_type_fact_field(live_session):
    resolved = resolve_field(
        live_session,
        SOURCE_MODEL_ID,
        FieldRef(field_kind=FieldKind.TYPE_FACT, field_name="type_name"),
    )
    assert resolved.json_path == ("type", "name")


def test_resolve_concept_returns_single_attribute_match(live_session):
    """'name' only resolves via the attribute source in this model (no property/
    quantity set is literally named 'name')."""
    matches = resolve_concept(live_session, SOURCE_MODEL_ID, "name")
    assert len(matches) == 1
    assert matches[0].field_kind is FieldKind.ATTRIBUTE


def test_resolve_concept_no_match_returns_empty_list(live_session):
    matches = resolve_concept(live_session, SOURCE_MODEL_ID, "totally-nonexistent-concept-xyz")
    assert matches == []


def test_ambiguous_field_error_carries_candidates():
    """Direct unit test of the AmbiguousFieldError shape used when a DIMENSION
    name exists in more than one quantity set (spec_v003 §8: 'return all
    relevant values rather than silently choosing one'). This model has no
    populated quantity_sets, so ambiguity is exercised structurally here
    rather than against live rows."""
    err = AmbiguousFieldError(
        "Width exists in multiple quantity sets",
        candidates=[
            {"field_kind": "quantity", "set_name": "BaseQuantities", "field_name": "Width"},
            {"field_kind": "quantity", "set_name": "CustomQuantities", "field_name": "Width"},
        ],
    )
    assert len(err.candidates) == 2
