"""Development-only lower-level endpoints (spec_v005 §15: "keep lower-level
endpoints development-only").

These are NOT part of the public frontend contract and are only mounted when
`settings.enable_dev_endpoints` is true. They expose the planner/validation
stage in isolation (no execution, no answer call) for debugging and evaluation.
They never bypass the safety layer: no raw SQL, no secrets.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas.request import SessionQueryRequest
from config.settings import get_settings
from db.session import session_scope
from llm.client import LLMError, get_llm_client
from llm.context import build_planner_context
from llm.validation import validate_plan_structure
from query.session import get_session_store

router = APIRouter(tags=["dev"], prefix="/api/dev")


@router.post("/plan")
def plan_only(request: SessionQueryRequest) -> dict:
    """Return the planner's validated plan without executing or answering."""
    settings = get_settings()
    state = get_session_store().get_or_create(request.session_id)
    try:
        with session_scope() as session:
            context = build_planner_context(session, request, state, settings)
            result = get_llm_client(settings).plan_query(context)
    except LLMError as exc:
        return {"ok": False, "error": str(exc)}
    errors = validate_plan_structure(result.plan)
    return {
        "ok": not errors,
        "structural_errors": errors,
        "plan": result.plan.model_dump(mode="json"),
        "token_usage": result.usage.as_dict(),
    }
