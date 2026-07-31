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
    """Which visualization the already-computed result supports (task29 §2.1).

    Derived deterministically from the authoritative operation and data — the
    frontend does not guess, and the choice cannot drift between the two.

    Task 29 narrowed the panel to three presentation families: a bounded
    scrollable table, a compact horizontal bar chart, and a grouped node-link
    diagram. A result whose operation supports none of them gets **no payload**
    at all rather than a decorative card, so the values below are the complete
    set the selector may choose.

    The Task 26 values are retained so an older client that still switches on
    them keeps parsing the contract, but `presentation.py` never emits them:
    the standalone metric, aggregate, relationship-metric and partial-split
    visuals were removed (task29 §2.1).
    """

    #: `count` / `list` over authoritative displayed identities.
    RESULT_TABLE = "result_table"
    #: A one-bucket distribution — a single bar carries no comparison.
    GROUP_TABLE = "group_table"
    #: A structured comparison whose existing values are heterogeneous.
    COMPARISON_TABLE = "comparison_table"
    #: A relationship result that does not qualify for the bounded diagram.
    RELATIONSHIP_TABLE = "relationship_table"
    #: A distribution with >= 2 buckets, or a homogeneous numeric comparison.
    BAR_CHART = "bar_chart"
    #: A relationship result with a complete, in-bounds grouped topology.
    RELATIONSHIP_GRAPH = "relationship_graph"

    # --- Task 26 values, accepted for backward compatibility, never chosen ---
    METRIC = "metric"
    TABLE = "table"
    DISTRIBUTION = "distribution"
    AGGREGATE = "aggregate"
    RELATIONSHIP = "relationship"
    PARTIAL = "partial"


class ExplanationGraphNodeRole(str, Enum):
    """Whether a presentation node is the query subject or a reached endpoint.

    The seed/subject is always its own node and is never merged into an endpoint
    group (task29 §5.2), so the two are distinguishable without the frontend
    re-deriving anything.
    """

    SEED = "seed"
    ENDPOINT = "endpoint"


class ExplanationGraphNode(BaseModel):
    """One grouped node of the relationship diagram (task29 §5.2).

    Endpoint occurrences are grouped by the exact structural key
    `IFC entity class + relationship class + endpoint role`, so entities of the
    same class participating through the same relationship structure collapse
    into one node. `entity_count` is the number of DISTINCT underlying entities
    the node represents.

    Node identity sets may **overlap**: the same physical entity appears in more
    than one node when it participates through a different relationship class,
    direction or endpoint role. They are therefore not a partition, and
    selecting one never implies the others form a disjoint remainder.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    role: ExplanationGraphNodeRole
    ifc_class: str | None = None
    relationship_class: str | None = None
    semantic_role: str | None = None
    #: The schema role name this group participates through, e.g. `RelatedElements`.
    endpoint_role: str | None = None
    entity_count: int = 0
    #: Bounded authoritative GlobalIds, for supported node selection only.
    global_ids: list[str] = Field(default_factory=list)
    #: True when `entity_count` exceeds the GlobalIds carried here, so a
    #: selection can never read as the whole group.
    global_ids_truncated: bool = False
    #: Selectable only when those GlobalIds are an authoritative subset of the
    #: original query-result highlight (task29 §5.4).
    selectable: bool = False


class ExplanationGraphEdge(BaseModel):
    """One grouped edge of the relationship diagram (task29 §5.2).

    Raw hops collapse into a single edge when they connect the same node pair
    through the same relationship class, semantic role and endpoint-role pair.
    `connection_count` is the number of DISTINCT stored connections represented.

    Direction follows the recorded IFC roles — `source` is always the relating
    side and `target` the related side — so the same stored connection
    discovered from the opposite traversal direction is the same edge, not a
    second one.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source_node_id: str
    target_node_id: str
    relationship_class: str
    semantic_role: str
    #: Always `relating_to_related`: the arrow is the IFC schema's direction.
    schema_direction: str = "relating_to_related"
    source_role: str
    target_role: str
    connection_count: int = 0
    label: str


class ExplanationGraph(BaseModel):
    """The bounded grouped topology of an accepted relationship traversal.

    Present only when the grouped graph is complete and within the exact bounds
    of task29 §5.3 (4-24 nodes, <= 40 edges, every edge authoritative). Carries
    no internal database ids, raw relationship-member rows, canonical JSON, SQL,
    predicates or unbounded paths.
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[ExplanationGraphNode] = Field(default_factory=list)
    edges: list[ExplanationGraphEdge] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    #: Plain-language description of the nodes and edges, for assistive
    #: technology. Composed from the same grouped values shown in the diagram.
    description: str = ""


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

    #: The grouped relationship topology, when the diagram qualifies (task29 §5).
    graph: ExplanationGraph | None = None
    #: Why a relationship result is shown as a table instead of the diagram, or
    #: `None` when no fallback applied. Stated in the panel's information region;
    #: it introduces no new interpretation or graph claim (task29 §5.3, §6).
    presentation_fallback_reason: str | None = None
    #: Unit for a value-based bar chart, when the existing result carries one.
    chart_unit: str | None = None

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
