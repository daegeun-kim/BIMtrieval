"""The explanation payload on the response envelope (task26 §1.1, §7).

Offline: `QueryService._build_envelope` is exercised with hand-built pipeline
outcomes, so there is no DB, no OpenAI, and no embedding.

The point of these tests is the *hard backend boundary*: serializing a
presentation payload must leave the answer text, the answer facts, the viewer
totals, and the primary viewer identities exactly as they were.
"""

from __future__ import annotations

from app.api.schemas.request import SessionQueryRequest
from app.query.binding.evidence import AnswerPartResult, ResultExample, ResultStatus
from app.query.binding.pipeline import PipelineOutcome
from app.query.binding.viewer import HydratedIdentity, ViewerHydration
from app.query.service import QueryService


def _request():
    return SessionQueryRequest(
        question="how many doors are on floor 3", session_id="s1", active_source_model_id=1
    )


def _result(part_id="p1", operation="count", status=ResultStatus.EXACT, total=9, **kw):
    return AnswerPartResult(
        part_id=part_id,
        request_text="how many doors are on floor 3",
        operation=operation,
        status=status,
        exact_total=total,
        **kw,
    )


def _hydration(pairs=(("IfcDoor", "G1"), ("IfcDoor", "G2"), ("IfcWindow", "G3")), **kw):
    identities = [HydratedIdentity(global_id=g, ifc_class=c) for c, g in pairs]
    counts: dict[str, int] = {}
    for c, _ in pairs:
        counts[c] = counts.get(c, 0) + 1
    return ViewerHydration(
        primary_global_ids=[i.global_id for i in identities],
        primary_identities=identities,
        viewer_matches_total=kw.pop("viewer_matches_total", len(identities)),
        class_counts=kw.pop("class_counts", counts),
        **kw,
    )


def _outcome(results, hydration, primary_visual="p1", **kw):
    return PipelineOutcome(
        answer="There are 9 doors on floor 3.",
        results=list(results),
        hydration=hydration,
        primary_visual_part_id=primary_visual,
        **kw,
    )


def _envelope(outcome):
    return QueryService(llm_client=object())._build_envelope(_request(), "r1", outcome)


# ---------------------------------------------------------------------------


def test_envelope_carries_the_explanation_for_a_highlighted_answer():
    env = _envelope(_outcome([_result()], _hydration()))
    assert env.answer_explanation is not None
    assert env.answer_explanation.part_id == "p1"
    assert env.answer_explanation.exact_total == 9
    assert env.answer_explanation.answer_basis == env.answer_basis


def test_explanation_describes_the_visual_part_not_merely_the_first_part():
    """A multi-part answer highlights ONE part; the card must describe that one,
    or the panel and the viewer would disagree."""
    first = _result(part_id="p0", operation="count", total=205)
    visual = _result(part_id="p1", operation="list", total=9)
    env = _envelope(_outcome([first, visual], _hydration(), primary_visual="p1"))
    assert env.answer_explanation is not None
    assert env.answer_explanation.part_id == "p1"
    assert env.answer_explanation.exact_total == 9
    # …and the long-standing result_summary behavior is untouched.
    assert env.result_summary is not None
    assert env.result_summary.exact_total == 205


def test_clarification_response_exposes_no_explanation():
    outcome = PipelineOutcome(answer="Which floor did you mean?", needs_clarification=True)
    env = _envelope(outcome)
    assert env.answer_explanation is None
    assert env.route.value == "clarify"


def test_zero_result_exposes_no_explanation():
    env = _envelope(_outcome([_result(status=ResultStatus.ZERO, total=0)], ViewerHydration()))
    assert env.answer_explanation is None


def test_serializing_the_explanation_changes_no_answer_or_viewer_field():
    """The same outcome with and without a presentable highlight must produce
    identical answer/evidence/viewer content."""
    results = [_result(examples=[ResultExample(1, "G1", "IfcDoor", "Door 1")])]
    hydration = _hydration()
    env = _envelope(_outcome(results, hydration))

    assert env.answer_explanation is not None
    assert env.answer == "There are 9 doors on floor 3."
    assert env.evidence_summary.sql_match_count == 9
    assert env.result_summary is not None
    assert env.result_summary.exact_total == 9
    assert env.result_summary.viewer_matches_total == 3
    assert env.viewer_actions.primary_global_ids == ["G1", "G2", "G3"]
    # The explanation restates those identities; it never replaces or extends them.
    grouped = {g for group in env.answer_explanation.groups for g in group.global_ids}
    assert grouped == set(env.viewer_actions.primary_global_ids)


def test_truncated_viewer_set_is_disclosed_not_implied_exhaustive():
    hydration = _hydration(
        viewer_matches_total=1981,
        class_counts={"IfcDoor": 1900, "IfcWindow": 81},
        viewer_matches_truncated=True,
    )
    env = _envelope(_outcome([_result(total=1981)], hydration))
    assert env.answer_explanation is not None
    assert env.answer_explanation.true_result_count == 1981
    assert env.answer_explanation.shown_identity_count == 3
    assert env.answer_explanation.identities_truncated is True
    # Viewer totals are the pre-existing ones, unchanged.
    assert env.viewer_actions.viewer_matches_total == 1981
    assert env.viewer_actions.viewer_matches_truncated is True


def test_envelope_json_round_trips_and_stays_allowlisted():
    env = _envelope(_outcome([_result()], _hydration()))
    payload = env.model_dump(mode="json")
    assert "answer_explanation" in payload
    forbidden = {"canonical_json", "sql", "raw_sql", "predicate", "prompt", "embedding"}
    assert not (set(payload["answer_explanation"]) & forbidden)


# ---------------------------------------------------------------------------
# Task 29 — a non-qualifying result carries no payload, and carries nothing else
# away with it
# ---------------------------------------------------------------------------


def test_a_scalar_answer_keeps_its_full_response_and_omits_the_payload():
    """The gate removes only the panel. The answer, evidence, result summary and
    viewer identities of an aggregate answer are exactly what they were."""
    results = [_result(operation="aggregate", total=205)]
    hydration = _hydration()
    env = _envelope(_outcome(results, hydration))

    assert env.answer_explanation is None
    assert env.answer == "There are 9 doors on floor 3."
    assert env.result_summary is not None
    assert env.result_summary.exact_total == 205
    assert env.result_summary.viewer_matches_total == 3
    assert env.viewer_actions.primary_global_ids == ["G1", "G2", "G3"]
    assert env.viewer_actions.selection_action.value != "none"


def test_the_qualifying_and_non_qualifying_envelopes_differ_only_by_the_payload():
    hydration = _hydration()
    with_panel = _envelope(_outcome([_result(operation="count")], hydration))
    without_panel = _envelope(_outcome([_result(operation="existence")], hydration))

    a = with_panel.model_dump(mode="json")
    b = without_panel.model_dump(mode="json")
    for volatile in ("request_id", "answer_explanation"):
        a.pop(volatile, None)
        b.pop(volatile, None)
    assert a == b
    assert with_panel.answer_explanation is not None
    assert without_panel.answer_explanation is None


def test_a_partial_count_still_carries_the_count_table_and_its_limitation():
    result = _result(
        status=ResultStatus.PARTIAL,
        known_parts=["the door count"],
        unknown_parts=["fire rating"],
        limitation="fire rating is recorded on only some doors",
    )
    env = _envelope(_outcome([result], _hydration()))
    assert env.answer_explanation is not None
    assert env.answer_explanation.presentation.value == "result_table"
    assert env.answer_explanation.limitation == "fire rating is recorded on only some doors"
    assert env.answer_explanation.unknown_parts == ["fire rating"]
