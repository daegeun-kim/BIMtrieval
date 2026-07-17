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


@dataclass(frozen=True)
class GroupPredicate:
    """A safe, typed, reproducible predicate (Task 17 §3). Maps to an allowlisted
    typed SQL operation — never raw SQL, a JSON path, or an LLM expression."""

    kind: str  # PredicateKind value
    ifc_classes: tuple[str, ...] = ()
    field_kind: str | None = None  # attribute | property | type_fact
    set_name: str | None = None
    field_name: str | None = None
    operator: str | None = None  # contains | case_insensitive_exact | exact
    value: str | None = None
    entity_ids: tuple[int, ...] = ()  # entity_id_set (RAG candidates)
    relationship_ids: tuple[int, ...] = ()  # relationship

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
        )


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
