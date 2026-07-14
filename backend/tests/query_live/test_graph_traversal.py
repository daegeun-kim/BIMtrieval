"""IFC relationship-graph traversal: containment, aggregation, property
definition, and process relationships where present in this model
(spec_v003 §12), plus endpoint hydration, depth, cycles, and source
isolation, live."""

from __future__ import annotations

from query.graph.hydration import hydrate_traversal
from query.graph.traversal import traverse
from query.sql.schemas import TraverseRelationshipsPlan
from sqlalchemy import text
from viewer.actions import SelectionAction

from .conftest import SOURCE_MODEL_ID

DOOR_ENTITY_ID = 627
DOOR_GLOBAL_ID = "1Uo8RaB_bDWA9BY6VlAcwo"


def test_containment_traversal_where_present(live_session):
    """The single IfcRelContainedInSpatialStructure relationship holds the door."""
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            relationship_classes=["IfcRelContainedInSpatialStructure"],
            max_depth=1,
            direction="incoming",
        ),
    )
    assert len(result.hops) == 1
    hop = result.hops[0]
    assert hop.semantic_role == "containment"
    assert hop.to_entity_global_id == "2uHHjIJM98q8JM83XVa$l1"  # Storey-1, verified live


def test_aggregation_traversal_where_present(live_session):
    row = live_session.execute(
        text(
            "SELECT entity_id FROM relationship_members m JOIN ifc_relationships r "
            "ON r.id = m.relationship_id WHERE r.ifc_class = 'IfcRelAggregates' "
            "AND m.role = 'RelatingObject' AND m.source_model_id = :sid LIMIT 1"
        ),
        {"sid": SOURCE_MODEL_ID},
    ).first()
    assert row is not None
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[row[0]],
            relationship_classes=["IfcRelAggregates"],
            max_depth=1,
            direction="outgoing",
        ),
    )
    assert len(result.hops) >= 1
    assert all(h.semantic_role == "aggregation" for h in result.hops)


def test_property_definition_traversal_where_present(live_session):
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            relationship_classes=["IfcRelDefinesByProperties"],
            max_depth=1,
            direction="incoming",
        ),
    )
    assert len(result.hops) == 1
    assert result.hops[0].semantic_role == "property_definition"


def test_process_relationship_traversal_where_present(live_session):
    row = live_session.execute(
        text(
            "SELECT entity_id FROM relationship_members WHERE role = 'RelatingControl' "
            "AND entity_id IS NOT NULL AND source_model_id = :sid LIMIT 1"
        ),
        {"sid": SOURCE_MODEL_ID},
    ).first()
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[row[0]],
            relationship_classes=["IfcRelAssignsTasks"],
            max_depth=1,
            direction="outgoing",
        ),
    )
    assert len(result.hops) >= 1
    assert all(h.semantic_role == "process_relationship" for h in result.hops)


def test_depth_bound_is_respected(live_session):
    depth1 = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            relationship_classes=["IfcRelContainedInSpatialStructure"],
            max_depth=1,
            direction="incoming",
        ),
    )
    depth3 = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            relationship_classes=["IfcRelContainedInSpatialStructure"],
            max_depth=3,
            direction="both",
        ),
    )
    # depth 3 both-directions expands through the storey hub to every contained
    # element (a real characteristic of this model's single huge containment
    # relationship, not a traversal bug) — strictly larger than depth 1.
    assert len(depth3.context_entity_ids) > len(depth1.context_entity_ids)


def test_cycle_prevention_terminates(live_session):
    """A relationship whose endpoints loop back to an already-visited entity
    must not cause infinite growth — traversal must terminate within max_depth
    traversal levels regardless of graph structure."""
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            max_depth=3,
            direction="both",
        ),
    )
    # visited-set discipline: an entity_id never appears in both primary and context
    assert result.primary_entity_ids.isdisjoint(result.context_entity_ids)


def test_source_model_isolation_for_nonexistent_model(live_session):
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=999999, start_entity_ids=[DOOR_ENTITY_ID], max_depth=2
        ),
    )
    assert result.hops == []
    assert result.context_entity_ids == set()


def test_unsupported_relationship_class_is_warned_not_crashed(live_session):
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            relationship_classes=["IfcRelNotARealClass"],
            max_depth=1,
        ),
    )
    assert result.hops == []
    assert any("unsupported" in w for w in result.warnings)


def test_hydration_distinguishes_primary_from_context_and_uses_global_ids(live_session):
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[DOOR_ENTITY_ID],
            relationship_classes=["IfcRelContainedInSpatialStructure"],
            max_depth=1,
            direction="incoming",
        ),
    )
    primary, context, viewer_actions = hydrate_traversal(live_session, SOURCE_MODEL_ID, result)

    assert [p.global_id for p in primary] == [DOOR_GLOBAL_ID]
    assert len(context) == 1
    assert context[0].global_id == "2uHHjIJM98q8JM83XVa$l1"
    assert context[0].ifc_class == "IfcBuildingStorey"

    assert viewer_actions.selection_action is SelectionAction.SELECT_AND_FIT
    assert viewer_actions.primary_global_ids == [DOOR_GLOBAL_ID]
    assert viewer_actions.context_global_ids == ["2uHHjIJM98q8JM83XVa$l1"]
    role_by_name = {rg.role.value: rg.global_ids for rg in viewer_actions.role_groups}
    assert role_by_name["primary_match"] == [DOOR_GLOBAL_ID]
    assert role_by_name["relationship_context"] == ["2uHHjIJM98q8JM83XVa$l1"]
