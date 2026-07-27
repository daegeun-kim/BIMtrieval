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
from app.query.binding.validate_v2 import validate_plan
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


# ---------------------------------------------------------------------------
# task27 §5 — the execution/evidence gaps the recorded traces proved
# ---------------------------------------------------------------------------


def test_a_material_distribution_executes_over_the_material_array(live_session, manifest2):
    """A grouped distribution over a multi-valued array field compiles and runs.

    The recorded run failed at dry compilation with "no scalar value expression
    for physical source 'materials'", so the question could not be answered at
    all.
    """
    part = AnswerPartV2(
        part_id="P1",
        request_text="what are the doors made of?",
        result_kind=ResultKind.DISTRIBUTION,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcDoor"),
        group=GroupNode(node_id="g1", semantic_id="mat:material.name"),
        aggregate=AggregateNode(node_id="a1", function=AggregateFunction.COUNT),
        order=OrderNode(node_id="o1"),
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    result = _compile_and_run(live_session, manifest2, part)
    assert result.status in (ResultStatusV2.EXACT, ResultStatusV2.PARTIAL)
    distribution = result.result
    assert isinstance(distribution, DistributionResult)
    assert len(distribution.buckets) > 1
    # Bucket counts describe objects, so none may exceed the base set.
    assert all(b.count <= distribution.base_cardinality for b in distribution.buckets)
    assert distribution.covered_cardinality <= distribution.base_cardinality


def test_a_derived_floor_count_answers_without_enumerating_bands(live_session, manifest2):
    """The floor count is one target, not a union of every band id."""
    from app.query.semantic.manifest_v002.schema import (
        DERIVED_FLOOR_COUNT_ID,
        DERIVED_OCCUPIABLE_FLOOR_COUNT_ID,
    )

    part = AnswerPartV2(
        part_id="P1",
        request_text="how many floors does this building have?",
        result_kind=ResultKind.SCALAR,
        target=TargetNode(node_id="t1", semantic_id=DERIVED_FLOOR_COUNT_ID),
        aggregate=AggregateNode(node_id="a1", function=AggregateFunction.COUNT),
        viewer_set=ViewerSetPolicy.NONE,
    )
    result = _compile_and_run(live_session, manifest2, part)
    assert result.status is ResultStatusV2.EXACT
    assert result.result.value == len(manifest2.floors.bands)
    assert result.statement_count == 0

    occupiable = AnswerPartV2(
        part_id="P1",
        request_text="how many occupiable floors are there?",
        result_kind=ResultKind.SCALAR,
        target=TargetNode(node_id="t1", semantic_id=DERIVED_OCCUPIABLE_FLOOR_COUNT_ID),
        aggregate=AggregateNode(node_id="a1", function=AggregateFunction.COUNT),
        viewer_set=ViewerSetPolicy.NONE,
    )
    result = _compile_and_run(live_session, manifest2, occupiable)
    assert result.result.value == len(manifest2.floors.occupiable_bands())


def test_a_thematic_profile_reports_relevant_subjects_not_an_empty_scope(
    live_session, manifest2, embedding_service
):
    """A theme profile must describe SOMETHING recorded, or say why it cannot.

    The recorded run returned the generic building profile with
    `evidence_scope=0` and declared the theme unavailable — a bounded retrieval
    miss presented as absence.
    """
    part = AnswerPartV2(
        part_id="P1",
        request_text="describe how people move through this building",
        result_kind=ResultKind.PROFILE,
        target=TargetNode(node_id="t1", semantic_id="derived:thematic_profile"),
        evidence_theme="movement between levels",
        viewer_set=ViewerSetPolicy.NONE,
    )
    compiled = compile_part(live_session, part, manifest2)
    context = ExecutionContextV2(
        live_session, manifest2, embedding_service_getter=lambda: embedding_service
    )
    result = execute_part(compiled, part.request_text, context)
    assert result.status is not ResultStatusV2.UNAVAILABLE
    assert result.evidence is not None
    assert result.evidence.excerpts, "a theme profile retrieved no text at all"
    assert result.evidence.subject_classes, "no structured subject was reported"
    assert result.result.structured.get("theme")


def test_the_catalog_lists_every_model_with_its_recorded_name(live_session):
    """The catalog query runs against the real schema (it raised UndefinedColumn)."""
    from app.query.catalog_answer import load_catalog_models

    rows = load_catalog_models(live_session)
    assert rows
    for row in rows:
        assert row["id"]
        assert row["display_name"] or row["file_name"]


# ---------------------------------------------------------------------------
# task27 — one end-to-end pipeline smoke test with NO provider call
# ---------------------------------------------------------------------------


def test_pipeline_runs_end_to_end_without_a_provider(live_session, manifest2):
    """Resolve/ground/answer are injected, so the chain runs with zero LLM calls.

    Covers intent -> ledger -> recall -> normalization -> validation ->
    preservation -> compile -> execute -> viewer -> packet -> answer validation,
    and asserts the delivered answer is grounded and free of internal wording.
    """
    from app.llm.schemas_grounding import GroundedBindings, SlotBinding
    from app.llm.schemas_v2 import ClaimKind, GroundedAnswerV2, GroundedClaim
    from app.llm.schemas_v5 import (
        IntentOperation,
        IntentPart,
        IntentTarget,
        ResolvedIntent,
        VisualizationIntent,
    )
    from app.query.binding.phrasing import banned_terms_in
    from app.query.binding.pipeline import PipelineRequest, run_pipeline

    def _resolve(context):
        payload = context["payload"]
        # task28 §2: the resolver receives the complete conversation and no
        # manifest at all.
        assert payload["conversation"][-1]["content"].startswith("how many doors")
        assert "projection_json" not in context
        return (
            ResolvedIntent(
                normalized_request="how many doors are in this building?",
                language="en",
                topic="doors",
                parts=[
                    IntentPart(
                        part_id="P1",
                        request_text="how many doors are in this building?",
                        operation=IntentOperation.COUNT,
                        highlightable=True,
                    )
                ],
                targets=[IntentTarget(target_id="T1", part_id="P1", text="doors")],
                visualization=VisualizationIntent.PRIMARY_ONLY,
            ),
            None,
        )

    def _ground(context):
        assert "projection_json" in context and "payload" in context
        # task30 §4: the grounding call receives the fixed structure and the
        # slots needing an identity — never the transcript, and never a request
        # to build a plan.
        assert context["payload"]["resolved_request"]
        assert "conversation" not in context["payload"]
        slots = context["payload"]["slots"]
        target_slot = next(s for s in slots if s["needs"] == "target")
        # The part's shape was decided before this call, not by it.
        assert context["payload"]["parts"][0]["result_kind"] == "scalar"
        return (
            GroundedBindings(
                bindings=[
                    SlotBinding(
                        slot_id=target_slot["slot_id"], semantic_id="cls:IfcDoor"
                    )
                ]
            ),
            None,
        )

    def _answer(payload):
        fact = payload["answer_parts"][0]["facts"][0]
        return (
            GroundedAnswerV2(
                answer=f"There are {fact['value']} doors in this model.",
                answer_part_ids=[payload["answer_parts"][0]["part_id"]],
                claims=[
                    GroundedClaim(
                        kind=ClaimKind.FACT,
                        cited_id=fact["fact_id"],
                        value=str(fact["value"]),
                    )
                ],
            ),
            None,
        )

    def _correct(_context):  # pragma: no cover - a valid plan needs no correction
        raise AssertionError("a valid plan must not trigger a correction")

    outcome = run_pipeline(
        live_session,
        PipelineRequest(question="how many doors are in this building?", source_model_id=MODEL_2),
        resolve=_resolve,
        ground=_ground,
        answer=_answer,
        correct=_correct,
    )
    assert outcome.terminal_status == "success"
    # §1: resolve + ground + answer for a normally answered question.
    assert outcome.llm_calls == 3
    assert not outcome.used_correction
    assert not outcome.used_deterministic_intent
    assert not outcome.used_fallback, outcome.answer_validation_failures
    assert outcome.results and outcome.results[0].status is ResultStatusV2.EXACT
    assert not banned_terms_in(outcome.answer)
    assert outcome.hydration.primary_global_ids
    # §7: nothing of the resolved meaning went missing on the way to the plan.
    assert outcome.preservation is not None and outcome.preservation.ok
    # §9: the viewer identities are attributed to the part the answer describes.
    assert outcome.hydration.contributing_part_ids() == ["P1"]
    # The disposition named a semantic id; code relinked it to the local handle.
    assert outcome.validation.normalization.relinked_references
