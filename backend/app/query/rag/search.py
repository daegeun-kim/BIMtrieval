"""Source-scoped semantic search over rag_documents (spec_v004 §3, §6, §7).

The sole builder of pgvector queries for the RAG path — always parameterized
via the ORM column's own comparator (`Vector.cosine_distance`), always
scoped by source_model_id + source_kind + document_type + embedding_model +
embedding_dim + non-null embedding. Entity and relationship kinds are
searched independently; their raw similarity distributions are never
assumed interchangeable (spec_v004 §7).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import trace
from app.db.models import RagDocument
from app.query.rag.embedding_service import EMBEDDING_DIM, EMBEDDING_MODEL_NAME, EmbeddingService
from app.query.rag.errors import IncompatibleEmbeddingError
from app.query.rag.fusion import reciprocal_rank_fusion
from app.query.rag.hydration import hydrate_selected_entities
from app.query.rag.schemas import (
    DOCUMENT_TEXT_EXCERPT_CHARS,
    RagCandidate,
    RagSearchPlan,
    RagSearchResult,
)
from app.query.rag.thresholds import get_threshold

_RD = RagDocument.__table__

_KIND_DOCUMENT_TYPE = {
    "entity": "entity_description",
    "relationship": "relationship_description",
}


def check_compatibility(session: Session, source_model_id: int, source_kind: str) -> None:
    """Raise IncompatibleEmbeddingError unless every stored vector for this
    (source_model_id, source_kind) matches the live query embedding model
    and dimension (spec_v004 §3). Zero stored rows for this kind is not an
    error here — `search_kind` simply returns no candidates in that case."""
    document_type = _KIND_DOCUMENT_TYPE[source_kind]
    rows = session.execute(
        sa.select(sa.distinct(_RD.c.embedding_model), _RD.c.embedding_dim).where(
            _RD.c.source_model_id == source_model_id,
            _RD.c.source_kind == source_kind,
            _RD.c.document_type == document_type,
        )
    ).all()
    for model_name, dim in rows:
        if model_name != EMBEDDING_MODEL_NAME or dim != EMBEDDING_DIM:
            raise IncompatibleEmbeddingError(
                f"stored {source_kind} documents for source_model_id={source_model_id} use "
                f"embedding_model={model_name!r} dim={dim}, but the live query embedding is "
                f"{EMBEDDING_MODEL_NAME!r} dim={EMBEDDING_DIM} — refusing to compare "
                "incompatible vectors"
            )


def search_kind(
    session: Session,
    source_model_id: int,
    source_kind: str,
    query_vector: list[float],
    top_k: int,
    threshold: float,
    scope_entity_ids: list[int] | None = None,
    scope_entity_select: sa.Select | None = None,
) -> list[RagCandidate]:
    """Independent per-kind pgvector search (spec_v004 §7).

    `scope_entity_ids` restricts an ENTITY search to an already-computed
    structured scope (Task 24 §5.3): RAG then ranks inside the authoritative SQL
    result rather than across the whole model. An empty list is a real,
    meaningful scope — it returns nothing rather than widening, because "the
    structured predicate matched nothing" and "no scope was requested" are
    different facts and must not produce the same answer.

    `scope_entity_select` is the task26 §10.6 database-side form: a SELECT of
    entity ids compiled from the same authoritative predicate, applied as an
    `IN (subquery)` so a 100k-entity scope never materializes into Python.
    """
    check_compatibility(session, source_model_id, source_kind)
    document_type = _KIND_DOCUMENT_TYPE[source_kind]
    canonical_col = _RD.c.entity_id if source_kind == "entity" else _RD.c.relationship_id

    if scope_entity_ids is not None and source_kind == "entity" and not scope_entity_ids:
        return []

    distance_expr = _RD.c.embedding.cosine_distance(query_vector)
    predicates = [
        _RD.c.source_model_id == source_model_id,
        _RD.c.source_kind == source_kind,
        _RD.c.document_type == document_type,
        _RD.c.embedding_model == EMBEDDING_MODEL_NAME,
        _RD.c.embedding_dim == EMBEDDING_DIM,
        _RD.c.embedding.is_not(None),
        canonical_col.is_not(None),
    ]
    if scope_entity_ids is not None and source_kind == "entity":
        predicates.append(_RD.c.entity_id.in_(list(scope_entity_ids)))
    if scope_entity_select is not None and source_kind == "entity":
        predicates.append(_RD.c.entity_id.in_(scope_entity_select))

    stmt = (
        sa.select(
            _RD.c.id,
            canonical_col.label("canonical_id"),
            _RD.c.document_text,
            _RD.c.embedding_model,
            _RD.c.embedding_dim,
            _RD.c.text_template_version,
            distance_expr.label("distance"),
        )
        .where(*predicates)
        .order_by(distance_expr)
        .limit(top_k)
    )
    rows = session.execute(stmt).all()

    candidates: list[RagCandidate] = []
    for rank, row in enumerate(rows, start=1):
        similarity = 1.0 - float(row.distance)
        candidates.append(
            RagCandidate(
                rag_document_id=row.id,
                source_kind=source_kind,
                document_type=document_type,
                canonical_id=row.canonical_id,
                cosine_distance=float(row.distance),
                similarity=similarity,
                per_kind_rank=rank,
                embedding_model=row.embedding_model,
                embedding_dim=row.embedding_dim,
                text_template_version=row.text_template_version,
                document_text_excerpt=row.document_text[:DOCUMENT_TEXT_EXCERPT_CHARS],
                passed_threshold=similarity >= threshold,
            )
        )
    return candidates


def run_rag_search(
    session: Session, embedding_service: EmbeddingService, plan: RagSearchPlan
) -> RagSearchResult:
    """Top-level entry point: embed the query once, search each requested
    kind independently, fuse only when both kinds ran, and hydrate any
    selected-object context (spec_v004 §5-9, §13)."""
    threshold = get_threshold(plan.minimum_similarity_profile)
    query_vector = embedding_service.embed_query(plan.semantic_query)

    kinds = [
        kind
        for kind, wanted in (
            ("entity", plan.search_entity_documents),
            ("relationship", plan.search_relationship_documents),
        )
        if wanted
    ]

    entity_candidates: list[RagCandidate] = []
    relationship_candidates: list[RagCandidate] = []
    # Opt-in trace (task13 §1). The query vector is a bound parameter, so the
    # captured statement holds a placeholder — the embedding cannot be printed.
    # No entity/relationship id list is recorded, only a bounded histogram.
    with trace.trace_rag_search(
        semantic_query=plan.semantic_query,
        document_kinds=kinds,
        top_k=plan.top_k_per_kind,
        minimum_similarity=threshold,
    ) as rec:
        if plan.search_entity_documents:
            entity_candidates = search_kind(
                session,
                plan.source_model_id,
                "entity",
                query_vector,
                plan.top_k_per_kind,
                threshold,
                scope_entity_ids=plan.scope_entity_ids,
            )
        if plan.search_relationship_documents:
            relationship_candidates = search_kind(
                session,
                plan.source_model_id,
                "relationship",
                query_vector,
                plan.top_k_per_kind,
                threshold,
            )
        retrieved = entity_candidates + relationship_candidates
        rec.retrieved_count = len(retrieved)
        rec.result_histogram = trace.histogram(c.document_type for c in retrieved)
        if retrieved:
            similarities = [c.similarity for c in retrieved]
            rec.similarity_min = min(similarities)
            rec.similarity_max = max(similarities)

    fused = []
    if plan.search_entity_documents and plan.search_relationship_documents:
        fused = reciprocal_rank_fusion(entity_candidates, relationship_candidates)

    sufficient_evidence = any(
        c.passed_threshold for c in entity_candidates + relationship_candidates
    )
    warnings: list[str] = []
    if plan.scope_entity_ids is not None and not plan.scope_entity_ids:
        # Distinct from "nothing was similar enough": the structured predicate
        # matched no objects, so there was nothing to rank. Reporting these the
        # same way would let an empty scope read as a semantic miss (§5.3, §6
        # "a bounded RAG miss is not proof of absence").
        warnings.append(
            "the structured scope for this question matched no objects, so no semantic "
            "ranking was performed; this is not a semantic miss"
        )
    elif not sufficient_evidence:
        warnings.append(
            "no candidate passed the similarity threshold; treat as insufficient_evidence"
        )

    selected_summaries = (
        hydrate_selected_entities(session, plan.source_model_id, plan.selected_entity_ids)
        if plan.selected_entity_ids
        else []
    )

    return RagSearchResult(
        source_model_id=plan.source_model_id,
        semantic_query=plan.semantic_query,
        threshold_profile=plan.minimum_similarity_profile,
        threshold_value=threshold,
        entity_candidates=entity_candidates,
        relationship_candidates=relationship_candidates,
        fused=fused,
        selected_entity_summaries=selected_summaries,
        sufficient_evidence=sufficient_evidence,
        warnings=warnings,
    )
