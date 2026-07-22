"""End-to-end Task 24 pipeline against the REAL models, with FAKE LLMs.

Read-only, and **no OpenAI call is made** — `bind` and `answer` are injected, so
this exercises the complete flow (slate → bind → validate → execute → packet →
answer → validate → viewer) deterministically and for free.

That injection is also the point of several assertions: because the two model
calls are counted, the "exactly two principal LLM calls" property (§10.1) and
the "no third call on failure" property (§8.3) are testable facts rather than
claims about the code.

The whole package skips when the database is unreachable (see conftest).
"""

from __future__ import annotations

import pytest

from app.llm.schemas import (
    AnswerPart,
    BindingPlan,
    FactualClaim,
    GroundedAnswer,
    OutputOperation,
    ScopeKind,
)
from app.query.binding.evidence import ResultStatus
from app.query.binding.pipeline import PipelineRequest, run_pipeline
from app.query.binding.previous_scope import capture_previous_scope
from app.query.binding.slate import SlateInputs, build_slate

MODEL_IDS = (1, 2)


class _Calls:
    """Counts the two injected model calls."""

    def __init__(self, plan_for, answer_for):
        self.binds = 0
        self.answers = 0
        self._plan_for = plan_for
        self._answer_for = answer_for
        self.last_binder_context = None
        self.last_packet = None

    def bind(self, context):
        self.binds += 1
        self.last_binder_context = context
        return self._plan_for(context)

    def answer(self, payload):
        self.answers += 1
        self.last_packet = payload
        return self._answer_for(payload)


def _subject_id(session, model_id, question, ifc_class):
    slate = build_slate(session, SlateInputs(question=question, source_model_id=model_id))
    return next((c.candidate_id for c in slate.subjects if c.ifc_class == ifc_class), None)


def _count_plan(subject_id, request_text="how many walls"):
    return BindingPlan(
        answer_parts=[
            AnswerPart(
                part_id="p1",
                request_text=request_text,
                operation=OutputOperation.COUNT,
                subject_candidate_id=subject_id,
                scope_kind=ScopeKind.ACTIVE_MODEL,
                is_primary_visual=True,
            )
        ]
    )


def _faithful_answer(payload):
    """An answer that copies the packet's numbers exactly."""
    facts = payload.get("facts", [])
    total = next((f for f in facts if f["kind"] == "total"), None)
    if total is None:
        return GroundedAnswer(answer="No total was available.", answer_part_ids=["p1"])
    return GroundedAnswer(
        answer=f"There are {total['value']}.",
        answer_part_ids=["p1"],
        structured_claims=[FactualClaim(fact_id=total["id"], value=str(total["value"]))],
    )


def _run(session, model_id, plan_for, answer_for, **request_kw):
    calls = _Calls(plan_for, answer_for)
    outcome = run_pipeline(
        session,
        PipelineRequest(
            question="how many walls are in this building?", source_model_id=model_id, **request_kw
        ),
        bind=calls.bind,
        answer=calls.answer,
    )
    return outcome, calls


# ---------------------------------------------------------------------------
# The two-call guarantee (§10.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_normal_question_makes_exactly_two_model_calls(live_session, model_id):
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    outcome, calls = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    assert (calls.binds, calls.answers) == (1, 1)
    assert outcome.llm_calls == 2
    assert outcome.results[0].status is ResultStatus.EXACT


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_an_invalid_binding_makes_no_second_call_and_clarifies(live_session, model_id):
    """§3.3: an invalid binding must not trigger a second planning call."""
    invalid = BindingPlan(
        answer_parts=[
            AnswerPart(
                part_id="p1",
                request_text="how many walls",
                operation=OutputOperation.COUNT,
                subject_candidate_id="s999",  # not in the slate
            )
        ]
    )
    outcome, calls = _run(live_session, model_id, lambda c: invalid, _faithful_answer)
    assert calls.binds == 1
    assert calls.answers == 0, "an unexecutable binding must not reach the answering model"
    assert outcome.needs_clarification
    assert outcome.answer


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_an_invalid_answer_falls_back_without_a_third_call(live_session, model_id):
    """§8.3: no LLM call after validation failure; fall back to real results."""
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")

    def _fabricating_answer(payload):
        facts = payload.get("facts", [])
        total = next(f for f in facts if f["kind"] == "total")
        return GroundedAnswer(
            answer="There are 9999 walls.",
            answer_part_ids=["p1"],
            structured_claims=[FactualClaim(fact_id=total["id"], value="9999")],
        )

    outcome, calls = _run(
        live_session, model_id, lambda c: _count_plan(subject), _fabricating_answer
    )
    assert (calls.binds, calls.answers) == (1, 1), "no third call"
    assert outcome.used_fallback
    assert "9999" not in outcome.answer
    assert str(outcome.results[0].exact_total) in outcome.answer


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_plan_level_issue_blocks_execution_entirely(live_session, model_id):
    """Regression guard for a defect a LIVE smoke run caught.

    "How many parking spaces are there?" binds `IfcSpace` perfectly well — the
    PART is valid, and only the question-level qualifier "parking" is
    unaccounted for. The pipeline gate inspected per-part validity only, so the
    valid part executed and returned every space in the model, reproducing the
    worst recorded failure. Plan-level issues must block everything.
    """
    slate = build_slate(
        live_session,
        SlateInputs(question="how many parking spaces are there?", source_model_id=model_id),
    )
    space = next((c for c in slate.subjects if c.ifc_class == "IfcSpace"), None)
    if space is None:
        pytest.skip(f"model {model_id} offers no IfcSpace candidate for this question")

    plan = BindingPlan(
        answer_parts=[
            AnswerPart(
                part_id="p1",
                request_text="how many parking spaces",
                operation=OutputOperation.COUNT,
                subject_candidate_id=space.candidate_id,
            )
        ]
    )
    calls = _Calls(lambda c: plan, _faithful_answer)
    outcome = run_pipeline(
        live_session,
        PipelineRequest(question="how many parking spaces are there?", source_model_id=model_id),
        bind=calls.bind,
        answer=calls.answer,
    )
    assert outcome.needs_clarification
    assert calls.answers == 0
    assert not outcome.results, "no part may execute when the question was misread"
    assert "parking" in outcome.answer
    assert not outcome.hydration.has_selection


