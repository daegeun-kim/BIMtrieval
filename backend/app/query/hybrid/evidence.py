"""Hydrate combined canonical ids and build the bounded answer payload
(spec_v005 §10, §11).

Two jobs:

1. Fetch compact evidence rows for a set of canonical ids (order-preserving),
   reusing the SQL hydration shapes so hybrid evidence looks identical to
   single-path evidence — canonical id + GlobalId + IFC class + name, never full
   canonical JSON.
2. Enforce the answer-model evidence bounds (50 primary / 50 context / 20
   relationships, spec_v005 §10) with a *deterministic* overflow summary, and
   serialize a secret-free, bounded payload for the grounded-answer call.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.db.models import DbIfcRelationship, IfcEntity
from app.query.hybrid.schemas import EvidencePackage
from app.query.sql.entities import entity_hydration_columns
from app.query.sql.hydration import (
    hydrate_context_entity,
    hydrate_primary_entity,
    hydrate_relationship,
)

_ET = IfcEntity.__table__
_RT = DbIfcRelationship.__table__


def _fetch_rows(session: Session, source_model_id: int, ids: list[int]) -> dict[int, Any]:
    if not ids:
        return {}
    rows = session.execute(
        sa.select(*entity_hydration_columns()).where(
            _ET.c.source_model_id == source_model_id, _ET.c.id.in_(ids)
        )
    ).all()
    return {r.id: r for r in rows}


def fetch_primary(session: Session, source_model_id: int, ids: list[int]) -> list:
    by_id = _fetch_rows(session, source_model_id, ids)
    return [hydrate_primary_entity(by_id[i]) for i in ids if i in by_id]


def fetch_context(session: Session, source_model_id: int, ids: list[int]) -> list:
    by_id = _fetch_rows(session, source_model_id, ids)
    return [hydrate_context_entity(by_id[i]) for i in ids if i in by_id]


def fetch_relationships(session: Session, source_model_id: int, ids: list[int]) -> list:
    if not ids:
        return []
    rows = session.execute(
        sa.select(_RT.c.id, _RT.c.global_id, _RT.c.ifc_class, _RT.c.name).where(
            _RT.c.source_model_id == source_model_id, _RT.c.id.in_(ids)
        )
    ).all()
    by_id = {r.id: r for r in rows}
    return [hydrate_relationship(by_id[i]) for i in ids if i in by_id]


def apply_bounds(pkg: EvidencePackage, settings: Settings) -> None:
    """Truncate evidence to the answer-model limits, preserving exact totals in
    `exact_totals` and recording a deterministic overflow summary (spec_v005 §10)."""
    pkg.exact_totals.setdefault("primary_entities", len(pkg.primary_entities))
    pkg.exact_totals.setdefault("context_entities", len(pkg.context_entities))
    pkg.exact_totals.setdefault("relationships", len(pkg.relationships))

    if len(pkg.primary_entities) > settings.max_primary_entities:
        total = len(pkg.primary_entities)
        pkg.primary_entities = pkg.primary_entities[: settings.max_primary_entities]
        pkg.overflow_summaries.append(
            f"{total} primary matches found; showing the first {settings.max_primary_entities} "
            "(exact total preserved in exact_totals.primary_entities)"
        )
    if len(pkg.context_entities) > settings.max_context_entities:
        total = len(pkg.context_entities)
        pkg.context_entities = pkg.context_entities[: settings.max_context_entities]
        pkg.overflow_summaries.append(
            f"{total} context entities found; showing the first {settings.max_context_entities}"
        )
    if len(pkg.relationships) > settings.max_relationships:
        total = len(pkg.relationships)
        pkg.relationships = pkg.relationships[: settings.max_relationships]
        pkg.overflow_summaries.append(
            f"{total} relationships found; showing the first {settings.max_relationships}"
        )


def build_answer_payload(pkg: EvidencePackage) -> dict[str, Any]:
    """Compact, bounded, secret-free evidence for the grounded-answer call
    (spec_v005 §11). RAG internal scores are intentionally excluded."""

    def _entity(e: Any) -> dict[str, Any]:
        return {
            "ifc_class": e.ifc_class,
            "name": e.name,
            "global_id": e.global_id,
            "summary": e.summary,
        }

    return {
        "question": pkg.question,
        "route": pkg.route,
        "scope": pkg.scope,
        "source_model_id": pkg.source_model_id,
        "answer_basis": pkg.answer_basis.value,
        "combination": pkg.combination,
        "exact_totals": pkg.exact_totals,
        "evidence_groups": pkg.evidence_groups,
        "sql_facts": pkg.sql_facts,
        "model_candidates": [
            {
                "source_model_id": c.source_model_id,
                "display_name": c.display_name,
                "version_label": c.version_label,
                "is_current": c.is_current,
                "status": c.status.value if c.status else None,
            }
            for c in pkg.model_candidates
        ],
        "primary_entities": [_entity(e) for e in pkg.primary_entities],
        "context_entities": [_entity(e) for e in pkg.context_entities],
        "relationships": [
            {"ifc_class": r.ifc_class, "name": r.name, "global_id": r.global_id}
            for r in pkg.relationships
        ],
        "conflicts": pkg.conflicts,
        "missing_coverage": pkg.missing_coverage,
        "overflow_summaries": pkg.overflow_summaries,
        "warnings": pkg.warnings,
        "partial_failures": pkg.partial_failures,
    }
