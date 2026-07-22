"""Typed candidate records for the model-aware slate (Task 24 §1.3).

Every candidate carries a stable, request-local ID. LLM call 1 may reference
those IDs and nothing else — never an IFC class, field name, JSON path, SQL
fragment, or graph seed (§2.2). That restriction is what makes the binding
checkable: a plan can only name things the backend put in front of it.

`to_payload()` on each record produces the compact form actually sent to the
model. Null and empty fields are omitted rather than serialized as empty
structures (§10.2), because the slate must stay far below its caps for a normal
question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.query.binding.spans import ModifierSpan

__all__ = [
    "MatchTier",
    "SubjectCandidate",
    "FieldCandidate",
    "ValueCandidate",
    "SpatialCandidate",
    "SpatialKind",
    "RelationshipCandidate",
    "CandidateSlate",
    "SlateCaps",
]


class MatchTier(str, Enum):
    """Why a candidate is in the slate (§1.2).

    Exact matches are retained BEFORE semantic supplements are capped, so a
    compound question naming several explicit BIM nouns cannot lose one because
    another ranked higher by embedding similarity.
    """

    #: Every token of the concept's name appears in the question.
    EXACT_LEXICAL = "exact_lexical"
    #: A value the model actually stores matches the question's wording.
    OBSERVED_VALUE = "observed_value"
    #: A schema-declared predefined type matches the question's wording.
    PREDEFINED_TYPE = "predefined_type"
    #: Ranked in by definition/embedding similarity.
    SEMANTIC = "semantic"
    #: Carried in from conversation state or the viewer selection.
    CONTEXT = "context"


#: Tiers that must survive capping.
_EXACT_TIERS = frozenset(
    {MatchTier.EXACT_LEXICAL, MatchTier.OBSERVED_VALUE, MatchTier.PREDEFINED_TYPE}
)


class SpatialKind(str, Enum):
    """§1.3: scope selection and spatial condition are different typed things."""

    #: The whole active model. A SCOPE selection — it narrows nothing.
    ACTIVE_MODEL = "active_model"
    #: A logical floor band from the elevation-band model (§11.4).
    FLOOR_BAND = "floor_band"
    #: A raw `IfcBuildingStorey` entity, used only when the user explicitly asks
    #: about storey entities (§1.3, §11.4).
    STOREY_ENTITY = "storey_entity"
    #: The user's current viewer selection.
    SELECTION = "selection"
    #: The previous accepted result's typed scope (§7).
    PREVIOUS_RESULT = "previous_result"


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop null/empty values so the serialized slate stays small (§10.2)."""
    return {k: v for k, v in payload.items() if v not in (None, "", [], (), {}, False)}


@dataclass(frozen=True)
class SubjectCandidate:
    """One possible requested result concept (§1.3 Subject candidates)."""

    candidate_id: str
    label: str
    ifc_class: str
    schema_role: str
    definition: str = ""
    #: Present family members in the active model (the closure).
    family_members: tuple[str, ...] = ()
    present: bool = False
    #: Cached exact count where already available — never a fresh COUNT(*) (§1.1).
    exact_count: int | None = None
    #: Whether selecting this represents one physical/logical result rather than
    #: a supporting component or definition record.
    result_kind: bool = False
    match_tier: MatchTier = MatchTier.SEMANTIC
    #: Why this candidate matched, in plain language, for diagnostics.
    match_reason: str = ""
    #: Set for a LOGICAL concept that is not an IFC class — currently only
    #: `logical_floor`, the elevation-band abstraction (§11.4). Such a subject is
    #: answered from the derived spatial model, never from an entity count, so a
    #: storey-entity total can never silently stand in for a floor count.
    logical_kind: str = ""
    #: How many content tokens of the question this candidate's name accounts
    #: for. "curtain walls" exact-matches both `IfcCurtainWall` (2 tokens) and
    #: `IfcWall` (1 token); the more specific reading must win regardless of
    #: which class happens to be more numerous.
    specificity: int = 0

    @property
    def is_exact_match(self) -> bool:
        return self.match_tier in _EXACT_TIERS

    def to_payload(self) -> dict[str, Any]:
        return _compact(
            {
                "id": self.candidate_id,
                "label": self.label,
                "ifc_class": self.ifc_class,
                "role": self.schema_role,
                "definition": self.definition,
                "family": list(self.family_members) if len(self.family_members) > 1 else None,
                "present": self.present,
                "count": self.exact_count,
                "is_result": self.result_kind,
                "logical_concept": self.logical_kind,
            }
        )


