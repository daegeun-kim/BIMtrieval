"""Typed resolved intent — the v5 semantic planning boundary (task28 §2, task30 §2).

The first planning call turns the COMPLETE conversation into one compact,
model-neutral description of what the user currently means. It is deliberately
about user meaning only: it names no semantic ID, no field, no IFC class, no
SQL, and no backend capability, because the resolver is never shown the
manifest.

What it produces becomes the authoritative interpretation for every stage after
it. Downstream stages read this object instead of re-reading the transcript, so
a topic, target, constraint, operation, requested output, or visualization
request that survives here cannot be silently reinterpreted later.

**Task 30 makes the contract typed rather than prose.** The v5 original carried
an operation plus natural-language strings, and `build_ledger_from_intent` then
used the same text as the record of the requirement, the retrieval key, and the
subject of lexical coverage validation. One string cannot do three jobs: role
and Boolean structure the resolver already knew were re-derived downstream by
span detection and token matching, and were frequently re-derived wrongly.

Here every material decision carries its own type: targets know whether they are
independent or coordinated, constraints carry their operator, value, unit,
negation and Boolean group, relationships carry endpoints and direction, and
grouping, ordering, limits, evidence kind, visualisation and partial policy are
first-class. Natural-language text remains, but only ever as a RETRIEVAL HINT and
for provenance — it never decides a role the resolver already established.

Non-recursive and small by construction, like the logical plan schema: OpenAI
strict structured outputs cannot express recursion, and a compact typed object
is what makes deterministic obligation transfer possible at all.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "IntentOperation",
    "ConstraintKind",
    "ConstraintOperator",
    "TargetCoordination",
    "RelationshipDirection",
    "EvidenceKind",
    "PartialPolicy",
    "OrderDirection",
    "OrderBasis",
    "VisualizationIntent",
    "UnresolvedKind",
    "IntentTarget",
    "IntentPart",
    "IntentConstraint",
    "IntentRelationship",
    "IntentGrouping",
    "IntentOrdering",
    "IntentOutput",
    "UnresolvedSlot",
    "IntentProvenance",
    "ResolvedIntent",
]

_TEXT = {"min_length": 1, "max_length": 300}
_HANDLE = {"min_length": 1, "max_length": 24}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentOperation(str, Enum):
    """What the user wants done with the subject — meaning, not result shape."""

    COUNT = "count"
    LIST = "list"
    EXISTENCE = "existence"
    VALUE_REPORT = "value_report"
    DISTRIBUTION = "distribution"
    COMPARISON = "comparison"
    EXTREMUM = "extremum"
    SAMPLE = "sample"
    DESCRIPTION = "description"
    CONNECTION = "connection"
    CATALOG = "catalog"


class ConstraintKind(str, Enum):
    """How a constraint restricts or situates the subject."""

    #: A recorded characteristic of the subject itself.
    ATTRIBUTE = "attribute"
    #: A numeric or ordered bound on a characteristic.
    COMPARISON = "comparison"
    #: Where in the building the subject must be.
    SPATIAL = "spatial"
    #: The set produced by an earlier turn of this conversation.
    PREVIOUS_RESULT = "previous_result"
    #: The objects currently selected in the viewer.
    SELECTION = "selection"


class ConstraintOperator(str, Enum):
    """How a constraint compares. Typed here so no later stage re-derives it.

    `IS_PRESENT` is the honest default for a condition that names a
    characteristic without naming a value ("fire rated", "load bearing"): the
    user requires the characteristic to be recorded, not to equal anything.
    """

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


class TargetCoordination(str, Enum):
    """Whether a subject stands alone or is combined with its peers.

    This is the distinction between several figures and one combined figure, and
    the resolver is the only stage that can see it in the user's phrasing.
    """

    #: The only subject of its part.
    SOLE = "sole"
    #: Combined with the other members of its part into ONE figure.
    UNION_MEMBER = "union_member"


class RelationshipDirection(str, Enum):
    """Which way a required connection runs, relative to the part's subject."""

    FROM_TARGET = "from_target"
    TO_TARGET = "to_target"
    EITHER = "either"


