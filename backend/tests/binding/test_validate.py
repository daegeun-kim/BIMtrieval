"""Binding validation + IFC semantic closure (Task 24 §3, §13.2).

Offline against the synthetic model. The binding plans here are constructed
directly — no LLM is called, which is exactly how §13.1 wants this boundary
tested ("LLM binding OR deterministic binding fixture").

The recurring theme: an invalid binding must produce a typed refusal, and must
NEVER silently broaden into a query the user did not ask for.
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    AnswerPart,
    BindingPlan,
    BoundCondition,
    BoundOperator,
    OutputOperation,
    ScopeKind,
)
from app.query.binding.closure import resolve_closure
from app.query.binding.slate import SlateInputs, build_slate
from app.query.binding.validate import validate_binding

from .conftest import SYNTHETIC_MODEL_ID


def _slate(question, **kw):
    return build_slate(
        session=None,
        inputs=SlateInputs(question=question, source_model_id=SYNTHETIC_MODEL_ID, **kw),
    )


def _subject_id(slate, ifc_class):
    return next(c.candidate_id for c in slate.subjects if c.ifc_class == ifc_class)


def _field_id(slate, field_name):
    return next(c.candidate_id for c in slate.fields if c.field_name == field_name)


def _part(slate, ifc_class, **kw):
    kw.setdefault("part_id", "p1")
    kw.setdefault("request_text", slate.question)
    kw.setdefault("operation", OutputOperation.COUNT)
    return AnswerPart(subject_candidate_id=_subject_id(slate, ifc_class), **kw)


def _plan(*parts) -> BindingPlan:
    return BindingPlan(answer_parts=list(parts))


def _codes(validation) -> set[str]:
    return {i.code for i in validation.all_issues()}


# ---------------------------------------------------------------------------
# Closure (§3.1, §3.2)
# ---------------------------------------------------------------------------


def test_closure_expands_a_superclass_to_its_present_subtypes(slate_env):
    slate = _slate("how many walls are there?")
    closure = resolve_closure(slate, _subject_id(slate, "IfcWall"))
    assert set(closure.ifc_classes) == {"IfcWall", "IfcWallStandardCase"}
    assert closure.executable


def test_closure_of_an_occurrence_excludes_a_co_present_type_definition(slate_env):
    slate = _slate("how many doors are there?")
    closure = resolve_closure(slate, _subject_id(slate, "IfcDoor"))
    assert closure.ifc_classes == ("IfcDoor",)


def test_closure_refuses_a_type_definition_as_an_object_result(slate_env):
    """§3.2: a requested occurrence cannot silently become a type definition."""
    slate = _slate("how many door styles are there?")
    style_id = _subject_id(slate, "IfcDoorStyle")
    closure = resolve_closure(slate, style_id, require_result_kind=True)
    assert not closure.resolved
    assert "type_definition" in (closure.unresolved_reason or "")


def test_closure_refuses_to_mix_subjects_of_different_kinds(slate_env):
    slate = _slate("how many doors and spaces are there?")
    closure = resolve_closure(
        slate,
        _subject_id(slate, "IfcDoor"),
        [_subject_id(slate, "IfcSpace")],
    )
    assert not closure.resolved
    assert "different kinds" in (closure.unresolved_reason or "")


def test_closure_of_an_absent_concept_is_zero_not_unresolved(slate_env):
    """§6: 'zero is not unavailable'. An absent concept was identified
    correctly, so it is an answerable zero — not a failure."""
    slate = _slate("how many escalators are in this building?")
    absent = next(c for c in slate.subjects if not c.present)
    closure = resolve_closure(slate, absent.candidate_id)
    assert closure.resolved
    assert closure.absent
    assert not closure.executable
    assert any("not present in this model" in n for n in closure.notes)


def test_closure_rejects_a_candidate_id_not_in_the_slate(slate_env):
    slate = _slate("how many doors are there?")
    closure = resolve_closure(slate, "s999")
    assert not closure.resolved
    assert "not in this request's slate" in (closure.unresolved_reason or "")


def test_explicit_union_of_peer_concepts_is_preserved(slate_env):
    """§3.1: peer concepts the user explicitly named stay together."""
    slate = _slate("how many walls and curtain walls are there?")
    closure = resolve_closure(
        slate,
        _subject_id(slate, "IfcCurtainWall"),
        [_subject_id(slate, "IfcWall")],
    )
    assert closure.executable
    assert "IfcCurtainWall" in closure.ifc_classes and "IfcWall" in closure.ifc_classes


# ---------------------------------------------------------------------------
# Provenance — the §2.4 anti-invention rule
# ---------------------------------------------------------------------------


def test_a_condition_citing_no_source_is_rejected_as_invented(slate_env):
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=_field_id(slate, "FireRating"),
                    operator=BoundOperator.EQUALS,
                    value_text="EI60",
                )
            ],
        )
    )
    validation = validate_binding(plan, slate)
    assert not validation.valid
    assert "invented_condition" in _codes(validation)


def test_a_condition_citing_a_span_absent_from_the_question_is_rejected(slate_env):
    """Guards against a plausible-looking but fabricated provenance string."""
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=_field_id(slate, "FireRating"),
                    operator=BoundOperator.EQUALS,
                    value_text="EI60",
                    source_span="first available wall",
                )
            ],
        )
    )
    assert "source_span_not_in_question" in _codes(validate_binding(plan, slate))


def test_a_condition_with_a_real_span_is_accepted(slate_env):
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=_field_id(slate, "FireRating"),
                    operator=BoundOperator.IS_PRESENT,
                    source_span="fire rating",
                )
            ],
        )
    )
    assert validate_binding(plan, slate).valid


def test_inherited_scope_is_rejected_when_there_is_no_previous_result(slate_env):
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=_field_id(slate, "FireRating"),
                    operator=BoundOperator.IS_PRESENT,
                    inherited_from_scope=True,
                )
            ],
        )
    )
    assert "no_inheritable_scope" in _codes(validate_binding(plan, slate))


# ---------------------------------------------------------------------------
# Scope is not a condition (§1.3)
# ---------------------------------------------------------------------------


def test_a_scope_selection_cannot_be_used_as_a_narrowing_condition(slate_env):
    """The general fix for the recorded 'could not read a specific floor from
    this building' family of failures."""
    slate = _slate("how many walls are in this building?")
    active_model = next(c for c in slate.spatial if c.kind.value == "active_model")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=active_model.candidate_id,
                    operator=BoundOperator.EQUALS,
                    value_text="this building",
                    source_span="this building",
                )
            ],
        )
    )
    assert "scope_used_as_condition" in _codes(validate_binding(plan, slate))


