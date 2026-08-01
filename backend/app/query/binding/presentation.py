"""Presentation payload for the primary visual answer part (task29 §2).

This module exists to make one guarantee structural rather than promised: the
explanation panel shows *only* what the pipeline already established for the
accepted answer.

    build_answer_explanation(result, hydration, ...) -> AnswerExplanation | None

There is no `Session` parameter and no import of any query/execution module, so
this code **cannot** issue a statement, recompute a breakdown, re-interpret the
question, or reach the LLM. It reads finished objects and copies bounded fields
out of them.

**Task 29 narrowed what qualifies.** The panel is no longer a card that opens for
every highlighted answer with whatever visual its operation suggested. There are
exactly three presentation families — a bounded scrollable table, a compact
horizontal bar chart, and a grouped node-link diagram — and a result whose
operation supports none of them returns `None` so the original full-height chat
layout stays. The former standalone metric, aggregate, relationship-metric and
partial-split visuals are gone: a scalar restated as a big number beside the
prose that already stated it supplemented nothing.

Four rules are load-bearing:

- **One deterministic decision, made here.** The backend owns presentation
  selection; the frontend renders the declared presentation and never infers one
  from prose, operation names or row counts (§2).
- **`partial` is a modifier, not a visualization.** It keeps the base
  operation's presentation and shows its limitation and known/unknown split in
  the information region. If the base operation does not qualify, partial status
  does not open a panel by itself (§2).
- **Never invent subgroup membership.** A group or graph node is offered as
  selectable only when its GlobalIds are an authoritative subset of the
  identities the viewer already received. Distribution buckets are grouped
  counts with no identity set, so they are shown and never made selectable (§4).
- **Never let a shown count pass for a true count.** `exact_count` on a group
  and `true_result_count` on the payload stay at their real values even when the
  identity list was capped, and `truncated`/`identities_truncated` say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.api.schemas.response import (
    AnswerExplanation,
    ExplanationAggregate,
    ExplanationBucket,
    ExplanationGraph,
    ExplanationGroup,
    ExplanationPresentation,
    ExplanationRow,
)
from app.query.binding.evidence import AnswerPartResult, ResultStatus
from app.query.binding.topology import build_relationship_graph
from app.query.binding.viewer import ViewerHydration
from app.shared.types import AnswerBasis

__all__ = ["build_answer_explanation", "select_visual_result"]

#: Bounds for the presentation payload. The row/bucket sources are already
#: bounded upstream; these are a second, explicit ceiling so the panel's payload
#: cannot grow with a future change to those limits.
#:
#: Task 31 §4.1 replaced the former terminal 50-row ceiling: every authoritative
#: row the response's hydrated identities already represent is made available to
#: the frontend, which displays them 50 at a time. The row list is therefore
#: bounded by VIEWER HYDRATION, not by a display quantum — but it is still
#: bounded, and this constant mirrors `Settings.max_viewer_match_ids` (2000) so
#: the payload can never become an unbounded result transport even if that
#: setting were raised. `true_result_count` and `identities_truncated` stay
#: independent of it, so a capped list can never read as the complete result.
MAX_EXPLANATION_ROWS = 2000
MAX_EXPLANATION_BUCKETS = 24
MAX_EXPLANATION_GROUPS = 24

#: Statuses that may open the panel at all (§2). `zero`, `unavailable` and
#: `ambiguous` never do — there is no authoritative structured result to present.
_PRESENTABLE_STATUSES = (ResultStatus.EXACT, ResultStatus.PARTIAL)


@dataclass
class _Choice:
    """The one presentation this result's operation and data support."""

    presentation: ExplanationPresentation
    rows: list[ExplanationRow] = field(default_factory=list)
    buckets: list[ExplanationBucket] = field(default_factory=list)
    graph: ExplanationGraph | None = None
    fallback_reason: str | None = None
    #: Whether an existing class partition is worth showing beside the table.
    show_groups: bool = False


