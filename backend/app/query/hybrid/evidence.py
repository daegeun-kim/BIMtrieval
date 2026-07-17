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

from app.api.schemas.models import DetailValue
from app.api.schemas.response import ResultSummary, SampleDetail
from app.config.settings import Settings
from app.db.models import DbIfcRelationship, IfcEntity
from app.query.hybrid.schemas import EvidencePackage
from app.query.sql import entities as entity_ops
from app.query.sql.entities import entity_hydration_columns
from app.query.sql.hydration import (
    hydrate_context_entity,
    hydrate_primary_entity,
    hydrate_relationship,
)
from app.viewer import details as detail_ops

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


def build_sample_detail(
    session: Session, source_model_id: int, global_id: str
) -> SampleDetail | None:
    """Bounded details for ONE deterministically chosen entity (task13 §3).

    Called only on explicit sample-detail intent. The entity is chosen by the
    backend from the ordered result set and every value is read from the stored
    canonical JSON through the same centralized allowlist the details endpoint
    uses — so the answer model cannot invent a sample or a property value.
    """
    row = entity_ops.get_entity_canonical(session, source_model_id, global_id)
    if row is None:
        return None
    canonical = row.canonical_json if isinstance(row.canonical_json, dict) else {}
    identity = canonical.get("identity") if isinstance(canonical.get("identity"), dict) else {}
    storey_name, _ = detail_ops.storey_of(canonical)
    return SampleDetail(
        global_id=row.global_id,
        ifc_class=row.ifc_class,
        name=detail_ops.safe_str(identity.get("name")),
        storey_name=storey_name,
        materials=detail_ops.select_materials(canonical),
        quantities=[
            DetailValue(name=v.name, value=v.value, source_set=v.source_set, unit=v.unit)
            for v in detail_ops.select_quantities(canonical)
        ],
        properties=[
            DetailValue(name=v.name, value=v.value, source_set=v.source_set, unit=v.unit)
            for v in detail_ops.select_properties(canonical)
        ],
    )


def build_result_summary(pkg: EvidencePackage) -> ResultSummary:
    """The compact, deterministic result description (task13 §3).

    `exact_total` prefers the true match total over the evidence sample size, so
    a count of 205 stays 205 no matter how the viewer/LLM caps applied.
    """
    exact_total = pkg.viewer_matches_total
    if exact_total is None:
        for key in ("sql_result", "primary_matches"):
            if key in pkg.exact_totals:
                exact_total = pkg.exact_totals[key]
                break
    return ResultSummary(
        exact_total=exact_total,
        viewer_match_count=len(pkg.viewer_global_ids),
        viewer_matches_total=pkg.viewer_matches_total,
        truncated=pkg.viewer_matches_truncated,
        class_counts=dict(pkg.class_histogram),
        sample_detail=pkg.sample_detail,
    )


def build_group_answer_payload(
    question: str,
    analysis_intent: str | None,
    source_model_id: int | None,
    groups: list[Any],
    settings: Settings,
) -> dict[str, Any]:
    """Bounded, secret-free evidence for the group-aware answerer (Task 17 §7, §8).

    Every bounded group gets a compact factual summary; each group's allocated
    detailed examples (≤50 total across groups) are included. NO similarity
    scores, raw predicates, plans, or database ids are surfaced."""
    excerpt_cap = settings.vocab_max_profile_excerpt_chars

    def _entity(e: Any) -> dict[str, Any]:
        return {"ifc_class": e.ifc_class, "name": e.name, "global_id": e.global_id}

    group_payloads = []
    for g in groups:
        group_payloads.append(
            {
                "group_id": g.group_id,
                "facet_id": g.facet_id,
                "label": g.label,
                "role_hint": g.role_hint,  # PLANNER hypothesis, not a fact
                "authority": g.authority,
                "coverage": g.coverage,
                "source_kinds": g.source_kinds,
                "exact_count": g.exact_count,
                "rag_candidate_count": g.rag_candidate_count,
                "ontology_definition": (g.ontology_definition or "")[:excerpt_cap] or None,
                "factual_profile": g.factual_profile,
                "examples": [_entity(e) for e in g.allocated_examples],
                "example_note": (
                    "bounded sample" if g.allocation_truncated else "all members shown"
                ),
                "warnings": g.warnings[:3],
            }
        )

    return {
        "question": question,
        "analysis_intent": analysis_intent,
        "source_model_id": source_model_id,
        "evidence_groups": group_payloads,
        "guidance": (
            "Each group is ONE independent semantic claim you may accept or reject. role_hint is "
            "the planner's hypothesis, NOT a fact — judge relevance from the factual_profile and "
            "the user's question. authority=exact is a precise database count for that predicate; "
            "structured_candidate is a discovered predicate exactly counted (count real, relevance "
            "yours); semantic_candidate is a bounded RAG candidate set (never an exact total). "
            "NEVER sum associated groups into a concept total (e.g. do not add stairs + railings + "
            "doors into one 'circulation' number). An exact count of 0 or an absent class means "
            "'not explicitly represented', not that the feature is absent. Put only entity-bearing "
            "groups you accept into viewer_primary_group_ids / viewer_context_group_ids."
        ),
    }


def build_answer_payload(pkg: EvidencePackage) -> dict[str, Any]:
    """Compact, bounded, secret-free evidence for the grounded-answer call
    (spec_v005 §11). RAG internal scores are intentionally excluded.

    `result_summary` carries the exact total and compact per-class counts so the
    answer model can state the outcome without enumerating components. The
    entity lists remain bounded grounding evidence (50/50/20) — never the viewer
    match set, which can be far larger and is never sent to the LLM (task13 §3).
    """

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
        "result_summary": build_result_summary(pkg).model_dump(mode="json"),
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
