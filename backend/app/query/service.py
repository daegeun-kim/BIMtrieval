"""Top-level query service — the only entry point the HTTP layer calls.

Implements the Task 24 pipeline for one natural-language question:

    session/selection validation
    → deterministic candidate slate            (task24 §1)
    → LLM call 1: semantic binding             (task24 §2)
    → validation + IFC closure + mode derivation (task24 §3, §5.1)
    → one authoritative execution per part     (task24 §5.2)
    → compact answer packet                    (task24 §8.2)
    → LLM call 2: grounded answer              (task24 §8.1)
    → deterministic answer validation + viewer identities (task24 §8.3, §9)
    → safe JSONL logging + stable response serialization

**Exactly two principal LLM calls** for a normally answered active-model
question. There is no route-classification call, no plan-repair call, no
verifier, and no second answering call: an invalid binding becomes a
clarification, and an invalid answer becomes a deterministic fallback built from
the same authoritative results (task24 §10.1).

Catalog, clarify, and general-knowledge questions are preserved routes and use
the same final response contract for uniform style (task24 §11.1).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas.request import SessionQueryRequest
from app.api.schemas.response import (
    EvidenceSummary,
    PrimaryEntityResult,
    QueryResponseEnvelope,
    ResultSummary,
)
from app.config import trace
from app.config.logging import write_jsonl_event
from app.config.settings import Settings, get_settings
from app.db.session import session_scope
from app.llm.client import (
    LLMError,
    LLMUnavailableError,
    OpenAIQueryClient,
    get_llm_client,
)
from app.llm.prompts import BINDER_PROMPT_VERSION, GROUNDED_ANSWERER_PROMPT_VERSION
from app.query.binding.evidence import AnswerPartResult, ResultStatus
from app.query.binding.pipeline import (
    PipelineOutcome,
    PipelineRequest,
    run_pipeline,
    status_summary,
)
from app.query.catalog_answer import answer_catalog_question, is_catalog_question
from app.query.rag.embedding_service import get_embedding_service
from app.query.rag.hydration import hydrate_selected_entities
from app.query.selection import SelectionConflictError, resolve_selection
from app.query.session import SessionState, get_session_store
from app.query.sql import catalog as catalog_ops
from app.query.sql.schemas import GetModelMetadataPlan
from app.shared.errors import BimRagError, ModelNotFoundError
from app.shared.types import AnswerBasis, QueryRoute, QueryScope, ResponseStatus
from app.viewer.actions import (
    SelectionAction,
    ViewerActions,
    build_default_viewer_actions,
    build_load_model_actions,
    build_viewer_actions,
)
from app.viewer.assets import viewer_asset_ref

#: Result status -> the externally-reported answer basis. The route vocabulary
#: is preserved for existing clients (task24 §5.1: "the external response may
#: continue to use the existing route vocabulary").
_BASIS_BY_STATUS = {
    ResultStatus.EXACT: AnswerBasis.EXACT_SQL,
    ResultStatus.ZERO: AnswerBasis.EXACT_SQL,
    ResultStatus.PARTIAL: AnswerBasis.HYBRID_EVIDENCE,
    ResultStatus.UNAVAILABLE: AnswerBasis.INSUFFICIENT_EVIDENCE,
    ResultStatus.AMBIGUOUS: AnswerBasis.INSUFFICIENT_EVIDENCE,
}


class QueryService:
    def __init__(
        self,
        settings: Settings | None = None,
        llm_client: OpenAIQueryClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._llm_client = llm_client  # injectable for offline tests
        self.store = get_session_store()

    def _client(self) -> OpenAIQueryClient:
        """One client per service instance.

        Cached rather than constructed per call: `get_llm_client` returns a NEW
        client each time, and each client owns its own call log, so rebuilding
        it mid-question would scatter the per-question token accounting across
        objects nobody reads.
        """
        if self._llm_client is None:
            self._llm_client = get_llm_client(self.settings)
        return self._llm_client

    # -- public entry point --------------------------------------------------

    def handle_query(self, request: SessionQueryRequest) -> QueryResponseEnvelope:
        state = self.store.get_or_create(request.session_id)

        if request.reset:
            return self._handle_reset(request)
        if request.confirm_model_id is not None:
            return self._handle_confirmation(request, state)

        return self._handle_question(request, state)

    # -- control actions -----------------------------------------------------

    def _handle_reset(self, request: SessionQueryRequest) -> QueryResponseEnvelope:
        self.store.reset(request.session_id)
        return _envelope(
            request,
            scope=QueryScope.MODEL_CATALOG,
            route=QueryRoute.EXPLAIN_GENERAL,
            basis=AnswerBasis.INSUFFICIENT_EVIDENCE,
            answer="Session cleared. Chat history, selection, results, and active model reset. "
            "No stored model data was deleted.",
            active_source_model_id=None,
            viewer_actions=build_default_viewer_actions(),
        )

    def _handle_confirmation(
        self, request: SessionQueryRequest, state: SessionState
    ) -> QueryResponseEnvelope:
        model_id = request.confirm_model_id
        try:
            with session_scope() as session:
                row = catalog_ops.get_model_metadata(
                    session, GetModelMetadataPlan(source_model_id=model_id)
                )
                display = getattr(row, "display_name", None)
        except ModelNotFoundError:
            return _error_envelope(
                request,
                "That model is not in the catalog; pick a model from the listed candidates.",
            )
        viewer_source = viewer_asset_ref(model_id)

        # Switching models invalidates the previous typed scope (task24 §7).
        fresh = SessionState(session_id=request.session_id, mode=QueryScope.ACTIVE_MODEL)
        fresh.active_source_model_id = model_id
        self.store.save(fresh)

        return _envelope(
            request,
            scope=QueryScope.ACTIVE_MODEL,
            route=QueryRoute.SQL,
            basis=AnswerBasis.EXACT_SQL,
            answer=f"Loaded model {display or model_id}. Ask a question about it.",
            active_source_model_id=model_id,
            viewer_actions=build_load_model_actions(model_id, viewer_source),
        )

    # -- normal question path ------------------------------------------------

    def _handle_question(
        self, request: SessionQueryRequest, state: SessionState
    ) -> QueryResponseEnvelope:
        t0 = time.perf_counter()
        request_id = str(uuid.uuid4())
        scope = (
            QueryScope.ACTIVE_MODEL
            if request.active_source_model_id is not None
            else QueryScope.MODEL_CATALOG
        )

        # Reject selected GlobalIds with no active model before any LLM/DB work,
        # so this path makes zero provider calls.
        if request.selected_global_ids and request.active_source_model_id is None:
            return _error_envelope(
                request,
                "Selected objects require an active model. Load a model before selecting objects.",
                request_id=request_id,
                scope=scope,
            )

        client = self._client()
        # Snapshot the call log so ONLY this question's calls are summed. The
        # client is cached per service instance, so `client.log.calls` holds
        # every call the process has made — logging it wholesale would report a
        # cumulative total as if it were one question's cost.
        usage_start = len(client.log.calls) if hasattr(client, "log") else 0
        try:
            return self._answer_question(
                request, request_id, scope, client, state, t0, usage_start
            )
        finally:
            _emit_question_usage(client.log.calls[usage_start:])

    def _answer_question(
        self,
        request: SessionQueryRequest,
        request_id: str,
        scope: QueryScope,
        client: OpenAIQueryClient,
        state: SessionState,
        t0: float,
        usage_start: int = 0,
    ) -> QueryResponseEnvelope:
        try:
            with session_scope() as session:
                # Catalog scope has no active model to bind against (task24 §11.1).
                if request.active_source_model_id is None:
                    return answer_catalog_question(session, request, request_id, client)

                try:
                    selection = resolve_selection(
                        session,
                        request.active_source_model_id,
                        request.selected_global_ids,
                        request.selected_entity_ids,
                        self.settings.max_selected_entity_ids,
                    )
                except SelectionConflictError as exc:
                    self._log_failure(request, request_id, "selection_conflict", str(exc))
                    return _error_envelope(
                        request,
                        "Your selected objects were ambiguous or invalid for the active model. "
                        "Clear your selection and try again.",
                        request_id=request_id,
                        scope=scope,
                    )

                selected = [
                    {"entity_id": s.entity_id, "ifc_class": s.ifc_class, "name": s.name}
                    for s in hydrate_selected_entities(
                        session,
                        request.active_source_model_id,
                        selection.entity_ids[: self.settings.max_selected_entity_ids],
                    )
                ]

                # A previous scope from a DIFFERENT model can never apply here
                # (task24 §7).
                previous = state.previous_scope
                if previous is not None and not previous.matches_model(
                    request.active_source_model_id
                ):
                    previous = None

                try:
                    outcome = run_pipeline(
                        session,
                        PipelineRequest(
                            question=request.question,
                            source_model_id=request.active_source_model_id,
                            history=[
                                {"role": t.role, "content": t.content}
                                for t in request.history[-self.settings.max_history_turns :]
                            ],
                            selected_entities=selected,
                            selection_entity_ids=selection.entity_ids,
                            previous_scope=previous,
                        ),
                        bind=lambda ctx: client.bind_query(ctx).plan,
                        answer=lambda payload: client.generate_grounded_answer(payload).output,
                        settings=self.settings,
                        embedding_service_getter=get_embedding_service,
                    )
                except (BimRagError, SQLAlchemyError) as exc:
                    # A validated binding can still hit an execution-time defect.
                    # Degrade to a clarification rather than a raw 500.
                    self._log_failure(request, request_id, "execution_error", str(exc))
                    return _error_envelope(
                        request,
                        "I couldn't complete that query against the model. Could you rephrase "
                        "it or narrow it down?",
                        request_id=request_id,
                        scope=scope,
                    )

                envelope = self._build_envelope(request, request_id, outcome)
                envelope.warnings = (list(envelope.warnings) + list(selection.warnings))[:20]
                self._finalize_state(state, request, outcome)
                self._log_event(request, request_id, outcome, client, t0, usage_start)
                return envelope
        except LLMUnavailableError as exc:
            self._log_failure(request, request_id, "llm_unavailable", str(exc))
            return _error_envelope(
                request,
                "The language model is currently unavailable. Please try again shortly.",
                request_id=request_id,
                scope=scope,
            )
        except LLMError as exc:
            self._log_failure(request, request_id, "llm_error", str(exc))
            return _error_envelope(
                request,
                "The language model could not complete this request.",
                request_id=request_id,
                scope=scope,
            )

    # -- response assembly ---------------------------------------------------

    def _build_envelope(
        self,
        request: SessionQueryRequest,
        request_id: str,
        outcome: PipelineOutcome,
    ) -> QueryResponseEnvelope:
        primary = outcome.primary_result
        if outcome.needs_clarification or primary is None:
            return _envelope(
                request,
                scope=QueryScope.ACTIVE_MODEL,
                route=QueryRoute.CLARIFY,
                basis=AnswerBasis.INSUFFICIENT_EVIDENCE,
                answer=outcome.answer,
                active_source_model_id=request.active_source_model_id,
                viewer_actions=build_default_viewer_actions(),
                request_id=request_id,
                warnings=outcome.warnings[:20],
            )

        hydration = outcome.hydration
        basis = _BASIS_BY_STATUS.get(primary.status, AnswerBasis.INSUFFICIENT_EVIDENCE)
        if any(r.rag_candidate_count for r in outcome.results):
            basis = AnswerBasis.HYBRID_EVIDENCE
        if any(r.operation == "relationship" for r in outcome.results):
            basis = AnswerBasis.GRAPH_TRAVERSAL

        return QueryResponseEnvelope(
            request_id=request_id,
            session_id=request.session_id,
            status=ResponseStatus.SUCCESS,
            scope=QueryScope.ACTIVE_MODEL,
            route=QueryRoute.HYBRID,
            answer_basis=basis,
            answer=outcome.answer,
            active_source_model_id=request.active_source_model_id,
            primary_entities=_grounding_entities(outcome.results, self.settings),
            viewer_actions=_viewer_actions(hydration),
            evidence_summary=EvidenceSummary(
                basis=basis,
                sql_match_count=primary.exact_total,
                rag_candidate_count=primary.rag_candidate_count,
                relationship_count=(
                    len(primary.graph_endpoints) if primary.graph_endpoints else None
                ),
                notes=[r.limitation for r in outcome.results if r.limitation][:20],
            ),
            result_summary=ResultSummary(
                exact_total=primary.exact_total,
                viewer_match_count=len(hydration.primary_global_ids),
                viewer_matches_total=hydration.viewer_matches_total or None,
                truncated=hydration.viewer_matches_truncated,
                class_counts=hydration.class_counts,
            ),
            warnings=outcome.warnings[:20],
        )

    # -- state + logging -----------------------------------------------------

    def _finalize_state(
        self, state: SessionState, request: SessionQueryRequest, outcome: PipelineOutcome
    ) -> None:
        state.mode = QueryScope.ACTIVE_MODEL
        state.active_source_model_id = request.active_source_model_id
        state.last_route = "hybrid"
        # The typed scope replaces the id list as the follow-up basis (§7).
        state.previous_scope = outcome.next_scope
        state.last_primary_entity_ids = [e.entity_id for e in _all_examples(outcome.results)][:200]
        state.last_context_entity_ids = []
        state.last_relationship_ids = []
        state.pending_candidate_model_ids = []
        self.store.save(state)

    def _log_event(
        self,
        request: SessionQueryRequest,
        request_id: str,
        outcome: PipelineOutcome,
        client: OpenAIQueryClient,
        t0: float,
        usage_start: int = 0,
    ) -> None:
        """Bounded diagnostic record (task24 §10.2, §10.5). No prompts, vectors,
        canonical JSON, SQL params, or full GlobalId lists.

        `usage_start` slices the client's call log to THIS question's calls; the
        client is process-lived, so logging the whole list would report a
        running total as one question's token cost."""
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        record = {
            "event": "query",
            "pipeline": "task24_binding",
            "request_id": request_id,
            "session_id": request.session_id,
            "active_source_model_id": request.active_source_model_id,
            "question": request.question,
            "planner_model": self.settings.get_planner_model(),
            "answer_model": self.settings.get_answer_model(),
            "binder_prompt_version": BINDER_PROMPT_VERSION,
            "answer_prompt_version": GROUNDED_ANSWERER_PROMPT_VERSION,
            "llm_calls": outcome.llm_calls,
            "slate": (outcome.slate.size_report() if outcome.slate else {}),
            "slate_bytes": outcome.slate_bytes,
            "answer_packet_bytes": outcome.packet_bytes,
            "answer_parts": [
                {
                    "part_id": r.part_id,
                    "operation": r.operation,
                    "status": r.status.value,
                    "exact_total": r.exact_total,
                    "modes": [m.value for m in r.modes_executed],
                    "statements": r.statement_count,
                    "duration_ms": r.duration_ms,
                }
                for r in outcome.results
            ],
            "status_summary": status_summary(outcome.results),
            "needs_clarification": outcome.needs_clarification,
            "answer_validation_failed": outcome.used_fallback,
            "answer_validation_failures": outcome.answer_validation_failures[:5],
            "general_knowledge_used": outcome.used_general_knowledge,
            "viewer_matches_total": outcome.hydration.viewer_matches_total,
            "viewer_returned": len(outcome.hydration.primary_global_ids),
            "database_statements": outcome.statement_count,
            "warnings": outcome.warnings[:20],
            "token_usage": client.log.calls[usage_start:],
            "latency_ms": latency_ms,
            "stage_latency_ms": outcome.stage_ms,
        }
        write_jsonl_event(record, Path(self.settings.query_log_path))
        _emit_backend_timing(request_id, outcome, latency_ms)

    def _log_failure(
        self, request: SessionQueryRequest, request_id: str, kind: str, detail: str
    ) -> None:
        record = {
            "event": "failure",
            "kind": kind,
            "request_id": request_id,
            "session_id": request.session_id,
            "active_source_model_id": request.active_source_model_id,
            "question": request.question,
            "detail": detail,
        }
        write_jsonl_event(record, Path(self.settings.failure_case_path))


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _all_examples(results: list[AnswerPartResult]) -> list:
    seen: set[int] = set()
    out: list = []
    for result in results:
        for example in result.examples:
            if example.entity_id not in seen:
                seen.add(example.entity_id)
                out.append(example)
    return out


