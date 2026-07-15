"""Allowlisted IFC relationship class -> semantic role + exact schema role
names (spec_v003 §12).

Spec-complete: covers every class the spec names (containment, aggregation,
type, property, material, opening/filling, grouping, boundary, connection)
even though several have zero rows in the currently-ingested Schependomlaan
model — other future models may populate them. Also covers the
schedule/process classes (`IfcRelAssignsTasks`, `IfcRelAssignsToProcess`,
`IfcRelSequence`) that ARE present in this model but aren't named in the
spec's building-element-focused list; without an entry these would be
silently unsupported by traversal even though they're valid stored
relationships that must support "direct endpoint inspection" (spec_v003
§12: "every stored relationship class").

Role names verified against this model's actual `relationship_members.role`
values (not guessed from the abstract IFC schema) for all six classes
currently present.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RelationshipSemanticRole(str, Enum):
    CONTAINMENT = "containment"
    AGGREGATION = "aggregation"
    TYPE_DEFINITION = "type_definition"
    PROPERTY_DEFINITION = "property_definition"
    MATERIAL_ASSOCIATION = "material_association"
    OPENING_FILLING = "opening_filling"
    GROUPING = "grouping"
    BOUNDARY = "boundary"
    CONNECTION = "connection"
    PROCESS_RELATIONSHIP = "process_relationship"


@dataclass(frozen=True)
class RelationshipRegistryEntry:
    ifc_class: str
    semantic_role: RelationshipSemanticRole
    relating_roles: tuple[str, ...]
    related_roles: tuple[str, ...]


REGISTRY: dict[str, RelationshipRegistryEntry] = {
    "IfcRelContainedInSpatialStructure": RelationshipRegistryEntry(
        "IfcRelContainedInSpatialStructure",
        RelationshipSemanticRole.CONTAINMENT,
        ("RelatingStructure",),
        ("RelatedElements",),
    ),
    "IfcRelAggregates": RelationshipRegistryEntry(
        "IfcRelAggregates",
        RelationshipSemanticRole.AGGREGATION,
        ("RelatingObject",),
        ("RelatedObjects",),
    ),
    "IfcRelDefinesByType": RelationshipRegistryEntry(
        "IfcRelDefinesByType",
        RelationshipSemanticRole.TYPE_DEFINITION,
        ("RelatingType",),
        ("RelatedObjects",),
    ),
    "IfcRelDefinesByProperties": RelationshipRegistryEntry(
        "IfcRelDefinesByProperties",
        RelationshipSemanticRole.PROPERTY_DEFINITION,
        ("RelatingPropertyDefinition",),
        ("RelatedObjects",),
    ),
    "IfcRelAssociatesMaterial": RelationshipRegistryEntry(
        "IfcRelAssociatesMaterial",
        RelationshipSemanticRole.MATERIAL_ASSOCIATION,
        ("RelatingMaterial",),
        ("RelatedObjects",),
    ),
    "IfcRelVoidsElement": RelationshipRegistryEntry(
        "IfcRelVoidsElement",
        RelationshipSemanticRole.OPENING_FILLING,
        ("RelatingBuildingElement",),
        ("RelatedOpeningElement",),
    ),
    "IfcRelFillsElement": RelationshipRegistryEntry(
        "IfcRelFillsElement",
        RelationshipSemanticRole.OPENING_FILLING,
        ("RelatingOpeningElement",),
        ("RelatedBuildingElement",),
    ),
    "IfcRelAssignsToGroup": RelationshipRegistryEntry(
        "IfcRelAssignsToGroup",
        RelationshipSemanticRole.GROUPING,
        ("RelatingGroup",),
        ("RelatedObjects",),
    ),
    "IfcRelSpaceBoundary": RelationshipRegistryEntry(
        "IfcRelSpaceBoundary",
        RelationshipSemanticRole.BOUNDARY,
        ("RelatingSpace",),
        ("RelatedBuildingElement",),
    ),
    "IfcRelConnectsElements": RelationshipRegistryEntry(
        "IfcRelConnectsElements",
        RelationshipSemanticRole.CONNECTION,
        ("RelatingElement",),
        ("RelatedElement",),
    ),
    "IfcRelConnectsPathElements": RelationshipRegistryEntry(
        "IfcRelConnectsPathElements",
        RelationshipSemanticRole.CONNECTION,
        ("RelatingElement",),
        ("RelatedElement",),
    ),
    # Present in the currently-ingested model (verified role names):
    "IfcRelAssignsTasks": RelationshipRegistryEntry(
        "IfcRelAssignsTasks",
        RelationshipSemanticRole.PROCESS_RELATIONSHIP,
        ("RelatingControl",),
        ("RelatedObjects", "TimeForTask"),
    ),
    "IfcRelAssignsToProcess": RelationshipRegistryEntry(
        "IfcRelAssignsToProcess",
        RelationshipSemanticRole.PROCESS_RELATIONSHIP,
        ("RelatingProcess",),
        ("RelatedObjects",),
    ),
    "IfcRelSequence": RelationshipRegistryEntry(
        "IfcRelSequence",
        RelationshipSemanticRole.PROCESS_RELATIONSHIP,
        ("RelatingProcess",),
        ("RelatedProcess",),
    ),
}
