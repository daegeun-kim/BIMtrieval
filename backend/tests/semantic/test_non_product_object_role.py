"""A non-product `IfcObject` may be the result of a question (Task 24 §3.2).

Offline, ontology-only. The hypothesis under test is that role assignment
conflated "not a physical product" with "not a legitimate answer", making every
question about a process, group, system or actor structurally unanswerable —
`IfcTask is a other and cannot be the result of a question about objects` — even
though those records are ingested, GlobalId-bearing and queryable.

The boundary that must NOT move: a definition describes other things and a
relationship connects them, so neither is ever a result.
"""

from __future__ import annotations

import pytest

from app.query.semantic.roles import SchemaRole, get_role_index, is_result_kind


@pytest.fixture(scope="module")
def index():
    return get_role_index("IFC2X3")


@pytest.mark.parametrize(
    "ifc_class", ["IfcTask", "IfcGroup", "IfcWorkSchedule", "IfcWorkPlan", "IfcActor"]
)
def test_a_non_product_object_can_be_an_answer(index, ifc_class):
    role = index.role(ifc_class)
    assert role is SchemaRole.NON_PRODUCT_OBJECT
    assert is_result_kind(role)


@pytest.mark.parametrize("ifc_class", ["IfcWall", "IfcDoor", "IfcFlowTerminal", "IfcCovering"])
def test_products_are_still_occurrences(index, ifc_class):
    assert index.role(ifc_class) is SchemaRole.OCCURRENCE
    assert is_result_kind(index.role(ifc_class))


@pytest.mark.parametrize("ifc_class", ["IfcBuildingStorey", "IfcSpace", "IfcSite"])
def test_spatial_structure_is_unchanged(index, ifc_class):
    assert index.role(ifc_class) is SchemaRole.SPATIAL_STRUCTURE


@pytest.mark.parametrize(
    "ifc_class, role",
    [
        ("IfcDoorStyle", SchemaRole.TYPE_DEFINITION),
        ("IfcWallType", SchemaRole.TYPE_DEFINITION),
        ("IfcPropertySet", SchemaRole.PROPERTY_DEFINITION),
        ("IfcDoorPanelProperties", SchemaRole.PROPERTY_DEFINITION),
        ("IfcRelAggregates", SchemaRole.RELATIONSHIP),
        ("IfcRelFillsElement", SchemaRole.RELATIONSHIP),
    ],
)
def test_definitions_and_relationships_are_still_never_a_result(index, ifc_class, role):
    """Widening the result kinds must not let a type/style or a relationship into
    an occurrence answer — that is the defect the role registry exists to stop."""
    assert index.role(ifc_class) is role
    assert not is_result_kind(index.role(ifc_class))


def test_a_task_closure_does_not_absorb_unrelated_classes(index):
    """Admitting a role must not widen what a request for it means."""
    assert index.closure("IfcTask", {"IfcTask", "IfcWall", "IfcDoor"}) == ("IfcTask",)
