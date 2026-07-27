"""Deterministic assembly of the typed logical plan (task30 §3, §4).

The skeleton already fixes every structural decision, and the grounding call
supplies only backend identities. Assembling the two is therefore pure code:
node handles, Boolean grouping, ordering, limits, viewer policy and the
requirement dispositions all follow from the obligations, and none of them can
be lost or altered by a model.

Dispositions are derived here rather than asked for, which is why the plan can
never claim to have bound something it did not: a `bound` disposition is written
only when a real identity reached the node, and an `unavailable` one carries the
reason the grounding call gave for the slot.
"""

from __future__ import annotations

from typing import Any

from app.llm.schemas_grounding import GroundedBindings
from app.llm.schemas_v2 import (
    AggregateFunction,
    AggregateNode,
    AnswerPartV2,
    DispositionKind,
    FilterNode,
    GroupNode,
    LogicalOperator,
    LogicalPlan,
    OrderNode,
    RequirementDisposition,
    ResultKind,
    ScopeKindV2,
    ScopeNode,
    TargetNode,
    TraverseNode,
    ViewerSetPolicy,
)
from app.llm.schemas_v5 import ConstraintKind, ConstraintOperator, ResolvedIntent
from app.query.binding.obligations import (
    Obligation,
    PlanSkeleton,
    apply_bindings,
)

__all__ = ["assemble_plan"]

_OPERATOR = {op.value: LogicalOperator(op.value) for op in ConstraintOperator}


def assemble_plan(
    intent: ResolvedIntent,
    skeleton: PlanSkeleton,
    obligations: list[Obligation],
    bindings: GroundedBindings,
) -> LogicalPlan:
    """Build the typed plan from the fixed skeleton and the chosen identities."""
    by_slot = bindings.by_slot()
    apply_bindings(
        obligations,
        {
            slot_id: {
                "semantic_id": binding.semantic_id,
                "unsupported_reason": binding.unsupported_reason,
            }
            for slot_id, binding in by_slot.items()
        },
    )
    ambiguous = set(bindings.ambiguous_slot_ids)
    for obligation in obligations:
        if obligation.slot_id in ambiguous:
            obligation.disposition = "ambiguous"

    obligation_by_id = {o.obligation_id: o for o in obligations}
    parts: list[AnswerPartV2] = []
    dispositions: list[RequirementDisposition] = []

    for skeleton_part in skeleton.parts:
        slots = skeleton.slots_for(skeleton_part.part_id)
        target_node: TargetNode | None = None
        filters: list[FilterNode] = []
        scope: ScopeNode | None = None
        traversals: list[TraverseNode] = []
        group: GroupNode | None = None
        projections: list[str] = []

        for slot in slots:
            binding = by_slot.get(slot.slot_id)
            obligation = obligation_by_id.get(slot.obligation_id)
            semantic_id = binding.semantic_id if binding else None

            if slot.node_kind == "target":
                if semantic_id and target_node is None:
                    union = list(binding.union_semantic_ids) if binding else []
                    target_node = TargetNode(
                        node_id=slot.node_id,
                        semantic_id=semantic_id,
                        union_semantic_ids=union[:4],
                    )
                continue
            if not semantic_id and slot.node_kind != "traverse":
                continue
            if slot.node_kind == "filter":
                operator = _OPERATOR.get(
                    slot.operator.value if slot.operator else "is_present",
                    LogicalOperator.IS_PRESENT,
                )
                filters.append(
                    FilterNode(
                        node_id=slot.node_id,
                        semantic_id=semantic_id,
                        operator=operator,
                        value_text=slot.value_text,
                        value_list=list(slot.value_list)[:50],
                        unit=slot.unit,
                        negated=slot.negated,
                        bool_group=slot.bool_group,
                    )
                )
            elif slot.node_kind == "scope":
                scope = ScopeNode(
                    node_id=slot.node_id,
                    kind=_scope_kind(obligation),
                    semantic_id=semantic_id,
                )
            elif slot.node_kind == "traverse":
                paths = list(binding.path_semantic_ids) if binding else []
                if not paths and semantic_id:
                    paths = [semantic_id]
                if paths:
                    traversals.append(
                        TraverseNode(
                            node_id=slot.node_id,
                            path_semantic_ids=paths[:3],
                            endpoint_semantic_id=(
                                binding.endpoint_semantic_id if binding else None
                            ),
                        )
                    )
            elif slot.node_kind == "group":
                group = GroupNode(node_id=slot.node_id, semantic_id=semantic_id)
            elif slot.node_kind == "report":
                projections.append(semantic_id)

        if target_node is None:
            # Nothing to count or list: the part cannot exist, and every one of
            # its obligations keeps whatever disposition grounding gave it.
            continue

        # A narrowing condition this model cannot serve does NOT cancel the
        # request — the part still executes over the set it can identify. But
        # that set is broader than the user asked for, so the part is marked
        # contextual: hydration then discloses that the highlighted objects are
        # the base set, and the answerer is required to say which condition
        # could not be applied. Answering the unnarrowed set silently is the one
        # outcome worse than refusing.
        widened = [
            obligation_by_id[s.obligation_id]
            for s in slots
            if s.node_kind in ("filter", "scope", "traverse")
            and s.obligation_id in obligation_by_id
            and obligation_by_id[s.obligation_id].required
            and not obligation_by_id[s.obligation_id].satisfied
        ]
        context_reason = None
        if widened:
            context_reason = (
                "this model does not record "
                + "; ".join(o.retrieval_text for o in widened[:2])
            )[:200]

        # A scope the user implied but no slot produced still selects the model.
        if scope is None:
            scope = ScopeNode(node_id="s0", kind=ScopeKindV2.ACTIVE_MODEL)

        result_kind = ResultKind(skeleton_part.result_kind)
        aggregate = None
        if skeleton_part.aggregate_function:
            aggregate = AggregateNode(
                node_id="a1", function=AggregateFunction(skeleton_part.aggregate_function)
            )
        order = None
        if skeleton_part.order_direction and group is not None:
            order = OrderNode(
                node_id="o1",
                by=skeleton_part.order_basis or "aggregate",
                direction=skeleton_part.order_direction,
            )

        parts.append(
            AnswerPartV2(
                part_id=skeleton_part.part_id,
                request_text=skeleton_part.request_text[:300],
                result_kind=result_kind,
                target=target_node,
                filters=filters[:10],
                filter_bool_op=skeleton_part.filter_bool_op,
                scope=scope,
                traversals=traversals[:2],
                group=group,
                aggregate=aggregate,
                order=order,
                limit=skeleton_part.limit,
                projections=projections[:6],
                evidence_theme=skeleton_part.evidence_theme,
                viewer_set=(
                    ViewerSetPolicy.CONTEXT
                    if context_reason
                    and skeleton_part.viewer_set not in ("none", "sample")
                    else ViewerSetPolicy(skeleton_part.viewer_set)
                ),
                context_reason=context_reason,
                is_primary_visual=skeleton_part.is_primary_visual,
            )
        )

    built_parts = {p.part_id for p in parts}
    for obligation in obligations:
        dispositions.append(_disposition_for(obligation, skeleton, built_parts))

    return LogicalPlan(
        response_language=intent.language or "en",
        answer_parts=parts[:6],
        dispositions=dispositions[:64],
        needs_clarification=bool(bindings.ambiguous_slot_ids),
        clarification_question=bindings.ambiguity_question,
    )


