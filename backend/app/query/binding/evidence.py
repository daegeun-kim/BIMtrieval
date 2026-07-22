"""Evidence status and the per-answer-part result contract (Task 24 §6).

Every answer part finishes in exactly one of five states. The distinctions are
the whole point — conflating them is how a pipeline tells a user something false
while sounding confident:

    exact        the requested representation was queried with complete
                 structured coverage. The result MAY be nonzero.
    zero         the representation was safely identified and completely
                 queried, and nothing matched.
    unavailable  the required property/quantity/relationship/representation
                 cannot be established from the model at all.
    partial      one requested part is exact or directly supported while
                 another is unavailable or incomplete.
    ambiguous    materially different bindings remain; the user must choose.

The rules this module enforces (§6):

- **zero is not unavailable.** "This model contains no escalators" is a fact
  about the model; "this model does not record thermal properties" is a gap in
  what can be asked. Reporting either as the other misleads.
- **missing field coverage is not a zero value.** A field populated on none of
  the matching objects yields UNAVAILABLE, not a count of 0.
- **a bounded RAG miss is not proof of absence**, and RAG candidate counts are
  never exact totals.
- **failed graph execution is not evidence of no real-world connection.**
- **partial evidence must identify the known and unknown parts separately.**
- **no unavailable condition may be silently removed to produce a broader exact
  result** — an unresolved condition forces unavailable/partial, never a
  quietly-widened `exact`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ResultStatus",
    "RetrievalMode",
    "ResultExample",
    "DistributionBucket",
    "AggregateValue",
    "AnswerPartResult",
    "classify_structured_result",
]


class ResultStatus(str, Enum):
    EXACT = "exact"
    ZERO = "zero"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"


class RetrievalMode(str, Enum):
    """What actually executed. DERIVED from the bound operation (§5.1), never
    chosen by the model."""

    SQL = "sql"
    SCOPED_RAG = "scoped_rag"
    GRAPH = "graph"
    CATALOG = "catalog"
    BUILDING_PROFILE = "building_profile"
    NONE = "none"


@dataclass(frozen=True)
class ResultExample:
    """One representative object. Identity is carried for the viewer channel;
    the answer packet sends only a bounded few (§8.2)."""

    entity_id: int
    global_id: str
    ifc_class: str
    name: str | None = None
    storey_name: str | None = None


@dataclass(frozen=True)
class DistributionBucket:
    key: str | None
    count: int
    value: float | None = None


@dataclass(frozen=True)
class AggregateValue:
    function: str
    value: float | None
    unit: str | None
    #: How many of the matching objects actually carried a usable value. When
    #: this is below `matched_count` the aggregate does NOT imply completeness.
    coverage_count: int
    matched_count: int

    @property
    def complete(self) -> bool:
        return self.coverage_count == self.matched_count


@dataclass
class AnswerPartResult:
    """The adjudicated result of ONE answer part.

    This is what the answer packet is built from (§8.2) and what the viewer
    identities are derived from (§9) — one object, one truth.
    """

    part_id: str
    request_text: str
    operation: str
    status: ResultStatus
    #: The selected interpretation in plain language, so the user can see — and
    #: correct — how the question was read.
    interpretation: str = ""
    modes_executed: tuple[RetrievalMode, ...] = ()

    exact_total: int | None = None
    aggregate: AggregateValue | None = None
    distribution: list[DistributionBucket] = field(default_factory=list)
    class_breakdown: dict[str, int] = field(default_factory=dict)
    examples: list[ResultExample] = field(default_factory=list)

    #: Bounded semantic evidence. NEVER an exact total (§5.3).
    rag_candidate_count: int | None = None
    #: Bounded relationship endpoints for a graph answer.
    graph_endpoints: list[ResultExample] = field(default_factory=list)
    graph_path_count: int | None = None

    #: One concise reason for a zero/unavailable/partial/ambiguous result.
    limitation: str | None = None
    #: The known/unknown split for a PARTIAL result (§6).
    known_parts: list[str] = field(default_factory=list)
    unknown_parts: list[str] = field(default_factory=list)

    #: Diagnostics (§10.3, §10.5).
    statement_count: int = 0
    duration_ms: float = 0.0
    #: Retained internally for viewer hydration; never sent to the answer LLM.
    predicate: Any = None

    @property
    def is_answerable(self) -> bool:
        return self.status in (ResultStatus.EXACT, ResultStatus.ZERO, ResultStatus.PARTIAL)

    @property
    def has_visual_result(self) -> bool:
        """Whether this part should drive viewer highlighting (§9).

        Exact zero, unavailable, and ambiguous results highlight nothing — they
        must not fall back to an unrelated set.
        """
        return self.status in (ResultStatus.EXACT, ResultStatus.PARTIAL) and bool(self.exact_total)

    def summary(self) -> str:
        """A short, safe restatement usable in a fallback answer (§8.3)."""
        if self.status is ResultStatus.EXACT and self.exact_total is not None:
            return f"{self.request_text}: {self.exact_total}"
        if self.status is ResultStatus.ZERO:
            return f"{self.request_text}: none found in this model"
        if self.status is ResultStatus.UNAVAILABLE:
            return f"{self.request_text}: cannot be determined from this model"
        if self.status is ResultStatus.AMBIGUOUS:
            return f"{self.request_text}: needs clarification"
        known = "; ".join(self.known_parts) or "partially answered"
        return f"{self.request_text}: {known}"


def classify_structured_result(
    *,
    matched_count: int,
    predicate_executable: bool,
    unresolved_reasons: list[str],
    subject_absent: bool,
    field_coverage_absent: bool = False,
) -> tuple[ResultStatus, str | None]:
    """Decide the §6 status of a structured result, and why.

    The ordering of these checks IS the contract:

    1. An unresolved condition wins over everything. Answering without it would
       describe a different set of objects, so the result is unavailable — never
       a quietly-broadened `exact` (§2.4, §6 final rule).
    2. A field the model does not populate is unavailable, NOT a zero count
       (§6 "missing field coverage is not a zero value").
    3. A correctly-identified concept the model simply does not contain is a
       genuine ZERO (§6 "zero is not unavailable"). This is the state that lets
       "this model contains no escalators" be answered honestly instead of being
       substituted with a similar present class.
    4. Otherwise the count is exact — including when it is 0, which by this
       point means "queried completely, nothing matched".
    """
    if unresolved_reasons:
        return ResultStatus.UNAVAILABLE, unresolved_reasons[0]
    if not predicate_executable and not subject_absent:
        return (
            ResultStatus.UNAVAILABLE,
            "the requested representation could not be established from this model",
        )
    if field_coverage_absent:
        return (
            ResultStatus.UNAVAILABLE,
            "this model records no values for the requested field, so it cannot be "
            "counted or compared",
        )
    if subject_absent:
        return (
            ResultStatus.ZERO,
            "this model contains no objects of the requested kind; this describes the "
            "model, not necessarily the real building",
        )
    if matched_count == 0:
        return ResultStatus.ZERO, "the model was queried completely and nothing matched"
    return ResultStatus.EXACT, None
