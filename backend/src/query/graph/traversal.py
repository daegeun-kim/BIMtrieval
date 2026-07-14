"""Bounded IFC relationship traversal (spec_v003 §12).

PostgreSQL only — `ifc_relationships -> relationship_members -> ifc_entities`,
no graph database. Depth 1-3 (default 1, `TraverseRelationshipsPlan.max_depth`),
cycle prevention via an accumulating visited-entity set, and every query is
scoped by `source_model_id`. One query per allowed relationship class per
direction per depth level (the registry's per-class role names can't be
folded into a single generic IN-clause query since they differ by class).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from bim_rag.schema.models import DbIfcRelationship, RelationshipMember
from query.graph.registry import REGISTRY
from query.graph.schemas import TraversalHop, TraversalResult
from query.sql.schemas import TraverseRelationshipsPlan

_RT = DbIfcRelationship.__table__
_MT = RelationshipMember.__table__


def traverse(session: Session, plan: TraverseRelationshipsPlan) -> TraversalResult:
    allowed_classes = (
        set(plan.relationship_classes) if plan.relationship_classes else set(REGISTRY.keys())
    )
    unsupported = allowed_classes - set(REGISTRY.keys())
    warnings: list[str] = []
    if unsupported:
        warnings.append(f"unsupported relationship classes ignored: {sorted(unsupported)}")
        allowed_classes -= unsupported

    visited_entities: set[int] = set(plan.start_entity_ids)
    frontier: set[int] = set(plan.start_entity_ids)
    visited_relationships: set[int] = set()
    hops: list[TraversalHop] = []

    for _ in range(plan.max_depth):
        if not frontier:
            break
        next_frontier: set[int] = set()

        directions = ("outgoing", "incoming") if plan.direction == "both" else (plan.direction,)
        for direction in directions:
            for hop in _expand(
                session,
                plan.source_model_id,
                frontier,
                allowed_classes,
                visited_relationships,
                direction,
            ):
                hops.append(hop)
                if hop.to_entity_id is not None and hop.to_entity_id not in visited_entities:
                    next_frontier.add(hop.to_entity_id)

        visited_entities |= next_frontier
        frontier = next_frontier

    return TraversalResult(
        primary_entity_ids=set(plan.start_entity_ids),
        context_entity_ids=visited_entities - set(plan.start_entity_ids),
        hops=hops,
        warnings=warnings,
    )


def _expand(
    session: Session,
    source_model_id: int,
    frontier_ids: set[int],
    allowed_classes: set[str],
    visited_relationships: set[int],
    direction: str,
) -> list[TraversalHop]:
    hops: list[TraversalHop] = []
    frontier_list = list(frontier_ids)

    for ifc_class in allowed_classes:
        entry = REGISTRY[ifc_class]
        from_roles = entry.relating_roles if direction == "outgoing" else entry.related_roles
        to_roles = entry.related_roles if direction == "outgoing" else entry.relating_roles

        m_from = _MT.alias("m_from")
        m_to = _MT.alias("m_to")
        stmt = (
            sa.select(
                m_from.c.relationship_id,
                _RT.c.global_id,
                _RT.c.ifc_class,
                m_from.c.entity_id.label("from_entity_id"),
                m_to.c.entity_id.label("to_entity_id"),
                m_to.c.endpoint_global_id.label("to_global_id"),
            )
            .select_from(
                m_from.join(_RT, _RT.c.id == m_from.c.relationship_id).join(
                    m_to, m_to.c.relationship_id == m_from.c.relationship_id
                )
            )
            .where(
                m_from.c.source_model_id == source_model_id,
                m_to.c.source_model_id == source_model_id,
                _RT.c.source_model_id == source_model_id,
                m_from.c.entity_id.in_(frontier_list),
                _RT.c.ifc_class == ifc_class,
                m_from.c.role.in_(from_roles),
                m_to.c.role.in_(to_roles),
                m_to.c.id != m_from.c.id,
            )
        )
        for row in session.execute(stmt):
            hops.append(
                TraversalHop(
                    relationship_id=row.relationship_id,
                    relationship_global_id=row.global_id,
                    relationship_class=row.ifc_class,
                    semantic_role=entry.semantic_role.value,
                    from_entity_id=row.from_entity_id,
                    to_entity_id=row.to_entity_id,
                    to_entity_global_id=row.to_global_id,
                )
            )
            visited_relationships.add(row.relationship_id)
    return hops
