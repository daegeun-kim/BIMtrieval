"""Grouped relationship topology and the exact graph bounds (task29 §5).

Offline: hops are constructed directly, so no DB, no traversal, no OpenAI.

The properties under test are the ones a wrong diagram would quietly violate —
node grouping by structural key, overlapping (not partitioned) identity sets,
one edge per stored connection regardless of which direction discovered it,
IFC-role direction rather than discovery order, and the exact 4-24 node /
40-edge threshold with a table fallback instead of a silently trimmed graph.
"""

from __future__ import annotations

import pytest

from app.api.schemas.response import ExplanationGraphNodeRole, ExplanationPresentation
from app.query.binding.evidence import AnswerPartResult, ResultExample, ResultStatus
from app.query.binding.presentation import build_answer_explanation
from app.query.binding.topology import (
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    build_relationship_graph,
)
from app.query.binding.viewer import HydratedIdentity, ViewerHydration
from app.query.graph.schemas import TraversalHop
from app.shared.types import AnswerBasis

# `IfcRelContainedInSpatialStructure`: RelatingStructure -> RelatedElements.
_CONTAINS = "IfcRelContainedInSpatialStructure"
_RELATING = "RelatingStructure"
_RELATED = "RelatedElements"
# `IfcRelAssociatesMaterial`: RelatingMaterial -> RelatedObjects.
_MATERIAL = "IfcRelAssociatesMaterial"
_MAT_RELATING = "RelatingMaterial"
_MAT_RELATED = "RelatedObjects"

SEED_ID = 1000


def hop(
    relationship_id: int,
    to_entity_id: int,
    *,
    from_entity_id: int = SEED_ID,
    relationship_class: str = _CONTAINS,
    semantic_role: str = "containment",
    from_role: str = _RELATING,
    to_role: str = _RELATED,
    from_ifc_class: str = "IfcBuildingStorey",
    to_ifc_class: str = "IfcDoor",
    direction: str = "outgoing",
    **kw,
) -> TraversalHop:
    return TraversalHop(
        relationship_id=relationship_id,
        relationship_global_id=f"rel{relationship_id}",
        relationship_class=relationship_class,
        semantic_role=semantic_role,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        to_entity_global_id=kw.pop("to_global_id", f"G{to_entity_id}"),
        from_role=from_role,
        to_role=to_role,
        from_entity_global_id=kw.pop("from_global_id", f"G{from_entity_id}"),
        from_entity_ifc_class=from_ifc_class,
        to_entity_ifc_class=to_ifc_class,
        traversal_direction=direction,
        **kw,
    )


def _result(hops, *, endpoints=None, seeds=(SEED_ID,), truncated=False):
    reached = endpoints
    if reached is None:
        reached = [
            ResultExample(entity_id=h.to_entity_id, global_id=f"G{h.to_entity_id}", ifc_class="X")
            for h in hops
            if h.to_entity_id is not None and h.to_entity_id not in set(seeds)
        ]
    return AnswerPartResult(
        part_id="p1",
        request_text="what is connected to the second floor",
        operation="relationship",
        status=ResultStatus.EXACT,
        exact_total=len(reached),
        graph_endpoints=list(reached),
        graph_seed_entity_ids=tuple(seeds),
        graph_topology_hops=list(hops),
        graph_topology_truncated=truncated,
    )


def _highlight(result):
    return {e.global_id for e in result.graph_endpoints}


def _graph(hops, **kw):
    result = _result(hops, **kw)
    return build_relationship_graph(result, _highlight(result))


# ---------------------------------------------------------------------------
# Grouping (§5.2)
# ---------------------------------------------------------------------------


def test_same_class_and_same_relationship_structure_collapse_into_one_node():
    selection = _graph([hop(1, 10), hop(2, 11), hop(3, 12)])
    assert selection.graph is None  # 2 nodes — below the threshold
    # Grouped explicitly: one seed plus one IfcDoor group, not four nodes.
    reason = selection.fallback_reason or ""
    assert "2 distinct group(s)" in reason


