"""Cached field-concept index for one source model (Task 24 §4.1).

Describes every queryable field of a model in terms a question can actually
reach: canonical typed reference, split identifier tokens, applicable subject
classes, data type and supported operators, coverage, and a few observed values.

The alias layer is **derived, not curated**. Splitting `IsExternal`,
`LoadBearing`, `FireRating`, `Qto_SlabBaseQuantities` into content tokens is
what lets ordinary wording reach the right field. §4.1 requires the alias
vocabulary to "describe general BIM concepts, not complete query phrases or
expected values", and tokenization satisfies that by construction: there is no
table here mapping a question to a database path, and adding one would be a
spec violation.

Two value surfaces, deliberately separate (§4.2):

- `FieldConcept.sample_values` — a few bounded values, safe to put in the
  candidate slate sent to LLM call 1. Never a global value dump (§1.3).
- `load_field_values()` — the field's COMPLETE indexed value vocabulary, read
  from the database on demand when a user value must actually be resolved.
  §4.2 forbids resolving a value against "only a globally capped set of top
  facts", and the cached vocabulary caps values per field, so authoritative
  value resolution must not use `sample_values`.

Built entirely from already-cached resources (the model vocabulary and the
schema catalog), so no per-question full canonical-JSON scan occurs (§10.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import IfcEntity
from app.query.binding.lexical import identifier_tokens, token_overlap
from app.query.semantic.vocabulary.builder import EXTRACTION_VERSION, PROFILE_BUILDER_VERSION
from app.query.semantic.vocabulary.cache import get_model_vocabulary
from app.query.semantic.vocabulary.profiles import ModelVocabulary
from app.query.sql.compiler import path_array_param
from app.query.sql.field_registry import (
    ATTRIBUTE_COLUMN_FIELDS,
    ATTRIBUTE_JSON_FIELDS,
    TYPE_FACT_JSON_FIELDS,
)

__all__ = [
    "FieldConcept",
    "FieldConceptIndex",
    "get_field_concept_index",
    "clear_field_concept_cache",
    "load_field_values",
    "FIELD_CONCEPT_BUILDER_VERSION",
]

FIELD_CONCEPT_BUILDER_VERSION = "v001"

#: Operators the typed SQL path supports per inferred data type. Values are the
#: string forms of `app.query.sql.schemas.Operator`.
_TEXT_OPERATORS = ("exact", "case_insensitive_exact", "contains", "starts_with", "in", "not_in")
_NUMERIC_OPERATORS = ("eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "not_in")
_BOOLEAN_OPERATORS = ("eq", "ne")

#: Bounded values carried in the slate. The complete vocabulary is read on
#: demand by `load_field_values`.
_MAX_SAMPLE_VALUES = 6
#: Hard cap on a single field's distinct-value read, so an accidental
#: high-cardinality field cannot pull an unbounded result into memory.
_MAX_DISTINCT_VALUES = 500

_ET = IfcEntity.__table__


@dataclass(frozen=True)
class FieldConcept:
    """One queryable field, described so a question can reach it."""

    field_kind: str  # attribute | property | quantity | type_fact
    set_name: str | None
    field_name: str
    data_type: str  # text | number | boolean
    operators: tuple[str, ...]
    #: Classes on which this field was actually observed. Empty means "applies
    #: model-wide" (the fixed attribute/type-fact fields).
    applicable_classes: tuple[str, ...] = ()
    populated_count: int = 0
    total_count: int = 0
    sample_values: tuple[str, ...] = ()
    unit_available: bool = False

    @property
    def key(self) -> tuple[str, str | None, str]:
        return (self.field_kind, self.set_name, self.field_name)

    @property
    def label(self) -> str:
        return f"{self.set_name}.{self.field_name}" if self.set_name else self.field_name

    @property
    def name_tokens(self) -> frozenset[str]:
        """Content tokens of the field name — the primary match target."""
        return identifier_tokens(self.field_name)

    @property
    def set_tokens(self) -> frozenset[str]:
        """Content tokens of the containing set name — a ranking signal only.

        Set names carry real meaning (`Pset_WallCommon`, `Qto_SlabBaseQuantities`)
        and help choose between two same-named fields on different families. But
        they must never join the primary target set: a five-token set name would
        then dilute its own two-token field below the match threshold, silently
        hiding every field in a verbosely-named set.
        """
        return identifier_tokens(self.set_name)

    @property
    def tokens(self) -> frozenset[str]:
        """All tokens associated with the field. For display/diagnostics — see
        `name_tokens`/`set_tokens` for the asymmetric matching contract."""
        return self.name_tokens | self.set_tokens

    @property
    def coverage_ratio(self) -> float:
        return self.populated_count / self.total_count if self.total_count else 0.0

    def applies_to(self, ifc_classes: frozenset[str] | set[str] | None) -> bool:
        """True when this field is usable for the given subject classes.

        A field with no recorded applicable classes is a fixed attribute that
        exists on every entity, so it always applies.
        """
        if not self.applicable_classes or not ifc_classes:
            return True
        return bool(set(self.applicable_classes) & set(ifc_classes))


@dataclass
class FieldConceptIndex:
    source_model_id: int
    file_fingerprint: str
    concepts: list[FieldConcept] = dataclass_field(default_factory=list)

    def search(
        self,
        query_tokens: frozenset[str] | set[str],
        *,
        subject_classes: frozenset[str] | set[str] | None = None,
        limit: int = 8,
        min_overlap: float = 0.5,
    ) -> list[tuple[FieldConcept, float]]:
        """Rank fields against a question's tokens (§1.2).

        Qualification is decided by overlap with the FIELD NAME alone: a field
        whose every token the question names scores 1.0, which is the "exact
        normalized lexical match" tier §1.2 requires to survive capping.

        The set name contributes only to ORDERING, so that a question naming a
        family ("external walls") prefers `Pset_WallCommon.IsExternal` over
        `Pset_WindowCommon.IsExternal` without a set name ever qualifying or
        disqualifying a field on its own.

        Ties break deterministically on coverage then label, so the same
        question always produces the same slate.
        """
        scored: list[tuple[FieldConcept, float, float]] = []
        for concept in self.concepts:
            if not concept.applies_to(subject_classes):
                continue
            score = token_overlap(query_tokens, concept.name_tokens)
            if score < min_overlap:
                continue
            set_affinity = token_overlap(query_tokens, concept.set_tokens)
            scored.append((concept, score, set_affinity))
        scored.sort(key=lambda t: (-t[1], -t[2], -t[0].coverage_ratio, t[0].label))
        return [(concept, score) for concept, score, _ in scored[:limit]]

    def get(self, field_kind: str, set_name: str | None, field_name: str) -> FieldConcept | None:
        for concept in self.concepts:
            if concept.key == (field_kind, set_name, field_name):
                return concept
        return None


# ---------------------------------------------------------------------------
# Data-type inference
# ---------------------------------------------------------------------------


def _infer_data_type(values: list[str]) -> str:
    """Infer a field's type from the values the model actually stores.

    Reading the data beats trusting a declared type: IFC property values arrive
    as strings regardless of their real type, and exporters are inconsistent.
    Falls back to `text`, whose operator set is the most permissive, so an
    inference miss never blocks a query.
    """
    from app.query.binding.values import is_numeric_value, parse_boolean

    if not values:
        return "text"
    if all(parse_boolean(v) is not None for v in values):
        return "boolean"
    # Strict whole-string test: a value such as `EI30` contains a number but is
    # categorical, and giving it numeric comparison operators would be wrong.
    if all(is_numeric_value(v) for v in values):
        return "number"
    return "text"


def _operators_for(data_type: str) -> tuple[str, ...]:
    if data_type == "number":
        return _NUMERIC_OPERATORS
    if data_type == "boolean":
        return _BOOLEAN_OPERATORS
    return _TEXT_OPERATORS


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


def _build_property_concepts(vocab: ModelVocabulary) -> list[FieldConcept]:
    """Property fields, merging observed values with coverage counts."""
    values: dict[tuple[str, str], list[str]] = {}
    classes: dict[tuple[str, str], set[str]] = {}
    coverage: dict[tuple[str, str], tuple[int, int]] = {}

    for fact in vocab.facts:
        if fact.set_name is None or fact.field_name is None:
            continue
        key = (fact.set_name, fact.field_name)
        if fact.fact_kind == "property_value":
            values.setdefault(key, [])
            if fact.observed_value not in values[key]:
                values[key].append(fact.observed_value)
            classes.setdefault(key, set()).add(fact.ifc_class)
        elif fact.fact_kind == "property_coverage":
            classes.setdefault(key, set()).add(fact.ifc_class)
            populated, total = coverage.get(key, (0, 0))
            #: `observed_value` is "<populated>/<total> populated"; the parsed
            #: counts are summed across classes so coverage is model-wide.
            parsed_total = _parse_total(fact.observed_value)
            coverage[key] = (populated + fact.occurrence_count, total + parsed_total)

    concepts: list[FieldConcept] = []
    for key in sorted(set(values) | set(coverage)):
        set_name, field_name = key
        observed = values.get(key, [])
        data_type = _infer_data_type(observed)
        populated, total = coverage.get(key, (0, 0))
        concepts.append(
            FieldConcept(
                field_kind="property",
                set_name=set_name,
                field_name=field_name,
                data_type=data_type,
                operators=_operators_for(data_type),
                applicable_classes=tuple(sorted(classes.get(key, set()))),
                populated_count=populated,
                total_count=total,
                sample_values=tuple(observed[:_MAX_SAMPLE_VALUES]),
            )
        )
    return concepts


def _parse_total(observed_value: str) -> int:
    """Total from a `"<populated>/<total> populated"` coverage string."""
    head = observed_value.split(" ", 1)[0]
    if "/" not in head:
        return 0
    try:
        return int(head.split("/", 1)[1])
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return 0


def _build_quantity_concepts(vocab: ModelVocabulary) -> list[FieldConcept]:
    merged: dict[tuple[str, str], list] = {}
    for qty in vocab.quantities:
        merged.setdefault((qty.set_name, qty.field_name), []).append(qty)
    concepts: list[FieldConcept] = []
    for (set_name, field_name), profiles in sorted(merged.items()):
        concepts.append(
            FieldConcept(
                field_kind="quantity",
                set_name=set_name,
                field_name=field_name,
                data_type="number",
                operators=_NUMERIC_OPERATORS,
                applicable_classes=tuple(sorted({p.ifc_class for p in profiles})),
                populated_count=sum(p.populated_count for p in profiles),
                total_count=sum(p.total_count for p in profiles),
                unit_available=any(p.unit_available for p in profiles),
            )
        )
    return concepts


#: Observed-fact kinds that describe a fixed attribute/type-fact field, mapped
#: to the canonical field reference the typed SQL path already understands.
_FACT_KIND_FIELDS: dict[str, tuple[str, str]] = {
    "name_stem": ("attribute", "name"),
    "object_type": ("attribute", "object_type"),
    "predefined_type": ("attribute", "predefined_type"),
    "storey": ("attribute", "storey_name"),
    "type_name": ("type_fact", "type_name"),
}


def _build_attribute_concepts(vocab: ModelVocabulary) -> list[FieldConcept]:
    """Fixed attribute/type-fact fields, carrying the values actually observed."""
    values: dict[tuple[str, str], list[str]] = {}
    classes: dict[tuple[str, str], set[str]] = {}
    for fact in vocab.facts:
        target = _FACT_KIND_FIELDS.get(fact.fact_kind)
        if target is None:
            continue
        values.setdefault(target, [])
        if fact.observed_value not in values[target]:
            values[target].append(fact.observed_value)
        classes.setdefault(target, set()).add(fact.ifc_class)

    known = set(ATTRIBUTE_JSON_FIELDS) | set(ATTRIBUTE_COLUMN_FIELDS)
    concepts: list[FieldConcept] = []
    for field_kind, field_name in sorted(set(_FACT_KIND_FIELDS.values())):
        if field_kind == "attribute" and field_name not in known:
            continue  # pragma: no cover - guards a registry/vocabulary drift
        if field_kind == "type_fact" and field_name not in TYPE_FACT_JSON_FIELDS:
            continue  # pragma: no cover
        key = (field_kind, field_name)
        observed = values.get(key, [])
        concepts.append(
            FieldConcept(
                field_kind=field_kind,
                set_name=None,
                field_name=field_name,
                data_type="text",
                operators=_TEXT_OPERATORS,
                applicable_classes=tuple(sorted(classes.get(key, set()))),
                sample_values=tuple(observed[:_MAX_SAMPLE_VALUES]),
            )
        )

    # Fixed fields that carry no observed-value facts but remain queryable, so a
    # question naming them still finds a candidate.
    covered = {(c.field_kind, c.field_name) for c in concepts}
    for field_name in sorted(known):
        if ("attribute", field_name) not in covered:
            concepts.append(
                FieldConcept(
                    field_kind="attribute",
                    set_name=None,
                    field_name=field_name,
                    data_type="text",
                    operators=_TEXT_OPERATORS,
                )
            )
    for field_name in sorted(TYPE_FACT_JSON_FIELDS):
        if ("type_fact", field_name) not in covered:
            concepts.append(
                FieldConcept(
                    field_kind="type_fact",
                    set_name=None,
                    field_name=field_name,
                    data_type="text",
                    operators=_TEXT_OPERATORS,
                )
            )
    return concepts


def build_field_concept_index(
    session: Session, source_model_id: int, settings: Settings | None = None
) -> FieldConceptIndex:
    settings = settings or get_settings()
    vocab = get_model_vocabulary(session, source_model_id, settings)
    concepts: list[FieldConcept] = []
    concepts.extend(_build_property_concepts(vocab))
    concepts.extend(_build_quantity_concepts(vocab))
    concepts.extend(_build_attribute_concepts(vocab))
    concepts.sort(key=lambda c: (c.field_kind, c.set_name or "", c.field_name))
    return FieldConceptIndex(
        source_model_id=source_model_id,
        file_fingerprint=vocab.file_fingerprint,
        concepts=concepts,
    )


_CACHE: dict[tuple, FieldConceptIndex] = {}


def get_field_concept_index(
    session: Session, source_model_id: int, settings: Settings | None = None
) -> FieldConceptIndex:
    """Cached field-concept index. Key mirrors the model-vocabulary key so a
    re-import under the same id invalidates both together."""
    settings = settings or get_settings()
    vocab = get_model_vocabulary(session, source_model_id, settings)
    key = (
        source_model_id,
        vocab.file_fingerprint,
        EXTRACTION_VERSION,
        PROFILE_BUILDER_VERSION,
        FIELD_CONCEPT_BUILDER_VERSION,
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    index = build_field_concept_index(session, source_model_id, settings)
    _CACHE[key] = index
    return index


def clear_field_concept_cache() -> None:
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Complete value vocabulary (read on demand)
# ---------------------------------------------------------------------------


def load_field_values(
    session: Session,
    source_model_id: int,
    concept: FieldConcept,
    ifc_classes: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """The field's COMPLETE distinct stored values, scoped to the model.

    §4.2 requires authoritative value resolution to run against the chosen
    field's whole indexed vocabulary, not the capped sample carried in the
    slate. One bounded, parameterized aggregate per resolved value — not one
    query per candidate (§10.3).

    Returns [] for a field whose values are not reachable as text (quantities
    are matched numerically, not by value identity).
    """
    if concept.field_kind == "quantity":
        return []
    path = _json_path_for(concept)
    if path is None:
        return []

    where = _ET.c.source_model_id == source_model_id
    if ifc_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(list(ifc_classes)))
    value_expr = _ET.c.canonical_json.op("#>>")(path_array_param(path))
    stmt = (
        sa.select(value_expr.label("value"))
        .where(sa.and_(where, value_expr.is_not(None)))
        .distinct()
        .order_by("value")
        .limit(_MAX_DISTINCT_VALUES)
    )
    return [row.value for row in session.execute(stmt) if row.value]


def _json_path_for(concept: FieldConcept) -> tuple[str, ...] | None:
    """Canonical JSON path for a concept, reusing the field registry's maps so
    there is exactly one definition of where a field lives."""
    if concept.field_kind == "property" and concept.set_name:
        return ("property_sets", concept.set_name, concept.field_name, "value")
    if concept.field_kind == "attribute":
        return ATTRIBUTE_JSON_FIELDS.get(concept.field_name)
    if concept.field_kind == "type_fact":
        return TYPE_FACT_JSON_FIELDS.get(concept.field_name)
    return None
