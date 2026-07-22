"""Unified schema-enforced planner output (spec_v005 §5).

ONE plan, produced by ONE OpenAI structured-output call, covering every route:
catalog, sql, rag, graph, hybrid, explain_general, and clarify. The planner
chooses the route *and* fills the complete executable subplans in the same
call — there is no separate route-classification request (spec_v005 §2).

Design constraints that make this safe to hand to OpenAI structured outputs
and to the backend:

- **Non-recursive.** OpenAI strict structured outputs do not reliably support
  recursive JSON schemas, and an LLM does not need arbitrarily nested boolean
  logic. Filters are a *flat* list combined by one `filter_bool_op`; that maps
  to a single depth-1 `FilterGroup` in the typed execution plan.
- **No raw SQL.** Subplans carry only semantic operation names, allowlisted
  field references, operators, and values — never table/column/WHERE text
  (spec_v005 §6, Prohibited actions).
- **Split scalar/list values.** `value_text` (scalars) and `value_list`
  (in/not_in/between) avoid a union-typed `value`, which keeps the emitted JSON
  schema simple and strict-mode friendly. The backend casts to the resolved
  field's real type during translation (`llm.translate`).

Semantic validation that needs the database (field existence, model existence,
operator/type compatibility) is intentionally NOT done here as pydantic
validators — it lives in `llm.validation` / `llm.translate` so an invalid plan
can be caught and given exactly one repair attempt (spec_v005 §6) instead of
raising inside the OpenAI SDK's parse step.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.query.sql.schemas import FieldKind, Operator, SqlOperation
from app.shared.types import QueryRoute, QueryScope

__all__ = [
    "FieldKind",
    "Operator",
    "SqlOperation",
    "ExecutionMode",
    "CombinationOp",
    "ViewerIntent",
    "PlanFieldRef",
    "PlanFilter",
    "CatalogPlan",
    "SqlPlan",
    "RagPlan",
    "GraphPlan",
    "PlanExecution",
    "QueryPlan",
    "RoleHint",
    "ConceptKind",
    "IntentOperator",
    "IntentCondition",
    "IntentGroup",
    "Facet",
    "RetrievalPolicy",
    "RetrievalPolicyPlan",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionMode(str, Enum):
    """spec_v005 §8 dependency modes, plus `single` for one-path routes."""

    SINGLE = "single"
    PARALLEL_INDEPENDENT = "parallel_independent"
    SQL_THEN_RAG = "sql_then_rag"
    RAG_THEN_SQL = "rag_then_sql"
    RAG_RELATIONSHIP_THEN_GRAPH_THEN_SQL = "rag_relationship_then_graph_then_sql"
    SQL_RELATIONSHIP_THEN_GRAPH_THEN_RAG = "sql_relationship_then_graph_then_rag"


class CombinationOp(str, Enum):
    """spec_v005 §9 canonical-ID combination semantics."""

    NONE = "none"
    INTERSECTION = "intersection"
    UNION = "union"
    SQL_FILTER_OF_RAG = "sql_filter_of_rag"
    RAG_RANK_OF_SQL = "rag_rank_of_sql"
    RELATIONSHIP_ENDPOINT_EXPANSION = "relationship_endpoint_expansion"


class ViewerIntent(str, Enum):
    """spec_v005 §14 — desired viewer behavior; frontend owns colors/camera."""

    NO_OP = "no_op"
    SELECT_AND_FIT = "select_and_fit"
    SELECT_ONLY = "select_only"
    CLEAR_SELECTION = "clear_selection"
    AWAIT_USER_CONFIRMATION = "await_user_confirmation"


class PlanFieldRef(_StrictModel):
    """An allowlisted semantic field reference (resolved later against schema)."""

    field_kind: FieldKind
    set_name: str | None = Field(default=None, max_length=200)
    field_name: str = Field(min_length=1, max_length=200)


class PlanFilter(_StrictModel):
    """One flat filter condition. Scalars go in `value_text`; list operators
    (in/not_in/between) go in `value_list`. Values are strings; the backend
    casts to the resolved field's real type (spec_v005 §6)."""

    field: PlanFieldRef
    operator: Operator
    value_text: str | None = Field(default=None, max_length=500)
    value_list: list[str] = Field(default_factory=list, max_length=50)
    unit: str | None = Field(default=None, max_length=16)