def test_the_seed_is_its_own_node_and_is_counted_in_the_threshold():
    hops = [
        hop(1, 10, to_ifc_class="IfcDoor"),
        hop(2, 11, to_ifc_class="IfcWindow"),
        hop(3, 12, to_ifc_class="IfcWall"),
    ]
    selection = _graph(hops)
    assert selection.graph is not None
    assert selection.graph.node_count == 4
    seeds = [n for n in selection.graph.nodes if n.role is ExplanationGraphNodeRole.SEED]
    assert len(seeds) == 1
    assert seeds[0].label == "IfcBuildingStorey"
    assert seeds[0].entity_count == 1
    # The subject is never merged into an endpoint group, and never selectable:
    # it is not part of the query-result highlight.
    assert seeds[0].selectable is False


def test_repeated_occurrences_of_one_entity_count_once():
    hops = [
        hop(1, 10, to_ifc_class="IfcDoor"),
        # The same door again through the same structure, via another relationship.
        hop(2, 10, to_ifc_class="IfcDoor"),
        hop(3, 11, to_ifc_class="IfcWindow"),
        hop(4, 12, to_ifc_class="IfcWall"),
    ]
    selection = _graph(hops)
    assert selection.graph is not None
    doors = next(n for n in selection.graph.nodes if n.ifc_class == "IfcDoor")
    assert doors.entity_count == 1
    assert doors.global_ids == ["G10"]


def test_one_entity_may_appear_in_several_nodes_under_different_structures():
    """§5.2: graph-node identity sets overlap and are not a partition."""
    hops = [
        hop(1, 10, to_ifc_class="IfcDoor"),
        hop(2, 11, to_ifc_class="IfcWindow"),
        # The SAME door, reached through a different relationship class.
        hop(
            3,
            10,
            relationship_class=_MATERIAL,
            semantic_role="material_association",
            from_role=_MAT_RELATING,
            to_role=_MAT_RELATED,
            from_ifc_class="IfcBuildingStorey",
            to_ifc_class="IfcDoor",
        ),
    ]
    selection = _graph(hops)
    assert selection.graph is not None
    door_nodes = [n for n in selection.graph.nodes if n.ifc_class == "IfcDoor"]
    assert len(door_nodes) == 2
    assert {n.relationship_class for n in door_nodes} == {_CONTAINS, _MATERIAL}
    # Overlapping, so the union is NOT the sum of the parts.
    assert all(n.global_ids == ["G10"] for n in door_nodes)


def test_a_different_endpoint_role_makes_a_different_node():
    hops = [
        hop(1, 10, to_ifc_class="IfcDoor"),
        hop(2, 11, to_ifc_class="IfcWindow"),
        # Same class, same relationship class, opposite endpoint role: this door
        # is the RELATING side of its own containment relationship.
        hop(
            3,
            SEED_ID,
            from_entity_id=12,
            from_role=_RELATING,
            to_role=_RELATED,
            from_ifc_class="IfcDoor",
            to_ifc_class="IfcBuildingStorey",
        ),
    ]
    selection = _graph(
        hops,
        endpoints=[
            ResultExample(10, "G10", "IfcDoor"),
            ResultExample(11, "G11", "IfcWindow"),
            ResultExample(12, "G12", "IfcDoor"),
        ],
    )
    assert selection.graph is not None
    door_nodes = [n for n in selection.graph.nodes if n.ifc_class == "IfcDoor"]
    assert len(door_nodes) == 2
    assert {n.endpoint_role for n in door_nodes} == {_RELATED, _RELATING}


# ---------------------------------------------------------------------------
# Edges: distinct connections, IFC direction, no reverse double-count (§5.2)
# ---------------------------------------------------------------------------


