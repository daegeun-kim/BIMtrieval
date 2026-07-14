"""Selected-path execution + evidence combination (spec_v005 §7, §8, §9, §10).

Given a structurally-valid planner `QueryPlan` and its translated typed plans,
run ONLY the declared paths, combine their canonical ids, and produce a bounded
`EvidencePackage` plus a stable `ViewerActions`. Independent SQL/RAG work runs
concurrently (spec_v005 §8); dependent modes are sequenced. A single path
failing is represented explicitly as a partial failure — never silently treated
as "no matches" and never allowed to change the combination semantics
(spec_v005 §17).

clarify / explain_general never reach here — they need no retrieval and are
handled by the query service.
"""

from __future__ import annotations

from typing import Any, Callable

from config.settings import Settings
from shared.errors import DegradedCapabilityError
from shared.types import AnswerBasis, QueryRoute
from sqlalchemy.orm import Session
from viewer.actions import (
    SelectionAction,
    ViewerActions,
    build_await_confirmation_actions,
    build_default_viewer_actions,
    build_viewer_actions,
)

from llm.schemas import CombinationOp, ExecutionMode, QueryPlan
from llm.translate import TranslatedPlan  # noqa: F401 (type annotation only)
from query.hybrid import combination as combine
from query.hybrid.concurrency import run_parallel
from query.hybrid.evidence import fetch_context, fetch_primary, fetch_relationships
from query.hybrid.schemas import EvidencePackage, PathRun, RagInternalItem
from query.rag.hydration import hydrate_rag_result
from query.rag.search import run_rag_search
from query.graph.hydration import hydrate_traversal
from query.graph.traversal import traverse
from query.sql.dispatch import execute_catalog, execute_sql


def _rag_accepted_entities(rag_res: Any) -> tuple[list[int], dict[int, float]]:
    accepted = [c for c in rag_res.entity_candidates if c.passed_threshold]
    accepted.sort(key=lambda c: c.similarity, reverse=True)
    ids = [c.canonical_id for c in accepted]
    scores = {c.canonical_id: c.similarity for c in accepted}
    return ids, scores


def _rag_internal_items(rag_res: Any) -> list[RagInternalItem]:
    items: list[RagInternalItem] = []
    for c in rag_res.entity_candidates + rag_res.relationship_candidates:
        if c.passed_threshold:
            items.append(
                RagInternalItem(
                    source_kind=c.source_kind,
                    canonical_id=c.canonical_id,
                    similarity=round(c.similarity, 4),
                    per_kind_rank=c.per_kind_rank,
                )
            )
    return items


