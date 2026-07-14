"""Structural plan validation (spec_v005 §6).

These checks need no database — they enforce scope/route/subplan/combination
agreement that the pydantic schema deliberately does not (so an invalid plan is
caught here and offered exactly one repair attempt, rather than raising inside
the OpenAI SDK). Database-backed checks (field existence, model existence,
operator/type compatibility) live in `llm.translate`.

`validate_plan_structure` returns a list of human-readable error strings (empty
== structurally valid). The strings are safe to feed back to the planner as the
single repair instruction (spec_v005 §6) — they contain no secrets or SQL.
"""

from __future__ import annotations

from llm.schemas import CombinationOp, ExecutionMode, QueryPlan
from shared.types import QueryRoute, QueryScope


class PlanValidationError(Exception):
    """A validated plan could not be executed. `repairable` gates the single
    planner repair attempt (spec_v005 §6)."""

    def __init__(self, message: str, *, repairable: bool = True) -> None:
        super().__init__(message)
        self.repairable = repairable


def validate_plan_structure(plan: QueryPlan) -> list[str]:
    errors: list[str] = []
    subplans = {
        "sql_plan": plan.sql_plan,
        "rag_plan": plan.rag_plan,
        "graph_plan": plan.graph_plan,
        "catalog_plan": plan.catalog_plan,
    }
    active = {k: v for k, v in subplans.items() if v is not None}

    # --- scope / active-model consistency ---
    if plan.scope is QueryScope.ACTIVE_MODEL and plan.source_model_id is None:
        errors.append("scope=active_model requires source_model_id to be set")
    if plan.scope is QueryScope.MODEL_CATALOG:
        if plan.source_model_id is not None:
            errors.append("scope=model_catalog must not set source_model_id")
        for name in ("sql_plan", "rag_plan", "graph_plan"):
            if subplans[name] is not None:
                errors.append(f"scope=model_catalog must not carry a {name}")

    # --- per-route requirements ---
    if plan.route is QueryRoute.CLARIFY:
        if not plan.needs_clarification or not plan.clarification_question:
            errors.append("route=clarify requires needs_clarification=true and a "
                          "clarification_question")
        if active:
            errors.append("route=clarify must not carry any execution subplan")
    elif plan.route is QueryRoute.EXPLAIN_GENERAL:
        if active:
            errors.append("route=explain_general must not carry any execution subplan")
    elif plan.route is QueryRoute.SQL:
        if plan.scope is QueryScope.MODEL_CATALOG:
            if plan.catalog_plan is None:
                errors.append("catalog-scope sql route requires catalog_plan")
        else:
            if plan.sql_plan is None:
                errors.append("active-model sql route requires sql_plan")
        if plan.rag_plan is not None or plan.graph_plan is not None:
            errors.append("sql route must not carry rag_plan/graph_plan")
    elif plan.route is QueryRoute.RAG:
        if plan.rag_plan is None:
            errors.append("rag route requires rag_plan")
        if plan.catalog_plan is not None:
            errors.append("rag route must not carry catalog_plan")
    elif plan.route is QueryRoute.GRAPH:
        if plan.graph_plan is None:
            errors.append("graph route requires graph_plan")
    elif plan.route is QueryRoute.HYBRID:
        n = sum(
            1 for p in (plan.sql_plan, plan.rag_plan, plan.graph_plan) if p is not None
        )
        if n < 2:
            errors.append("hybrid route requires at least two of sql_plan/rag_plan/graph_plan")
        if plan.execution.combination is CombinationOp.NONE:
            errors.append("hybrid route requires a combination other than 'none'")
        if plan.execution.mode is ExecutionMode.SINGLE:
            errors.append("hybrid route requires an execution mode other than 'single'")
        errors.extend(_validate_combination(plan))

    # --- non-hybrid execution sanity ---
    if plan.route is not QueryRoute.HYBRID:
        if plan.execution.mode is not ExecutionMode.SINGLE:
            errors.append("non-hybrid routes must use execution.mode='single'")
        if plan.execution.combination is not CombinationOp.NONE:
            errors.append("non-hybrid routes must use execution.combination='none'")

    return errors


def _validate_combination(plan: QueryPlan) -> list[str]:
    errors: list[str] = []
    combo = plan.execution.combination
    id_ops = {
        CombinationOp.INTERSECTION,
        CombinationOp.UNION,
        CombinationOp.SQL_FILTER_OF_RAG,
        CombinationOp.RAG_RANK_OF_SQL,
    }
    if combo in id_ops:
        if plan.sql_plan is None or plan.rag_plan is None:
            errors.append(f"combination={combo.value} requires both sql_plan and rag_plan")
    if combo is CombinationOp.RELATIONSHIP_ENDPOINT_EXPANSION:
        if plan.rag_plan is None and plan.graph_plan is None:
            errors.append(
                "combination=relationship_endpoint_expansion requires rag_plan or graph_plan"
            )
    return errors
