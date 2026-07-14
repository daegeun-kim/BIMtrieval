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
from query.sql.schemas import FieldKind, Operator, SqlOperation
from shared.types import QueryRoute, QueryScope

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
