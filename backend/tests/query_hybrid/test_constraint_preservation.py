"""Constraint preservation through the pipeline (Task 23 §1).

The defect these guard against: a filtered request ("doors on the second floor")
being answered with the unfiltered class total, because the condition never
survived planning/retrieval as structured data.
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    Facet,
    IntentCondition,
    IntentGroup,
    RetrievalPolicy,
    RetrievalPolicyPlan,
)
from app.llm.validation import validate_policy_plan
from app.query.hybrid.groups.execute import compile_predicate_group
from app.query.hybrid.groups.schemas import (
    GroupPredicate,
    PredicateCondition,
    PredicateGroup,
    PredicateKind,
)
from app.query.semantic.intent_resolution import ResolvedCondition, _compose
from app.shared.types import QueryRoute, QueryScope


def _condition(name="storey_global_id", value=("a", "b"), operator="in", **kw):
    return PredicateCondition(
        field_kind="attribute", field_name=name, operator=operator, value=value, **kw
    )


# ---------------------------------------------------------------------------
# Predicate contract
# ---------------------------------------------------------------------------


def test_compound_predicate_is_queryable_and_constrained():
    p = GroupPredicate(
        kind=PredicateKind.COMPOUND.value,
        ifc_classes=("IfcDoor",),
        filters=PredicateGroup(bool_op="and", conditions=(_condition(),)),
    )
    assert p.queryable
    assert p.is_constrained


def test_bare_class_predicate_is_not_constrained():
    p = GroupPredicate(kind=PredicateKind.ENTITY_CLASS.value, ifc_classes=("IfcDoor",))
    assert not p.is_constrained


def test_signature_distinguishes_different_conditions():
    """A filtered and an unfiltered predicate must never dedupe together."""
    base = GroupPredicate(kind=PredicateKind.COMPOUND.value, ifc_classes=("IfcDoor",))
    filtered = GroupPredicate(
        kind=PredicateKind.COMPOUND.value,
        ifc_classes=("IfcDoor",),
        filters=PredicateGroup(bool_op="and", conditions=(_condition(),)),
    )
    other = GroupPredicate(
        kind=PredicateKind.COMPOUND.value,
        ifc_classes=("IfcDoor",),
        filters=PredicateGroup(bool_op="and", conditions=(_condition(value=("c",)),)),
    )
    sigs = {base.signature(), filtered.signature(), other.signature()}
    assert len(sigs) == 3


# ---------------------------------------------------------------------------
# Compilation into the EXISTING typed SQL filter tree
# ---------------------------------------------------------------------------


def test_conditions_compile_to_typed_filter_group():
    group = PredicateGroup(
        bool_op="and",
        conditions=(
            _condition(),
            _condition(name="name", value="lift", operator="contains"),
        ),
    )
    compiled = compile_predicate_group(group)
    assert compiled.bool_op == "and"
    assert len(compiled.conditions) == 2


def test_nested_or_survives_compilation():
    group = PredicateGroup(
        bool_op="and",
        conditions=(
            _condition(),
            PredicateGroup(
                bool_op="or",
                conditions=(
                    _condition(name="name", value="a", operator="contains"),
                    _condition(name="name", value="b", operator="contains"),
                ),
            ),
        ),
    )
    compiled = compile_predicate_group(group)
    assert compiled.bool_op == "and"
    inner = [c for c in compiled.conditions if hasattr(c, "bool_op")]
    assert len(inner) == 1 and inner[0].bool_op == "or"


def test_negation_uses_an_allowlisted_inverse():
    compiled = compile_predicate_group(
        PredicateGroup(bool_op="and", conditions=(_condition(negated=True),))
    )
    assert compiled.conditions[0].operator.value == "not_in"


def test_uncompilable_operator_raises_rather_than_degrading():
    """An unsupported condition must fail loudly — never quietly widen the query."""
    bad = PredicateCondition(field_kind="attribute", field_name="name", operator="regex", value="x")
    with pytest.raises(ValueError):
        compile_predicate_group(PredicateGroup(bool_op="and", conditions=(bad,)))


def test_negation_without_an_inverse_raises():
    bad = PredicateCondition(
        field_kind="attribute",
        field_name="name",
        operator="contains",
        value="x",
        negated=True,
    )
    with pytest.raises(ValueError):
        compile_predicate_group(PredicateGroup(bool_op="and", conditions=(bad,)))


# ---------------------------------------------------------------------------
# Boolean structure is preserved from the planner's tree
# ---------------------------------------------------------------------------


def _resolved(cid, parent=None, value=("x",)):
    return ResolvedCondition(
        condition_id=cid,
        parent_group_id=parent,
        condition=_condition(value=value),
        required=True,
    )


def test_ungrouped_conditions_combine_with_and():
    composed = _compose([_resolved("c1"), _resolved("c2")], [])
    assert composed.bool_op == "and"
    assert len(composed.conditions) == 2


def test_declared_or_group_is_preserved():
    groups = [IntentGroup(group_id="g1", bool_op="or")]
    composed = _compose([_resolved("c1", "g1"), _resolved("c2", "g1")], groups)
    assert composed.bool_op == "or"
    assert len(composed.conditions) == 2


def test_mixed_and_of_or_group_and_plain_condition():
    groups = [IntentGroup(group_id="g1", bool_op="or")]
    composed = _compose([_resolved("c1", "g1"), _resolved("c2", "g1"), _resolved("c3")], groups)
    assert composed.bool_op == "and"
    assert any(isinstance(c, PredicateGroup) and c.bool_op == "or" for c in composed.conditions)


def test_unresolved_conditions_are_excluded_from_composition():
    unresolved = ResolvedCondition(
        condition_id="c2", parent_group_id=None, condition=None, required=True
    )
    composed = _compose([_resolved("c1"), unresolved], [])
    assert len(composed.conditions) == 1


def test_no_resolved_conditions_yields_no_filters():
    unresolved = ResolvedCondition(
        condition_id="c1", parent_group_id=None, condition=None, required=True
    )
    assert _compose([unresolved], []) is None


# ---------------------------------------------------------------------------
# Planner contract
# ---------------------------------------------------------------------------


def _plan(facet):
    return RetrievalPolicyPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=2,
        facets=[facet],
        retrieval_policy=RetrievalPolicy(sql=facet.needs_exact_structured),
    )


def test_filtered_facet_must_request_structured_retrieval():
    facet = Facet(
        facet_id="f",
        question="doors on the second floor",
        semantic_query="doors",
        needs_exact_structured=False,
        conditions=[
            IntentCondition(
                condition_id="c1",
                concept="containing building level",
                value_concept="the second floor",
            )
        ],
    )
    errors = validate_policy_plan(_plan(facet))
    assert any("cannot be answered without" in e for e in errors)


def test_condition_without_a_value_is_rejected():
    facet = Facet(
        facet_id="f",
        question="q",
        semantic_query="s",
        needs_exact_structured=True,
        conditions=[IntentCondition(condition_id="c1", concept="level")],
    )
    assert any("carries no value" in e for e in validate_policy_plan(_plan(facet)))


def test_condition_referencing_unknown_group_is_rejected():
    facet = Facet(
        facet_id="f",
        question="q",
        semantic_query="s",
        needs_exact_structured=True,
        conditions=[
            IntentCondition(
                condition_id="c1",
                concept="level",
                value_concept="2",
                parent_group_id="nope",
            )
        ],
    )
    assert any("unknown parent_group_id" in e for e in validate_policy_plan(_plan(facet)))


def test_duplicate_condition_ids_are_rejected():
    facet = Facet(
        facet_id="f",
        question="q",
        semantic_query="s",
        needs_exact_structured=True,
        conditions=[
            IntentCondition(condition_id="c1", concept="a", value_concept="1"),
            IntentCondition(condition_id="c1", concept="b", value_concept="2"),
        ],
    )
    assert any("unique condition_id" in e for e in validate_policy_plan(_plan(facet)))


def test_unconstrained_facet_remains_valid():
    """Task 17 behavior is unchanged for questions with no conditions."""
    facet = Facet(
        facet_id="f",
        question="how many doors",
        semantic_query="doors",
        needs_exact_structured=True,
    )
    assert validate_policy_plan(_plan(facet)) == []
