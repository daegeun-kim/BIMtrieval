"""Structural plan validation across all routes / dependency modes (spec_v005 §6)."""

from __future__ import annotations

from llm.schemas import (
    CatalogPlan,
    CombinationOp,
    ExecutionMode,
    GraphPlan,
    PlanExecution,
    QueryPlan,
    RagPlan,
    SqlPlan,
)
from llm.validation import validate_plan_structure
from query.sql.schemas import SqlOperation
from shared.types import QueryRoute, QueryScope


def _sql(op="count_entities", classes=None):
    return SqlPlan(operation=SqlOperation(op), entity_classes=classes or [])


def test_valid_sql_active_plan_has_no_errors():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=1,
        sql_plan=_sql("count_entities", ["IfcDoor"]),
    )
    assert validate_plan_structure(plan) == []


def test_active_scope_requires_source_model_id():
    plan = QueryPlan(scope=QueryScope.ACTIVE_MODEL, route=QueryRoute.SQL, sql_plan=_sql())
    errs = validate_plan_structure(plan)
    assert any("source_model_id" in e for e in errs)


def test_catalog_scope_rejects_entity_plans():
    plan = QueryPlan(
        scope=QueryScope.MODEL_CATALOG,
        route=QueryRoute.SQL,
        catalog_plan=CatalogPlan(operation=SqlOperation.LIST_MODELS),
        sql_plan=_sql(),
    )
    errs = validate_plan_structure(plan)
    assert any("model_catalog must not carry a sql_plan" in e for e in errs)


def test_clarify_requires_question_and_no_subplans():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.CLARIFY,
        source_model_id=1,
        needs_clarification=False,
    )
    errs = validate_plan_structure(plan)
    assert any("clarify" in e for e in errs)


def test_clarify_valid():
    plan = QueryPlan(
        scope=QueryScope.MODEL_CATALOG,
        route=QueryRoute.CLARIFY,
        needs_clarification=True,
        clarification_question="Which model?",
    )
    assert validate_plan_structure(plan) == []


def test_rag_route_rejects_catalog_plan():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.RAG,
        source_model_id=1,
        rag_plan=RagPlan(semantic_query="fire"),
        catalog_plan=CatalogPlan(operation=SqlOperation.LIST_MODELS),
    )
    errs = validate_plan_structure(plan)
    assert errs  # catalog_plan not allowed + catalog under active scope


def test_hybrid_requires_two_plans_and_combination():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=1,
        sql_plan=_sql("filter_entities", ["IfcDoor"]),
        execution=PlanExecution(mode=ExecutionMode.SINGLE, combination=CombinationOp.NONE),
    )
    errs = validate_plan_structure(plan)
    assert any("at least two" in e for e in errs)
    assert any("combination other than 'none'" in e for e in errs)


def test_hybrid_intersection_needs_sql_and_rag():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=1,
        sql_plan=_sql("filter_entities", ["IfcDoor"]),
        graph_plan=GraphPlan(start_entity_ids=[1]),
        execution=PlanExecution(
            mode=ExecutionMode.PARALLEL_INDEPENDENT, combination=CombinationOp.INTERSECTION
        ),
    )
    errs = validate_plan_structure(plan)
    assert any("requires both sql_plan and rag_plan" in e for e in errs)


def test_valid_hybrid_intersection():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=1,
        sql_plan=_sql("filter_entities", ["IfcDoor"]),
        rag_plan=RagPlan(semantic_query="fire separation"),
        execution=PlanExecution(
            mode=ExecutionMode.PARALLEL_INDEPENDENT, combination=CombinationOp.INTERSECTION
        ),
    )
    assert validate_plan_structure(plan) == []


def test_non_hybrid_must_not_set_combination():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=1,
        sql_plan=_sql(),
        execution=PlanExecution(mode=ExecutionMode.SINGLE, combination=CombinationOp.UNION),
    )
    errs = validate_plan_structure(plan)
    assert any("execution.combination='none'" in e for e in errs)


def test_extra_field_is_rejected_by_schema():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QueryPlan(
            scope=QueryScope.MODEL_CATALOG,
            route=QueryRoute.CLARIFY,
            needs_clarification=True,
            clarification_question="?",
            raw_sql="SELECT 1",
        )