def test_the_same_question_binds_cleanly_as_a_whole_model_scope(slate_env):
    """The correct binding of the same question carries NO condition at all."""
    slate = _slate("how many walls are in this building?")
    plan = _plan(_part(slate, "IfcWall", scope_kind=ScopeKind.ACTIVE_MODEL))
    assert validate_binding(plan, slate).valid


def test_claiming_a_previous_result_scope_that_does_not_exist_is_rejected(slate_env):
    slate = _slate("how many walls are there?")
    plan = _plan(_part(slate, "IfcWall", scope_kind=ScopeKind.PREVIOUS_RESULT))
    assert "scope_unavailable" in _codes(validate_binding(plan, slate))


def test_an_unknown_spatial_candidate_is_rejected(slate_env):
    slate = _slate("how many walls are there?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            scope_kind=ScopeKind.SPATIAL_CANDIDATE,
            scope_candidate_id="sp99",
        )
    )
    assert "unknown_scope_candidate" in _codes(validate_binding(plan, slate))


# ---------------------------------------------------------------------------
# Operator / data type / applicability (§3.3)
# ---------------------------------------------------------------------------


def test_a_numeric_operator_on_a_text_field_is_rejected(slate_env):
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=_field_id(slate, "FireRating"),
                    operator=BoundOperator.GREATER_THAN,
                    value_text="60",
                    source_span="fire rating",
                )
            ],
        )
    )
    assert "operator_type_mismatch" in _codes(validate_binding(plan, slate))


def test_the_slate_does_not_offer_a_field_absent_from_the_subject_family(slate_env):
    """§13.3, first line of defence: a field recorded only on walls must not be
    offered as a candidate for a question about spaces."""
    slate = _slate("which spaces have a fire rating?")
    assert not any(f.field_name == "FireRating" for f in slate.fields)


def test_a_field_not_recorded_on_the_subject_family_is_rejected(slate_env):
    """§13.3, second line of defence: even if a binding names a field that IS in
    the slate, applying it to a family that does not carry it must be refused.

    The synthetic model records `IsExternal` in a different property set per
    family, so a question naming both families offers both candidates — and
    crossing them over must fail rather than silently query nothing.
    """
    slate = _slate("which external doors and external walls are there?")
    wall_external = next(
        c for c in slate.fields if c.field_name == "IsExternal" and c.set_name == "Pset_WallCommon"
    )
    plan = _plan(
        _part(
            slate,
            "IfcDoor",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=wall_external.candidate_id,
                    operator=BoundOperator.EQUALS,
                    value_text="true",
                    source_span="external",
                )
            ],
        )
    )
    assert "field_not_applicable" in _codes(validate_binding(plan, slate))


