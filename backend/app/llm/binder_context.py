"""Input assembly for LLM call 1, the semantic binder (Task 24 §2.1).

§2.1 lists exactly what the first model may see:

- the current user question;
- bounded conversational text required to resolve references;
- active model / catalog scope;
- selected-object summaries when present;
- typed previous-result scope when present;
- the compact request-specific candidate slate;
- the small output schema and its rules (carried by the prompt).

And what it may not: full canonical JSON, full model vocabulary, database rows,
raw embeddings, candidate SQL results, or viewer identity lists.

This module is the single place that boundary is enforced, and it is enforced by
CONSTRUCTION — the payload is assembled from a fixed set of fields, so there is
no path by which a database row or an identity list could arrive. That matters
more than a prompt instruction: the previous architecture's isolation was also
stated in a prompt, and drifted.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import Settings
from app.query.binding.schemas import CandidateSlate

__all__ = ["build_binder_context"]


def build_binder_context(
    question: str,
    slate: CandidateSlate,
    *,
    settings: Settings,
    history: list[dict[str, str]] | None = None,
    selected_entities: list[dict[str, Any]] | None = None,
    previous_scope: Any | None = None,
    active_source_model_id: int | None = None,
) -> dict[str, Any]:
    """Assemble the bounded binder payload (§2.1)."""
    context: dict[str, Any] = {
        "question": question,
        "scope": "active_model" if active_source_model_id is not None else "model_catalog",
        "candidates": slate.to_prompt_payload(),
    }

    if history:
        # Bounded, and only for reference resolution ("how many of those…").
        context["recent_turns"] = [
            {"role": turn["role"], "content": str(turn["content"])[:400]}
            for turn in history[-settings.max_history_turns :]
            if turn.get("role") and turn.get("content")
        ]

    if selected_entities:
        # The user's own selection is legitimate input. Compact identity only —
        # never the full entity record.
        context["selected_objects"] = [
            {"ifc_class": s.get("ifc_class"), "name": s.get("name")}
            for s in selected_entities[: settings.max_selected_entity_ids]
        ]

    if previous_scope is not None:
        # A DESCRIPTION of the previous result, never its ids. The binder only
        # needs to know a previous scope exists and what it was about; the
        # backend re-executes the stored predicate if the binding inherits it.
        context["previous_result"] = previous_scope.summary()

    return context
