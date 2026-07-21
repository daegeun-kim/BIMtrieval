"""Seeded graph execution for relationship answer parts (Task 24 §5.4).

§5.4 requires graph operations to be "wired into the active pipeline rather than
only recording that graph retrieval was requested". A previous run answered
"which spaces are connected to the stairs?" by naming six spaces while
highlighting all 778 — the names were not a computed connectivity result at all,
because traversal never ran. This module is the correction.

The executor receives, per §5.4:

- seed identities derived from the SELECTED SUBJECT PREDICATE (not a broad class
  scan), the viewer selection, or the typed previous result;
- the relationship class and its role binding;
- direction;
- the existing bounded maximum depth;
- an optional endpoint subject family to filter results to;
- source-model isolation (inherited from `TraverseRelationshipsPlan`, every
  statement of which is scoped by `source_model_id`).

Endpoint results are filtered to the requested endpoint semantics. When the
model lacks the relationship representation, or traversal cannot establish the
requested connection, the result is UNAVAILABLE/ZERO — never a plausible list of
names assembled from a broad entity query. §6: "failed graph execution is not
evidence of no real-world connection."
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import IfcEntity
from app.query.binding.compile import CompiledPredicate
from app.query.binding.evidence import ResultExample
from app.query.graph.registry import REGISTRY
from app.query.graph.traversal import traverse
from app.query.sql.schemas import MAX_TRAVERSAL_DEPTH, TraverseRelationshipsPlan

__all__ = ["GraphExecution", "execute_graph"]

_ET = IfcEntity.__table__

#: Seeds are bounded by the existing typed-plan limit; a traversal from every
#: object in a large class is neither useful nor executable.
MAX_SEEDS = 50


@dataclass
class GraphExecution:
    """Outcome of one seeded traversal."""

    ran: bool = False
    relationship_class: str | None = None
    seed_count: int = 0
    #: Endpoints matching the requested endpoint family, deduped and ordered.
    endpoints: list[ResultExample] = field(default_factory=list)
    #: Distinct traversal hops that produced those endpoints.
    path_count: int = 0
    #: Set when traversal could not be performed or established nothing.
    unavailable_reason: str | None = None
    #: True when seeds existed and traversal ran but nothing connected.
    established_nothing: bool = False
    warnings: list[str] = field(default_factory=list)
    statement_count: int = 0

    @property
    def has_connection(self) -> bool:
        """A connection may be claimed ONLY when traversal actually found one."""
        return self.ran and bool(self.endpoints)


def execute_graph(
    session: Session,
    predicate: CompiledPredicate,
    *,
    relationship_class: str,
    relationship_available: bool,
    endpoint_ifc_classes: tuple[str, ...] = (),
    direction: str = "both",
    max_depth: int = 1,
    seed_entity_ids: list[int] | None = None,
) -> GraphExecution:
    """Traverse from the subject predicate's own matches to its endpoints."""
    execution = GraphExecution(relationship_class=relationship_class)

    entry = REGISTRY.get(relationship_class)
    if entry is None:
        execution.unavailable_reason = (
            f"{relationship_class} is not a traversable relationship in this system, so the "
            "requested connection cannot be computed"
        )
        return execution
    if not relationship_available:
        execution.unavailable_reason = (
            f"this model records no {relationship_class} relationships, so the requested "
            "connection cannot be established from it"
        )
        return execution

    seeds = list(seed_entity_ids or [])
    if not seeds:
        seeds, seed_statements = _seed_from_predicate(session, predicate)
        execution.statement_count += seed_statements
    seeds = seeds[:MAX_SEEDS]
    execution.seed_count = len(seeds)

    if not seeds:
        # No seeds is NOT "no connection" — there was nothing to traverse from.
        execution.unavailable_reason = (
            "no objects matched the subject of this question, so there was nothing to "
            "trace connections from"
        )
        return execution

    plan = TraverseRelationshipsPlan(
        source_model_id=predicate.source_model_id,
        start_entity_ids=seeds,
        relationship_classes=[relationship_class],
        max_depth=max(0, min(max_depth, MAX_TRAVERSAL_DEPTH)),
        direction=direction,
    )
    result = traverse(session, plan)
    execution.ran = True
    execution.statement_count += 1
    execution.warnings.extend(result.warnings)

    reached_ids = [i for i in result.context_entity_ids if i not in set(seeds)]
    if not reached_ids:
        execution.established_nothing = True
        return execution

    rows, hydrate_statements = _hydrate_endpoints(
        session, predicate.source_model_id, reached_ids, endpoint_ifc_classes
    )
    execution.statement_count += hydrate_statements
    execution.endpoints = rows
    execution.path_count = len(result.hops)

    if endpoint_ifc_classes and not rows:
        # Traversal succeeded but reached nothing of the requested kind. That is
        # a real, reportable ZERO for the endpoint family — and crucially NOT a
        # licence to report the unfiltered endpoints instead.
        execution.established_nothing = True
    return execution


def _seed_from_predicate(session: Session, predicate: CompiledPredicate) -> tuple[list[int], int]:
    """Seed ids from the SAME predicate the answer's count comes from (§5.4).

    Reusing the compiled predicate is what keeps the traversal's starting set
    identical to the set the user asked about — a broad class scan here would
    reintroduce the defect where the answer and the highlighted objects
    disagreed.
    """
    from app.query.sql.compiler import build_condition_expr

    where = _ET.c.source_model_id == predicate.source_model_id
    if predicate.ifc_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(list(predicate.ifc_classes)))
    if predicate.filters is not None:
        where = sa.and_(
            where,
            build_condition_expr(session, predicate.source_model_id, predicate.filters, _ET),
        )
    if predicate.scope_entity_ids is not None:
        if not predicate.scope_entity_ids:
            return [], 0
        where = sa.and_(where, _ET.c.id.in_(list(predicate.scope_entity_ids)))

    stmt = sa.select(_ET.c.id).where(where).order_by(_ET.c.id).limit(MAX_SEEDS)
    return [row[0] for row in session.execute(stmt)], 1


def _hydrate_endpoints(
    session: Session,
    source_model_id: int,
    entity_ids: list[int],
    endpoint_ifc_classes: tuple[str, ...],
) -> tuple[list[ResultExample], int]:
    """Compact identities for reached endpoints, filtered to the requested family.

    Filtering happens in SQL rather than after the fact so an endpoint family
    the user did not ask about never reaches the answer packet.
    """
    from app.query.sql.compiler import path_array_param

    name_expr = _ET.c.canonical_json.op("#>>")(path_array_param(("identity", "name")))
    storey_expr = _ET.c.canonical_json.op("#>>")(path_array_param(("storey", "name")))
    where = sa.and_(
        _ET.c.source_model_id == source_model_id,
        _ET.c.id.in_(entity_ids),
    )
    if endpoint_ifc_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(list(endpoint_ifc_classes)))

    stmt = (
        sa.select(
            _ET.c.id,
            _ET.c.global_id,
            _ET.c.ifc_class,
            name_expr.label("name"),
            storey_expr.label("storey_name"),
        )
        .where(where)
        .order_by(_ET.c.id)
    )
    rows = [
        ResultExample(
            entity_id=r.id,
            global_id=r.global_id,
            ifc_class=r.ifc_class,
            name=r.name,
            storey_name=r.storey_name,
        )
        for r in session.execute(stmt)
    ]
    return rows, 1