def _grounding_entities(
    results: list[AnswerPartResult], settings: Settings
) -> list[PrimaryEntityResult]:
    """Bounded grounding entities for citations, from the answer parts' examples."""
    return [
        PrimaryEntityResult(
            entity_id=e.entity_id,
            global_id=e.global_id,
            ifc_class=e.ifc_class,
            name=e.name,
        )
        for e in _all_examples(results)[: settings.max_primary_entities]
    ]


def _viewer_actions(hydration) -> ViewerActions:
    """§9: zero/unavailable answers highlight nothing — no fallback set."""
    if not hydration.has_selection:
        return build_default_viewer_actions()
    return build_viewer_actions(
        selection_action=SelectionAction.SELECT_AND_FIT,
        primary_global_ids=hydration.primary_global_ids,
        context_global_ids=hydration.context_global_ids,
        viewer_matches_total=hydration.viewer_matches_total,
        viewer_matches_truncated=hydration.viewer_matches_truncated,
    )


def _emit_question_usage(calls: list[dict]) -> None:
    """One per-question provider usage block, summed from API-reported usage."""
    if not calls:
        return
    trace.emit_openai_usage(
        prompt_tokens=sum(int(c.get("prompt_tokens", 0) or 0) for c in calls),
        completion_tokens=sum(int(c.get("completion_tokens", 0) or 0) for c in calls),
        total_tokens=sum(int(c.get("total_tokens", 0) or 0) for c in calls),
    )