def select_visual_result(
    results: list[AnswerPartResult], primary_visual_part_id: str | None
) -> AnswerPartResult | None:
    """The ONE part the viewer is showing — the same choice `viewer.py` made.

    A multi-part question highlights one explicit primary visual part, so the
    explanation must describe that part and not `results[0]`; unrelated answer
    parts are never unioned to cross a visualization threshold (§2).
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
    """Build the bounded payload, or `None` when no presentation qualifies.

    The four gate conditions of §2, in order: a designated primary visual part
    exists; its status is `exact` or `partial`; it has a non-empty current
    query-result highlight; and its operation/data maps to a supported
    presentation with authoritative, non-empty data. A clarification, zero,
    unavailable or ambiguous answer fails one of the first three, so no stale
    explanation can be produced for it.
    """
    if result is None or not result.has_visual_result:
        return None
    if result.status not in _PRESENTABLE_STATUSES:
        return None
    if not hydration.primary_global_ids:
        return None

    choice = _choose(result, hydration)
    if choice is None:
        return None

    return AnswerExplanation(
        part_id=result.part_id,
        request_label=result.request_text,
        operation=result.operation,
        result_status=result.status.value,
        presentation=choice.presentation,
        answer_basis=answer_basis,
        interpretation=result.interpretation or None,
        retrieval_modes=[m.value for m in result.modes_executed],
        exact_total=result.exact_total,
        class_breakdown=dict(result.class_breakdown or hydration.class_counts),
        distribution=choice.buckets,
        aggregate=_aggregate(result),
        relationship_endpoint_total=(
            len(result.graph_endpoints) if result.operation == "relationship" else None
        ),
        graph=choice.graph,
        presentation_fallback_reason=choice.fallback_reason,
        chart_unit=_chart_unit(result, choice),
        limitation=result.limitation,
        known_parts=list(result.known_parts)[:10],
        unknown_parts=list(result.unknown_parts)[:10],
        shown_identity_count=len(hydration.primary_global_ids),
        # The identity cap never reduces the reported total (§3.1): prefer the
        # hydration's own count of matching objects, and fall back to the part's
        # exact total rather than to the length of the capped identity list.
        true_result_count=(
            hydration.viewer_matches_total
            or result.exact_total
            or len(hydration.primary_global_ids)
        ),
        identities_truncated=hydration.viewer_matches_truncated,
        groups=_groups(result, hydration) if choice.show_groups else [],
        rows=choice.rows,
    )


# ---------------------------------------------------------------------------
# The fixed operation/data mapping (§2.1)
# ---------------------------------------------------------------------------


def _choose(result: AnswerPartResult, hydration: ViewerHydration) -> _Choice | None:
    """Map the accepted operation and its existing data to one presentation.

    `partial` status is deliberately NOT consulted here: it is a modifier, so a
    partial count is still a count table and a partial aggregate still opens
    nothing. Its limitation and known/unknown split travel in the payload and
    appear in the persistent information region instead (§2).

    Operations absent from this function — `existence`, `sample_detail`,
    `aggregate`, `extremum`, `description` — return `None` on purpose: a scalar,
    a measurement or qualitative text gains nothing from a supporting
    visualization, and `sample_detail` keeps the existing component/detail flow.
    """
    operation = result.operation

    if operation in ("count", "list"):
        # A count is the deliberate exception to the general scalar rule: when it
        # counts an identifiable object set, the table lets the user inspect
        # membership. With no authoritative displayed identities it stays in chat.
        rows = _identity_rows(result, hydration)
        if not rows:
            return None
        return _Choice(
            ExplanationPresentation.RESULT_TABLE,
            rows=rows,
            show_groups=True,
        )

    if operation == "group_distribution":
        buckets = _buckets(result)
        if len(buckets) >= 2:
            return _Choice(ExplanationPresentation.BAR_CHART, buckets=buckets)
        if len(buckets) == 1:
            # One bar is no comparison, so the bucket is tabulated instead (§3.2).
            return _Choice(ExplanationPresentation.GROUP_TABLE, buckets=buckets)
        return None

    if operation == "relationship":
        selection = build_relationship_graph(result, set(hydration.primary_global_ids))
        if selection.graph is not None:
            return _Choice(ExplanationPresentation.RELATIONSHIP_GRAPH, graph=selection.graph)
        rows = _endpoint_rows(result)
        if not rows:
            return None
        return _Choice(
            ExplanationPresentation.RELATIONSHIP_TABLE,
            rows=rows,
            fallback_reason=selection.fallback_reason,
            show_groups=True,
        )

    if operation == "comparison":
        # Only an ALREADY-structured comparison qualifies. Nothing is computed to
        # make one exist, so a comparison the pipeline answered qualitatively
        # stays in chat (§2.1, §3.2).
        buckets = _buckets(result)
        if len(buckets) >= 2 and all(b.value is not None for b in buckets):
            return _Choice(ExplanationPresentation.BAR_CHART, buckets=buckets)
        if buckets:
            return _Choice(ExplanationPresentation.COMPARISON_TABLE, buckets=buckets)
        return None

    return None


def _identity_rows(result: AnswerPartResult, hydration: ViewerHydration) -> list[ExplanationRow]:
    """Bounded rows over the identities the viewer ALREADY received (§3.1).

    The IFC class comes from the class each identity was hydrated with, and any
    name/storey already fetched as an example is merged in by GlobalId. Both
    lists are ordered by entity id, so the merge is positional-free and stable —
    and that order is the "original backend order" the frontend's sort cycle
    restores on its third click (task31 §4.3).

    No query is issued to fill a missing name: GlobalId plus IFC class is a
    sufficient row, and GlobalId is the final identity fallback. That stays true
    now that every hydrated identity becomes a row (task31 §4.1) — the larger
    list is a projection of identities already in hand, never a reason to fetch
    metadata for the rows that lack it.

    Without hydrated class information there are no authoritative displayed
    identities, so this returns nothing and the result stays in chat.
    """
    metadata = {e.global_id: e for e in result.examples}
    rows: list[ExplanationRow] = []
    for identity in hydration.primary_identities[:MAX_EXPLANATION_ROWS]:
        example = metadata.get(identity.global_id)
        rows.append(
            ExplanationRow(
                global_id=identity.global_id,
                ifc_class=identity.ifc_class,
                name=example.name if example else None,
                storey_name=example.storey_name if example else None,
            )
        )
    return rows


def _endpoint_rows(result: AnswerPartResult) -> list[ExplanationRow]:
    """The traversal endpoints — the only objects a relationship answer claims."""
    return [
        ExplanationRow(
            global_id=e.global_id,
            ifc_class=e.ifc_class,
            name=e.name,
            storey_name=e.storey_name,
        )
        for e in result.graph_endpoints[:MAX_EXPLANATION_ROWS]
    ]


def _groups(result: AnswerPartResult, hydration: ViewerHydration) -> list[ExplanationGroup]:
    """Selectable class groups, partitioned from the identities already sent.

    Membership comes from the class each identity was retrieved with, so a group
    is a literal subset of the highlighted set. When no class information
    accompanied the identities, no group is offered at all — an unselectable
    card is correct; a guessed subgroup is not. A single-class result yields no
    group summary either: one row of a breakdown is not a breakdown (§3.1).
    """
    if not hydration.primary_identities:
        return []

    shown: dict[str, list[str]] = {}
    for identity in hydration.primary_identities:
        shown.setdefault(identity.ifc_class, []).append(identity.global_id)
    if len(shown) < 2:
        return []

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
    """Retained for the information region's coverage note. `aggregate` and
    `extremum` no longer open a panel, so this is populated only when some other
    qualifying operation happens to carry a value."""
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


def _chart_unit(result: AnswerPartResult, choice: _Choice) -> str | None:
    """The bar chart's unit, only when the result already recorded one."""
    if choice.presentation is not ExplanationPresentation.BAR_CHART:
        return None
    if not any(b.value is not None for b in choice.buckets):
        return None
    return result.aggregate.unit if result.aggregate else None