def _scope_kind(obligation: Obligation | None) -> ScopeKindV2:
    if obligation is None or obligation.constraint_kind is None:
        return ScopeKindV2.ACTIVE_MODEL
    if obligation.constraint_kind is ConstraintKind.PREVIOUS_RESULT:
        return ScopeKindV2.PREVIOUS_RESULT
    if obligation.constraint_kind is ConstraintKind.SELECTION:
        return ScopeKindV2.SELECTED_OBJECTS
    if obligation.constraint_kind is ConstraintKind.SPATIAL:
        return ScopeKindV2.FLOOR_BAND
    return ScopeKindV2.ACTIVE_MODEL


def _disposition_for(
    obligation: Obligation, skeleton: PlanSkeleton, built_parts: set[str]
) -> RequirementDisposition:
    """The account of one obligation, derived rather than asserted."""
    slot = skeleton.slot(obligation.slot_id) if obligation.slot_id else None
    if obligation.satisfied and obligation.part_id in built_parts and slot is not None:
        return RequirementDisposition(
            requirement_id=obligation.obligation_id,
            disposition=DispositionKind.BOUND,
            part_id=obligation.part_id,
            node_ids=[slot.node_id],
        )
    if obligation.disposition == "ambiguous":
        return RequirementDisposition(
            requirement_id=obligation.obligation_id,
            disposition=DispositionKind.AMBIGUOUS,
            part_id=obligation.part_id,
            note=(obligation.disposition_note or "more than one recorded reading")[:300],
        )
    return RequirementDisposition(
        requirement_id=obligation.obligation_id,
        disposition=DispositionKind.UNAVAILABLE,
        part_id=obligation.part_id,
        note=(
            obligation.disposition_note
            or f"{obligation.retrieval_text!r} is not recorded in this model"
        )[:300],
    )


def obligation_payload(obligations: list[Obligation]) -> list[dict[str, Any]]:
    return [o.to_payload() for o in obligations]