class EvidenceKind(str, Enum):
    """What kind of evidence can answer the part at all."""

    #: Countable, filterable structured facts.
    EXACT = "exact"
    #: Descriptive text about a structured set.
    QUALITATIVE = "qualitative"
    #: Recorded connections between things.
    RELATIONSHIP = "relationship"
    #: Structured facts plus description together.
    MIXED = "mixed"


class PartialPolicy(str, Enum):
    """What the user would accept if part of the request cannot be served."""

    #: A supported result plus an honest statement of what is missing is useful.
    ALLOW_PARTIAL = "allow_partial"
    #: Anything less than the whole request would mislead.
    REQUIRE_COMPLETE = "require_complete"


class OrderDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class OrderBasis(str, Enum):
    AGGREGATE = "aggregate"
    VALUE = "value"


class VisualizationIntent(str, Enum):
    ALL_RESULTS = "all_results"
    PRIMARY_ONLY = "primary_only"
    NONE = "none"


class UnresolvedKind(str, Enum):
    TARGET = "target"
    CONSTRAINT = "constraint"
    OPERATION = "operation"
    OUTPUT = "output"
    SCOPE = "scope"


class IntentTarget(_StrictModel):
    """One subject the user asked about."""

    target_id: str = Field(**_HANDLE)
    part_id: str = Field(**_HANDLE)
    #: The user's own words for this subject. A RETRIEVAL HINT, never a role.
    text: str = Field(**_TEXT)
    coordination: TargetCoordination = TargetCoordination.SOLE


class IntentPart(_StrictModel):
    """One independently answerable request inside the current message."""

    part_id: str = Field(**_HANDLE)
    #: This part alone, phrased as a standalone request in the user's language.
    request_text: str = Field(**_TEXT)
    operation: IntentOperation
    evidence_kind: EvidenceKind = EvidenceKind.EXACT
    #: Set only when the user fixed one ("one example", "the top three").
    limit: int | None = Field(default=None, ge=1, le=500)
    #: Whether the user would expect these objects shown in the 3D viewer.
    highlightable: bool = False
    partial_policy: PartialPolicy = PartialPolicy.ALLOW_PARTIAL


class IntentConstraint(_StrictModel):
    """One condition on a part's subject, with its comparison typed."""

    constraint_id: str = Field(**_HANDLE)
    part_id: str = Field(**_HANDLE)
    #: The user's own words for this condition. A retrieval hint, never a role.
    text: str = Field(**_TEXT)
    kind: ConstraintKind
    #: Which subject it restricts; omitted when the part has one subject.
    applies_to_target_id: str | None = Field(default=None, max_length=24)
    operator: ConstraintOperator = ConstraintOperator.IS_PRESENT
    #: The value the user named, when they named one.
    value_text: str | None = Field(default=None, max_length=200)
    #: The alternatives, for a one-of comparison, or the two bounds of a range.
    value_list: list[str] = Field(default_factory=list, max_length=20)
    unit: str | None = Field(default=None, max_length=16)
    negated: bool = False
    #: Constraints sharing a group are alternatives; groups combine as "and".
    or_group: str | None = Field(default=None, max_length=24)


class IntentRelationship(_StrictModel):
    """A required connection between the subject and another kind of thing."""

    relationship_id: str = Field(**_HANDLE)
    part_id: str = Field(**_HANDLE)
    #: The user's own words for the connection.
    text: str = Field(**_TEXT)
    #: The user's words for the near end; omitted when it is the part's subject.
    from_text: str | None = Field(default=None, max_length=300)
    #: The user's words for the far end of the connection.
    to_text: str = Field(**_TEXT)
    direction: RelationshipDirection = RelationshipDirection.FROM_TARGET
    #: False when the connection enriches the answer rather than restricting it.
    restricts: bool = True


class IntentGrouping(_StrictModel):
    """The axis the user wants results broken down by."""

    grouping_id: str = Field(**_HANDLE)
    part_id: str = Field(**_HANDLE)
    #: The user's own words for the axis. A retrieval hint, never a role.
    axis_text: str = Field(**_TEXT)


class IntentOrdering(_StrictModel):
    """How the user wants results ranked."""

    ordering_id: str = Field(**_HANDLE)
    part_id: str = Field(**_HANDLE)
    direction: OrderDirection = OrderDirection.DESC
    basis: OrderBasis = OrderBasis.AGGREGATE


