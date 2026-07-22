"""The Task 25 active query pipeline (§1 required data flow).

    question + bounded history/selection
      -> load and validate the complete active-model semantic manifest
      -> typed constraint ledger
      -> deterministic high-recall recommendations over the COMPLETE manifest
      -> LLM call 1: manifest-aware semantic binding + decomposition
      -> deterministic structural validation + ledger-coverage gate
      -> optional ONE corrective LLM call, only for a proven recoverable gap
      -> one authoritative execution per answer part
      -> compact adjudicated answer packet
      -> LLM call 2: uniform grounded answer
      -> deterministic answer validation + same-predicate viewer identities

A normally-answered question uses exactly two LLM calls; a proven recoverable
gap adds ONE correction; no request exceeds three. The binder selects any id in
the complete manifest — the recommendations are advisory, not a gate — and every
material request element is tracked through the typed ledger, so a dropped
condition cannot be reported as a broader exact answer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.llm.binder_context import build_binder_context, build_correction_context
from app.llm.schemas import BindingPlan
from app.query.binding.answer_validation import build_fallback_answer, validate_answer
from app.query.binding.evidence import AnswerPartResult, ResultStatus
from app.query.binding.execute import ExecutionContext, execute_answer_part
from app.query.binding.ledger import build_ledger
from app.query.binding.ledger_validation import LedgerCoverage, validate_ledger_coverage
from app.query.binding.packet import AnswerPacket, build_answer_packet
from app.query.binding.previous_scope import (
    PreviousScope,
    capture_previous_scope,
    resolve_previous_entity_ids,
)
from app.query.binding.recommend import RecommendationInputs, build_recommendations
from app.query.binding.schemas import CandidateSlate
from app.query.binding.validate import BindingValidation, validate_binding
from app.query.binding.viewer import ViewerHydration, hydrate_viewer_identities
from app.query.semantic.manifest import (
    ManifestUnavailableError,
    get_semantic_manifest,
)

__all__ = ["PipelineOutcome", "PipelineRequest", "GateState", "run_pipeline"]


class GateState(str, Enum):
    """The one deterministic gate state after binding (§4)."""

    READY = "ready"
    RECOVERABLE_BINDING_GAP = "recoverable_binding_gap"
    NEEDS_CLARIFICATION = "needs_clarification"
    MODEL_DATA_UNAVAILABLE = "model_data_unavailable"
    INVALID = "invalid"


@dataclass
class PipelineRequest:
    question: str
    source_model_id: int
    history: list[dict[str, str]] = field(default_factory=list)
    selected_entities: list[dict[str, Any]] = field(default_factory=list)
    selection_entity_ids: list[int] = field(default_factory=list)
    previous_scope: PreviousScope | None = None


@dataclass
class PipelineOutcome:
    answer: str
    results: list[AnswerPartResult] = field(default_factory=list)
    slate: CandidateSlate | None = None
    binding: BindingPlan | None = None
    validation: BindingValidation | None = None
    packet: AnswerPacket | None = None
    hydration: ViewerHydration = field(default_factory=ViewerHydration)
    next_scope: PreviousScope | None = None

    gate_state: GateState = GateState.INVALID
    needs_clarification: bool = False
    used_fallback: bool = False
    used_correction: bool = False
    answer_validation_failures: list[str] = field(default_factory=list)
    used_general_knowledge: bool = False
    warnings: list[str] = field(default_factory=list)

    stage_ms: dict[str, float] = field(default_factory=dict)
    statement_count: int = 0
    slate_bytes: int = 0
    packet_bytes: int = 0
    llm_calls: int = 0

    @property
    def primary_result(self) -> AnswerPartResult | None:
        return self.results[0] if self.results else None


def run_pipeline(
    session: Session,
    request: PipelineRequest,
    *,
    bind: Callable[[dict[str, Any]], BindingPlan],
    answer: Callable[[dict[str, Any]], Any],
    correct: Callable[[dict[str, Any]], BindingPlan] | None = None,
    settings: Settings | None = None,
    embedding_service_getter: Callable[[], Any] | None = None,
) -> PipelineOutcome:
    """Run one question end to end.

    `bind`, `correct`, and `answer` are injected so the pipeline is testable
    without a provider. `correct` is optional — without it, a recoverable gap ends
    as a clarification rather than a third call.
    """
    settings = settings or get_settings()
    outcome = PipelineOutcome(answer="")

    # -- 1. complete semantic manifest --------------------------------------
    started = time.perf_counter()
    try:
        manifest = get_semantic_manifest(session, request.source_model_id, settings)
    except ManifestUnavailableError as exc:
        outcome.gate_state = GateState.MODEL_DATA_UNAVAILABLE
        outcome.needs_clarification = True
        outcome.answer = "I can't answer questions about this model yet: " + str(exc) + "."
        outcome.warnings.append(str(exc))
        return outcome
    outcome.stage_ms["manifest_load_ms"] = _elapsed(started)

    previous_ids = resolve_previous_entity_ids(
        session, request.previous_scope, request.source_model_id
    )

    # -- 2. typed constraint ledger -----------------------------------------
    started = time.perf_counter()
    ledger = build_ledger(
        request.question,
        previous_scope=request.previous_scope,
        selected_entities=request.selected_entities,
    )
    outcome.stage_ms["ledger_build_ms"] = _elapsed(started)

    # -- 3. high-recall recommendations over the COMPLETE manifest ----------
    started = time.perf_counter()
    slate = build_recommendations(
        session,
        RecommendationInputs(
            question=request.question,
            source_model_id=request.source_model_id,
            history=request.history,
            selected_entities=request.selected_entities,
            previous_scope=request.previous_scope,
        ),
        manifest,
        ledger,
        settings=settings,
        embedding_service_getter=embedding_service_getter,
    )
    outcome.slate = slate
    outcome.stage_ms["recommendation_ms"] = _elapsed(started)
    outcome.slate_bytes = _payload_bytes(slate.to_prompt_payload())

    # -- 4. LLM call 1: semantic binding ------------------------------------
    started = time.perf_counter()
    binder_context = build_binder_context(
        request.question,
        manifest,
        slate,
        ledger,
        settings=settings,
        history=request.history,
        selected_entities=request.selected_entities,
        previous_scope=request.previous_scope,
    )
    plan = bind(binder_context)
    outcome.binding = plan
    outcome.llm_calls += 1
    outcome.stage_ms["binding_llm_ms"] = _elapsed(started)

    # -- 5. deterministic validation + ledger-coverage gate -----------------
    started = time.perf_counter()
    validation = validate_binding(plan, slate)
    coverage = validate_ledger_coverage(plan, ledger)
    gate = _gate(plan, validation, coverage)
    outcome.stage_ms["binding_validation_ms"] = _elapsed(started)

    # -- 6. optional ONE corrective binding ---------------------------------
    if gate is GateState.RECOVERABLE_BINDING_GAP and correct is not None:
        started = time.perf_counter()
        correction_context = build_correction_context(
            request.question,
            manifest,
            ledger,
            plan,
            _gate_failures(validation, coverage),
            slate,
            settings=settings,
        )
        plan = correct(correction_context)
        outcome.binding = plan
        outcome.llm_calls += 1
        outcome.used_correction = True
        validation = validate_binding(plan, slate)
        coverage = validate_ledger_coverage(plan, ledger)
        gate = _gate(plan, validation, coverage)
        outcome.stage_ms["correction_llm_ms"] = _elapsed(started)

    outcome.validation = validation
    outcome.gate_state = gate

    if gate in (
        GateState.NEEDS_CLARIFICATION,
        GateState.RECOVERABLE_BINDING_GAP,
        GateState.INVALID,
    ):
        outcome.needs_clarification = True
        outcome.answer = _clarification_text(plan, validation, coverage)
        outcome.warnings.extend(coverage.failures()[:5])
        outcome.warnings.extend(i.detail for i in validation.all_issues()[:5])
        return outcome

    # -- 7. one authoritative execution per answer part ---------------------
    started = time.perf_counter()
    context = ExecutionContext(
        session,
        request.source_model_id,
        slate,
        settings=settings,
        selection_entity_ids=request.selection_entity_ids,
        previous_scope_entity_ids=previous_ids,
        embedding_service_getter=embedding_service_getter,
    )
    results = [execute_answer_part(part, context) for part in validation.valid_parts]
    outcome.results = results
    outcome.statement_count += sum(r.statement_count for r in results)
    outcome.stage_ms["execution_ms"] = _elapsed(started)

    # -- 8. compact answer packet -------------------------------------------
    started = time.perf_counter()
    primary_visual = _primary_visual_part_id(plan, results)
    packet = build_answer_packet(
        request.question,
        results,
        response_language=plan.response_language,
        primary_visual_part_id=primary_visual,
        settings=settings,
    )
    outcome.packet = packet
    outcome.packet_bytes = _payload_bytes(packet.to_prompt_payload())
    outcome.stage_ms["packet_build_ms"] = _elapsed(started)

    # -- 9. LLM call: grounded answer ---------------------------------------
    started = time.perf_counter()
    generated = answer(packet.to_prompt_payload())
    outcome.llm_calls += 1
    outcome.stage_ms["answer_llm_ms"] = _elapsed(started)
    outcome.used_general_knowledge = bool(getattr(generated, "used_general_knowledge", False))

    # -- 10. deterministic response validation ------------------------------
    started = time.perf_counter()
    answer_validation = validate_answer(generated, packet, results)
    if answer_validation.ok:
        outcome.answer = generated.answer
    else:
        outcome.used_fallback = True
        outcome.answer_validation_failures = answer_validation.failures
        outcome.answer = build_fallback_answer(results)
        outcome.warnings.append(
            "the generated answer did not match the retrieved results, so a direct "
            "summary of those results was returned instead"
        )
    outcome.stage_ms["answer_validation_ms"] = _elapsed(started)

    # -- 11. viewer identities from the SAME result -------------------------
    started = time.perf_counter()
    hydration = hydrate_viewer_identities(session, results, primary_visual, settings)
    outcome.hydration = hydration
    outcome.statement_count += hydration.statement_count
    outcome.warnings.extend(hydration.warnings)
    outcome.stage_ms["viewer_hydration_ms"] = _elapsed(started)

    outcome.next_scope = _capture_scope(results, primary_visual)
    outcome.warnings.extend(_interpretation_notes(results))
    return outcome


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def _gate(plan: BindingPlan, validation: BindingValidation, coverage: LedgerCoverage) -> GateState:
    """Collapse binding + validation + coverage into one gate state (§4)."""
    if plan.needs_clarification:
        return GateState.NEEDS_CLARIFICATION

    structural_ok = validation.valid and bool(validation.valid_parts)

    if structural_ok and coverage.ok:
        return GateState.READY

    # An honest unavailable/ambiguous disposition that is otherwise well-formed is
    # NOT a gap to correct — the parts execute and report the limitation (§4, §5).
    if structural_ok and coverage.declared_failures and not _mechanical_gap(coverage):
        return GateState.READY

    if coverage.recoverable or not structural_ok:
        return GateState.RECOVERABLE_BINDING_GAP

    return GateState.INVALID


def _mechanical_gap(coverage: LedgerCoverage) -> bool:
    """True when something is missing/mis-kinded rather than honestly declared."""
    return bool(
        coverage.undisposed or coverage.mismatched or coverage.unsupported or coverage.invented
    )


def _gate_failures(validation: BindingValidation, coverage: LedgerCoverage) -> list[str]:
    return coverage.failures() + [i.detail for i in validation.all_issues()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def _payload_bytes(payload: dict[str, Any]) -> int:
    from app.llm.serialization import dumps_context

    return len(dumps_context(payload).encode("utf-8"))


def _primary_visual_part_id(plan: BindingPlan, results: list[AnswerPartResult]) -> str | None:
    explicit = [p.part_id for p in plan.answer_parts if p.is_primary_visual]
    if len(explicit) == 1:
        return explicit[0]
    visual = [r.part_id for r in results if r.has_visual_result]
    return visual[0] if len(visual) == 1 else (visual[0] if visual else None)


def _capture_scope(
    results: list[AnswerPartResult], primary_visual: str | None
) -> PreviousScope | None:
    target = next((r for r in results if r.part_id == primary_visual), None)
    if target is None:
        target = next((r for r in results if r.is_answerable), None)
    return capture_previous_scope(target) if target is not None else None


def _clarification_text(
    plan: BindingPlan, validation: BindingValidation, coverage: LedgerCoverage
) -> str:
    if plan.needs_clarification and plan.clarification_question:
        return plan.clarification_question
    detail = coverage.clarification() or validation.clarification()
    if not detail:
        return "Could you rephrase that question, or be more specific?"
    return (
        f"I couldn't answer that as asked: {detail}. "
        "I haven't answered a broader version instead, because that would describe a "
        "different set of objects. Could you rephrase that part?"
    )


def _interpretation_notes(results: list[AnswerPartResult]) -> list[str]:
    notes: list[str] = []
    for result in results:
        if result.interpretation and result.interpretation not in notes:
            notes.append(result.interpretation)
    return notes[:6]


def status_summary(results: list[AnswerPartResult]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for result in results:
        tally[result.status.value] = tally.get(result.status.value, 0) + 1
    return tally


def has_only_status(results: list[AnswerPartResult], status: ResultStatus) -> bool:
    return bool(results) and all(r.status is status for r in results)
