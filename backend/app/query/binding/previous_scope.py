"""Typed, reproducible previous-result scope (Task 24 §7).

Replaces the previous session state — a truncated list of entity ids — with a
scope that can be RE-EXECUTED.

§7 is explicit about why: "Do not scope a large follow-up to the first 50 or 200
previous IDs. Re-execute the stored typed predicate when complete scope is
required." A capped id list silently answers a follow-up about a different,
smaller set than the one the user just saw — "how many of those are external?"
over 551 doors would have quietly meant "of the first 200".

Storing the predicate instead makes the follow-up exact at any size, and costs
one query rather than a growing list in session memory.

The scope is invalidated whenever it could no longer describe the same objects:
a different active model, a session reset, or a stored model id that does not
match the request (§7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import IfcEntity
from app.query.sql.compiler import build_condition_expr
from app.query.sql.schemas import FilterGroup

__all__ = ["PreviousScope", "capture_previous_scope", "resolve_previous_entity_ids"]

_ET = IfcEntity.__table__


@dataclass
class PreviousScope:
    """A reproducible description of the last accepted result (§7)."""

    source_model_id: int
    #: The subject family the result was about.
    ifc_classes: tuple[str, ...]
    #: The complete typed predicate, so the scope can be re-executed exactly.
    filters: FilterGroup | None = None
    #: Entity-id scope, when the previous result was itself scoped that way.
    scope_entity_ids: tuple[int, ...] | None = None
    #: Which answer part was accepted, and what it produced.
    part_id: str = ""
    status: str = ""
    exact_count: int | None = None
    #: Plain-language description, for the binder's context.
    description: str = ""
    #: A few example ids, useful only for diagnostics — NEVER the scope itself.
    example_entity_ids: tuple[int, ...] = field(default_factory=tuple)

    def matches_model(self, source_model_id: int | None) -> bool:
        """§7: clear the scope when the stored model does not match the request."""
        return source_model_id is not None and source_model_id == self.source_model_id

    def summary(self) -> dict[str, Any]:
        """Bounded description for LLM call 1 — no ids, no SQL (§2.1)."""
        payload: dict[str, Any] = {"about": self.description or ", ".join(self.ifc_classes)}
        if self.exact_count is not None:
            payload["count"] = self.exact_count
        if self.status:
            payload["status"] = self.status
        return payload


def capture_previous_scope(result: Any, description: str = "") -> PreviousScope | None:
    """Store the accepted answer part as a re-executable scope.

    Returns None for results that cannot meaningfully be followed up (an
    unavailable or ambiguous part describes no set of objects).
    """
    predicate = getattr(result, "predicate", None)
    if predicate is None or not predicate.ifc_classes:
        return None
    if result.status.value not in ("exact", "zero", "partial"):
        return None
    return PreviousScope(
        source_model_id=predicate.source_model_id,
        ifc_classes=tuple(predicate.ifc_classes),
        filters=predicate.filters,
        scope_entity_ids=predicate.scope_entity_ids,
        part_id=result.part_id,
        status=result.status.value,
        exact_count=result.exact_total,
        description=description or result.request_text,
        example_entity_ids=tuple(e.entity_id for e in result.examples[:5]),
    )


def resolve_previous_entity_ids(
    session: Session, scope: PreviousScope | None, source_model_id: int | None
) -> list[int]:
    """Re-execute the stored predicate to get the COMPLETE previous scope (§7).

    Returns every matching id, not a capped prefix — that is the entire point.
    An invalid or mismatched scope resolves to an empty list rather than to a
    stale set, so a follow-up can never silently target another model's objects.
    """
    if scope is None or not scope.matches_model(source_model_id):
        return []

    where = _ET.c.source_model_id == scope.source_model_id
    if scope.ifc_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(list(scope.ifc_classes)))
    if scope.filters is not None:
        where = sa.and_(
            where,
            build_condition_expr(session, scope.source_model_id, scope.filters, _ET),
        )
    if scope.scope_entity_ids is not None:
        if not scope.scope_entity_ids:
            return []
        where = sa.and_(where, _ET.c.id.in_(list(scope.scope_entity_ids)))

    return [row[0] for row in session.execute(sa.select(_ET.c.id).where(where).order_by(_ET.c.id))]
