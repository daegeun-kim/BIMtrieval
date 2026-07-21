"""Schema-enforced contracts for the two Task 24 LLM calls.

Exactly two model-facing schemas remain, one per principal call (§10.1):

- `BindingPlan` — LLM call 1 selects candidate IDs the backend computed against
  the active model. It cannot emit an IFC class, field name, JSON path, SQL
  fragment, or graph seed, which is what makes the binding checkable.
- `GroundedAnswer` — LLM call 2 expresses already-adjudicated answer parts, and
  every structured claim cites a `fact_id` the backend supplied.

Design constraints that keep these safe for OpenAI structured outputs:

- **Non-recursive.** Strict structured outputs do not reliably support recursive
  JSON schemas, so Boolean structure is a flat adjacency list (`bool_group`)
  rather than a nested tree. The backend expands it into the bounded
  `FilterGroup` tree in `query.sql.schemas` during compilation.
- **No raw SQL, no identifiers.** Both schemas carry only IDs, enum values, and
  the user's own wording.

Semantic validation that needs the database is deliberately NOT done as pydantic
validators — it lives in `query.binding.validate`, so an invalid binding
produces a typed clarification rather than raising inside the SDK's parse step,
and never a repair call (§3.3).

The Task 04/16/17 planner contracts (`QueryPlan`, `RetrievalPolicyPlan`,
`Facet`, and their subplans) were removed with the orchestration they served.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.query.sql.schemas import FieldKind, Operator, SqlOperation

__all__ = [
    "FieldKind",
    "Operator",
    "SqlOperation",
    "ViewerIntent",
    "OutputOperation",
    "ScopeKind",
    "BoundOperator",
    "BoundCondition",
    "AnswerPart",
    "BindingPlan",
    "FactualClaim",
    "GroundedAnswer",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewerIntent(str, Enum):
    """Desired viewer behavior; the frontend owns colors and camera."""

    NO_OP = "no_op"
    SELECT_AND_FIT = "select_and_fit"
    SELECT_ONLY = "select_only"
    CLEAR_SELECTION = "clear_selection"
    AWAIT_USER_CONFIRMATION = "await_user_confirmation"


# ---------------------------------------------------------------------------
# Task 24: the model-aware semantic binding contract (LLM call 1)
# ---------------------------------------------------------------------------
#
# This REPLACES the broad facet/evidence-group planning contract above with one
# compact typed binding plan (Task 24 §2.2). The essential difference: the model
# no longer describes concepts in prose for the backend to resolve afterwards —
# it SELECTS from candidate IDs the backend already computed against the active
# model. It may not emit IFC classes, field names, JSON paths, SQL, graph seeds,
# or new candidate definitions.
#
# There are deliberately no hypotheses, investigation lists, dependencies,
# planner-authored DAGs, exploratory branches, correction plans, or alternate
# plans to execute and compare (§2.3). One binding per requested answer part.


class OutputOperation(str, Enum):
    """What the user wants DONE with the bound subject (§2.2).

    Retrieval mode is DERIVED from this by the backend, never chosen by the
    model (§5.1) — there are no sql/rag/graph flags in this contract.
    """

    COUNT = "count"
    EXISTENCE = "existence"
    LIST = "list"
    SAMPLE_DETAIL = "sample_detail"
    GROUP_DISTRIBUTION = "group_distribution"
    AGGREGATE = "aggregate"
    EXTREMUM = "extremum"
    DESCRIPTION = "description"
    COMPARISON = "comparison"
    RELATIONSHIP = "relationship"


class ScopeKind(str, Enum):
    """Where the answer part looks. A SCOPE selects; it never narrows (§1.3)."""

    ACTIVE_MODEL = "active_model"
    SELECTED_OBJECTS = "selected_objects"
    PREVIOUS_RESULT = "previous_result"
    SPATIAL_CANDIDATE = "spatial_candidate"


class BoundOperator(str, Enum):
    """Conceptual comparison. Mapped to an allowlisted SQL operator only after
    the field's data type is known, so the model never picks a database
    operator."""

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


class BoundCondition(_StrictModel):
    """One narrowing condition, tied to a slate candidate and to the question.

    Provenance is mandatory (§2.4): every executed narrowing condition must be
    traceable to an exact span in the current question, the viewer selection, or
    a typed predicate inherited from the previous accepted result. A condition
    carrying neither `source_span` nor `inherited_from_scope` is INVENTED and is
    rejected deterministically — never repaired by asking the model again.
    """

    condition_id: str = Field(min_length=1, max_length=40)
    #: A field / spatial / material / classification candidate ID from the slate.
    candidate_id: str = Field(min_length=1, max_length=40)
    operator: BoundOperator = BoundOperator.EQUALS
    value_text: str | None = Field(default=None, max_length=500)
    value_list: list[str] = Field(default_factory=list, max_length=50)
    unit: str | None = Field(default=None, max_length=16)
    negated: bool = False
    #: Boolean group position. Conditions sharing a group id combine with that
    #: group's operator; conditions with no group combine with the part's
    #: `condition_bool_op`. Flat by design — OpenAI strict structured outputs do
    #: not reliably support recursive schemas.
    bool_group: str | None = Field(default=None, max_length=40)
    #: The EXACT substring of the current question this condition came from.
    source_span: str | None = Field(default=None, max_length=300)
    #: True when the condition is inherited from the previous accepted result's
    #: typed scope rather than from the current question's wording.
    inherited_from_scope: bool = False


class AnswerPart(_StrictModel):
    """One independent request inside the question (§2.2)."""

    part_id: str = Field(min_length=1, max_length=40)
    #: The portion of the user's question this part answers, quoted or closely
    #: paraphrased, so the final answer can address each part explicitly.
    request_text: str = Field(min_length=1, max_length=300)
    operation: OutputOperation
    #: Exactly one primary subject candidate ID.
    subject_candidate_id: str = Field(min_length=1, max_length=40)
    #: A bounded explicit union, used ONLY when the user asks for multiple peer
    #: concepts. Never used to add components, type definitions, or supporting
    #: elements to a requested occurrence total (§3.1).
    union_subject_candidate_ids: list[str] = Field(default_factory=list, max_length=4)
    scope_kind: ScopeKind = ScopeKind.ACTIVE_MODEL
    #: Required when `scope_kind` is `spatial_candidate`.
    scope_candidate_id: str | None = Field(default=None, max_length=40)
    conditions: list[BoundCondition] = Field(default_factory=list, max_length=20)
    condition_bool_op: Literal["and", "or"] = "and"
    #: Field candidate IDs whose values the answer should report.
    output_field_candidate_ids: list[str] = Field(default_factory=list, max_length=8)
    #: Free text for genuinely QUALITATIVE ranking only. Structured questions
    #: must not use this — it is the one place semantics stay unadjudicated.
    semantic_ranking_text: str | None = Field(default=None, max_length=300)
    #: Only for relationship/connectivity operations.
    relationship_candidate_id: str | None = Field(default=None, max_length=40)
    endpoint_subject_candidate_id: str | None = Field(default=None, max_length=40)
    #: Multi-part questions need ONE explicit primary visual part; the viewer
    #: must not union every part merely because each was retrieved (§9).
    is_primary_visual: bool = False


class BindingPlan(_StrictModel):
    """LLM call 1 output: the complete model-aware semantic binding (§2.2)."""

    #: The language to answer in, so responses stay in the user's language.
    response_language: str = Field(default="en", max_length=32)
    #: One to four answer parts, matching the actual independent requests.
    answer_parts: list[AnswerPart] = Field(default_factory=list, max_length=4)
    viewer_intent: ViewerIntent = ViewerIntent.NO_OP
    #: Set ONLY when a material ambiguity cannot be safely bound (§2.2).
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)
    #: Detected material modifiers the model could not bind. Declaring one here
    #: is REQUIRED rather than optional: §2.4 forbids silently dropping a
    #: modifier so a broader query can execute.
    unresolved_modifiers: list[str] = Field(default_factory=list, max_length=12)


class FactualClaim(_StrictModel):
    """One checkable numeric/named assertion the answer makes (§8.3).

    Every structured claim must reference a `fact_id` the backend supplied, and
    the value must match what the backend computed. Deterministic validation
    compares them; a mismatch is rejected without another model call.
    """

    fact_id: str = Field(min_length=1, max_length=80)
    #: The value as asserted in the answer text. Compared against the packet.
    value: str = Field(max_length=120)
    unit: str | None = Field(default=None, max_length=16)
    #: Any IFC class, property, material, or relationship endpoint named in this
    #: claim. Each must appear in the answer packet (§8.3).
    named_entities: list[str] = Field(default_factory=list, max_length=12)


class GroundedAnswer(_StrictModel):
    """LLM call 2 output: the final answer plus what it is grounded in (§8.3)."""

    answer: str = Field(min_length=1)
    #: The answer parts this response actually used.
    answer_part_ids: list[str] = Field(default_factory=list, max_length=8)
    structured_claims: list[FactualClaim] = Field(default_factory=list, max_length=16)
    #: True when the answer draws on general knowledge rather than the model.
    used_general_knowledge: bool = False
    used_inference: bool = False
    #: True when the answer discloses a material limitation it was given.
    disclosed_limitation: bool = False
