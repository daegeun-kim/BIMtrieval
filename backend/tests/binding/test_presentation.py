"""The Task 26 presentation payload (task26 §1.1, §7).

Offline: results and hydrations are constructed directly, so no DB, no OpenAI,
no embedding.

The property under test is that the payload is *strictly derivative*. It may
restate what the pipeline already established for the accepted answer and
nothing else — no re-query, no fresh breakdown, no invented subgroup, and no
shown count passed off as a true count.
"""

from __future__ import annotations

import inspect

import pytest

from app.api.schemas.response import ExplanationPresentation
from app.query.binding import presentation as presentation_module
from app.query.binding.evidence import (
    AggregateValue,
    AnswerPartResult,
    DistributionBucket,
    ResultExample,
    ResultStatus,
    RetrievalMode,
)
from app.query.binding.presentation import build_answer_explanation, select_visual_result
from app.query.binding.viewer import HydratedIdentity, ViewerHydration
from app.shared.types import AnswerBasis


def _result(
    part_id="p1",
    request="how many doors are on floor 3",
    operation="count",
    status=ResultStatus.EXACT,
    total=9,
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


def _hydration(classes=(("IfcDoor", "G1"), ("IfcDoor", "G2"), ("IfcWindow", "G3")), **kw):
    identities = [HydratedIdentity(global_id=g, ifc_class=c) for c, g in classes]
    counts: dict[str, int] = {}
    for c, _ in classes:
        counts[c] = counts.get(c, 0) + 1
    return ViewerHydration(
        primary_global_ids=[i.global_id for i in identities],
        primary_identities=identities,
        viewer_matches_total=kw.pop("viewer_matches_total", len(identities)),
        class_counts=kw.pop("class_counts", counts),
        **kw,
    )


def _build(result, hydration=None, basis=AnswerBasis.EXACT_SQL):
    return build_answer_explanation(result, hydration or _hydration(), basis)


# ---------------------------------------------------------------------------
# It cannot compute anything
# ---------------------------------------------------------------------------


def test_builder_takes_no_session_so_it_cannot_query():
    """The strongest available guarantee that no extra breakdown is calculated
    for presentation: the function has no way to reach the database."""
    params = set(inspect.signature(build_answer_explanation).parameters)
    assert "session" not in params
    # Checks the module's imports, not its prose: the docstring legitimately
    # names `Session` in order to say the module does not take one.
    imports = [
        line
        for line in inspect.getsource(presentation_module).splitlines()
        if line.startswith(("import ", "from "))
    ]
    for forbidden in ("sqlalchemy", "session", "execute", "compiler", "llm"):
        assert not any(forbidden in line.lower() for line in imports), forbidden


def test_no_extra_class_breakdown_is_invented():
    """A part with no class breakdown of its own reuses the breakdown viewer
    hydration already produced — it never computes a second one."""
    explanation = _build(_result())
    assert explanation is not None
    assert explanation.class_breakdown == {"IfcDoor": 2, "IfcWindow": 1}


# ---------------------------------------------------------------------------
# Derived from the primary VISUAL part
# ---------------------------------------------------------------------------


def test_visual_part_is_selected_not_the_first_part():
    summary = _result(part_id="p0", operation="count", total=100)
    visual = _result(part_id="p1", operation="list", total=9)
    chosen = select_visual_result([summary, visual], "p1")
    assert chosen is visual


def test_non_visual_parts_are_never_selected():
    zero = _result(part_id="p0", status=ResultStatus.ZERO, total=0)
    unavailable = _result(part_id="p1", status=ResultStatus.UNAVAILABLE, total=None)
    assert select_visual_result([zero, unavailable], None) is None


def test_no_explanation_without_a_visual_part():
    zero = _result(status=ResultStatus.ZERO, total=0)
    assert build_answer_explanation(zero, _hydration(), AnswerBasis.EXACT_SQL) is None


def test_no_explanation_without_highlighted_objects():
    """A clarification or no-highlight response must not carry a stale panel."""
    assert build_answer_explanation(_result(), ViewerHydration(), AnswerBasis.EXACT_SQL) is None
    assert build_answer_explanation(None, _hydration(), AnswerBasis.EXACT_SQL) is None


# ---------------------------------------------------------------------------
# Presentation choice (§4.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation,expected",
    [
        ("count", ExplanationPresentation.METRIC),
        ("existence", ExplanationPresentation.METRIC),
        ("list", ExplanationPresentation.TABLE),
        ("sample_detail", ExplanationPresentation.TABLE),
        ("group_distribution", ExplanationPresentation.DISTRIBUTION),
        ("aggregate", ExplanationPresentation.AGGREGATE),
        ("extremum", ExplanationPresentation.AGGREGATE),
        ("relationship", ExplanationPresentation.RELATIONSHIP),
        ("description", ExplanationPresentation.TABLE),
    ],
)
def test_presentation_follows_the_authoritative_operation(operation, expected):
    explanation = _build(_result(operation=operation))
    assert explanation is not None
    assert explanation.presentation is expected