def orchestrate(
    *,
    plan: QueryPlan,
    translated: "TranslatedPlan",
    session: Session,
    session_factory: Callable[[], Any],
    embedding_service_getter: Callable[[], Any],
    settings: Settings,
) -> tuple[EvidencePackage, ViewerActions]:
    pkg = EvidencePackage(
        question="",  # filled by service
        route=plan.route.value,
        scope=plan.scope.value,
        source_model_id=plan.source_model_id,
    )

    if plan.route is QueryRoute.SQL:
        return _run_sql_route(plan, translated, session, pkg)
    if plan.route is QueryRoute.RAG:
        return _run_rag_route(plan, translated, session, embedding_service_getter, pkg)
    if plan.route is QueryRoute.GRAPH:
        return _run_graph_route(plan, translated, session, pkg)
    if plan.route is QueryRoute.HYBRID:
        return _run_hybrid_route(
            plan, translated, session, session_factory, embedding_service_getter, settings, pkg
        )
    raise ValueError(f"orchestrator does not handle route {plan.route}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Single-path routes
# ---------------------------------------------------------------------------


def _run_sql_route(
    plan: QueryPlan, translated: "TranslatedPlan", session: Session, pkg: EvidencePackage
) -> tuple[EvidencePackage, ViewerActions]:
    if translated.catalog_plan is not None:
        res = execute_catalog(session, translated.catalog_operation, translated.catalog_plan)
        pkg.model_candidates = res.model_candidates
        pkg.sql_facts = res.facts
        pkg.exact_totals["model_count"] = res.exact_total
        pkg.warnings.extend(res.warnings)
        pkg.answer_basis = AnswerBasis.EXACT_SQL
        pkg.path_runs.append(PathRun(name="catalog", ran=True, ok=True))
        return pkg, build_await_confirmation_actions()

    res = execute_sql(session, translated.sql_operation, translated.sql_plan)
    pkg.primary_entities = res.primary_entities
    pkg.context_entities = res.context_entities
    pkg.relationships = res.relationships
    pkg.sql_facts = res.facts
    pkg.warnings.extend(res.warnings)
    if res.exact_total is not None:
        pkg.exact_totals["sql_result"] = res.exact_total
    has_any = bool(res.primary_entities or res.context_entities or res.relationships or res.facts)
    pkg.answer_basis = AnswerBasis.EXACT_SQL if has_any else AnswerBasis.INSUFFICIENT_EVIDENCE
    pkg.path_runs.append(PathRun(name="sql", ran=True, ok=True))
    return pkg, _select_actions(pkg)


def _run_rag_route(
    plan: QueryPlan,
    translated: "TranslatedPlan",
    session: Session,
    embedding_service_getter: Callable[[], Any],
    pkg: EvidencePackage,
) -> tuple[EvidencePackage, ViewerActions]:
    try:
        emb = embedding_service_getter()
        rag_res = run_rag_search(session, emb, translated.rag_plan)
    except DegradedCapabilityError as exc:
        pkg.partial_failures.append(f"semantic retrieval unavailable: {exc}")
        pkg.warnings.append("RAG path is degraded; no semantic evidence was retrieved.")
        pkg.answer_basis = AnswerBasis.INSUFFICIENT_EVIDENCE
        pkg.path_runs.append(PathRun(name="rag", ran=True, ok=False, error=str(exc)[:200]))
        return pkg, build_default_viewer_actions()

    primary, context, rels, viewer, warnings = hydrate_rag_result(
        session, plan.source_model_id, rag_res, translated.rag_plan.expand_relationship_endpoints
    )
    pkg.primary_entities = primary
    pkg.context_entities = context
    pkg.relationships = rels
    pkg.warnings.extend(warnings)
    pkg.warnings.extend(rag_res.warnings)
    pkg.rag_internal = _rag_internal_items(rag_res)
    pkg.exact_totals["rag_accepted_entities"] = len(
        [c for c in rag_res.entity_candidates if c.passed_threshold]
    )
    pkg.answer_basis = (
        AnswerBasis.SEMANTIC_RETRIEVAL if rag_res.sufficient_evidence else AnswerBasis.INSUFFICIENT_EVIDENCE
    )
    pkg.path_runs.append(PathRun(name="rag", ran=True, ok=True))
    return pkg, viewer


def _run_graph_route(
    plan: QueryPlan, translated: "TranslatedPlan", session: Session, pkg: EvidencePackage
) -> tuple[EvidencePackage, ViewerActions]:
    result = traverse(session, translated.graph_plan)
    primary, context, viewer = hydrate_traversal(session, plan.source_model_id, result)
    pkg.primary_entities = primary
    pkg.context_entities = context
    pkg.warnings.extend(result.warnings)
    pkg.exact_totals["context_total"] = len(result.context_entity_ids)
    pkg.answer_basis = (
        AnswerBasis.GRAPH_TRAVERSAL if (primary or context) else AnswerBasis.INSUFFICIENT_EVIDENCE
    )
    pkg.path_runs.append(PathRun(name="graph", ran=True, ok=True))
    return pkg, viewer


# ---------------------------------------------------------------------------
# Hybrid route
# ---------------------------------------------------------------------------


def _run_hybrid_route(
    plan: QueryPlan,
    translated: "TranslatedPlan",
    session: Session,
    session_factory: Callable[[], Any],
    embedding_service_getter: Callable[[], Any],
    settings: Settings,
    pkg: EvidencePackage,
) -> tuple[EvidencePackage, ViewerActions]:
    combo = plan.execution.combination
    pkg.combination = combo.value
    need_sql = translated.sql_plan is not None
    need_rag = translated.rag_plan is not None

    sql_res, rag_res = _run_hybrid_paths(
        plan, translated, session_factory, embedding_service_getter, settings, pkg,
        need_sql, need_rag,
    )

    sql_ids = sql_res.entity_ids if sql_res else []
    rag_ids, rag_scores = _rag_accepted_entities(rag_res) if rag_res else ([], {})
    rag_rel_ids = (
        [c.canonical_id for c in rag_res.relationship_candidates if c.passed_threshold]
        if rag_res
        else []
    )
    if rag_res:
        pkg.rag_internal = _rag_internal_items(rag_res)
        pkg.warnings.extend(rag_res.warnings)
    if sql_res:
        pkg.sql_facts = sql_res.facts
        pkg.warnings.extend(sql_res.warnings)

    # Degraded hybrid: one path missing → return the surviving portion, clearly
    # labelled, without pretending the missing path returned no matches (§17).
    if need_sql and need_rag and (sql_res is None or rag_res is None):
        return _degraded_hybrid(plan, session, pkg, sql_res, sql_ids, rag_res, rag_ids)

    if combo is CombinationOp.RELATIONSHIP_ENDPOINT_EXPANSION:
        outcome, rel_ids = _relationship_expansion(
            session, plan, sql_ids, rag_rel_ids, rag_res
        )
    else:
        outcome = _combine_ids(combo, sql_ids, rag_ids, rag_scores)
        rel_ids = rag_rel_ids

    pkg.evidence_groups = outcome.groups
    pkg.warnings.extend(outcome.notes)
    pkg.primary_entities = fetch_primary(session, plan.source_model_id, outcome.primary_ids)
    pkg.context_entities = fetch_context(session, plan.source_model_id, outcome.context_ids)
    pkg.relationships = fetch_relationships(session, plan.source_model_id, rel_ids)
    pkg.exact_totals["primary_matches"] = len(outcome.primary_ids)
    pkg.answer_basis = (
        AnswerBasis.HYBRID_EVIDENCE
        if (pkg.primary_entities or pkg.context_entities or pkg.relationships)
        else AnswerBasis.INSUFFICIENT_EVIDENCE
    )
    return pkg, _select_actions(pkg)


def _run_hybrid_paths(
    plan, translated, session_factory, embedding_service_getter, settings, pkg, need_sql, need_rag
):
    sql_res = rag_res = None
    parallel = plan.execution.mode is ExecutionMode.PARALLEL_INDEPENDENT

    def sql_task():
        with session_factory() as s:
            return execute_sql(s, translated.sql_operation, translated.sql_plan)

    def rag_task():
        with session_factory() as s:
            emb = embedding_service_getter()
            return run_rag_search(s, emb, translated.rag_plan)

    if parallel and need_sql and need_rag:
        results = run_parallel({"sql": sql_task, "rag": rag_task}, settings.path_timeout_s)
        sql_res = _collect(results["sql"], "sql", pkg)
        rag_res = _collect(results["rag"], "rag", pkg)
    else:
        # Dependent / sequential modes: one path consumes the other's candidates,
        # so they must not run concurrently (spec_v005 §8).
        if need_sql:
            sql_res = _run_safe(sql_task, "sql", pkg)
        if need_rag:
            rag_res = _run_safe(rag_task, "rag", pkg)
    return sql_res, rag_res


def _collect(task_result, name, pkg):
    if task_result.ok:
        pkg.path_runs.append(PathRun(name=name, ran=True, ok=True))
        return task_result.value
    pkg.path_runs.append(PathRun(name=name, ran=True, ok=False, error=task_result.error))
    pkg.partial_failures.append(f"{name} path failed: {task_result.error}")
    return None


def _run_safe(fn, name, pkg):
    try:
        value = fn()
        pkg.path_runs.append(PathRun(name=name, ran=True, ok=True))
        return value
    except DegradedCapabilityError as exc:
        pkg.path_runs.append(PathRun(name=name, ran=True, ok=False, error=str(exc)[:200]))
        pkg.partial_failures.append(f"{name} path unavailable: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 - one path failing is not fatal
        pkg.path_runs.append(PathRun(name=name, ran=True, ok=False, error=str(exc)[:200]))
        pkg.partial_failures.append(f"{name} path failed: {type(exc).__name__}")
        return None


def _combine_ids(combo, sql_ids, rag_ids, rag_scores):
    if combo is CombinationOp.INTERSECTION:
        return combine.intersection(sql_ids, rag_ids)
    if combo is CombinationOp.UNION:
        return combine.union(sql_ids, rag_ids)
    if combo is CombinationOp.SQL_FILTER_OF_RAG:
        return combine.sql_filter_of_rag(sql_ids, rag_ids)
    if combo is CombinationOp.RAG_RANK_OF_SQL:
        return combine.rag_rank_of_sql(sql_ids, rag_scores)
    raise ValueError(f"unhandled combination {combo}")  # pragma: no cover


def _relationship_expansion(session, plan, sql_ids, rag_rel_ids, rag_res):
    """Accepted relationships → expand endpoints → SQL constraint (if any) promotes
    matching endpoints to primary, the rest are context (spec_v005 §9)."""
    from query.rag.relationship_expansion import expand_relationship_endpoints

    endpoint_ids: list[int] = []
    seen: set[int] = set()
    for rel_id in rag_rel_ids:
        exp = expand_relationship_endpoints(session, plan.source_model_id, rel_id)
        for row in exp.resolved_endpoints:
            if row.id not in seen:
                seen.add(row.id)
                endpoint_ids.append(row.id)

    sql_set = set(sql_ids)
    if sql_set:
        primary = [i for i in endpoint_ids if i in sql_set]
        context = [i for i in endpoint_ids if i not in sql_set]
        groups = {"endpoints": len(endpoint_ids), "promoted_primary": len(primary)}
    else:
        primary = endpoint_ids
        context = []
        groups = {"endpoints": len(endpoint_ids)}
    return combine.CombinationOutcome(primary_ids=primary, context_ids=context, groups=groups), rag_rel_ids


def _degraded_hybrid(plan, session, pkg, sql_res, sql_ids, rag_res, rag_ids):
    pkg.warnings.append(
        "hybrid answer is degraded: one retrieval path was unavailable, so this reflects "
        "only the surviving path — not a complete hybrid result."
    )
    if sql_res is not None:
        pkg.primary_entities = fetch_primary(session, plan.source_model_id, sql_ids)
        pkg.exact_totals["primary_matches"] = len(sql_ids)
        pkg.answer_basis = (
            AnswerBasis.EXACT_SQL if pkg.primary_entities else AnswerBasis.INSUFFICIENT_EVIDENCE
        )
    elif rag_res is not None:
        pkg.primary_entities = fetch_primary(session, plan.source_model_id, rag_ids)
        pkg.exact_totals["primary_matches"] = len(rag_ids)
        pkg.answer_basis = (
            AnswerBasis.SEMANTIC_RETRIEVAL if pkg.primary_entities else AnswerBasis.INSUFFICIENT_EVIDENCE
        )
    else:
        pkg.answer_basis = AnswerBasis.INSUFFICIENT_EVIDENCE
    return pkg, _select_actions(pkg)


def _select_actions(pkg: EvidencePackage) -> ViewerActions:
    primary_ids = [e.global_id for e in pkg.primary_entities]
    context_ids = [e.global_id for e in pkg.context_entities]
    if not primary_ids and not context_ids:
        return build_default_viewer_actions()
    return build_viewer_actions(
        selection_action=SelectionAction.SELECT_AND_FIT,
        primary_global_ids=primary_ids,
        context_global_ids=context_ids,
    )
