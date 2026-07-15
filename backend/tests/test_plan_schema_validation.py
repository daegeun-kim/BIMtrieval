"""The unified planner QueryPlan (spec_v005 §5) accepts the spec example and is
strict (extra="forbid", enum-validated). Semantic scope/route rules live in
llm.validation (see tests/query_hybrid/test_validation.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.schemas import (
    CombinationOp,
    ExecutionMode,
    GraphPlan,
    PlanExecution,
    QueryPlan,
    RagPlan,
    SqlPlan,
)
from app.query.sql.schemas import SqlOperation
from app.shared.types import QueryRoute, QueryScope


def test_section5_hybrid_example_accepted():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=1,
        sql_plan=SqlPlan(operation=SqlOperation.FILTER_ENTITIES, entity_classes=["IfcDoor"]),
        rag_plan=RagPlan(
            semantic_query="doors related to fire separation",
            search_entity_documents=True,
            search_relationship_documents=True,
        ),
        graph_plan=GraphPlan(expand_relationship_endpoints=True, max_depth=1),
        execution=PlanExecution(
            mode=ExecutionMode.PARALLEL_INDEPENDENT, combination=CombinationOp.INTERSECTION
        ),
    )
    assert plan.route is QueryRoute.HYBRID
    assert plan.execution.combination is CombinationOp.INTERSECTION


def test_plan_rejects_unknown_field():
    with pytest.raises(ValidationError):
        QueryPlan(
            scope=QueryScope.MODEL_CATALOG,
            route=QueryRoute.CLARIFY,
            needs_clarification=True,
            clarification_question="Which model?",
            raw_sql="SELECT 1",
        )


def test_plan_rejects_out_of_vocabulary_route():
    with pytest.raises(ValidationError):
        QueryPlan(scope=QueryScope.ACTIVE_MODEL, route="delete_everything", source_model_id=1)


def test_sql_plan_rejects_unknown_operation():
    with pytest.raises(ValidationError):
        SqlPlan(operation="drop_table")


def test_rag_plan_top_k_bounded():
    with pytest.raises(ValidationError):
        RagPlan(semantic_query="x", top_k_per_kind=9999)
