"""The presentation payload and its opening gate (task29 §2, §3, §4; task26 §1.1).

Offline: results and hydrations are constructed directly, so no DB, no OpenAI,
no embedding.

Two properties are under test. First, the payload is *strictly derivative* — it
may restate what the pipeline already established for the accepted answer and
nothing else: no re-query, no fresh breakdown, no invented subgroup, and no shown
count passed off as a true count. Second, Task 29's gate: the panel opens only
when a supported presentation is genuinely supplemented by structured data, and
a scalar, measurement or qualitative answer opens nothing at all.
"""

from __future__ import annotations

import inspect

import pytest

from app.api.schemas.response import ExplanationPresentation
from app.config.settings import Settings
from app.query.binding import presentation as presentation_module
from app.query.binding import topology as topology_module
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


@pytest.mark.parametrize("module", [presentation_module, topology_module])
def test_presentation_code_cannot_reach_a_database_or_the_llm(module):
    """The strongest available guarantee that no extra breakdown, lookup or
    traversal is performed for presentation: neither module can reach one."""
    params = set(inspect.signature(build_answer_explanation).parameters)
    assert "session" not in params
    # Checks the modules' imports, not their prose: the docstrings legitimately
    # name `Session` in order to say they do not take one.
    imports = [
        line
        for line in inspect.getsource(module).splitlines()
        if line.startswith(("import ", "from "))
    ]
    for forbidden in (
        "sqlalchemy",
        "session",
        "execute",
        "compiler",
        "llm",
        # The traversal itself, and the module that runs it: the topology must be
        # a copy of hops already returned, never a second traversal (task29 §5.1).
        "graph.traversal",
        "graph_exec",
    ):
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


@pytest.mark.parametrize(
    "status", [ResultStatus.ZERO, ResultStatus.UNAVAILABLE, ResultStatus.AMBIGUOUS]
)
def test_non_presentable_statuses_never_open_the_panel(status):
    """§2: zero, unavailable and ambiguous results never open the panel — even
    if a stale total and a highlight were somehow present together."""
    result = _result(status=status, total=9)
    assert build_answer_explanation(result, _hydration(), AnswerBasis.EXACT_SQL) is None


# ---------------------------------------------------------------------------
# The fixed operation/data mapping (§2.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["count", "list"])
def test_count_and_list_select_a_result_table(operation):
    explanation = _build(_result(operation=operation))
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.RESULT_TABLE


def test_count_rows_come_from_the_already_hydrated_viewer_identities():
    """§3.1: the table is built from identities the viewer already received,
    with existing example metadata merged in by GlobalId — never a new query."""
    result = _result(
        examples=[ResultExample(1, "G2", "IfcDoor", "Door two", "Floor 3")],
    )
    explanation = _build(result)
    assert explanation is not None
    assert [r.global_id for r in explanation.rows] == ["G1", "G2", "G3"]
    merged = next(r for r in explanation.rows if r.global_id == "G2")
    assert (merged.name, merged.storey_name) == ("Door two", "Floor 3")
    # GlobalId plus IFC class is a sufficient row where no example existed.
    bare = next(r for r in explanation.rows if r.global_id == "G1")
    assert (bare.ifc_class, bare.name) == ("IfcDoor", None)


def test_every_hydrated_identity_becomes_a_row(monkeypatch):
    """task31 §4.1: the former 50-row terminal ceiling is gone.

    Every authoritative row the response's hydrated identities represent is made
    available to the frontend, which displays them 50 at a time. The order is the
    hydration order — the "original backend order" the frontend's sort cycle
    restores.
    """
    pairs = tuple(("IfcDoor", f"G{i}") for i in range(200))
    explanation = _build(_result(total=200), _hydration(pairs))
    assert explanation is not None
    assert len(explanation.rows) == 200
    assert [r.global_id for r in explanation.rows[:3]] == ["G0", "G1", "G2"]


def test_rows_remain_bounded_by_the_viewer_identity_cap(monkeypatch):
    """task31 §4.1: bounded by hydration, never an unbounded result transport."""
    assert presentation_module.MAX_EXPLANATION_ROWS == 2000
    assert presentation_module.MAX_EXPLANATION_ROWS == Settings().max_viewer_match_ids

    monkeypatch.setattr(presentation_module, "MAX_EXPLANATION_ROWS", 5)
    pairs = tuple(("IfcDoor", f"G{i}") for i in range(20))
    explanation = _build(_result(total=20), _hydration(pairs))
    assert explanation is not None
    assert len(explanation.rows) == 5
    assert explanation.rows[0].global_id == "G0"


def test_the_true_total_stays_independent_of_the_row_list():
    """task31 §4.1: a capped identity set never reduces the reported result."""
    pairs = tuple(("IfcDoor", f"G{i}") for i in range(30))
    hydration = _hydration(pairs)
    hydration.viewer_matches_total = 7431
    hydration.viewer_matches_truncated = True
    explanation = _build(_result(total=7431), hydration)
    assert explanation is not None
    assert len(explanation.rows) == 30
    assert explanation.shown_identity_count == 30
    assert explanation.true_result_count == 7431
    assert explanation.identities_truncated is True


def test_a_count_without_authoritative_displayed_identities_stays_in_chat():
    """§2.1: a count with no identifiable object set gets no table."""
    hydration = ViewerHydration(
        primary_global_ids=["G1", "G2"], viewer_matches_total=2, class_counts={"IfcDoor": 2}
    )
    assert _build(_result(), hydration) is None


def test_two_bucket_distribution_selects_horizontal_bars():
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
    assert explanation.presentation is ExplanationPresentation.BAR_CHART
    assert [b.key for b in explanation.distribution] == ["Floor 1", "(not recorded)"]


