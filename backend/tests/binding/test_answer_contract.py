"""Answer packet + grounded-answer validation + fallback (Task 24 §8, §13.5).

Offline: results are constructed directly, so no DB, no OpenAI, no embedding.

The theme is one property: **the answering model cannot introduce a fact.** It
receives only adjudicated results, every number it may cite is a checkable
`fact_id`, and anything it changes is caught and replaced by a fallback built
from those same results — without a third model call.
"""

from __future__ import annotations

import json

import pytest

from app.llm.schemas import FactualClaim, GroundedAnswer
from app.query.binding.answer_validation import (
    build_fallback_answer,
    validate_answer,
)
from app.query.binding.evidence import (
    AggregateValue,
    AnswerPartResult,
    DistributionBucket,
    ResultExample,
    ResultStatus,
)
from app.query.binding.packet import build_answer_packet


def _result(
    part_id="p1",
    request="how many doors are there",
    operation="count",
    status=ResultStatus.EXACT,
    total=42,
    **kw,
):
    return AnswerPartResult(
        part_id=part_id,
        request_text=request,
        operation=operation,
        status=status,
        exact_total=total,
        **kw,
    )


def _packet(*results):
    return build_answer_packet("how many doors are there?", list(results))


def _answer(text="There are 42 doors.", claims=None, parts=("p1",), **kw):
    return GroundedAnswer(
        answer=text,
        answer_part_ids=list(parts),
        structured_claims=list(claims or []),
        **kw,
    )


# ---------------------------------------------------------------------------
# Packet contents and exclusions (§8.2)
# ---------------------------------------------------------------------------


def test_packet_carries_the_exact_total_as_a_checkable_fact():
    packet = _packet(_result())
    assert packet.parts[0]["exact_total"]["value"] == 42
    fact = packet.fact("p1.total")
    assert fact is not None and fact.value == 42


def test_packet_excludes_everything_section_8_2_forbids():
    """No rejected candidates, similarity scores, planner reasoning, group ids,
    complete viewer identities, raw canonical JSON, database ids, or SQL."""
    result = _result(
        examples=[ResultExample(entity_id=7, global_id="ABC123", ifc_class="IfcDoor", name="D1")],
        class_breakdown={"IfcDoor": 42},
    )
    blob = json.dumps(_packet(result).to_prompt_payload())
    for forbidden in (
        "ABC123",  # viewer identity
        "entity_id",
        "global_id",
        "canonical_json",
        "similarity",
        "rejected",
        "group_id",
        "SELECT",
        "predicate",
    ):
        assert forbidden not in blob, f"packet leaked {forbidden!r}"


def test_packet_examples_are_bounded_by_default():
    """§10.2: at most 3 examples per answer part by default."""
    examples = [
        ResultExample(entity_id=i, global_id=f"G{i}", ifc_class="IfcDoor") for i in range(30)
    ]
    packet = _packet(_result(examples=examples))
    assert len(packet.parts[0]["examples"]) == 3
    assert "examples_note" in packet.parts[0]


def test_partial_results_carry_the_known_and_unknown_split_separately():
    """§6: partial evidence must identify known and unknown parts separately."""
    result = _result(
        status=ResultStatus.PARTIAL,
        known_parts=["area for the 12 spaces that record it"],
        unknown_parts=["18 spaces record no area"],
        limitation="only 12 of 30 spaces carry this measurement",
    )
    entry = _packet(result).parts[0]
    assert entry["known"] == ["area for the 12 spaces that record it"]
    assert entry["not_known"] == ["18 spaces record no area"]


def test_rag_evidence_is_labelled_as_bounded_not_a_total():
    result = _result(rag_candidate_count=7)
    entry = _packet(result).parts[0]
    assert entry["semantic_examples_considered"]["count"] == 7
    assert "not a total" in entry["semantic_examples_considered"]["note"]


def test_aggregate_coverage_travels_with_the_number():
    result = _result(
        operation="aggregate",
        total=None,
        aggregate=AggregateValue("sum", 120.0, "m2", coverage_count=12, matched_count=30),
    )
    entry = _packet(result).parts[0]
    assert entry["aggregate"]["complete"] is False
    assert entry["aggregate"]["covers"] == 12 and entry["aggregate"]["of_matching"] == 30


def test_distribution_is_included_when_present():
    result = _result(distribution=[DistributionBucket("EI60", 720), DistributionBucket("EI30", 12)])
    assert _packet(result).parts[0]["distribution"][0] == {"value": "EI60", "count": 720}


# ---------------------------------------------------------------------------
# Grounded-answer validation (§8.3)
# ---------------------------------------------------------------------------


def test_a_faithful_answer_passes():
    result = _result()
    packet = _packet(result)
    answer = _answer(claims=[FactualClaim(fact_id="p1.total", value="42")])
    assert validate_answer(answer, packet, [result]).ok


def test_a_changed_number_is_rejected():
    """The single most important check: the model must not alter a value."""
    result = _result()
    packet = _packet(result)
    answer = _answer(
        text="There are 9999 doors.", claims=[FactualClaim(fact_id="p1.total", value="9999")]
    )
    validation = validate_answer(answer, packet, [result])
    assert not validation.ok
    assert "authoritative value" in validation.failures[0]


def test_an_unknown_fact_id_is_rejected():
    result = _result()
    answer = _answer(claims=[FactualClaim(fact_id="p9.invented", value="42")])
    validation = validate_answer(answer, _packet(result), [result])
    assert not validation.ok
    assert "unknown fact id" in validation.failures[0]