class IntentOutput(_StrictModel):
    """One characteristic the user asked to have reported."""

    output_id: str = Field(**_HANDLE)
    part_id: str = Field(**_HANDLE)
    #: The NAME of the characteristic, in the user's words.
    text: str = Field(**_TEXT)


class UnresolvedSlot(_StrictModel):
    """One decision the conversation genuinely does not supply (§6)."""

    slot_id: str = Field(**_HANDLE)
    kind: UnresolvedKind
    part_id: str | None = Field(default=None, max_length=24)
    #: The smallest missing decision, as a question for the user.
    question: str = Field(min_length=1, max_length=400)
    #: The words in the request that are underdetermined.
    about_text: str = Field(default="", max_length=300)
    #: False when a useful supported answer can still be produced without it.
    blocking: bool = True


class IntentProvenance(_StrictModel):
    """Which conversation turn a material decision came from (§2)."""

    #: Any handle in this object — a part, target, constraint, relationship,
    #: grouping, ordering, output, or unresolved slot.
    element_id: str = Field(**_HANDLE)
    #: Index into the serialized conversation; the current message is last.
    turn_index: int = Field(ge=0)


class ResolvedIntent(_StrictModel):
    """Planning call 1 output: the authoritative interpretation (§2, task30 §2)."""

    #: The current request restated so it stands alone without the transcript.
    normalized_request: str = Field(min_length=1, max_length=1000)
    #: BCP-47-ish tag of the user's language, for the final answer.
    language: str = Field(default="en", max_length=32)
    #: The active subject of the conversation, in the user's words.
    topic: str = Field(default="", max_length=200)
    parts: list[IntentPart] = Field(default_factory=list, max_length=6)
    targets: list[IntentTarget] = Field(default_factory=list, max_length=12)
    constraints: list[IntentConstraint] = Field(default_factory=list, max_length=16)
    relationships: list[IntentRelationship] = Field(default_factory=list, max_length=6)
    groupings: list[IntentGrouping] = Field(default_factory=list, max_length=6)
    orderings: list[IntentOrdering] = Field(default_factory=list, max_length=6)
    outputs: list[IntentOutput] = Field(default_factory=list, max_length=12)
    visualization: VisualizationIntent = VisualizationIntent.NONE
    #: Earlier constraints the current message replaced or withdrew.
    superseded: list[str] = Field(default_factory=list, max_length=6)
    unresolved: list[UnresolvedSlot] = Field(default_factory=list, max_length=4)
    #: True when this message answers the clarification the previous turn asked.
    resolves_pending_clarification: bool = False
    provenance: list[IntentProvenance] = Field(default_factory=list, max_length=48)

    # -- convenience -------------------------------------------------------

    def part(self, part_id: str) -> IntentPart | None:
        return next((p for p in self.parts if p.part_id == part_id), None)

    def targets_for(self, part_id: str) -> list[IntentTarget]:
        return [t for t in self.targets if t.part_id == part_id]

    def constraints_for(self, part_id: str) -> list[IntentConstraint]:
        return [c for c in self.constraints if c.part_id == part_id]

    def relationships_for(self, part_id: str) -> list[IntentRelationship]:
        return [r for r in self.relationships if r.part_id == part_id]

    def groupings_for(self, part_id: str) -> list[IntentGrouping]:
        return [g for g in self.groupings if g.part_id == part_id]

    def orderings_for(self, part_id: str) -> list[IntentOrdering]:
        return [o for o in self.orderings if o.part_id == part_id]

    def outputs_for(self, part_id: str) -> list[IntentOutput]:
        return [o for o in self.outputs if o.part_id == part_id]

    def blocking_slots(self) -> list[UnresolvedSlot]:
        return [s for s in self.unresolved if s.blocking]

    def turn_for(self, element_id: str) -> int | None:
        for record in self.provenance:
            if record.element_id == element_id:
                return record.turn_index
        return None

    def handles(self) -> list[str]:
        """Every material handle this intent establishes, in a stable order."""
        return [
            *(p.part_id for p in self.parts),
            *(t.target_id for t in self.targets),
            *(c.constraint_id for c in self.constraints),
            *(r.relationship_id for r in self.relationships),
            *(g.grouping_id for g in self.groupings),
            *(o.ordering_id for o in self.orderings),
            *(o.output_id for o in self.outputs),
        ]