def _emit_backend_timing(request_id: str, outcome: PipelineOutcome, total_ms: float) -> None:
    trace.emit(
        "[Query backend timing]",
        {
            "request_id": request_id,
            "stages_ms": outcome.stage_ms,
            "llm_calls": outcome.llm_calls,
            "db_statements": outcome.statement_count,
            "slate_bytes": outcome.slate_bytes,
            "packet_bytes": outcome.packet_bytes,
            "backend_total_ms": total_ms,
        },
        force=True,
    )


def _envelope(
    request: SessionQueryRequest,
    *,
    scope: QueryScope,
    route: QueryRoute,
    basis: AnswerBasis,
    answer: str,
    active_source_model_id: int | None,
    viewer_actions: ViewerActions,
    request_id: str | None = None,
    warnings: list[str] | None = None,
) -> QueryResponseEnvelope:
    return QueryResponseEnvelope(
        request_id=request_id or str(uuid.uuid4()),
        session_id=request.session_id,
        status=ResponseStatus.SUCCESS,
        scope=scope,
        route=route,
        answer_basis=basis,
        answer=answer,
        active_source_model_id=active_source_model_id,
        viewer_actions=viewer_actions,
        evidence_summary=EvidenceSummary(basis=basis),
        warnings=warnings or [],
    )


def _error_envelope(
    request: SessionQueryRequest,
    message: str,
    *,
    request_id: str | None = None,
    scope: QueryScope = QueryScope.MODEL_CATALOG,
) -> QueryResponseEnvelope:
    return QueryResponseEnvelope(
        request_id=request_id or str(uuid.uuid4()),
        session_id=request.session_id,
        status=ResponseStatus.ERROR,
        scope=scope,
        route=QueryRoute.CLARIFY,
        answer_basis=AnswerBasis.INSUFFICIENT_EVIDENCE,
        answer=message,
        active_source_model_id=request.active_source_model_id,
        viewer_actions=build_default_viewer_actions(),
        evidence_summary=EvidenceSummary(basis=AnswerBasis.INSUFFICIENT_EVIDENCE),
        warnings=[],
    )


def get_query_service() -> QueryService:
    return QueryService()


__all__ = ["QueryService", "get_query_service", "is_catalog_question"]