def test_grouped_edge_counts_distinct_authoritative_connections():
    hops = [
        hop(1, 10, to_ifc_class="IfcDoor"),
        hop(2, 11, to_ifc_class="IfcDoor"),
        hop(3, 12, to_ifc_class="IfcWindow"),
        hop(4, 13, to_ifc_class="IfcWall"),
    ]
    selection = _graph(hops)
    assert selection.graph is not None
    assert selection.graph.edge_count == 3
    doors = next(e for e in selection.graph.edges if e.target_node_id == "n1")
    assert doors.connection_count == 2


def test_reverse_discovery_of_one_stored_connection_is_not_a_second_edge():
    """The same relationship found outgoing and incoming is ONE semantic edge."""
    forward = hop(1, 10, to_ifc_class="IfcDoor")
    backward = hop(
        1,
        SEED_ID,
        from_entity_id=10,
        from_role=_RELATED,
        to_role=_RELATING,
        from_ifc_class="IfcDoor",
        to_ifc_class="IfcBuildingStorey",
        direction="incoming",
    )
    hops = [
        forward,
        backward,
        hop(2, 11, to_ifc_class="IfcWindow"),
        hop(3, 12, to_ifc_class="IfcWall"),
    ]
    selection = _graph(
        hops,
        endpoints=[
            ResultExample(10, "G10", "IfcDoor"),
            ResultExample(11, "G11", "IfcWindow"),
            ResultExample(12, "G12", "IfcWall"),
        ],
    )
    assert selection.graph is not None
    assert selection.graph.node_count == 4
    assert selection.graph.edge_count == 3
    for edge in selection.graph.edges:
        assert edge.connection_count == 1


def test_schema_direction_is_preserved_independently_of_discovery_order():
    """Arrows follow the recorded IFC roles: relating -> related, always."""
    hops = [
        # Discovered from the DOOR side, i.e. the related end first.
        hop(
            1,
            SEED_ID,
            from_entity_id=10,
            from_role=_RELATED,
            to_role=_RELATING,
            from_ifc_class="IfcDoor",
            to_ifc_class="IfcBuildingStorey",
            direction="incoming",
        ),
        hop(2, 11, to_ifc_class="IfcWindow"),
        hop(3, 12, to_ifc_class="IfcWall"),
    ]
    selection = _graph(
        hops,
        endpoints=[
            ResultExample(10, "G10", "IfcDoor"),
            ResultExample(11, "G11", "IfcWindow"),
            ResultExample(12, "G12", "IfcWall"),
        ],
    )
    assert selection.graph is not None
    nodes = {n.id: n for n in selection.graph.nodes}
    door_edge = next(
        e for e in selection.graph.edges if nodes[e.target_node_id].ifc_class == "IfcDoor"
    )
    # The storey is the relating side, so it is the source even though traversal
    # reached this hop from the door.
    assert nodes[door_edge.source_node_id].role is ExplanationGraphNodeRole.SEED
    assert door_edge.source_role == _RELATING
    assert door_edge.target_role == _RELATED
    assert door_edge.schema_direction == "relating_to_related"


# ---------------------------------------------------------------------------
# The exact threshold (§5.3)
# ---------------------------------------------------------------------------


def _n_class_hops(class_count: int, per_class: int = 1) -> list[TraversalHop]:
    hops: list[TraversalHop] = []
    rel = 0
    entity = 10
    for i in range(class_count):
        for _ in range(per_class):
            rel += 1
            entity += 1
            hops.append(hop(rel, entity, to_ifc_class=f"IfcClass{i:02d}"))
    return hops


def test_two_nodes_and_one_edge_use_the_table():
    selection = _graph([hop(1, 10)])
    assert selection.graph is None
    assert "too few" in (selection.fallback_reason or "")


def test_three_grouped_nodes_use_the_table():
    selection = _graph(_n_class_hops(2))
    assert selection.graph is None
    assert "3 distinct group(s)" in (selection.fallback_reason or "")


def test_four_grouped_nodes_use_the_graph():
    selection = _graph(_n_class_hops(3))
    assert selection.graph is not None
    assert selection.graph.node_count == 4


