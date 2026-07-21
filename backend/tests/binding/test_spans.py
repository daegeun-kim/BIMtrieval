"""Detected modifier spans (Task 24 §2.4, §1.3, §13.2).

Offline: pure text handling. No DB, no OpenAI, no embedding.

The central assertion in this file is the §1.3 typed distinction between a
SCOPE reference (which selects what to look at) and a spatial CONDITION (which
narrows results). Conflating them is what produced a string of recorded
failures where an ordinary question was refused with a floor-resolution error
for a phrase naming the building as a whole.
"""

from __future__ import annotations

import pytest

from app.query.binding.spans import (
    ModifierKind,
    detect_spans,
    material_spans,
)


def _kinds(question: str) -> set[ModifierKind]:
    return {s.kind for s in detect_spans(question)}


def _of_kind(question: str, kind: ModifierKind) -> list[str]:
    return [s.text for s in detect_spans(question) if s.kind is kind]


# ---------------------------------------------------------------------------
# Scope reference vs spatial condition (§1.3) — the load-bearing distinction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "how many walls are in this building?",
        "give me a summary of this building",
        "what is the estimated construction cost of this building",
        "how many escalators are in this building?",
        # Paraphrases not drawn from specs/test_query.md (§13.6).
        "what does the model contain",
        "describe the entire structure",
        "how much glazing is in the whole project",
    ],
)
def test_whole_model_phrases_are_scope_not_conditions(question):
    """A phrase naming the model as a whole selects scope and narrows nothing.

    It must therefore produce NO floor reference and NO material span — a
    question containing only such a phrase carries no constraint at all.
    """
    spans = detect_spans(question)
    assert ModifierKind.SCOPE_REFERENCE in {s.kind for s in spans}
    assert ModifierKind.FLOOR_REFERENCE not in {s.kind for s in spans}
    assert all(not s.material for s in spans if s.kind is ModifierKind.SCOPE_REFERENCE)


@pytest.mark.parametrize(
    "question",
    [
        "show me all the doors in the second floor",
        "which spaces are on the second floor?",
        "external doors on the third floor",
        "what is on the top floor of this building?",
        # Paraphrases (§13.6).
        "list the columns on level 4",
        "anything on the ground floor",
        "windows on the 3rd storey",
        "what sits on the lowest level",
    ],
)
def test_positional_floor_language_is_a_material_condition(question):
    spans = detect_spans(question)
    floor = [s for s in spans if s.kind is ModifierKind.FLOOR_REFERENCE]
    assert floor, f"no floor reference detected in {question!r}"
    assert all(s.material for s in floor)


def test_a_question_carries_both_a_floor_condition_and_a_model_scope():
    """'the top floor of this building': the floor part narrows, the building
    part selects scope. Both must survive, correctly typed."""
    kinds = _kinds("what is on the top floor of this building?")
    assert ModifierKind.FLOOR_REFERENCE in kinds
    assert ModifierKind.SCOPE_REFERENCE in kinds


def test_the_scope_phrase_inside_a_floor_reference_is_not_double_counted():
    spans = detect_spans("show me the second floor of the building")
    floor = [s for s in spans if s.kind is ModifierKind.FLOOR_REFERENCE]
    scope = [s for s in spans if s.kind is ModifierKind.SCOPE_REFERENCE]
    assert len(floor) == 1
    assert len(scope) == 1
    assert "second floor" in floor[0].text.lower()


@pytest.mark.parametrize(
    "question",
    [
        "how many floors does this building have?",
        "how many storeys are there",
        "count the levels in the model",
    ],
)
def test_floor_language_without_a_positional_qualifier_is_not_a_condition(question):
    """Here the floors are the SUBJECT being counted, not a filter.

    Treating bare floor language as a condition is what let a generic question
    be refused for failing to resolve a floor. A qualifier is required.
    """
    assert ModifierKind.FLOOR_REFERENCE not in _kinds(question)


# ---------------------------------------------------------------------------
# The remaining structural modifier kinds (§2.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("show me the doors of type 'D2 ny'", "D2 ny"),
        ('walls with a rating of "EI60"', "EI60"),
    ],
)
def test_quoted_values_are_captured_exactly(question, expected):
    assert _of_kind(question, ModifierKind.QUOTED_VALUE) == [expected]


@pytest.mark.parametrize(
    "question",
    [
        "show me all doors wider than 1 metre",
        "walls taller than 3m",
        "spaces larger than 20 m2",
        "rooms with at least 2 windows",
        "anything under 500mm",
    ],
)
def test_comparison_language_is_material(question):
    spans = [s for s in detect_spans(question) if s.kind is ModifierKind.COMPARISON]
    assert spans and all(s.material for s in spans)


@pytest.mark.parametrize(
    ("question", "unit"),
    [
        ("doors wider than 1 metre", "metre"),
        ("walls over 900mm", "mm"),
        ("spaces above 20 m2", "m2"),
        ("openings beyond 90 degrees", "degrees"),
    ],
)
def test_numeric_bounds_and_units_are_detected(question, unit):
    kinds = _kinds(question)
    assert ModifierKind.NUMERIC_BOUND in kinds
    assert unit in [u.lower() for u in _of_kind(question, ModifierKind.UNIT)]


@pytest.mark.parametrize(
    "question",
    [
        "how many walls are not load bearing?",
        "doors without a fire rating",
        "show non load-bearing columns",
        "every wall except the external ones",
    ],
)
def test_negation_is_material(question):
    spans = [s for s in detect_spans(question) if s.kind is ModifierKind.NEGATION]
    assert spans and all(s.material for s in spans)


@pytest.mark.parametrize(
    "question",
    [
        "how many of those are external?",
        "which of these are load bearing",
        "show me the previous result again",
    ],
)
def test_previous_result_references_are_material(question):
    spans = [s for s in detect_spans(question) if s.kind is ModifierKind.PREVIOUS_RESULT_REFERENCE]
    assert spans and all(s.material for s in spans)


@pytest.mark.parametrize(
    "question",
    [
        "what is the area of the selected objects",
        "describe these objects",
        "show highlighted walls",
    ],
)
def test_selection_references_are_material(question):
    spans = [s for s in detect_spans(question) if s.kind is ModifierKind.SELECTION_REFERENCE]
    assert spans and all(s.material for s in spans)


# ---------------------------------------------------------------------------
# Bounds and determinism
# ---------------------------------------------------------------------------


def test_spans_are_ordered_by_position_and_deterministic():
    q = "show me external doors wider than 1 metre on the second floor of this building"
    first = detect_spans(q)
    assert [s.start for s in first] == sorted(s.start for s in first)
    assert first == detect_spans(q)


def test_span_count_is_bounded():
    q = " ".join(["not over 1m on the second floor of this building"] * 40)
    assert len(detect_spans(q)) <= 24


def test_source_spans_index_back_into_the_question():
    """§2.2 requires an EXACT source span from the current question; offsets
    must therefore actually address the original text."""
    q = "show me all doors wider than 1 metre"
    for span in detect_spans(q):
        assert span.text.lower() in q[span.start : span.end].lower()


@pytest.mark.parametrize("question", ["", None, "   ", "asdkfj qwerty ??? ###"])
def test_degenerate_input_produces_no_spans_and_does_not_raise(question):
    assert detect_spans(question) == []


def test_material_spans_excludes_scope_references():
    spans = detect_spans("how many walls are in this building?")
    assert spans
    assert material_spans(spans) == []
