"""Compile a validated binding into ONE typed, executable predicate (Task 24 §4, §5.2).

The output of this module is the single source of truth for an answer part.
§9 requires that "the final answer, exact total, and viewer identities must
derive from the same authoritative answer-part result", so exactly one
`CompiledPredicate` is built per part and every downstream consumer — the exact
count, the class breakdown, the examples, the RAG scope, the graph seeds, and
the viewer identities — is derived from it. There is no second place where a
"similar" predicate could be rebuilt and drift.

Value resolution happens HERE, not in the binder, and against the chosen
field's COMPLETE stored vocabulary (§4.2). A value the model does not hold is
reported as unresolved; it is never dropped so that a broader query can run
(§2.4), and it never falls back to a nearby field (§3.3).

Everything compiles to the existing typed SQL vocabulary in
`app.query.sql.schemas`, so the existing allowlists, bound-parameter
compilation, and Boolean-depth limits apply unchanged — this module adds no new
query engine (§Required architecture: "reused and corrected rather than rebuilt
as parallel systems").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.llm.schemas import AnswerPart, BoundCondition, BoundOperator, ScopeKind
from app.query.binding.closure import SubjectClosure
from app.query.binding.schemas import CandidateSlate, FieldCandidate
from app.query.binding.values import ValueMatch, parse_number, resolve_value
from app.query.semantic.field_concepts import (
    FieldConcept,
    get_field_concept_index,
    load_field_values,
)
from app.query.sql.schemas import (
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterGroup,
    Operator,
)

__all__ = [
    "CompiledPredicate",
    "UnresolvedCondition",
    "compile_predicate",
]


#: Conceptual operator -> allowlisted SQL operator, per resolved data type.
#: Text equality uses case-insensitive matching because exporters are
#: inconsistent about case; a user demanding exactness is honoured earlier, by
#: `resolve_value(exact_required=True)` refusing a merely-similar stored value.
_TEXT_OPERATORS: dict[BoundOperator, Operator] = {
    BoundOperator.EQUALS: Operator.CASE_INSENSITIVE_EXACT,
    BoundOperator.NOT_EQUALS: Operator.NOT_IN,
    BoundOperator.CONTAINS: Operator.CONTAINS,
    BoundOperator.STARTS_WITH: Operator.STARTS_WITH,
    BoundOperator.ONE_OF: Operator.IN,
}
_NUMERIC_OPERATORS: dict[BoundOperator, Operator] = {
    BoundOperator.EQUALS: Operator.EQ,
    BoundOperator.NOT_EQUALS: Operator.NE,
    BoundOperator.GREATER_THAN: Operator.GT,
    BoundOperator.GREATER_OR_EQUAL: Operator.GTE,
    BoundOperator.LESS_THAN: Operator.LT,
    BoundOperator.LESS_OR_EQUAL: Operator.LTE,
    BoundOperator.BETWEEN: Operator.BETWEEN,
    BoundOperator.ONE_OF: Operator.IN,
}

#: The stored attribute a floor-band condition constrains. Storey containment is
#: recorded per entity as `storey.global_id`, so a logical floor band compiles
#: to an IN over its member storeys — the band abstraction never leaks into SQL.
_STOREY_FIELD = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="storey_global_id")


@dataclass(frozen=True)
class UnresolvedCondition:
    """A condition that could not be compiled, and why.

    Its presence forces an `unavailable`/`partial` result. It may never be
    silently discarded to let a broader query execute (§2.4, §6).
    """

    condition_id: str
    reason: str
    source_span: str | None = None


@dataclass
class CompiledPredicate:
    """The one executable description of an answer part's result set."""

    source_model_id: int
    ifc_classes: tuple[str, ...]
    filters: FilterGroup | None = None
    #: Entity ids the result is restricted to (selection / previous result).
    scope_entity_ids: tuple[int, ...] | None = None
    #: How each condition was actually resolved, reported to the user so the
    #: interpretation can be seen and corrected rather than trusted.
    interpretation_notes: list[str] = field(default_factory=list)
    unresolved: list[UnresolvedCondition] = field(default_factory=list)

    @property
    def executable(self) -> bool:
        """True when this predicate can be run as the user asked.

        An unresolved condition makes it NOT executable: running the remainder
        would answer a broader question than the one asked.
        """
        return not self.unresolved and bool(self.ifc_classes)

    @property
    def is_empty_scope(self) -> bool:
        """True when an explicit scope resolved to no entities at all."""
        return self.scope_entity_ids is not None and len(self.scope_entity_ids) == 0


