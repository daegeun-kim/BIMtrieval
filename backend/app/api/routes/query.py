"""POST /api/query — the only public query endpoint (spec_v002 Section 16).

Thin adapter over query.service.QueryService; no LLM/SQL/RAG/graph logic
lives in this module.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.schemas.request import QueryRenderTimingRequest, SessionQueryRequest
from app.api.schemas.response import QueryResponseEnvelope
from app.config import trace
from app.query.service import get_query_service

router = APIRouter(tags=["query"])


@router.post("/api/query", response_model=QueryResponseEnvelope)
def query(request: SessionQueryRequest) -> QueryResponseEnvelope:
    return get_query_service().handle_query(request)


@router.post(
    "/api/query/render-timing",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def query_render_timing(timing: QueryRenderTimingRequest) -> Response:
    """Print browser-observed completion time after 3D highlighting finishes."""
    trace.emit(
        "[Query render timing]",
        {
            "request_id": timing.request_id,
            "response_received_ms": round(timing.response_received_ms, 1),
            "viewer_render_ms": round(timing.viewer_render_ms, 1),
            "total_query_to_viewer_ms": round(timing.total_to_viewer_ms, 1),
        },
        force=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