def test_partial_status_outranks_the_operation():
    explanation = _build(
        _result(
            status=ResultStatus.PARTIAL,
            known_parts=["door count"],
            unknown_parts=["fire rating"],
        )
    )
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.PARTIAL
    assert explanation.known_parts == ["door count"]
    assert explanation.unknown_parts == ["fire rating"]


# ---------------------------------------------------------------------------
# Truthful counts and bounded identities
# ---------------------------------------------------------------------------


def test_truncation_keeps_the_true_total_and_discloses_the_shown_count():
    hydration = _hydration(
        viewer_matches_total=1981,
        class_counts={"IfcDoor": 1900, "IfcWindow": 81},
        viewer_matches_truncated=True,
    )
    explanation = _build(_result(total=1981), hydration)
    assert explanation is not None
    assert explanation.true_result_count == 1981
    assert explanation.shown_identity_count == 3
    assert explanation.identities_truncated is True


def test_group_keeps_its_exact_count_when_identities_are_capped():
    hydration = _hydration(
        viewer_matches_total=1981,
        class_counts={"IfcDoor": 1900, "IfcWindow": 81},
        viewer_matches_truncated=True,
    )
    explanation = _build(_result(total=1981), hydration)
    assert explanation is not None
    doors = next(g for g in explanation.groups if g.key == "IfcDoor")
    assert doors.exact_count == 1900
    assert doors.shown_count == 2
    assert doors.truncated is True
    assert doors.global_ids == ["G1", "G2"]


def test_groups_are_a_subset_of_the_highlighted_identities():
    hydration = _hydration()
    explanation = _build(_result(), hydration)
    assert explanation is not None
    highlighted = set(hydration.primary_global_ids)
    for group in explanation.groups:
        assert set(group.global_ids) <= highlighted
    # and every highlighted object belongs to exactly one group
    grouped = [g for group in explanation.groups for g in group.global_ids]
    assert sorted(grouped) == sorted(hydration.primary_global_ids)


def test_no_groups_are_offered_without_authoritative_class_membership():
    """Identities with no class information yield no selectable group at all —
    never a guessed one."""
    hydration = ViewerHydration(
        primary_global_ids=["G1", "G2"],
        viewer_matches_total=2,
        class_counts={"IfcDoor": 2},
    )
    explanation = _build(_result(), hydration)
    assert explanation is not None
    assert explanation.groups == []


def test_distribution_buckets_are_shown_but_carry_no_identities():
    explanation = _build(
        _result(
            operation="group_distribution",
            distribution=[
                DistributionBucket(key="Floor 1", count=120),
                DistributionBucket(key=None, count=4),
            ],
        )
    )
    assert explanation is not None
    assert [b.key for b in explanation.distribution] == ["Floor 1", "(not recorded)"]
    assert not hasattr(explanation.distribution[0], "global_ids")


def test_rows_are_bounded_and_come_from_already_retrieved_examples():
    examples = [
        ResultExample(entity_id=i, global_id=f"E{i}", ifc_class="IfcDoor", name=f"D{i}")
        for i in range(200)
    ]
    explanation = _build(_result(operation="list", examples=examples))
    assert explanation is not None
    assert len(explanation.rows) == presentation_module.MAX_EXPLANATION_ROWS
    assert explanation.rows[0].global_id == "E0"


def test_relationship_rows_are_the_traversal_endpoints():
    endpoints = [
        ResultExample(entity_id=1, global_id="R1", ifc_class="IfcSpace", name="Office"),
        ResultExample(entity_id=2, global_id="R2", ifc_class="IfcSpace", name="Hall"),
    ]
    explanation = _build(_result(operation="relationship", graph_endpoints=endpoints))
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.RELATIONSHIP
    assert explanation.relationship_endpoint_total == 2
    assert [r.global_id for r in explanation.rows] == ["R1", "R2"]


def test_aggregate_coverage_is_carried_through_unchanged():
    explanation = _build(
        _result(
            operation="aggregate",
            aggregate=AggregateValue(
                function="sum", value=812.5, unit="m2", coverage_count=180, matched_count=205
            ),
        )
    )
    assert explanation is not None
    assert explanation.aggregate is not None
    assert explanation.aggregate.value == 812.5
    assert explanation.aggregate.unit == "m2"
    assert explanation.aggregate.coverage_count == 180
    assert explanation.aggregate.matched_count == 205
    assert explanation.aggregate.complete is False


def test_limitation_interpretation_and_modes_are_restated_verbatim():
    explanation = _build(
        _result(
            interpretation="doors whose storey is the third elevation band",
            limitation="fire rating is recorded on only some doors",
            modes_executed=(RetrievalMode.SQL,),
        )
    )
    assert explanation is not None
    assert explanation.interpretation == "doors whose storey is the third elevation band"
    assert explanation.limitation == "fire rating is recorded on only some doors"
    assert explanation.retrieval_modes == ["sql"]
    assert explanation.request_label == "how many doors are on floor 3"


def test_payload_forbids_unknown_fields():
    """Allowlisted: a future field cannot be smuggled onto the payload."""
    explanation = _build(_result())
    assert explanation is not None
    with pytest.raises(Exception):
        type(explanation)(**{**explanation.model_dump(), "raw_sql": "SELECT 1"})