def test_between_requires_exactly_two_bounds(slate_env):
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=_field_id(slate, "FireRating"),
                    operator=BoundOperator.BETWEEN,
                    value_list=["1"],
                    source_span="fire rating",
                )
            ],
        )
    )
    codes = _codes(validate_binding(plan, slate))
    assert "bad_value_shape" in codes or "operator_type_mismatch" in codes


def test_an_unknown_condition_candidate_is_rejected(slate_env):
    slate = _slate("which walls have a fire rating?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id="f99",
                    operator=BoundOperator.IS_PRESENT,
                    source_span="fire rating",
                )
            ],
        )
    )
    assert "unknown_condition_candidate" in _codes(validate_binding(plan, slate))


# ---------------------------------------------------------------------------
# Operation shape (§3.3, §5.1)
# ---------------------------------------------------------------------------


def test_an_exact_operation_cannot_rest_on_semantic_ranking(slate_env):
    """§3.3: 'an exact operation is not being based on a bounded
    semantic-candidate count'."""
    slate = _slate("how many walls are there?")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            operation=OutputOperation.COUNT,
            semantic_ranking_text="walls that feel structural",
        )
    )
    assert "exact_operation_from_semantic_evidence" in _codes(validate_binding(plan, slate))


def test_a_qualitative_operation_may_carry_semantic_ranking(slate_env):
    slate = _slate("describe the walls in this building")
    plan = _plan(
        _part(
            slate,
            "IfcWall",
            operation=OutputOperation.DESCRIPTION,
            semantic_ranking_text="how the walls are organized",
        )
    )
    assert validate_binding(plan, slate).valid


def test_unknown_output_field_is_rejected(slate_env):
    slate = _slate("how many walls are there?")
    plan = _plan(_part(slate, "IfcWall", output_field_candidate_ids=["f99"]))
    assert "unknown_output_field" in _codes(validate_binding(plan, slate))


# ---------------------------------------------------------------------------
# Relationship execution (§3.3, §5.4)
# ---------------------------------------------------------------------------


def test_a_relationship_operation_requires_a_relationship_candidate(slate_env):
    slate = _slate("which spaces are connected to the stairs?")
    plan = _plan(_part(slate, "IfcSpace", operation=OutputOperation.RELATIONSHIP))
    assert "missing_relationship_binding" in _codes(validate_binding(plan, slate))


def test_an_unknown_relationship_candidate_is_rejected(slate_env):
    slate = _slate("which spaces are connected to the stairs?")
    plan = _plan(
        _part(
            slate,
            "IfcSpace",
            operation=OutputOperation.RELATIONSHIP,
            relationship_candidate_id="r99",
        )
    )
    assert "unknown_relationship_candidate" in _codes(validate_binding(plan, slate))


# ---------------------------------------------------------------------------
# Modifier coverage — §2.4's "never silently dropped"
# ---------------------------------------------------------------------------


def test_a_material_modifier_that_is_neither_bound_nor_declared_is_reported(slate_env):
    """Binding the broad subject while ignoring "on the second floor" would
    answer a different, larger question."""
    slate = _slate("how many doors are on the second floor?")
    plan = _plan(_part(slate, "IfcDoor", scope_kind=ScopeKind.ACTIVE_MODEL))
    validation = validate_binding(plan, slate)
    assert "modifier_silently_dropped" in _codes(validation)
    assert validation.silently_dropped_modifiers


def test_declaring_a_modifier_unresolved_is_accepted(slate_env):
    """Honest declaration is allowed; silent omission is not."""
    slate = _slate("how many doors are on the second floor?")
    plan = BindingPlan(
        answer_parts=[_part(slate, "IfcDoor")],
        unresolved_modifiers=["the second floor"],
    )
    validation = validate_binding(plan, slate)
    assert "modifier_silently_dropped" not in _codes(validation)


def test_binding_a_floor_scope_candidate_satisfies_the_floor_modifier(slate_env):
    slate = _slate("how many doors are on the second floor?")
    band = next(c for c in slate.spatial if c.kind.value == "floor_band")
    plan = _plan(
        _part(
            slate,
            "IfcDoor",
            scope_kind=ScopeKind.SPATIAL_CANDIDATE,
            scope_candidate_id=band.candidate_id,
        )
    )
    assert "modifier_silently_dropped" not in _codes(validate_binding(plan, slate))


