"""RagSearchResult -> Task 04 evidence shapes + viewer actions (spec_v004 §11).

Only accepted (`passed_threshold=True`) candidates are hydrated into
primary/context evidence — weak candidates stay in `RagSearchResult` for
debug/calibration but never reach the evidence shapes returned here. Reuses
`query.sql.hydration` so RAG evidence has the exact same compact shape as
SQL/graph evidence (canonical ID + GlobalId + IFC class + name/summary, not
full canonical JSON — spec_v004 §11).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import DbIfcRelationship, IfcEntity
from app.query.rag.relationship_expansion import expand_relationship_endpoints
from app.query.rag.schemas import RagSearchResult, SelectedEntitySummary
from app.query.sql.entities import entity_hydration_columns
from app.query.sql.hydration import (
    hydrate_context_entity,
    hydrate_primary_entity,
    hydrate_relationship,
)
from app.viewer.actions import SelectionAction, ViewerActions, build_viewer_actions

_ET = IfcEntity.__table__
_RT = DbIfcRelationship.__table__


def hydrate_selected_entities(
    session: Session, source_model_id: int, entity_ids: list[int]
) -> list[SelectedEntitySummary]:
    """Compact selected-object summaries (spec_v004 §13). Caller (RagSearchPlan)
    already caps `entity_ids` at 5; this never sends full canonical JSON."""
    if not entity_ids:
        return []
    rows = session.execute(
        sa.select(*entity_hydration_columns()).where(
            _ET.c.source_model_id == source_model_id, _ET.c.id.in_(entity_ids)
        )
    ).all()
    by_id = {r.id: r for r in rows}
    summaries = []
    for entity_id in entity_ids:
        row = by_id.get(entity_id)
        if row is None:
            continue
        primary = hydrate_primary_entity(row)
        summaries.append(
            SelectedEntitySummary(
                entity_id=row.id,
                global_id=row.global_id,
                ifc_class=row.ifc_class,
                name=primary.name,
                summary=primary.summary,
            )
        )
    return summaries


def hydrate_rag_result(
    session: Session,
    source_model_id: int,
    result: RagSearchResult,
    expand_endpoints: bool,
) -> tuple[list, list, list, ViewerActions, list[str]]:
    """Returns (primary_entities, context_entities, relationships, viewer_actions, warnings)."""
    accepted_entity_ids = {c.canonical_id for c in result.entity_candidates if c.passed_threshold}
    accepted_relationship_ids = {
        c.canonical_id for c in result.relationship_candidates if c.passed_threshold
    }
    warnings: list[str] = []

    primary_entities = []
    if accepted_entity_ids:
        rows = session.execute(
            sa.select(*entity_hydration_columns()).where(
                _ET.c.source_model_id == source_model_id, _ET.c.id.in_(accepted_entity_ids)
            )
        ).all()
        primary_entities = [hydrate_primary_entity(r) for r in rows]

    relationships_out = []
    context_entities = []
    seen_context_ids: set[int] = set()
    if accepted_relationship_ids:
        rel_rows = session.execute(
            sa.select(_RT.c.id, _RT.c.global_id, _RT.c.ifc_class, _RT.c.name).where(
                _RT.c.source_model_id == source_model_id, _RT.c.id.in_(accepted_relationship_ids)
            )
        ).all()
        relationships_out = [hydrate_relationship(r) for r in rel_rows]

        if expand_endpoints:
            for rel_id in accepted_relationship_ids:
                expansion = expand_relationship_endpoints(session, source_model_id, rel_id)
                warnings.extend(expansion.warnings)
                for ent_row in expansion.resolved_endpoints:
                    if ent_row.id in accepted_entity_ids or ent_row.id in seen_context_ids:
                        continue
                    seen_context_ids.add(ent_row.id)
                    context_entities.append(hydrate_context_entity(ent_row))

    has_any = bool(primary_entities or relationships_out or context_entities)
    viewer_actions = build_viewer_actions(
        selection_action=SelectionAction.SELECT_AND_FIT if has_any else SelectionAction.NONE,
        primary_global_ids=[p.global_id for p in primary_entities],
        context_global_ids=[c.global_id for c in context_entities],
    )
    return primary_entities, context_entities, relationships_out, viewer_actions, warnings
