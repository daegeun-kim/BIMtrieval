"""Development-only lower-level endpoints (spec_v005 §15: "keep lower-level
endpoints development-only").

These are NOT part of the public frontend contract and are only mounted when
`settings.enable_dev_endpoints` is true. They expose the experiment2_v4 binding
stage in isolation — the requirement ledger, high-recall recommendations, and
the compact binder projection, plus optionally LLM call 1 and deterministic
validation — with no execution and no answer call. They never bypass the safety
layer: no raw SQL, no secrets, no viewer identities.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.request import SessionQueryRequest
from app.config.settings import get_settings
from app.db.session import session_scope
from app.llm.binder_context_v2 import build_binder_context_v2
from app.llm.client import LLMError, get_llm_client
from app.query.binding.ledger_v2 import build_ledger_skeleton
from app.query.binding.recall import resolve_ledger, run_recall
from app.query.binding.validate_v2 import validate_plan
from app.query.rag.embedding_service import get_embedding_service
from app.query.semantic.manifest_v002 import (
    ManifestV002UnavailableError,
    build_binder_projection,
    get_manifest_v002,
)

router = APIRouter(tags=["dev"], prefix="/api/dev")


@router.post("/resolve")
def resolve_only(request: SessionQueryRequest) -> dict:
    """Return the ledger + recall + projection size without any model call.

    Useful for inspecting recall and prompt size for a question at zero cost.
    """
    settings = get_settings()
    if request.active_source_model_id is None:
        return {"ok": False, "error": "an active model is required to resolve a question"}
    with session_scope() as session:
        try:
            manifest = get_manifest_v002(session, request.active_source_model_id, settings)
        except ManifestV002UnavailableError as exc:
            return {"ok": False, "error": str(exc)}
        projection = build_binder_projection(manifest)
        ledger = build_ledger_skeleton(request.question)
        recall = run_recall(
            session, manifest, ledger, embedding_service_getter=get_embedding_service
        )
        resolve_ledger(ledger, recall, manifest)
        return {
            "ok": True,
            "projection_tokens": projection.estimated_tokens,
            "projection_hash": projection.projection_hash[:16],
            "ledger": ledger.to_payload(),
            "recommendations": [r.to_payload() for r in recall.recommendations],
            "recall_diagnostics": recall.diagnostics,
        }


@router.post("/bind")
def bind_only(request: SessionQueryRequest) -> dict:
    """Resolve + LLM call 1 + deterministic validation, with no execution.

    Exactly one model call is made — there is no correction attempt here,
    matching the production contract.
    """
    settings = get_settings()
    if request.active_source_model_id is None:
        return {"ok": False, "error": "an active model is required to bind a question"}
    try:
        with session_scope() as session:
            manifest = get_manifest_v002(session, request.active_source_model_id, settings)
            projection = build_binder_projection(manifest)
            ledger = build_ledger_skeleton(request.question)
            recall = run_recall(
                session, manifest, ledger, embedding_service_getter=get_embedding_service
            )
            resolve_ledger(ledger, recall, manifest)
            context = build_binder_context_v2(
                request.question,
                projection,
                ledger,
                recall,
                settings=settings,
                source_model_id=request.active_source_model_id,
            )
            plan, usage = get_llm_client(settings).bind_query_v2(context)
            validation = validate_plan(session, plan, ledger, manifest)
    except (LLMError, ManifestV002UnavailableError) as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": all(
            v.state.value in ("ready", "partial_executable") for v in validation.verdicts
        ),
        "gate_states": {v.part.part_id: v.state.value for v in validation.verdicts},
        "issues": [i.to_payload() for i in validation.all_issues()],
        "binding": plan.model_dump(mode="json"),
        "token_usage": usage.as_dict() if usage is not None else None,
    }
