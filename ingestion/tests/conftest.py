"""Shared fixtures — no database connection, no production embeddings."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _make_ifc_entity(
    global_id: str = "abc123",
    ifc_class: str = "IfcWall",
    is_relationship: bool = False,
    has_global_id: bool = True,
) -> MagicMock:
    entity = MagicMock()
    entity.GlobalId = global_id if has_global_id else None
    entity.is_a = MagicMock(
        side_effect=lambda cls=None: (
            (
                cls is not None
                and (
                    cls == ifc_class
                    or cls == "IfcRoot"
                    or (cls == "IfcRelationship" and is_relationship)
                )
            )
            if cls is not None
            else ifc_class
        )
    )
    entity.id = MagicMock(return_value=42)
    return entity


@pytest.fixture
def wall_entity():
    return _make_ifc_entity("WALL001", "IfcWall")


@pytest.fixture
def door_entity():
    return _make_ifc_entity("DOOR001", "IfcDoor")


@pytest.fixture
def storey_entity():
    return _make_ifc_entity("STOR001", "IfcBuildingStorey")


@pytest.fixture
def relationship_entity():
    return _make_ifc_entity("REL001", "IfcRelContainedInSpatialStructure", is_relationship=True)


@pytest.fixture
def no_global_id_entity():
    return _make_ifc_entity("", "IfcWall", has_global_id=False)


def minimal_canonical(
    ifc_class: str = "IfcWall",
    global_id: str = "WALL001",
    name: str | None = "W-001",
    storey_name: str | None = None,
    psets: dict | None = None,
    qsets: dict | None = None,
    materials: list | None = None,
    predefined_type: str | None = None,
) -> dict[str, Any]:
    return {
        "meta": {
            "step_id": 1,
            "global_id": global_id,
            "ifc_class": ifc_class,
            "predefined_type": predefined_type,
            "extraction_version": "v001",
        },
        "identity": {
            k: v
            for k, v in {
                "name": name,
                "description": None,
                "object_type": None,
                "tag": None,
            }.items()
            if v is not None
        },
        "storey": {"name": storey_name, "global_id": "STOR001"} if storey_name else None,
        "type": None,
        "materials": materials or [],
        "classifications": [],
        "property_sets": psets or {},
        "quantity_sets": qsets or {},
        "placement": {},
        "representation": {},
        "warnings": [],
    }