class CatalogPlan(_StrictModel):
    """Model-catalog operations (spec_v005 §7 SQL/catalog, scope=model_catalog)."""

    operation: SqlOperation
    filters: list[PlanFilter] = Field(default_factory=list, max_length=20)
    filter_bool_op: Literal["and", "or"] = "and"
    family_key: str | None = Field(default=None, max_length=200)
    entity_class: str | None = Field(default=None, max_length=200)
    target_source_model_id: int | None = None
    direction: Literal["asc", "desc"] = "desc"
    limit: int | None = Field(default=None, ge=1, le=500)


class SqlPlan(_StrictModel):
    """Deterministic active-model structured retrieval (spec_v005 §7 SQL)."""

    operation: SqlOperation
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    filters: list[PlanFilter] = Field(default_factory=list, max_length=20)
    filter_bool_op: Literal["and", "or"] = "and"
    aggregate_function: Literal["count", "sum", "min", "max", "average"] | None = None
    aggregate_field: PlanFieldRef | None = None
    group_by_field: PlanFieldRef | None = None
    target_unit: str | None = Field(default=None, max_length=16)
    entity_id: int | None = None
    global_id: str | None = Field(default=None, max_length=64)
    entity_ids: list[int] = Field(default_factory=list, max_length=50)
    relationship_id: int | None = None
    relationship_classes: list[str] = Field(default_factory=list, max_length=50)
    limit: int | None = Field(default=None, ge=1, le=500)


class RagPlan(_StrictModel):
    """Semantic retrieval (spec_v005 §7 RAG; conforms to v004 contracts)."""

    semantic_query: str = Field(min_length=1, max_length=2000)
    search_entity_documents: bool = True
    search_relationship_documents: bool = False
    top_k_per_kind: int = Field(default=30, ge=1, le=100)
    visible_limit: int = Field(default=10, ge=1, le=50)
    threshold_profile: Literal["default_v001", "high_precision_v001"] = "default_v001"
    expand_relationship_endpoints: bool = True


class GraphPlan(_StrictModel):
    """Deterministic relationship traversal (spec_v005 §7 Graph)."""

    start_entity_ids: list[int] = Field(default_factory=list, max_length=50)
    relationship_classes: list[str] = Field(default_factory=list, max_length=50)
    max_depth: int = Field(default=1, ge=0, le=3)
    direction: Literal["outgoing", "incoming", "both"] = "both"
    expand_relationship_endpoints: bool = True


class PlanExecution(_StrictModel):
    """How declared paths run and how their canonical IDs combine (spec_v005 §8, §9)."""

    mode: ExecutionMode = ExecutionMode.SINGLE
    combination: CombinationOp = CombinationOp.NONE


class RoleHint(str, Enum):
    """Query-specific PRELIMINARY relevance hint for a facet (Task 17 §5). It is a
    hypothesis, not a decision — the answerer assigns the final group role."""

    DIRECT = "direct"
    SUPPORTING = "supporting"
    CONTEXT = "context"
    UNCERTAIN = "uncertain"


class ConceptKind(str, Enum):
    """What KIND of thing a condition constrains (Task 23 §1). Still conceptual —
    the planner says "a containing building level", not `storey_name`."""

    FIELD = "field"  # a named characteristic of the result concept
    QUANTITY = "quantity"  # a measured/dimensional value
    SPATIAL_SCOPE = "spatial_scope"  # containing level / building / space
    RELATIONSHIP_SCOPE = "relationship_scope"  # constrained via a connection
    CLASSIFICATION = "classification"
    MATERIAL = "material"
    MISSING_VALUE = "missing_value"  # the characteristic is absent/unset


class IntentOperator(str, Enum):
    """Conceptual comparison. Mapped to an allowlisted SQL operator only AFTER the
    field is resolved, so the planner never picks a database operator."""

    EQUALS = "equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ONE_OF = "one_of"
    GREATER_THAN = "greater_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_THAN = "less_than"
    LESS_OR_EQUAL = "less_or_equal"
    BETWEEN = "between"
    IS_MISSING = "is_missing"
    IS_PRESENT = "is_present"