def test_one_bucket_distribution_selects_a_group_table():
    explanation = _build(
        _result(
            operation="group_distribution",
            distribution=[DistributionBucket(key="Floor 1", count=120)],
        )
    )
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.GROUP_TABLE


def test_a_distribution_with_no_buckets_opens_nothing():
    assert _build(_result(operation="group_distribution")) is None


@pytest.mark.parametrize(
    "operation", ["existence", "sample_detail", "aggregate", "extremum", "description"]
)
def test_scalar_measurement_and_qualitative_operations_open_no_panel(operation):
    """§2.1: these answers gain nothing from a supporting visualization, and
    `sample_detail` keeps the existing component/detail behavior."""
    result = _result(
        operation=operation,
        aggregate=AggregateValue(
            function="sum", value=812.5, unit="m2", coverage_count=180, matched_count=205
        ),
    )
    assert _build(result) is None


def test_comparison_without_a_structured_payload_opens_no_panel():
    assert _build(_result(operation="comparison")) is None


def test_comparison_with_a_homogeneous_numeric_series_selects_bars():
    explanation = _build(
        _result(
            operation="comparison",
            distribution=[
                DistributionBucket(key="Floor 1", count=2, value=120.0),
                DistributionBucket(key="Floor 2", count=2, value=61.0),
            ],
            aggregate=AggregateValue(
                function="sum", value=181.0, unit="m2", coverage_count=4, matched_count=4
            ),
        )
    )
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.BAR_CHART
    assert explanation.chart_unit == "m2"


def test_comparison_with_heterogeneous_values_selects_a_comparison_table():
    explanation = _build(
        _result(
            operation="comparison",
            distribution=[
                DistributionBucket(key="Floor 1", count=2, value=120.0),
                DistributionBucket(key="Floor 2", count=2, value=None),
            ],
        )
    )
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.COMPARISON_TABLE
    assert explanation.chart_unit is None


def test_an_unknown_operation_opens_no_panel():
    assert _build(_result(operation="something_new")) is None


def test_the_selector_never_chooses_a_task26_presentation():
    """Legacy enum values stay accepted for older clients but are never emitted."""
    legacy = {
        ExplanationPresentation.METRIC,
        ExplanationPresentation.TABLE,
        ExplanationPresentation.DISTRIBUTION,
        ExplanationPresentation.AGGREGATE,
        ExplanationPresentation.RELATIONSHIP,
        ExplanationPresentation.PARTIAL,
    }
    chosen = set()
    for operation in (
        "count",
        "list",
        "group_distribution",
        "relationship",
        "comparison",
        "existence",
        "aggregate",
        "extremum",
        "description",
        "sample_detail",
    ):
        explanation = _build(
            _result(
                operation=operation,
                distribution=[
                    DistributionBucket(key="a", count=2),
                    DistributionBucket(key="b", count=1),
                ],
                graph_endpoints=[ResultExample(1, "G1", "IfcSpace", "Office")],
            )
        )
        if explanation is not None:
            chosen.add(explanation.presentation)
    assert not (chosen & legacy), chosen & legacy


# ---------------------------------------------------------------------------
# `partial` is a modifier, not a presentation (§2)
# ---------------------------------------------------------------------------


def test_partial_keeps_the_base_operations_presentation_and_its_limitation():
    explanation = _build(
        _result(
            status=ResultStatus.PARTIAL,
            known_parts=["door count"],
            unknown_parts=["fire rating"],
            limitation="fire rating is recorded on only some doors",
        )
    )
    assert explanation is not None
    assert explanation.presentation is ExplanationPresentation.RESULT_TABLE
    assert explanation.known_parts == ["door count"]
    assert explanation.unknown_parts == ["fire rating"]
    assert explanation.limitation == "fire rating is recorded on only some doors"


def test_partial_status_does_not_open_a_panel_for_a_non_qualifying_operation():
    result = _result(
        operation="aggregate",
        status=ResultStatus.PARTIAL,
        known_parts=["total area"],
        unknown_parts=["fire rating"],
    )
    assert _build(result) is None


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
    never a guessed one. Here they also fail the row gate, so nothing opens."""
    hydration = ViewerHydration(
        primary_global_ids=["G1", "G2"],
        viewer_matches_total=2,
        class_counts={"IfcDoor": 2},
    )
    assert _build(_result(), hydration) is None


def test_a_single_class_result_shows_no_group_summary():
    """§3.1: one row of a breakdown is not a breakdown, so no bars fill space."""
    explanation = _build(_result(), _hydration((("IfcDoor", "G1"), ("IfcDoor", "G2"))))
    assert explanation is not None
    assert explanation.groups == []


def test_distribution_buckets_carry_no_identities():
    explanation = _build(
        _result(
            operation="group_distribution",
            distribution=[
                DistributionBucket(key="Floor 1", count=120),
                DistributionBucket(key="Floor 2", count=61),
            ],
        )
    )
    assert explanation is not None
    assert not hasattr(explanation.distribution[0], "global_ids")


def test_relationship_rows_are_the_traversal_endpoints():
    endpoints = [
        ResultExample(entity_id=1, global_id="R1", ifc_class="IfcSpace", name="Office"),
        ResultExample(entity_id=2, global_id="R2", ifc_class="IfcSpace", name="Hall"),
    ]
    explanation = _build(_result(operation="relationship", graph_endpoints=endpoints))
    assert explanation is not None
    # No topology hops were recorded, so the endpoint table is the presentation.
    assert explanation.presentation is ExplanationPresentation.RELATIONSHIP_TABLE
    assert explanation.relationship_endpoint_total == 2
    assert [r.global_id for r in explanation.rows] == ["R1", "R2"]
    assert explanation.presentation_fallback_reason is not None


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
