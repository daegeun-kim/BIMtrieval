"""Hydrate raw rows into the Task 04 evidence shapes (spec_v002 §13.3, §16, §17).

Never exposes raw SQL or full canonical JSON — only compact summaries plus
canonical IDs/GlobalIds (api.schemas.response.*, viewer.actions.*).
"""

from __future__ import annotations

from typing import Any

from app.api.schemas.response import ContextEntityResult, PrimaryEntityResult, RelationshipResult


def _entity_summary(name: str | None, storey_name: str | None) -> str | None:
    parts = [p for p in (name, f"on {storey_name}" if storey_name else None) if p]
    return " ".join(parts) or None


def hydrate_primary_entity(row: Any) -> PrimaryEntityResult:
    return PrimaryEntityResult(
        entity_id=row.id,
        global_id=row.global_id,
        ifc_class=row.ifc_class,
        name=getattr(row, "name", None),
        summary=_entity_summary(getattr(row, "name", None), getattr(row, "storey_name", None)),
    )


def hydrate_context_entity(row: Any) -> ContextEntityResult:
    return ContextEntityResult(
        entity_id=row.id,
        global_id=row.global_id,
        ifc_class=row.ifc_class,
        name=getattr(row, "name", None),
        summary=_entity_summary(getattr(row, "name", None), getattr(row, "storey_name", None)),
    )


def hydrate_relationship(row: Any) -> RelationshipResult:
    return RelationshipResult(
        relationship_id=row.id,
        global_id=row.global_id,
        ifc_class=row.ifc_class,
        name=getattr(row, "name", None),
    )