def test_exactly_twenty_four_nodes_and_forty_edges_remain_eligible():
    # 23 endpoint classes + the seed = 24 nodes, and 23 grouped edges.
    selection = _graph(_n_class_hops(MAX_GRAPH_NODES - 1))
    assert selection.graph is not None
    assert selection.graph.node_count == MAX_GRAPH_NODES
    assert selection.graph.edge_count <= MAX_GRAPH_EDGES


def test_twenty_five_nodes_fall_back_to_the_table_with_a_size_limitation():
    selection = _graph(_n_class_hops(MAX_GRAPH_NODES))
    assert selection.graph is None
    reason = selection.fallback_reason or ""
    assert "too large" in reason
    assert str(MAX_GRAPH_NODES + 1) in reason


def _dense_hops(relating: int, related: int) -> tuple[list[TraversalHop], list[ResultExample]]:
    """A complete bipartite containment mesh, so edges outgrow nodes.

    Group index 0 on the relating side IS the seed, so the seed node is counted
    once. Nodes = `relating + related`; edges = `relating * related`.
    """
    hops: list[TraversalHop] = []
    endpoints: list[ResultExample] = []
    rel = 0
    for i in range(relating):
        from_entity = SEED_ID if i == 0 else 200 + i
        if i:
            endpoints.append(ResultExample(from_entity, f"G{from_entity}", f"IfcHost{i:02d}"))
        for j in range(related):
            rel += 1
            to_entity = 300 + j
            hops.append(
                hop(
                    rel,
                    to_entity,
                    from_entity_id=from_entity,
                    from_ifc_class="IfcBuildingStorey" if i == 0 else f"IfcHost{i:02d}",
                    to_ifc_class=f"IfcPart{j:02d}",
                )
            )
    for j in range(related):
        endpoints.append(ResultExample(300 + j, f"G{300 + j}", f"IfcPart{j:02d}"))
    return hops, endpoints


def test_forty_one_grouped_edges_fall_back_to_the_table():
    """15 grouped nodes but 49 grouped edges: the edge bound alone rejects it."""
    hops, endpoints = _dense_hops(7, 7)
    selection = _graph(hops, endpoints=endpoints)
    assert selection.graph is None
    reason = selection.fallback_reason or ""
    assert "too large" in reason
    assert "14 groups, 49 grouped connections" in reason


def test_exactly_forty_grouped_edges_remain_eligible():
    """Same construction one edge below the bound: 13 nodes and 40 edges."""
    hops, endpoints = _dense_hops(8, 5)
    selection = _graph(hops, endpoints=endpoints)
    assert selection.graph is not None
    assert selection.graph.edge_count == MAX_GRAPH_EDGES
    assert selection.graph.node_count <= MAX_GRAPH_NODES


def test_a_hop_set_over_the_transport_ceiling_reports_too_large():
    selection = _graph(_n_class_hops(3), truncated=True)
    assert selection.graph is None
    assert "too large" in (selection.fallback_reason or "")


# ---------------------------------------------------------------------------
# Incomplete authoritative topology (§5.2, §5.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"from_role": None},
        {"to_role": None},
        {"from_ifc_class": None},
        {"to_ifc_class": None},
        {"relationship_class": "IfcRelNotInTheRegistry"},
        # Roles that belong to neither side of the registered relationship.
        {"from_role": "Nonsense", "to_role": "AlsoNonsense"},
    ],
)
def test_missing_or_unusable_roles_fall_back_to_the_table(override):
    hops = _n_class_hops(3)
    hops[0] = hop(99, 999, **override)
    selection = _graph(hops)
    assert selection.graph is None
    assert "endpoint structure" in (selection.fallback_reason or "")


def test_an_unresolved_endpoint_falls_back_to_the_table():
    hops = _n_class_hops(3)
    hops[0].to_entity_id = None
    selection = _graph(hops)
    assert selection.graph is None


