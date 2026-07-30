"""Response envelope for POST /api/query (spec_v002 Section 16.2).

Every field is allowlisted (`extra="forbid"`). Canonical IDs may appear
(evidence/citation use, Section 13.3), but full canonical JSON, raw SQL,
credentials, and full prompts must never be placed on this envelope.
"""

from __future__ import annotations

from enum import Enum

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


# ---------------------------------------------------------------------------
# Task 26 — bounded presentation payload for the primary visual answer part
#
# Additive and strictly derivative: every field below is copied from structured
# information the pipeline ALREADY established for the accepted answer. Nothing
# here re-queries the database, re-interprets the question, or reaches the LLM.
# ---------------------------------------------------------------------------


class ExplanationPresentation(str, Enum):
    """Which visualization the already-computed result supports (task26 §4.1).

    Derived deterministically from the authoritative operation and status — the
    frontend does not guess, and the choice cannot drift between the two.
    """

    METRIC = "metric"
    TABLE = "table"
    DISTRIBUTION = "distribution"
    AGGREGATE = "aggregate"
    RELATIONSHIP = "relationship"
    PARTIAL = "partial"


class ExplanationGroup(BaseModel):
    """A selectable subgroup of the highlighted set, backed by real identities.

    `global_ids` is an authoritative subset of the objects the viewer already
    received — never a reconstruction. When the identity list was capped,
    `exact_count` still reports the true size of the group and `truncated` says
    so, so a selected group can never imply the shown objects are exhaustive.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    #: Exact size of this group over the FULL matching set, when the pipeline
    #: already counted it. `None` means only the shown identities are known.
    exact_count: int | None = None
    shown_count: int = 0
    truncated: bool = False
    global_ids: list[str] = Field(default_factory=list)


class ExplanationRow(BaseModel):
    """One already-retrieved example/endpoint object, for a bounded table."""

    model_config = ConfigDict(extra="forbid")

    global_id: str
    ifc_class: str
    name: str | None = None
    storey_name: str | None = None


class ExplanationBucket(BaseModel):
    """One existing distribution bucket.

    Deliberately carries NO identities: the pipeline computed these buckets as
    grouped counts, so no authoritative identity subset exists for them. They
    are displayed, never selectable (task26 §1.1).
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    count: int
    value: float | None = None


class ExplanationAggregate(BaseModel):
    """The existing aggregate value and its coverage."""

    model_config = ConfigDict(extra="forbid")

    function: str
    value: float | None = None
    unit: str | None = None
    matched_count: int = 0
    coverage_count: int = 0
    complete: bool = True


class AnswerExplanation(BaseModel):
    """Bounded, presentation-only view of the primary visual answer part.

    This describes the SAME part that produced the viewer highlight — not
    `result_summary`'s first answer part — so the panel and the 3D view can
    never describe different sets.
    """

    model_config = ConfigDict(extra="forbid")

    part_id: str
    #: The portion of the question this part answered, as the pipeline recorded it.
    request_label: str
    operation: str
    result_status: str
    presentation: ExplanationPresentation
    answer_basis: AnswerBasis
    #: How the backend read the question, in its own already-stored words.
    interpretation: str | None = None
    retrieval_modes: list[str] = Field(default_factory=list)

    exact_total: int | None = None
    class_breakdown: dict[str, int] = Field(default_factory=dict)
    distribution: list[ExplanationBucket] = Field(default_factory=list)
    aggregate: ExplanationAggregate | None = None
    relationship_endpoint_total: int | None = None

    limitation: str | None = None
    known_parts: list[str] = Field(default_factory=list)
    unknown_parts: list[str] = Field(default_factory=list)

    #: Identities actually handed to the viewer.
    shown_identity_count: int = 0
    #: The true number of matching objects, never reduced by the identity cap.
    true_result_count: int = 0
    identities_truncated: bool = False

    groups: list[ExplanationGroup] = Field(default_factory=list)
    rows: list[ExplanationRow] = Field(default_factory=list)


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
    # Bounded presentation payload for the primary VISUAL answer part (task26
    # §1.1). Additive and optional: present only when that part produced a
    # non-empty highlight, absent for clarification/no-highlight responses, and
    # ignorable by any existing client.
    answer_explanation: AnswerExplanation | None = None
    warnings: list[str] = Field(default_factory=list)
