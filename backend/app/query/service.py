"""Top-level query service — the only entry point the HTTP layer calls
(spec_v005 §15).

Implements the full pipeline for one natural-language question:

    session/context validation
    → schema-context selection
    → planner call (OpenAI call 1)
    → validate + at most one repair            (spec_v005 §6)
    → execute only the selected paths          (spec_v005 §7, §8)
    → combine bounded evidence                 (spec_v005 §9, §10)
    → grounded answer call (OpenAI call 2)      (spec_v005 §11)
    → viewer-action construction               (spec_v005 §14)
    → safe JSONL logging                        (spec_v005 §16)
    → stable response serialization            (spec_v005 §15)

There is NO separate route-classification call — the single planner call both
routes and produces complete subplans (spec_v005 §2). SQL/RAG do not run for
every question; only declared paths execute.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas.request import SessionQueryRequest
from app.api.schemas.response import EvidenceSummary, QueryResponseEnvelope
from app.config.logging import write_jsonl_event
from app.config.settings import Settings, get_settings
from app.db.session import session_scope
from app.llm.answerer import answer_from_evidence, answer_general
from app.llm.client import LLMError, LLMUnavailableError, OpenAIQueryClient, get_llm_client
from app.llm.context import build_planner_context
from app.llm.prompts import ANSWERER_PROMPT_VERSION, PLANNER_PROMPT_VERSION
from app.llm.schemas import QueryPlan
from app.llm.translate import TranslatedPlan, translate_plan
from app.llm.validation import PlanValidationError, validate_plan_structure
from app.query.hybrid.evidence import apply_bounds
from app.query.hybrid.orchestrator import orchestrate
from app.query.hybrid.schemas import EvidencePackage
from app.query.rag.embedding_service import get_embedding_service
from app.query.selection import SelectionConflictError, resolve_selection
from app.query.session import SessionState, get_session_store
from app.query.sql import catalog as catalog_ops
from app.query.sql.schemas import GetModelMetadataPlan
from app.shared.errors import BimRagError, ModelNotFoundError
from app.shared.types import AnswerBasis, QueryRoute, QueryScope, ResponseStatus
from app.viewer.actions import (
    ViewerActions,
    build_default_viewer_actions,
    build_load_model_actions,
)
from app.viewer.assets import viewer_asset_ref


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
        return self._llm_client or get_llm_client(self.settings)

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
        # Browser-safe asset reference, never the DB filesystem path (Task 10 §3).
        viewer_source = viewer_asset_ref(model_id)

        # Catalog-to-model transition (spec_v005 §13): set active model, reset prior
        # model-specific result context, instruct the frontend to load the source.
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

        # Reject selected GlobalIds with no active model before any LLM/DB work
        # (spec_v006 §10.4). Guard runs before the LLM client is constructed so
        # this path makes zero OpenAI calls.
        if request.selected_global_ids and request.active_source_model_id is None:
            return _error_envelope(
                request,
                "Selected objects require an active model. Load a model before selecting objects.",
                request_id=request_id,
                scope=scope,
            )

        client = self._client()

        try:
            with session_scope() as session:
                # Trusted resolution of the browser selection to canonical entity
                # IDs before planner context / selected-object retrieval.
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
                req = request.model_copy(update={"selected_entity_ids": selection.entity_ids})

                context = build_planner_context(session, req, state, self.settings)
                plan, translated, repaired, final_errors = self._plan_and_translate(
                    client, context, session, req.selected_entity_ids
                )
                planner_ms = round((time.perf_counter() - t0) * 1000.0, 1)

                if translated is None:
                    return _with_warnings(
                        self._clarify_after_repair(
                            req, request_id, scope, plan, final_errors, client, t0
                        ),
                        selection.warnings,
                    )

                envelope = self._execute_and_answer(
                    req,
                    request_id,
                    session,
                    plan,
                    translated,
                    client,
                    state,
                    t0,
                    repaired,
                    planner_ms,
                )
                return _with_warnings(envelope, selection.warnings)
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

    def _plan_and_translate(
        self,
        client: OpenAIQueryClient,
        context: dict[str, Any],
        session: Any,
        selected_ids: list[int],
    ) -> tuple[QueryPlan, TranslatedPlan | None, bool, list[str]]:
        """Planner call + at most one repair (spec_v005 §6)."""
        result = client.plan_query(context)
        plan = result.plan
        errors = validate_plan_structure(plan)
        if not errors:
            try:
                return plan, translate_plan(session, plan, selected_ids), False, []
            except PlanValidationError as exc:
                errors = [str(exc)]

        # exactly one repair attempt
        repair_context = dict(context)
        repair_context["repair_instruction"] = {
            "your_previous_plan_was_invalid": errors,
            "instruction": "Return one corrected plan that fixes exactly these problems. "
            "Do not repeat the same mistakes.",
        }
        result2 = client.plan_query(repair_context)
        plan2 = result2.plan
        errors2 = validate_plan_structure(plan2)
        if not errors2:
            try:
                return plan2, translate_plan(session, plan2, selected_ids), True, []
            except PlanValidationError as exc:
                errors2 = [str(exc)]
        return plan2, None, True, errors2

    def _execute_and_answer(
        self,
        request: SessionQueryRequest,
        request_id: str,
        session: Any,
        plan: QueryPlan,
        translated: TranslatedPlan,
        client: OpenAIQueryClient,
        state: SessionState,
        t0: float,
        repaired: bool,
        planner_ms: float,
    ) -> QueryResponseEnvelope:
        # clarify / explain_general need no retrieval (spec_v005 §7)
        if plan.route is QueryRoute.CLARIFY:
            answer = plan.clarification_question or "Could you clarify your question?"
            pkg = EvidencePackage(
                question=request.question,
                route=plan.route.value,
                scope=plan.scope.value,
                source_model_id=plan.source_model_id,
                answer_basis=AnswerBasis.INSUFFICIENT_EVIDENCE,
            )
            viewer = build_default_viewer_actions()
            stages = {"planner_ms": planner_ms, "execute_ms": 0.0, "answer_ms": 0.0}
            self._finalize_state(state, plan, pkg)
            self._log_event(request, request_id, plan, pkg, client, t0, repaired, False, stages)
            return _from_package(request, request_id, plan, pkg, answer, viewer)

        if plan.route is QueryRoute.EXPLAIN_GENERAL:
            t_ans = time.perf_counter()
            ans = answer_general(client, request.question)
            pkg = EvidencePackage(
                question=request.question,
                route=plan.route.value,
                scope=plan.scope.value,
                source_model_id=plan.source_model_id,
                answer_basis=AnswerBasis.GENERAL_KNOWLEDGE,
            )
            viewer = build_default_viewer_actions()
            stages = {
                "planner_ms": planner_ms,
                "execute_ms": 0.0,
                "answer_ms": round((time.perf_counter() - t_ans) * 1000.0, 1),
            }
            self._finalize_state(state, plan, pkg)
            self._log_event(request, request_id, plan, pkg, client, t0, repaired, True, stages)
            return _from_package(request, request_id, plan, pkg, ans.output.answer, viewer)

        # retrieval routes
        t_exec = time.perf_counter()
        try:
            pkg, viewer = orchestrate(
                plan=plan,
                translated=translated,
                session=session,
                session_factory=session_scope,
                embedding_service_getter=get_embedding_service,
                settings=self.settings,
            )
        except (BimRagError, SQLAlchemyError) as exc:
            # A validated plan can still hit an execution-time defect (unknown
            # field/operator not caught in translation, SQL timeout, etc.). Never
            # surface a raw 500 — degrade to a safe clarification (spec_v005 §17).
            self._log_failure(request, request_id, "execution_error", str(exc))
            return _error_envelope(
                request,
                "I couldn't complete that query against the model. Could you rephrase it "
                "or narrow it down?",
                request_id=request_id,
                scope=plan.scope,
            )
        pkg.question = request.question
        apply_bounds(pkg, self.settings)
        execute_ms = round((time.perf_counter() - t_exec) * 1000.0, 1)

        # OpenAI call 2 — grounded answer from bounded evidence
        t_ans = time.perf_counter()
        ans = answer_from_evidence(client, pkg)
        answer_ms = round((time.perf_counter() - t_ans) * 1000.0, 1)
        if ans.output.disclosed_conflicts and not pkg.conflicts:
            pkg.conflicts.append("model reported a conflict in the evidence")

        stages = {"planner_ms": planner_ms, "execute_ms": execute_ms, "answer_ms": answer_ms}
        # catalog scope keeps its await-confirmation viewer action
        self._finalize_state(state, plan, pkg)
        self._log_event(
            request,
            request_id,
            plan,
            pkg,
            client,
            t0,
            repaired,
            ans.output.used_general_knowledge,
            stages,
        )
        return _from_package(request, request_id, plan, pkg, ans.output.answer, viewer)

    def _clarify_after_repair(
        self,
        request: SessionQueryRequest,
        request_id: str,
        scope: QueryScope,
        plan: QueryPlan,
        errors: list[str],
        client: OpenAIQueryClient,
        t0: float,
    ) -> QueryResponseEnvelope:
        self._log_failure(request, request_id, "plan_invalid_after_repair", "; ".join(errors))
        answer = (
            "I couldn't build a reliable plan for that question, even after one retry. "
            "Could you rephrase it or be more specific about the model, field, or metric?"
        )
        return _envelope(
            request,
            scope=scope,
            route=QueryRoute.CLARIFY,
            basis=AnswerBasis.INSUFFICIENT_EVIDENCE,
            answer=answer,
            active_source_model_id=request.active_source_model_id,
            viewer_actions=build_default_viewer_actions(),
            request_id=request_id,
            warnings=["planner produced an invalid plan twice; returned a clarification"],
        )

    # -- state + logging -----------------------------------------------------

    def _finalize_state(self, state: SessionState, plan: QueryPlan, pkg: EvidencePackage) -> None:
        state.mode = plan.scope
        state.active_source_model_id = plan.source_model_id
        state.last_route = plan.route.value
        state.last_primary_entity_ids = [e.entity_id for e in pkg.primary_entities]
        state.last_context_entity_ids = [e.entity_id for e in pkg.context_entities]
        state.last_relationship_ids = [r.relationship_id for r in pkg.relationships]
        state.pending_candidate_model_ids = [c.source_model_id for c in pkg.model_candidates]
        self.store.save(state)

    def _log_event(
        self,
        request: SessionQueryRequest,
        request_id: str,
        plan: QueryPlan,
        pkg: EvidencePackage,
        client: OpenAIQueryClient,
        t0: float,
        repaired: bool,
        used_general_knowledge: bool,
        stages: dict | None = None,
    ) -> None:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        record = {
            "event": "query",
            "request_id": request_id,
            "session_id": request.session_id,
            "active_source_model_id": request.active_source_model_id,
            "question": request.question,
            "planner_model": self.settings.get_planner_model(),
            "answer_model": self.settings.get_answer_model(),
            "planner_prompt_version": PLANNER_PROMPT_VERSION,
            "answer_prompt_version": ANSWERER_PROMPT_VERSION,
            "route": plan.route.value,
            "scope": plan.scope.value,
            "combination": pkg.combination,
            "validated_plan": plan.model_dump(mode="json"),
            "repaired": repaired,
            "primary_entity_ids": [e.entity_id for e in pkg.primary_entities],
            "context_entity_ids": [e.entity_id for e in pkg.context_entities],
            "relationship_ids": [r.relationship_id for r in pkg.relationships],
            "rag_ranks": [
                {"kind": i.source_kind, "id": i.canonical_id, "rank": i.per_kind_rank}
                for i in pkg.rag_internal
            ],
            "exact_totals": pkg.exact_totals,
            "evidence_groups": pkg.evidence_groups,
            "answer_basis": pkg.answer_basis.value,
            "general_knowledge_used": used_general_knowledge,
            "warnings": pkg.warnings,
            "partial_failures": pkg.partial_failures,
            "path_runs": [{"name": p.name, "ok": p.ok, "error": p.error} for p in pkg.path_runs],
            "token_usage": client.log.calls,
            "latency_ms": latency_ms,
            "stage_latency_ms": stages or {},
        }
        write_jsonl_event(record, Path(self.settings.query_log_path))

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


def _with_warnings(envelope: QueryResponseEnvelope, extra: list[str]) -> QueryResponseEnvelope:
    """Append bounded selection-resolution warnings to a built envelope."""
    if extra:
        envelope.warnings = list(envelope.warnings) + list(extra)
        envelope.warnings = envelope.warnings[:20]
    return envelope


def _evidence_summary(pkg: EvidencePackage) -> EvidenceSummary:
    notes = list(pkg.overflow_summaries) + list(pkg.missing_coverage) + list(pkg.partial_failures)
    sql_match = pkg.exact_totals.get("sql_result")
    if sql_match is None:
        sql_match = pkg.exact_totals.get("primary_matches")
    if sql_match is None and pkg.sql_facts and "count" in pkg.sql_facts:
        sql_match = pkg.sql_facts["count"]
    return EvidenceSummary(
        basis=pkg.answer_basis,
        sql_match_count=sql_match,
        rag_candidate_count=len(pkg.rag_internal) or None,
        relationship_count=len(pkg.relationships) or None,
        notes=notes[:20],
    )


def _from_package(
    request: SessionQueryRequest,
    request_id: str,
    plan: QueryPlan,
    pkg: EvidencePackage,
    answer: str,
    viewer: ViewerActions,
) -> QueryResponseEnvelope:
    return QueryResponseEnvelope(
        request_id=request_id,
        session_id=request.session_id,
        status=ResponseStatus.SUCCESS,
        scope=plan.scope,
        route=plan.route,
        answer_basis=pkg.answer_basis,
        answer=answer,
        active_source_model_id=plan.source_model_id,
        model_candidates=pkg.model_candidates,
        primary_entities=pkg.primary_entities,
        context_entities=pkg.context_entities,
        relationships=pkg.relationships,
        viewer_actions=viewer,
        evidence_summary=_evidence_summary(pkg),
        warnings=list(pkg.warnings)[:20],
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
