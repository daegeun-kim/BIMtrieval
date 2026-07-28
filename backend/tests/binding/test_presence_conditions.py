"""A presence/absence condition must RESTRICT the result set (Task 24 §2.4, §6).

Offline. These tests exist to disprove one hypothesis: that "which X have Y
recorded" and "which X are missing Y" were executing the same unfiltered
predicate as "how many X", so both reported the class total.

The invariant under test is stated once and applies to every condition kind: a
bound condition either narrows the compiled predicate, or it records an
`UnresolvedCondition` that makes the part non-executable. Producing neither is
what lets a narrower question be answered with a broader set.
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    AnswerPart,
    BoundCondition,
    BoundOperator,
    OutputOperation,
)
from app.query.binding.closure import resolve_closure
from app.query.binding.compile import compile_predicate
from app.query.binding.slate import SlateInputs, build_slate
from app.query.sql.schemas import FilterCondition, FilterGroup, Operator

from .conftest import SYNTHETIC_MODEL_ID


def _slate(question):
    return build_slate(
        session=None,
        inputs=SlateInputs(question=question, source_model_id=SYNTHETIC_MODEL_ID),
    )


def _field_id(slate, field_name, set_name=None):
    return next(
        c.candidate_id
        for c in slate.fields
        if c.field_name == field_name and (set_name is None or c.set_name == set_name)
    )


def _compile_with(slate, ifc_class, conditions):
    subject_id = next(c.candidate_id for c in slate.subjects if c.ifc_class == ifc_class)
    part = AnswerPart(
        part_id="p1",
        request_text=slate.question,
        operation=OutputOperation.COUNT,
        subject_candidate_id=subject_id,
        conditions=conditions,
    )
    closure = resolve_closure(slate, subject_id, part.union_subject_candidate_ids)
    return compile_predicate(None, part, closure, slate, SYNTHETIC_MODEL_ID)


def _flatten(node):
    if node is None:
        return []
    if isinstance(node, FilterCondition):
        return [node]
    return [c for child in node.conditions for c in _flatten(child)]


def _presence_part(slate, operator):
    return _compile_with(
        slate,
        "IfcWall",
        [
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "FireRating", "Pset_WallCommon"),
                operator=operator,
                source_span="fire rating",
            )
        ],
    )


# ---------------------------------------------------------------------------
# The condition must reach the predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bound, expected",
    [
        (BoundOperator.IS_PRESENT, Operator.IS_PRESENT),
        (BoundOperator.IS_MISSING, Operator.IS_MISSING),
    ],
)
def test_a_presence_condition_compiles_to_a_real_predicate(slate_env, bound, expected):
    predicate = _presence_part(_slate("which walls have a fire rating recorded?"), bound)

    conditions = _flatten(predicate.filters)
    assert len(conditions) == 1, "the condition must not be discarded"
    assert conditions[0].operator is expected
    assert conditions[0].field.field_name == "FireRating"
    assert predicate.executable


def test_presence_and_absence_are_different_predicates(slate_env):
    """If both compiled to the same thing, "recorded" and "missing" would report
    identical counts — which is the observable symptom of the dropped condition."""
    slate = _slate("which walls have a fire rating recorded?")
    present = _flatten(_presence_part(slate, BoundOperator.IS_PRESENT).filters)
    missing = _flatten(_presence_part(slate, BoundOperator.IS_MISSING).filters)

    assert present[0].operator is not missing[0].operator
    assert present[0].field == missing[0].field


def test_a_presence_condition_is_reported_in_the_interpretation(slate_env):
    """The user must be able to see that presence, not a value, was applied."""
    predicate = _presence_part(
        _slate("which walls have a fire rating recorded?"), BoundOperator.IS_PRESENT
    )
    assert any("recorded" in note for note in predicate.interpretation_notes)


# ---------------------------------------------------------------------------
# The general invariant: no condition may vanish
# ---------------------------------------------------------------------------


def test_an_uncompilable_condition_blocks_execution_rather_than_widening(slate_env):
    """A condition naming a field that is not on the slate must not be ignored.

    Without this the part would execute unfiltered and report the whole class,
    which is a broader answer than the one asked for."""
    slate = _slate("which walls have a fire rating recorded?")
    predicate = _compile_with(
        slate,
        "IfcWall",
        [
            BoundCondition(
                condition_id="c1",
                candidate_id="prop:NoSuchSet.NoSuchField",
                operator=BoundOperator.IS_PRESENT,
                source_span="fire rating",
            )
        ],
    )
    assert not predicate.executable
    assert predicate.unresolved
    assert predicate.unresolved[0].condition_id == "c1"


# ---------------------------------------------------------------------------
# Typed vocabulary shape
# ---------------------------------------------------------------------------


def test_a_valueless_operator_rejects_a_value():
    from pydantic import ValidationError

    from app.query.sql.schemas import FieldKind, FieldRef

    field = FieldRef(field_kind=FieldKind.PROPERTY, set_name="Pset_WallCommon", field_name="FireRating")
    FilterCondition(field=field, operator=Operator.IS_PRESENT)  # no value: fine
    with pytest.raises(ValidationError):
        FilterCondition(field=field, operator=Operator.IS_PRESENT, value="EI60")


def test_a_comparison_operator_still_requires_a_value():
    from pydantic import ValidationError

    from app.query.sql.schemas import FieldKind, FieldRef

    field = FieldRef(field_kind=FieldKind.PROPERTY, set_name="Pset_WallCommon", field_name="FireRating")
    with pytest.raises(ValidationError):
        FilterCondition(field=field, operator=Operator.CASE_INSENSITIVE_EXACT)
