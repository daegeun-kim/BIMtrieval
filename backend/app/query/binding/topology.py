"""Grouped relationship topology for the explanation panel (task29 §5).

This module explains the topology of a traversal that has **already** been
accepted. It does no graph analysis, requests no path, and — like
`presentation.py` — has no way to reach a database session or the LLM: it takes
a finished `AnswerPartResult` plus the GlobalIds the viewer already received,
and reduces hops the traversal already returned into grouped nodes and edges.

Three rules carry the truthfulness of the diagram:

- **Direction is the IFC schema's, not traversal's.** Every hop is normalized
  so `source` is the *relating* side and `target` the *related* side, using the
  registry's role names. The same stored connection discovered from the opposite
  traversal direction therefore normalizes to the identical
  `(relationship, relating entity, related entity)` triple and collapses into
  one edge instead of appearing twice with a reversed arrow (§5.2).

- **Grouping counts distinct entities and distinct connections.** A node's
  `entity_count` is the number of distinct entities under its structural key —
  repeated occurrences of one entity count once — and an edge's
  `connection_count` is the number of distinct stored connections. Node identity
  sets may overlap across keys and are explicitly not a partition.

- **A graph is drawn only when it is complete and within bounds.** Missing
  roles, missing endpoint classes, an unresolved endpoint, an accepted endpoint
  no retained hop covers, more than `MAX_TOPOLOGY_HOPS` hops, fewer than 4 or
  more than 24 grouped nodes, or more than 40 grouped edges all fall back to the
  endpoint table with a stated reason. Nothing is sampled, truncated or hidden
  to squeeze a result past the threshold (§5.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.api.schemas.response import (
    ExplanationGraph,
    ExplanationGraphEdge,
    ExplanationGraphNode,
    ExplanationGraphNodeRole,
)
from app.query.binding.evidence import AnswerPartResult
from app.query.graph.registry import REGISTRY
from app.query.graph.schemas import TraversalHop

__all__ = [
    "MAX_GRAPH_EDGES",
    "MAX_GRAPH_NODES",
    "MAX_NODE_GLOBAL_IDS",
    "MIN_GRAPH_NODES",
    "TopologySelection",
    "build_relationship_graph",
]

#: Exact graph bounds (§5.3). Counted AFTER grouping, seed node included.
MIN_GRAPH_NODES = 4
MAX_GRAPH_NODES = 24
MAX_GRAPH_EDGES = 40

#: Ceiling on the GlobalIds carried for one node's selection.
MAX_NODE_GLOBAL_IDS = 50

#: The arrow's meaning, fixed by the IFC schema rather than by traversal order.
SCHEMA_DIRECTION = "relating_to_related"

_INCOMPLETE_REASON = (
    "this relationship result does not record enough endpoint structure for a "
    "diagram, so the connected objects are listed instead"
)


@dataclass(frozen=True)
class TopologySelection:
    """Either a qualifying grouped graph, or the reason there is none."""

    graph: ExplanationGraph | None = None
    fallback_reason: str | None = None


# ---------------------------------------------------------------------------
# Normalized connections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Side:
    entity_id: int
    global_id: str | None
    ifc_class: str
    role: str


@dataclass(frozen=True)
class _Connection:
    relationship_id: int
    relationship_class: str
    semantic_role: str
    #: The relating side — always the arrow's tail.
    source: _Side
    #: The related side — always the arrow's head.
    target: _Side

    @property
    def key(self) -> tuple[int, int, int]:
        """Identity of the STORED connection, independent of discovery order."""
        return (self.relationship_id, self.source.entity_id, self.target.entity_id)


def _normalize(hop: TraversalHop) -> _Connection | None:
    """Orient one hop by its recorded IFC roles, or reject it as unusable.

    Returning `None` is how an incomplete hop forces the table fallback rather
    than an edge drawn from a guess. The registry supplies the role names, so
    orientation never depends on `traversal_direction`.
    """
    entry = REGISTRY.get(hop.relationship_class)
    if entry is None:
        return None
    if hop.to_entity_id is None:
        return None
    if not hop.from_role or not hop.to_role:
        return None
    if not hop.from_entity_ifc_class or not hop.to_entity_ifc_class:
        return None

    from_side = _Side(
        hop.from_entity_id,
        hop.from_entity_global_id,
        hop.from_entity_ifc_class,
        hop.from_role,
    )
    to_side = _Side(
        hop.to_entity_id,
        hop.to_entity_global_id,
        hop.to_entity_ifc_class,
        hop.to_role,
    )

    if hop.from_role in entry.relating_roles and hop.to_role in entry.related_roles:
        source, target = from_side, to_side
    elif hop.from_role in entry.related_roles and hop.to_role in entry.relating_roles:
        # Discovered backwards. The semantic edge still runs relating -> related.
        source, target = to_side, from_side
    else:
        return None

    return _Connection(
        relationship_id=hop.relationship_id,
        relationship_class=hop.relationship_class,
        semantic_role=hop.semantic_role,
        source=source,
        target=target,
    )


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

#: The one key every seed occurrence collapses to. The query subject is its own
#: node and is never merged into an endpoint group (§5.2).
_SEED_KEY: tuple[str, ...] = ("__seed__",)


@dataclass
class _NodeGroup:
    key: tuple[str, ...]
    is_seed: bool
    ifc_classes: set[str] = field(default_factory=set)
    relationship_class: str | None = None
    semantic_role: str | None = None
    endpoint_role: str | None = None
    #: entity id -> GlobalId, insertion-ordered. A dict, so a repeated
    #: occurrence of the same entity under this key counts exactly once.
    entities: dict[int, str | None] = field(default_factory=dict)

    def add(self, side: _Side) -> None:
        self.ifc_classes.add(side.ifc_class)
        if side.entity_id not in self.entities or self.entities[side.entity_id] is None:
            self.entities[side.entity_id] = side.global_id

    @property
    def entity_count(self) -> int:
        return len(self.entities)


def _node_key(side: _Side, connection: _Connection, seeds: set[int]) -> tuple[str, ...]:
    if side.entity_id in seeds:
        return _SEED_KEY
    return (side.ifc_class, connection.relationship_class, side.role)


def build_relationship_graph(
    result: AnswerPartResult, highlighted_global_ids: set[str]
) -> TopologySelection:
    """Group the accepted traversal's hops, or say why no diagram qualifies."""
    if result.graph_topology_truncated:
        return TopologySelection(fallback_reason=_too_large_reason())
    hops = list(result.graph_topology_hops)
    seeds = set(result.graph_seed_entity_ids)
    if not hops or not seeds:
        return TopologySelection(fallback_reason=_INCOMPLETE_REASON)

    connections: dict[tuple[int, int, int], _Connection] = {}
    for hop in hops:
        connection = _normalize(hop)
        if connection is None:
            return TopologySelection(fallback_reason=_INCOMPLETE_REASON)
        # Deduplicates the same stored connection reached from either direction.
        connections.setdefault(connection.key, connection)

    groups: dict[tuple[str, ...], _NodeGroup] = {}
    edges: dict[tuple, set[tuple[int, int, int]]] = {}

    for connection in connections.values():
        source_key = _node_key(connection.source, connection, seeds)
        target_key = _node_key(connection.target, connection, seeds)
        _record(groups, source_key, connection.source, connection)
        _record(groups, target_key, connection.target, connection)

        edge_key = (
            source_key,
            target_key,
            connection.relationship_class,
            connection.semantic_role,
            connection.source.role,
            connection.target.role,
        )
        edges.setdefault(edge_key, set()).add(connection.key)

    # Every object the answer claims must appear in the diagram. An accepted
    # endpoint that no retained hop covers would otherwise be silently dropped.
    covered = {eid for group in groups.values() for eid in group.entities}
    if any(endpoint.entity_id not in covered for endpoint in result.graph_endpoints):
        return TopologySelection(fallback_reason=_INCOMPLETE_REASON)

    node_count = len(groups)
    edge_count = len(edges)
    if node_count < MIN_GRAPH_NODES:
        return TopologySelection(
            fallback_reason=(
                f"this relationship result forms only {node_count} distinct group(s), too "
                "few for a diagram; the connected objects are listed in full instead"
            )
        )
    if node_count > MAX_GRAPH_NODES or edge_count > MAX_GRAPH_EDGES:
        return TopologySelection(fallback_reason=_too_large_reason(node_count, edge_count))

    nodes = _public_nodes(groups, highlighted_global_ids)
    node_ids = {group_key: node.id for group_key, node in nodes}
    public_nodes = [node for _, node in nodes]
    public_edges = _public_edges(edges, node_ids)

    return TopologySelection(
        graph=ExplanationGraph(
            nodes=public_nodes,
            edges=public_edges,
            node_count=node_count,
            edge_count=edge_count,
            description=_describe(public_nodes, public_edges),
        )
    )


