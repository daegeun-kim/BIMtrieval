"""Constraint ledger and ledger-coverage validation (task25 §3.2, §9.2).

The central test here is `test_an_output_field_cannot_discharge_a_filter_word`,
which reproduces the exact Task 24 defect and proves it is now unrepresentable
rather than merely detected.

Cases are written over unrelated and paraphrased wording, not the questions in
`specs/test_query.md`, so passing them means the invariant holds rather than
that a suite was fitted.
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    AnswerPart,
    BindingPlan,
    BoundCondition,
    LedgerDisposition,
    LedgerDispositionKind,
    OutputOperation,
)
from app.query.binding.ledger import LedgerRole, build_ledger
from app.query.binding.ledger_validation import validate_ledger_coverage


def _part(part_id="p1", conditions=(), outputs=(), relationship=None):
    return AnswerPart(
        part_id=part_id,
        request_text="request",
        operation=OutputOperation.COUNT,
        subject_candidate_id="cls:IfcWall",
        conditions=list(conditions),
        output_field_candidate_ids=list(outputs),
        relationship_candidate_id=relationship,
    )


def _condition(condition_id="c1", candidate_id="prop:Pset_WallCommon.IsExternal", span=None):
    return BoundCondition(
        condition_id=condition_id,
        candidate_id=candidate_id,
        value_text="true",
        source_span=span,
    )


def _plan(parts=(), dispositions=()):
    return BindingPlan(answer_parts=list(parts), ledger_dispositions=list(dispositions))


def _item_named(ledger, text):
    item = next((i for i in ledger.items if i.text == text), None)
    assert item is not None, f"no ledger item {text!r} in {[i.text for i in ledger.items]}"
    return item


# ---------------------------------------------------------------------------
# Ledger construction
# ---------------------------------------------------------------------------


def test_a_qualifier_becomes_its_own_required_condition_item():
    """ "external" must exist as a separate obligation from "external walls"."""
    ledger = build_ledger("how many external walls are there?")

    qualifier = _item_named(ledger, "external")

    assert qualifier.role is LedgerRole.CONDITION
    assert qualifier.required is True


@pytest.mark.parametrize(
    "question,qualifier,head",
    [
        ("count the insulated pipes", "insulated", "insulated pipes"),
        ("how many acoustic ceilings?", "acoustic", "acoustic ceilings"),
        ("list the structural columns", "structural", "structural columns"),
    ],
)
def test_qualifiers_are_extracted_across_unrelated_vocabulary(question, qualifier, head):
    """The rule is positional, not a list of known adjectives."""
    ledger = build_ledger(question)

    assert _item_named(ledger, qualifier).role is LedgerRole.CONDITION
    assert _item_named(ledger, head).role is LedgerRole.SUBJECT


@pytest.mark.parametrize(
    "question,constraint",
    [
        ("hoeveel dragende wanden zijn er?", "dragende"),
        ("hur många bärande väggar finns det?", "bärande"),
        ("combien de murs porteurs y a-t-il ?", "porteurs"),
    ],
)
def test_a_constraint_word_survives_in_any_language(question, constraint):
    """The safety property, which holds regardless of language.

    Head/qualifier GROUPING is English-specific — the structural-word list only
    knows English function words, so a non-English question yields one long run
    and every word becomes its own required item. That degrades in the SAFE
    direction: the binder is asked to account for more than necessary, never
    less, so a real constraint still cannot be silently dropped. Over-requiring
    costs a disposition; under-requiring costs a wrong answer.
    """
    ledger = build_ledger(question)
    texts = {i.text for i in ledger.required_items()}

    assert constraint in texts


def test_a_compound_question_keeps_every_subject():
    ledger = build_ledger("how many beams and how many railings?")
    subjects = {i.text for i in ledger.items_with_role(LedgerRole.SUBJECT)}

    assert subjects == {"beams", "railings"}


def test_a_scope_reference_is_tracked_but_not_required():
    """ "in this building" selects where to look; it restricts nothing.

    Marking it required would push the binder into inventing a building filter.
    """
    ledger = build_ledger("how many sinks are in this building?")
    scope = next(i for i in ledger.items if "building" in i.text)

    assert scope.role is LedgerRole.SCOPE
    assert scope.required is False


def test_a_floor_reference_is_a_required_scope():
    ledger = build_ledger("how many lamps on the third floor?")
    floor = next(i for i in ledger.items if i.span_kind == "floor_reference")

    assert floor.role is LedgerRole.SCOPE
    assert floor.required is True


def test_quoted_values_and_comparisons_become_condition_items():
    ledger = build_ledger('rooms named "Office 12" with area greater than 30')
    kinds = {i.span_kind for i in ledger.items if i.span_kind}

    assert "quoted_value" in kinds
    assert any(i.role is LedgerRole.CONDITION for i in ledger.items)


def test_inherited_scope_is_a_typed_item_not_a_word():
    ledger = build_ledger("how many of those are external?", previous_scope=object())
    inherited = next(i for i in ledger.items if i.source.value == "inherited_scope")

    assert inherited.role is LedgerRole.SCOPE


def test_structural_words_never_become_obligations():
    """A domain noun in the stopword list would silently drop a real constraint."""
    ledger = build_ledger("how many are there in total?")

    assert ledger.required_items() == []


def test_item_ids_are_unique():
    ledger = build_ledger("how many external fire rated walls on the second floor?")
    ids = [i.item_id for i in ledger.items]

    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# The Task 24 defect
# ---------------------------------------------------------------------------


def test_an_output_field_cannot_discharge_a_filter_word():
    """THE regression test for the Task 24 defect.

    Binding: subject IfcWall, NO conditions, and IsExternal listed as an output
    field. Task 24 accepted this and counted every wall in the model, reporting
    it as an exact answer to "how many external walls?".

    Here the ledger item for "external" has role `condition`, and `bound_output`
    is not an acceptable discharge for that role, so the binding is rejected.
    """
    ledger = build_ledger("how many external walls are there?")
    external = _item_named(ledger, "external")
    walls = _item_named(ledger, "external walls")

    plan = _plan(
        parts=[_part(outputs=["prop:Pset_WallCommon.IsExternal"])],
        dispositions=[
            LedgerDisposition(
                item_id=walls.item_id,
                disposition=LedgerDispositionKind.BOUND_SUBJECT,
                part_id="p1",
                semantic_id="cls:IfcWall",
            ),
            LedgerDisposition(
                item_id=external.item_id,
                disposition=LedgerDispositionKind.BOUND_OUTPUT,
                part_id="p1",
                semantic_id="prop:Pset_WallCommon.IsExternal",
            ),
        ],
    )

    coverage = validate_ledger_coverage(plan, ledger)

    assert coverage.ok is False
    assert any("external" in f and "bound_output" in f for f in coverage.failures())


def test_the_same_question_passes_when_the_qualifier_is_actually_filtered():
    """The positive half: filtering on IsExternal is accepted."""
    ledger = build_ledger("how many external walls are there?")
    external = _item_named(ledger, "external")

    plan = _plan(
        parts=[_part(conditions=[_condition(span="external")])],
        dispositions=[
            LedgerDisposition(
                item_id=item.item_id,
                disposition=(
                    LedgerDispositionKind.BOUND_CONDITION
                    if item.item_id == external.item_id
                    else LedgerDispositionKind.BOUND_SUBJECT
                ),
                part_id="p1",
                semantic_id=(
                    "prop:Pset_WallCommon.IsExternal"
                    if item.item_id == external.item_id
                    else "cls:IfcWall"
                ),
            )
            for item in ledger.required_items()
        ],
    )

    assert validate_ledger_coverage(plan, ledger).ok is True


def test_a_dropped_qualifier_is_caught():
    """The "parking spaces" fabrication shape: subject bound, qualifier ignored."""
    ledger = build_ledger("how many parking spaces are there?")
    parking = _item_named(ledger, "parking")
    spaces = _item_named(ledger, "parking spaces")

    plan = _plan(
        parts=[_part()],
        dispositions=[
            LedgerDisposition(
                item_id=spaces.item_id,
                disposition=LedgerDispositionKind.BOUND_SUBJECT,
                part_id="p1",
            )
        ],
    )

    coverage = validate_ledger_coverage(plan, ledger)

    assert coverage.ok is False
    assert any(parking.text in f for f in coverage.undisposed_texts())


def test_a_claimed_condition_must_actually_exist_in_the_part():
    """`bound_condition` cannot be a word the model emits to pass the check."""
    ledger = build_ledger("how many insulated pipes?")
    insulated = _item_named(ledger, "insulated")
    pipes = _item_named(ledger, "insulated pipes")

    plan = _plan(
        parts=[_part(conditions=[])],  # claims a condition it does not have
        dispositions=[
            LedgerDisposition(
                item_id=pipes.item_id,
                disposition=LedgerDispositionKind.BOUND_SUBJECT,
                part_id="p1",
            ),
            LedgerDisposition(
                item_id=insulated.item_id,
                disposition=LedgerDispositionKind.BOUND_CONDITION,
                part_id="p1",
            ),
        ],
    )

    coverage = validate_ledger_coverage(plan, ledger)

    assert coverage.ok is False
    assert any("has no conditions" in f for f in coverage.unsupported)


def test_a_qualifier_may_legitimately_be_part_of_the_subject():
    """ "curtain walls" selects IfcCurtainWall — that is binding, not dropping."""
    ledger = build_ledger("how many curtain walls?")

    # Both "curtain" and "walls" are satisfied by the one subject choice, which
    # is what `bound_subject` means for a condition-role item.
    plan = _plan(
        parts=[_part()],
        dispositions=[
            LedgerDisposition(
                item_id=item.item_id,
                disposition=LedgerDispositionKind.BOUND_SUBJECT,
                part_id="p1",
                semantic_id="cls:IfcCurtainWall",
            )
            for item in ledger.required_items()
        ],
    )

    assert validate_ledger_coverage(plan, ledger).ok is True


def test_an_invented_filter_is_rejected():
    """A condition citing neither a ledger item nor a real span narrows silently."""
    ledger = build_ledger("how many doors?")
    doors = _item_named(ledger, "doors")

    plan = _plan(
        parts=[_part(conditions=[_condition(condition_id="c9", span="fire rated")])],
        dispositions=[
            LedgerDisposition(
                item_id=doors.item_id,
                disposition=LedgerDispositionKind.BOUND_SUBJECT,
                part_id="p1",
            )
        ],
    )

    coverage = validate_ledger_coverage(plan, ledger)

    assert coverage.ok is False
    assert coverage.invented


def test_an_honest_unavailable_is_accepted_and_not_recoverable():
    """§4: never retry a proven absence — retrying invites fabrication."""
    ledger = build_ledger("what is the acoustic rating of the walls?")
    item = _item_named(ledger, "acoustic")

    plan = _plan(
        parts=[_part()],
        dispositions=[
            LedgerDisposition(
                item_id=d.item_id,
                disposition=(
                    LedgerDispositionKind.UNAVAILABLE
                    if d.item_id == item.item_id
                    else LedgerDispositionKind.BOUND_SUBJECT
                ),
                part_id="p1",
                note="this model does not expose acoustic ratings",
            )
            for d in ledger.required_items()
        ],
    )

    coverage = validate_ledger_coverage(plan, ledger)

    assert coverage.ok is True
    assert coverage.declared_failures


def test_redundancy_must_cite_a_real_other_item():
    ledger = build_ledger("how many walls?")
    walls = _item_named(ledger, "walls")

    plan = _plan(
        parts=[_part()],
        dispositions=[
            LedgerDisposition(
                item_id=walls.item_id,
                disposition=LedgerDispositionKind.REDUNDANT_WITH,
                redundant_with_item_id="L999",
            )
        ],
    )

    coverage = validate_ledger_coverage(plan, ledger)

    assert coverage.ok is False