def test_no_hops_or_no_seeds_fall_back_to_the_table():
    assert _graph([]).graph is None
    assert _graph(_n_class_hops(3), seeds=()).graph is None


def test_an_accepted_endpoint_no_retained_hop_covers_falls_back_to_the_table():
    """A diagram may not silently omit an object the answer claims (§5.3)."""
    hops = _n_class_hops(3)
    endpoints = [
        ResultExample(entity_id=h.to_entity_id, global_id=f"G{h.to_entity_id}", ifc_class="X")
        for h in hops
    ]
    endpoints.append(ResultExample(entity_id=777, global_id="G777", ifc_class="IfcSpace"))
    selection = _graph(hops, endpoints=endpoints)
    assert selection.graph is None


# ---------------------------------------------------------------------------
# Selection, bounds, and the public payload (§5.1, §5.4)
# ---------------------------------------------------------------------------


def test_a_node_is_selectable_only_when_its_ids_are_inside_the_highlight():
    hops = _n_class_hops(3)
    result = _result(hops)
    # Highlight everything except the first endpoint's GlobalId.
    partial_highlight = _highlight(result) - {"G11"}
    selection = build_relationship_graph(result, partial_highlight)
    assert selection.graph is not None
    outside = next(n for n in selection.graph.nodes if n.global_ids == ["G11"])
    assert outside.selectable is False
    inside = next(n for n in selection.graph.nodes if n.global_ids == ["G12"])
    assert inside.selectable is True


def test_public_payload_is_bounded_allowlisted_and_hides_internal_ids():
    selection = _graph(_n_class_hops(3))
    assert selection.graph is not None
    payload = selection.graph.model_dump(mode="json")
    fields = (
        set(payload)
        | {k for n in payload["nodes"] for k in n}
        | {k for e in payload["edges"] for k in e}
    )
    for forbidden in ("entity_id", "relationship_id", "canonical_json", "sql", "predicate", "rows"):
        assert forbidden not in fields, forbidden
    # Node/edge ids are opaque presentation ids, not database ids.
    assert [n["id"] for n in payload["nodes"]] == ["n0", "n1", "n2", "n3"]
    assert all(e["id"].startswith("e") for e in payload["edges"])
    with pytest.raises(Exception):
        type(selection.graph)(**{**payload, "raw_rows": []})


def test_the_graph_carries_a_textual_description_of_nodes_and_edges():
    selection = _graph(_n_class_hops(3))
    assert selection.graph is not None
    description = selection.graph.description
    assert "4 groups and 3 grouped connections" in description
    for node in selection.graph.nodes:
        assert node.label in description


# ---------------------------------------------------------------------------
# Wired into the presentation choice (§2.1)
# ---------------------------------------------------------------------------


def _hydration(result):
    identities = [
        HydratedIdentity(global_id=e.global_id, ifc_class=e.ifc_class)
        for e in result.graph_endpoints
    ]
    return ViewerHydration(
        primary_global_ids=[i.global_id for i in identities],
        primary_identities=identities,
        viewer_matches_total=len(identities),
    )


def test_a_qualifying_relationship_result_selects_the_node_link_diagram():
    result = _result(_n_class_hops(3))
    explanation = build_answer_explanation(result, _hydration(result), AnswerBasis.GRAPH_TRAVERSAL)
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.RELATIONSHIP_GRAPH
    assert explanation.graph is not None
    assert explanation.presentation_fallback_reason is None
    # The graph replaces the table; it does not duplicate it.
    assert explanation.rows == []


def test_a_non_qualifying_relationship_result_selects_the_endpoint_table():
    result = _result([hop(1, 10)])
    explanation = build_answer_explanation(result, _hydration(result), AnswerBasis.GRAPH_TRAVERSAL)
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.RELATIONSHIP_TABLE
    assert explanation.graph is None
    assert "too few" in (explanation.presentation_fallback_reason or "")
    assert [r.global_id for r in explanation.rows] == ["G10"]