class IntentCondition(_StrictModel):
    """ONE material condition the user expressed about a facet's result concept.

    Conditions are first-class typed data — they must NEVER exist only inside
    prose fields such as `question`, `semantic_query`, or `analysis_intent`,
    because retrieval can only preserve what it can see (Task 23 §1).

    Boolean structure is expressed as a bounded adjacency list rather than a
    nested object, because OpenAI strict structured outputs do not reliably
    support recursive schemas: `parent_group_id` points at an `IntentGroup`, or
    is empty for a condition attached directly to the facet (an implicit AND).
    """

    condition_id: str = Field(min_length=1, max_length=40)
    parent_group_id: str | None = Field(default=None, max_length=40)
    concept_kind: ConceptKind = ConceptKind.FIELD
    # The characteristic being constrained, in plain language — never a final IFC
    # property name, database field, or JSON path.
    concept: str = Field(min_length=1, max_length=200)
    operator: IntentOperator = IntentOperator.EQUALS
    # The value in plain language ("the second floor", "external", "fire rated").
    value_concept: str | None = Field(default=None, max_length=200)
    value_list: list[str] = Field(default_factory=list, max_length=50)
    unit: str | None = Field(default=None, max_length=16)
    negated: bool = False
    # A required condition may NEVER be dropped to let a broader query run. When
    # it cannot be resolved the query must fail or clarify (Task 23 §1).
    required: bool = True


<<<<<<< Updated upstream
class IntentGroup(_StrictModel):
    """A Boolean grouping node for conditions that are not a simple AND."""
=======
class LedgerDispositionKind(str, Enum):
    """How a required ledger item was accounted for (task25 §3.2).

    These are NOT interchangeable. `bound_condition` means the item restricts
    which objects qualify and a predicate was compiled for it; `bound_output`
    means the item asked for something to be REPORTED and nothing was filtered.
    Using the second where the first is required is exactly the Task 24 defect.
    """

    BOUND_SUBJECT = "bound_subject"
    BOUND_CONDITION = "bound_condition"
    BOUND_SCOPE = "bound_scope"
    BOUND_OUTPUT = "bound_output"
    BOUND_RELATIONSHIP = "bound_relationship"
    #: Semantically the same request as another cited item.
    REDUNDANT_WITH = "redundant_with"
    #: Genuinely ambiguous; the request cannot be bound without clarification.
    AMBIGUOUS = "ambiguous"
    #: The model does not represent this in a queryable form.
    UNAVAILABLE = "unavailable"


class AnswerPart(_StrictModel):
    """One independent request inside the question (§2.2)."""
>>>>>>> Stashed changes

    group_id: str = Field(min_length=1, max_length=40)
    parent_group_id: str | None = Field(default=None, max_length=40)
    bool_op: Literal["and", "or"] = "and"


<<<<<<< Updated upstream
class Facet(_StrictModel):
    """One conceptual sub-question of the query (Task 17 §1 Stage 2).

    Emitted by the QUERY-ONLY policy planner: it carries a concept and its
    per-facet retrieval information needs — never a final IFC class, property, or
    raw SQL. The backend resolves the concept against the active model afterward
    (Stage 3)."""

    facet_id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=300)
    role_hint: RoleHint = RoleHint.UNCERTAIN
    semantic_query: str = Field(min_length=1, max_length=400)
    needs_exact_structured: bool = False
    needs_entity_rag: bool = False
    needs_relationship_rag: bool = False
    needs_graph: bool = False

    # --- conceptual intent tree (Task 23 §1) ---
    # The thing the user wants returned by this facet, in plain language ("doors").
    # Resolved to IFC classes later; never an IFC class here.
    result_concept: str | None = Field(default=None, max_length=200)
    # Every material condition on `result_concept`, and their Boolean structure.
    # Conditions attached to no group are combined with AND.
    conditions: list[IntentCondition] = Field(default_factory=list, max_length=20)
    condition_groups: list[IntentGroup] = Field(default_factory=list, max_length=8)