@dataclass(frozen=True)
class FieldCandidate:
    """One queryable field the question may be constraining (§1.3 Field candidates)."""

    candidate_id: str
    field_kind: str
    set_name: str | None
    field_name: str
    data_type: str
    operators: tuple[str, ...] = ()
    applicable_classes: tuple[str, ...] = ()
    populated_count: int = 0
    total_count: int = 0
    sample_values: tuple[str, ...] = ()
    unit_available: bool = False
    match_tier: MatchTier = MatchTier.SEMANTIC

    @property
    def is_exact_match(self) -> bool:
        return self.match_tier in _EXACT_TIERS

    @property
    def label(self) -> str:
        return f"{self.set_name}.{self.field_name}" if self.set_name else self.field_name

    @property
    def coverage_state(self) -> str:
        """Coverage as a typed state — never conflated with a zero value (§6)."""
        if not self.total_count:
            return "unknown"
        if self.populated_count == 0:
            return "absent"
        if self.populated_count < self.total_count:
            return "partial"
        return "complete"

    def to_payload(self) -> dict[str, Any]:
        return _compact(
            {
                "id": self.candidate_id,
                "field": self.label,
                "kind": self.field_kind,
                "type": self.data_type,
                "operators": list(self.operators),
                "applies_to": list(self.applicable_classes),
                "coverage": self.coverage_state,
                "populated": self.populated_count or None,
                "of": self.total_count or None,
                "example_values": list(self.sample_values),
                "unit_available": self.unit_available,
            }
        )


@dataclass(frozen=True)
class ValueCandidate:
    """A stored value the question's wording appears to name (§1.3)."""

    candidate_id: str
    field_candidate_id: str
    value: str
    occurrence_count: int = 0
    ifc_class: str | None = None
    match_tier: MatchTier = MatchTier.OBSERVED_VALUE

    def to_payload(self) -> dict[str, Any]:
        return _compact(
            {
                "id": self.candidate_id,
                "field": self.field_candidate_id,
                "value": self.value,
                "count": self.occurrence_count or None,
                "on": self.ifc_class,
            }
        )


@dataclass(frozen=True)
class SpatialCandidate:
    """A spatial scope or spatial condition — typed so they cannot swap (§1.3)."""

    candidate_id: str
    kind: SpatialKind
    label: str
    #: Concrete storey identities for a band/storey candidate.
    storey_global_ids: tuple[str, ...] = ()
    #: How the band was interpreted, reported to the user (Task 23 behaviour).
    interpretation: str = ""

    @property
    def is_scope_selection(self) -> bool:
        """True when this SELECTS what to look at rather than narrowing it.

        §1.3: the active model, the selection, and a previous result choose a
        scope; a floor band or storey entity is a restricting condition.
        """
        return self.kind in (
            SpatialKind.ACTIVE_MODEL,
            SpatialKind.SELECTION,
            SpatialKind.PREVIOUS_RESULT,
        )

    def to_payload(self) -> dict[str, Any]:
        return _compact(
            {
                "id": self.candidate_id,
                "kind": self.kind.value,
                "label": self.label,
                "is_scope": self.is_scope_selection,
                "storeys": len(self.storey_global_ids) or None,
            }
        )


