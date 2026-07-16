"""Response envelope for POST /api/query (spec_v002 Section 16.2).

Every field is allowlisted (`extra="forbid"`). Canonical IDs may appear
(evidence/citation use, Section 13.3), but full canonical JSON, raw SQL,
credentials, and full prompts must never be placed on this envelope.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.models import DetailValue
from app.shared.types import AnswerBasis, ModelStatus, QueryRoute, QueryScope, ResponseStatus
from app.viewer.actions import ViewerActions, build_default_viewer_actions


class ModelCandidate(BaseModel):
    """spec_v002 Section 5 — a catalog model card, not an auto-loaded model."""

    model_config = ConfigDict(extra="forbid")

    source_model_id: int
    display_name: str | None = None
    version_label: str | None = None
    is_current: bool | None = None
    status: ModelStatus | None = None
    tags: list[str] = Field(default_factory=list)


class PrimaryEntityResult(BaseModel):
    """A primary-match entity. Compact summary only, not full canonical_json."""

    model_config = ConfigDict(extra="forbid")

    entity_id: int
    global_id: str
    ifc_class: str
    name: str | None = None
    summary: str | None = None


class ContextEntityResult(BaseModel):
    """A relationship-context entity (spec_v002 Section 10: distinguish from primary)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: int
    global_id: str
    ifc_class: str
    name: str | None = None
    summary: str | None = None


class RelationshipResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: int
    global_id: str
    ifc_class: str
    name: str | None = None


class EvidenceSummary(BaseModel):
    """spec_v002 Section 13 — internal basis classification, bounded evidence counts."""

    model_config = ConfigDict(extra="forbid")

    basis: AnswerBasis
    sql_match_count: int | None = None
    rag_candidate_count: int | None = None
    relationship_count: int | None = None
    notes: list[str] = Field(default_factory=list)


class SampleDetail(BaseModel):
    """Bounded details for ONE deterministically chosen matching entity.

    Populated only when the planner reports explicit sample-detail intent
    (task13 §3), e.g. "pick a sample door and show me the details". The entity
    and every value come from the database — the LLM cannot invent a sample.
    """

    model_config = ConfigDict(extra="forbid")

    global_id: str
    ifc_class: str
    name: str | None = None
    storey_name: str | None = None
    materials: list[str] = Field(default_factory=list)
    quantities: list[DetailValue] = Field(default_factory=list)
    properties: list[DetailValue] = Field(default_factory=list)


class ResultSummary(BaseModel):
    """Compact, deterministic result description (task13 §3).

    Lets the frontend state the outcome without listing every retrieved object.
    The three counts are deliberately independent:

    - `exact_total` — the true database total, never reduced by any cap;
    - `viewer_match_count` — identities actually returned for highlighting
      (at most `max_viewer_match_ids`);
    - `class_counts` — exact counts grouped by IFC class over the FULL matching
      set, so they stay correct even when the viewer set is truncated.
    """

    model_config = ConfigDict(extra="forbid")

    exact_total: int | None = None
    viewer_match_count: int = 0
    viewer_matches_total: int | None = None
    truncated: bool = False
    class_counts: dict[str, int] = Field(default_factory=dict)
    sample_detail: SampleDetail | None = None


class QueryResponseEnvelope(BaseModel):
    """spec_v002 Section 16.2 — the stable /api/query response shape."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    session_id: str
    status: ResponseStatus
    scope: QueryScope
    route: QueryRoute
    answer_basis: AnswerBasis
    answer: str
    active_source_model_id: int | None = None
    model_candidates: list[ModelCandidate] = Field(default_factory=list)
    primary_entities: list[PrimaryEntityResult] = Field(default_factory=list)
    context_entities: list[ContextEntityResult] = Field(default_factory=list)
    relationships: list[RelationshipResult] = Field(default_factory=list)
    viewer_actions: ViewerActions = Field(default_factory=build_default_viewer_actions)
    evidence_summary: EvidenceSummary
    # Compact deterministic result description (task13 §3). Additive: existing
    # clients that ignore it keep working. `primary_entities` above remains the
    # bounded evidence list for grounding/citations.
    result_summary: ResultSummary | None = None
    warnings: list[str] = Field(default_factory=list)
