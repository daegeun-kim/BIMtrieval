"""Development-only lower-level endpoints (spec_v005 §15: "keep lower-level
endpoints development-only").

These are NOT part of the public frontend contract and are only mounted when
`settings.enable_dev_endpoints` is true. They expose the experiment2_v5
grounding stage in isolation — the intent-derived requirement ledger,
high-recall recommendations, and the compact capability projection, plus
optionally the grounding call and deterministic validation — with no execution
and no answer call. They never bypass the safety layer: no raw SQL, no secrets,
no viewer identities.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.request import SessionQueryRequest
from app.config.settings import get_settings
from app.db.session import session_scope
from app.llm.client import LLMError, get_llm_client
from app.llm.grounding_context_v5 import build_grounding_context_v5
from app.query.binding.intent import deterministic_intent, serialize_conversation
from app.query.binding.obligations import (
    build_obligations,
    build_plan_skeleton,
    build_recall_ledger,
    candidates_by_slot,
)
from app.query.binding.assemble_v5 import assemble_plan
from app.query.binding.preservation import validate_semantic_preservation
from app.query.binding.recall import resolve_ledger, run_recall
from app.query.binding.validate_v2 import validate_plan
from app.query.rag.embedding_service import get_embedding_service
from app.query.semantic.manifest_v002 import (
    ManifestV002UnavailableError,
    build_binder_projection,
    get_manifest_v002,
)

router = APIRouter(tags=["dev"], prefix="/api/dev")


def _offline_intent(request: SessionQueryRequest):
    """The deterministic intent, so these endpoints cost nothing to call.

    The dev surface inspects retrieval and grounding, not conversation
    interpretation, so it deliberately skips the resolver call.
    """
    conversation = serialize_conversation(
        request.question,
        [{"role": t.role, "content": t.content} for t in request.history],
    )
    return deterministic_intent(request.question, conversation)


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
        intent = _offline_intent(request)
        ledger = build_recall_ledger(
            build_obligations(intent), intent.normalized_request
        )
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


@router.post("/ground")
def ground_only(request: SessionQueryRequest) -> dict:
    """Recall + the grounding call + deterministic validation, no execution.

    Exactly one model call is made — no resolver call and no correction attempt
    — so the grounding stage can be inspected on its own.
    """
    settings = get_settings()
    if request.active_source_model_id is None:
        return {"ok": False, "error": "an active model is required to ground a question"}
    try:
        with session_scope() as session:
            manifest = get_manifest_v002(session, request.active_source_model_id, settings)
            projection = build_binder_projection(manifest)
            intent = _offline_intent(request)
            obligations = build_obligations(intent)
            skeleton = build_plan_skeleton(intent, obligations)
            ledger = build_recall_ledger(obligations, intent.normalized_request)
            recall = run_recall(
                session, manifest, ledger, embedding_service_getter=get_embedding_service
            )
            resolve_ledger(ledger, recall, manifest)
            context = build_grounding_context_v5(
                intent,
                projection,
                skeleton,
                recall,
                settings=settings,
                source_model_id=request.active_source_model_id,
                candidates_by_slot=candidates_by_slot(obligations, recall),
            )
            bindings, usage = get_llm_client(settings).ground_plan_v5(context)
            plan = assemble_plan(intent, skeleton, obligations, bindings)
            validation = validate_plan(session, plan, ledger, manifest)
            preservation = validate_semantic_preservation(
                intent, obligations, skeleton, plan, validation
            )
    except (LLMError, ManifestV002UnavailableError) as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": all(
            v.state.value in ("ready", "partial_executable") for v in validation.verdicts
        )
        and preservation.ok,
        "gate_states": {v.part.part_id: v.state.value for v in validation.verdicts},
        "issues": [i.to_payload() for i in validation.all_issues()],
        "preservation": preservation.to_payload(),
        "slots": skeleton.to_payload(),
        "bindings": bindings.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "token_usage": usage.as_dict() if usage is not None else None,
    }