def test_a_scope_reference_needs_no_condition(slate_env):
    """Scope references are not material, so binding nothing for them is fine."""
    slate = _slate("how many walls are in this building?")
    plan = _plan(_part(slate, "IfcWall"))
    validation = validate_binding(plan, slate)
    assert validation.valid
    assert not validation.silently_dropped_modifiers


# ---------------------------------------------------------------------------
# Unaccounted question terms — the general form of the worst recorded failure
# ---------------------------------------------------------------------------


def test_an_unexplained_qualifier_is_rejected(slate_env):
    """Regression guard for a defect a LIVE smoke run caught.

    "How many parking spaces are there?" lexically matches `IfcSpace` on the
    word "spaces". "parking" is not a quoted value, comparison, unit, floor
    reference or negation, so the structural modifier check never sees it — and
    the pipeline confidently answered with every space in the model. Any content
    token no selected candidate explains must block the answer.
    """
    slate = _slate("how many parking spaces are there?")
    plan = _plan(_part(slate, "IfcSpace"))
    validation = validate_binding(plan, slate)
    assert not validation.valid
    assert "unaccounted_question_terms" in _codes(validation)
    assert "parking" in validation.clarification()


def test_declaring_the_qualifier_unresolved_still_blocks_the_broader_answer(slate_env):
    """Declaring is honest, but it does not license the broader query.

    §6: "no unavailable condition may be silently removed to produce a broader
    exact result." A declaration improves the MESSAGE, never the outcome —
    otherwise the model could unlock any over-broad answer by admitting to it.
    """
    slate = _slate("how many parking spaces are there?")
    plan = BindingPlan(answer_parts=[_part(slate, "IfcSpace")], unresolved_modifiers=["parking"])
    validation = validate_binding(plan, slate)
    assert "unaccounted_question_terms" in _codes(validation)
    assert "could not apply" in validation.clarification()


@pytest.mark.parametrize(
    "question",
    [
        "how many doors are there?",
        "how many doors are in this building?",
        "how many walls are in this building?",
        "how many curtain walls are there?",
        "show me all the doors on the second floor",
        "which walls have a fire rating of EI60?",
    ],
)
def test_ordinary_questions_are_fully_accounted_for(slate_env, question):
    """The check must not fire on normal questions, or it blocks everything.

    Each of these should bind cleanly: the subject explains its noun, a scope
    reference explains "building", a floor span explains the level, and a bound
    field/value explains the rest.
    """
    slate = _slate(question)
    subject = slate.subjects[0]
    conditions = []
    if "fire rating" in question:
        conditions = [
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "FireRating"),
                operator=BoundOperator.EQUALS,
                value_text="EI60",
                source_span="EI60",
            )
        ]
    kwargs = {"conditions": conditions}
    if "second floor" in question:
        band = next(c for c in slate.spatial if c.kind.value == "floor_band")
        kwargs["scope_kind"] = ScopeKind.SPATIAL_CANDIDATE
        kwargs["scope_candidate_id"] = band.candidate_id

    part = AnswerPart(
        part_id="p1",
        request_text=question,
        operation=OutputOperation.COUNT,
        subject_candidate_id=subject.candidate_id,
        **kwargs,
    )
    codes = _codes(validate_binding(_plan(part), slate))
    assert "unaccounted_question_terms" not in codes, codes


@pytest.mark.parametrize(
    "question",
    [
        "Hur manga fonster finns det i byggnaden?",
        "Hoeveel deuren zitten er in dit gebouw?",
        "Combien de portes y a-t-il dans ce batiment?",
    ],
)
def test_a_non_english_question_is_not_flagged_as_unaccounted(slate_env, question):
    """Regression guard for a defect a LIVE smoke run caught.

    The coverage check is English-oriented, so a Swedish question had almost
    every token flagged as unaccounted and was refused — losing multilingual
    support the pipeline previously had. The check only fires on a MODIFIER
    position now, so a question this machinery cannot read simply produces no
    flags rather than a false refusal.
    """
    slate = _slate(question)
    if not slate.subjects:
        return  # nothing recognized at all is itself a non-flagging outcome
    plan = _plan(_part(slate, slate.subjects[0].ifc_class))
    assert "unaccounted_question_terms" not in _codes(validate_binding(plan, slate))


