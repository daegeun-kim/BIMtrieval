"""Presentation payload for the primary visual answer part (task26 §1.1).

This module exists to make one guarantee structural rather than promised: the
explanation panel shows *only* what the pipeline already established for the
accepted answer.

    build_answer_explanation(result, hydration, ...) -> AnswerExplanation | None

There is no `Session` parameter and no import of any query/execution module, so
this code **cannot** issue a statement, recompute a breakdown, re-interpret the
question, or reach the LLM. It reads finished objects and copies bounded fields
out of them. Everything it can express — totals, class breakdown, distribution
buckets, aggregate coverage, limitation, known/unknown split, identities — was
computed before it ran.

Two rules are load-bearing:

- **Never invent subgroup membership.** A group is offered as selectable only
  when its GlobalIds are an authoritative subset of the identities the viewer
  already received. Distribution buckets are grouped counts with no identity
  set, so they are shown and never made selectable (§5).
- **Never let a shown count pass for a true count.** `exact_count` on a group
  and `true_result_count` on the payload stay at their real values even when the
  identity list was capped, and `truncated`/`identities_truncated` say so.
"""

from __future__ import annotations

from app.api.schemas.response import (
    AnswerExplanation,
    ExplanationAggregate,
    ExplanationBucket,
    ExplanationGroup,
    ExplanationPresentation,
    ExplanationRow,
)
from app.query.binding.evidence import AnswerPartResult, ResultStatus
from app.query.binding.viewer import ViewerHydration
from app.shared.types import AnswerBasis

__all__ = ["build_answer_explanation", "select_visual_result"]

#: Bounds for the presentation payload. The row/bucket sources are already
#: bounded upstream; these are a second, explicit ceiling so the panel's payload
#: cannot grow with a future change to those limits.
MAX_EXPLANATION_ROWS = 50
MAX_EXPLANATION_BUCKETS = 24
MAX_EXPLANATION_GROUPS = 24

#: Operation -> visualization (§4.1). Anything unlisted falls back to a table,
#: which needs nothing beyond the bounded example rows every part carries.
_PRESENTATION_BY_OPERATION = {
    "count": ExplanationPresentation.METRIC,
    "existence": ExplanationPresentation.METRIC,
    "list": ExplanationPresentation.TABLE,
    "sample_detail": ExplanationPresentation.TABLE,
    "group_distribution": ExplanationPresentation.DISTRIBUTION,
    "aggregate": ExplanationPresentation.AGGREGATE,
    "extremum": ExplanationPresentation.AGGREGATE,
    "relationship": ExplanationPresentation.RELATIONSHIP,
}


def select_visual_result(
    results: list[AnswerPartResult], primary_visual_part_id: str | None
) -> AnswerPartResult | None:
    """The ONE part the viewer is showing — the same choice `viewer.py` made.

    A multi-part question highlights one explicit primary visual part, so the
    explanation must describe that part and not `results[0]`; otherwise the card
    could narrate one answer part while the viewer emphasizes another (§4.1).
    """
    visual = [r for r in results if r.has_visual_result]
    if not visual:
        return None
    if primary_visual_part_id:
        explicit = next((r for r in visual if r.part_id == primary_visual_part_id), None)
        if explicit is not None:
            return explicit
    return visual[0]


