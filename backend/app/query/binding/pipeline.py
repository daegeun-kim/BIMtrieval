"""The experiment2_v4 active query pipeline (task26).

    question + bounded history/selection
      -> load and validate the v002 semantic manifest + binder projection
      -> deterministic phrase-level requirement ledger (intent skeleton)
      -> always-parallel recall channels + request-time value linking
      -> ledger model resolution (states + partial policies)
      -> LLM call 1: typed logical plan over the compact projection
      -> ten-layer deterministic validation with per-part gates
      -> optional ONE budget-gated corrective call for mechanical gaps only
      -> per-part compilation + one authoritative execution each
      -> adjudicated answer packet
      -> LLM call 2: claim-citing grounded answer
      -> deterministic claim validation (fallback never discards results)
      -> viewer identities from each part's typed viewer set

A normally-answered question uses exactly two LLM calls; a proven mechanical
binding gap adds ONE correction inside the USD budget; no request exceeds
three. Failures degrade at the stage that owns them (§13): a correction or
answer-writer failure never discards an already-executed deterministic result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.llm.binder_context_v2 import (
    build_binder_context_v2,
    build_correction_context_v2,
)
from app.llm.budget import RequestBudget
from app.llm.client import LLMError
from app.llm.schemas_v2 import GroundedAnswerV2, LogicalPlan
from app.query.binding.answer_validation_v2 import (
    build_fallback_answer_v2,
    validate_answer_v2,
)
from app.query.binding.execute_v2 import ExecutionContextV2, execute_part
from app.query.binding.ledger_v2 import LedgerV2, build_ledger_skeleton
from app.query.binding.packet_v2 import AnswerPacketV2, build_answer_packet_v2
from app.query.binding.previous_scope import (
    PreviousScope,
    resolve_previous_entity_ids,
)
from app.query.binding.recall import RecallResult, resolve_ledger, run_recall
from app.query.binding.results_v2 import PartResultV2, ResultStatusV2
from app.query.binding.validate_v2 import (
    GateStateV2,
    PlanValidation,
    validate_plan,
)
from app.query.binding.viewer_v2 import ViewerHydrationV2, hydrate_viewer_v2
from app.query.semantic.manifest_v002 import (
    BinderProjection,
    ManifestV002,
    ManifestV002UnavailableError,
    build_binder_projection,
    get_manifest_v002,
)

__all__ = ["PipelineOutcome", "PipelineRequest", "GateStateV2", "run_pipeline"]

PIPELINE_VERSION = "experiment2_v4"


@dataclass
class PipelineRequest:
    question: str
    source_model_id: int
    history: list[dict[str, str]] = field(default_factory=list)
    selected_entities: list[dict[str, Any]] = field(default_factory=list)
    selection_entity_ids: list[int] = field(default_factory=list)
    previous_scope: PreviousScope | None = None


@dataclass
class StageRecord:
    name: str
    status: str = "ok"
    duration_ms: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }
        if self.payload:
            record.update(self.payload)
        return record


@dataclass
class PipelineOutcome:
    answer: str = ""
    results: list[PartResultV2] = field(default_factory=list)
    ledger: LedgerV2 | None = None
    recall: RecallResult | None = None
    plan: LogicalPlan | None = None
    corrected_plan: LogicalPlan | None = None
    validation: PlanValidation | None = None
    packet: AnswerPacketV2 | None = None
    raw_answer: GroundedAnswerV2 | None = None
    hydration: ViewerHydrationV2 = field(default_factory=ViewerHydrationV2)
    next_scope: PreviousScope | None = None
    budget: RequestBudget = field(default_factory=RequestBudget)
    projection: BinderProjection | None = None
    manifest: ManifestV002 | None = None

    terminal_stage: str = "response_delivery"
    terminal_status: str = "success"
    needs_clarification: bool = False
    used_fallback: bool = False
    used_correction: bool = False
    correction_skipped_reason: str | None = None
    answer_validation_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stages: list[StageRecord] = field(default_factory=list)
    statement_count: int = 0
    llm_calls: int = 0

    @property
    def primary_result(self) -> PartResultV2 | None:
        return self.results[0] if self.results else None

    def stage_ms(self) -> dict[str, float]:
        return {s.name: s.duration_ms for s in self.stages}


class _Stage:
    """Timed stage recorder that always lands in the outcome's stage list."""

    def __init__(self, outcome: PipelineOutcome, name: str) -> None:
        self.record = StageRecord(name=name)
        outcome.stages.append(self.record)
        self._started = time.perf_counter()

    def done(self, status: str = "ok", **payload: Any) -> None:
        self.record.status = status
        self.record.duration_ms = round((time.perf_counter() - self._started) * 1000.0, 1)
        self.record.payload.update(payload)


