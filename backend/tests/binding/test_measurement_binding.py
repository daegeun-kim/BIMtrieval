"""Numeric filtering and aggregation against IFC-native units (task27 §4.3, §7.3).

Offline: every unit verdict is a pure function of the field candidate's
manifest-derived measurement facts, so no database, no OpenAI call, and no
embedding is involved. The candidates below are synthetic and carry no
production field name, model id, or expected count.

What is being pinned is that a number never quietly changes meaning:

- a bare number is read in the field's own unit AND that is disclosed;
- the same unit spelled differently still runs;
- a DIFFERENT unit fails rather than being converted;
- a field whose values are not on one scale is neither filtered nor summed.
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    AnswerPart,
    BoundCondition,
    BoundOperator,
    OutputOperation,
)
from app.query.binding.closure import SubjectClosure
from app.query.binding.compile import compile_predicate
from app.query.binding.schemas import (
    CandidateSlate,
    FieldCandidate,
    SubjectCandidate,
)
from app.query.binding.validate import PartValidation, _check_condition

SYNTHETIC_MODEL_ID = 4242
#: The condition spans below must appear verbatim in the question — an
#: invented span is rejected before any unit check runs.
QUESTION = "how many with a measured value over 20 in this model"
SPAN = "over 20"


def _candidate(
    candidate_id="f1",
    *,
    field_kind="quantity",
    set_name="Qto_Any",
    field_name="GrossArea",
    measure_type="area",
    unit_state="uniform",
    unit_symbol="m²",
    unit_limitation=None,
) -> FieldCandidate:
    return FieldCandidate(
        candidate_id=candidate_id,
        field_kind=field_kind,
        set_name=set_name,
        field_name=field_name,
        data_type="number",
        operators=("gt", "gte", "lt", "lte", "eq", "between"),
        applicable_classes=("IfcSlab",),
        populated_count=30,
        total_count=50,
        measure_type=measure_type,
        unit_state=unit_state,
        unit_symbol=unit_symbol,
        unit_limitation=unit_limitation,
    )


def _slate(candidate: FieldCandidate) -> CandidateSlate:
    return CandidateSlate(
        question=QUESTION,
        source_model_id=SYNTHETIC_MODEL_ID,
        subjects=[
            SubjectCandidate(
                candidate_id="s1",
                label="IfcSlab",
                ifc_class="IfcSlab",
                schema_role="element",
                present=True,
                result_kind=True,
            )
        ],
        fields=[candidate],
    )


def _compile(candidate: FieldCandidate, *, value="20", unit=None):
    slate = _slate(candidate)
    part = AnswerPart(
        part_id="p1",
        request_text=QUESTION,
        operation=OutputOperation.COUNT,
        subject_candidate_id="s1",
        conditions=[
            BoundCondition(
                condition_id="c1",
                candidate_id=candidate.candidate_id,
                operator=BoundOperator.GREATER_THAN,
                value_text=value,
                unit=unit,
                source_span=SPAN,
            )
        ],
    )
    closure = SubjectClosure(ifc_classes=("IfcSlab",))
    return compile_predicate(None, part, closure, slate, SYNTHETIC_MODEL_ID)


# ---------------------------------------------------------------------------
# The candidate's own contract
# ---------------------------------------------------------------------------


def test_a_uniform_field_is_unit_available():
    assert _candidate().unit_available is True


@pytest.mark.parametrize("state", ["mixed", "unknown", None])
def test_a_field_that_is_not_uniform_is_not_unit_available(state):
    assert _candidate(unit_state=state, unit_symbol=None).unit_available is False


def test_a_uniform_state_with_no_symbol_is_still_not_available():
    """Uniform-but-nameless would let an aggregate be reported with no unit."""
    assert _candidate(unit_symbol=None).unit_available is False


def test_the_payload_shows_the_unit_only_when_it_is_trustworthy():
    available = _candidate().to_payload()
    assert available["unit"] == "m²"
    assert available["measure"] == "area"

    unavailable = _candidate(
        unit_state="mixed", unit_symbol=None, unit_limitation="two different units"
    ).to_payload()
    assert "unit" not in unavailable  # compacted away rather than shown as null
    assert unavailable["unit_limitation"] == "two different units"


def test_a_non_dimensional_number_field_advertises_no_unit():
    payload = _candidate(measure_type=None, unit_state=None, unit_symbol=None).to_payload()
    assert "unit" not in payload
    assert "measure" not in payload


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def test_a_unitless_literal_is_read_in_the_fields_own_unit_and_disclosed():
    predicate = _compile(_candidate())
    assert predicate.executable
    assert any("m²" in note for note in predicate.interpretation_notes)


def test_an_equivalent_spelling_of_the_same_unit_executes():
    for spelling in ("m2", "square metres", "M²"):
        predicate = _compile(_candidate(), unit=spelling)
        assert predicate.executable, spelling


def test_a_different_unit_is_unavailable_rather_than_converted():
    predicate = _compile(_candidate(), unit="mm2")
    assert not predicate.executable
    reason = predicate.unresolved[0].reason
    assert "m²" in reason
    assert "not converted" in reason


def test_a_mixed_unit_field_cannot_be_filtered():
    predicate = _compile(
        _candidate(
            unit_state="mixed",
            unit_symbol=None,
            unit_limitation="recorded in 2 different units in this model",
        )
    )
    assert not predicate.executable
    assert "2 different units" in predicate.unresolved[0].reason


def test_an_unknown_unit_field_cannot_be_filtered():
    predicate = _compile(
        _candidate(
            unit_state="unknown",
            unit_symbol=None,
            unit_limitation="this model declares no project default area unit",
        )
    )
    assert not predicate.executable
    assert "no project default" in predicate.unresolved[0].reason


def test_a_refused_unit_never_degrades_into_a_broader_query():
    """The whole point of refusing: the condition must not simply vanish.

    A dropped condition would leave the part unfiltered and report the class
    total as though it were the filtered count.
    """
    predicate = _compile(_candidate(), unit="mm2")
    assert predicate.filters is None or not predicate.executable
    assert predicate.unresolved


def test_a_plain_non_dimensional_number_still_filters_without_a_unit():
    predicate = _compile(
        _candidate(
            field_kind="property",
            set_name="Pset_Any",
            field_name="NumberOfRisers",
            measure_type=None,
            unit_state=None,
            unit_symbol=None,
        )
    )
    assert predicate.executable


def test_a_unit_against_a_non_dimensional_number_is_refused():
    predicate = _compile(
        _candidate(
            field_kind="property",
            set_name="Pset_Any",
            field_name="NumberOfRisers",
            measure_type=None,
            unit_state=None,
            unit_symbol=None,
        ),
        unit="mm",
    )
    assert not predicate.executable
    assert "no IFC measure type" in predicate.unresolved[0].reason


# ---------------------------------------------------------------------------
# Validation (the same verdict, one stage earlier)
# ---------------------------------------------------------------------------


def _validation(candidate: FieldCandidate, unit: str | None):
    slate = _slate(candidate)
    part = AnswerPart(
        part_id="p1",
        request_text=QUESTION,
        operation=OutputOperation.COUNT,
        subject_candidate_id="s1",
    )
    condition = BoundCondition(
        condition_id="c1",
        candidate_id=candidate.candidate_id,
        operator=BoundOperator.GREATER_THAN,
        value_text="20",
        unit=unit,
        source_span=SPAN,
    )
    validation = PartValidation(part=part, closure=SubjectClosure(ifc_classes=("IfcSlab",)))
    _check_condition(condition, part, slate, {"IfcSlab"}, validation)
    return validation


def test_validation_accepts_the_same_unit_and_rejects_a_different_one():
    assert not [i for i in _validation(_candidate(), "m2").issues if i.code == "unit_not_available"]
    rejected = _validation(_candidate(), "mm2")
    assert [i for i in rejected.issues if i.code == "unit_not_available"]


def test_validation_rejects_a_comparison_on_a_mixed_unit_field():
    issues = _validation(
        _candidate(unit_state="mixed", unit_symbol=None, unit_limitation="two units"), None
    ).issues
    assert [i for i in issues if i.code == "unit_not_available"]
