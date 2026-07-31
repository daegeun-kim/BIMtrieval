"""The traversal statement is unchanged apart from its projection (task29 §1, §5.1).

Offline: the statement is compiled to SQL text and inspected, and the hop copy is
exercised with a fake traversal result. No DB connection, no OpenAI.

The whole permitted backend change for Task 29 is an additive presentation
transport. These tests pin that down from the direction that would actually
break: the FROM/JOIN/WHERE of the relationship-member statement, the number of
statements, and the reached endpoint set must all be identical — only the SELECT
list grew.
"""

from __future__ import annotations

import re

import sqlalchemy as sa

from app.query.binding.evidence import ResultExample
from app.query.binding.graph_exec import MAX_TOPOLOGY_HOPS, GraphExecution, _retain_topology
from app.query.graph import traversal as traversal_module
from app.query.graph.schemas import TraversalHop


def _compiled_statements() -> list[str]:
    """Compile every statement `_expand` builds, without executing any of them."""
    captured: list[str] = []

    class _RecordingSession:
        def execute(self, stmt):
            captured.append(str(stmt.compile(dialect=sa.dialects.postgresql.dialect())))
            return []

    traversal_module._expand(
        _RecordingSession(),
        1,
        {10, 11},
        {"IfcRelContainedInSpatialStructure"},
        set(),
        "outgoing",
    )
    return captured


def test_one_statement_per_class_per_direction_is_still_issued():
    assert len(_compiled_statements()) == 1


def test_the_joins_and_predicates_are_unchanged():
    sql = _compiled_statements()[0]
    lowered = sql.lower()
    # The same two member aliases joined to the relationship table, once each.
    assert lowered.count("join") == 2
    assert "m_from" in lowered and "m_to" in lowered
    # The same source-model isolation and role/frontier predicates.
    assert lowered.count("source_model_id = ") == 3
    for fragment in (
        "m_from.entity_id in ",
        "ifc_relationships.ifc_class = ",
        "m_from.role in ",
        "m_to.role in ",
        "m_to.id != m_from.id",
    ):
        assert fragment in lowered, fragment
    # No ordering, limit, grouping or extra filter was introduced.
    for forbidden in ("order by", "limit", "group by", "distinct", "union"):
        assert forbidden not in lowered, forbidden


def test_only_the_projection_grew_and_only_with_member_columns():
    sql = _compiled_statements()[0]
    select_list = re.split(r"\bFROM\b", sql, maxsplit=1)[0]
    # The pre-existing columns are still projected, unchanged…
    for existing in (
        "m_from.relationship_id",
        "ifc_relationships.global_id",
        "ifc_relationships.ifc_class",
        "m_from.entity_id",
        "m_to.entity_id",
        "m_to.endpoint_global_id",
    ):
        assert existing in select_list, existing
    # …and every added column comes off one of the two member rows already joined.
    for added in (
        "m_from.role",
        "m_to.role",
        "m_from.endpoint_global_id",
        "m_from.endpoint_ifc_class",
        "m_to.endpoint_ifc_class",
    ):
        assert added in select_list, added
    assert "canonical_json" not in select_list


# ---------------------------------------------------------------------------
# The retained hop copy (§5.1)
# ---------------------------------------------------------------------------


def _hop(relationship_id: int, from_entity_id: int, to_entity_id: int) -> TraversalHop:
    return TraversalHop(
        relationship_id=relationship_id,
        relationship_global_id=f"rel{relationship_id}",
        relationship_class="IfcRelContainedInSpatialStructure",
        semantic_role="containment",
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        to_entity_global_id=f"G{to_entity_id}",
    )


def test_retained_hops_are_restricted_to_the_seeds_and_accepted_endpoints():
    """A hop to an object the answer does not claim is not part of its topology."""
    execution = GraphExecution()
    hops = [_hop(1, 100, 10), _hop(2, 100, 99), _hop(3, 10, 11)]
    endpoints = [ResultExample(10, "G10", "IfcDoor"), ResultExample(11, "G11", "IfcDoor")]
    _retain_topology(execution, hops, [100], endpoints)
    assert [h.relationship_id for h in execution.topology_hops] == [1, 3]
    assert execution.topology_truncated is False


def test_an_oversized_hop_set_is_reported_not_sampled():
    """§5.3 forbids trimming a topology to fit; the copy is dropped instead."""
    execution = GraphExecution()
    hops = [_hop(i, 100, 1000 + i) for i in range(MAX_TOPOLOGY_HOPS + 1)]
    _retain_topology(execution, hops, [100], [])
    assert execution.topology_hops == []
    assert execution.topology_truncated is True