def compile_predicate(
    session: Session,
    part: AnswerPart,
    closure: SubjectClosure,
    slate: CandidateSlate,
    source_model_id: int,
    *,
    selection_entity_ids: list[int] | None = None,
    previous_scope_entity_ids: list[int] | None = None,
) -> CompiledPredicate:
    """Compile one validated answer part into its authoritative predicate."""
    predicate = CompiledPredicate(
        source_model_id=source_model_id,
        ifc_classes=closure.ifc_classes,
        interpretation_notes=list(closure.notes),
    )

    # Scope conditions are kept SEPARATE from the part's own conditions so the
    # merge below can AND them together even when the conditions OR among
    # themselves. Folding them into one list would let "walls on floor 2 that
    # are external or load bearing" become an OR across the floor too.
    scope_nodes = _scope_conditions(
        part, slate, predicate, selection_entity_ids, previous_scope_entity_ids
    )

    condition_nodes: list[FilterCondition | FilterGroup] = []
    grouped: dict[str, list[FilterCondition]] = {}
    for condition in part.conditions:
        compiled = _compile_condition(session, condition, slate, predicate, source_model_id)
        if compiled is None:
            continue
        if condition.bool_group:
            grouped.setdefault(condition.bool_group, []).append(compiled)
        else:
            condition_nodes.append(compiled)

    # Conditions sharing a bool_group are OR-ed within the group; the groups and
    # the ungrouped conditions then combine with the part's operator. This maps
    # the flat binding structure onto the existing bounded FilterGroup tree
    # without exceeding its depth limit.
    for conditions in grouped.values():
        condition_nodes.append(
            conditions[0]
            if len(conditions) == 1
            else FilterGroup(bool_op="or", conditions=conditions)
        )

    predicate.filters = _merge_scope_and_conditions(
        scope_nodes, condition_nodes, part.condition_bool_op
    )
    return predicate


def _merge_scope_and_conditions(
    scope_nodes: list[FilterCondition],
    condition_nodes: list[FilterCondition | FilterGroup],
    bool_op: str,
) -> FilterGroup | None:
    """Scope always ANDs with the conditions, even when they OR among themselves.

    "external OR load bearing walls on the second floor" means
    `floor AND (external OR load_bearing)` — never
    `floor OR external OR load_bearing`, which would return the whole floor.
    """
    if not scope_nodes and not condition_nodes:
        return None
    if not scope_nodes:
        return FilterGroup(bool_op=bool_op, conditions=condition_nodes)
    if not condition_nodes:
        return FilterGroup(bool_op="and", conditions=list(scope_nodes))
    inner: FilterCondition | FilterGroup = (
        condition_nodes[0]
        if len(condition_nodes) == 1
        else FilterGroup(bool_op=bool_op, conditions=condition_nodes)
    )
    return FilterGroup(bool_op="and", conditions=[*scope_nodes, inner])


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _scope_conditions(
    part: AnswerPart,
    slate: CandidateSlate,
    predicate: CompiledPredicate,
    selection_entity_ids: list[int] | None,
    previous_scope_entity_ids: list[int] | None,
) -> list[FilterCondition]:
    """Filter nodes implied by the part's scope (§1.3).

    A scope SELECTS what to look at. Entity-id scopes (selection, previous
    result) are carried on the predicate rather than compiled into SQL, because
    they also seed RAG and graph execution. A floor band is the one scope that
    IS a genuine restricting condition, so it alone returns a filter node.

    The active-model scope deliberately returns nothing: it is the default
    extent, and representing it as a predicate would turn a scope reference into
    a condition — the exact confusion §1.3 exists to prevent, and the direct
    cause of a recorded family of "could not read a specific floor from 'this
    building'" failures.
    """
    if part.scope_kind is ScopeKind.ACTIVE_MODEL:
        return []

    if part.scope_kind is ScopeKind.SELECTED_OBJECTS:
        predicate.scope_entity_ids = tuple(selection_entity_ids or ())
        predicate.interpretation_notes.append(
            f"restricted to the {len(predicate.scope_entity_ids)} object(s) you have selected"
        )
        return []

    if part.scope_kind is ScopeKind.PREVIOUS_RESULT:
        predicate.scope_entity_ids = tuple(previous_scope_entity_ids or ())
        predicate.interpretation_notes.append("restricted to the previous result you asked about")
        return []

    # A typed spatial candidate. Only a genuine CONDITION kind reaches SQL.
    candidate = slate.spatial_candidate(part.scope_candidate_id or "")
    if candidate is None:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition_id="scope",
                reason=(
                    f"spatial scope {part.scope_candidate_id!r} is not available for this request"
                ),
            )
        )
        return []
    if candidate.is_scope_selection:
        # Validation rejects this too; compiling it would silently narrow.
        return []
    if not candidate.storey_global_ids:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition_id="scope",
                reason=f"{candidate.label} contains no storey identities to restrict by",
            )
        )
        return []

    predicate.interpretation_notes.append(
        candidate.interpretation
        or f"restricted to {candidate.label} ({len(candidate.storey_global_ids)} storey entities)"
    )
    return [
        FilterCondition(
            field=_STOREY_FIELD,
            operator=Operator.IN,
            value=list(candidate.storey_global_ids),
        )
    ]


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def _compile_condition(
    session: Session,
    condition: BoundCondition,
    slate: CandidateSlate,
    predicate: CompiledPredicate,
    source_model_id: int,
) -> FilterCondition | None:
    """Compile one bound condition, or record why it could not be."""
    spatial = slate.spatial_candidate(condition.candidate_id)
    if spatial is not None:
        return _compile_spatial_condition(condition, spatial, predicate)

    candidate = slate.field_candidate(condition.candidate_id)
    if candidate is None:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"{condition.candidate_id!r} is not a field available for this request",
                condition.source_span,
            )
        )
        return None

    concept = _concept_for(session, source_model_id, candidate)
    field_ref = _field_ref(candidate)

    if condition.operator in (BoundOperator.IS_PRESENT, BoundOperator.IS_MISSING):
        # Presence/absence is a distinct operation with its own coverage
        # semantics (§4.3); it is not a value comparison and is executed via the
        # missing-value path rather than compiled into a filter here.
        return None

    if candidate.data_type == "number":
        return _compile_numeric(condition, candidate, field_ref, predicate)
    return _compile_text(
        session, condition, candidate, concept, field_ref, predicate, source_model_id
    )


