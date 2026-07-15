"""Trusted browser-selection resolution (spec_v006 §10.4; Task 10 §5).

The frontend supplies IFC GlobalIds scoped by `active_source_model_id`; only
trusted backend code turns those into canonical entity IDs before any planner
context or selected-object retrieval. This module is that single, deterministic,
LLM-free, read-only bridge.

Rules enforced here:
- selected GlobalIds require an active model;
- trim, drop-empty, and stable-dedupe before resolution;
- every lookup is scoped to the active model (cross-model IDs never resolve);
- the deprecated internal `selected_entity_ids` integer path is retained only
  for backward compatibility and must NEVER override a conflicting GlobalId
  selection — disagreement is rejected (spec_v006 §10.4);
- unresolved IDs are reported as a bounded warning, not a crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.query.sql.entities import resolve_entities_by_global_ids


class SelectionConflictError(Exception):
    """Raised when a browser selection is invalid for the active model.

    Covers: selected GlobalIds with no active model, and GlobalId vs. deprecated
    integer-ID selections that disagree (spec_v006 §10.4 — never accept both
    representations when they conflict).
    """


@dataclass
class ResolvedSelection:
    entity_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_global_ids(raw: list[str]) -> list[str]:
    """Trim, drop empties, and stable-dedupe while preserving request order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in raw:
        trimmed = value.strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        out.append(trimmed)
    return out


def resolve_selection(
    session,
    active_model_id: int | None,
    global_ids: list[str],
    deprecated_entity_ids: list[int],
    max_ids: int,
    *,
    resolver=resolve_entities_by_global_ids,
) -> ResolvedSelection:
    """Resolve a browser selection to canonical entity IDs (Task 10 §5).

    `resolver` is injectable for offline unit tests. Returns resolved entity IDs
    in request order plus any bounded warnings; raises SelectionConflictError for
    a no-active-model GlobalId selection or a GlobalId/integer-ID disagreement.
    """
    gids = normalize_global_ids(global_ids)

    # No GlobalIds supplied: fall back to the deprecated internal integer path
    # (backward compatibility only), bounded to the selection cap.
    if not gids:
        return ResolvedSelection(entity_ids=list(deprecated_entity_ids[:max_ids]))

    if active_model_id is None:
        raise SelectionConflictError("selected GlobalIds require an active model")

    rows = resolver(session, active_model_id, gids[:max_ids])
    by_gid = {r.global_id: r.id for r in rows}
    resolved_ids = [by_gid[g] for g in gids[:max_ids] if g in by_gid]
    unresolved = [g for g in gids[:max_ids] if g not in by_gid]

    warnings: list[str] = []
    if unresolved:
        warnings.append(
            f"{len(unresolved)} selected object(s) could not be resolved in the active "
            "model and were ignored"
        )

    # GlobalIds are the authoritative browser contract: if deprecated integer IDs
    # were also supplied and disagree, reject rather than let them override.
    if deprecated_entity_ids and set(deprecated_entity_ids) != set(resolved_ids):
        raise SelectionConflictError(
            "selected_global_ids and selected_entity_ids disagree; supply GlobalIds only"
        )

    return ResolvedSelection(entity_ids=resolved_ids, warnings=warnings)