def test_the_exemption_set_contains_no_domain_nouns(slate_env):
    """Guards the guard.

    A word in `_UNREMARKABLE_TOKENS` is exempt from needing a candidate to
    explain it. Adding a BIM noun or adjective there would silently exempt
    exactly the qualifiers this check exists to catch — "parking" being the
    motivating case — so the set must stay operation verbs and generic English.
    """
    from app.query.binding.validate import _UNREMARKABLE_TOKENS

    domain_words = {
        "parking",
        "external",
        "internal",
        "fire",
        "rating",
        "bearing",
        "load",
        "door",
        "window",
        "wall",
        "space",
        "room",
        "floor",
        "storey",
        "level",
        "column",
        "beam",
        "slab",
        "roof",
        "stair",
        "ramp",
        "railing",
        "material",
        "curtain",
        "escalator",
        "toilet",
        "accessible",
        "wheelchair",
        "thermal",
        "acoustic",
        "cost",
        "area",
        "volume",
        "width",
        "height",
    }
    assert not (_UNREMARKABLE_TOKENS & domain_words)


def test_a_value_identified_subject_explains_its_own_noun(slate_env):
    """ "rooms" is explained by the stored value that admitted `IfcSpace`, even
    though no class or field is called "room"."""
    slate = _slate("how many rooms are in this building?")
    space = next(c for c in slate.subjects if c.ifc_class == "IfcSpace")
    plan = _plan(_part(slate, "IfcSpace"))
    assert "Rooms" in space.match_reason
    assert "unaccounted_question_terms" not in _codes(validate_binding(plan, slate))


# ---------------------------------------------------------------------------
# Plan-level and no-repair guarantees
# ---------------------------------------------------------------------------


def test_a_declared_clarification_is_a_valid_outcome(slate_env):
    slate = _slate("something ambiguous")
    plan = BindingPlan(needs_clarification=True, clarification_question="Which one?")
    assert validate_binding(plan, slate).valid


def test_an_empty_plan_is_rejected(slate_env):
    slate = _slate("how many doors are there?")
    assert "no_answer_parts" in _codes(validate_binding(BindingPlan(), slate))


def test_more_than_one_primary_visual_part_is_rejected(slate_env):
    """§9: multi-part questions need ONE explicit primary visual answer part."""
    slate = _slate("how many doors and walls are there?")
    plan = _plan(
        _part(slate, "IfcDoor", part_id="p1", is_primary_visual=True),
        _part(slate, "IfcWall", part_id="p2", is_primary_visual=True),
    )
    assert "multiple_primary_visual_parts" in _codes(validate_binding(plan, slate))


def test_duplicate_part_ids_are_rejected(slate_env):
    slate = _slate("how many doors and walls are there?")
    plan = _plan(_part(slate, "IfcDoor", part_id="p1"), _part(slate, "IfcWall", part_id="p1"))
    assert "duplicate_part_id" in _codes(validate_binding(plan, slate))


def test_validation_yields_a_concise_user_facing_reason(slate_env):
    slate = _slate("how many walls are there?")
    plan = _plan(_part(slate, "IfcWall", scope_kind=ScopeKind.PREVIOUS_RESULT))
    message = validate_binding(plan, slate).clarification()
    assert message and "previous result" in message


def test_a_partially_valid_plan_keeps_its_sound_parts(slate_env):
    """§6 partial: a useful part must not be discarded because another failed."""
    slate = _slate("how many doors and walls are there?")
    plan = _plan(
        _part(slate, "IfcDoor", part_id="p1"),
        _part(slate, "IfcWall", part_id="p2", scope_kind=ScopeKind.PREVIOUS_RESULT),
    )
    validation = validate_binding(plan, slate)
    assert not validation.valid
    assert [p.part.part_id for p in validation.valid_parts] == ["p1"]


def test_validation_is_pure_and_makes_no_model_call(slate_env, monkeypatch):
    """§3.3 / §10.1: an invalid binding must not trigger a second LLM request.

    Any attempt to construct an OpenAI client during validation fails loudly.
    """
    import app.llm.client as client_module

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("validation attempted an LLM call")

    monkeypatch.setattr(client_module, "get_llm_client", _explode)
    monkeypatch.setattr(client_module.OpenAIQueryClient, "_get_client", _explode)

    slate = _slate("how many walls are there?")
    plan = _plan(_part(slate, "IfcWall", scope_kind=ScopeKind.PREVIOUS_RESULT))
    assert not validate_binding(plan, slate).valid
