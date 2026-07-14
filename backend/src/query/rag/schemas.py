"""Typed RAG search plan + result shapes (spec_v004 §5, §7, §9, §13).

Parallel to `query.sql.schemas`: this is the real, validated typed plan used
to exercise the RAG path directly. `llm.schemas.RagPlan` (Task 04) remains
the LLM-facing envelope for a future planner (v005) and is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_TOP_K_PER_KIND = 30
MAX_TOP_K_PER_KIND = 100
DEFAULT_VISIBLE_LIMIT = 10
MAX_VISIBLE_LIMIT = 50
MAX_SELECTED_ENTITY_IDS = 5
DOCUMENT_TEXT_EXCERPT_CHARS = 300


class RagSearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_model_id: int
    semantic_query: str = Field(min_length=1, max_length=2000)
    search_entity_documents: bool = True
    search_relationship_documents: bool = True
    top_k_per_kind: int = Field(default=DEFAULT_TOP_K_PER_KIND, ge=1, le=MAX_TOP_K_PER_KIND)
    visible_limit: int = Field(default=DEFAULT_VISIBLE_LIMIT, ge=1, le=MAX_VISIBLE_LIMIT)
    minimum_similarity_profile: str = "default_v001"
    expand_relationship_endpoints: bool = True
    selected_entity_ids: list[int] = Field(default_factory=list, max_length=MAX_SELECTED_ENTITY_IDS)

    @model_validator(mode="after")
    def _at_least_one_kind_enabled(self) -> "RagSearchPlan":
        if not self.search_entity_documents and not self.search_relationship_documents:
            raise ValueError(
                "at least one of search_entity_documents/search_relationship_documents must be true"
            )
        return self


@dataclass
class RagCandidate:
    """One per-kind retrieval candidate, before fusion (spec_v004 §7).

    Preserved even when `passed_threshold` is False — weak candidates stay
    available for debug/evaluation logs but must never be presented as
    accepted evidence (spec_v004 §8).
    """

    rag_document_id: int
    source_kind: str  # "entity" | "relationship"
    document_type: str
    canonical_id: int  # entity_id or relationship_id
    cosine_distance: float
    similarity: float  # 1 - cosine_distance
    per_kind_rank: int  # 1-based
    embedding_model: str
    embedding_dim: int
    text_template_version: str
    document_text_excerpt: str
    passed_threshold: bool


@dataclass
class FusedCandidate:
    """A reciprocal-rank-fused entry (spec_v004 §9).

    Entity and relationship items never collide in the fusion key —
    (source_kind, canonical_id) — so this list is a genuine merge of two
    distinct item kinds, not a single re-scored list.
    """

    source_kind: str
    canonical_id: int
    rrf_score: float
    per_kind_rank: int
    similarity: float
    passed_threshold: bool


@dataclass
class SelectedEntitySummary:
    """Compact selected-object context (spec_v004 §13), never full canonical JSON."""

    entity_id: int
    global_id: str
    ifc_class: str
    name: str | None
    summary: str | None


@dataclass
class RagSearchResult:
    source_model_id: int
    semantic_query: str
    threshold_profile: str
    threshold_value: float
    entity_candidates: list[RagCandidate] = field(default_factory=list)
    relationship_candidates: list[RagCandidate] = field(default_factory=list)
    fused: list[FusedCandidate] = field(default_factory=list)
    selected_entity_summaries: list[SelectedEntitySummary] = field(default_factory=list)
    sufficient_evidence: bool = False
    warnings: list[str] = field(default_factory=list)