def _record(
    groups: dict[tuple[str, ...], _NodeGroup],
    key: tuple[str, ...],
    side: _Side,
    connection: _Connection,
) -> None:
    group = groups.get(key)
    if group is None:
        is_seed = key == _SEED_KEY
        group = _NodeGroup(
            key=key,
            is_seed=is_seed,
            relationship_class=None if is_seed else connection.relationship_class,
            semantic_role=None if is_seed else connection.semantic_role,
            endpoint_role=None if is_seed else side.role,
        )
        groups[key] = group
    group.add(side)


def _public_nodes(
    groups: dict[tuple[str, ...], _NodeGroup], highlighted: set[str]
) -> list[tuple[tuple[str, ...], ExplanationGraphNode]]:
    """Stable node order and ids: seed first, then largest group first.

    Deterministic ordering is what lets the frontend lay the diagram out without
    a force simulation and without the layout shifting between renders.
    """
    ordered = sorted(
        groups.values(),
        key=lambda g: (
            0 if g.is_seed else 1,
            -g.entity_count,
            g.relationship_class or "",
            g.endpoint_role or "",
            _class_label(g),
        ),
    )

    public: list[tuple[tuple[str, ...], ExplanationGraphNode]] = []
    for index, group in enumerate(ordered):
        global_ids = [gid for gid in group.entities.values() if gid]
        bounded = global_ids[:MAX_NODE_GLOBAL_IDS]
        selectable = not group.is_seed and bool(bounded) and set(bounded) <= highlighted
        public.append(
            (
                group.key,
                ExplanationGraphNode(
                    id=f"n{index}",
                    label=_node_label(group),
                    role=(
                        ExplanationGraphNodeRole.SEED
                        if group.is_seed
                        else ExplanationGraphNodeRole.ENDPOINT
                    ),
                    ifc_class=_class_label(group) or None,
                    relationship_class=group.relationship_class,
                    semantic_role=group.semantic_role,
                    endpoint_role=group.endpoint_role,
                    entity_count=group.entity_count,
                    global_ids=bounded,
                    global_ids_truncated=group.entity_count > len(bounded),
                    selectable=selectable,
                ),
            )
        )
    return public


