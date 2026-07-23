"""Viewer identities from the typed viewer set (task26 §12.5).

Identities come from each part's declared `viewer_set` policy and the SAME
compiled predicate the results used — never from whichever predicate was
scanned first:

- requested: the matching answer entities;
- context: the contextual base set, only when policy explicitly allowed it;
- sample: exactly the one sample;
- graph_endpoints: the selected endpoint set;
- none / zero / unavailable / ambiguous: nothing, no fallback highlights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.db.models import IfcEntity
from app.query.binding.results_v2 import PartResultV2, ResultStatusV2

__all__ = ["ViewerHydrationV2", "hydrate_viewer_v2"]

_ET = IfcEntity.__table__


@dataclass
class ViewerHydrationV2:
    primary_global_ids: list[str] = field(default_factory=list)
    context_global_ids: list[str] = field(default_factory=list)
    viewer_matches_total: int = 0
    viewer_matches_truncated: bool = False
    is_context_only: bool = False
    class_counts: dict[str, int] = field(default_factory=dict)
    statement_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def has_selection(self) -> bool:
        return bool(self.primary_global_ids)


def hydrate_viewer_v2(
    session: Session,
    parts: list[PartResultV2],
    primary_visual_part_id: str | None,
    settings: Settings,
) -> ViewerHydrationV2:
    hydration = ViewerHydrationV2()
    target = _select_part(parts, primary_visual_part_id)
    if target is None:
        return hydration

    if target.status not in (ResultStatusV2.EXACT, ResultStatusV2.PARTIAL):
        return hydration
    policy = target.viewer_policy
    if policy in ("none", ""):
        return hydration

    if policy == "sample":
        if target.viewer_sample is not None:
            hydration.primary_global_ids = [target.viewer_sample.global_id]
            hydration.viewer_matches_total = 1
            hydration.class_counts = {target.viewer_sample.ifc_class: 1}
        return hydration

    where = target.viewer_where
    if where is None:
        return hydration
    cap = settings.max_viewer_global_ids if hasattr(settings, "max_viewer_global_ids") else 2000

    total = session.execute(sa.select(sa.func.count()).select_from(_ET).where(where)).scalar_one()
    rows = session.execute(
        sa.select(_ET.c.global_id, _ET.c.ifc_class).where(where).order_by(_ET.c.id).limit(cap)
    ).all()
    hydration.statement_count += 2

    global_ids = [r[0] for r in rows]
    hydration.viewer_matches_total = int(total)
    hydration.viewer_matches_truncated = total > len(global_ids)
    class_counts: dict[str, int] = {}
    for _gid, ifc_class in rows:
        class_counts[ifc_class] = class_counts.get(ifc_class, 0) + 1
    hydration.class_counts = dict(sorted(class_counts.items(), key=lambda kv: -kv[1]))

    if policy == "context":
        hydration.context_global_ids = global_ids
        hydration.primary_global_ids = global_ids
        hydration.is_context_only = True
        hydration.warnings.append(
            "highlighted objects are the contextual base set, not the requested "
            "constrained set: " + (target.context_reason or "a requested constraint is unavailable")
        )
    else:
        hydration.primary_global_ids = global_ids
    if hydration.viewer_matches_truncated:
        hydration.warnings.append(
            f"highlighting the first {len(global_ids)} of {total} matching objects"
        )
    return hydration


def _select_part(
    parts: list[PartResultV2], primary_visual_part_id: str | None
) -> PartResultV2 | None:
    if primary_visual_part_id:
        explicit = next((p for p in parts if p.part_id == primary_visual_part_id), None)
        if explicit is not None:
            return explicit
    candidates = [p for p in parts if p.viewer_policy not in ("none", "") and p.is_answerable]
    return candidates[0] if candidates else None