@dataclass(frozen=True)
class RelationshipCandidate:
    """A traversable relationship (§1.3 Relationship candidates)."""

    candidate_id: str
    ifc_class: str
    meaning: str
    endpoint_roles: tuple[str, ...] = ()
    available: bool = False
    instance_count: int = 0
    directions: tuple[str, ...] = ("outgoing", "incoming", "both")
    max_depth: int = 1

    def to_payload(self) -> dict[str, Any]:
        return _compact(
            {
                "id": self.candidate_id,
                "relationship": self.ifc_class,
                "meaning": self.meaning,
                "roles": list(self.endpoint_roles),
                "available": self.available,
                "count": self.instance_count or None,
                "directions": list(self.directions),
                "max_depth": self.max_depth,
            }
        )


@dataclass(frozen=True)
class SlateCaps:
    """Maximum bounds, not quotas (§1.4).

    "Simple exact questions should usually receive one obvious subject candidate
    and only the fields actually implied by the question."
    """

    subjects: int = 8
    fields: int = 8
    values: int = 8
    spatial: int = 6
    relationships: int = 6


@dataclass
class CandidateSlate:
    """The bounded, request-specific description of how this question may be
    represented in the active model (§1.1)."""

    question: str
    source_model_id: int | None
    subjects: list[SubjectCandidate] = field(default_factory=list)
    fields: list[FieldCandidate] = field(default_factory=list)
    values: list[ValueCandidate] = field(default_factory=list)
    spatial: list[SpatialCandidate] = field(default_factory=list)
    relationships: list[RelationshipCandidate] = field(default_factory=list)
    detected_modifier_spans: list[ModifierSpan] = field(default_factory=list)
    #: Advisory shortlist pointing at likely manifest concepts (task25 §3.1).
    #: NOT a gate: the binder may select any valid manifest semantic ID, and
    #: `subjects`/`fields`/... above hold the COMPLETE universe for validation.
    recommendations: list[Any] = field(default_factory=list)
    #: Query-relevant capability notes only — never a full model manifest (§1.3).
    coverage_notes: list[str] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None

    # -- lookup -------------------------------------------------------------

    def subject(self, candidate_id: str) -> SubjectCandidate | None:
        return next((c for c in self.subjects if c.candidate_id == candidate_id), None)

    def field_candidate(self, candidate_id: str) -> FieldCandidate | None:
        return next((c for c in self.fields if c.candidate_id == candidate_id), None)

    def value(self, candidate_id: str) -> ValueCandidate | None:
        return next((c for c in self.values if c.candidate_id == candidate_id), None)

    def spatial_candidate(self, candidate_id: str) -> SpatialCandidate | None:
        return next((c for c in self.spatial if c.candidate_id == candidate_id), None)

    def relationship(self, candidate_id: str) -> RelationshipCandidate | None:
        return next((c for c in self.relationships if c.candidate_id == candidate_id), None)

    def all_candidate_ids(self) -> set[str]:
        return {
            c.candidate_id
            for group in (self.subjects, self.fields, self.values, self.spatial, self.relationships)
            for c in group
        }

    # -- serialization ------------------------------------------------------

    def to_prompt_payload(self) -> dict[str, Any]:
        """The compact form sent to LLM call 1 (§2.1).

        Carries no canonical JSON, no full vocabulary, no database rows, no
        embeddings, no retrieval results, and no viewer identities.
        """
        return _compact(
            {
                "subjects": [c.to_payload() for c in self.subjects],
                "fields": [c.to_payload() for c in self.fields],
                "values": [c.to_payload() for c in self.values],
                "spatial": [c.to_payload() for c in self.spatial],
                "relationships": [c.to_payload() for c in self.relationships],
                "detected_modifiers": [
                    {"kind": s.kind.value, "text": s.text, "material": s.material}
                    for s in self.detected_modifier_spans
                ],
                "coverage_notes": list(self.coverage_notes),
                "degraded": self.degraded,
            }
        )

    def size_report(self) -> dict[str, int]:
        """Per-type counts, for the §10.2 prompt-bound diagnostics."""
        return {
            "subjects": len(self.subjects),
            "fields": len(self.fields),
            "values": len(self.values),
            "spatial": len(self.spatial),
            "relationships": len(self.relationships),
            "modifier_spans": len(self.detected_modifier_spans),
        }
