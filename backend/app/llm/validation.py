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

import hashlib

from app.config.settings import Settings, get_settings  # noqa: F401 (Settings kept for signature)
from app.llm.schemas import (
    CombinationOp,
    ExecutionMode,
    IntentOperator,
    QueryPlan,
    RetrievalPolicy,
    RetrievalPolicyPlan,
)
from app.shared.types import QueryRoute, QueryScope


class PlanValidationError(Exception):
    """A validated plan could not be executed. `repairable` gates the single
    planner repair attempt (spec_v005 §6)."""

    def __init__(self, message: str, *, repairable: bool = True) -> None:
        super().__init__(message)
        self.repairable = repairable


# ---------------------------------------------------------------------------
# Task 17 — query-only retrieval policy validation
# ---------------------------------------------------------------------------


def frozen_policy(plan: RetrievalPolicyPlan) -> RetrievalPolicy:
    """The authoritative, immutable modality policy = the union of the facets'
    per-facet needs (Task 17 §2). This is what execution honors — never a value
    derived later from semantic-resolution candidates."""
    return RetrievalPolicy(
        sql=any(f.needs_exact_structured for f in plan.facets),
        rag_entity=any(f.needs_entity_rag for f in plan.facets),
        rag_relationship=any(f.needs_relationship_rag for f in plan.facets),
        graph=any(f.needs_graph for f in plan.facets),
    )


def policy_hash(policy: RetrievalPolicy) -> str:
    bits = (policy.sql, policy.rag_entity, policy.rag_relationship, policy.graph)
    blob = "".join(str(int(b)) for b in bits)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def validate_policy_plan(plan: RetrievalPolicyPlan) -> list[str]:
    """Structural validation of the query-only policy plan (Task 17 §11).

    Enforces route/scope consistency and — for the active-model analysis route —
    that the emitted `retrieval_policy` equals the union of the facets' needs, so
    the frozen policy is unambiguous and reproducible."""
    errors: list[str] = []

    if plan.route is QueryRoute.HYBRID:
        # Conversational active-model analysis.
        if plan.scope is not QueryScope.ACTIVE_MODEL:
            errors.append("route=hybrid (active analysis) requires scope=active_model")
        if plan.source_model_id is None:
            errors.append("active-model analysis requires source_model_id")
        if not plan.facets:
            errors.append("active-model analysis requires at least one facet")
        if plan.catalog_plan is not None:
            errors.append("active-model analysis must not carry catalog_plan")
        ids = [f.facet_id for f in plan.facets]
        if len(ids) != len(set(ids)):
            errors.append("facet_id values must be unique")
        for f in plan.facets:
            if f.needs_entity_rag or f.needs_relationship_rag or f.needs_graph:
                if not f.semantic_query.strip():
                    errors.append(
                        f"facet {f.facet_id!r} needs retrieval but has empty semantic_query"
                    )
            errors.extend(_validate_intent_tree(f))
        # The declared policy must equal the authoritative union of facet needs.
        declared = plan.retrieval_policy
        union = frozen_policy(plan)
        if (
            declared.sql != union.sql
            or declared.rag_entity != union.rag_entity
            or declared.rag_relationship != union.rag_relationship
            or declared.graph != union.graph
        ):
            errors.append(
                "retrieval_policy must equal the union of facet needs "
                f"(union: sql={union.sql}, rag_entity={union.rag_entity}, "
                f"rag_relationship={union.rag_relationship}, graph={union.graph})"
            )
    elif plan.route is QueryRoute.SQL:
        # Catalog route.
        if plan.scope is not QueryScope.MODEL_CATALOG:
            errors.append("route=sql at policy stage is the catalog route; requires model_catalog")
        if plan.catalog_plan is None:
            errors.append("catalog route requires catalog_plan")
        if plan.facets:
            errors.append("catalog route must not carry facets")
    elif plan.route is QueryRoute.EXPLAIN_GENERAL:
        if plan.facets or plan.catalog_plan is not None:
            errors.append("explain_general must not carry facets/catalog_plan")
    elif plan.route is QueryRoute.CLARIFY:
        if not plan.needs_clarification or not plan.clarification_question:
            errors.append("clarify requires needs_clarification=true and a clarification_question")
        if plan.facets:
            errors.append("clarify must not carry facets")
    else:
        errors.append(f"policy route {plan.route.value!r} is not supported at Stage 2")

    return errors


