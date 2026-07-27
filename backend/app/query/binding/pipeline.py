"""The experiment2_v5 active query pipeline (task28).

    complete conversation + selection/previous scope
      -> LLM call 1: semantic intent resolver
      -> ONE normalized standalone request (authoritative from here on)
      -> load and validate the v002 semantic manifest + capability projection
      -> intent-derived requirement ledger (phrase-level, role from meaning)
      -> always-parallel recall channels + request-time value linking
      -> ledger model resolution (states + partial policies)
      -> LLM call 2: grounding planner -> typed logical plan
      -> ten-layer deterministic validation with per-part gates
      -> deterministic SEMANTIC PRESERVATION check against the resolved intent
      -> optional ONE budget-gated corrective call for mechanical gaps only
      -> backend-justified clarification gate over structured unresolved slots
      -> per-part compilation + one authoritative execution each
      -> adjudicated answer packet
      -> LLM call 3: claim-citing grounded answer
      -> deterministic claim validation (fallback never discards results)
      -> viewer identities combined from EVERY requested highlightable part

A normally-answered question uses exactly three LLM calls — the two planning
calls of the one semantic planning boundary (§1), plus the answer writer. A
proven mechanical grounding gap adds ONE correction inside the USD budget; no
request exceeds four.

Failures degrade at the stage that owns them: a resolver failure falls back to a
deterministic single-part intent rather than abandoning the request, and a
correction or answer-writer failure never discards an already-executed
deterministic result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.llm.budget import RequestBudget
from app.llm.client import LLMError
from app.llm.grounding_context_v5 import (
    build_correction_context_v5,
    build_grounding_context_v5,
)
from app.llm.schemas_v2 import GroundedAnswerV2, LogicalPlan
from app.llm.schemas_v5 import ResolvedIntent, VisualizationIntent
from app.query.binding.answer_validation_v2 import (
    build_fallback_answer_v2,
    validate_answer_v2,
)
from app.query.binding.assemble_v5 import assemble_plan
from app.query.binding.clarification import ClarificationDecision, decide_clarification
from app.query.binding.execute_v2 import ExecutionContextV2, execute_part
from app.query.binding.intent import (
    PendingClarification,
    SerializedConversation,
    build_intent_context,
    deterministic_intent,
    intent_payload,
    repair_intent,
    sanitize_intent,
    serialize_conversation,
)
from app.query.binding.ledger_v2 import LedgerV2
from app.query.binding.obligations import (
    Obligation,
    PlanSkeleton,
    build_obligations,
    build_plan_skeleton,
    build_recall_ledger,
    candidates_by_slot,
)
from app.query.binding.packet_v2 import AnswerPacketV2, build_answer_packet_v2
from app.query.binding.phrasing import humanize_text
from app.query.binding.preservation import (
    PreservationReport,
    validate_semantic_preservation,
)
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

__all__ = [
    "PIPELINE_VERSION",
    "PipelineOutcome",
    "PipelineRequest",
    "GateStateV2",
    "run_pipeline",
]

PIPELINE_VERSION = "experiment2_v5"


@dataclass
class PipelineRequest:
    question: str
    source_model_id: int
    #: The COMPLETE available conversation in original order (task28 §2). No
    #: turn window and no per-message truncation are applied to it here or
    #: downstream; the resolver receives every turn intact.
    history: list[dict[str, str]] = field(default_factory=list)
    selected_entities: list[dict[str, Any]] = field(default_factory=list)
    selection_entity_ids: list[int] = field(default_factory=list)
    previous_scope: PreviousScope | None = None
    #: What the previous response asked the user to decide, if anything (§3).
    pending_clarification: PendingClarification | None = None
    model_label: str | None = None


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
    intent: ResolvedIntent | None = None
    conversation: SerializedConversation | None = None
    intent_violations: list[str] = field(default_factory=list)
    obligations: list[Obligation] = field(default_factory=list)
    skeleton: PlanSkeleton | None = None
    bindings: Any = None
    ledger: LedgerV2 | None = None
    recall: RecallResult | None = None
    plan: LogicalPlan | None = None
    corrected_plan: LogicalPlan | None = None
    validation: PlanValidation | None = None
    preservation: PreservationReport | None = None
    clarification: ClarificationDecision | None = None
    next_pending_clarification: PendingClarification | None = None
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
    used_deterministic_intent: bool = False
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
    resolve: Callable[[dict[str, Any]], tuple[ResolvedIntent, Any]] | None = None,
    ground: Callable[[dict[str, Any]], tuple[LogicalPlan, Any]],
    answer: Callable[[dict[str, Any]], tuple[GroundedAnswerV2, Any]],
    correct: Callable[[dict[str, Any]], tuple[LogicalPlan, Any]] | None = None,
    settings: Settings | None = None,
    embedding_service_getter: Callable[[], Any] | None = None,
) -> PipelineOutcome:
    """Run one question end to end. `resolve`/`ground`/`correct`/`answer` are
    injected and return (parsed, usage) so the pipeline is testable without a
    provider."""
    settings = settings or get_settings()
    outcome = PipelineOutcome()

    # -- 1. LLM call 1: semantic intent resolution ---------------------------
    stage = _Stage(outcome, "intent_resolution")
    conversation = serialize_conversation(request.question, request.history)
    outcome.conversation = conversation
    if conversation.omitted_turns:
        # §2: a provider hard limit must be handled explicitly and recorded;
        # history is never silently dropped.
        outcome.warnings.append(conversation.omission_reason or "")

    intent = _resolve_intent(session, request, conversation, resolve, outcome, settings)
    outcome.intent = intent
    stage.done(
        parts=len(intent.parts),
        constraints=len(intent.constraints),
        unresolved=len(intent.unresolved),
        deterministic=outcome.used_deterministic_intent,
        **conversation.diagnostics(),
    )

    # -- 2. manifest + projection -------------------------------------------
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

    # -- 3. typed obligations + deterministic plan skeleton -------------------
    # task30 §3/§4: every structural decision that follows from meaning alone is
    # made HERE, in code, before any model sees the request. What reaches the
    # grounding call is a list of slots needing a backend identity — never a
    # request to reconstruct the user's logic.
    stage = _Stage(outcome, "obligations")
    obligations = build_obligations(intent)
    skeleton = build_plan_skeleton(intent, obligations)
    ledger = build_recall_ledger(obligations, intent.normalized_request)
    outcome.obligations = obligations
    outcome.skeleton = skeleton
    outcome.ledger = ledger
    stage.done(obligations=len(obligations), **skeleton.size_report())

    # -- 4. recall + value linking + resolution -------------------------------
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

    # -- 5. LLM call 2: grounding binder --------------------------------------
    stage = _Stage(outcome, "grounding_llm")
    slot_candidates = candidates_by_slot(obligations, recall)
    grounding_context = build_grounding_context_v5(
        intent,
        projection,
        skeleton,
        recall,
        settings=settings,
        source_model_id=request.source_model_id,
        candidates_by_slot=slot_candidates,
        selected_entities=request.selected_entities,
        previous_scope=request.previous_scope,
    )
    try:
        bindings, usage = ground(grounding_context)
    except LLMError as exc:
        stage.done("failed", error=str(exc)[:300])
        outcome.terminal_stage = "grounding_llm"
        outcome.terminal_status = "provider_failure"
        outcome.answer = (
            "The language model is currently unavailable, so this question could not be "
            "interpreted. Please try again shortly."
        )
        return outcome
    outcome.bindings = bindings
    plan = assemble_plan(intent, skeleton, obligations, bindings)
    outcome.plan = plan
    outcome.llm_calls += 1
    if usage is not None:
        outcome.budget.track_actual("grounding_planner", usage)
    stage.done(parts=len(plan.answer_parts), dispositions=len(plan.dispositions))

    # -- 6. validation + semantic preservation --------------------------------
    stage = _Stage(outcome, "validation")
    validation = validate_plan(
        session,
        plan,
        ledger,
        manifest,
        selection_entity_ids=request.selection_entity_ids,
        previous_scope_entity_ids=previous_ids,
    )
    preservation = _apply_preservation(
        intent, obligations, skeleton, plan, validation, ledger
    )
    outcome.validation = validation
    outcome.preservation = preservation
    stage.done(
        states={v.part.part_id: v.state.value for v in validation.verdicts},
        issues=validation.layer_summary(),
        preservation=preservation.to_payload(),
    )

    # -- 7. optional ONE budget-gated correction ------------------------------
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
            expanded = _expanded_candidates(validation, recall, plan, manifest)
            _ = keep
            correction_context = build_correction_context_v5(
                # The intent and the structure travel unchanged: a repair may fix
                # an identity, never what the user meant (task30 §4).
                intent,
                projection,
                skeleton,
                failures,
                expanded,
                settings=settings,
                source_model_id=request.source_model_id,
                previous_bindings=bindings,
            )
            try:
                corrected_bindings, usage = correct(correction_context)
                outcome.llm_calls += 1
                outcome.used_correction = True
                if usage is not None:
                    outcome.budget.track_actual("correction", usage)
                bindings = corrected_bindings
                outcome.bindings = bindings
                plan = assemble_plan(intent, skeleton, obligations, bindings)
                outcome.corrected_plan = plan
                validation = validate_plan(
                    session,
                    plan,
                    ledger,
                    manifest,
                    selection_entity_ids=request.selection_entity_ids,
                    previous_scope_entity_ids=previous_ids,
                )
                preservation = _apply_preservation(
                    intent, obligations, skeleton, plan, validation, ledger
                )
                outcome.validation = validation
                outcome.preservation = preservation
                stage.done(
                    states={v.part.part_id: v.state.value for v in validation.verdicts},
                    preservation=preservation.to_payload(),
                )
            except LLMError as exc:
                # Retain the initial valid parts; never replace the whole
                # response with generic unavailability.
                outcome.correction_skipped_reason = f"provider: {str(exc)[:120]}"
                outcome.warnings.append(
                    "a corrective grounding call failed; answering with the parts that "
                    "validated"
                )
                stage.done("failed", error=str(exc)[:300])

    # -- 8. clarification gate + gate resolution -------------------------------
    stage = _Stage(outcome, "clarification_gate")
    decision = decide_clarification(
        intent,
        ledger,
        plan_requested=plan.needs_clarification,
        plan_question=plan.clarification_question,
        pending=request.pending_clarification,
    )
    outcome.clarification = decision
    if decision.rejected_reason:
        # §6: an unjustified question is refused, and the request continues to
        # whatever it can honestly answer.
        outcome.warnings.append(
            "a request for clarification was not asked because nothing in the "
            "question or this model was genuinely undecided"
        )
    stage.done(**decision.to_payload())

    executable = validation.executable_verdicts()
    if not executable:
        outcome.needs_clarification = True
        outcome.terminal_stage = "validation"
        if decision.justified:
            outcome.terminal_status = "clarification"
            outcome.answer = decision.question
            outcome.next_pending_clarification = decision.to_pending(
                intent, request.source_model_id
            )
        else:
            # A source that cannot answer a clear request returns the correct
            # unavailable result and explains the limitation — it never converts
            # source unavailability into a question (§6).
            outcome.terminal_status = "unavailable"
            outcome.answer = _unavailable_text(validation, preservation)
        outcome.warnings.extend(issue.detail for issue in validation.all_issues()[:5])
        return outcome

    # -- 9. execution ---------------------------------------------------------
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
            # An unsupported optional enrichment marks only ITSELF unknown; the
            # supported core result survives (§8).
            result.add_limitation(
                "MANIFEST_CAPABILITY_GAP",
                f"{requirement.source_text!r} is not determinable from this model"
                + (f": {requirement.resolution_note}" if requirement.resolution_note else ""),
            )
            result.unknown_parts.append(requirement.source_text)
            if result.status is ResultStatusV2.EXACT:
                result.status = ResultStatusV2.PARTIAL
        results.append(result)
    outcome.results = results
    outcome.statement_count += sum(r.statement_count for r in results)
    stage.done(parts={r.part_id: r.status.value for r in results})

    # -- 10. viewer identities -------------------------------------------------
    # Hydration runs BEFORE the answer is written so the packet can name exactly
    # the parts the viewer will show: the text and the highlighted objects are
    # then derived from one set of result identities, not two (§9).
    stage = _Stage(outcome, "viewer_hydration")
    visual_part_ids = _visual_part_ids(intent, plan, results)
    hydration = hydrate_viewer_v2(session, results, visual_part_ids, settings)
    outcome.hydration = hydration
    outcome.statement_count += hydration.statement_count
    outcome.warnings.extend(hydration.warnings)
    stage.done(**hydration.to_payload())

    # -- 11. answer packet ------------------------------------------------------
    stage = _Stage(outcome, "answer_packet")
    packet = build_answer_packet_v2(
        intent.normalized_request,
        results,
        response_language=intent.language or plan.response_language,
        visual_part_ids=hydration.contributing_part_ids(),
        clarifications=[decision.question] if decision.justified else [],
    )
    outcome.packet = packet
    if decision.justified:
        outcome.next_pending_clarification = decision.to_pending(
            intent, request.source_model_id
        )
    stage.done(parts=len(packet.parts), facts=len(packet.fact_ids()))

    # -- 12. LLM call 3: grounded answer ---------------------------------------
    stage = _Stage(outcome, "answer_llm")
    try:
        generated, usage = answer(packet.to_prompt_payload())
        outcome.raw_answer = generated
        outcome.llm_calls += 1
        if usage is not None:
            outcome.budget.track_actual("grounded_answerer", usage)
        stage.done()
    except LLMError as exc:
        # The deterministic result stands; the writer is replaceable.
        generated = None
        outcome.used_fallback = True
        outcome.answer = build_fallback_answer_v2(packet)
        outcome.warnings.append(
            "the answer-writing model was unavailable, so a direct summary of the "
            "retrieved results is shown"
        )
        stage.done("failed", error=str(exc)[:300])

    # -- 13. answer validation / fallback --------------------------------------
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

    outcome.next_scope = _capture_scope(executable, results, visual_part_ids)
    for result in results:
        for note in result.interpretation_notes:
            if note not in outcome.warnings:
                outcome.warnings.append(note)
    outcome.warnings = [w for w in outcome.warnings if w][:12]
    return outcome


# ---------------------------------------------------------------------------
# Stage 1 helpers
# ---------------------------------------------------------------------------


def _resolve_intent(
    session: Session,
    request: PipelineRequest,
    conversation: SerializedConversation,
    resolve: Callable[[dict[str, Any]], tuple[ResolvedIntent, Any]] | None,
    outcome: PipelineOutcome,
    settings: Settings,
) -> ResolvedIntent:
    """Planning call 1, with an honest deterministic degradation (§2).

    A resolver that is absent, unavailable, or in breach of its contract must
    not abandon the request: the pipeline falls back to a single-part intent
    that preserves the message verbatim. It then finds less than the resolver
    would have — but it invents nothing, and the degradation is recorded.
    """
    _ = session
    if resolve is None:
        outcome.used_deterministic_intent = True
        return deterministic_intent(
            request.question,
            conversation,
            has_previous_result=request.previous_scope is not None,
            selected_object_count=len(request.selected_entities),
        )

    context = build_intent_context(
        conversation,
        source_model_id=request.source_model_id,
        model_label=request.model_label,
        selected_object_count=len(request.selected_entities),
        has_previous_result=request.previous_scope is not None,
        previous_result_summary=(
            request.previous_scope.summary() if request.previous_scope else None
        ),
        pending=request.pending_clarification,
    )
    try:
        intent, usage = resolve(context)
    except LLMError as exc:
        outcome.used_deterministic_intent = True
        outcome.warnings.append(
            "the conversation could not be interpreted by the language model, so this "
            "question was read on its own"
        )
        outcome.intent_violations.append(f"provider: {str(exc)[:160]}")
        return deterministic_intent(
            request.question,
            conversation,
            has_previous_result=request.previous_scope is not None,
            selected_object_count=len(request.selected_entities),
        )

    outcome.llm_calls += 1
    if usage is not None:
        outcome.budget.track_actual("intent_resolver", usage)

    violations = sanitize_intent(intent, conversation)
    if violations:
        outcome.intent_violations = violations[:8]
        repair_intent(intent, conversation)
    if not intent.parts and not intent.unresolved:
        # An intent with neither a request nor a question resolves nothing;
        # degrade rather than ground an empty meaning.
        outcome.used_deterministic_intent = True
        return deterministic_intent(
            request.question,
            conversation,
            has_previous_result=request.previous_scope is not None,
            selected_object_count=len(request.selected_entities),
        )
    _ = settings
    return intent


def _apply_preservation(
    intent: ResolvedIntent,
    obligations: list[Obligation],
    skeleton: PlanSkeleton,
    plan: LogicalPlan,
    validation: PlanValidation,
    ledger: LedgerV2,
) -> PreservationReport:
    """Run the obligation check and fold its verdicts into the per-part gates.

    Preservation issues are ordinary validation issues once raised: a correctable
    one becomes a mechanical grounding gap the single corrective call may fix, an
    uncorrectable one makes its part unanswerable — an unsupported obligation
    degrades its part to a partial result with a stated limitation rather than
    silently narrowing the answer. Neither is ever repaired by inferring a
    different intent.
    """
    report = validate_semantic_preservation(
        intent, obligations, skeleton, plan, validation
    )
    verdicts = {v.part.part_id: v for v in validation.verdicts}
    for issue in report.issues:
        verdict = verdicts.get(issue.part_id or "")
        if verdict is not None:
            verdict.issues.append(issue)
        else:
            validation.plan_issues.append(issue)

    # Re-gate every part the check touched, so a preserved-meaning failure
    # cannot coexist with a "ready" verdict (§7).
    from app.query.binding.ledger_v2 import ResolutionState

    ambiguous = [
        r for r in ledger.required() if r.resolution is ResolutionState.AMBIGUOUS
    ]
    from app.query.binding.validate_v2 import _gate

    for verdict in validation.verdicts:
        verdict.state = _gate(verdict.part, verdict, ambiguous, plan)
    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _visual_part_ids(
    intent: ResolvedIntent, plan: LogicalPlan, results: list[PartResultV2]
) -> list[str]:
    """Every part the user asked to see, per the resolved visualization (§9).

    The v4 rule — exactly one part is the visualization authority — silently
    discarded the identities of every other requested set. Here the intent
    decides how many sets are shown, and the plan decides which parts they are.
    """
    if intent.visualization is VisualizationIntent.NONE:
        return []
    showable = [
        r.part_id
        for r in results
        if r.viewer_policy not in ("none", "") and r.is_answerable
    ]
    if not showable:
        return []

    wanted = {p.part_id for p in intent.parts if p.highlightable}
    if wanted:
        matched = [p for p in showable if p in wanted]
        if matched:
            showable = matched

    if intent.visualization is VisualizationIntent.ALL_RESULTS:
        return showable

    explicit = [
        p.part_id
        for p in plan.answer_parts
        if p.is_primary_visual and p.part_id in showable
    ]
    return explicit[:1] or showable[:1]


def _expanded_candidates(
    validation: PlanValidation,
    recall: RecallResult,
    plan: LogicalPlan,
    manifest: ManifestV002,
) -> dict[str, Any]:
    """Bounded expanded candidates/values for ONLY the failed requirements.

    Also names, per failing node, the exact invalid fragment and the valid ids
    that could replace it: recorded corrections re-emitted the same invented
    `semantic_id` because nothing told them which string was rejected.
    """
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
    return {
        "candidates": candidates[:24],
        "value_matches": value_matches[:12],
        "invalid_fragments": _invalid_fragments(validation, plan, manifest),
    }


def _invalid_fragments(
    validation: PlanValidation, plan: LogicalPlan, manifest: ManifestV002
) -> list[dict[str, Any]]:
    """`{node, invalid_semantic_id, replace_with}` for each unknown id."""
    invalid: dict[tuple[str, str], dict[str, Any]] = {}
    for issue in validation.correctable_issues():
        if issue.layer != "identity" or not issue.part_id or not issue.node_id:
            continue
        part = next((p for p in plan.answer_parts if p.part_id == issue.part_id), None)
        if part is None:
            continue
        for node_id, (kind, semantic_id) in _plan_part_nodes(part).items():
            if node_id != issue.node_id or manifest.get(semantic_id) is not None:
                continue
            invalid[(issue.part_id, node_id)] = {
                "part_id": issue.part_id,
                "node_id": node_id,
                "node_kind": kind,
                "invalid_semantic_id": semantic_id,
                "replace_with": _nearest_ids(semantic_id, kind, manifest),
            }
    return list(invalid.values())[:8]


def _plan_part_nodes(part: Any) -> dict[str, tuple[str, str]]:
    from app.query.binding.validate_v2 import _part_nodes

    return _part_nodes(part)


def _nearest_ids(invalid: str, kind: str, manifest: ManifestV002) -> list[str]:
    """Valid ids of the right kind whose words overlap the rejected string."""
    from app.query.binding.lexical import identifier_tokens

    wanted_use = {
        "target": "target",
        "filter": "filter",
        "group": "group",
        "aggregate": "aggregate",
        "report": "report",
    }.get(kind)
    tokens = identifier_tokens(invalid)
    scored: list[tuple[int, str]] = []
    for semantic_id, capability in manifest.capabilities.items():
        if not capability.executable:
            continue
        if wanted_use and not capability.supports_use(wanted_use):
            continue
        overlap = len(tokens & identifier_tokens(capability.search_text))
        if overlap:
            scored.append((-overlap, semantic_id))
    scored.sort()
    return [semantic_id for _score, semantic_id in scored[:6]]


def _unavailable_text(
    validation: PlanValidation, preservation: PreservationReport | None
) -> str:
    """Plain-language "this model doesn't record that".

    The reasons come from validation issues written for engineers, so they pass
    through the same humanizing rewrite the answers use: a user was told
    "prop:Pset_RoofCommon.TotalArea cannot be aggregated (unproven unit
    contract)" when the honest answer is that this model records no area with a
    usable unit.
    """
    reasons = [
        humanize_text(i.detail)
        for v in validation.verdicts
        for i in v.issues
        if not i.correctable and i.layer != "preservation"
    ]
    for verdict in validation.verdicts:
        for requirement in verdict.unavailable_requirements:
            reasons.append(f"{requirement.source_text!r} is not recorded in this model")
    # Preservation details are written for an engineer — they name plan parts,
    # node handles and internal codes. They diagnose the pipeline, never the
    # model, so they must not become the sentence a user reads; the generic
    # honest statement below is the correct user-facing outcome.
    _ = preservation
    if reasons:
        return (
            "This model does not record what that question needs: "
            + "; ".join(r for r in reasons[:2] if r)
            + ". I haven't answered a broader version instead."
        )
    return "This model's recorded data cannot answer that question as asked."


def _capture_scope(
    verdicts: list[Any], results: list[PartResultV2], visual_part_ids: list[str]
) -> PreviousScope | None:
    from app.query.binding.previous_scope import capture_previous_scope_v2

    target = next(
        (r for r in results if visual_part_ids and r.part_id == visual_part_ids[0]), None
    )
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


def intent_trace_payload(outcome: PipelineOutcome) -> dict[str, Any] | None:
    """The resolved intent as the permanent trace records it (§2)."""
    if outcome.intent is None:
        return None
    payload = intent_payload(outcome.intent)
    if outcome.used_deterministic_intent:
        payload["deterministic_fallback"] = True
    if outcome.intent_violations:
        payload["contract_violations"] = outcome.intent_violations[:8]
    if outcome.conversation is not None:
        payload["conversation"] = outcome.conversation.diagnostics()
    return payload
