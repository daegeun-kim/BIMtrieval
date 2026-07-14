"""POST /api/query — the only public query endpoint (spec_v002 Section 16).

Thin adapter over query.service.QueryService; no LLM/SQL/RAG/graph logic
lives in this module.
"""

from __future__ import annotations

from fastapi import APIRouter
from query.service import get_query_service

from api.schemas.request import SessionQueryRequest
from api.schemas.response import QueryResponseEnvelope

router = APIRouter(tags=["query"])


@router.post("/api/query", response_model=QueryResponseEnvelope)
def query(request: SessionQueryRequest) -> QueryResponseEnvelope:
    return get_query_service().handle_query(request)