def run_pipeline(
    session: Session,
    request: PipelineRequest,
    *,
    bind: Callable[[dict[str, Any]], tuple[LogicalPlan, Any]],
    answer: Callable[[dict[str, Any]], tuple[GroundedAnswerV2, Any]],
    correct: Callable[[dict[str, Any]], tuple[LogicalPlan, Any]] | None = None,
    settings: Settings | None = None,
    embedding_service_getter: Callable[[], Any] | None = None,
) -> PipelineOutcome:
    """Run one question end to end. `bind`/`correct`/`answer` are injected and
    return (parsed, usage) so the pipeline is testable without a provider."""
    settings = settings or get_settings()
    outcome = PipelineOutcome()

    # -- 1. manifest + projection -------------------------------------------
    stage = _Stage(outcome, "manifest_load")
    try:
        manifest = get_manifest_v002(session, request.source_model_id, settings)
    except ManifestV002UnavailableError as exc:
        stage.done("failed", error=str(exc))
        outcome.terminal_stage = "manifest_load"
        outcome.terminal_status = "manifest_unavailable"
        outcome.needs_clarification = True
        outcome.answer = "I can't answer questions about this model yet: " + str(exc) + "."
        outcome.warnings.append(str(exc))
        return outcome
    outcome.manifest = manifest
    projection = build_binder_projection(manifest)
    outcome.projection = projection
    stage.done(
        capabilities=len(manifest.capabilities),
        projection_tokens=projection.estimated_tokens,
        projection_hash=projection.projection_hash[:16],
        content_hash=manifest.content_hash[:16],
    )

    previous_ids = resolve_previous_entity_ids(
        session, request.previous_scope, request.source_model_id
    )

    # -- 2. ledger skeleton ---------------------------------------------------
    stage = _Stage(outcome, "ledger")
    ledger = build_ledger_skeleton(
        request.question,
        previous_scope=request.previous_scope,
        selected_entities=request.selected_entities,
    )
    outcome.ledger = ledger
    stage.done(**ledger.size_report())

    # -- 3. recall + value linking + resolution -------------------------------
    stage = _Stage(outcome, "recall")
    recall = run_recall(
        session,
        manifest,
        ledger,
        embedding_service_getter=embedding_service_getter,
    )
    resolve_ledger(ledger, recall, manifest)
    outcome.recall = recall
    stage.done(
        recommendations=len(recall.recommendations),
        value_links=sum(len(v) for v in recall.value_links.values()),
        **recall.diagnostics,
    )

    # -- 4. LLM call 1: typed logical plan ------------------------------------
    stage = _Stage(outcome, "binding_llm")
    binder_context = build_binder_context_v2(
        request.question,
        projection,
        ledger,
        recall,
        settings=settings,
        source_model_id=request.source_model_id,
        history=request.history,
        selected_entities=request.selected_entities,
        previous_scope=request.previous_scope,
    )
    try:
        plan, usage = bind(binder_context)
    except LLMError as exc:
        stage.done("failed", error=str(exc)[:300])
        outcome.terminal_stage = "binding_llm"
        outcome.terminal_status = "provider_failure"
        outcome.answer = (
            "The language model is currently unavailable, so this question could not be "
            "interpreted. Please try again shortly."
        )
        return outcome
    outcome.plan = plan
    outcome.llm_calls += 1
    if usage is not None:
        outcome.budget.track_actual("binder", usage)
    stage.done(parts=len(plan.answer_parts), dispositions=len(plan.dispositions))

    # -- 5. validation --------------------------------------------------------
    stage = _Stage(outcome, "validation")
    validation = validate_plan(
        session,
        plan,
        ledger,
        manifest,
        selection_entity_ids=request.selection_entity_ids,
        previous_scope_entity_ids=previous_ids,
    )
    outcome.validation = validation
    stage.done(
        states={v.part.part_id: v.state.value for v in validation.verdicts},
        issues=validation.layer_summary(),
    )

    # -- 6. optional ONE budget-gated correction ------------------------------
    correctable = [
        v for v in validation.verdicts if v.state is GateStateV2.CORRECTABLE_BINDING_GAP
    ] or ([] if not validation.plan_issues else [None])
    if correctable and correct is not None:
        stage = _Stage(outcome, "correction")
        estimate = outcome.budget.estimate_call(
            "correction",
            model=settings.get_correction_model(),
            stable_prefix_bytes=len(projection.json_text.encode("utf-8")),
            dynamic_bytes=4000,
            max_output_tokens=settings.correction_max_output_tokens,
            expect_cached_prefix=True,
        )
        reserve = outcome.budget.estimate_call(
            "grounded_answerer",
            model=settings.get_answer_model(),
            stable_prefix_bytes=2000,
            dynamic_bytes=8000,
            max_output_tokens=settings.answer_max_output_tokens,
        )
        if not outcome.budget.allows_correction(estimate, reserve):
            outcome.correction_skipped_reason = "budget"
            stage.done("skipped", reason="budget")
        else:
            failures = [i.to_payload() for i in validation.correctable_issues()]
            keep = [
                v.part.part_id
                for v in validation.verdicts
                if v.state in (GateStateV2.READY, GateStateV2.PARTIAL_EXECUTABLE)
            ]
            expanded = _expanded_candidates(validation, recall)
            correction_context = build_correction_context_v2(
                request.question,
                projection,
                plan,
                failures,
                {"keep": keep, **expanded},
                settings=settings,
                source_model_id=request.source_model_id,
            )
            try:
                corrected, usage = correct(correction_context)
                outcome.corrected_plan = corrected
                outcome.llm_calls += 1
                outcome.used_correction = True
                if usage is not None:
                    outcome.budget.track_actual("correction", usage)
                plan = corrected
                validation = validate_plan(
                    session,
                    plan,
                    ledger,
                    manifest,
                    selection_entity_ids=request.selection_entity_ids,
                    previous_scope_entity_ids=previous_ids,
                )
                outcome.validation = validation
                stage.done(
                    states={v.part.part_id: v.state.value for v in validation.verdicts}
                )
            except LLMError as exc:
                # §13: retain the initial valid parts; never replace the whole
                # response with generic unavailability.
                outcome.correction_skipped_reason = f"provider: {str(exc)[:120]}"
                outcome.warnings.append(
                    "a corrective binding call failed; answering with the parts that "
                    "validated"
                )
                stage.done("failed", error=str(exc)[:300])

    # -- 7. gate resolution ---------------------------------------------------
    executable = validation.executable_verdicts()
    clarification_states = [
        v for v in validation.verdicts if v.state is GateStateV2.NEEDS_CLARIFICATION
    ]
    if not executable:
        outcome.needs_clarification = True
        outcome.terminal_stage = "validation"
        if plan.needs_clarification and plan.clarification_question:
            outcome.terminal_status = "clarification"
            outcome.answer = plan.clarification_question
        elif clarification_states:
            outcome.terminal_status = "clarification"
            outcome.answer = _ambiguity_question(validation, ledger)
        else:
            outcome.terminal_status = "unavailable"
            outcome.answer = _unavailable_text(validation)
        outcome.warnings.extend(
            issue.detail for issue in validation.all_issues()[:5]
        )
        return outcome

    # -- 8. execution ---------------------------------------------------------
    stage = _Stage(outcome, "execution")
    context = ExecutionContextV2(
        session,
        manifest,
        settings=settings,
        embedding_service_getter=embedding_service_getter,
    )
    results: list[PartResultV2] = []
    for verdict in executable:
        compiled = verdict.compiled
        if compiled is None:
            continue
        result = execute_part(compiled, verdict.part.request_text, context)
        for requirement in verdict.unavailable_requirements:
            limitation_id = result.add_limitation(
                "MANIFEST_CAPABILITY_GAP",
                f"{requirement.source_text!r} is not determinable from this model"
                + (f": {requirement.resolution_note}" if requirement.resolution_note else ""),
            )
            result.unknown_parts.append(requirement.source_text)
            if result.status is ResultStatusV2.EXACT:
                result.status = ResultStatusV2.PARTIAL
            _ = limitation_id
        results.append(result)
    outcome.results = results
    outcome.statement_count += sum(r.statement_count for r in results)
    stage.done(parts={r.part_id: r.status.value for r in results})

    # -- 9. answer packet ------------------------------------------------------
    stage = _Stage(outcome, "answer_packet")
    primary_visual = _primary_visual_part_id(plan, results)
    clarifications = [
        _ambiguity_question(validation, ledger)
    ] if clarification_states else []
    packet = build_answer_packet_v2(
        request.question,
        results,
        response_language=plan.response_language,
        primary_visual_part_id=primary_visual,
        clarifications=clarifications,
    )
    outcome.packet = packet
    stage.done(parts=len(packet.parts), facts=len(packet.fact_ids()))

    # -- 10. LLM call 2: grounded answer --------------------------------------
    stage = _Stage(outcome, "answer_llm")
    try:
        generated, usage = answer(packet.to_prompt_payload())
        outcome.raw_answer = generated
        outcome.llm_calls += 1
        if usage is not None:
            outcome.budget.track_actual("grounded_answerer", usage)
        stage.done()
    except LLMError as exc:
        # §13: the deterministic result stands; the writer is replaceable.
        generated = None
        outcome.used_fallback = True
        outcome.answer = build_fallback_answer_v2(packet)
        outcome.warnings.append(
            "the answer-writing model was unavailable, so a direct summary of the "
            "retrieved results is shown"
        )
        stage.done("failed", error=str(exc)[:300])

    # -- 11. answer validation / fallback --------------------------------------
    if generated is not None:
        stage = _Stage(outcome, "answer_validation")
        answer_validation = validate_answer_v2(generated, packet)
        if answer_validation.ok:
            outcome.answer = generated.answer
            stage.done()
        else:
            outcome.used_fallback = True
            outcome.answer_validation_failures = answer_validation.failures
            outcome.answer = build_fallback_answer_v2(packet)
            outcome.warnings.append(
                "the generated answer did not match the retrieved results, so a direct "
                "summary of those results was returned instead"
            )
            stage.done("failed", failures=answer_validation.failures[:5])

    # -- 12. viewer -------------------------------------------------------------
    stage = _Stage(outcome, "viewer_hydration")
    hydration = hydrate_viewer_v2(session, results, primary_visual, settings)
    outcome.hydration = hydration
    outcome.statement_count += hydration.statement_count
    outcome.warnings.extend(hydration.warnings)
    stage.done(
        returned=len(hydration.primary_global_ids),
        total=hydration.viewer_matches_total,
        truncated=hydration.viewer_matches_truncated,
    )

    outcome.next_scope = _capture_scope(executable, results, primary_visual)
    for result in results:
        for note in result.interpretation_notes:
            if note not in outcome.warnings:
                outcome.warnings.append(note)
    outcome.warnings = outcome.warnings[:12]
    return outcome


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expanded_candidates(
    validation: PlanValidation, recall: RecallResult
) -> dict[str, Any]:
    """Bounded expanded candidates/values for ONLY the failed requirements."""
    failed_requirements = {
        i.requirement_id for i in validation.correctable_issues() if i.requirement_id
    }
    candidates = [
        r.to_payload()
        for r in recall.recommendations
        if r.requirement_id in failed_requirements
    ]
    value_matches = [
        link.to_payload() | {"for": requirement_id}
        for requirement_id, links in recall.value_links.items()
        if requirement_id in failed_requirements
        for link in links[:4]
    ]
    return {"candidates": candidates[:24], "value_matches": value_matches[:12]}


