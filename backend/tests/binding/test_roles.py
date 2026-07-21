"""IFC schema-role + family closure registry (Task 24 §3.2, §13.2).

Offline: reads the committed ontology JSON only. No DB, no OpenAI, no embedding.

These tests assert *IFC semantic rules*, never a sample question or an expected
count from `specs/test_query.md` (Task 24 §Non-negotiable generalization rule).
Every rule is checked on at least two unrelated class families so a fix that
only worked for one family cannot pass (§13.6).
"""

from __future__ import annotations

import pytest

from app.query.semantic.roles import (
    SchemaRole,
    family_closure,
    get_role_index,
    is_result_kind,
    occurrence_for_type,
    schema_role,
)


@pytest.fixture(scope="module")
def index():
    return get_role_index("IFC2X3")


# ---------------------------------------------------------------------------
# Role assignment — occurrence vs type definition vs everything else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ifc_class",
    ["IfcDoor", "IfcWindow", "IfcWall", "IfcColumn", "IfcBeam", "IfcCurtainWall", "IfcRailing"],
)
def test_building_elements_are_occurrences(ifc_class):
    assert schema_role(ifc_class) is SchemaRole.OCCURRENCE


@pytest.mark.parametrize(
    "ifc_class",
    ["IfcDoorStyle", "IfcWindowStyle", "IfcWallType", "IfcColumnType", "IfcFurnitureType"],
)
def test_type_and_style_classes_are_type_definitions(ifc_class):
    """§3.2: type/style/property-definition classes are not physical occurrences.

    Checked across both the IFC2X3 `*Style` and `*Type` spellings and across
    unrelated families, so this is a schema rule and not a door-specific patch.
    """
    assert schema_role(ifc_class) is SchemaRole.TYPE_DEFINITION
    assert not is_result_kind(schema_role(ifc_class))


@pytest.mark.parametrize("ifc_class", ["IfcSpace", "IfcBuildingStorey", "IfcBuilding", "IfcSite"])
def test_spatial_structure_classes(ifc_class):
    assert schema_role(ifc_class) is SchemaRole.SPATIAL_STRUCTURE


@pytest.mark.parametrize("ifc_class", ["IfcPropertySet", "IfcElementQuantity"])
def test_property_definitions(ifc_class):
    assert schema_role(ifc_class) is SchemaRole.PROPERTY_DEFINITION
    assert not is_result_kind(schema_role(ifc_class))


@pytest.mark.parametrize(
    "ifc_class",
    ["IfcRelContainedInSpatialStructure", "IfcRelAggregates", "IfcRelConnectsElements"],
)
def test_relationship_classes(ifc_class):
    """§3.2: relationships are evidence about endpoints, not occurrence results."""
    assert schema_role(ifc_class) is SchemaRole.RELATIONSHIP
    assert not is_result_kind(schema_role(ifc_class))


@pytest.mark.parametrize(
    ("type_class", "occurrence"),
    [
        ("IfcTransportElementType", "IfcTransportElement"),
        ("IfcDoorStyle", "IfcDoor"),
        ("IfcWindowStyle", "IfcWindow"),
        ("IfcWallType", "IfcWall"),
        ("IfcColumnType", "IfcColumn"),
    ],
)
def test_a_type_definition_resolves_to_its_occurrence_class(type_class, occurrence):
    """Regression guard for a defect this suite caught during implementation.

    IFC2X3 records predefined-type enumerations (ESCALATOR, ELEVATOR, …) on the
    `*Type` class ONLY, and the ontology does not link the type branch back to
    the occurrence branch. A question about escalators therefore reached
    `IfcTransportElementType` — a definition record — and was refused as
    "cannot be established" instead of answering the honest "this model has
    none". Asserted across five unrelated families so this is the IFC naming
    rule, not one class's special case.
    """
    assert occurrence_for_type(type_class) == occurrence


@pytest.mark.parametrize("ifc_class", ["IfcDoor", "IfcWall", "IfcSpace"])
def test_an_occurrence_class_has_no_type_pairing(ifc_class):
    assert occurrence_for_type(ifc_class) is None


def test_type_pairing_never_invents_a_class():
    """The derived name must actually exist as an occurrence in the ontology."""
    assert occurrence_for_type("IfcNotARealThingType") is None
    assert occurrence_for_type("IfcPropertySet") is None


def test_occurrence_and_spatial_structure_are_the_only_result_kinds():
    assert is_result_kind(SchemaRole.OCCURRENCE)
    assert is_result_kind(SchemaRole.SPATIAL_STRUCTURE)
    for role in (
        SchemaRole.TYPE_DEFINITION,
        SchemaRole.PROPERTY_DEFINITION,
        SchemaRole.RELATIONSHIP,
        SchemaRole.OTHER,
        SchemaRole.UNKNOWN,
    ):
        assert not is_result_kind(role)


# ---------------------------------------------------------------------------
# Truthful degradation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ifc_class", ["IfcDoorType", "IfcVendorExtensionThing", ""])
def test_classes_absent_from_the_schema_are_unknown_not_occurrence(ifc_class):
    """A class the ontology cannot describe must never be guessed into a role.

    `IfcDoorType` is a real IFC4 class that genuinely does not exist in IFC2X3,
    so this also covers the cross-schema case rather than only a nonsense name.
    """
    assert schema_role(ifc_class) is SchemaRole.UNKNOWN
    assert not is_result_kind(schema_role(ifc_class))
    assert family_closure(ifc_class) == ()