def build_answer_explanation(
    result: AnswerPartResult | None,
    hydration: ViewerHydration,
    answer_basis: AnswerBasis,
) -> AnswerExplanation | None:
    """Build the bounded payload, or `None` when there is nothing to explain.

    Returns `None` for every case in which the card must not open: no visual
    part, and no highlighted objects. A clarification, zero, unavailable or
    ambiguous answer reaches neither branch with a highlight, so no stale
    explanation can be produced for it.
    """
    if result is None or not result.has_visual_result:
        return None
    if not hydration.primary_global_ids:
        return None

    presentation = _presentation_for(result)
    groups = _groups(result, hydration)

    return AnswerExplanation(
        part_id=result.part_id,
        request_label=result.request_text,
        operation=result.operation,
        result_status=result.status.value,
        presentation=presentation,
        answer_basis=answer_basis,
        interpretation=result.interpretation or None,
        retrieval_modes=[m.value for m in result.modes_executed],
        exact_total=result.exact_total,
        class_breakdown=dict(result.class_breakdown or hydration.class_counts),
        distribution=_buckets(result),
        aggregate=_aggregate(result),
        relationship_endpoint_total=(
            len(result.graph_endpoints) if result.operation == "relationship" else None
        ),
        limitation=result.limitation,
        known_parts=list(result.known_parts)[:10],
        unknown_parts=list(result.unknown_parts)[:10],
        shown_identity_count=len(hydration.primary_global_ids),
        # The identity cap never reduces the reported total (§5): prefer the
        # hydration's own count of matching objects, and fall back to the part's
        # exact total rather than to the length of the capped identity list.
        true_result_count=(
            hydration.viewer_matches_total
            or result.exact_total
            or len(hydration.primary_global_ids)
        ),
        identities_truncated=hydration.viewer_matches_truncated,
        groups=groups,
        rows=_rows(result),
    )


def _presentation_for(result: AnswerPartResult) -> ExplanationPresentation:
    """A partial result is presented as such regardless of its operation — the
    known/unknown split is the point of the card in that case (§4.1)."""
    if result.status is ResultStatus.PARTIAL:
        return ExplanationPresentation.PARTIAL
    return _PRESENTATION_BY_OPERATION.get(result.operation, ExplanationPresentation.TABLE)


def _groups(result: AnswerPartResult, hydration: ViewerHydration) -> list[ExplanationGroup]:
    """Selectable class groups, partitioned from the identities already sent.

    Membership comes from the class each identity was retrieved with, so a group
    is a literal subset of the highlighted set. When no class information
    accompanied the identities, no group is offered at all — an unselectable
    card is correct; a guessed subgroup is not.
    """
    if not hydration.primary_identities:
        return []

    shown: dict[str, list[str]] = {}
    for identity in hydration.primary_identities:
        shown.setdefault(identity.ifc_class, []).append(identity.global_id)

    exact = result.class_breakdown or hydration.class_counts
    groups = [
        ExplanationGroup(
            key=ifc_class,
            label=ifc_class,
            exact_count=exact.get(ifc_class),
            shown_count=len(global_ids),
            truncated=(ifc_class in exact and exact[ifc_class] > len(global_ids)),
            global_ids=global_ids,
        )
        for ifc_class, global_ids in shown.items()
    ]
    # Largest first, so the panel's ordering is deterministic and matches how a
    # reader scans a breakdown.
    groups.sort(key=lambda g: (-(g.exact_count or g.shown_count), g.key))
    return groups[:MAX_EXPLANATION_GROUPS]


def _buckets(result: AnswerPartResult) -> list[ExplanationBucket]:
    return [
        ExplanationBucket(
            key=b.key if b.key is not None else "(not recorded)", count=b.count, value=b.value
        )
        for b in result.distribution[:MAX_EXPLANATION_BUCKETS]
    ]


def _aggregate(result: AnswerPartResult) -> ExplanationAggregate | None:
    agg = result.aggregate
    if agg is None:
        return None
    return ExplanationAggregate(
        function=agg.function,
        value=agg.value,
        unit=agg.unit,
        matched_count=agg.matched_count,
        coverage_count=agg.coverage_count,
        complete=agg.complete,
    )


def _rows(result: AnswerPartResult) -> list[ExplanationRow]:
    """Bounded rows from objects the part already retrieved.

    A relationship answer's rows are its traversal endpoints — the only objects
    that answer claims — and every other operation uses its bounded examples.
    """
    source = result.graph_endpoints if result.operation == "relationship" else result.examples
    return [
        ExplanationRow(
            global_id=e.global_id,
            ifc_class=e.ifc_class,
            name=e.name,
            storey_name=e.storey_name,
        )
        for e in source[:MAX_EXPLANATION_ROWS]
    ]