def _compile_spatial_condition(
    condition: BoundCondition, spatial, predicate: CompiledPredicate
) -> FilterCondition | None:
    if spatial.is_scope_selection:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"{spatial.label} selects what to look at and cannot narrow the result",
                condition.source_span,
            )
        )
        return None
    if not spatial.storey_global_ids:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"{spatial.label} contains no storey identities to restrict by",
                condition.source_span,
            )
        )
        return None
    predicate.interpretation_notes.append(
        spatial.interpretation or f"restricted to {spatial.label}"
    )
    return FilterCondition(
        field=_STOREY_FIELD,
        operator=Operator.IN,
        value=list(spatial.storey_global_ids),
    )


def _compile_numeric(
    condition: BoundCondition,
    candidate: FieldCandidate,
    field_ref: FieldRef,
    predicate: CompiledPredicate,
) -> FilterCondition | None:
    operator = _NUMERIC_OPERATORS.get(condition.operator)
    if operator is None:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"{condition.operator.value} cannot be applied to the numeric field "
                f"{candidate.label}",
                condition.source_span,
            )
        )
        return None

    raw_values = condition.value_list or ([condition.value_text] if condition.value_text else [])
    numbers: list[float] = []
    unit: str | None = condition.unit
    for raw in raw_values:
        parsed = parse_number(raw)
        if parsed is None:
            predicate.unresolved.append(
                UnresolvedCondition(
                    condition.condition_id,
                    f"{raw!r} is not a number, so it cannot be compared against {candidate.label}",
                    condition.source_span,
                )
            )
            return None
        magnitude, parsed_unit = parsed
        numbers.append(magnitude)
        unit = unit or parsed_unit

    if unit and not candidate.unit_available:
        # §3.3: units must be deterministically convertible. Refusing here is
        # what stops a millimetre comparison being run against an unnormalized
        # stored number and silently producing a wrong set.
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"{candidate.label} records no normalized unit, so a value in {unit} "
                "cannot be compared against it",
                condition.source_span,
            )
        )
        return None

    if operator is Operator.BETWEEN and len(numbers) != 2:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"a range on {candidate.label} needs two bounds",
                condition.source_span,
            )
        )
        return None

    value: object = numbers if operator in (Operator.BETWEEN, Operator.IN) else numbers[0]
    predicate.interpretation_notes.append(
        f"{candidate.label} {condition.operator.value.replace('_', ' ')} "
        f"{numbers[0] if len(numbers) == 1 else numbers}" + (f" {unit}" if unit else "")
    )
    return FilterCondition(field=field_ref, operator=operator, value=value, unit=unit)


