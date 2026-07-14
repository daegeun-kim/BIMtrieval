"""Direct relationship listing/lookup/member inspection for every stored
relationship class (spec_v003 §12), live."""

from __future__ import annotations

import pytest
from query.sql import relationships
from query.sql.errors import UnknownEntityOrRelationshipError
from query.sql.schemas import GetRelationshipMembersPlan, GetRelationshipPlan, ListRelationshipsPlan

from .conftest import SOURCE_MODEL_ID

# Verified live counts (see task05 completion report).
_KNOWN_RELATIONSHIP_CLASSES = {
    "IfcRelDefinesByProperties": 3228,
    "IfcRelAssignsTasks": 125,
    "IfcRelAssignsToProcess": 73,
    "IfcRelSequence": 42,
    "IfcRelAggregates": 4,
    "IfcRelContainedInSpatialStructure": 1,
}


@pytest.mark.parametrize(
    "relationship_class,expected_count", list(_KNOWN_RELATIONSHIP_CLASSES.items())
)
def test_list_relationships_every_class_directly_inspectable(
    live_session, relationship_class, expected_count
):
    rows = relationships.list_relationships(
        live_session,
        ListRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID, relationship_classes=[relationship_class], limit=500
        ),
    )
    assert len(rows) == min(expected_count, 500)
    assert all(r.ifc_class == relationship_class for r in rows)


def test_get_relationship_by_id_and_global_id_agree(live_session):
    rows = relationships.list_relationships(
        live_session,
        ListRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID, relationship_classes=["IfcRelAggregates"], limit=1
        ),
    )
    target = rows[0]
    by_id = relationships.get_relationship(
        live_session,
        GetRelationshipPlan(source_model_id=SOURCE_MODEL_ID, relationship_id=target.id),
    )
    by_gid = relationships.get_relationship(
        live_session,
        GetRelationshipPlan(source_model_id=SOURCE_MODEL_ID, global_id=target.global_id),
    )
    assert by_id.id == by_gid.id == target.id


def test_get_relationship_not_found_raises(live_session):
    with pytest.raises(UnknownEntityOrRelationshipError):
        relationships.get_relationship(
            live_session,
            GetRelationshipPlan(source_model_id=SOURCE_MODEL_ID, relationship_id=999999999),
        )


def test_get_relationship_members_matches_known_member_count(live_session):
    rows = relationships.list_relationships(
        live_session,
        ListRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID, relationship_classes=["IfcRelAssignsTasks"], limit=1
        ),
    )
    members = relationships.get_relationship_members(
        live_session,
        GetRelationshipMembersPlan(source_model_id=SOURCE_MODEL_ID, relationship_id=rows[0].id),
    )
    # IfcRelAssignsTasks members: 1 RelatingControl + N RelatedObjects + 1 TimeForTask
    roles = {m.role for m in members}
    assert roles == {"RelatingControl", "RelatedObjects", "TimeForTask"}


def test_get_relationship_members_cross_model_isolation_rejected(live_session):
    """A relationship_id that exists but under a different declared source_model_id
    must be rejected, not silently served (spec_v003 §13)."""
    rows = relationships.list_relationships(
        live_session, ListRelationshipsPlan(source_model_id=SOURCE_MODEL_ID, limit=1)
    )
    with pytest.raises(UnknownEntityOrRelationshipError):
        relationships.get_relationship_members(
            live_session,
            GetRelationshipMembersPlan(source_model_id=999999, relationship_id=rows[0].id),
        )
