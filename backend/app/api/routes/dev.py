"""Development-only lower-level endpoints (spec_v005 §15: "keep lower-level
endpoints development-only").

These are NOT part of the public frontend contract and are only mounted when
`settings.enable_dev_endpoints` is true. They expose the Task 24 binding stage
in isolation — slate construction and, optionally, LLM call 1 plus deterministic
validation — with no execution and no answer call. They never bypass the safety
layer: no raw SQL, no secrets, no viewer identities.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.request import SessionQueryRequest
from app.config.settings import get_settings
from app.db.session import session_scope
from app.llm.binder_context import build_binder_context
from app.llm.client import LLMError, get_llm_client
from app.query.binding.slate import SlateInputs, build_slate
from app.query.binding.validate import validate_binding
from app.query.session import get_session_store

router = APIRouter(tags=["dev"], prefix="/api/dev")


@router.post("/slate")
def slate_only(request: SessionQueryRequest) -> dict:
    """Return the candidate slate without calling any model (task24 §1).

    Useful for inspecting recall and prompt size for a question at zero cost.
    """
    settings = get_settings()
    if request.active_source_model_id is None:
        return {"ok": False, "error": "an active model is required to build a slate"}
    with session_scope() as session:
        slate = build_slate(
            session,
            SlateInputs(
                question=request.question,
                source_model_id=request.active_source_model_id,
            ),
            settings=settings,
        )
        return {
            "ok": True,
            "size": slate.size_report(),
            "slate": slate.to_prompt_payload(),
        }


@router.post("/bind")
def bind_only(request: SessionQueryRequest) -> dict:
    """Slate + LLM call 1 + deterministic validation, with no execution.

    Exactly one model call is made — there is no repair attempt, matching the
    production contract (task24 §3.3).
    """
    settings = get_settings()
    if request.active_source_model_id is None:
        return {"ok": False, "error": "an active model is required to bind a question"}
    state = get_session_store().get_or_create(request.session_id)
    try:
        with session_scope() as session:
            slate = build_slate(
                session,
                SlateInputs(
                    question=request.question,
                    source_model_id=request.active_source_model_id,
                ),
                settings=settings,
            )
            context = build_binder_context(
                request.question,
                slate,
                settings=settings,
                previous_scope=state.previous_scope,
                active_source_model_id=request.active_source_model_id,
            )
            result = get_llm_client(settings).bind_query(context)
    except LLMError as exc:
        return {"ok": False, "error": str(exc)}

    validation = validate_binding(result.plan, slate)
    return {
        "ok": validation.valid,
        "issues": [{"code": i.code, "detail": i.detail} for i in validation.all_issues()],
        "dropped_modifiers": validation.silently_dropped_modifiers,
        "binding": result.plan.model_dump(mode="json"),
        "closures": [
            {"part_id": p.part.part_id, "ifc_classes": list(p.closure.ifc_classes)}
            for p in validation.parts
        ],
        "token_usage": result.usage.as_dict(),
    }
