"""Reciprocal rank fusion correctness (spec_v004 §9). Pure function, synthetic
ranked lists — no database access, no model load."""

from __future__ import annotations

from app.query.rag.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion
from app.query.rag.schemas import RagCandidate


def _candidate(
    kind: str, canonical_id: int, rank: int, similarity: float, passed: bool = True
) -> RagCandidate:
    return RagCandidate(
        rag_document_id=canonical_id,
        source_kind=kind,
        document_type=f"{kind}_description",
        canonical_id=canonical_id,
        cosine_distance=1.0 - similarity,
        similarity=similarity,
        per_kind_rank=rank,
        embedding_model="BAAI/bge-m3",
        embedding_dim=1024,
        text_template_version="v001",
        document_text_excerpt="...",
        passed_threshold=passed,
    )


def test_rrf_score_matches_documented_formula():
    entities = [_candidate("entity", 1, 1, 0.9), _candidate("entity", 2, 2, 0.8)]
    relationships = [_candidate("relationship", 10, 1, 0.85)]

    fused = reciprocal_rank_fusion(entities, relationships, k=60)

    scores = {(f.source_kind, f.canonical_id): f.rrf_score for f in fused}
    assert scores[("entity", 1)] == 1.0 / (60 + 1)
    assert scores[("entity", 2)] == 1.0 / (60 + 2)
    assert scores[("relationship", 10)] == 1.0 / (60 + 1)


def test_default_k_is_60():
    assert DEFAULT_RRF_K == 60


def test_k_is_configurable():
    entities = [_candidate("entity", 1, 1, 0.9)]
    fused_k10 = reciprocal_rank_fusion(entities, [], k=10)
    fused_k60 = reciprocal_rank_fusion(entities, [], k=60)
    assert fused_k10[0].rrf_score > fused_k60[0].rrf_score


def test_entity_and_relationship_with_same_numeric_id_never_collide():
    entities = [_candidate("entity", 5, 1, 0.9)]
    relationships = [_candidate("relationship", 5, 1, 0.9)]
    fused = reciprocal_rank_fusion(entities, relationships)
    assert len(fused) == 2
    kinds = {f.source_kind for f in fused}
    assert kinds == {"entity", "relationship"}


def test_fused_list_sorted_descending_by_rrf_score():
    entities = [_candidate("entity", 1, 1, 0.9), _candidate("entity", 2, 5, 0.6)]
    relationships = [_candidate("relationship", 10, 2, 0.8)]
    fused = reciprocal_rank_fusion(entities, relationships)
    scores = [f.rrf_score for f in fused]
    assert scores == sorted(scores, reverse=True)


def test_original_rank_and_similarity_preserved_on_fused_entries():
    entities = [_candidate("entity", 1, 3, 0.72)]
    fused = reciprocal_rank_fusion(entities, [])
    assert fused[0].per_kind_rank == 3
    assert fused[0].similarity == 0.72


def test_passed_threshold_preserved_through_fusion():
    entities = [_candidate("entity", 1, 1, 0.9, passed=False)]
    fused = reciprocal_rank_fusion(entities, [])
    assert fused[0].passed_threshold is False
