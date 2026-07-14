"""Assemble the sanitized planner context — the input to OpenAI call 1
(spec_v005 §5, §6).

The planner receives: the current question, bounded history, current scope and
active model, up to five selected-entity summaries, a rich BUT sanitized schema
context (class/pset/qset/attribute names only — never secrets, never full
tables, never raw SQL authority), the available operation/route vocabularies,
and the limits/unit conventions.

Everything here is derived read-only from the database schema and is safe to
send to the model. No credentials, no `canonical_json` blobs, no SQL text.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.schemas.request import SessionQueryRequest
from config.settings import Settings
from llm.schemas import (
    CombinationOp,
    ExecutionMode,
    SqlOperation,
    ViewerIntent,
)
from query.rag.hydration import hydrate_selected_entities
from query.session import SessionState
from query.sql import catalog as catalog_ops
from query.sql.field_registry import build_schema_catalog
from query.sql.schemas import FieldKind, ListModelsPlan, Operator

_MAX_CLASSES = 80
_MAX_SETS = 40
_MAX_FIELDS_PER_SET = 20


def _compact_schema(session: Session, source_model_id: int) -> dict[str, Any]:
    cat = build_schema_catalog(session, source_model_id)

    def _cap_sets(sets: dict[str, list[str]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name in list(sets.keys())[:_MAX_SETS]:
            out[name] = sets[name][:_MAX_FIELDS_PER_SET]
        return out

    return {
        "source_model_id": source_model_id,
        "entity_classes": cat.entity_classes[:_MAX_CLASSES],
        "relationship_classes": cat.relationship_classes,
        "attribute_fields": cat.attribute_fields,
        "type_fact_fields": cat.type_fact_fields,
        "property_sets": _cap_sets(cat.property_sets),
        "quantity_sets": _cap_sets(cat.quantity_sets),
        "note": (
            "Use only these class/field/set names. quantity/dimension fields are numeric; "
            "attribute/property/type_fact are text unless obviously numeric."
        ),
    }


def _catalog_context(session: Session) -> dict[str, Any]:
    rows = catalog_ops.list_models(session, ListModelsPlan(limit=50))
    return {
        "available_models": [
            {
                "source_model_id": r.source_model_id,
                "display_name": getattr(r, "display_name", None),
                "version_label": getattr(r, "version_label", None),
                "is_current": getattr(r, "is_current", None),
                "family_key": getattr(r, "family_key", None),
                "status": getattr(r, "status", None),
            }
            for r in rows
        ]
    }


def _operation_vocab() -> dict[str, Any]:
    return {
        "sql_operations": [op.value for op in SqlOperation],
        "field_kinds": [k.value for k in FieldKind],
        "operators": [o.value for o in Operator],
        "execution_modes": [m.value for m in ExecutionMode],
        "combinations": [c.value for c in CombinationOp],
        "viewer_intents": [v.value for v in ViewerIntent],
        "threshold_profiles": ["default_v001", "high_precision_v001"],
    }


def build_planner_context(
    session: Session,
    request: SessionQueryRequest,
    state: SessionState,
    settings: Settings,
) -> dict[str, Any]:
    active_id = request.active_source_model_id
    scope = "active_model" if active_id is not None else "model_catalog"

    selected_summaries: list[dict[str, Any]] = []
    if active_id is not None and request.selected_entity_ids:
        for s in hydrate_selected_entities(
            session, active_id, request.selected_entity_ids[: settings.max_selected_entity_ids]
        ):
            selected_summaries.append(
                {
                    "entity_id": s.entity_id,
                    "ifc_class": s.ifc_class,
                    "name": s.name,
                    "global_id": s.global_id,
                }
            )

    context: dict[str, Any] = {
        "question": request.question,
        "scope": scope,
        "active_source_model_id": active_id,
        "history": [
            {"role": t.role, "content": t.content}
            for t in request.history[-settings.max_history_turns :]
        ],
        "selected_entities": selected_summaries,
        "previous_result_entity_ids": state.last_primary_entity_ids[:50],
        "operations": _operation_vocab(),
        "limits": {
            "max_list_limit": settings.max_list_limit,
            "max_graph_depth": settings.max_graph_depth,
            "max_selected_entity_ids": settings.max_selected_entity_ids,
        },
    }

    if active_id is not None:
        context["schema"] = _compact_schema(session, active_id)
    else:
        context["catalog"] = _catalog_context(session)

    return context
