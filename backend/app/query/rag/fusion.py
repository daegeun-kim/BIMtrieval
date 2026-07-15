"""Reciprocal rank fusion (spec_v004 §9).

Fuses the independent entity and relationship ranked lists into one combined
ranking. `(source_kind, canonical_id)` is the fusion key, so an entity and a
relationship never collide even if they happen to share a numeric ID —
this is a genuine merge of two distinct item kinds, not a re-scoring of one
list. Original per-kind rank/similarity are preserved on every fused entry;
the RRF score itself is never presented as a probability (spec_v004 §9).
"""

from __future__ import annotations

from app.query.rag.schemas import FusedCandidate, RagCandidate

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    entity_candidates: list[RagCandidate],
    relationship_candidates: list[RagCandidate],
    k: int = DEFAULT_RRF_K,
) -> list[FusedCandidate]:
    fused: list[FusedCandidate] = []
    for candidates in (entity_candidates, relationship_candidates):
        for candidate in candidates:
            rrf_score = 1.0 / (k + candidate.per_kind_rank)
            fused.append(
                FusedCandidate(
                    source_kind=candidate.source_kind,
                    canonical_id=candidate.canonical_id,
                    rrf_score=rrf_score,
                    per_kind_rank=candidate.per_kind_rank,
                    similarity=candidate.similarity,
                    passed_threshold=candidate.passed_threshold,
                )
            )
    fused.sort(key=lambda f: f.rrf_score, reverse=True)
    return fused