def _public_edges(
    edges: dict[tuple, set[tuple[int, int, int]]],
    node_ids: dict[tuple[str, ...], str],
) -> list[ExplanationGraphEdge]:
    ordered = sorted(
        edges.items(),
        key=lambda item: (
            node_ids[item[0][0]],
            node_ids[item[0][1]],
            item[0][2],
            item[0][4],
            item[0][5],
        ),
    )
    public: list[ExplanationGraphEdge] = []
    for index, (edge_key, connection_keys) in enumerate(ordered):
        source_key, target_key, relationship_class, semantic_role, source_role, target_role = (
            edge_key
        )
        public.append(
            ExplanationGraphEdge(
                id=f"e{index}",
                source_node_id=node_ids[source_key],
                target_node_id=node_ids[target_key],
                relationship_class=relationship_class,
                semantic_role=semantic_role,
                schema_direction=SCHEMA_DIRECTION,
                source_role=source_role,
                target_role=target_role,
                connection_count=len(connection_keys),
                label=_semantic_label(semantic_role),
            )
        )
    return public


def _class_label(group: _NodeGroup) -> str:
    if len(group.ifc_classes) == 1:
        return next(iter(group.ifc_classes))
    return ""


def _node_label(group: _NodeGroup) -> str:
    label = _class_label(group)
    if label:
        return label
    return "Query subject" if group.is_seed else "Mixed classes"


def _semantic_label(semantic_role: str) -> str:
    return semantic_role.replace("_", " ")


def _too_large_reason(node_count: int | None = None, edge_count: int | None = None) -> str:
    if node_count is None or edge_count is None:
        return (
            "this relationship result is too large for the bounded diagram, so the "
            "connected objects are listed instead"
        )
    return (
        f"this relationship result is too large for the bounded diagram "
        f"({node_count} groups, {edge_count} grouped connections; the limits are "
        f"{MAX_GRAPH_NODES} and {MAX_GRAPH_EDGES}), so the connected objects are "
        "listed instead"
    )


def _describe(nodes: list[ExplanationGraphNode], edges: list[ExplanationGraphEdge]) -> str:
    """A plain-language reading of the same grouped values the diagram shows."""
    labels = {node.id: node for node in nodes}
    parts = [f"{len(nodes)} groups and {len(edges)} grouped connections."]
    for node in nodes:
        kind = "query subject" if node.role is ExplanationGraphNodeRole.SEED else "endpoint group"
        parts.append(f"{node.label} ({kind}): {node.entity_count} object(s).")
    for edge in edges:
        source = labels[edge.source_node_id].label
        target = labels[edge.target_node_id].label
        parts.append(
            f"{source} to {target} by {edge.label} "
            f"({edge.relationship_class}): {edge.connection_count} connection(s)."
        )
    return " ".join(parts)
