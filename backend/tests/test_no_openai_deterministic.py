"""Deterministic control/selection paths make zero OpenAI calls (Task 10 tests;
extended for the Task 13 detail/group endpoints).

A fake client raises if any planner/answer call is attempted, so reset and the
no-active-model selection guard are proven LLM-free without a network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import models as models_route
from app.api.schemas.request import SessionQueryRequest
from app.query.service import QueryService
from app.query.sql import entities as entity_ops
from app.shared.types import ResponseStatus


class _ExplodingClient:
    """Any LLM interaction is a hard failure."""

    def plan_query(self, _context):  # pragma: no cover - must never run
        raise AssertionError("OpenAI must not be called on this path")


def test_reset_makes_no_openai_call():
    svc = QueryService(llm_client=_ExplodingClient())
    resp = svc.handle_query(SessionQueryRequest(question="clear", session_id="s1", reset=True))
    assert resp.status is ResponseStatus.SUCCESS
    assert resp.active_source_model_id is None


def test_selected_global_ids_without_active_model_makes_no_openai_call():
    svc = QueryService(llm_client=_ExplodingClient())
    resp = svc.handle_query(
        SessionQueryRequest(
            question="what is this?",
            session_id="s1",
            selected_global_ids=["G1"],
            active_source_model_id=None,
        )
    )
    assert resp.status is ResponseStatus.ERROR
    assert "active model" in resp.answer.lower()


@pytest.mark.parametrize("bad", [["G1", "G2", "G3", "G4", "G5", "G6"]])
def test_more_than_five_global_ids_rejected_by_schema(bad):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SessionQueryRequest(question="q", session_id="s1", selected_global_ids=bad)


# ---------------------------------------------------------------------------
# Task 13 §4/§5: the component-panel endpoints are deterministic and LLM-free
# ---------------------------------------------------------------------------


@pytest.fixture()
def panel_api(monkeypatch):
    """Detail/group endpoints with a stubbed entity row and exploding LLM/embedding."""

    def _no_llm(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("OpenAI must not be called by the component-panel endpoints")

    def _no_embedding(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("no embedding may be created by the component-panel endpoints")

    monkeypatch.setattr("app.llm.client.OpenAIQueryClient", _no_llm)
    monkeypatch.setattr("app.query.rag.embedding_service.get_embedding_service", _no_embedding)
    monkeypatch.setattr(
        entity_ops,
        "get_entity_canonical",
        lambda _s, model_id, gid: (
            SimpleNamespace(
                id=1,
                global_id="G1",
                ifc_class="IfcDoor",
                canonical_json={"identity": {"name": "Door"}, "type": None, "property_sets": {}},
            )
            if model_id == 1 and gid == "G1"
            else None
        ),
    )
    monkeypatch.setattr(
        entity_ops,
        "match_instance",
        lambda *_a: (
            entity_ops.ViewerIdentityResult(
                rows=[SimpleNamespace(global_id="G1", ifc_class="IfcDoor")],
                exact_total=1,
                truncated=False,
            ),
            {"IfcDoor": 1},
        ),
    )
    app.dependency_overrides[models_route.get_db] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.pop(models_route.get_db, None)


def test_details_endpoint_makes_no_openai_or_embedding_call(panel_api):
    resp = panel_api.get("/api/models/1/entities/G1/details")
    assert resp.status_code == 200
    assert resp.json()["instance"]["global_id"] == "G1"


def test_highlight_group_endpoint_makes_no_openai_or_embedding_call(panel_api):
    resp = panel_api.post(
        "/api/models/1/entities/highlight-group",
        json={"selected_global_id": "G1", "scope": "instance"},
    )
    assert resp.status_code == 200
    assert resp.json()["global_ids"] == ["G1"]


def test_panel_endpoints_do_not_mutate_the_shared_session_state(panel_api):
    """The panel buttons must not create a chat message or alter conversation
    history (task13 §5). Uses the real shared store the query service uses."""
    from app.query.session import ChatMessage, get_session_store

    state = get_session_store().get_or_create("panel-session")
    state.chat_history.append(ChatMessage(role="user", content="how many doors?"))
    state.active_source_model_id = 1
    before = [m.model_copy() for m in state.chat_history]

    panel_api.post(
        "/api/models/1/entities/highlight-group",
        json={"selected_global_id": "G1", "scope": "instance"},
    )
    panel_api.get("/api/models/1/entities/G1/details")

    after = get_session_store().get_or_create("panel-session")
    assert after.chat_history == before
    assert after.last_primary_entity_ids == []
    assert after.active_source_model_id == 1  # untouched, not reset
