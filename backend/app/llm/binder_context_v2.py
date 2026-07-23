"""Input assembly for the v4 binder, corrective, and answer calls (task26 §5.8, §8.5).

The binder sees exactly:

- the compact, COMPLETE binder projection of the active model as the stable
  cacheable prefix (instructions);
- the small dynamic request: the resolved requirement ledger, bounded per-slot
  recommendations, exact value matches, available scopes, and bounded
  history/selection metadata.

There is no duplicate complete-universe serialization: the projection IS the
universe, and the dynamic payload never re-lists it (§5.8). The initial and
corrective calls share an IDENTICAL stable prefix — same prompt-compatible
projection text, same cache key family — so a correction re-sends only its
small failure payload (§8.5).
"""

from __future__ import annotations

from typing import Any

from app.config.settings import Settings
from app.query.binding.ledger_v2 import LedgerV2
from app.query.binding.recall import RecallResult
from app.query.semantic.manifest_v002.projection import BinderProjection

__all__ = [
    "build_binder_context_v2",
    "build_correction_context_v2",
    "stable_prefix_cache_key",
]


def build_binder_context_v2(
    question: str,
    projection: BinderProjection,
    ledger: LedgerV2,
    recall: RecallResult,
    *,
    settings: Settings,
    source_model_id: int,
    history: list[dict[str, str]] | None = None,
    selected_entities: list[dict[str, Any]] | None = None,
    previous_scope: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question,
        "requirement_ledger": ledger.to_payload(),
        "recommendations": [r.to_payload() for r in recall.recommendations],
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

    return {
        "projection_json": projection.json_text,
        "payload": payload,
        "cache_key": stable_prefix_cache_key(
            "bind",
            projection,
            source_model_id,
            settings.get_binder_model(),
            settings.binder_reasoning_effort,
        ),
    }


def build_correction_context_v2(
    question: str,
    projection: BinderProjection,
    previous_plan: Any,
    failures: list[dict[str, Any]],
    expanded: dict[str, Any],
    *,
    settings: Settings,
    source_model_id: int,
) -> dict[str, Any]:
    """The one-time corrective input (§8.5, §9.4).

    Carries the ORIGINAL plan, the exact mechanical failures with affected
    requirement/node ids, and a bounded expanded candidate/value set for only
    those failures. Never a duplicate universe: the stable prefix is the same
    projection the initial call used.
    """
    payload: dict[str, Any] = {
        "question": question,
        "previous_plan": (
            previous_plan.model_dump(mode="json")
            if hasattr(previous_plan, "model_dump")
            else previous_plan
        ),
        "failures": failures[:16],
        "keep": expanded.get("keep", []),
        "expanded_candidates": expanded.get("candidates", [])[:24],
        "expanded_value_matches": expanded.get("value_matches", [])[:12],
    }
    return {
        "projection_json": projection.json_text,
        "payload": payload,
        # The SAME family as the initial call: role/model/effort partition the
        # provider cache, but the projection prefix text is identical, so the
        # provider's prefix cache still covers it when model+effort match.
        "cache_key": stable_prefix_cache_key(
            "bind",
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
