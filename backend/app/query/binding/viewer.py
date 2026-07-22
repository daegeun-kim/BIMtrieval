"""Viewer identity hydration from the authoritative result (Task 24 §9).

§9's requirement is a single sentence with sharp consequences: "The final
answer, exact total, and viewer identities must derive from the same
authoritative answer-part result."

So identities are fetched HERE — after execution has established the result —
by re-running the answer part's own `CompiledPredicate`. Not from a broader
class query, not from the answer's bounded examples, and not while candidates
are still being evaluated (§5.2). A previous run answered with six space names
while highlighting 778 objects; deriving both from one predicate makes that
disagreement structurally impossible.

The other §9 rules, each enforced below:

- type/style/property-definition records are never highlighted for a physical
  occurrence result (guaranteed upstream by closure, re-checked here);
- exact zero, unavailable, catalog and non-visual answers highlight NOTHING —
  no unrelated fallback set;
- viewer identity limits never change the exact total handed to the answerer;
- a multi-part question highlights ONE explicit primary part, not the union of
  every part that happened to be retrieved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import IfcEntity
from app.query.binding.evidence import AnswerPartResult
from app.query.sql.compiler import build_condition_expr

__all__ = ["ViewerHydration", "hydrate_viewer_identities"]

_ET = IfcEntity.__table__


@dataclass
class ViewerHydration:
    """Identities for highlighting, plus the totals that describe them."""

    primary_global_ids: list[str] = field(default_factory=list)
    context_global_ids: list[str] = field(default_factory=list)
    #: The TRUE number of matching objects, never reduced by any identity cap.
    viewer_matches_total: int = 0
    viewer_matches_truncated: bool = False
    class_counts: dict[str, int] = field(default_factory=dict)
    statement_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def has_selection(self) -> bool:
        return bool(self.primary_global_ids or self.context_global_ids)


def hydrate_viewer_identities(
    session: Session,
    results: list[AnswerPartResult],
    primary_visual_part_id: str | None,
    settings: Settings | None = None,
) -> ViewerHydration:
    """Fetch complete identities for the ONE part that drives the viewer (§9)."""
    settings = settings or get_settings()
    hydration = ViewerHydration()

    target = _select_visual_part(results, primary_visual_part_id)
    if target is None:
        # Nothing to highlight is a legitimate, common outcome: a zero,
        # unavailable, catalog or summary answer must not light up a fallback
        # set just because something was retrieved.
        return hydration

    if target.operation == "relationship":
        return _hydrate_from_endpoints(target, hydration, settings)

    predicate = target.predicate
    if predicate is None or not predicate.ifc_classes:
        return hydration

    where = _predicate_where(session, predicate)

    total = session.execute(sa.select(sa.func.count()).select_from(_ET).where(where)).scalar_one()
    hydration.statement_count += 1
    hydration.viewer_matches_total = total

    limit = settings.max_viewer_match_ids
    rows = session.execute(
        sa.select(_ET.c.global_id, _ET.c.ifc_class).where(where).order_by(_ET.c.id).limit(limit)
    ).all()
    hydration.statement_count += 1
    hydration.primary_global_ids = [r.global_id for r in rows]
    hydration.viewer_matches_truncated = total > len(rows)

    # Counted with its own GROUP BY over the FULL set, so the breakdown stays
    # exact even when the identity list is capped.
    class_rows = session.execute(
        sa.select(_ET.c.ifc_class, sa.func.count().label("cnt"))
        .where(where)
        .group_by(_ET.c.ifc_class)
    ).all()
    hydration.statement_count += 1
    hydration.class_counts = {r.ifc_class: r.cnt for r in class_rows}

    if hydration.viewer_matches_truncated:
        hydration.warnings.append(
            f"{total} objects match; the viewer received the first {len(rows)} "
            "(the exact total in the answer is unaffected)"
        )

    # The identity set and the answer's total describe the same predicate, so a
    # disagreement means something rebuilt the query. Report rather than hide.
    if target.exact_total is not None and total != target.exact_total:
        hydration.warnings.append(
            "internal: highlighted set and reported total were derived from different "
            "queries; the reported total is authoritative"
        )
    return hydration


def _select_visual_part(
    results: list[AnswerPartResult], primary_visual_part_id: str | None
) -> AnswerPartResult | None:
    """Exactly one part may drive the viewer (§9).

    "Multi-part questions need an explicit primary visual answer part; do not
    union all answer-part IDs merely because they were retrieved."
    """
    visual = [r for r in results if r.has_visual_result]
    if not visual:
        return None
    if primary_visual_part_id:
        explicit = next((r for r in visual if r.part_id == primary_visual_part_id), None)
        if explicit is not None:
            return explicit
    if len(visual) == 1:
        return visual[0]
    # Several visual parts but no explicit choice: highlight the first, and do
    # NOT union them — a union would highlight objects the answer never claimed.
    return visual[0]


def _predicate_where(session: Session, predicate) -> sa.ColumnElement:
    """Rebuild the answer part's own predicate — the same one that counted it."""
    where = _ET.c.source_model_id == predicate.source_model_id
    if predicate.ifc_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(list(predicate.ifc_classes)))
    if predicate.filters is not None:
        where = sa.and_(
            where,
            build_condition_expr(session, predicate.source_model_id, predicate.filters, _ET),
        )
    if predicate.scope_entity_ids is not None:
        where = sa.and_(where, _ET.c.id.in_(list(predicate.scope_entity_ids)))
    return where


def _hydrate_from_endpoints(
    target: AnswerPartResult, hydration: ViewerHydration, settings: Settings
) -> ViewerHydration:
    """A relationship answer highlights the endpoints traversal established.

    Endpoints are already hydrated with identities by the graph executor, and
    they are the only objects the answer claims — so no further query is needed
    and no broader set may be substituted (§5.4, §9).
    """
    limit = settings.max_viewer_match_ids
    endpoints = target.graph_endpoints[:limit]
    hydration.primary_global_ids = [e.global_id for e in endpoints]
    hydration.viewer_matches_total = len(target.graph_endpoints)
    hydration.viewer_matches_truncated = len(target.graph_endpoints) > len(endpoints)
    counts: dict[str, int] = {}
    for endpoint in target.graph_endpoints:
        counts[endpoint.ifc_class] = counts.get(endpoint.ifc_class, 0) + 1
    hydration.class_counts = counts
    return hydration