# ---------------------------------------------------------------------------
# Binder input boundary (§2.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_the_binder_never_receives_rows_identities_or_sql(live_session, model_id):
    import json

    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    _, calls = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    blob = json.dumps(calls.last_binder_context)
    for forbidden in ("canonical_json", "global_id", "GlobalId", "SELECT ", "embedding"):
        assert forbidden not in blob


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_the_answerer_never_receives_viewer_identities(live_session, model_id):
    import json

    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    outcome, calls = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    blob = json.dumps(calls.last_packet)
    assert outcome.hydration.primary_global_ids, "the viewer should have identities"
    for global_id in outcome.hydration.primary_global_ids[:20]:
        assert global_id not in blob


# ---------------------------------------------------------------------------
# Answer and viewer agree (§9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_viewer_total_equals_the_answer_total(live_session, model_id):
    """The defect this prevents: an answer naming 6 objects while 778 highlight."""
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    outcome, _ = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    assert outcome.hydration.viewer_matches_total == outcome.results[0].exact_total
    assert sum(outcome.hydration.class_counts.values()) == outcome.results[0].exact_total


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_zero_result_highlights_nothing(live_session, model_id):
    """§9: exact zero must not fall back to an unrelated highlight set."""
    slate = build_slate(
        live_session,
        SlateInputs(question="how many escalators are in this building?", source_model_id=model_id),
    )
    absent = next((c for c in slate.subjects if not c.present and c.result_kind), None)
    if absent is None:
        pytest.skip(f"model {model_id} offers no absent result-kind concept")

    plan = BindingPlan(
        answer_parts=[
            AnswerPart(
                part_id="p1",
                request_text="how many escalators",
                operation=OutputOperation.COUNT,
                subject_candidate_id=absent.candidate_id,
                is_primary_visual=True,
            )
        ]
    )
    calls = _Calls(lambda c: plan, _faithful_answer)
    outcome = run_pipeline(
        live_session,
        PipelineRequest(
            question="how many escalators are in this building?", source_model_id=model_id
        ),
        bind=calls.bind,
        answer=calls.answer,
    )
    assert outcome.results[0].status is ResultStatus.ZERO
    assert not outcome.hydration.has_selection


# ---------------------------------------------------------------------------
# Typed previous scope (§7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_followup_reuses_the_COMPLETE_previous_scope(live_session, model_id):
    """§7: 'Do not scope a large follow-up to the first 50 or 200 previous IDs.'

    The stored scope is re-executed, so the follow-up covers every object of the
    previous result — even when that result is far larger than any id cap.
    """
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")

    outcome, _ = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    scope = outcome.next_scope
    assert scope is not None

    from app.query.binding.previous_scope import resolve_previous_entity_ids

    ids = resolve_previous_entity_ids(live_session, scope, model_id)
    assert len(ids) == outcome.results[0].exact_total
    # The whole point: not truncated to a session cap.
    if outcome.results[0].exact_total > 200:
        assert len(ids) > 200


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_previous_scope_from_another_model_is_discarded(live_session, model_id):
    """§7: clear the scope when the stored source model does not match."""
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    outcome, _ = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)

    from app.query.binding.previous_scope import resolve_previous_entity_ids

    other_model = 2 if model_id == 1 else 1
    assert resolve_previous_entity_ids(live_session, outcome.next_scope, other_model) == []


def test_an_unavailable_result_produces_no_followup_scope():
    """A result that describes no set of objects cannot be followed up."""
    from app.query.binding.evidence import AnswerPartResult

    unavailable = AnswerPartResult(
        part_id="p1",
        request_text="u-values",
        operation="count",
        status=ResultStatus.UNAVAILABLE,
    )
    assert capture_previous_scope(unavailable) is None


# ---------------------------------------------------------------------------
# Diagnostics (§10.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_every_required_stage_is_measured(live_session, model_id):
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    outcome, _ = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    for stage in (
        "slate_build_ms",
        "binding_llm_ms",
        "binding_validation_ms",
        "execution_ms",
        "packet_build_ms",
        "answer_llm_ms",
        "answer_validation_ms",
        "viewer_hydration_ms",
    ):
        assert stage in outcome.stage_ms, f"{stage} not measured"
    assert outcome.slate_bytes > 0
    assert outcome.packet_bytes > 0
    assert outcome.statement_count > 0


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_simple_question_stays_cheap_in_database_statements(live_session, model_id):
    """§10.3: no sequential exact query per semantic candidate."""
    subject = _subject_id(live_session, model_id, "how many walls are in this building?", "IfcWall")
    if subject is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    outcome, _ = _run(live_session, model_id, lambda c: _count_plan(subject), _faithful_answer)
    assert outcome.statement_count <= 8, outcome.statement_count
