"""Request/response envelopes accept valid examples and reject invalid shapes
(spec_v002 Section 16, tasks/task04.md required verification)."""

from __future__ import annotations

import pytest
from api.schemas.request import SessionQueryRequest
from api.schemas.response import EvidenceSummary, QueryResponseEnvelope
from pydantic import ValidationError
from shared.types import AnswerBasis, QueryRoute, QueryScope, ResponseStatus
from viewer.actions import build_default_viewer_actions


def test_valid_request_accepted():
    req = SessionQueryRequest(
        question="Which doors relate to fire separation?",
        session_id="browser-session-id",
        active_source_model_id=1,
        selected_entity_ids=[101, 102],
        history=[],
    )
    assert req.active_source_model_id == 1


def test_catalog_request_allows_null_active_model():
    req = SessionQueryRequest(question="Show me a residential model.", session_id="s1")
    assert req.active_source_model_id is None


def test_request_rejects_more_than_five_selected_entities():
    with pytest.raises(ValidationError):
        SessionQueryRequest(
            question="q",
            session_id="s1",
            selected_entity_ids=[1, 2, 3, 4, 5, 6],
        )


def test_request_rejects_unknown_field():
    with pytest.raises(ValidationError):
        SessionQueryRequest(question="q", session_id="s1", raw_sql="DROP TABLE x")


def test_valid_response_envelope_accepted():
    env = QueryResponseEnvelope(
        request_id="r1",
        session_id="s1",
        status=ResponseStatus.SUCCESS,
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        answer_basis=AnswerBasis.HYBRID_EVIDENCE,
        answer="The model contains 84 doors.",
        active_source_model_id=1,
        viewer_actions=build_default_viewer_actions(),
        evidence_summary=EvidenceSummary(basis=AnswerBasis.HYBRID_EVIDENCE),
    )
    assert env.status is ResponseStatus.SUCCESS


def test_response_envelope_rejects_unknown_field():
    with pytest.raises(ValidationError):
        QueryResponseEnvelope(
            request_id="r1",
            session_id="s1",
            status=ResponseStatus.SUCCESS,
            scope=QueryScope.MODEL_CATALOG,
            route=QueryRoute.CLARIFY,
            answer_basis=AnswerBasis.INSUFFICIENT_EVIDENCE,
            answer="Please choose a model.",
            evidence_summary=EvidenceSummary(basis=AnswerBasis.INSUFFICIENT_EVIDENCE),
            raw_sql="SELECT * FROM ifc_entities",
        )
