"""Input assembly for the binder and corrective calls (task25 §3, §6).

The binder sees exactly:

- the complete, untruncated semantic manifest of the active model (§2.4);
- advisory high-recall recommendations pointing at likely concepts (§3.1);
- the typed constraint ledger it must account for (§3.2);
- the current question and bounded context needed to resolve references.

It never sees database rows, raw embeddings, retrieval results, similarity
scores, or viewer identities — that boundary is enforced by CONSTRUCTION here,
because the payload is assembled from a fixed set of fields.

The return shape is split for prompt caching (§6): `manifest_json` is the large
stable prefix (it goes into the Responses `instructions`), `payload` is the small
variable part (it goes into `input`), and `cache_key` routes and invalidates the
prefix cache. The final answer writer does NOT go through here — it receives only
the adjudicated packet, never the manifest.
"""

from __future__ import annotations

import json
from typing import Any

from app.config.settings import Settings
from app.llm.serialization import dumps_context
from app.query.binding.ledger import ConstraintLedger
from app.query.binding.schemas import CandidateSlate
from app.query.semantic.manifest import SemanticManifest

__all__ = ["build_binder_context", "build_correction_context"]


def _compact_manifest(manifest: SemanticManifest) -> str:
    """Serialize the complete manifest with NO indentation.

    The manifest is the large stable prefix, and pretty-printing it inflates the
    token count ~2.5x for no benefit to the model — an entirely mechanical cost.
    A compact single-line dump keeps the COMPLETE manifest (§2.4, nothing
    truncated) while roughly halving the input tokens, which also keeps each
    binder request under the smaller models' per-minute token limits.
    """
    return json.dumps(manifest.document, ensure_ascii=False, separators=(",", ":"))


def build_binder_context(
    question: str,
    manifest: SemanticManifest,
    recommendations: CandidateSlate,
    ledger: ConstraintLedger,
    *,
    settings: Settings,
    history: list[dict[str, str]] | None = None,
    selected_entities: list[dict[str, Any]] | None = None,
    previous_scope: Any | None = None,
) -> dict[str, Any]:
    """Assemble the binder input (§3.3)."""
    payload: dict[str, Any] = {
        "question": question,
        "recommendations": [r.to_payload() for r in recommendations.recommendations],
        "constraint_ledger": ledger.to_payload(),
    }
    # Request-specific scope candidates (floor bands, the current selection, the
    # previous result) are DERIVED per request and are not manifest concepts, so
    # they must be listed explicitly or the binder cannot select a floor/selection
    # scope by id. §3.1 admits these validated request-specific candidates
    # alongside the manifest.
    scopes = [c.to_payload() for c in recommendations.spatial]
    if scopes:
        payload["available_scopes"] = scopes
    if recommendations.coverage_notes:
        payload["model_limitations"] = list(recommendations.coverage_notes)

    if history:
        payload["recent_turns"] = [
            {"role": turn["role"], "content": str(turn["content"])[:400]}
            for turn in history[-settings.max_history_turns :]
            if turn.get("role") and turn.get("content")
        ]
    if selected_entities:
        payload["selected_objects"] = [
            {"ifc_class": s.get("ifc_class"), "name": s.get("name")}
            for s in selected_entities[: settings.max_selected_entity_ids]
        ]
    if previous_scope is not None:
        payload["previous_result"] = previous_scope.summary()

    return {
        "manifest_json": _compact_manifest(manifest),
        "payload": payload,
        "cache_key": _cache_key(
            "binder", manifest, settings.get_binder_model(), settings.binder_reasoning_effort
        ),
    }


def build_correction_context(
    question: str,
    manifest: SemanticManifest,
    ledger: ConstraintLedger,
    previous_plan: Any,
    gate_failures: list[str],
    expanded: CandidateSlate,
    *,
    settings: Settings,
) -> dict[str, Any]:
    """Assemble the one-time corrective input (§4).

    Carries the same complete manifest and ledger, plus the previous binding, the
    typed gate failures, and expanded candidates around the failed items only.
    """
    payload: dict[str, Any] = {
        "question": question,
        "previous_binding": previous_plan.model_dump(mode="json")
        if hasattr(previous_plan, "model_dump")
        else previous_plan,
        "gate_failures": list(gate_failures),
        "constraint_ledger": ledger.to_payload(),
        "expanded_recommendations": [r.to_payload() for r in expanded.recommendations],
    }
    if expanded.coverage_notes:
        payload["model_limitations"] = list(expanded.coverage_notes)

    return {
        "manifest_json": _compact_manifest(manifest),
        "payload": payload,
        "cache_key": _cache_key(
            "correction",
            manifest,
            settings.get_correction_model(),
            settings.correction_reasoning_effort,
        ),
    }


def _cache_key(role: str, manifest: SemanticManifest, model: str, effort: str) -> str:
    """Key the prefix cache by everything that changes the stable prefix (§6).

    Role, model, and effort partition callers; source model, fingerprint, and
    manifest hash invalidate the moment the model or its semantics change; the
    prompt version is folded in via the role name changing with the prompt.
    """
    return ":".join(
        [
            role,
            model,
            effort,
            str(manifest.source_model_id),
            manifest.file_fingerprint[:16],
            manifest.content_hash[:16],
        ]
    )
