"""Evidence-group data contract (Task 17 §3).

An `EvidenceGroup` is one independently-selectable semantic claim with a stable
id, a typed SAFE predicate (never raw SQL or a JSON path), authority + coverage,
a deterministic factual profile, and bounded representative evidence. Groups are
never flattened into one mixed entity collection, and a group never bundles
semantically distinct classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.api.schemas.response import (
    ContextEntityResult,
    PrimaryEntityResult,
    RelationshipResult,
)

# Authority / coverage vocab reused from Task 16 (§3).
from app.query.hybrid.schemas import (  # noqa: F401 (re-exported for callers)
    AUTHORITIES,
    AUTHORITY_EXACT,
    AUTHORITY_GENERAL,
    AUTHORITY_SEMANTIC,
    AUTHORITY_STRUCTURED,
    COVERAGE_BOUNDED,
    COVERAGE_COMPLETE,
    COVERAGE_FAILED,
    COVERAGE_UNAVAILABLE,
    COVERAGE_UNKNOWN,
    COVERAGES,
)


class PredicateKind(str, Enum):
    ENTITY_CLASS = "entity_class"
    ATTRIBUTE_VALUE = "attribute_value"
    PROPERTY_VALUE = "property_value"
    TYPE_VALUE = "type_value"
    ENTITY_ID_SET = "entity_id_set"
    RELATIONSHIP = "relationship"
    # A result class AND every material condition the user expressed about it,
    # executed as ONE authoritative compound result (Task 23 §1).
    COMPOUND = "compound"


@dataclass(frozen=True)
class PredicateCondition:
    """One resolved leaf condition. Hashable so a compound predicate keeps a
    stable dedup signature; `value` is a tuple for list operators."""

    field_kind: str  # attribute | property | type_fact | quantity | dimension
    field_name: str
    operator: str
    value: str | tuple[str, ...]
    set_name: str | None = None
    unit: str | None = None
    negated: bool = False
    # Provenance for the user-facing interpretation report (Task 23 §1). Never
    # used for execution and never sent to the planner.
    concept: str | None = None
    interpretation: str | None = None

    def signature(self) -> tuple:
        value = (
            tuple(sorted(v.lower() for v in self.value))
            if isinstance(self.value, tuple)
            else (self.value or "").lower()
        )
        return (
            "cond",
            self.field_kind,
            self.set_name,
            self.field_name,
            self.operator,
            value,
            self.unit,
            self.negated,
        )


@dataclass(frozen=True)
class PredicateGroup:
    """A bounded Boolean group of conditions/subgroups, mirroring the typed SQL
    `FilterGroup` it compiles to (max depth 3) so no parallel compiler exists."""

    bool_op: str  # "and" | "or"
    conditions: tuple["PredicateCondition | PredicateGroup", ...] = ()

    def signature(self) -> tuple:
        return ("group", self.bool_op, tuple(c.signature() for c in self.conditions))

    def leaves(self) -> list[PredicateCondition]:
        out: list[PredicateCondition] = []
        for c in self.conditions:
            if isinstance(c, PredicateGroup):
                out.extend(c.leaves())
            else:
                out.append(c)
        return out


@dataclass(frozen=True)
class GroupPredicate:
    """A safe, typed, reproducible predicate (Task 17 §3). Maps to an allowlisted
    typed SQL operation — never raw SQL, a JSON path, or an LLM expression.

    A `compound` predicate additionally carries `filters`: the full Boolean
    condition tree the user expressed about `ifc_classes`. Class and conditions
    are executed together as one authoritative result set, so a filtered question
    can never be answered by the unfiltered class total (Task 23 §1)."""

    kind: str  # PredicateKind value
    ifc_classes: tuple[str, ...] = ()
    field_kind: str | None = None  # attribute | property | type_fact
    set_name: str | None = None
    field_name: str | None = None
    operator: str | None = None  # contains | case_insensitive_exact | exact
    value: str | None = None
    entity_ids: tuple[int, ...] = ()  # entity_id_set (RAG candidates)
    relationship_ids: tuple[int, ...] = ()  # relationship
    filters: PredicateGroup | None = None  # compound only

    def signature(self) -> tuple:
        """Canonical dedup key: two predicates with the same signature describe
        the same set of objects (Task 17 §4)."""
        return (
            self.kind,
            self.ifc_classes,
            self.field_kind,
            self.set_name,
            self.field_name,
            self.operator,
            (self.value or "").lower() if self.value else None,
            self.entity_ids,
            self.relationship_ids,
            self.filters.signature() if self.filters is not None else None,
        )

    @property
    def queryable(self) -> bool:
        """True when the predicate can be executed against structured data for an
        exact count + complete identities."""
        return self.kind in (
            PredicateKind.ENTITY_CLASS.value,
            PredicateKind.ATTRIBUTE_VALUE.value,
            PredicateKind.PROPERTY_VALUE.value,
            PredicateKind.TYPE_VALUE.value,
            PredicateKind.ENTITY_ID_SET.value,
            PredicateKind.COMPOUND.value,
        )

    @property
    def is_constrained(self) -> bool:
        """True when this predicate carries at least one user condition beyond the
        result class — i.e. answering it with a bare class total would drop a
        constraint (Task 23 §1)."""
        return self.filters is not None and bool(self.filters.leaves())


@dataclass
class EvidenceGroup:
    group_id: str
    facet_id: str
    label: str
    predicate: GroupPredicate
    role_hint: str
    authority: str
    coverage: str
    source_kinds: list[str] = field(default_factory=list)
    predicate_queryable: bool = False
    exact_count: int | None = None
    rag_candidate_count: int | None = None
    ontology_definition: str | None = None
    factual_profile: dict = field(default_factory=dict)
    representative_entities: list[PrimaryEntityResult] = field(default_factory=list)
    context_entities: list[ContextEntityResult] = field(default_factory=list)
    relationship_evidence: list[RelationshipResult] = field(default_factory=list)
    all_viewer_identities_available: bool = False
    warnings: list[str] = field(default_factory=list)
    # Human-readable record of how each conceptual condition was resolved against
    # this model (e.g. which storeys a floor band covers). Surfaced to the user so
    # the interpretation is auditable and correctable (Task 23 §1).
    interpretation_notes: list[str] = field(default_factory=list)
    # A required condition that could not be resolved/compiled. A group carrying
    # these is NEVER accepted as exact evidence — the constraint must not be
    # silently dropped so a broader query can run (Task 23 §1).
    unresolved_conditions: list[str] = field(default_factory=list)

    # --- internal (never sent verbatim to the LLM) ---
    similarity: float = 0.0  # best facet similarity, for ranking only
    facet_ids: list[str] = field(default_factory=list)
    # RAG candidate entity ids (entity_id_set groups) or ranked ids for ordering.
    candidate_entity_ids: list[int] = field(default_factory=list)
    # Detailed examples allocated to this group (Task 17 §7); filled by the allocator.
    allocated_examples: list[PrimaryEntityResult] = field(default_factory=list)
    allocation_truncated: bool = False

    def count_for_display(self) -> int | None:
        """Exact count for exact/structured groups; bounded candidate count for
        RAG-only groups (never presented as an exact total)."""
        if self.exact_count is not None:
            return self.exact_count
        return None
