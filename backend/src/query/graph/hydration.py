"""Hydrate a TraversalResult into Task 04 evidence + viewer actions
(spec_v002 §10, §17: primary matches vs. relationship-context endpoints)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session
from viewer.actions import SelectionAction, ViewerActions, build_viewer_actions

from bim_rag.schema.models import IfcEntity
from query.graph.schemas import TraversalResult
from query.sql.entities import entity_hydration_columns
from query.sql.hydration import hydrate_context_entity, hydrate_primary_entity

_ET = IfcEntity.__table__

# A single hub relationship (e.g. one IfcRelContainedInSpatialStructure holding
# thousands of RelatedElements) can legitimately fan out to thousands of context
# entities at depth > 1. Evidence must stay bounded (spec_v002 §14: "bounded,
# relevant evidence") even though the exact traversal itself is uncapped except
# by depth/cycle rules — so hydration caps how many context entities are
# hydrated into evidence, while the caller still has the exact total via
# `len(result.context_entity_ids)`.
MAX_HYDRATED_CONTEXT_ENTITIES = 200


def hydrate_traversal(
    session: Session, source_model_id: int, result: TraversalResult
) -> tuple[list, list, ViewerActions]:
    all_primary_ids = result.primary_entity_ids
    all_context_ids = set(sorted(result.context_entity_ids)[:MAX_HYDRATED_CONTEXT_ENTITIES])
    all_ids = all_primary_ids | all_context_ids
    if not all_ids:
        return [], [], build_viewer_actions()

    rows = session.execute(
        sa.select(*entity_hydration_columns()).where(
            _ET.c.source_model_id == source_model_id, _ET.c.id.in_(all_ids)
        )
    ).all()
    by_id = {r.id: r for r in rows}

    primary = [hydrate_primary_entity(by_id[i]) for i in all_primary_ids if i in by_id]
    context = [hydrate_context_entity(by_id[i]) for i in sorted(all_context_ids) if i in by_id]

    viewer_actions = build_viewer_actions(
        selection_action=SelectionAction.SELECT_AND_FIT
        if (primary or context)
        else SelectionAction.NONE,
        primary_global_ids=[p.global_id for p in primary],
        context_global_ids=[c.global_id for c in context],
    )
    return primary, context, viewer_actions
