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


@dataclass
class TraversalResult:
    primary_entity_ids: set[int]
    context_entity_ids: set[int]
    hops: list[TraversalHop] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
