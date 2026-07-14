"""Relationship semantic registry structure (spec_v003 §12). No database access."""

from __future__ import annotations

from query.graph.registry import REGISTRY, RelationshipSemanticRole

# Verified against this project's live database (relationship_members.role,
# grouped by ifc_relationships.ifc_class) — see task05 completion report.
_CLASSES_PRESENT_IN_CURRENT_MODEL = {
    "IfcRelAggregates",
    "IfcRelAssignsTasks",
    "IfcRelAssignsToProcess",
    "IfcRelContainedInSpatialStructure",
    "IfcRelDefinesByProperties",
    "IfcRelSequence",
}

_SPEC_NAMED_ROLES = {
    RelationshipSemanticRole.CONTAINMENT,
    RelationshipSemanticRole.AGGREGATION,
    RelationshipSemanticRole.TYPE_DEFINITION,
    RelationshipSemanticRole.PROPERTY_DEFINITION,
    RelationshipSemanticRole.MATERIAL_ASSOCIATION,
    RelationshipSemanticRole.OPENING_FILLING,
    RelationshipSemanticRole.GROUPING,
    RelationshipSemanticRole.BOUNDARY,
    RelationshipSemanticRole.CONNECTION,
}


def test_all_currently_present_classes_are_registered():
    assert _CLASSES_PRESENT_IN_CURRENT_MODEL.issubset(REGISTRY.keys())


def test_every_spec_named_role_has_at_least_one_registry_entry():
    covered_roles = {entry.semantic_role for entry in REGISTRY.values()}
    assert _SPEC_NAMED_ROLES.issubset(covered_roles)


def test_every_entry_has_nonempty_relating_and_related_roles():
    for ifc_class, entry in REGISTRY.items():
        assert entry.ifc_class == ifc_class
        assert len(entry.relating_roles) >= 1
        assert len(entry.related_roles) >= 1


def test_no_class_has_overlapping_relating_and_related_role_names():
    for entry in REGISTRY.values():
        assert set(entry.relating_roles).isdisjoint(entry.related_roles)