#: Conceptual operators that carry no value of their own.
_VALUELESS_OPERATORS = {IntentOperator.IS_MISSING, IntentOperator.IS_PRESENT}
#: Conceptual operators that need a list rather than a single value.
_LIST_OPERATORS = {IntentOperator.ONE_OF, IntentOperator.BETWEEN}
#: Matches the typed SQL `FilterGroup` bound, so a planner tree can never encode
#: Boolean logic the compiler would have to reject later (spec_v003 §6).
MAX_INTENT_DEPTH = 3


def _validate_intent_tree(facet) -> list[str]:
    """Structural validation of ONE facet's conceptual intent tree (Task 23 §1).

    Enforces that conditions are well-formed, uniquely identified, correctly
    grouped, and bounded — so a condition can never be half-expressed and then
    silently discarded during resolution."""
    errors: list[str] = []
    fid = facet.facet_id

    group_ids = [g.group_id for g in facet.condition_groups]
    if len(group_ids) != len(set(group_ids)):
        errors.append(f"facet {fid!r}: condition_groups must have unique group_id values")
    known_groups = set(group_ids)

    condition_ids = [c.condition_id for c in facet.conditions]
    if len(condition_ids) != len(set(condition_ids)):
        errors.append(f"facet {fid!r}: conditions must have unique condition_id values")

    for g in facet.condition_groups:
        if g.parent_group_id and g.parent_group_id not in known_groups:
            errors.append(
                f"facet {fid!r}: group {g.group_id!r} references unknown "
                f"parent_group_id {g.parent_group_id!r}"
            )
        if g.parent_group_id == g.group_id:
            errors.append(f"facet {fid!r}: group {g.group_id!r} is its own parent")

    # Cycle + depth check over the group forest.
    parent_of = {g.group_id: g.parent_group_id for g in facet.condition_groups}
    for gid in group_ids:
        seen: set[str] = set()
        cur: str | None = gid
        depth = 0
        while cur:
            if cur in seen:
                errors.append(f"facet {fid!r}: condition_groups contain a cycle at {cur!r}")
                break
            seen.add(cur)
            cur = parent_of.get(cur)
            depth += 1
        if depth > MAX_INTENT_DEPTH:
            errors.append(
                f"facet {fid!r}: group {gid!r} nests deeper than {MAX_INTENT_DEPTH} levels"
            )

    for c in facet.conditions:
        if c.parent_group_id and c.parent_group_id not in known_groups:
            errors.append(
                f"facet {fid!r}: condition {c.condition_id!r} references unknown "
                f"parent_group_id {c.parent_group_id!r}"
            )
        if not c.concept.strip():
            errors.append(f"facet {fid!r}: condition {c.condition_id!r} has an empty concept")
        has_value = bool((c.value_concept or "").strip()) or bool(c.value_list)
        if c.operator in _VALUELESS_OPERATORS:
            if has_value:
                errors.append(
                    f"facet {fid!r}: condition {c.condition_id!r} uses "
                    f"{c.operator.value} and must not carry a value"
                )
        elif not has_value:
            errors.append(
                f"facet {fid!r}: condition {c.condition_id!r} uses {c.operator.value} "
                "but carries no value_concept/value_list"
            )
        if c.operator is IntentOperator.BETWEEN and len(c.value_list) != 2:
            errors.append(
                f"facet {fid!r}: condition {c.condition_id!r} uses between and "
                "requires exactly 2 value_list entries"
            )
        if c.operator is IntentOperator.ONE_OF and not c.value_list:
            errors.append(
                f"facet {fid!r}: condition {c.condition_id!r} uses one_of and requires value_list"
            )

    # A facet that carries conditions is by definition a filtered request, so it
    # must ask for the structured retrieval that can actually apply them.
    if facet.conditions and not facet.needs_exact_structured:
        errors.append(
            f"facet {fid!r} carries conditions but did not request exact structured "
            "retrieval; a filtered request cannot be answered without it"
        )
    return errors


def validate_plan_structure(plan: QueryPlan, settings: Settings | None = None) -> list[str]:
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
            errors.append(
                "route=clarify requires needs_clarification=true and a clarification_question"
            )
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
        n = sum(1 for p in (plan.sql_plan, plan.rag_plan, plan.graph_plan) if p is not None)
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