class RetrievalPolicy(_StrictModel):
    """The immutable SQL/RAG/graph modality decision (Task 17 §2). Decided from
    the query alone; the authoritative value is the union of the facets' needs."""

    sql: bool = False
    rag_entity: bool = False
    rag_relationship: bool = False
    graph: bool = False


class RetrievalPolicyPlan(_StrictModel):
    """LLM call 1 output (Task 17 Stage 2): the query-only retrieval policy and
    conceptual facet plan. For a conversational active-model question it carries
    `facets` + `retrieval_policy` (route=hybrid). Catalog/general/clarify are
    preserved routes and carry no facets. NO active-model candidates, schema
    fields, IFC classes, or raw SQL appear in the INPUT to this call."""

    scope: QueryScope
    route: QueryRoute
    source_model_id: int | None = None

    analysis_intent: str | None = Field(default=None, max_length=500)
    facets: list[Facet] = Field(default_factory=list, max_length=6)
    retrieval_policy: RetrievalPolicy = Field(default_factory=RetrievalPolicy)

    # Preserved non-analysis routes.
    catalog_plan: CatalogPlan | None = None
=======
class LedgerDisposition(_StrictModel):
    """What the binding did with one required constraint-ledger item (task25 §3.2).

    Every required item needs one of these, and the KIND matters as much as the
    presence. An item whose ledger role is `condition` is only discharged by
    `bound_condition` — reporting a same-named field as an output does not
    discharge it. That distinction is the whole reason this type exists: Task 24
    allowed an output field to account for a filter word, and answered "how many
    external walls?" with every wall in the model.
    """

    item_id: str = Field(min_length=1, max_length=40)
    disposition: LedgerDispositionKind
    #: The part that discharged it, when a part did.
    part_id: str | None = Field(default=None, max_length=40)
    #: The manifest semantic ID it was bound to, when it was bound.
    semantic_id: str | None = Field(default=None, max_length=200)
    #: Required for `redundant_with`: the other item this one duplicates.
    redundant_with_item_id: str | None = Field(default=None, max_length=40)
    #: Required for `ambiguous` and `unavailable`: why, in plain language.
    note: str | None = Field(default=None, max_length=300)


class BindingPlan(_StrictModel):
    """LLM call 1 output: the complete model-aware semantic binding (§2.2)."""

    #: The language to answer in, so responses stay in the user's language.
    response_language: str = Field(default="en", max_length=32)
    #: Up to eight independent answer parts (task25 §3.3).
    answer_parts: list[AnswerPart] = Field(default_factory=list, max_length=8)
    #: One disposition per REQUIRED ledger item. Deterministic validation
    #: rejects a binding that leaves one unaccounted for (task25 §3.2).
    ledger_dispositions: list[LedgerDisposition] = Field(default_factory=list, max_length=64)
    viewer_intent: ViewerIntent = ViewerIntent.NO_OP
    #: Set ONLY when a material ambiguity cannot be safely bound (§2.2).
>>>>>>> Stashed changes
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)

    viewer_intent: ViewerIntent = ViewerIntent.NO_OP
    answer_focus: str | None = Field(default=None, max_length=500)
    sample_detail_requested: bool = False


class QueryPlan(_StrictModel):
    """The complete planner output for one natural-language question (spec_v005 §5)."""

    scope: QueryScope
    route: QueryRoute
    source_model_id: int | None = None

    catalog_plan: CatalogPlan | None = None
    sql_plan: SqlPlan | None = None
    rag_plan: RagPlan | None = None
    graph_plan: GraphPlan | None = None

    execution: PlanExecution = Field(default_factory=PlanExecution)

    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)
    viewer_intent: ViewerIntent = ViewerIntent.NO_OP
    # A short internal note the answer model may use to focus the response.
    # Never surfaced verbatim; never authoritative (spec_v005 §11).
    answer_focus: str | None = Field(default=None, max_length=500)
    # True ONLY when the user explicitly asked for a sample/example object's
    # details ("pick a sample door and show me the details") or one specific
    # component's details (task13 §3). Ordinary count/list/show/highlight
    # questions are NOT sample-detail intent. When true, the backend picks one
    # deterministic matching entity from the database and attaches its bounded
    # details — the answer model never invents a sample.
    sample_detail_requested: bool = False
