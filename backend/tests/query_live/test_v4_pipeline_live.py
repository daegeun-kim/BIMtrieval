"""task26 §17.2/§17.6/§17.9 — v4 compiler + validation + execution against the
REAL models, with injected typed plans (no OpenAI call).

Read-only. The whole package skips when the database is unreachable. These
assert the audited ground-truth repairs from the task's failure taxonomy:
relationship-backed floor membership, covered fire-rated distribution, grouped
argmax, a true one-sample result, and effective-membership space counts.
"""

from __future__ import annotations

import pytest

from app.llm.schemas_v2 import (
    AggregateFunction,
    AggregateNode,
    AnswerPartV2,
    DispositionKind,
    FilterNode,
    GroupNode,
    LogicalOperator,
    LogicalPlan,
    OrderNode,
    RequirementDisposition,
    ResultKind,
    ScopeKindV2,
    ScopeNode,
    TargetNode,
    ViewerSetPolicy,
)
from app.query.binding.compile_v2 import compile_part
from app.query.binding.execute_v2 import ExecutionContextV2, execute_part
from app.query.binding.ledger_v2 import build_ledger_skeleton
from app.query.binding.recall import resolve_ledger, run_recall
from app.query.binding.results_v2 import (
    DistributionResult,
    EntitySetResult,
    ResultStatusV2,
    SampleResult,
)
from app.query.binding.validate_v2 import GateStateV2, validate_plan
from app.query.semantic.manifest_v002 import get_manifest_v002

MODEL_2 = 2


@pytest.fixture(scope="module")
def manifest2(live_session):
    return get_manifest_v002(live_session, MODEL_2)


def _first_occupiable_band(manifest):
    return manifest.floors.band_for_ordinal(1)


def _compile_and_run(live_session, manifest, part):
    ledger = build_ledger_skeleton(part.request_text)
    recall = run_recall(live_session, manifest, ledger, embedding_service_getter=None)
    resolve_ledger(ledger, recall, manifest)
    compiled = compile_part(live_session, part, manifest)
    context = ExecutionContextV2(live_session, manifest, embedding_service_getter=None)
    return execute_part(compiled, part.request_text, context)


# ---------------------------------------------------------------------------
# §17.2 — relationship-backed floor membership (the false-zero repair)
# ---------------------------------------------------------------------------


def test_all_model2_spaces_resolve_through_effective_membership(live_session, manifest2):
    summary = manifest2.spatial_by_class.get("IfcSpace")
    assert summary is not None
    assert summary.total_count == 778
    # Every space resolves through effective membership despite a null scalar.
    assert summary.effective_count == 778
    assert summary.direct_count == 0


