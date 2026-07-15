"""POST /api/query — the only public query endpoint (spec_v002 Section 16).

Thin adapter over query.service.QueryService; no LLM/SQL/RAG/graph logic
lives in this module.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.request import SessionQueryRequest
from app.api.schemas.response import QueryResponseEnvelope
from app.query.service import get_query_service

router = APIRouter(tags=["query"])


@router.post("/api/query", response_model=QueryResponseEnvelope)
def query(request: SessionQueryRequest) -> QueryResponseEnvelope:
    return get_query_service().handle_query(request)
