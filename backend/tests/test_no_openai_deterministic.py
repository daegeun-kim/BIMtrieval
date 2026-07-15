"""Deterministic control/selection paths make zero OpenAI calls (Task 10 tests).

A fake client raises if any planner/answer call is attempted, so reset and the
no-active-model selection guard are proven LLM-free without a network.
"""

from __future__ import annotations

import pytest

from app.api.schemas.request import SessionQueryRequest
from app.query.service import QueryService
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
