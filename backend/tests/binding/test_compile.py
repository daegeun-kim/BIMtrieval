"""Predicate compilation + evidence status (Task 24 §4, §5.2, §6, §13.3).

Offline: compilation is pure apart from the value-vocabulary read, which is
stubbed. No DB, no OpenAI, no embedding.

The compiled predicate is the single object every downstream consumer shares
(§9), so these tests are really about one question: does the predicate describe
exactly the set the user asked for — never broader?
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    AnswerPart,
    BoundCondition,
    BoundOperator,
    OutputOperation,
    ScopeKind,
)
from app.query.binding.closure import resolve_closure
from app.query.binding.compile import compile_predicate
from app.query.binding.evidence import ResultStatus, classify_structured_result
from app.query.binding.slate import SlateInputs, build_slate
from app.query.sql.schemas import FilterCondition, FilterGroup, Operator

from .conftest import SYNTHETIC_MODEL_ID


@pytest.fixture(autouse=True)
def _stub_value_vocabulary(monkeypatch):
    """Serve the field's 'complete' vocabulary from the synthetic slate samples.

    Compilation must read the COMPLETE stored vocabulary rather than the slate's
    bounded sample (§4.2); this stub stands in for that read so the test stays
    offline while exercising the same code path.
    """
    import app.query.binding.compile as compile_module

    vocab = {
        ("property", "Pset_WallCommon", "FireRating"): ["EI30", "EI60", "EI90"],
        ("property", "Pset_WallCommon", "IsExternal"): ["true", "false"],
        ("property", "Pset_DoorCommon", "IsExternal"): ["true", "false"],
        ("attribute", None, "object_type"): ["Rooms", "Corridors"],
        ("type_fact", None, "type_name"): ["D2 ny", "D1 ny"],
    }
    monkeypatch.setattr(
        compile_module,
        "load_field_values",
        lambda session, sid, concept, classes=None: vocab.get(
            (concept.field_kind, concept.set_name, concept.field_name), []
        ),
    )


def _slate(question, **kw):
    return build_slate(
        session=None,
        inputs=SlateInputs(question=question, source_model_id=SYNTHETIC_MODEL_ID, **kw),
    )


def _compile(slate, ifc_class, **part_kw):
    subject_id = next(c.candidate_id for c in slate.subjects if c.ifc_class == ifc_class)
    part = AnswerPart(
        part_id="p1",
        request_text=slate.question,
        operation=part_kw.pop("operation", OutputOperation.COUNT),
        subject_candidate_id=subject_id,
        **part_kw,
    )
    closure = resolve_closure(slate, subject_id, part.union_subject_candidate_ids)
    return compile_predicate(None, part, closure, slate, SYNTHETIC_MODEL_ID)


def _field_id(slate, field_name, set_name=None):
    return next(
        c.candidate_id
        for c in slate.fields
        if c.field_name == field_name and (set_name is None or c.set_name == set_name)
    )


def _flatten(node):
    if node is None:
        return []
    if isinstance(node, FilterCondition):
        return [node]
    return [c for child in node.conditions for c in _flatten(child)]


# ---------------------------------------------------------------------------
# Subject family reaches the predicate (§3.2)
# ---------------------------------------------------------------------------


def test_predicate_carries_the_whole_present_family(slate_env):
    predicate = _compile(_slate("how many walls are there?"), "IfcWall")
    assert set(predicate.ifc_classes) == {"IfcWall", "IfcWallStandardCase"}
    assert predicate.executable


def test_predicate_excludes_a_co_present_type_definition(slate_env):
    predicate = _compile(_slate("how many doors are there?"), "IfcDoor")
    assert predicate.ifc_classes == ("IfcDoor",)


# ---------------------------------------------------------------------------
# Scope is not a condition (§1.3)
# ---------------------------------------------------------------------------


def test_active_model_scope_adds_no_filter(slate_env):
    """The whole-model scope is the default extent. Compiling it into a
    predicate is what previously turned "this building" into a floor filter."""
    predicate = _compile(
        _slate("how many walls are in this building?"), "IfcWall", scope_kind=ScopeKind.ACTIVE_MODEL
    )
    assert predicate.filters is None
    assert predicate.executable


def test_a_floor_band_scope_compiles_to_a_storey_restriction(slate_env):
    slate = _slate("how many doors are on the second floor?")
    band = next(c for c in slate.spatial if c.kind.value == "floor_band")
    predicate = _compile(
        slate,
        "IfcDoor",
        scope_kind=ScopeKind.SPATIAL_CANDIDATE,
        scope_candidate_id=band.candidate_id,
    )
    conditions = _flatten(predicate.filters)
    assert len(conditions) == 1
    assert conditions[0].field.field_name == "storey_global_id"
    assert conditions[0].operator is Operator.IN
    assert set(conditions[0].value) == set(band.storey_global_ids)


def test_selection_scope_is_carried_as_entity_ids_not_a_filter(slate_env):
    slate = _slate(
        "how many of the selected walls are external?",
        selected_entities=[{"entity_id": 7}, {"entity_id": 9}],
    )
    predicate = _compile(slate, "IfcWall", scope_kind=ScopeKind.SELECTED_OBJECTS)
    assert predicate.scope_entity_ids == ()  # ids supplied by the caller, not the slate
    assert predicate.filters is None


# ---------------------------------------------------------------------------
# Boolean structure — the AND/OR precedence that decides correctness
# ---------------------------------------------------------------------------


def test_scope_ands_with_conditions_that_or_among_themselves(slate_env):
    """ "walls on floor 2 that are external OR load bearing" must be
    `floor AND (external OR load_bearing)`.

    Flattening scope into the OR would return every object on the floor — a
    silently enormous over-answer.
    """
    slate = _slate("show me walls on the second floor that are external or fire rated")
    band = next(c for c in slate.spatial if c.kind.value == "floor_band")
    predicate = _compile(
        slate,
        "IfcWall",
        scope_kind=ScopeKind.SPATIAL_CANDIDATE,
        scope_candidate_id=band.candidate_id,
        condition_bool_op="or",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "IsExternal", "Pset_WallCommon"),
                operator=BoundOperator.EQUALS,
                value_text="true",
                source_span="external",
            ),
            BoundCondition(
                condition_id="c2",
                candidate_id=_field_id(slate, "FireRating"),
                operator=BoundOperator.EQUALS,
                value_text="EI60",
                source_span="fire rated",
            ),
        ],
    )
    assert isinstance(predicate.filters, FilterGroup)
    assert predicate.filters.bool_op == "and"
    # The storey restriction sits at the top level, the value conditions inside an OR.
    top_level = predicate.filters.conditions
    storey = [c for c in top_level if isinstance(c, FilterCondition)]
    inner = [c for c in top_level if isinstance(c, FilterGroup)]
    assert storey and storey[0].field.field_name == "storey_global_id"
    assert inner and inner[0].bool_op == "or"


def test_conditions_in_a_bool_group_are_or_ed(slate_env):
    slate = _slate("show me walls that are either external or fire rated")
    predicate = _compile(
        slate,
        "IfcWall",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "IsExternal", "Pset_WallCommon"),
                operator=BoundOperator.EQUALS,
                value_text="true",
                bool_group="g1",
                source_span="external",
            ),
            BoundCondition(
                condition_id="c2",
                candidate_id=_field_id(slate, "FireRating"),
                operator=BoundOperator.EQUALS,
                value_text="EI60",
                bool_group="g1",
                source_span="fire rated",
            ),
        ],
    )
    groups = [c for c in _flatten_groups(predicate.filters) if c.bool_op == "or"]
    assert groups, "grouped conditions must OR together"


def _flatten_groups(node):
    if node is None or isinstance(node, FilterCondition):
        return []
    return [node] + [g for c in node.conditions for g in _flatten_groups(c)]


# ---------------------------------------------------------------------------
# Value resolution against the field's own vocabulary (§4.2)
# ---------------------------------------------------------------------------


def test_a_value_the_model_holds_compiles(slate_env):
    slate = _slate("which walls have a fire rating of EI60?")
    predicate = _compile(
        slate,
        "IfcWall",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "FireRating"),
                operator=BoundOperator.EQUALS,
                value_text="EI60",
                source_span="EI60",
            )
        ],
    )
    assert predicate.executable
    assert _flatten(predicate.filters)[0].value == "EI60"


def test_a_value_the_model_does_not_hold_is_unresolved_not_dropped(slate_env):
    """§2.4: a required modifier may never be silently dropped so a broader
    query can execute. The predicate must become NOT executable."""
    slate = _slate("which walls have a fire rating of EI120?")
    predicate = _compile(
        slate,
        "IfcWall",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "FireRating"),
                operator=BoundOperator.EQUALS,
                value_text="EI120",
                source_span="EI120",
            )
        ],
    )
    assert not predicate.executable
    assert predicate.unresolved
    assert "EI120" in predicate.unresolved[0].reason


def test_morphological_value_match_is_reported_as_an_interpretation(slate_env):
    """Stored "Rooms" reached by the user's "room" — correct, but the user must
    be told how it was read."""
    slate = _slate("how many spaces are rooms?")
    predicate = _compile(
        slate,
        "IfcSpace",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "object_type"),
                operator=BoundOperator.EQUALS,
                value_text="room",
                source_span="rooms",
            )
        ],
    )
    assert predicate.executable
    assert any("Rooms" in note for note in predicate.interpretation_notes)


def test_a_quoted_value_demands_an_exact_stored_match(slate_env):
    """§4.2: exact quoted values preserved when the user requests exactness."""
    slate = _slate("show me the doors of type 'd2 NY'")
    predicate = _compile(
        slate,
        "IfcDoor",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "type_name"),
                operator=BoundOperator.EQUALS,
                value_text="d2 NY",
                source_span="'d2 NY'",
            )
        ],
    )
    assert not predicate.executable, (
        "a quoted value must not fold case onto a different stored value"
    )


def test_negation_compiles_to_an_exclusion(slate_env):
    slate = _slate("how many walls are not external?")
    predicate = _compile(
        slate,
        "IfcWall",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=_field_id(slate, "IsExternal", "Pset_WallCommon"),
                operator=BoundOperator.EQUALS,
                value_text="true",
                negated=True,
                source_span="not external",
            )
        ],
    )
    assert _flatten(predicate.filters)[0].operator is Operator.NOT_IN


# ---------------------------------------------------------------------------
# Units (§3.3, §4.2)
# ---------------------------------------------------------------------------


def test_a_unit_comparison_against_a_field_with_no_normalized_unit_is_refused(slate_env):
    """Comparing millimetres against an unnormalized stored number would
    silently produce a wrong set, so it must refuse instead."""
    slate = _slate("show me spaces with a gross floor area over 20 m2")
    area = next((c for c in slate.fields if c.field_name == "GrossFloorArea"), None)
    if area is None:
        pytest.skip("quantity field not offered for this question")
    predicate = _compile(
        slate,
        "IfcSpace",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=area.candidate_id,
                operator=BoundOperator.GREATER_THAN,
                value_text="20",
                unit="m2",
                source_span="over 20 m2",
            )
        ],
    )
    assert not predicate.executable
    assert "unit" in predicate.unresolved[0].reason.lower()


# ---------------------------------------------------------------------------
# Evidence status contract (§6)
# ---------------------------------------------------------------------------


def test_zero_is_not_unavailable():
    status, reason = classify_structured_result(
        matched_count=0,
        predicate_executable=True,
        unresolved_reasons=[],
        subject_absent=False,
    )
    assert status is ResultStatus.ZERO
    assert reason and "queried completely" in reason


def test_an_absent_subject_is_zero_and_says_so_about_the_model():
    status, reason = classify_structured_result(
        matched_count=0,
        predicate_executable=False,
        unresolved_reasons=[],
        subject_absent=True,
    )
    assert status is ResultStatus.ZERO
    assert "not necessarily the real building" in (reason or "")


def test_missing_field_coverage_is_unavailable_not_zero():
    """§6: 'missing field coverage is not a zero value'."""
    status, _ = classify_structured_result(
        matched_count=10,
        predicate_executable=True,
        unresolved_reasons=[],
        subject_absent=False,
        field_coverage_absent=True,
    )
    assert status is ResultStatus.UNAVAILABLE


def test_an_unresolved_condition_forces_unavailable_over_a_broader_exact():
    """§6 final rule: no unavailable condition may be silently removed to
    produce a broader exact result."""
    status, reason = classify_structured_result(
        matched_count=999,
        predicate_executable=False,
        unresolved_reasons=["'EI120' is not one of the recorded values"],
        subject_absent=False,
    )
    assert status is ResultStatus.UNAVAILABLE
    assert "EI120" in (reason or "")


def test_a_nonzero_complete_query_is_exact():
    status, reason = classify_structured_result(
        matched_count=42,
        predicate_executable=True,
        unresolved_reasons=[],
        subject_absent=False,
    )
    assert status is ResultStatus.EXACT
    assert reason is None
