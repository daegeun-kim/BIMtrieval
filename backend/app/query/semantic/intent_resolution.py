"""Deterministic resolution of a conceptual intent tree (Task 23 §1).

Stage 3b of the pipeline. LLM call 1 has emitted, per facet, a `result_concept`
and a typed tree of `IntentCondition`s expressed in plain language. This module
resolves those leaves against the ACTIVE MODEL — ontology candidates, observed
vocabulary, and IFC spatial data — while preserving each condition's identity,
Boolean position, and subject scope.

Design rules this module exists to enforce:

- **Contextual resolution.** A condition is resolved against the facet's already
  resolved result class, not against the whole model. "width" on a door query
  resolves to a width observed on doors, never to any width-like field anywhere.
- **Never silently drop.** A required condition that cannot be resolved is
  reported as unresolved. The caller must fail or clarify — it must never run the
  broader unfiltered query instead.
- **No new LLM call and no new embedding work.** Resolution is lexical +
  structural over the vocabulary/spatial data the pipeline already caches, so it
  adds no model round trips to the query path.
- **No SQL here.** This module produces typed `PredicateCondition`s; compiling
  them to filters remains the job of the existing SQL compiler.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.llm.schemas import ConceptKind, IntentOperator
from app.query.hybrid.groups.schemas import PredicateCondition, PredicateGroup
from app.query.semantic.spatial import mentions_floor_concept, resolve_floor_concept
from app.query.semantic.vocabulary.cache import get_model_vocabulary
from app.query.semantic.vocabulary.profiles import ModelVocabulary

# Conceptual operator -> allowlisted SQL operator, for a TEXT-valued field.
_TEXT_OPERATORS = {
    IntentOperator.EQUALS: "case_insensitive_exact",
    IntentOperator.CONTAINS: "contains",
    IntentOperator.STARTS_WITH: "starts_with",
    IntentOperator.ONE_OF: "in",
}
# Conceptual operator -> allowlisted SQL operator, for a NUMERIC-valued field.
_NUMERIC_OPERATORS = {
    IntentOperator.EQUALS: "eq",
    IntentOperator.GREATER_THAN: "gt",
    IntentOperator.GREATER_OR_EQUAL: "gte",
    IntentOperator.LESS_THAN: "lt",
    IntentOperator.LESS_OR_EQUAL: "lte",
    IntentOperator.BETWEEN: "between",
    IntentOperator.ONE_OF: "in",
}
#: Values that mean "true"/"false" across the IFC exporters seen in practice.
_TRUE_TOKENS = {"true", "t", ".t.", "yes", "y", "1"}
_FALSE_TOKENS = {"false", "f", ".f.", "no", "n", "0"}


@dataclass
class ResolvedCondition:
    condition_id: str
    parent_group_id: str | None
    condition: PredicateCondition | None
    required: bool
    interpretation: str | None = None
    unresolved_reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.condition is not None


@dataclass
class FacetIntent:
    """One facet's fully resolved result scope."""

    facet_id: str
    ifc_classes: list[str] = field(default_factory=list)
    filters: PredicateGroup | None = None
    interpretation_notes: list[str] = field(default_factory=list)
    unresolved_required: list[str] = field(default_factory=list)
    condition_count: int = 0

    @property
    def has_conditions(self) -> bool:
        return self.condition_count > 0

    @property
    def executable(self) -> bool:
        """A constrained facet is executable only when EVERY required condition
        resolved — otherwise running it would answer a different question."""
        return bool(self.ifc_classes) and not self.unresolved_required


# ---------------------------------------------------------------------------
# Lexical helpers (deterministic; no embeddings)
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 1}


def _split_identifier(name: str) -> set[str]:
    """Tokenize an IFC field name: `IsExternal` -> {is, external}."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name or "")
    return _tokens(spaced)


def _overlap(concept: str, candidate: str) -> float:
    """Jaccard-style containment of the concept's tokens in the candidate name."""
    c = _tokens(concept)
    k = _split_identifier(candidate)
    if not c or not k:
        return 0.0
    return len(c & k) / len(c)


def _is_boolean_value(value: str) -> bool:
    return (value or "").strip().lower() in (_TRUE_TOKENS | _FALSE_TOKENS)


