"""Evidence package + path-run bookkeeping (spec_v005 §10).

The `EvidencePackage` is the bounded, provenance-aware object the orchestrator
produces and the answer stage consumes. It carries compact hydrated evidence
(canonical ids + GlobalIds + names, never full canonical JSON), separated
exact/semantic groups, exact totals kept apart from samples, and explicit
conflict / missing-coverage / partial-failure notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.api.schemas.response import (
    ContextEntityResult,
    ModelCandidate,
    PrimaryEntityResult,
    RelationshipResult,
    SampleDetail,
)
from app.shared.types import AnswerBasis

# Probe-evidence authority + coverage vocabularies (Task 16 §8). Kept as string
# constants (not enums) so they serialize cleanly into the answer payload.
AUTHORITY_EXACT = "exact"
AUTHORITY_STRUCTURED = "structured_candidate"
AUTHORITY_SEMANTIC = "semantic_candidate"
AUTHORITY_GENERAL = "general_context"
AUTHORITIES = frozenset(
    {AUTHORITY_EXACT, AUTHORITY_STRUCTURED, AUTHORITY_SEMANTIC, AUTHORITY_GENERAL}
)

COVERAGE_COMPLETE = "complete"
COVERAGE_BOUNDED = "bounded"
COVERAGE_UNKNOWN = "unknown"
COVERAGE_UNAVAILABLE = "unavailable"
COVERAGE_FAILED = "failed"
COVERAGES = frozenset(
    {COVERAGE_COMPLETE, COVERAGE_BOUNDED, COVERAGE_UNKNOWN, COVERAGE_UNAVAILABLE, COVERAGE_FAILED}
)


@dataclass
class PathRun:
    name: str
    ran: bool = False
    ok: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RagInternalItem:
    """RAG scores/ranks kept internal — never surfaced to the user by default
    (spec_v005 §9 rank behavior, §11)."""

    source_kind: str
    canonical_id: int
    similarity: float
    per_kind_rank: int


@dataclass
class EvidencePackage:
    question: str
    route: str
    scope: str
    source_model_id: int | None = None

    primary_entities: list[PrimaryEntityResult] = field(default_factory=list)
    context_entities: list[ContextEntityResult] = field(default_factory=list)
    relationships: list[RelationshipResult] = field(default_factory=list)
    model_candidates: list[ModelCandidate] = field(default_factory=list)

    sql_facts: dict | None = None
    exact_totals: dict = field(default_factory=dict)
    evidence_groups: dict = field(default_factory=dict)
    combination: str | None = None
    rag_internal: list[RagInternalItem] = field(default_factory=list)

    # --- Viewer match identities (task13 §2) ---
    # Deliberately separate from `primary_entities`, which `apply_bounds`
    # truncates to the 50-item answer-LLM evidence limit. These identities are
    # for highlighting only (up to max_viewer_match_ids) and are never sent to
    # the LLM. `viewer_matches_total` is the true total regardless of both caps.
    viewer_global_ids: list[str] = field(default_factory=list)
    viewer_matches_total: int | None = None
    viewer_matches_truncated: bool = False
    class_histogram: dict[str, int] = field(default_factory=dict)
    # Bounded details for one deterministically chosen entity, populated only on
    # explicit sample-detail intent (task13 §3).
    sample_detail: SampleDetail | None = None

    conflicts: list[str] = field(default_factory=list)
    missing_coverage: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    partial_failures: list[str] = field(default_factory=list)
    overflow_summaries: list[str] = field(default_factory=list)

    answer_basis: AnswerBasis = AnswerBasis.INSUFFICIENT_EVIDENCE
    path_runs: list[PathRun] = field(default_factory=list)
