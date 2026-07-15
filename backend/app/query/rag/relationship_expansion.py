"""Direct relationship-endpoint expansion for accepted RAG candidates
(spec_v004 §10).

Reuses `query.sql.relationships.get_relationship_members` for the member
rows, then hydrates resolved endpoints directly against `ifc_entities`
(bypassing `GetSelectedEntitiesPlan`'s 50-ID viewer-selection cap, which is
a different concept — spec_v004 §10 requires hydrating *all* direct
endpoints of an accepted relationship). No recursive traversal: deeper
expansion belongs to `query.graph` for hybrid/v005 execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import IfcEntity
from app.query.sql import relationships as sql_relationships
from app.query.sql.entities import entity_hydration_columns
from app.query.sql.schemas import GetRelationshipMembersPlan

_ET = IfcEntity.__table__

# A single hub relationship can have thousands of members (see Task 05's
# IfcRelContainedInSpatialStructure containment hub, 3505 RelatedElements).
# Evidence must stay bounded (spec_v002 §14) even though "all direct
# endpoints" is otherwise uncapped.
MAX_EXPANDED_ENDPOINTS = 200


@dataclass
class UnresolvedEndpoint:
    role: str
    member_order: int | None
    endpoint_ifc_class: str | None
    endpoint_global_id: str | None
    endpoint_name: str | None


@dataclass
class ExpandedRelationship:
    relationship_id: int
    resolved_endpoints: list = field(default_factory=list)  # entity_hydration_columns() rows
    unresolved_endpoints: list[UnresolvedEndpoint] = field(default_factory=list)
    total_member_count: int = 0
    warnings: list[str] = field(default_factory=list)


def expand_relationship_endpoints(
    session: Session, source_model_id: int, relationship_id: int
) -> ExpandedRelationship:
    members = sql_relationships.get_relationship_members(
        session,
        GetRelationshipMembersPlan(
            source_model_id=source_model_id, relationship_id=relationship_id
        ),
    )
    resolved_ids = [m.entity_id for m in members if m.entity_id is not None]
    unresolved = [
        UnresolvedEndpoint(
            role=m.role,
            member_order=m.member_order,
            endpoint_ifc_class=m.endpoint_ifc_class,
            endpoint_global_id=m.endpoint_global_id,
            endpoint_name=m.endpoint_name,
        )
        for m in members
        if m.entity_id is None
    ]

    warnings: list[str] = []
    if unresolved:
        warnings.append(
            f"{len(unresolved)} relationship endpoint(s) could not be resolved to entity rows"
        )

    bounded_ids = resolved_ids[:MAX_EXPANDED_ENDPOINTS]
    if len(resolved_ids) > MAX_EXPANDED_ENDPOINTS:
        warnings.append(
            f"{len(resolved_ids)} resolved endpoints exceed the {MAX_EXPANDED_ENDPOINTS}-entity "
            "evidence bound; hydrated the first "
            f"{MAX_EXPANDED_ENDPOINTS} only (exact total in total_member_count)"
        )

    resolved_rows = []
    if bounded_ids:
        resolved_rows = session.execute(
            sa.select(*entity_hydration_columns()).where(
                _ET.c.source_model_id == source_model_id, _ET.c.id.in_(bounded_ids)
            )
        ).all()

    return ExpandedRelationship(
        relationship_id=relationship_id,
        resolved_endpoints=resolved_rows,
        unresolved_endpoints=unresolved,
        total_member_count=len(members),
        warnings=warnings,
    )