# ---------------------------------------------------------------------------
# Family closure — the §3.2 invariants
# ---------------------------------------------------------------------------


def test_generic_superclass_includes_present_subtypes():
    """§3.2: 'a generic superclass request includes applicable present occurrence
    subtypes'. Derived from ontology inheritance, not a hand-written alias table."""
    present = {"IfcWall", "IfcWallStandardCase"}
    assert family_closure("IfcWall", present) == ("IfcWall", "IfcWallStandardCase")


def test_explicit_subtype_request_stays_specific():
    """§3.2: 'an explicitly requested subtype remains specific'."""
    present = {"IfcWall", "IfcWallStandardCase"}
    assert family_closure("IfcWallStandardCase", present) == ("IfcWallStandardCase",)


def test_closure_is_intersected_with_what_the_model_actually_has():
    assert family_closure("IfcWall", {"IfcWall"}) == ("IfcWall",)
    assert family_closure("IfcWall", set()) == ()


@pytest.mark.parametrize(
    ("whole", "component"),
    [
        ("IfcStair", "IfcStairFlight"),
        ("IfcRamp", "IfcRampFlight"),
        ("IfcRoof", "IfcSlab"),
    ],
)
def test_related_components_are_not_absorbed_into_the_whole(whole, component):
    """§3.2: 'semantically related components are not descendants and are not
    automatically included'.

    In IFC these components are siblings under `IfcBuildingElement`, not
    descendants, so correct inheritance already excludes them. Asserting it here
    pins the behaviour against a future 'helpful' widening. Three unrelated
    whole/part pairs, so this cannot be satisfied by one special case.
    """
    present = {whole, component}
    closure = family_closure(whole, present)
    assert closure == (whole,)
    assert component not in closure


@pytest.mark.parametrize(
    ("occurrence", "type_definition"),
    [("IfcDoor", "IfcDoorStyle"), ("IfcWindow", "IfcWindowStyle")],
)
def test_occurrence_closure_never_includes_a_type_definition(occurrence, type_definition):
    """A requested occurrence cannot silently become a type definition."""
    present = {occurrence, type_definition}
    closure = family_closure(occurrence, present)
    assert closure == (occurrence,)
    assert type_definition not in closure


def test_closure_membership_shares_the_requested_role(index):
    """No closure may mix schema roles, for any class in the schema."""
    present = set(index.classes)
    for ifc_class, info in index.classes.items():
        for member in index.closure(ifc_class, present):
            assert index.role(member) is info.role


def test_closure_is_deterministic_and_leads_with_the_requested_class():
    present = {"IfcWall", "IfcWallStandardCase"}
    first = family_closure("IfcWall", present)
    assert first[0] == "IfcWall"
    assert first == family_closure("IfcWall", present)
    assert list(first[1:]) == sorted(first[1:])


# ---------------------------------------------------------------------------
# Anti-overfitting (§13.6)
# ---------------------------------------------------------------------------


def test_every_indexed_class_resolves_to_a_concrete_role(index):
    """No class in the loaded schema may fall through to UNKNOWN — that state is
    reserved for classes the ontology genuinely does not describe."""
    for ifc_class, info in index.classes.items():
        assert info.role is not SchemaRole.UNKNOWN, ifc_class


def test_role_partition_is_non_degenerate(index):
    """Guards against a marker-ordering regression collapsing everything into one
    role. Asserts the partition has substance, not specific tallies — a schema
    update may legitimately move the numbers."""
    counts: dict[SchemaRole, int] = {}
    for info in index.classes.values():
        counts[info.role] = counts.get(info.role, 0) + 1
    for role in (
        SchemaRole.OCCURRENCE,
        SchemaRole.TYPE_DEFINITION,
        SchemaRole.SPATIAL_STRUCTURE,
        SchemaRole.PROPERTY_DEFINITION,
        SchemaRole.RELATIONSHIP,
    ):
        assert counts.get(role, 0) > 0, role
    assert max(counts.values()) < len(index.classes)


def test_spatial_structure_is_ordered_before_product_in_marker_resolution():
    """`IfcSpace` descends from BOTH `IfcSpatialStructureElement` and `IfcProduct`.

    If the markers were tested in the wrong order it would resolve to
    `occurrence`, and a storey-entity count could then silently stand in for a
    logical floor count (§11.4). This pins the ordering itself.
    """
    assert schema_role("IfcSpace") is SchemaRole.SPATIAL_STRUCTURE
    assert schema_role("IfcBuildingStorey") is SchemaRole.SPATIAL_STRUCTURE


def test_type_definition_is_ordered_before_object_in_marker_resolution():
    """`IfcDoorStyle` descends from `IfcTypeObject` -> `IfcObjectDefinition`.
    A marker-order regression would make it an occurrence and let door styles
    join a door count."""
    assert schema_role("IfcDoorStyle") is SchemaRole.TYPE_DEFINITION
