"""Complete post-answer viewer-identity hydration (Task 17 §9).

After the answerer accepts direct primary viewer groups, deterministically
retrieve EVERY identity of each accepted viewer group (no 2,000-ID cap) and
build the viewer action. Supporting/context groups remain answer evidence but
are not highlighted. Genuinely missing GlobalIds
(a matched entity with no usable GlobalId) are reported separately — that is not
truncation. This is read-only DB work, not another LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.query.hybrid.groups.decision import GroupDecision
from app.query.hybrid.groups.execute import all_identities
from app.viewer.actions import (
    SelectionAction,
    ViewerActions,
    build_default_viewer_actions,
    build_viewer_actions,
)


@dataclass
class ViewerHydration:
    primary_global_ids: list[str] = field(default_factory=list)
    context_global_ids: list[str] = field(default_factory=list)
    viewer_matches_total: int = 0
    missing_identity_count: int = 0
    accepted_primary_entity_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def viewer_actions(self) -> ViewerActions:
        if not self.primary_global_ids and not self.context_global_ids:
            return build_default_viewer_actions()
        return build_viewer_actions(
            selection_action=SelectionAction.SELECT_AND_FIT,
            primary_global_ids=self.primary_global_ids,
            context_global_ids=self.context_global_ids,
            viewer_matches_total=self.viewer_matches_total,
            viewer_matches_truncated=False,  # complete hydration — never truncated (§9)
        )


def hydrate_accepted_viewer_identities(
    session: Session, decision: GroupDecision, source_model_id: int
) -> ViewerHydration:
    result = ViewerHydration()
    seen: set[str] = set()
    missing = 0

    for g in decision.viewer_primary:
        ident = all_identities(session, g.predicate, source_model_id)
        missing += ident.missing_count
        for gid in ident.global_ids:
            if gid not in seen:
                seen.add(gid)
                result.primary_global_ids.append(gid)
    result.viewer_matches_total = len(result.primary_global_ids)
    result.missing_identity_count = missing
    # Follow-up state stores accepted primary group representative entity ids.
    for g in decision.accepted_primary:
        result.accepted_primary_entity_ids.extend(e.entity_id for e in g.representative_entities)
    if missing:
        result.warnings.append(
            f"{missing} matched objects have no usable viewer GlobalId (not truncation)"
        )
    return result