def _numeric(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Condition resolution
# ---------------------------------------------------------------------------


def _resolve_spatial(
    session: Session, source_model_id: int, condition, concept_text: str
) -> ResolvedCondition:
    """Floor/level scope -> containing-storey identities (Task 23 §1).

    Delegates entirely to the model-independent elevation-band resolver; this
    module never inspects storey names or applies a naming convention."""
    result = resolve_floor_concept(session, source_model_id, concept_text)
    if not result.resolved:
        return ResolvedCondition(
            condition_id=condition.condition_id,
            parent_group_id=condition.parent_group_id,
            condition=None,
            required=condition.required,
            unresolved_reason=result.reason,
        )
    return ResolvedCondition(
        condition_id=condition.condition_id,
        parent_group_id=condition.parent_group_id,
        required=condition.required,
        interpretation=result.interpretation,
        condition=PredicateCondition(
            field_kind="attribute",
            field_name="storey_global_id",
            # An `IN` over every storey entity in the resolved band: multiple
            # wings at one level are ONE floor, not an ambiguity (Task 23 §1).
            operator="in",
            value=tuple(result.storey_global_ids),
            negated=condition.negated,
            concept=condition.concept,
            interpretation=result.interpretation,
        ),
    )


def _candidate_facts(vocab: ModelVocabulary, ifc_classes: list[str]) -> list:
    """Observed facts for the resolved result classes ONLY — this is what makes
    resolution contextual to the subject rather than global."""
    wanted = {c.lower() for c in ifc_classes}
    return [
        f
        for f in vocab.facts
        if f.ifc_class.lower() in wanted
        and f.queryable is not None
        and f.fact_kind != "property_coverage"
    ]


def _resolve_value_field(
    condition, concept_text: str, value_text: str, facts: list
) -> tuple[object, str] | None:
    """Pick the (field, value) the condition means, from observed facts on the
    subject class. Returns (fact, matched_value) or None."""
    best: tuple[float, object] | None = None
    for fact in facts:
        ref = fact.queryable
        field_label = ref.field_name or fact.fact_kind or ""
        field_score = max(
            _overlap(concept_text, field_label),
            _overlap(concept_text, fact.fact_kind or ""),
        )
        if field_score <= 0.0:
            continue
        observed = str(fact.observed_value or "")
        value_score = 0.0
        if value_text:
            if observed.strip().lower() == value_text.strip().lower():
                value_score = 1.0
            elif _is_boolean_value(observed) and _is_boolean_value(value_text):
                same = (observed.strip().lower() in _TRUE_TOKENS) == (
                    value_text.strip().lower() in _TRUE_TOKENS
                )
                value_score = 1.0 if same else 0.0
            else:
                value_score = _overlap(value_text, observed)
        score = field_score * 2.0 + value_score
        if value_text and value_score <= 0.0:
            continue
        if best is None or score > best[0]:
            best = (score, fact)
    return (best[1], str(best[1].observed_value)) if best else None


def _resolve_value_condition(condition, concept_text: str, facts: list) -> ResolvedCondition:
    """A field/property/material/classification/quantity condition."""
    values = list(condition.value_list) or (
        [condition.value_concept] if condition.value_concept else []
    )
    value_text = str(values[0]) if values else ""

    match = _resolve_value_field(condition, concept_text, value_text, facts)
    if match is None:
        return ResolvedCondition(
            condition_id=condition.condition_id,
            parent_group_id=condition.parent_group_id,
            condition=None,
            required=condition.required,
            unresolved_reason=(
                f"no observed {concept_text!r} value matching "
                f"{value_text!r} on the requested objects in this model"
            ),
        )
    fact, matched_value = match
    ref = fact.queryable

    numeric = _numeric(matched_value) is not None
    table = _NUMERIC_OPERATORS if numeric else _TEXT_OPERATORS
    sql_op = table.get(condition.operator)
    if sql_op is None:
        return ResolvedCondition(
            condition_id=condition.condition_id,
            parent_group_id=condition.parent_group_id,
            condition=None,
            required=condition.required,
            unresolved_reason=(
                f"operator {condition.operator.value!r} cannot be applied to "
                f"{ref.field_name!r} in this model"
            ),
        )

    if condition.operator in (IntentOperator.ONE_OF, IntentOperator.BETWEEN):
        value: object = tuple(str(v) for v in values)
    else:
        value = matched_value

    where = f"{ref.set_name}.{ref.field_name}" if ref.set_name else ref.field_name
    interpretation = (
        f"Interpreted {condition.concept!r} as {where} = {matched_value!r} on {fact.ifc_class}."
    )
    return ResolvedCondition(
        condition_id=condition.condition_id,
        parent_group_id=condition.parent_group_id,
        required=condition.required,
        interpretation=interpretation,
        condition=PredicateCondition(
            field_kind=ref.field_kind,
            set_name=ref.set_name,
            field_name=ref.field_name,
            operator=sql_op,
            value=value,
            unit=condition.unit,
            negated=condition.negated,
            concept=condition.concept,
            interpretation=interpretation,
        ),
    )


def resolve_condition(
    session: Session,
    source_model_id: int,
    condition,
    ifc_classes: list[str],
    vocab: ModelVocabulary,
) -> ResolvedCondition:
    """Resolve ONE conceptual condition against the model, in the subject's context."""
    concept_text = condition.concept or ""
    value_text = condition.value_concept or ""

    # Spatial scope: either explicitly typed as such, or unmistakably about a
    # building level. Both routes go through the same model-independent resolver.
    spatial = condition.concept_kind is ConceptKind.SPATIAL_SCOPE or mentions_floor_concept(
        f"{concept_text} {value_text}"
    )
    if spatial:
        resolved = _resolve_spatial(session, source_model_id, condition, value_text or concept_text)
        # A spatial-looking condition that is NOT a floor (e.g. "in the north
        # wing") falls through to ordinary value resolution rather than failing.
        if resolved.resolved or condition.concept_kind is ConceptKind.SPATIAL_SCOPE:
            return resolved

    if condition.operator in (IntentOperator.IS_MISSING, IntentOperator.IS_PRESENT):
        return ResolvedCondition(
            condition_id=condition.condition_id,
            parent_group_id=condition.parent_group_id,
            condition=None,
            required=condition.required,
            unresolved_reason=(
                f"presence/absence filtering on {concept_text!r} is not supported "
                "by the current structured query path"
            ),
        )

    facts = _candidate_facts(vocab, ifc_classes)
    if not facts:
        return ResolvedCondition(
            condition_id=condition.condition_id,
            parent_group_id=condition.parent_group_id,
            condition=None,
            required=condition.required,
            unresolved_reason=(
                "the requested objects carry no queryable observed values in this model"
            ),
        )
    return _resolve_value_condition(condition, concept_text, facts)


# ---------------------------------------------------------------------------
# Facet-level composition
# ---------------------------------------------------------------------------


def _compose(resolved: list[ResolvedCondition], groups: list) -> PredicateGroup | None:
    """Rebuild the planner's Boolean structure from resolved leaves.

    Conditions with no parent group are combined with AND, matching the planner
    contract. A group's own resolved children keep their declared `bool_op`, so
    an `OR` the user expressed stays an `OR`."""
    usable = [r for r in resolved if r.resolved]
    if not usable:
        return None

    by_parent: dict[str | None, list[PredicateCondition]] = {}
    for r in usable:
        by_parent.setdefault(r.parent_group_id, []).append(r.condition)  # type: ignore[arg-type]

    group_meta = {g.group_id: g for g in groups}
    built: dict[str, PredicateGroup] = {}

    # Build deepest-first so a nested group exists before its parent references it.
    def depth(gid: str) -> int:
        d, cur, seen = 0, group_meta.get(gid), set()
        while cur is not None and cur.group_id not in seen:
            seen.add(cur.group_id)
            if not cur.parent_group_id:
                break
            cur = group_meta.get(cur.parent_group_id)
            d += 1
        return d

    for gid in sorted(group_meta, key=depth, reverse=True):
        meta = group_meta[gid]
        children: list = list(by_parent.get(gid, []))
        children.extend(
            built[g.group_id] for g in groups if g.parent_group_id == gid and g.group_id in built
        )
        if children:
            built[gid] = PredicateGroup(bool_op=meta.bool_op, conditions=tuple(children))

    top: list = list(by_parent.get(None, []))
    top.extend(built[g.group_id] for g in groups if not g.parent_group_id and g.group_id in built)
    if not top:
        return None
    if len(top) == 1 and isinstance(top[0], PredicateGroup):
        return top[0]
    return PredicateGroup(bool_op="and", conditions=tuple(top))


def resolve_facet_intent(
    session: Session,
    facet,
    ifc_classes: list[str],
    source_model_id: int,
    *,
    settings: Settings,
) -> FacetIntent:
    """Resolve one facet's whole intent tree against the active model."""
    intent = FacetIntent(
        facet_id=facet.facet_id,
        ifc_classes=list(ifc_classes),
        condition_count=len(getattr(facet, "conditions", []) or []),
    )
    conditions = getattr(facet, "conditions", None) or []
    if not conditions:
        return intent

    vocab = get_model_vocabulary(session, source_model_id, settings)
    resolved = [
        resolve_condition(session, source_model_id, c, ifc_classes, vocab) for c in conditions
    ]
    for r in resolved:
        if r.interpretation:
            intent.interpretation_notes.append(r.interpretation)
        if not r.resolved and r.required:
            intent.unresolved_required.append(r.unresolved_reason or "unresolved condition")

    intent.filters = _compose(resolved, getattr(facet, "condition_groups", None) or [])
    return intent
