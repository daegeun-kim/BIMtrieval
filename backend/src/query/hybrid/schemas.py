"""Evidence package + path-run bookkeeping (spec_v005 §10).

The `EvidencePackage` is the bounded, provenance-aware object the orchestrator
produces and the answer stage consumes. It carries compact hydrated evidence
(canonical ids + GlobalIds + names, never full canonical JSON), separated
exact/semantic groups, exact totals kept apart from samples, and explicit
conflict / missing-coverage / partial-failure notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.schemas.response import (
    ContextEntityResult,
    ModelCandidate,
    PrimaryEntityResult,
    RelationshipResult,
)
from shared.types import AnswerBasis


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

    conflicts: list[str] = field(default_factory=list)
    missing_coverage: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    partial_failures: list[str] = field(default_factory=list)
    overflow_summaries: list[str] = field(default_factory=list)

    answer_basis: AnswerBasis = AnswerBasis.INSUFFICIENT_EVIDENCE
    path_runs: list[PathRun] = field(default_factory=list)