def _ambiguity_question(validation: PlanValidation, ledger: LedgerV2) -> str:
    from app.query.binding.ledger_v2 import ResolutionState

    ambiguous = [
        r for r in ledger.required() if r.resolution is ResolutionState.AMBIGUOUS
    ]
    if ambiguous:
        notes = "; ".join(
            f"{r.source_text!r}: {r.resolution_note}" for r in ambiguous[:2] if r.resolution_note
        )
        return (
            "That question has more than one reasonable reading — "
            + (notes or "an ambiguous reference")
            + ". Which interpretation do you mean?"
        )
    detail = next((i.detail for i in validation.all_issues()), None)
    if detail:
        return (
            f"I couldn't answer that as asked: {detail}. I haven't answered a broader "
            "version instead. Could you rephrase that part?"
        )
    return "Could you rephrase that question, or be more specific?"


def _unavailable_text(validation: PlanValidation) -> str:
    reasons = [
        i.detail
        for v in validation.verdicts
        for i in v.issues
        if not i.correctable
    ]
    for verdict in validation.verdicts:
        for requirement in verdict.unavailable_requirements:
            reasons.append(f"{requirement.source_text!r} is not recorded in this model")
    if reasons:
        return (
            "This model's data cannot answer that: " + "; ".join(reasons[:2]) + ". "
            "I haven't substituted a broader question instead."
        )
    return "This model's data cannot answer that question as asked."


def _primary_visual_part_id(
    plan: LogicalPlan, results: list[PartResultV2]
) -> str | None:
    explicit = [p.part_id for p in plan.answer_parts if p.is_primary_visual]
    if len(explicit) == 1:
        return explicit[0]
    visual = [
        r.part_id
        for r in results
        if r.viewer_policy not in ("none", "") and r.is_answerable
    ]
    return visual[0] if visual else None


def _capture_scope(
    verdicts: list[Any], results: list[PartResultV2], primary_visual: str | None
) -> PreviousScope | None:
    from app.query.binding.previous_scope import capture_previous_scope_v2

    target = next((r for r in results if r.part_id == primary_visual), None)
    if target is None:
        target = next((r for r in results if r.is_answerable), None)
    if target is None:
        return None
    compiled = next(
        (v.compiled for v in verdicts if v.part.part_id == target.part_id), None
    )
    try:
        return capture_previous_scope_v2(compiled, target)
    except Exception:  # noqa: BLE001 - follow-up scope is best-effort
        return None


def status_summary(results: list[PartResultV2]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for result in results:
        tally[result.status.value] = tally.get(result.status.value, 0) + 1
    return tally
