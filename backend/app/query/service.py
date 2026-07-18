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
from app.config import trace
from app.config.logging import write_jsonl_event
from app.config.settings import Settings, get_settings
from app.db.session import session_scope
from app.llm.answerer import answer_from_evidence, answer_general
from app.llm.client import LLMError, LLMUnavailableError, OpenAIQueryClient, get_llm_client
from app.llm.context import build_policy_context
from app.llm.prompts import (
    ANSWERER_PROMPT_VERSION,
    GROUP_ANSWERER_PROMPT_VERSION,
    PLANNER_PROMPT_VERSION,
    POLICY_PLANNER_PROMPT_VERSION,
)
from app.llm.schemas import CatalogPlan, QueryPlan, RetrievalPolicyPlan
from app.llm.translate import TranslatedPlan, translate_plan
from app.llm.validation import (
    PlanValidationError,
    frozen_policy,
    policy_hash,
    validate_plan_structure,
    validate_policy_plan,
)
from app.query.hybrid.evidence import (
    apply_bounds,
    build_group_answer_payload,
    build_result_summary,
    build_sample_detail,
)
from app.query.hybrid.groups.allocation import allocate_examples
from app.query.hybrid.groups.builder import build_groups
from app.query.hybrid.groups.decision import resolve_group_answer
from app.query.hybrid.groups.viewer import hydrate_accepted_viewer_identities
from app.query.hybrid.orchestrator import orchestrate
from app.query.hybrid.schemas import EvidencePackage
from app.query.rag.embedding_service import get_embedding_service
from app.query.selection import SelectionConflictError, resolve_selection
from app.query.semantic.resolution import resolve_facets
from app.query.session import SessionState, get_session_store
from app.query.sql import catalog as catalog_ops
from app.query.sql.schemas import GetModelMetadataPlan, SqlOperation
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
        # Per-question OpenAI usage (task15 §1): snapshot the client's call log
        # so only the calls made for THIS question are summed, whether the
        # question succeeds, degrades, or fails after a completed planner call.
        usage_start = len(client.log.calls) if hasattr(client, "log") else None

        try:
            return self._answer_question(request, request_id, scope, client, state, t0)
        finally:
            if usage_start is not None:
                _emit_question_usage(client.log.calls[usage_start:])

    def _answer_question(
        self,
        request: SessionQueryRequest,
        request_id: str,
        scope: QueryScope,
        client: OpenAIQueryClient,
        state: SessionState,
        t0: float,
    ) -> QueryResponseEnvelope:
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

                # Task 17 Stage 2: query-ONLY retrieval policy (LLM call 1). The
                # context carries no active-model candidates/schema, so the
                # SQL/RAG/graph decision cannot depend on model contents.
                policy_context = build_policy_context(session, req, state, self.settings)
                policy_plan, repaired, policy_errors = self._plan_policy(client, policy_context)
                planner_ms = round((time.perf_counter() - t0) * 1000.0, 1)

                if policy_plan is None:
                    return _with_warnings(
                        self._clarify_after_repair(req, request_id, scope, policy_errors, t0),
                        selection.warnings,
                    )

                if (
                    policy_plan.route is QueryRoute.HYBRID
                    and req.active_source_model_id is not None
                    and policy_plan.facets
                ):
                    envelope = self._execute_groups_and_answer(
                        req,
                        request_id,
                        session,
                        policy_plan,
                        client,
                        state,
                        t0,
                        repaired,
                        planner_ms,
                    )
                else:
                    envelope = self._answer_non_analysis(
                        req,
                        request_id,
                        scope,
                        session,
                        policy_plan,
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

        # retrieval routes (legacy single-path; used for the catalog route)
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
        # Explicit sample-detail intent only: pick ONE deterministic matching
        # entity and attach its bounded details from the database (task13 §3).
        # Must run before apply_bounds so the choice is made over the full result
        # set, and before the answer call so the model cannot invent a sample.
        if plan.sample_detail_requested and plan.source_model_id and pkg.primary_entities:
            pkg.sample_detail = build_sample_detail(
                session, plan.source_model_id, pkg.primary_entities[0].global_id
            )
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

    # -- Task 17 query-only policy + group pipeline --------------------------

    def _plan_policy(
        self, client: OpenAIQueryClient, context: dict[str, Any]
    ) -> tuple[RetrievalPolicyPlan | None, bool, list[str]]:
        """LLM call 1 + at most one repair (Task 17 Stage 2). The context is
        query-only, so the returned policy cannot depend on model contents."""
        result = client.plan_retrieval_policy(context)
        plan = result.plan
        errors = validate_policy_plan(plan)
        if not errors:
            return plan, False, []
        repair_context = dict(context)
        repair_context["repair_instruction"] = {
            "your_previous_plan_was_invalid": errors,
            "instruction": "Return one corrected plan that fixes exactly these problems.",
        }
        result2 = client.plan_retrieval_policy(repair_context)
        plan2 = result2.plan
        errors2 = validate_policy_plan(plan2)
        if not errors2:
            return plan2, True, []
        return None, True, errors2

    def _execute_groups_and_answer(
        self,
        request: SessionQueryRequest,
        request_id: str,
        session: Any,
        policy_plan: RetrievalPolicyPlan,
        client: OpenAIQueryClient,
        state: SessionState,
        t0: float,
        repaired: bool,
        planner_ms: float,
    ) -> QueryResponseEnvelope:
        """Task 17 Stages 3-9: resolve facets under the FROZEN policy, build
        evidence groups, allocate examples, let the answerer judge groups, then
        hydrate complete viewer identities for accepted groups."""
        sid = policy_plan.source_model_id
        policy = frozen_policy(policy_plan)  # immutable; resolution cannot change it
        t_retrieval = time.perf_counter()
        try:
            facet_resolutions = resolve_facets(
                session,
                policy_plan.facets,
                sid,
                embedding_service_getter=get_embedding_service,
                settings=self.settings,
            )
            groups = build_groups(
                session,
                facet_resolutions,
                policy,
                sid,
                settings=self.settings,
                embedding_service_getter=get_embedding_service,
                selection_entity_ids=request.selected_entity_ids,
            )
        except (BimRagError, SQLAlchemyError) as exc:
            self._log_failure(request, request_id, "group_execution_error", str(exc))
            return _error_envelope(
                request,
                "I couldn't complete that analysis against the model. Could you rephrase it?",
                request_id=request_id,
                scope=QueryScope.ACTIVE_MODEL,
            )
        retrieval_ms = round((time.perf_counter() - t_retrieval) * 1000.0, 1)

        # Build the bounded group descriptions submitted to the final LLM as a
        # separately timed stage.
        t_summary = time.perf_counter()
        alloc_meta = allocate_examples(
            groups, self.settings.max_answer_examples, self.settings.small_group_full_threshold
        )
        trace.emit(
            "[trace] policy",
            {
                "route": policy_plan.route.value,
                "policy_hash": policy_hash(policy),
                "sql": policy.sql,
                "rag_entity": policy.rag_entity,
                "rag_relationship": policy.rag_relationship,
                "graph": policy.graph,
            },
        )
        trace.emit("[trace] groups", _group_trace(groups))
        payload = build_group_answer_payload(
            request.question, policy_plan.analysis_intent, sid, groups, self.settings
        )
        group_summary_ms = round((time.perf_counter() - t_summary) * 1000.0, 1)

        # OpenAI call 2 — group-level relevance judgment + answer.
        t_ans = time.perf_counter()
        ans = client.generate_group_answer(payload)
        answer_ms = round((time.perf_counter() - t_ans) * 1000.0, 1)

        t_viewer = time.perf_counter()
        decision = resolve_group_answer(groups, ans.output)
        hydration = hydrate_accepted_viewer_identities(session, decision, sid)
        viewer_hydration_ms = round((time.perf_counter() - t_viewer) * 1000.0, 1)

        # Build the response package from accepted groups only (§9, §10).
        plan = QueryPlan(
            scope=QueryScope.ACTIVE_MODEL, route=QueryRoute.HYBRID, source_model_id=sid
        )
        pkg = EvidencePackage(
            question=request.question,
            route="hybrid",
            scope="active_model",
            source_model_id=sid,
            answer_basis=decision.answer_basis,
        )
        pkg.primary_entities = _accepted_examples(decision, self.settings)
        pkg.viewer_global_ids = hydration.primary_global_ids
        pkg.viewer_matches_total = hydration.viewer_matches_total
        pkg.viewer_matches_truncated = False  # complete hydration (§9)
        pkg.class_histogram = _accepted_class_histogram(decision)
        pkg.warnings = (list(decision.warnings) + list(hydration.warnings))[:20]
        # Ambiguous concept totals are forbidden: only set an exact total when a
        # single exact primary group is accepted (§10).
        if (
            len(decision.accepted_primary) == 1
            and decision.accepted_primary[0].exact_count is not None
        ):
            pkg.exact_totals["sql_result"] = decision.accepted_primary[0].exact_count
        if ans.output.disclosed_conflicts:
            pkg.conflicts.append("model reported a conflict in the evidence")

        stages = {
            "modality_policy_ms": planner_ms,
            "sql_rag_graph_and_grouping_ms": retrieval_ms,
            "group_summary_to_llm_ms": group_summary_ms,
            "final_llm_response_ms": answer_ms,
            "viewer_identity_hydration_ms": viewer_hydration_ms,
        }
        self._finalize_group_state(state, sid, decision, hydration)
        self._log_group_event(
            request,
            request_id,
            policy_plan,
            policy,
            groups,
            decision,
            hydration,
            alloc_meta,
            pkg,
            client,
            t0,
            ans.output.used_general_knowledge,
            stages,
            repaired,
        )
        return _from_package(
            request, request_id, plan, pkg, ans.output.answer, hydration.viewer_actions()
        )

    def _answer_non_analysis(
        self,
        request: SessionQueryRequest,
        request_id: str,
        scope: QueryScope,
        session: Any,
        policy_plan: RetrievalPolicyPlan,
        client: OpenAIQueryClient,
        state: SessionState,
        t0: float,
        repaired: bool,
        planner_ms: float,
    ) -> QueryResponseEnvelope:
        """Preserved routes (Task 17 §2): catalog / explain_general / clarify.
        These reuse the legacy single-path execution via a compact QueryPlan."""
        legacy = self._policy_to_legacy_plan(policy_plan)
        try:
            translated = translate_plan(session, legacy, request.selected_entity_ids)
        except PlanValidationError as exc:
            return self._clarify_after_repair(request, request_id, scope, [str(exc)], t0)
        return self._execute_and_answer(
            request,
            request_id,
            session,
            legacy,
            translated,
            client,
            state,
            t0,
            repaired,
            planner_ms,
        )

    def _policy_to_legacy_plan(self, policy_plan: RetrievalPolicyPlan) -> QueryPlan:
        if policy_plan.route is QueryRoute.SQL:  # catalog
            return QueryPlan(
                scope=QueryScope.MODEL_CATALOG,
                route=QueryRoute.SQL,
                catalog_plan=policy_plan.catalog_plan
                or CatalogPlan(operation=SqlOperation.LIST_MODELS),
            )
        if policy_plan.route is QueryRoute.CLARIFY:
            return QueryPlan(
                scope=policy_plan.scope,
                route=QueryRoute.CLARIFY,
                source_model_id=policy_plan.source_model_id,
                needs_clarification=True,
                clarification_question=policy_plan.clarification_question
                or "Could you clarify your question?",
            )
        return QueryPlan(
            scope=policy_plan.scope,
            route=QueryRoute.EXPLAIN_GENERAL,
            source_model_id=policy_plan.source_model_id,
        )

    def _finalize_group_state(
        self, state: SessionState, sid: int | None, decision: Any, hydration: Any
    ) -> None:
        """Store ONLY accepted-group evidence in follow-up state (Task 17 §8)."""
        state.mode = QueryScope.ACTIVE_MODEL
        state.active_source_model_id = sid
        state.last_route = "hybrid"
        state.last_primary_entity_ids = hydration.accepted_primary_entity_ids[:200]
        state.last_context_entity_ids = []
        state.last_relationship_ids = []
        state.pending_candidate_model_ids = []
        self.store.save(state)

    def _clarify_after_repair(
        self,
        request: SessionQueryRequest,
        request_id: str,
        scope: QueryScope,
        errors: list[str],
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

    def _log_group_event(
        self,
        request: SessionQueryRequest,
        request_id: str,
        policy_plan: RetrievalPolicyPlan,
        policy: Any,
        groups: list,
        decision: Any,
        hydration: Any,
        alloc_meta: dict,
        pkg: EvidencePackage,
        client: OpenAIQueryClient,
        t0: float,
        used_general_knowledge: bool,
        stages: dict,
        repaired: bool,
    ) -> None:
        """Bounded diagnostic record for the group pipeline (Task 17 §14). No
        prompts/vectors/canonical JSON/SQL params/full GlobalId lists."""
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        record = {
            "event": "query",
            "pipeline": "task17_groups",
            "request_id": request_id,
            "session_id": request.session_id,
            "active_source_model_id": request.active_source_model_id,
            "question": request.question,
            "planner_model": self.settings.get_planner_model(),
            "answer_model": self.settings.get_answer_model(),
            "policy_planner_prompt_version": POLICY_PLANNER_PROMPT_VERSION,
            "group_answerer_prompt_version": GROUP_ANSWERER_PROMPT_VERSION,
            "route": policy_plan.route.value,
            "retrieval_policy": {
                "sql": policy.sql,
                "rag_entity": policy.rag_entity,
                "rag_relationship": policy.rag_relationship,
                "graph": policy.graph,
            },
            "policy_hash": policy_hash(policy),
            "facets": [
                {"facet_id": f.facet_id, "role_hint": f.role_hint.value} for f in policy_plan.facets
            ],
            "groups": [
                {
                    "group_id": g.group_id,
                    "authority": g.authority,
                    "coverage": g.coverage,
                    "exact_count": g.exact_count,
                    "rag_candidate_count": g.rag_candidate_count,
                    "examples": len(g.allocated_examples),
                    "source_kinds": g.source_kinds,
                }
                for g in groups
            ],
            "allocation": alloc_meta,
            "decision": {
                "primary": [g.group_id for g in decision.accepted_primary],
                "supporting": [g.group_id for g in decision.accepted_supporting],
                "context": [g.group_id for g in decision.accepted_context],
                "rejected": decision.rejected_ids,
                "viewer_primary": [g.group_id for g in decision.viewer_primary],
            },
            "answer_basis": pkg.answer_basis.value,
            "viewer_accepted_total": hydration.viewer_matches_total,
            "viewer_returned_total": len(hydration.primary_global_ids)
            + len(hydration.context_global_ids),
            "missing_identity_count": hydration.missing_identity_count,
            "general_knowledge_used": used_general_knowledge,
            "repaired": repaired,
            "warnings": pkg.warnings,
            "token_usage": client.log.calls,
            "latency_ms": latency_ms,
            "stage_latency_ms": stages,
        }
        write_jsonl_event(record, Path(self.settings.query_log_path))
        _emit_backend_timing(request_id, stages, latency_ms)

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
        _emit_backend_timing(request_id, stages or {}, latency_ms)

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


def _accepted_examples(decision: Any, settings: Settings) -> list:
    """Grounding entities from accepted groups' allocated examples (Task 17 §7),
    deduped by entity id and bounded to the answer-evidence limit."""
    seen: set[int] = set()
    out: list = []
    for g in decision.accepted():
        for e in g.allocated_examples:
            if e.entity_id not in seen:
                seen.add(e.entity_id)
                out.append(e)
                if len(out) >= settings.max_primary_entities:
                    return out
    return out


def _accepted_class_histogram(decision: Any) -> dict[str, int]:
    """Exact per-class counts of accepted PRIMARY groups (never summed into a
    single concept total)."""
    hist: dict[str, int] = {}
    for g in decision.accepted_primary:
        if len(g.predicate.ifc_classes) == 1 and g.exact_count is not None:
            cls = g.predicate.ifc_classes[0]
            hist[cls] = hist.get(cls, 0) + g.exact_count
    return hist


def _group_trace(groups: list) -> dict:
    """Concise bounded group trace (no full profiles/predicates/ids lists)."""
    return {
        "groups": [
            {
                "group_id": g.group_id,
                "authority": g.authority,
                "coverage": g.coverage,
                "exact_count": g.exact_count,
                "rag_candidates": g.rag_candidate_count,
                "examples": len(g.allocated_examples),
            }
            for g in groups[:24]
        ]
    }


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


def _emit_question_usage(calls: list[dict]) -> None:
    """Print one per-question OpenAI usage block (task15 §1).

    `calls` are the client-log entries added during this question only — each
    carries the usage the OpenAI API itself reported (planner, repair, and
    answerer alike), so the sums are actuals, never estimates. A question that
    made no OpenAI call (or none that reported usage) prints nothing rather
    than a misleading zero block; a question that failed after a completed
    planner call prints only what was actually reported.
    """
    if not calls:
        return
    trace.emit_openai_usage(
        prompt_tokens=sum(int(c.get("prompt_tokens", 0) or 0) for c in calls),
        completion_tokens=sum(int(c.get("completion_tokens", 0) or 0) for c in calls),
        total_tokens=sum(int(c.get("total_tokens", 0) or 0) for c in calls),
    )


def _emit_backend_timing(request_id: str, stages: dict, total_ms: float) -> None:
    """Always print bounded backend stage timing for one completed query."""
    trace.emit(
        "[Query backend timing]",
        {
            "request_id": request_id,
            "stages_ms": stages,
            "backend_total_ms": total_ms,
        },
        force=True,
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
        result_summary=build_result_summary(pkg),
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