def test_spaces_on_a_floor_are_not_a_false_zero(live_session, manifest2):
    band = _first_occupiable_band(manifest2)
    part = AnswerPartV2(
        part_id="P1",
        request_text="how many spaces are on the first floor?",
        result_kind=ResultKind.ENTITY_SET,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcSpace"),
        scope=ScopeNode(node_id="s1", kind=ScopeKindV2.FLOOR_BAND, semantic_id=band.semantic_id),
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    result = _compile_and_run(live_session, manifest2, part)
    assert result.status is ResultStatusV2.EXACT
    assert isinstance(result.result, EntitySetResult)
    assert result.result.matched_cardinality > 0  # not a scalar-path zero


def test_walls_on_first_floor_match_audited_count(live_session, manifest2):
    band = _first_occupiable_band(manifest2)
    part = AnswerPartV2(
        part_id="P1",
        request_text="how many walls are on the first floor?",
        result_kind=ResultKind.ENTITY_SET,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcWall"),
        scope=ScopeNode(node_id="s1", kind=ScopeKindV2.FLOOR_BAND, semantic_id=band.semantic_id),
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    result = _compile_and_run(live_session, manifest2, part)
    assert result.status is ResultStatusV2.EXACT
    # Audited ground truth: 203 wall occurrences in the first occupiable band.
    assert result.result.matched_cardinality == 203


# ---------------------------------------------------------------------------
# §17.6 — is_present distribution vs scanned total (fire-rated repair)
# ---------------------------------------------------------------------------


def test_fire_rated_walls_report_the_covered_count_not_all_walls(live_session, manifest2):
    part = AnswerPartV2(
        part_id="P1",
        request_text="how many fire rated walls are there?",
        result_kind=ResultKind.ENTITY_SET,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcWall"),
        filters=[
            FilterNode(
                node_id="f1",
                semantic_id="prop:Pset_WallCommon.FireRating",
                operator=LogicalOperator.IS_PRESENT,
            )
        ],
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    result = _compile_and_run(live_session, manifest2, part)
    # Audited ground truth: 720 walls carry a rating, not all ~1981.
    assert result.result.matched_cardinality == 720
    assert result.result.scanned_cardinality > result.result.matched_cardinality


def test_is_present_produces_a_real_predicate_not_none(live_session, manifest2):
    part = AnswerPartV2(
        part_id="P1",
        request_text="walls with a fire rating",
        result_kind=ResultKind.ENTITY_SET,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcWall"),
        filters=[
            FilterNode(
                node_id="f1",
                semantic_id="prop:Pset_WallCommon.FireRating",
                operator=LogicalOperator.IS_MISSING,
            )
        ],
        viewer_set=ViewerSetPolicy.NONE,
    )
    compiled = compile_part(live_session, part, manifest2)
    assert compiled.filter_expr is not None  # is_missing did not disappear


# ---------------------------------------------------------------------------
# §17.6 — grouped argmax (which floor has the most doors)
# ---------------------------------------------------------------------------


def test_grouped_argmax_returns_a_floor_not_the_global_total(live_session, manifest2):
    part = AnswerPartV2(
        part_id="P1",
        request_text="which floor has the most doors?",
        result_kind=ResultKind.DISTRIBUTION,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcDoor"),
        group=GroupNode(node_id="g1", semantic_id="spatial:floor_membership"),
        aggregate=AggregateNode(node_id="a1", function=AggregateFunction.COUNT),
        order=OrderNode(node_id="o1", by="aggregate", direction="desc"),
        limit=1,
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    result = _compile_and_run(live_session, manifest2, part)
    assert result.status is ResultStatusV2.EXACT
    assert isinstance(result.result, DistributionResult)
    assert result.result.top_buckets
    top = result.result.top_buckets[0]
    # The winning floor's count is far below the global 551 door total.
    assert 0 < top.count < result.result.base_cardinality


# ---------------------------------------------------------------------------
# §17.6 — a true one-sample result
# ---------------------------------------------------------------------------


def test_sample_reports_one_not_the_eligible_total(live_session, manifest2):
    part = AnswerPartV2(
        part_id="P1",
        request_text="show me one example of a door",
        result_kind=ResultKind.SAMPLE,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcDoor"),
        limit=1,
        viewer_set=ViewerSetPolicy.SAMPLE,
    )
    result = _compile_and_run(live_session, manifest2, part)
    assert result.status is ResultStatusV2.EXACT
    assert isinstance(result.result, SampleResult)
    assert result.result.eligible_cardinality > 1
    assert result.result.answer_cardinality == 1
    assert result.viewer_sample is not None


# ---------------------------------------------------------------------------
# §17.5 — validation catches an incompatible-class field before SQL
# ---------------------------------------------------------------------------


def test_a_wrong_class_field_fails_applicability_before_sql(live_session, manifest2):
    # Pset_DoorCommon fields do not apply to walls.
    door_field = next(
        (c for c in manifest2.capabilities if c.startswith("prop:Pset_DoorCommon.")),
        None,
    )
    if door_field is None:
        pytest.skip("model has no Pset_DoorCommon field to misuse")
    part = AnswerPartV2(
        part_id="P1",
        request_text="walls with a door reference",
        result_kind=ResultKind.ENTITY_SET,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcWall"),
        filters=[
            FilterNode(node_id="f1", semantic_id=door_field, operator=LogicalOperator.IS_PRESENT)
        ],
    )
    ledger = build_ledger_skeleton(part.request_text)
    plan = LogicalPlan(
        answer_parts=[part],
        dispositions=[
            RequirementDisposition(
                requirement_id="L1",
                disposition=DispositionKind.BOUND,
                part_id="P1",
                node_ids=["t1", "f1"],
            )
        ],
    )
    validation = validate_plan(live_session, plan, ledger, manifest2)
    codes = {i.code for i in validation.all_issues()}
    assert "MANIFEST_APPLICABILITY_ERROR" in codes


# ---------------------------------------------------------------------------
# §17.5 — an exact zero requires a coverage proof
# ---------------------------------------------------------------------------


def test_partial_coverage_filter_cannot_prove_a_false_zero(live_session, manifest2):
    fire = manifest2.capabilities["prop:Pset_WallCommon.FireRating"]
    part = AnswerPartV2(
        part_id="P1",
        request_text="how many walls are rated ZZ999?",
        result_kind=ResultKind.ENTITY_SET,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcWall"),
        filters=[
            FilterNode(
                node_id="f1",
                semantic_id="prop:Pset_WallCommon.FireRating",
                operator=LogicalOperator.EQUALS,
                value_text="ZZ999-not-a-real-rating",
            )
        ],
        viewer_set=ViewerSetPolicy.NONE,
    )
    result = _compile_and_run(live_session, manifest2, part)
    # No wall has this rating, but the field is only partially covered, so this
    # is PARTIAL (cannot prove real-world absence), not an EXACT zero.
    assert result.status is ResultStatusV2.PARTIAL
