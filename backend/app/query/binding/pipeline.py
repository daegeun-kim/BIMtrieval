"""The Task 24 active query pipeline (§Required architecture).

    question + bounded history + typed previous scope
      -> deterministic candidate slate from cached model semantics
      -> LLM call 1: bind requested answer parts to candidate IDs
      -> deterministic validation, IFC semantic closure, retrieval-mode derivation
      -> ONE authoritative execution per answer part
      -> compact answer packet containing only adjudicated results
      -> LLM call 2: uniform grounded answer writing
      -> deterministic response validation and viewer identities from the same results

**Exactly two principal LLM calls** for a normally answered active-model
question (§10.1). There is no router, verifier, judge, repair, reflection,
correction, reranking, or replanning call anywhere in this module, and an
invalid binding or invalid final answer does not trigger a third model request:
an invalid binding becomes a clarification/unavailable result, and an invalid
answer becomes a deterministic fallback assembled from the same authoritative
results.

This module owns orchestration only. Every decision it coordinates lives in a
dedicated module (`slate`, `validate`, `closure`, `compile`, `execute`,
`packet`, `answer_validation`, `viewer`), so the flow above is readable in one
place without any of it being reimplemented here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.llm.binder_context import build_binder_context
from app.llm.schemas import BindingPlan
from app.query.binding.answer_validation import build_fallback_answer, validate_answer
from app.query.binding.evidence import AnswerPartResult, ResultStatus
from app.query.binding.execute import ExecutionContext, execute_answer_part
from app.query.binding.packet import AnswerPacket, build_answer_packet
from app.query.binding.previous_scope import (
    PreviousScope,
    capture_previous_scope,
    resolve_previous_entity_ids,
)
from app.query.binding.schemas import CandidateSlate, SlateCaps
from app.query.binding.slate import SlateInputs, build_slate
from app.query.binding.validate import BindingValidation, validate_binding
from app.query.binding.viewer import ViewerHydration, hydrate_viewer_identities

__all__ = ["PipelineOutcome", "PipelineRequest", "run_pipeline"]


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
    """Everything the HTTP layer needs, plus per-stage diagnostics (§10.5)."""

    answer: str
    results: list[AnswerPartResult] = field(default_factory=list)
    slate: CandidateSlate | None = None
    binding: BindingPlan | None = None
    validation: BindingValidation | None = None
    packet: AnswerPacket | None = None
    hydration: ViewerHydration = field(default_factory=ViewerHydration)
    next_scope: PreviousScope | None = None

    needs_clarification: bool = False
    used_fallback: bool = False
    answer_validation_failures: list[str] = field(default_factory=list)
    used_general_knowledge: bool = False
    warnings: list[str] = field(default_factory=list)

    #: §10.5 requires each of these measured separately.
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
    settings: Settings | None = None,
    caps: SlateCaps | None = None,
    embedding_service_getter: Callable[[], Any] | None = None,
) -> PipelineOutcome:
    """Run one question end to end.

    `bind` and `answer` are injected so the pipeline is testable without a
    provider — they are the ONLY two model calls in the flow.
    """
    settings = settings or get_settings()
    outcome = PipelineOutcome(answer="")

    # -- 1. deterministic candidate slate -----------------------------------
    started = time.perf_counter()
    previous_ids = resolve_previous_entity_ids(
        session, request.previous_scope, request.source_model_id
    )
    slate = build_slate(
        session,
        SlateInputs(
            question=request.question,
            source_model_id=request.source_model_id,
            history=request.history,
            selected_entities=request.selected_entities,
            previous_scope=request.previous_scope,
        ),
        settings=settings,
        caps=caps,
        embedding_service_getter=embedding_service_getter,
    )
    outcome.slate = slate
    outcome.stage_ms["slate_build_ms"] = _elapsed(started)
    outcome.slate_bytes = _payload_bytes(slate.to_prompt_payload())

    # -- 2. LLM call 1: semantic binding ------------------------------------
    started = time.perf_counter()
    binder_context = build_binder_context(
        request.question,
        slate,
        settings=settings,
        history=request.history,
        selected_entities=request.selected_entities,
        previous_scope=request.previous_scope,
        active_source_model_id=request.source_model_id,
    )
    plan = bind(binder_context)
    outcome.binding = plan
    outcome.llm_calls += 1
    outcome.stage_ms["binding_llm_ms"] = _elapsed(started)

    # -- 3. deterministic validation + semantic closure ---------------------
    started = time.perf_counter()
    validation = validate_binding(plan, slate)
    outcome.validation = validation
    outcome.stage_ms["binding_validation_ms"] = _elapsed(started)

    if plan.needs_clarification:
        outcome.needs_clarification = True
        outcome.answer = plan.clarification_question or "Could you clarify that question?"
        return outcome

    # PLAN-level issues block everything, not just the part they touch: they mean
    # the question as a whole was misread (an unaccounted qualifier, a dropped
    # modifier, a contested visual part). Executing the individually-valid parts
    # anyway is precisely how "how many parking spaces?" once returned every
    # space in the model — the subject bound fine, and only the qualifier was
    # lost.
    if validation.issues or not validation.valid_parts:
        # Nothing safely executable. This returns a clarification WITHOUT a
        # second planning call — §3.3 forbids one, and silently broadening
        # instead would answer a question the user did not ask.
        outcome.needs_clarification = True
        outcome.answer = _clarification_text(validation)
        outcome.warnings.extend(i.detail for i in validation.all_issues()[:5])
        return outcome

    # -- 4. one authoritative execution per answer part ---------------------
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
    results = [execute_answer_part(part, context) for part in validation.parts]
    outcome.results = results
    outcome.statement_count += sum(r.statement_count for r in results)
    outcome.stage_ms["execution_ms"] = _elapsed(started)

    # -- 5. compact answer packet -------------------------------------------
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

    # -- 6. LLM call 2: grounded answer -------------------------------------
    started = time.perf_counter()
    generated = answer(packet.to_prompt_payload())
    outcome.llm_calls += 1
    outcome.stage_ms["answer_llm_ms"] = _elapsed(started)
    outcome.used_general_knowledge = bool(getattr(generated, "used_general_knowledge", False))

    # -- 7. deterministic response validation -------------------------------
    started = time.perf_counter()
    answer_validation = validate_answer(generated, packet, results)
    if answer_validation.ok:
        outcome.answer = generated.answer
    else:
        # No third model call. A safe answer is assembled from the same
        # authoritative results the model was given (§8.3).
        outcome.used_fallback = True
        outcome.answer_validation_failures = answer_validation.failures
        outcome.answer = build_fallback_answer(results)
        outcome.warnings.append(
            "the generated answer did not match the retrieved results, so a direct "
            "summary of those results was returned instead"
        )
    outcome.stage_ms["answer_validation_ms"] = _elapsed(started)

    # -- 8. viewer identities from the SAME result --------------------------
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
# Helpers
# ---------------------------------------------------------------------------


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def _payload_bytes(payload: dict[str, Any]) -> int:
    from app.llm.serialization import dumps_context

    return len(dumps_context(payload).encode("utf-8"))


def _primary_visual_part_id(plan: BindingPlan, results: list[AnswerPartResult]) -> str | None:
    """The one part that drives the viewer (§9).

    Prefers the binding's explicit choice; otherwise the single visual part.
    Never a union of parts.
    """
    explicit = [p.part_id for p in plan.answer_parts if p.is_primary_visual]
    if len(explicit) == 1:
        return explicit[0]
    visual = [r.part_id for r in results if r.has_visual_result]
    return visual[0] if len(visual) == 1 else (visual[0] if visual else None)


def _capture_scope(
    results: list[AnswerPartResult], primary_visual: str | None
) -> PreviousScope | None:
    """Store the accepted part as a re-executable follow-up scope (§7)."""
    target = next((r for r in results if r.part_id == primary_visual), None)
    if target is None:
        target = next((r for r in results if r.is_answerable), None)
    return capture_previous_scope(target) if target is not None else None


def _clarification_text(validation: BindingValidation) -> str:
    """A concise, specific reason — so the user can rephrase precisely."""
    detail = validation.clarification()
    if not detail:
        return "Could you rephrase that question, or be more specific?"
    return (
        f"I couldn't answer that as asked: {detail}. "
        "I haven't answered a broader version instead, because that would describe a "
        "different set of objects. Could you rephrase that part?"
    )


def _interpretation_notes(results: list[AnswerPartResult]) -> list[str]:
    """Surface how conditions were read, so the user can correct them."""
    notes: list[str] = []
    for result in results:
        if result.interpretation and result.interpretation not in notes:
            notes.append(result.interpretation)
    return notes[:6]


def status_summary(results: list[AnswerPartResult]) -> dict[str, int]:
    """Bounded per-status tally for diagnostics."""
    tally: dict[str, int] = {}
    for result in results:
        tally[result.status.value] = tally.get(result.status.value, 0) + 1
    return tally


def has_only_status(results: list[AnswerPartResult], status: ResultStatus) -> bool:
    return bool(results) and all(r.status is status for r in results)
