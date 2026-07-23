"""Top-level query service — the only entry point the HTTP layer calls.

Implements the experiment2_v4 pipeline for one natural-language question:

    trace accumulator created FIRST (task26 §14.2)
    → session/selection validation
    → v002 manifest + binder projection
    → deterministic requirement ledger + always-parallel recall
    → LLM call 1: typed logical plan
    → ten-layer validation, optional budget-gated correction
    → per-part compilation + authoritative execution
    → answer packet → LLM call 2 → claim validation / deterministic fallback
    → typed viewer sets
    → exactly ONE terminal record appended to the permanent query trace

**Exactly two principal LLM calls** for a normally answered active-model
question; one budget-gated correction at most; no request exceeds three.
Provider failures degrade at the stage that owns them (§13). Every request —
questions, catalog questions, reset, confirmation, early errors — appends one
terminal record to `backend/app/evaluation/query_trace.jsonl`; the two v3 log
files receive no further writes.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas.request import SessionQueryRequest
from app.api.schemas.response import (
    EvidenceSummary,
    PrimaryEntityResult,
    QueryResponseEnvelope,
    ResultSummary,
)
from app.config import trace
from app.config.settings import Settings, get_settings
from app.db.session import session_scope
from app.llm.client import (
    LLMError,
    LLMUnavailableError,
    OpenAIQueryClient,
    get_llm_client,
)
from app.llm.prompts import (
    BINDER_V3_PROMPT_VERSION,
    GROUNDED_ANSWERER_V2_PROMPT_VERSION,
)
from app.query.binding.pipeline import (
    PIPELINE_VERSION,
    PipelineOutcome,
    PipelineRequest,
    run_pipeline,
    status_summary,
)
from app.query.binding.results_v2 import PartResultV2, ResultStatusV2
from app.query.catalog_answer import answer_catalog_question, is_catalog_question
from app.query.rag.embedding_service import get_embedding_service
from app.query.rag.hydration import hydrate_selected_entities
from app.query.selection import SelectionConflictError, resolve_selection
from app.query.session import SessionState, get_session_store
from app.query.sql import catalog as catalog_ops
from app.query.sql.schemas import GetModelMetadataPlan
from app.query.trace_v2 import QueryTrace, resolve_trace_path
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

_BASIS_BY_STATUS = {
    ResultStatusV2.EXACT: AnswerBasis.EXACT_SQL,
    ResultStatusV2.ZERO: AnswerBasis.EXACT_SQL,
    ResultStatusV2.PARTIAL: AnswerBasis.HYBRID_EVIDENCE,
    ResultStatusV2.UNAVAILABLE: AnswerBasis.INSUFFICIENT_EVIDENCE,
    ResultStatusV2.AMBIGUOUS: AnswerBasis.INSUFFICIENT_EVIDENCE,
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
        if self._llm_client is None:
            self._llm_client = get_llm_client(self.settings)
        return self._llm_client

    # -- public entry point --------------------------------------------------

    def handle_query(self, request: SessionQueryRequest) -> QueryResponseEnvelope:
        # §14.2: the accumulator exists BEFORE reset, confirmation, selection
        # validation, catalog routing, LLM creation, or database work.
        request_id = str(uuid.uuid4())
        action = (
            "reset"
            if request.reset
            else "confirm_model"
            if request.confirm_model_id is not None
            else "question"
        )
        query_trace = QueryTrace(
            request_id=request_id,
            session_id=request.session_id,
            action=action,
            trace_path=resolve_trace_path(self.settings.query_trace_path),
        )
        query_trace.set(
            question=request.question,
            active_source_model_id=request.active_source_model_id,
            history=[
                {"role": t.role, "content": t.content} for t in request.history[-6:]
            ],
            selected_global_ids=list(request.selected_global_ids or [])[:200],
            selected_entity_ids=list(request.selected_entity_ids or [])[:200],
        )
        try:
            state = self.store.get_or_create(request.session_id)
            if request.reset:
                envelope = self._handle_reset(request, request_id)
                query_trace.terminal("response_delivery", "success")
            elif request.confirm_model_id is not None:
                envelope = self._handle_confirmation(request, state, request_id, query_trace)
            else:
                envelope = self._handle_question(request, state, request_id, query_trace)
            query_trace.set_delivery(
                answer=envelope.answer,
                envelope=envelope.model_dump(mode="json"),
                viewer_global_ids=list(
                    getattr(envelope.viewer_actions, "primary_global_ids", []) or []
                ),
                viewer_total=(
                    envelope.result_summary.viewer_matches_total
                    if envelope.result_summary
                    else None
                ),
                viewer_truncated=(
                    envelope.result_summary.truncated if envelope.result_summary else None
                ),
            )
            return envelope
        except Exception as exc:
            query_trace.terminal("request_handling", "unhandled_error")
            query_trace.add_stage(
                "request_handling", "failed", error=f"{type(exc).__name__}: {str(exc)[:300]}"
            )
            raise
        finally:
            query_trace.flush()

    # -- control actions -----------------------------------------------------

    def _handle_reset(
        self, request: SessionQueryRequest, request_id: str
    ) -> QueryResponseEnvelope:
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
            request_id=request_id,
        )

    def _handle_confirmation(
        self,
        request: SessionQueryRequest,
        state: SessionState,
        request_id: str,
        query_trace: QueryTrace,
    ) -> QueryResponseEnvelope:
        model_id = request.confirm_model_id
        try:
            with session_scope() as session:
                row = catalog_ops.get_model_metadata(
                    session, GetModelMetadataPlan(source_model_id=model_id)
                )
                display = getattr(row, "display_name", None)
        except ModelNotFoundError:
            query_trace.terminal("request_validation", "invalid_model")
            return _error_envelope(
                request,
                "That model is not in the catalog; pick a model from the listed candidates.",
                request_id=request_id,
            )
        viewer_source = viewer_asset_ref(model_id)

        fresh = SessionState(session_id=request.session_id, mode=QueryScope.ACTIVE_MODEL)
        fresh.active_source_model_id = model_id
        self.store.save(fresh)
        query_trace.terminal("response_delivery", "success")

        return _envelope(
            request,
            scope=QueryScope.ACTIVE_MODEL,
            route=QueryRoute.SQL,
            basis=AnswerBasis.EXACT_SQL,
            answer=f"Loaded model {display or model_id}. Ask a question about it.",
            active_source_model_id=model_id,
            viewer_actions=build_load_model_actions(model_id, viewer_source),
            request_id=request_id,
        )

    # -- normal question path ------------------------------------------------

    def _handle_question(
        self,
        request: SessionQueryRequest,
        state: SessionState,
        request_id: str,
        query_trace: QueryTrace,
    ) -> QueryResponseEnvelope:
        t0 = time.perf_counter()
        scope = (
            QueryScope.ACTIVE_MODEL
            if request.active_source_model_id is not None
            else QueryScope.MODEL_CATALOG
        )

        if request.selected_global_ids and request.active_source_model_id is None:
            query_trace.terminal("request_validation", "selection_without_model")
            return _error_envelope(
                request,
                "Selected objects require an active model. Load a model before selecting objects.",
                request_id=request_id,
                scope=scope,
            )

        client = self._client()
        query_trace.set_versions(
            binder_model=self.settings.get_binder_model(),
            correction_model=self.settings.get_correction_model(),
            answer_model=self.settings.get_answer_model(),
            binder_effort=self.settings.binder_reasoning_effort,
            answer_effort=self.settings.answer_reasoning_effort,
            binder_prompt=BINDER_V3_PROMPT_VERSION,
            answer_prompt=GROUNDED_ANSWERER_V2_PROMPT_VERSION,
            service_tier=self.settings.openai_service_tier,
        )
        has_log = hasattr(client, "log")
        usage_start = len(client.log.calls) if has_log else 0
        try:
            return self._answer_question(
                request, request_id, scope, client, state, t0, query_trace
            )
        finally:
            if has_log:
                calls = client.log.calls[usage_start:]
                query_trace.set(token_usage=calls)
                _emit_question_usage(calls)

    def _answer_question(
        self,
        request: SessionQueryRequest,
        request_id: str,
        scope: QueryScope,
        client: OpenAIQueryClient,
        state: SessionState,
        t0: float,
        query_trace: QueryTrace,
    ) -> QueryResponseEnvelope:
        try:
            with session_scope() as session:
                if request.active_source_model_id is None:
                    envelope = answer_catalog_question(session, request, request_id, client)
                    query_trace.terminal("response_delivery", "success")
                    query_trace.add_stage("catalog_question", "ok")
                    return envelope

                try:
                    selection = resolve_selection(
                        session,
                        request.active_source_model_id,
                        request.selected_global_ids,
                        request.selected_entity_ids,
                        self.settings.max_selected_entity_ids,
                    )
                except SelectionConflictError as exc:
                    query_trace.terminal("request_validation", "selection_conflict")
                    query_trace.add_stage(
                        "request_validation", "failed", error=str(exc)[:300]
                    )
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
                        bind=client.bind_query_v2,
                        correct=client.correct_binding_v2,
                        answer=client.generate_grounded_answer_v2,
                        settings=self.settings,
                        embedding_service_getter=get_embedding_service,
                    )
                except (BimRagError, SQLAlchemyError) as exc:
                    query_trace.terminal("execution", "execution_error")
                    query_trace.add_stage(
                        "execution", "failed", error=f"{type(exc).__name__}: {str(exc)[:300]}"
                    )
                    return _error_envelope(
                        request,
                        "I couldn't complete that query against the model. Could you rephrase "
                        "it or narrow it down?",
                        request_id=request_id,
                        scope=scope,
                    )

                _record_outcome(query_trace, outcome)
                envelope = self._build_envelope(request, request_id, outcome)
                envelope.warnings = (list(envelope.warnings) + list(selection.warnings))[:20]
                self._finalize_state(state, request, outcome)
                _emit_backend_timing(
                    request_id, outcome, round((time.perf_counter() - t0) * 1000.0, 1)
                )
                return envelope
        except LLMUnavailableError as exc:
            stage = getattr(exc, "stage", None) or "binding_llm"
            query_trace.terminal(stage, "provider_failure")
            query_trace.add_stage(stage, "failed", error=str(exc)[:300])
            return _error_envelope(
                request,
                "The language model is currently unavailable. Please try again shortly.",
                request_id=request_id,
                scope=scope,
            )
        except LLMError as exc:
            stage = getattr(exc, "stage", None) or "binding_llm"
            query_trace.terminal(stage, "provider_failure")
            query_trace.add_stage(stage, "failed", error=str(exc)[:300])
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
        if any(r.evidence is not None and r.evidence.excerpts for r in outcome.results):
            basis = AnswerBasis.HYBRID_EVIDENCE
        if any(r.result_kind == "graph_endpoints" for r in outcome.results):
            basis = AnswerBasis.GRAPH_TRAVERSAL

        matched = None
        entity_result = getattr(primary, "result", None)
        if entity_result is not None:
            matched = getattr(entity_result, "matched_cardinality", None)
            if matched is None:
                matched = getattr(entity_result, "endpoint_entity_count", None)

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
                sql_match_count=matched,
                rag_candidate_count=(
                    len(primary.evidence.excerpts) if primary.evidence else None
                ),
                notes=[
                    limitation["text"]
                    for r in outcome.results
                    for limitation in r.limitations
                ][:20],
            ),
            result_summary=ResultSummary(
                exact_total=matched if primary.status is not ResultStatusV2.PARTIAL else matched,
                viewer_match_count=len(hydration.primary_global_ids),
                viewer_matches_total=hydration.viewer_matches_total or None,
                truncated=hydration.viewer_matches_truncated,
                class_counts=hydration.class_counts,
            ),
            warnings=outcome.warnings[:20],
        )

    # -- state ---------------------------------------------------------------

    def _finalize_state(
        self, state: SessionState, request: SessionQueryRequest, outcome: PipelineOutcome
    ) -> None:
        state.mode = QueryScope.ACTIVE_MODEL
        state.active_source_model_id = request.active_source_model_id
        state.last_route = "hybrid"
        state.previous_scope = outcome.next_scope
        state.last_primary_entity_ids = [
            e.entity_id for r in outcome.results for e in r.examples
        ][:200]
        state.last_context_entity_ids = []
        state.last_relationship_ids = []
        state.pending_candidate_model_ids = []
        self.store.save(state)


# ---------------------------------------------------------------------------
# Trace assembly
# ---------------------------------------------------------------------------


def _record_outcome(query_trace: QueryTrace, outcome: PipelineOutcome) -> None:
    """Move the pipeline's bounded diagnostics into the terminal record (§14.5)."""
    query_trace.extend_stages([s.to_payload() for s in outcome.stages])
    query_trace.terminal(outcome.terminal_stage, outcome.terminal_status)
    if outcome.manifest is not None:
        query_trace.set_versions(
            manifest_schema="v002",
            manifest_builder=outcome.manifest.builder_version,
            contract_version=outcome.manifest.contract_version,
            manifest_content_hash=outcome.manifest.content_hash[:16],
            extraction_version=outcome.manifest.extraction_version,
            source_model_fingerprint=outcome.manifest.file_fingerprint[:16],
            ifc_schema=outcome.manifest.ifc_schema,
        )
    if outcome.projection is not None:
        query_trace.set_versions(
            projection_hash=outcome.projection.projection_hash[:16],
            projection_tokens=outcome.projection.estimated_tokens,
        )
    if outcome.ledger is not None:
        query_trace.set(ledger=outcome.ledger.to_payload())
    if outcome.recall is not None:
        query_trace.set(
            recommendations=[r.to_payload() for r in outcome.recall.recommendations][:48],
            value_links={
                rid: [link.to_payload() for link in links[:4]]
                for rid, links in outcome.recall.value_links.items()
            },
        )
    if outcome.plan is not None:
        query_trace.set(binder_output=outcome.plan.model_dump(mode="json"))
    if outcome.corrected_plan is not None:
        query_trace.set(correction_output=outcome.corrected_plan.model_dump(mode="json"))
    if outcome.validation is not None:
        query_trace.set(
            validation={
                "states": {
                    v.part.part_id: v.state.value for v in outcome.validation.verdicts
                },
                "issues": [i.to_payload() for i in outcome.validation.all_issues()][:16],
            }
        )
        query_trace.set(
            physical_plans=[
                v.compiled.diagnostics
                for v in outcome.validation.verdicts
                if v.compiled is not None
            ]
        )
    if outcome.results:
        query_trace.set(
            results=[r.to_packet_payload() for r in outcome.results],
            status_summary=status_summary(outcome.results),
        )
    if outcome.raw_answer is not None:
        query_trace.set(raw_answer_output=outcome.raw_answer.model_dump(mode="json"))
    query_trace.set(
        llm_calls=outcome.llm_calls,
        used_correction=outcome.used_correction,
        correction_skipped_reason=outcome.correction_skipped_reason,
        used_fallback=outcome.used_fallback,
        answer_validation_failures=outcome.answer_validation_failures[:5],
        database_statements=outcome.statement_count,
        budget=outcome.budget.to_payload(),
        warnings=outcome.warnings[:20],
    )


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _grounding_entities(
    results: list[PartResultV2], settings: Settings
) -> list[PrimaryEntityResult]:
    seen: set[int] = set()
    out: list[PrimaryEntityResult] = []
    for result in results:
        for example in result.examples:
            if example.entity_id in seen:
                continue
            seen.add(example.entity_id)
            out.append(
                PrimaryEntityResult(
                    entity_id=example.entity_id,
                    global_id=example.global_id,
                    ifc_class=example.ifc_class,
                    name=example.name,
                )
            )
    return out[: settings.max_primary_entities]