def test_an_unknown_answer_part_is_rejected():
    result = _result()
    answer = _answer(parts=("p1", "p7"))
    validation = validate_answer(answer, _packet(result), [result])
    assert not validation.ok
    assert "unknown answer part" in validation.failures[0]


def test_a_named_entity_absent_from_the_packet_is_rejected():
    """§8.3: named classes/properties/materials must appear in the packet."""
    result = _result(
        examples=[ResultExample(entity_id=1, global_id="G", ifc_class="IfcDoor", name="D1")]
    )
    answer = _answer(
        claims=[FactualClaim(fact_id="p1.total", value="42", named_entities=["IfcParkingSpace"])]
    )
    validation = validate_answer(answer, _packet(result), [result])
    assert not validation.ok
    assert "IfcParkingSpace" in validation.failures[0]


def test_a_named_entity_present_in_the_packet_is_accepted():
    result = _result(
        examples=[ResultExample(entity_id=1, global_id="G", ifc_class="IfcDoor", name="D1")]
    )
    answer = _answer(
        claims=[FactualClaim(fact_id="p1.total", value="42", named_entities=["IfcDoor"])]
    )
    assert validate_answer(answer, _packet(result), [result]).ok


def test_a_mismatched_unit_is_rejected():
    result = _result(
        operation="aggregate",
        total=None,
        aggregate=AggregateValue("sum", 120.0, "m2", coverage_count=30, matched_count=30),
    )
    answer = _answer(claims=[FactualClaim(fact_id="p1.aggregate", value="120", unit="mm")])
    validation = validate_answer(answer, _packet(result), [result])
    assert not validation.ok
    assert "unit" in validation.failures[0]


def test_reporting_unavailable_data_as_zero_is_rejected():
    """§6: absent data is not a count of zero."""
    result = _result(
        status=ResultStatus.UNAVAILABLE,
        total=None,
        limitation="this model records no thermal properties",
    )
    packet = _packet(result)
    answer = GroundedAnswer(
        answer="There are 0 walls with a U-value.",
        answer_part_ids=["p1"],
        structured_claims=[FactualClaim(fact_id="p1.total", value="0")],
    )
    validation = validate_answer(answer, packet, [result])
    assert not validation.ok


def test_describing_a_genuine_zero_as_unavailable_is_rejected():
    """The opposite inversion: a real zero must not read as missing data."""
    result = _result(status=ResultStatus.ZERO, total=0)
    answer = _answer(text="That information is not recorded in this model.", claims=[])
    validation = validate_answer(answer, _packet(result), [result])
    assert not validation.ok
    assert "genuine zero" in validation.failures[0]


def test_claiming_complete_coverage_from_bounded_rag_is_rejected():
    """§8.3: the model must not claim completeness from bounded evidence."""
    result = _result(
        operation="description", status=ResultStatus.EXACT, total=None, rag_candidate_count=5
    )
    answer = _answer(text="Every circulation element in the building is a stair.", claims=[])
    validation = validate_answer(answer, _packet(result), [result])
    assert not validation.ok
    assert "complete coverage" in validation.failures[0]


# ---------------------------------------------------------------------------
# Safe fallback (§8.3) — and the no-third-call guarantee
# ---------------------------------------------------------------------------


def test_fallback_reports_the_authoritative_numbers():
    text = build_fallback_answer([_result()])
    assert "42" in text


def test_fallback_distinguishes_every_status():
    results = [
        _result(part_id="p1", request="doors", status=ResultStatus.EXACT, total=42),
        _result(part_id="p2", request="escalators", status=ResultStatus.ZERO, total=0),
        _result(
            part_id="p3",
            request="u-values",
            status=ResultStatus.UNAVAILABLE,
            total=None,
            limitation="this model records no thermal properties",
        ),
    ]
    text = build_fallback_answer(results)
    assert "42" in text
    assert "none found in this model" in text
    assert "no thermal properties" in text
    # A zero and an unavailable must not read the same way.
    assert text.count("none found in this model") == 1


def test_fallback_invents_nothing():
    """Every token of a number in the fallback must come from a result."""
    result = _result(total=7)
    text = build_fallback_answer([result])
    import re

    for number in re.findall(r"\d+", text):
        assert number == "7"


def test_fallback_handles_no_results_without_crashing():
    assert build_fallback_answer([])


def test_validation_makes_no_model_call(monkeypatch):
    """§8.3: 'Do not call the LLM again after validation failure.'"""
    import app.llm.client as client_module

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("answer validation attempted an LLM call")

    monkeypatch.setattr(client_module, "get_llm_client", _explode)
    monkeypatch.setattr(client_module.OpenAIQueryClient, "_get_client", _explode)

    result = _result()
    bad = _answer(text="9999 doors", claims=[FactualClaim(fact_id="p1.total", value="9999")])
    assert not validate_answer(bad, _packet(result), [result]).ok
    assert build_fallback_answer([result])


@pytest.mark.parametrize(
    "status", [ResultStatus.ZERO, ResultStatus.UNAVAILABLE, ResultStatus.AMBIGUOUS]
)
def test_non_visual_results_do_not_drive_the_viewer(status):
    """§9: exact zero, unavailable and ambiguous answers highlight nothing."""
    result = _result(status=status, total=0 if status is ResultStatus.ZERO else None)
    assert not result.has_visual_result
