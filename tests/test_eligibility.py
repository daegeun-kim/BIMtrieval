"""Tests: entity eligibility and IfcRelationship exclusion (spec §5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from bim_rag.ifc_parser import is_eligible, is_ifcrelationship


def _entity(ifc_class: str, global_id: str | None = "GID001") -> MagicMock:
    e = MagicMock()
    e.GlobalId = global_id
    relationship_classes = {
        "IfcRelationship",
        "IfcRelContainedInSpatialStructure",
        "IfcRelDefinesByProperties",
        "IfcRelAggregates",
        "IfcRelAssociatesMaterial",
    }

    def is_a(cls=None):
        if cls is None:
            return ifc_class
        if cls == ifc_class:
            return True
        if cls == "IfcRoot" and ifc_class != "IfcRepresentation":
            return True
        if cls == "IfcRelationship" and ifc_class in relationship_classes:
            return True
        return False

    e.is_a = is_a
    return e


def test_wall_is_eligible():
    assert is_eligible(_entity("IfcWall")) is True


def test_door_is_eligible():
    assert is_eligible(_entity("IfcDoor")) is True


def test_storey_is_eligible():
    assert is_eligible(_entity("IfcBuildingStorey")) is True


def test_space_is_eligible():
    assert is_eligible(_entity("IfcSpace")) is True


def test_relationship_excluded():
    assert is_eligible(_entity("IfcRelContainedInSpatialStructure")) is False


def test_relationship_defines_properties_excluded():
    assert is_eligible(_entity("IfcRelDefinesByProperties")) is False


def test_relationship_aggregates_excluded():
    assert is_eligible(_entity("IfcRelAggregates")) is False


def test_no_global_id_excluded():
    assert is_eligible(_entity("IfcWall", global_id=None)) is False


def test_empty_global_id_excluded():
    assert is_eligible(_entity("IfcWall", global_id="")) is False


def test_is_ifcrelationship_true():
    e = _entity("IfcRelContainedInSpatialStructure")
    assert is_ifcrelationship(e) is True


def test_is_ifcrelationship_false_for_wall():
    e = _entity("IfcWall")
    assert is_ifcrelationship(e) is False


def test_non_root_entity_excluded():
    e = MagicMock()
    e.GlobalId = "GID001"
    e.is_a = lambda cls=None: (cls == "IfcRepresentation") if cls else "IfcRepresentation"
    assert is_eligible(e) is False
