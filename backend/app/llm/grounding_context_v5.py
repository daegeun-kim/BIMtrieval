"""Input assembly for the v5 grounding, corrective, and answer calls (task30 §4).

The grounding call sees:

- the compact, COMPLETE capability projection of the active model as the stable
  cacheable prefix — the escape path that keeps v3's candidate-omission problem
  from returning, since any id in it may be selected;
- the resolved request as context only;
- the SLOTS, each carrying what kind of concept it needs, the user's words for
  it, and the comparison, value, unit, negation, Boolean group, direction and
  far-end already decided;
- per-slot ranked candidates the backend matched to that slot's words.

It does NOT see the raw conversation, and it is no longer asked to build a plan.
The structure is fixed before the call, so the payload is a list of small
questions rather than a request to reconstruct the user's logic from a lexical
ledger — which is what made the v5 original lose meaning at this boundary.

The grounding and corrective calls share an IDENTICAL stable prefix, so a
correction re-sends only its small failure payload.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import Settings
from app.query.binding.intent import intent_payload
from app.query.binding.obligations import PlanSkeleton
from app.query.binding.recall import RecallResult
from app.query.semantic.manifest_v002.projection import BinderProjection

__all__ = [
    "build_grounding_context_v5",
    "build_correction_context_v5",
    "stable_prefix_cache_key",
]

#: Ranked candidates offered per slot. High enough for real recall, small enough
#: that the payload stays a list of short questions.
MAX_CANDIDATES_PER_SLOT = 8


def build_grounding_context_v5(
    intent: Any,
    projection: BinderProjection,
    skeleton: PlanSkeleton,
    recall: RecallResult,
    *,
    settings: Settings,
    source_model_id: int,
    candidates_by_slot: dict[str, list[dict[str, Any]]] | None = None,
    selected_entities: list[dict[str, Any]] | None = None,
    previous_scope: Any | None = None,
) -> dict[str, Any]:
    candidates_by_slot = candidates_by_slot or {}
    slots: list[dict[str, Any]] = []
    for slot in skeleton.slots:
        record = slot.to_payload()
        offered = candidates_by_slot.get(slot.slot_id, [])
        if offered:
            record["candidates"] = offered[:MAX_CANDIDATES_PER_SLOT]
        slots.append(record)

    payload: dict[str, Any] = {
        # Context only: the structure below is what must be bound.
        "resolved_request": intent.normalized_request,
        "parts": [p.to_payload() for p in skeleton.parts],
        "slots": slots,
    }

    value_matches = [
        link.to_payload() | {"for": requirement_id}
        for requirement_id, links in sorted(recall.value_links.items())
        for link in links[:4]
    ]
    if value_matches:
        payload["value_matches"] = value_matches[:24]

    scopes: list[dict[str, Any]] = [{"kind": "active_model"}]
    if selected_entities:
        scopes.append({"kind": "selected_objects", "count": len(selected_entities)})
    if previous_scope is not None:
        scopes.append({"kind": "previous_result", "summary": previous_scope.summary()})
    payload["available_scopes"] = scopes

    return {
        "projection_json": projection.json_text,
        "payload": payload,
        "cache_key": stable_prefix_cache_key(
            "ground",
            projection,
            source_model_id,
            settings.get_binder_model(),
            settings.binder_reasoning_effort,
        ),
    }


def build_correction_context_v5(
    intent: Any,
    projection: BinderProjection,
    skeleton: PlanSkeleton,
    failures: list[dict[str, Any]],
    expanded: dict[str, Any],
    *,
    settings: Settings,
    source_model_id: int,
    previous_bindings: Any = None,
) -> dict[str, Any]:
    """The one-time corrective input (task30 §4).

    Carries the same fixed structure, the bindings that failed, the exact reason
    each failed, and expanded candidates for those slots alone. A repair may
    change an identity; it can no longer change the request, because the request
    is not expressed in anything this call returns.
    """
    payload: dict[str, Any] = {
        "resolved_request": intent.normalized_request,
        "intent": intent_payload(intent),
        "parts": [p.to_payload() for p in skeleton.parts],
        "previous_bindings": (
            previous_bindings.model_dump(mode="json")
            if hasattr(previous_bindings, "model_dump")
            else previous_bindings
        ),
        "failures": failures[:16],
        "expanded_candidates": expanded.get("candidates", [])[:24],
        "expanded_value_matches": expanded.get("value_matches", [])[:12],
        "invalid_fragments": expanded.get("invalid_fragments", [])[:8],
    }
    return {
        "projection_json": projection.json_text,
        "payload": payload,
        "cache_key": stable_prefix_cache_key(
            "ground",
            projection,
            source_model_id,
            settings.get_correction_model(),
            settings.correction_reasoning_effort,
        ),
    }


def stable_prefix_cache_key(
    role_family: str,
    projection: BinderProjection,
    source_model_id: int,
    model: str,
    effort: str,
) -> str:
    return ":".join(
        [
            role_family,
            model,
            effort,
            str(source_model_id),
            projection.projection_hash[:16],
        ]
    )
