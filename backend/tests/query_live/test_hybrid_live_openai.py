"""Bounded live-OpenAI validation (spec_v005 §18).

These make real `gpt-5-nano` calls and hit the live database, so they are
skipped unless BOTH are available (the query_live conftest skips on no DB; a
module fixture skips on no OPENAI_API_KEY). Kept intentionally small — a handful
of calls covering paraphrase stability, route selection, grounded answering, and
the public /api/query contract.
"""

from __future__ import annotations

import pytest
from api.schemas.request import SessionQueryRequest
from config.settings import get_settings
from db.session import session_scope
from llm.client import get_llm_client
from llm.context import build_planner_context
from llm.validation import validate_plan_structure
from query.service import get_query_service
from query.session import get_session_store
from query.sql.schemas import SqlOperation
from shared.types import QueryRoute

SOURCE_MODEL_ID = 1


@pytest.fixture(scope="module")
def openai_client():
    settings = get_settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY not configured")
    return get_llm_client(settings)


def _plan(client, question, active=SOURCE_MODEL_ID):
    settings = get_settings()
    req = SessionQueryRequest(question=question, session_id="live", active_source_model_id=active)
    state = get_session_store().get_or_create("live")
    with session_scope() as s:
        ctx = build_planner_context(s, req, state, settings)
        plan = client.plan_query(ctx).plan
    assert validate_plan_structure(plan) == []
    return plan


def test_paraphrases_produce_equivalent_operation(openai_client):
    p1 = _plan(openai_client, "How many doors are in this model?")
    p2 = _plan(openai_client, "Count the doors in the building.")
    assert p1.route is QueryRoute.SQL and p2.route is QueryRoute.SQL
    assert p1.sql_plan.operation is SqlOperation.COUNT_ENTITIES
    assert p2.sql_plan.operation is SqlOperation.COUNT_ENTITIES
    assert "IfcDoor" in p1.sql_plan.entity_classes
    assert "IfcDoor" in p2.sql_plan.entity_classes


def test_semantic_question_routes_to_rag(openai_client):
    plan = _plan(openai_client, "Which elements seem related to fire separation?")
    assert plan.route in (QueryRoute.RAG, QueryRoute.HYBRID)
    assert plan.rag_plan is not None


def test_grounded_count_answer_is_exact(openai_client):
    svc = get_query_service()
    req = SessionQueryRequest(
        question="How many windows are in this model?",
        session_id="live_ans",
        active_source_model_id=SOURCE_MODEL_ID,
    )
    resp = svc.handle_query(req)
    assert resp.status.value == "success"
    assert resp.route is QueryRoute.SQL
    assert resp.evidence_summary.sql_match_count == 259
    assert "259" in resp.answer


def test_api_query_contract(openai_client):
    from api.app import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    resp = client.post(
        "/api/query",
        json={
            "question": "How many doors are there?",
            "session_id": "http_live",
            "active_source_model_id": SOURCE_MODEL_ID,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # stable response contract (spec_v005 §15)
    for key in (
        "request_id",
        "session_id",
        "status",
        "scope",
        "route",
        "answer_basis",
        "answer",
        "viewer_actions",
        "evidence_summary",
    ):
        assert key in body
    assert body["viewer_actions"]["model_action"] in {
        "keep_current",
        "await_user_confirmation",
        "load_model",
    }