def _viewer_actions(hydration) -> ViewerActions:
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
    if not calls:
        return
    trace.emit_openai_usage(
        prompt_tokens=sum(int(c.get("prompt_tokens", 0) or 0) for c in calls),
        completion_tokens=sum(int(c.get("completion_tokens", 0) or 0) for c in calls),
        total_tokens=sum(int(c.get("total_tokens", 0) or 0) for c in calls),
    )
    _emit_openai_cost(calls)


def _emit_openai_cost(calls: list[dict]) -> None:
    from app.llm.pricing import (
        PRICING_REGISTRY_VERSION,
        CallCost,
        cost_for_call,
        cost_for_request,
        cost_from_simple_usage,
    )

    per_call: list[CallCost] = []
    role_costs: dict[str, CallCost] = {}
    for call in calls:
        model = str(call.get("model", ""))
        if "uncached_input_tokens" in call:
            cost = cost_for_call(
                model=model,
                uncached_input_tokens=int(call.get("uncached_input_tokens", 0) or 0),
                cached_input_tokens=int(call.get("cached_input_tokens", 0) or 0),
                cache_write_tokens=int(call.get("cache_write_tokens", 0) or 0),
                output_tokens=int(call.get("output_tokens", 0) or 0),
                service_tier=call.get("service_tier"),
            )
        else:
            cost = cost_from_simple_usage(
                model,
                int(call.get("prompt_tokens", 0) or 0),
                int(call.get("completion_tokens", 0) or 0),
                service_tier=call.get("service_tier"),
            )
        per_call.append(cost)
        role_costs[str(call.get("role", "?"))] = cost

    request_cost = cost_for_request(per_call)
    fields = {role: cost.formatted() for role, cost in role_costs.items()}
    fields["total"] = request_cost.formatted() if request_cost else "$0.000000"
    fields["registry"] = PRICING_REGISTRY_VERSION
    trace.emit("[OpenAI cost]", fields, force=True)


def _emit_backend_timing(request_id: str, outcome: PipelineOutcome, total_ms: float) -> None:
    trace.emit(
        "[Query backend timing]",
        {
            "request_id": request_id,
            "pipeline": PIPELINE_VERSION,
            "stages_ms": outcome.stage_ms(),
            "llm_calls": outcome.llm_calls,
            "db_statements": outcome.statement_count,
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
