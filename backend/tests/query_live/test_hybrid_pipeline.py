"""End-to-end query-service pipeline with a scripted (fake) LLM client and the
real database (spec_v005 §2, §6, §7, §9, §15, §18).

Using a fake planner makes routing/repair/combination behavior deterministic —
no OpenAI variability — while SQL execution, canonical-ID combination, and
hydration run for real against the live model. RAG is monkeypatched so hybrid
combination can be exercised without loading the embedding model.

Skipped automatically when the live database is unreachable (query_live
conftest). Live OpenAI behavior is covered separately in
test_hybrid_live_openai.py.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from api.schemas.request import SessionQueryRequest
from llm.client import AnswerOutput, AnswerResult, PlanResult, TokenUsage
from llm.schemas import (
    CombinationOp,
    ExecutionMode,
    PlanExecution,
    QueryPlan,
    RagPlan,
    SqlPlan,
)
from query.rag.schemas import RagCandidate, RagSearchResult
from query.service import QueryService
from query.sql.schemas import (
    FieldKind,
    Operator,
    SqlOperation,
)
from llm.schemas import PlanFieldRef, PlanFilter
from shared.types import AnswerBasis, QueryRoute, QueryScope

from bim_rag.schema.models import IfcEntity

SOURCE_MODEL_ID = 1


class _FakeLog:
    def __init__(self):
        self.calls = []


class FakeLLMClient:
    """Returns scripted plans/answers; records how many planner calls happened."""

    def __init__(self, plans, answer="scripted answer", used_general=False):
        self._plans = list(plans)
        self._answer = answer
        self._used_general = used_general
        self.plan_calls = 0
        self.answer_calls = 0
        self.log = _FakeLog()

    def plan_query(self, context):
        idx = min(self.plan_calls, len(self._plans) - 1)
        plan = self._plans[idx]
        self.plan_calls += 1
        self.log.calls.append({"role": "planner", "model": "fake", "total_tokens": 1})
        return PlanResult(plan=plan, usage=TokenUsage(model="fake", total_tokens=1))

    def generate_answer(self, payload):
        self.answer_calls += 1
        self.log.calls.append({"role": "answerer", "model": "fake", "total_tokens": 1})
        return AnswerResult(
            output=AnswerOutput(answer=self._answer, used_general_knowledge=self._used_general),
            usage=TokenUsage(model="fake", total_tokens=1),
        )


def _service(plans, **kw):
    return QueryService(llm_client=FakeLLMClient(plans, **kw))


def _req(question="q", sid="pipe", active=SOURCE_MODEL_ID, **kw):
    return SessionQueryRequest(question=question, session_id=sid, active_source_model_id=active, **kw)


def _door_ids(session, n=6):
    rows = session.execute(
        sa.select(IfcEntity.__table__.c.id)
        .where(
            IfcEntity.__table__.c.source_model_id == SOURCE_MODEL_ID,
            IfcEntity.__table__.c.ifc_class == "IfcDoor",
        )
        .order_by(IfcEntity.__table__.c.id)
        .limit(n)
    ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# One planner call; no separate routing call
# ---------------------------------------------------------------------------


def test_single_planner_call_and_no_separate_routing():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(operation=SqlOperation.COUNT_ENTITIES, entity_classes=["IfcDoor"]),
    )
    svc = _service([plan])
    resp = svc.handle_query(_req("How many doors?"))
    assert resp.status.value == "success"
    assert resp.route is QueryRoute.SQL
    assert resp.answer_basis is AnswerBasis.EXACT_SQL
    # exactly one planner call — proves there is no separate route-classification call
    assert svc._client().plan_calls == 1  # type: ignore[attr-defined]
    assert resp.evidence_summary.sql_match_count == 205


# ---------------------------------------------------------------------------
# At most one repair
# ---------------------------------------------------------------------------


def test_one_repair_recovers_from_invalid_plan():
    bad = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(
            operation=SqlOperation.FILTER_ENTITIES,
            entity_classes=["IfcDoor"],
            filters=[
                PlanFilter(
                    field=PlanFieldRef(field_kind=FieldKind.DIMENSION, field_name="NoSuchField"),
                    operator=Operator.GT,
                    value_text="1",
                )
            ],
        ),
    )
    good = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(operation=SqlOperation.COUNT_ENTITIES, entity_classes=["IfcDoor"]),
    )
    svc = _service([bad, good])
    resp = svc.handle_query(_req())
    assert resp.status.value == "success"
    assert svc._client().plan_calls == 2  # one repair


def test_two_invalid_plans_yield_clarification_not_loop():
    bad = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(
            operation=SqlOperation.AGGREGATE_ENTITIES,
            entity_classes=["IfcSlab"],
            aggregate_function="sum",
            aggregate_field=PlanFieldRef(field_kind=FieldKind.DIMENSION, field_name="Nope"),
        ),
    )
    svc = _service([bad, bad])
    resp = svc.handle_query(_req())
    assert resp.route is QueryRoute.CLARIFY
    assert svc._client().plan_calls == 2  # bounded — never a third attempt


# ---------------------------------------------------------------------------
# Non-retrieval routes
# ---------------------------------------------------------------------------


def test_clarify_route_returns_question():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.CLARIFY,
        source_model_id=SOURCE_MODEL_ID,
        needs_clarification=True,
        clarification_question="Which storey do you mean?",
    )
    svc = _service([plan])
    resp = svc.handle_query(_req())
    assert resp.route is QueryRoute.CLARIFY
    assert resp.answer == "Which storey do you mean?"
    assert svc._client().answer_calls == 0  # clarify needs no answer call


def test_explain_general_uses_general_knowledge_basis():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.EXPLAIN_GENERAL,
        source_model_id=SOURCE_MODEL_ID,
    )
    svc = _service([plan], answer="IFC is an open BIM data schema.", used_general=True)
    resp = svc.handle_query(_req("what is IFC?"))
    assert resp.route is QueryRoute.EXPLAIN_GENERAL
    assert resp.answer_basis is AnswerBasis.GENERAL_KNOWLEDGE
    assert resp.viewer_actions.selection_action.value == "none"


# ---------------------------------------------------------------------------
# Hybrid combination (RAG monkeypatched)
# ---------------------------------------------------------------------------


def _hybrid_plan(combo=CombinationOp.INTERSECTION):
    return QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(operation=SqlOperation.LIST_ENTITIES, entity_classes=["IfcDoor"], limit=500),
        rag_plan=RagPlan(semantic_query="fire", search_entity_documents=True),
        execution=PlanExecution(
            mode=ExecutionMode.PARALLEL_INDEPENDENT, combination=combo
        ),
    )


def _fake_rag_result(accepted_ids):
    cands = [
        RagCandidate(
            rag_document_id=1000 + i,
            source_kind="entity",
            document_type="entity_description",
            canonical_id=cid,
            cosine_distance=0.1,
            similarity=0.9 - i * 0.01,
            per_kind_rank=i + 1,
            embedding_model="BAAI/bge-m3",
            embedding_dim=1024,
            text_template_version="v001",
            document_text_excerpt="...",
            passed_threshold=True,
        )
        for i, cid in enumerate(accepted_ids)
    ]
    return RagSearchResult(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="fire",
        threshold_profile="default_v001",
        threshold_value=0.5,
        entity_candidates=cands,
        sufficient_evidence=bool(cands),
    )


def test_hybrid_intersection_nonempty(live_session, monkeypatch):
    doors = _door_ids(live_session, 6)
    assert len(doors) >= 4
    accepted = [doors[0], doors[1], 999999999]  # two real doors + one non-door
    monkeypatch.setattr(
        "query.hybrid.orchestrator.run_rag_search", lambda s, e, p: _fake_rag_result(accepted)
    )
    monkeypatch.setattr(
        "query.hybrid.orchestrator.get_embedding_service", lambda: object(), raising=False
    )
    svc = QueryService(llm_client=FakeLLMClient([_hybrid_plan()]))
    # inject the getter used by orchestrate via service; embedding getter is imported there
    monkeypatch.setattr("query.service.get_embedding_service", lambda: object())
    resp = svc.handle_query(_req("doors related to fire", sid="hyb1"))
    assert resp.route is QueryRoute.HYBRID
    ids = {e.entity_id for e in resp.primary_entities}
    assert ids == {doors[0], doors[1]}
    assert resp.answer_basis is AnswerBasis.HYBRID_EVIDENCE


def test_hybrid_empty_intersection_is_not_union(live_session, monkeypatch):
    doors = _door_ids(live_session, 4)
    monkeypatch.setattr(
        "query.hybrid.orchestrator.run_rag_search",
        lambda s, e, p: _fake_rag_result([888888888, 777777777]),
    )
    monkeypatch.setattr("query.service.get_embedding_service", lambda: object())
    svc = QueryService(llm_client=FakeLLMClient([_hybrid_plan(CombinationOp.INTERSECTION)]))
    resp = svc.handle_query(_req("doors related to fire", sid="hyb2"))
    assert resp.primary_entities == []  # empty intersection stays empty
    assert any("empty intersection" in w for w in resp.warnings)


def test_degraded_hybrid_returns_sql_portion_with_warning(live_session, monkeypatch):
    from query.rag.errors import EmbeddingServiceUnavailableError

    def _boom(session, emb, plan):
        raise EmbeddingServiceUnavailableError("embedding model down")

    monkeypatch.setattr("query.hybrid.orchestrator.run_rag_search", _boom)
    monkeypatch.setattr("query.service.get_embedding_service", lambda: object())
    # sequential mode so the RAG failure surfaces as a DegradedCapabilityError
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(operation=SqlOperation.LIST_ENTITIES, entity_classes=["IfcDoor"], limit=10),
        rag_plan=RagPlan(semantic_query="fire", search_entity_documents=True),
        execution=PlanExecution(
            mode=ExecutionMode.SQL_THEN_RAG, combination=CombinationOp.INTERSECTION
        ),
    )
    svc = QueryService(llm_client=FakeLLMClient([plan]))
    resp = svc.handle_query(_req("doors related to fire", sid="degraded"))
    assert resp.status.value == "success"
    # surviving SQL portion returned, clearly labelled as degraded, not a crash
    assert len(resp.primary_entities) > 0
    assert any("degraded" in w.lower() for w in resp.warnings)


def test_execution_error_degrades_gracefully_not_500(monkeypatch):
    from shared.errors import UnsupportedOperationError

    def _boom(**kwargs):
        raise UnsupportedOperationError("unknown field at execution")

    monkeypatch.setattr("query.service.orchestrate", _boom)
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.SQL,
        source_model_id=SOURCE_MODEL_ID,
        sql_plan=SqlPlan(operation=SqlOperation.COUNT_ENTITIES, entity_classes=["IfcDoor"]),
    )
    svc = _service([plan])
    resp = svc.handle_query(_req("count doors", sid="execguard"))
    assert resp.status.value == "error"
    assert resp.route is QueryRoute.CLARIFY
    assert "couldn't complete" in resp.answer.lower()


def test_reset_clears_active_model():
    plan = QueryPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.EXPLAIN_GENERAL,
        source_model_id=SOURCE_MODEL_ID,
    )
    svc = _service([plan], answer="ok")
    resp = svc.handle_query(_req(reset=True))
    assert resp.status.value == "success"
    assert resp.active_source_model_id is None
