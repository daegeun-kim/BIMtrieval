"""Graph traversal result shapes (spec_v003 §12).

`TraverseRelationshipsPlan` itself lives in `query.sql.schemas` (it's part of
the same typed-plan vocabulary as the other 16 operations); this module
defines the traversal *output* shape, kept separate since it's graph-specific
and not part of the SQL evidence contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TraversalHop:
    relationship_id: int
    relationship_global_id: str
    relationship_class: str
    semantic_role: str
    from_entity_id: int
    to_entity_id: int | None
    to_entity_global_id: str | None

    # --- Presentation-only columns (task29 §5.1) ----------------------------
    #
    # Every field below already existed on the `relationship_members` rows the
    # traversal statement ALREADY joins (`role`, `endpoint_global_id`,
    # `endpoint_ifc_class` on both the `m_from` and `m_to` aliases), so carrying
    # them adds no statement, join, predicate, or reached endpoint. They exist
    # so the explanation panel can reproduce the recorded topology — the answer,
    # the endpoints and the LLM packet never read them.
    #
    # Defaulted to `None` so a hop constructed without them (fixtures, callers
    # that only need reachability) stays valid and simply yields no diagram.
    from_role: str | None = None
    to_role: str | None = None
    from_entity_global_id: str | None = None
    from_entity_ifc_class: str | None = None
    to_entity_ifc_class: str | None = None
    #: Which traversal direction discovered this hop. Recorded for diagnostics
    #: only: arrow direction is derived from the IFC roles above, never from
    #: discovery order (task29 §5.2).
    traversal_direction: str | None = None


@dataclass
class TraversalResult:
    primary_entity_ids: set[int]
    context_entity_ids: set[int]
    hops: list[TraversalHop] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
