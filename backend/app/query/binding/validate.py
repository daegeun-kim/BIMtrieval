"""Deterministic binding validation (Task 24 §3.3).

Runs after LLM call 1 and before ANY authoritative query executes. Every check
here is a structural invariant, not a heuristic, and every failure is final:

    "An invalid binding returns a concise clarification or typed unavailable
     result. It must not trigger a second planning call, silently broaden the
     scope, or fall back to all entities of a nearby class."  (§3.3)

There is therefore no repair path in this module and no way to reach the model
again. That is the point — the previous architecture's repair call is one of the
things Task 24 removes (§10.1: no format-repair, correction, verifier, or retry
LLM call).

Validation is reported per answer part so a partially valid plan can still
answer the parts that are sound while reporting the rest honestly (§6 partial).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.schemas import AnswerPart, BindingPlan, BoundCondition, BoundOperator, ScopeKind
from app.query.binding.closure import SubjectClosure, resolve_closure
from app.query.binding.lexical import normalize_text
from app.query.binding.schemas import CandidateSlate, FieldCandidate, SpatialCandidate
from app.query.semantic.units import decide_unit

__all__ = [
    "ValidationIssue",
    "PartValidation",
    "BindingValidation",
    "validate_binding",
]


#: Operators that need no value at all.
_VALUELESS_OPERATORS = frozenset({BoundOperator.IS_PRESENT, BoundOperator.IS_MISSING})
#: Operators requiring a list value.
_LIST_OPERATORS = frozenset({BoundOperator.ONE_OF, BoundOperator.BETWEEN})
#: Operators that only make sense on an ordered (numeric) field.
_NUMERIC_OPERATORS = frozenset(
    {
        BoundOperator.GREATER_THAN,
        BoundOperator.GREATER_OR_EQUAL,
        BoundOperator.LESS_THAN,
        BoundOperator.LESS_OR_EQUAL,
        BoundOperator.BETWEEN,
    }
)
#: Operators that only make sense on text.
_TEXT_OPERATORS = frozenset({BoundOperator.CONTAINS, BoundOperator.STARTS_WITH})

#: A candidate advertises its capabilities in the typed SQL vocabulary
#: (`gt`, `lte`, ...), while a binding speaks the `BoundOperator` vocabulary
#: (`greater_than`, `less_or_equal`, ...). The support check below must compare
#: like with like: without this translation every ordered comparison looks
#: unsupported, which makes numeric filtering unreachable no matter how well the
#: field's units resolve (task27 §4.3).
_SQL_OPERATOR_NAMES: dict[BoundOperator, tuple[str, ...]] = {
    BoundOperator.GREATER_THAN: ("gt",),
    BoundOperator.GREATER_OR_EQUAL: ("gte",),
    BoundOperator.LESS_THAN: ("lt",),
    BoundOperator.LESS_OR_EQUAL: ("lte",),
    BoundOperator.BETWEEN: ("between",),
    BoundOperator.CONTAINS: ("contains",),
    BoundOperator.STARTS_WITH: ("starts_with",),
}


def _operator_is_supported(operator: BoundOperator, candidate: FieldCandidate) -> bool:
    names = (operator.value, *_SQL_OPERATOR_NAMES.get(operator, ()))
    return any(name in candidate.operators for name in names)


#: Operations whose answer is an exact figure. Such a figure may never be based
#: on a bounded semantic candidate count (§3.3 final check).
_EXACT_OPERATIONS = frozenset({"count", "existence", "aggregate", "extremum", "group_distribution"})

#: Operations that legitimately carry qualitative ranking text.
_QUALITATIVE_OPERATIONS = frozenset({"description", "comparison"})

#: Boolean structure bound, matching the existing typed SQL limits so a binding
#: can never encode logic the compiler cannot express.
_MAX_CONDITIONS = 20
_MAX_BOOL_GROUPS = 8


@dataclass(frozen=True)
class ValidationIssue:
    """One reason a binding cannot execute as written."""

    code: str
    detail: str
    part_id: str | None = None

    def __str__(self) -> str:  # pragma: no cover - diagnostics only
        return f"[{self.code}] {self.detail}"


@dataclass
class PartValidation:
    part: AnswerPart
    closure: SubjectClosure
    issues: list[ValidationIssue] = field(default_factory=list)
    #: Material modifier spans this part accounts for.
    covered_spans: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues and self.closure.resolved


@dataclass
class BindingValidation:
    plan: BindingPlan
    parts: list[PartValidation] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues and all(p.valid for p in self.parts)

    @property
    def valid_parts(self) -> list[PartValidation]:
        return [p for p in self.parts if p.valid]

    def all_issues(self) -> list[ValidationIssue]:
        return list(self.issues) + [i for p in self.parts for i in p.issues]

    def clarification(self) -> str | None:
        """A concise, user-facing reason, or None when the binding is usable."""
        issues = self.all_issues()
        if not issues:
            return None
        return issues[0].detail


def validate_binding(plan: BindingPlan, slate: CandidateSlate) -> BindingValidation:
    """Validate a binding plan against the slate it was produced from (§3.3)."""
    result = BindingValidation(plan=plan)

    if plan.needs_clarification:
        # A declared clarification is a valid outcome, not an error.
        return result

    if not plan.answer_parts:
        result.issues.append(
            ValidationIssue("no_answer_parts", "the binding contains no answer parts")
        )
        return result

    seen_part_ids: set[str] = set()
    for part in plan.answer_parts:
        if part.part_id in seen_part_ids:
            result.issues.append(
                ValidationIssue("duplicate_part_id", f"part id {part.part_id!r} is repeated")
            )
        seen_part_ids.add(part.part_id)
        result.parts.append(_validate_part(part, slate))

    _validate_visual_primacy(plan, result)
    # Task 25: constraint coverage is no longer approximated by token/modifier
    # heuristics here. It is enforced by the typed constraint ledger in
    # `ledger_validation.validate_ledger_coverage`, called separately by the
    # pipeline. The former `_validate_modifier_coverage` /
    # `_validate_question_coverage` machinery — and the output-field leak that let
    # a reported field "explain" a filter word — is retired (§3.2).
    return result


# ---------------------------------------------------------------------------
# Per-part validation
# ---------------------------------------------------------------------------


def _validate_part(part: AnswerPart, slate: CandidateSlate) -> PartValidation:
    closure = resolve_closure(slate, part.subject_candidate_id, part.union_subject_candidate_ids)
    validation = PartValidation(part=part, closure=closure)

    if not closure.resolved:
        validation.issues.append(
            ValidationIssue("unresolved_subject", closure.unresolved_reason or "", part.part_id)
        )

    _check_scope(part, slate, validation)
    _check_conditions(part, slate, validation)
    _check_operation_shape(part, slate, validation)
    _check_relationship(part, slate, validation)
    return validation


def _check_scope(part: AnswerPart, slate: CandidateSlate, v: PartValidation) -> None:
    """Scope must exist, belong to this request, and be the right typed kind."""
    if part.scope_kind is ScopeKind.SPATIAL_CANDIDATE:
        if not part.scope_candidate_id:
            v.issues.append(
                ValidationIssue(
                    "missing_scope_candidate",
                    "a spatial scope was declared without naming a spatial candidate",
                    part.part_id,
                )
            )
            return
        candidate = slate.spatial_candidate(part.scope_candidate_id)
        if candidate is None:
            v.issues.append(
                ValidationIssue(
                    "unknown_scope_candidate",
                    f"spatial candidate {part.scope_candidate_id!r} is not in this request's slate",
                    part.part_id,
                )
            )
        return

    # The non-spatial scopes must actually be offered by this request, so a
    # previous-result or selection scope cannot be claimed when none exists.
    required = {
        ScopeKind.SELECTED_OBJECTS: "selection",
        ScopeKind.PREVIOUS_RESULT: "previous_result",
    }.get(part.scope_kind)
    if required and not any(c.kind.value == required for c in slate.spatial):
        v.issues.append(
            ValidationIssue(
                "scope_unavailable",
                f"the binding referenced the {required.replace('_', ' ')} scope, "
                "but this request has none",
                part.part_id,
            )
        )


def _check_conditions(part: AnswerPart, slate: CandidateSlate, v: PartValidation) -> None:
    if len(part.conditions) > _MAX_CONDITIONS:
        v.issues.append(
            ValidationIssue(
                "too_many_conditions",
                f"{len(part.conditions)} conditions exceeds the supported maximum "
                f"of {_MAX_CONDITIONS}",
                part.part_id,
            )
        )
    groups = {c.bool_group for c in part.conditions if c.bool_group}
    if len(groups) > _MAX_BOOL_GROUPS:
        v.issues.append(
            ValidationIssue(
                "boolean_structure_too_complex",
                f"{len(groups)} boolean groups exceeds the supported maximum of {_MAX_BOOL_GROUPS}",
                part.part_id,
            )
        )

    subject_classes = set(v.closure.ifc_classes)
    for condition in part.conditions:
        _check_condition(condition, part, slate, subject_classes, v)


def _check_condition(
    condition: BoundCondition,
    part: AnswerPart,
    slate: CandidateSlate,
    subject_classes: set[str],
    v: PartValidation,
) -> None:
    # 1. Provenance. An invented condition is rejected outright (§2.4).
    if not condition.source_span and not condition.inherited_from_scope:
        v.issues.append(
            ValidationIssue(
                "invented_condition",
                f"condition {condition.condition_id!r} cites neither a span of the question "
                "nor an inherited scope, so it was not something the user asked for",
                part.part_id,
            )
        )
        return
    if condition.source_span and not _span_is_in_question(condition.source_span, slate.question):
        v.issues.append(
            ValidationIssue(
                "source_span_not_in_question",
                f"condition {condition.condition_id!r} cites {condition.source_span!r}, "
                "which does not appear in the question",
                part.part_id,
            )
        )
        return
    if condition.inherited_from_scope and not any(
        c.kind.value == "previous_result" for c in slate.spatial
    ):
        v.issues.append(
            ValidationIssue(
                "no_inheritable_scope",
                f"condition {condition.condition_id!r} claims an inherited scope, "
                "but this request has no previous result to inherit from",
                part.part_id,
            )
        )
        return

    # 2. The candidate must exist in this request's slate.
    field_candidate = slate.field_candidate(condition.candidate_id)
    spatial_candidate = slate.spatial_candidate(condition.candidate_id)
    if field_candidate is None and spatial_candidate is None:
        # A SUBJECT id here is a specific, recurring mistake — the model treats
        # "doors in this building" as `building = <subject>` — so name it
        # precisely rather than reporting a generic unknown id. The id IS in the
        # slate; it is the wrong KIND of candidate.
        if slate.subject(condition.candidate_id) is not None:
            v.issues.append(
                ValidationIssue(
                    "subject_used_as_condition",
                    f"condition {condition.condition_id!r} constrains on "
                    f"{condition.candidate_id!r}, which is a subject rather than a field or "
                    "spatial candidate; a subject is what the answer returns, not a filter",
                    part.part_id,
                )
            )
            return
        v.issues.append(
            ValidationIssue(
                "unknown_condition_candidate",
                f"condition {condition.condition_id!r} references "
                f"{condition.candidate_id!r}, which is not in this request's slate",
                part.part_id,
            )
        )
        return

    if spatial_candidate is not None:
        _check_spatial_condition(condition, spatial_candidate, part, v)
        return

    _check_field_condition(condition, field_candidate, part, subject_classes, v)


def _check_spatial_condition(
    condition: BoundCondition,
    candidate: SpatialCandidate,
    part: AnswerPart,
    v: PartValidation,
) -> None:
    """A SCOPE selection may never be used as a narrowing condition (§1.3).

    This is the check that stops a phrase naming the model as a whole from
    becoming a predicate that then fails to resolve.
    """
    if candidate.is_scope_selection:
        v.issues.append(
            ValidationIssue(
                "scope_used_as_condition",
                f"{candidate.label!r} selects what to look at and cannot be used as a "
                "condition that narrows the result",
                part.part_id,
            )
        )


def _check_field_condition(
    condition: BoundCondition,
    candidate: FieldCandidate,
    part: AnswerPart,
    subject_classes: set[str],
    v: PartValidation,
) -> None:
    # 3. The field must apply to the chosen subject family.
    if (
        candidate.applicable_classes
        and subject_classes
        and not (set(candidate.applicable_classes) & subject_classes)
    ):
        v.issues.append(
            ValidationIssue(
                "field_not_applicable",
                f"{candidate.label} is not recorded on "
                + ", ".join(sorted(subject_classes))
                + " in this model",
                part.part_id,
            )
        )
        return

    # 4. Operator/data-type compatibility.
    if condition.operator in _NUMERIC_OPERATORS and candidate.data_type != "number":
        v.issues.append(
            ValidationIssue(
                "operator_type_mismatch",
                f"{condition.operator.value} cannot be applied to {candidate.label}, "
                f"which holds {candidate.data_type} values",
                part.part_id,
            )
        )
        return
    if condition.operator in _TEXT_OPERATORS and candidate.data_type == "number":
        v.issues.append(
            ValidationIssue(
                "operator_type_mismatch",
                f"{condition.operator.value} cannot be applied to the numeric "
                f"field {candidate.label}",
                part.part_id,
            )
        )
        return
    if not _operator_is_supported(condition.operator, candidate) and condition.operator not in (
        _VALUELESS_OPERATORS
        | {BoundOperator.EQUALS, BoundOperator.NOT_EQUALS, BoundOperator.ONE_OF}
    ):
        v.issues.append(
            ValidationIssue(
                "operator_unsupported",
                f"{candidate.label} does not support {condition.operator.value}",
                part.part_id,
            )
        )
        return

    # 5. Value shape.
    if condition.operator in _VALUELESS_OPERATORS:
        return
    if condition.operator in _LIST_OPERATORS:
        expected = 2 if condition.operator is BoundOperator.BETWEEN else None
        if not condition.value_list or (expected and len(condition.value_list) != expected):
            v.issues.append(
                ValidationIssue(
                    "bad_value_shape",
                    f"{condition.operator.value} on {candidate.label} requires "
                    + ("two bounds" if expected else "a list of values"),
                    part.part_id,
                )
            )
        return
    if condition.value_text is None:
        v.issues.append(
            ValidationIssue(
                "missing_value",
                f"{condition.operator.value} on {candidate.label} requires a value",
                part.part_id,
            )
        )
        return

    # 6. The comparison must be meaningful in the unit the model actually uses.
    #    Nothing is converted (task27 §4.3), so a request in a different unit —
    #    or against a field whose values are not all on one scale — is refused
    #    here rather than executed and silently mis-scaled.
    decision = decide_unit(
        requested_unit=condition.unit,
        effective_unit=candidate.unit_symbol,
        unit_state=candidate.unit_state,
        measure_type=candidate.measure_type,
        label=candidate.label,
        unit_limitation=candidate.unit_limitation,
    )
    if not decision.ok:
        v.issues.append(
            ValidationIssue(
                "unit_not_available",
                decision.reason
                or f"{candidate.label} cannot be compared against a value in {condition.unit}",
                part.part_id,
            )
        )


def _check_operation_shape(part: AnswerPart, slate: CandidateSlate, v: PartValidation) -> None:
    """The operation must be compatible with the subject and its own inputs."""
    # An exact figure may never rest on bounded semantic evidence (§3.3).
    if part.operation.value in _EXACT_OPERATIONS and part.semantic_ranking_text:
        v.issues.append(
            ValidationIssue(
                "exact_operation_from_semantic_evidence",
                f"{part.operation.value} produces an exact figure and cannot be based on "
                "bounded semantic ranking",
                part.part_id,
            )
        )
    if part.semantic_ranking_text and part.operation.value not in _QUALITATIVE_OPERATIONS:
        v.issues.append(
            ValidationIssue(
                "semantic_ranking_on_structured_operation",
                f"{part.operation.value} is a structured operation and must not carry "
                "semantic ranking text",
                part.part_id,
            )
        )
    for candidate_id in part.output_field_candidate_ids:
        if slate.field_candidate(candidate_id) is None:
            v.issues.append(
                ValidationIssue(
                    "unknown_output_field",
                    f"output field {candidate_id!r} is not in this request's slate",
                    part.part_id,
                )
            )


def _check_relationship(part: AnswerPart, slate: CandidateSlate, v: PartValidation) -> None:
    """Relationship seed and endpoint semantics must be executable (§3.3)."""
    if part.operation.value == "relationship":
        if not part.relationship_candidate_id:
            v.issues.append(
                ValidationIssue(
                    "missing_relationship_binding",
                    "a relationship question needs a relationship candidate",
                    part.part_id,
                )
            )
            return
    if not part.relationship_candidate_id:
        return

    candidate = slate.relationship(part.relationship_candidate_id)
    if candidate is None:
        v.issues.append(
            ValidationIssue(
                "unknown_relationship_candidate",
                f"relationship candidate {part.relationship_candidate_id!r} is not in "
                "this request's slate",
                part.part_id,
            )
        )
        return
    if not candidate.available:
        # Not an error to ASK — but it must produce typed unavailable evidence
        # rather than a fabricated connection (§5.4).
        v.issues.append(
            ValidationIssue(
                "relationship_unavailable",
                f"this model records no {candidate.ifc_class} relationships, so the "
                "requested connection cannot be established from it",
                part.part_id,
            )
        )
    if (
        part.endpoint_subject_candidate_id
        and slate.subject(part.endpoint_subject_candidate_id) is None
    ):
        v.issues.append(
            ValidationIssue(
                "unknown_endpoint_subject",
                f"endpoint subject {part.endpoint_subject_candidate_id!r} is not in "
                "this request's slate",
                part.part_id,
            )
        )


# ---------------------------------------------------------------------------
# Plan-level checks
# ---------------------------------------------------------------------------


def _validate_visual_primacy(plan: BindingPlan, result: BindingValidation) -> None:
    """§9: a multi-part question needs ONE explicit primary visual part."""
    primary = [p for p in plan.answer_parts if p.is_primary_visual]
    if len(plan.answer_parts) > 1 and len(primary) > 1:
        result.issues.append(
            ValidationIssue(
                "multiple_primary_visual_parts",
                "more than one answer part was marked as the primary visual result",
            )
        )


# ---------------------------------------------------------------------------
# Retired: Task 24 token/modifier coverage
# ---------------------------------------------------------------------------
#
# `_validate_modifier_coverage`, `_validate_question_coverage`,
# `_qualifying_unaccounted_tokens`, `_unaccounted_tokens`, `_span_is_covered`
# and the `_UNREMARKABLE_TOKENS` exemption set lived here. Task 25 §3.2 replaced
# them with the typed constraint ledger, which the pipeline validates separately
# via `ledger_validation.validate_ledger_coverage`, and `validate_binding` has
# not called any of them since.
#
# Removed in Task 37 rather than left dormant: `silently_dropped_modifiers` was
# still being reported by the dev diagnostics endpoint, where a permanently
# empty list reads as "nothing was dropped" instead of "this is no longer
# measured here". Dead code that reports is worse than dead code that sits.


def _span_is_in_question(span: str, question: str) -> bool:
    """Provenance check: the cited span must really occur in the question.

    Compared on normalized text so ordinary case/punctuation differences in the
    model's copy do not read as fabrication, while an entirely invented span
    still fails.
    """
    normalized_span = normalize_text(span)
    return bool(normalized_span) and normalized_span in normalize_text(question)