def _compile_text(
    session: Session,
    condition: BoundCondition,
    candidate: FieldCandidate,
    concept: FieldConcept | None,
    field_ref: FieldRef,
    predicate: CompiledPredicate,
    source_model_id: int,
) -> FilterCondition | None:
    operator = _TEXT_OPERATORS.get(condition.operator)
    if operator is None:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"{condition.operator.value} cannot be applied to {candidate.label}",
                condition.source_span,
            )
        )
        return None

    raw_values = condition.value_list or ([condition.value_text] if condition.value_text else [])
    if not raw_values:
        predicate.unresolved.append(
            UnresolvedCondition(
                condition.condition_id,
                f"no value was supplied for {candidate.label}",
                condition.source_span,
            )
        )
        return None

    # §4.2: resolve against the field's COMPLETE stored vocabulary, read on
    # demand — never the bounded sample carried in the slate, and never another
    # field's values.
    vocabulary = (
        load_field_values(session, source_model_id, concept, candidate.applicable_classes)
        if concept is not None
        else []
    )
    # A quoted value means the user asked for exactness (§4.2).
    exact_required = _was_quoted(condition, predicate)
    allow_contains = condition.operator in (BoundOperator.CONTAINS, BoundOperator.STARTS_WITH)

    resolved: list[str] = []
    for raw in raw_values:
        if allow_contains:
            # A contains/starts_with request is matching a fragment on purpose,
            # so it is not resolved against whole stored values.
            resolved.append(raw)
            continue
        match = resolve_value(raw, vocabulary, exact_required=exact_required)
        if match is None:
            predicate.unresolved.append(
                UnresolvedCondition(
                    condition.condition_id,
                    _unresolved_value_reason(raw, candidate, vocabulary),
                    condition.source_span,
                )
            )
            return None
        resolved.append(match.stored_value)
        _note_interpretation(predicate, candidate, match)

    negated = condition.negated or condition.operator is BoundOperator.NOT_EQUALS
    if negated:
        return FilterCondition(field=field_ref, operator=Operator.NOT_IN, value=resolved)
    if operator in (Operator.IN, Operator.NOT_IN) or len(resolved) > 1:
        return FilterCondition(field=field_ref, operator=Operator.IN, value=resolved)
    return FilterCondition(field=field_ref, operator=operator, value=resolved[0])


def _unresolved_value_reason(raw: str, candidate: FieldCandidate, vocabulary: list[str]) -> str:
    """A reason that distinguishes 'no such value' from 'no such field data'.

    §6 requires these to stay distinct: a field the model never populates is
    UNAVAILABLE, whereas a populated field that simply lacks this value is a
    genuine zero.
    """
    if not vocabulary:
        return (
            f"{candidate.label} holds no values in this model, so {raw!r} cannot be "
            "matched against it"
        )
    return f"{raw!r} is not one of the values recorded for {candidate.label} in this model"


def _note_interpretation(
    predicate: CompiledPredicate, candidate: FieldCandidate, match: ValueMatch
) -> None:
    if match.is_exact_identity:
        return
    predicate.interpretation_notes.append(
        f"read {match.user_value!r} as {candidate.label} = {match.stored_value!r} "
        f"({match.match_kind.value} match)"
    )


def _was_quoted(condition: BoundCondition, predicate: CompiledPredicate) -> bool:
    """True when the user quoted the value, demanding an exact stored match."""
    span = (condition.source_span or "").strip()
    return len(span) >= 2 and span[0] in "'\"" and span[-1] in "'\""


# ---------------------------------------------------------------------------
# Field reference helpers
# ---------------------------------------------------------------------------


def _field_ref(candidate: FieldCandidate) -> FieldRef:
    return FieldRef(
        field_kind=FieldKind(candidate.field_kind),
        set_name=candidate.set_name,
        field_name=candidate.field_name,
    )


def _concept_for(
    session: Session, source_model_id: int, candidate: FieldCandidate
) -> FieldConcept | None:
    index = get_field_concept_index(session, source_model_id)
    return index.get(candidate.field_kind, candidate.set_name, candidate.field_name)
