"""Viewer identities from the executed result parts (task26 §12.5, task28 §9).

Identities come from each part's declared `viewer_set` policy and the SAME
compiled predicate the results used — never from whichever predicate was
scanned first:

- requested: the matching answer entities;
- context: the contextual base set, only when policy explicitly allowed it;
- sample: exactly the one sample;
- graph_endpoints: the selected endpoint set;
- none / zero / unavailable / ambiguous: nothing, no fallback highlights.

task28 §9 removes the assumption that exactly ONE part is the visualization
authority. When the user asks for several highlightable sets, every requested
part contributes its exact identities and they are combined, deduplicated, under
one shared cap with truncation disclosed. The per-part identities are retained
so the delivered text, the result summary, the viewer class counts, and the
trace can be checked against each other.

Two safety rules survive the change. A zero, unavailable, or non-highlightable
part contributes nothing, so it can never cause an unrelated broader set to be
shown. And a contextual base set is only ever shown when no requested set exists
— a broader stand-in must never be silently mixed into exact identities.
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

_HIGHLIGHTABLE = (ResultStatusV2.EXACT, ResultStatusV2.PARTIAL)


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
    #: Which parts contributed, and how many identities each gave (§9). This is
    #: what makes answer/viewer/trace agreement checkable instead of assumed.
    part_global_ids: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_selection(self) -> bool:
        return bool(self.primary_global_ids)

    def contributing_part_ids(self) -> list[str]:
        return [p for p, ids in self.part_global_ids.items() if ids]

    def to_payload(self) -> dict[str, Any]:
        return {
            "returned": len(self.primary_global_ids),
            "total": self.viewer_matches_total,
            "truncated": self.viewer_matches_truncated,
            "context_only": self.is_context_only,
            "parts": {p: len(ids) for p, ids in self.part_global_ids.items()},
        }


def hydrate_viewer_v2(
    session: Session,
    parts: list[PartResultV2],
    visual_part_ids: list[str] | None,
    settings: Settings,
) -> ViewerHydrationV2:
    """Combine the identities of every requested highlightable part (§9)."""
    hydration = ViewerHydrationV2()
    selected = _select_parts(parts, visual_part_ids)
    if not selected:
        return hydration

    cap = getattr(settings, "max_viewer_global_ids", None) or getattr(
        settings, "max_viewer_match_ids", 2000
    )

    requested = [p for p in selected if p.viewer_policy != "context"]
    contextual = [p for p in selected if p.viewer_policy == "context"]
    # A contextual base set stands in for a set that could not be produced. It
    # is shown only when nothing exact was produced at all, so an exact answer
    # is never quietly widened by a stand-in.
    active = requested or contextual
    hydration.is_context_only = not requested and bool(contextual)

    seen: set[str] = set()
    combined: list[str] = []
    class_counts: dict[str, int] = {}
    grand_total = 0
    truncated = False

    for part in active:
        room = cap - len(combined)
        ids, part_total, statements = _identities_for(session, part, max(room, 0))
        hydration.statement_count += statements
        grand_total += part_total
        # Truncation is a property of each part's own retrieval, not of
        # deduplication: overlapping requested sets legitimately return fewer
        # combined identities than the sum of their totals.
        truncated = truncated or part_total > len(ids)
        kept: list[str] = []
        for global_id, ifc_class in ids:
            if global_id in seen:
                continue
            seen.add(global_id)
            kept.append(global_id)
            combined.append(global_id)
            class_counts[ifc_class] = class_counts.get(ifc_class, 0) + 1
        hydration.part_global_ids[part.part_id] = kept

    hydration.viewer_matches_total = grand_total
    hydration.viewer_matches_truncated = truncated
    hydration.class_counts = dict(
        sorted(class_counts.items(), key=lambda kv: -kv[1])
    )
    hydration.primary_global_ids = combined

    if hydration.is_context_only:
        hydration.context_global_ids = combined
        reason = next(
            (p.context_reason for p in contextual if p.context_reason),
            "a requested constraint could not be resolved",
        )
        hydration.warnings.append(
            "highlighted objects are the contextual base set, not the requested "
            "constrained set: " + reason
        )
    if hydration.viewer_matches_truncated:
        hydration.warnings.append(
            f"highlighting the first {len(combined)} of {grand_total} matching objects"
        )
    return hydration


def _identities_for(
    session: Session, part: PartResultV2, room: int
) -> tuple[list[tuple[str, str]], int, int]:
    """One part's exact identities, its true total, and statements spent."""
    if part.viewer_policy == "sample":
        if part.viewer_sample is None:
            return [], 0, 0
        return (
            [(part.viewer_sample.global_id, part.viewer_sample.ifc_class)],
            1,
            0,
        )

    where = part.viewer_where
    if where is None:
        return [], 0, 0

    total = int(
        session.execute(
            sa.select(sa.func.count()).select_from(_ET).where(where)
        ).scalar_one()
    )
    if room <= 0:
        # Still report the true total so truncation is disclosed honestly.
        return [], total, 1
    rows = session.execute(
        sa.select(_ET.c.global_id, _ET.c.ifc_class)
        .where(where)
        .order_by(_ET.c.id)
        .limit(room)
    ).all()
    return [(r[0], r[1]) for r in rows], total, 2


def _select_parts(
    parts: list[PartResultV2], visual_part_ids: list[str] | None
) -> list[PartResultV2]:
    """Every part that both asked to be shown and produced something to show."""
    eligible = [
        p
        for p in parts
        if p.viewer_policy not in ("none", "") and p.status in _HIGHLIGHTABLE
    ]
    if visual_part_ids:
        wanted = [p for p in eligible if p.part_id in set(visual_part_ids)]
        if wanted:
            return wanted
    return eligible
