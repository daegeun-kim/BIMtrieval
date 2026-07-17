"""Model-vocabulary profile shapes (Task 16 §3).

Three separately-searchable profile kinds so minority meanings are not hidden
inside a large class profile:

- `ClassProfile`          — one per observed entity/relationship class.
- `ObservedFactProfile`   — one per notable observed fact (name stem, property
                            value, object type, predefined type, type name,
                            material, classification, storey). Preserves exact
                            provenance and, when safe, a queryable typed field
                            reference for automatic structured verification.
- `QuantityCoverageProfile` — quantity/dimension availability per class/field.

Every profile exposes `profile_text()` (deterministic text used for BGE-M3
semantic search) and `excerpt()` (a bounded, provenance-first summary suitable
for the planner/answer LLM). No profile ever carries full canonical JSON,
GlobalIds, STEP ids, vectors, or secrets (Task 16 §3 bounds, §16 prohibited).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryableRef:
    """A safe, typed field reference for automatic structured verification
    (Task 16 §6). Maps directly onto an allowlisted SQL filter — never raw SQL.
    `field_kind`/`operator` are the string values of app.query.sql.schemas enums."""

    field_kind: str  # attribute | property | type_fact | quantity | dimension
    set_name: str | None
    field_name: str
    operator: str  # case_insensitive_exact | contains | exact
    value: str


@dataclass
class ClassProfile:
    ifc_class: str
    kind: str  # "entity" | "relationship"
    instance_count: int
    predefined_types: list[tuple[str, int]] = field(default_factory=list)
    name_stems: list[tuple[str, int]] = field(default_factory=list)
    representative_names: list[str] = field(default_factory=list)
    object_types: list[tuple[str, int]] = field(default_factory=list)
    type_names: list[tuple[str, int]] = field(default_factory=list)
    material_names: list[tuple[str, int]] = field(default_factory=list)
    classification_names: list[tuple[str, int]] = field(default_factory=list)
    storey_names: list[tuple[str, int]] = field(default_factory=list)
    property_set_names: list[str] = field(default_factory=list)
    quantity_set_names: list[str] = field(default_factory=list)
    endpoint_roles: list[tuple[str, int]] = field(default_factory=list)  # relationships only
    # From the bundled ontology when the class is recognized (advisory only).
    present_in_ontology: bool = False
    ontology_label: str | None = None
    ancestors: list[str] = field(default_factory=list)

    def profile_text(self) -> str:
        from app.query.semantic.ontology.loader import split_class_words

        words = split_class_words(self.ifc_class)
        parts = [f"{self.kind} class {self.ifc_class} ({words}).", f"count {self.instance_count}."]
        if self.ontology_label:
            parts.append(f"IFC concept: {self.ontology_label}.")
        if self.ancestors:
            parts.append("hierarchy: " + " > ".join(self.ancestors[:4]) + ".")
        if self.predefined_types:
            parts.append("predefined types: " + _join_counts(self.predefined_types) + ".")
        if self.name_stems:
            parts.append("names: " + _join_counts(self.name_stems) + ".")
        if self.object_types:
            parts.append("object types: " + _join_counts(self.object_types) + ".")
        if self.type_names:
            parts.append("types: " + _join_counts(self.type_names) + ".")
        if self.material_names:
            parts.append("materials: " + _join_counts(self.material_names) + ".")
        if self.storey_names:
            parts.append("storeys: " + _join_counts(self.storey_names) + ".")
        if self.property_set_names:
            parts.append("property sets: " + ", ".join(self.property_set_names[:12]) + ".")
        if self.quantity_set_names:
            parts.append("quantity sets: " + ", ".join(self.quantity_set_names[:12]) + ".")
        if self.endpoint_roles:
            parts.append("endpoint roles: " + _join_counts(self.endpoint_roles) + ".")
        return " ".join(parts)

    def excerpt(self, max_chars: int) -> str:
        return self.profile_text()[:max_chars]


@dataclass
class ObservedFactProfile:
    # fact_kind ∈ name_stem | property_value | property_coverage | object_type |
    #   predefined_type | type_name | type_predefined | material |
    #   classification | storey
    # source   ∈ attribute | property | type | material | classification |
    #   storey | meta
    ifc_class: str
    fact_kind: str
    source: str
    set_name: str | None
    field_name: str | None
    observed_value: str
    normalized_value: str | None
    occurrence_count: int
    queryable: QueryableRef | None = None

    def profile_text(self) -> str:
        from app.query.semantic.ontology.loader import split_class_words

        words = split_class_words(self.ifc_class)
        loc = self.field_name or self.fact_kind
        where = f"{self.set_name}.{loc}" if self.set_name else loc
        return (
            f"{self.ifc_class} ({words}) {self.fact_kind} {where} = {self.observed_value} "
            f"(count {self.occurrence_count})."
        )

    def excerpt(self, max_chars: int) -> str:
        return self.profile_text()[:max_chars]


@dataclass
class QuantityCoverageProfile:
    ifc_class: str
    set_name: str
    field_name: str
    populated_count: int
    total_count: int
    unit_available: bool

    @property
    def missing_count(self) -> int:
        return max(0, self.total_count - self.populated_count)

    def profile_text(self) -> str:
        return (
            f"{self.ifc_class} quantity {self.set_name}.{self.field_name}: "
            f"{self.populated_count} populated / {self.missing_count} missing "
            f"(unit {'available' if self.unit_available else 'unavailable'})."
        )

    def excerpt(self, max_chars: int) -> str:
        return self.profile_text()[:max_chars]


@dataclass
class ModelVocabulary:
    """The full bounded, cached vocabulary for one source model."""

    source_model_id: int
    file_fingerprint: str
    extraction_version: str
    profile_builder_version: str
    ifc_schema: str | None
    classes: list[ClassProfile] = field(default_factory=list)
    facts: list[ObservedFactProfile] = field(default_factory=list)
    quantities: list[QuantityCoverageProfile] = field(default_factory=list)

    def class_count(self, ifc_class: str) -> int:
        for c in self.classes:
            if c.ifc_class == ifc_class:
                return c.instance_count
        return 0

    def present_classes(self) -> set[str]:
        return {c.ifc_class for c in self.classes}


def _join_counts(items: list[tuple[str, int]], limit: int = 12) -> str:
    return ", ".join(f"{v} ({n})" for v, n in items[:limit])
