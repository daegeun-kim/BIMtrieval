"""Typed logical query algebra for the v4 binder (task26 §8).

The binder's output is a static discriminated plan of typed nodes — target,
filter, scope, traversal, group, aggregate, order, limit, projection — with an
explicit result kind and explicit requested/context/viewer set policies. There
is deliberately NO dynamic enum of manifest IDs (that would duplicate the
manifest and destabilize the cached prompt size); IDs are plain strings
validated deterministically against the loaded manifest afterwards (§8.2).

Non-recursive by construction (OpenAI strict structured outputs), bounded to
the compiler's limits by schema, and free of SQL, JSON paths, vector limits,
and graph algorithms. Semantic IDs allow up to 120 characters — the shared
contract limit — so no valid manifest ID is rejected by a residual Task 24
40-character field (§1.4).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SEMANTIC_ID_MAX_LENGTH",
    "ResultKind",
    "ViewerSetPolicy",
    "LogicalOperator",
    "AggregateFunction",
    "ScopeKindV2",
    "TargetNode",
    "FilterNode",
    "ScopeNode",
    "TraverseNode",
    "GroupNode",
    "AggregateNode",
    "OrderNode",
    "AnswerPartV2",
    "RequirementDisposition",
    "DispositionKind",
    "LogicalPlan",
    "ClaimKind",
    "GroundedClaim",
    "GroundedAnswerV2",
]

#: One shared limit that safely accepts every manifest ID (contract id_rules).
SEMANTIC_ID_MAX_LENGTH = 120

_ID = {"min_length": 1, "max_length": SEMANTIC_ID_MAX_LENGTH}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResultKind(str, Enum):
    """What shape of result this part produces (task26 §8.2)."""

    ENTITY_SET = "entity_set"
    SCALAR = "scalar"
    DISTRIBUTION = "distribution"
    SAMPLE = "sample"
    PROFILE = "profile"
    QUALITATIVE_EVIDENCE = "qualitative_evidence"
    GRAPH_ENDPOINTS = "graph_endpoints"


class ViewerSetPolicy(str, Enum):
    """Which set, if any, the viewer highlights (§8.4)."""

    REQUESTED = "requested"
    CONTEXT = "context"
    SAMPLE = "sample"
    GRAPH_ENDPOINTS = "graph_endpoints"
    NONE = "none"


class LogicalOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ONE_OF = "one_of"
    GREATER_THAN = "greater_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_THAN = "less_than"
    LESS_OR_EQUAL = "less_or_equal"
    BETWEEN = "between"
    IS_PRESENT = "is_present"
    IS_MISSING = "is_missing"


class AggregateFunction(str, Enum):
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class ScopeKindV2(str, Enum):
    ACTIVE_MODEL = "active_model"
    SELECTED_OBJECTS = "selected_objects"
    PREVIOUS_RESULT = "previous_result"
    FLOOR_BAND = "floor_band"
    STOREY = "storey"


class TargetNode(_StrictModel):
    """The requested entity/value set (§8.3)."""

    node_id: str = Field(min_length=1, max_length=24)
    #: A class capability, derived floor, profile, or storey semantic ID.
    semantic_id: str = Field(**_ID)
    #: Bounded explicit union, ONLY when the user asked for multiple peer
    #: concepts in one set.
    union_semantic_ids: list[str] = Field(default_factory=list, max_length=4)


class FilterNode(_StrictModel):
    """One narrowing or presence predicate."""

    node_id: str = Field(min_length=1, max_length=24)
    semantic_id: str = Field(**_ID)
    operator: LogicalOperator = LogicalOperator.EQUALS
    value_text: str | None = Field(default=None, max_length=500)
    value_list: list[str] = Field(default_factory=list, max_length=50)
    unit: str | None = Field(default=None, max_length=16)
    negated: bool = False
    #: Filters sharing a group id OR together; groups AND with the rest.
    bool_group: str | None = Field(default=None, max_length=24)


class ScopeNode(_StrictModel):
    """Where the part looks. A scope SELECTS; it never invents a filter."""

    node_id: str = Field(min_length=1, max_length=24)
    kind: ScopeKindV2 = ScopeKindV2.ACTIVE_MODEL
    #: Required for floor_band / storey kinds: the band or storey semantic ID.
    semantic_id: str | None = Field(default=None, max_length=SEMANTIC_ID_MAX_LENGTH)


class TraverseNode(_StrictModel):
    """A bounded typed traversal composed of validated one-hop contracts."""

    node_id: str = Field(min_length=1, max_length=24)
    #: One to three path semantic IDs, composed in order.
    path_semantic_ids: list[str] = Field(min_length=1, max_length=3)
    #: The far-end subject class, when the question names one.
    endpoint_semantic_id: str | None = Field(default=None, max_length=SEMANTIC_ID_MAX_LENGTH)


class GroupNode(_StrictModel):
    node_id: str = Field(min_length=1, max_length=24)
    #: The grouping axis: `spatial:floor_membership`, a field capability, ...
    semantic_id: str = Field(**_ID)


class AggregateNode(_StrictModel):
    node_id: str = Field(min_length=1, max_length=24)
    function: AggregateFunction = AggregateFunction.COUNT
    #: The measured field; None for count.
    semantic_id: str | None = Field(default=None, max_length=SEMANTIC_ID_MAX_LENGTH)


class OrderNode(_StrictModel):
    node_id: str = Field(min_length=1, max_length=24)
    by: Literal["aggregate", "value"] = "aggregate"
    direction: Literal["asc", "desc"] = "desc"


class AnswerPartV2(_StrictModel):
    """One independent answer part expressed in the typed algebra (§8.2)."""

    part_id: str = Field(min_length=1, max_length=24)
    request_text: str = Field(min_length=1, max_length=300)
    result_kind: ResultKind
    target: TargetNode
    filters: list[FilterNode] = Field(default_factory=list, max_length=10)
    filter_bool_op: Literal["and", "or"] = "and"
    scope: ScopeNode | None = None
    traversals: list[TraverseNode] = Field(default_factory=list, max_length=2)
    group: GroupNode | None = None
    aggregate: AggregateNode | None = None
    order: OrderNode | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    #: Field capability IDs whose values the answer should REPORT.
    projections: list[str] = Field(default_factory=list, max_length=6)
    #: Free text for genuinely qualitative retrieval only.
    evidence_theme: str | None = Field(default=None, max_length=200)
    viewer_set: ViewerSetPolicy = ViewerSetPolicy.NONE
    #: Required when `viewer_set` or the reported result uses a CONTEXT set:
    #: why a base/contextual set is safe to show (§8.4).
    context_reason: str | None = Field(default=None, max_length=200)
    is_primary_visual: bool = False


class DispositionKind(str, Enum):
    """How one ledger requirement was accounted for (§6.4)."""

    BOUND = "bound"
    REDUNDANT_WITH = "redundant_with"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"
    TOPIC_CONTEXT = "topic_context"


class RequirementDisposition(_StrictModel):
    """The binder's account of one ledger requirement.

    `bound` requires `node_ids` naming the logical node(s) the requirement's
    concept actually contributes to — mentioning a concept discharges nothing
    (§6.4). Deterministic validation compares these against the plan.
    """

    requirement_id: str = Field(min_length=1, max_length=24)
    disposition: DispositionKind
    part_id: str | None = Field(default=None, max_length=24)
    node_ids: list[str] = Field(default_factory=list, max_length=8)
    semantic_id: str | None = Field(default=None, max_length=SEMANTIC_ID_MAX_LENGTH)
    redundant_with_requirement_id: str | None = Field(default=None, max_length=24)
    note: str | None = Field(default=None, max_length=300)


class LogicalPlan(_StrictModel):
    """LLM call 1 output: the complete typed logical plan (§8)."""

    response_language: str = Field(default="en", max_length=32)
    answer_parts: list[AnswerPartV2] = Field(default_factory=list, max_length=6)
    dispositions: list[RequirementDisposition] = Field(default_factory=list, max_length=64)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Final answer (LLM call 2) — §12.4 claim citations
# ---------------------------------------------------------------------------


class ClaimKind(str, Enum):
    FACT = "fact"
    EVIDENCE = "evidence"
    CONNECTION = "connection"
    LIMITATION = "limitation"


class GroundedClaim(_StrictModel):
    """One checkable assertion, citing the packet item that supports it."""

    kind: ClaimKind
    #: A `fact_id`, `evidence_id`, graph path/fact id, or limitation id from
    #: the answer packet — never an invented identifier.
    cited_id: str = Field(min_length=1, max_length=80)
    #: The value/text as asserted, compared against the packet.
    value: str = Field(max_length=160)
    unit: str | None = Field(default=None, max_length=16)


class GroundedAnswerV2(_StrictModel):
    """LLM call 2 output: the final answer plus its grounding (§12.4)."""

    answer: str = Field(min_length=1)
    answer_part_ids: list[str] = Field(default_factory=list, max_length=6)
    claims: list[GroundedClaim] = Field(default_factory=list, max_length=24)
    used_general_knowledge: bool = False
    disclosed_limitation: bool = False
