"""Typed obligation transfer and the deterministic plan skeleton (task30 §3, §4).

Three concepts that the v5 original conflated into one string are separated
here, and the separation is the whole repair:

- **semantic obligation** — what must be answered or explicitly disposed. It
  carries the resolver's TYPE: a constraint's operator, value, unit, negation
  and Boolean group; a target's coordination; a relationship's direction. These
  are decisions the resolver already made from the conversation, and no later
  stage may re-derive them.
- **retrieval hint** — the user's words, used ONLY to discover backend
  candidates and to explain the result. A hint never decides a role.
- **satisfaction proof** — the selected capability, the executed evidence, or an
  explicit unsupported/ambiguous disposition that discharges the obligation.

`build_plan_skeleton` then fixes everything about the logical plan that follows
from meaning alone: how many answer parts there are, each part's result shape,
which slots exist, their Boolean structure, ordering, limits, and which parts
the viewer will show. Only the backend identity of each slot is left open.

This is what narrows the grounding call from "reconstruct the user's logic while
searching a large projection" to "choose a valid capability for this slot, or say
you cannot". The structure can no longer be lost, because it is never sent
through a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.llm.schemas_v5 import (
    ConstraintKind,
    ConstraintOperator,
    EvidenceKind,
    IntentOperation,
    OrderBasis,
    OrderDirection,
    ResolvedIntent,
    TargetCoordination,
    VisualizationIntent,
)

__all__ = [
    "ObligationKind",
    "Obligation",
    "SkeletonSlot",
    "SkeletonPart",
    "PlanSkeleton",
    "build_obligations",
    "build_plan_skeleton",
]


class ObligationKind(str, Enum):
    TARGET = "target"
    FILTER = "filter"
    SCOPE = "scope"
    RELATIONSHIP = "relationship"
    GROUPING = "grouping"
    ORDERING = "ordering"
    OUTPUT = "output"


#: Which logical node kind can discharge each obligation kind. A slot of the
#: wrong kind never satisfies an obligation, so a target cannot be quietly
#: discharged by a filter, nor a scope by a grouping.
NODE_KIND_FOR: dict[ObligationKind, str] = {
    ObligationKind.TARGET: "target",
    ObligationKind.FILTER: "filter",
    ObligationKind.SCOPE: "scope",
    ObligationKind.RELATIONSHIP: "traverse",
    ObligationKind.GROUPING: "group",
    ObligationKind.OUTPUT: "report",
}


@dataclass
class Obligation:
    """One thing the request requires, with the type the resolver established."""

    obligation_id: str
    #: The resolver handle this obligation represents, one-to-one.
    intent_handle: str
    part_id: str
    kind: ObligationKind
    #: The user's words. A RETRIEVAL HINT and an explanation, never a role.
    retrieval_text: str
    required: bool = True

    # -- typed payload carried through unchanged -------------------------
    operator: ConstraintOperator | None = None
    value_text: str | None = None
    value_list: list[str] = field(default_factory=list)
    unit: str | None = None
    negated: bool = False
    or_group: str | None = None
    coordination: TargetCoordination | None = None
    direction: str | None = None
    constraint_kind: ConstraintKind | None = None
    #: For a relationship, the user's words for the far end.
    endpoint_text: str | None = None

    # -- satisfaction proof, filled after grounding -----------------------
    slot_id: str | None = None
    disposition: str | None = None
    disposition_note: str | None = None

    @property
    def satisfied(self) -> bool:
        return self.disposition == "bound" and self.slot_id is not None

    @property
    def explicitly_disposed(self) -> bool:
        return self.disposition in ("unsupported", "ambiguous", "redundant")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "obligation_id": self.obligation_id,
            "from_intent": self.intent_handle,
            "part_id": self.part_id,
            "kind": self.kind.value,
            "text": self.retrieval_text,
            "required": self.required,
        }
        if self.operator is not None:
            payload["operator"] = self.operator.value
        for key, value in (
            ("value", self.value_text),
            ("unit", self.unit),
            ("or_group", self.or_group),
            ("direction", self.direction),
            ("endpoint", self.endpoint_text),
            ("slot_id", self.slot_id),
            ("disposition", self.disposition),
        ):
            if value:
                payload[key] = value
        if self.value_list:
            payload["values"] = list(self.value_list)
        if self.negated:
            payload["negated"] = True
        if self.coordination is not None:
            payload["coordination"] = self.coordination.value
        return payload


# ---------------------------------------------------------------------------
# Obligations
# ---------------------------------------------------------------------------


def build_obligations(intent: ResolvedIntent) -> list[Obligation]:
    """One obligation per material intent handle, in a stable order (§3).

    The mapping is one-to-one and total: every target, constraint, relationship,
    grouping, ordering and output the resolver established becomes exactly one
    obligation, and nothing else does. No obligation is created from text, and
    none is dropped for being wordy — a condition that cannot be named is
    reported unsupported later, never silently downgraded.
    """
    obligations: list[Obligation] = []
    counter = 0

    def _next(kind: ObligationKind) -> str:
        nonlocal counter
        counter += 1
        return f"O{counter}"

    for target in intent.targets:
        obligations.append(
            Obligation(
                obligation_id=_next(ObligationKind.TARGET),
                intent_handle=target.target_id,
                part_id=target.part_id,
                kind=ObligationKind.TARGET,
                retrieval_text=target.text,
                required=True,
                coordination=target.coordination,
            )
        )

    for constraint in intent.constraints:
        kind = (
            ObligationKind.SCOPE
            if constraint.kind
            in (
                ConstraintKind.SPATIAL,
                ConstraintKind.PREVIOUS_RESULT,
                ConstraintKind.SELECTION,
            )
            else ObligationKind.FILTER
        )
        obligations.append(
            Obligation(
                obligation_id=_next(kind),
                intent_handle=constraint.constraint_id,
                part_id=constraint.part_id,
                kind=kind,
                retrieval_text=constraint.text,
                # A session-supplied scope is provenance, not a demand; every
                # condition the USER stated is required, however it is worded.
                required=constraint.kind
                not in (ConstraintKind.PREVIOUS_RESULT, ConstraintKind.SELECTION),
                operator=constraint.operator,
                value_text=constraint.value_text,
                value_list=list(constraint.value_list),
                unit=constraint.unit,
                negated=constraint.negated,
                or_group=constraint.or_group,
                constraint_kind=constraint.kind,
            )
        )

    for relationship in intent.relationships:
        obligations.append(
            Obligation(
                obligation_id=_next(ObligationKind.RELATIONSHIP),
                intent_handle=relationship.relationship_id,
                part_id=relationship.part_id,
                kind=ObligationKind.RELATIONSHIP,
                retrieval_text=relationship.text,
                required=relationship.restricts,
                direction=relationship.direction.value,
                endpoint_text=relationship.to_text,
            )
        )

    for grouping in intent.groupings:
        obligations.append(
            Obligation(
                obligation_id=_next(ObligationKind.GROUPING),
                intent_handle=grouping.grouping_id,
                part_id=grouping.part_id,
                kind=ObligationKind.GROUPING,
                retrieval_text=grouping.axis_text,
                required=True,
            )
        )

    for output in intent.outputs:
        obligations.append(
            Obligation(
                obligation_id=_next(ObligationKind.OUTPUT),
                intent_handle=output.output_id,
                part_id=output.part_id,
                kind=ObligationKind.OUTPUT,
                retrieval_text=output.text,
                required=True,
            )
        )

    return obligations


# ---------------------------------------------------------------------------
# Plan skeleton
# ---------------------------------------------------------------------------


@dataclass
class SkeletonSlot:
    """One place in the plan where a backend identity must be chosen."""

    slot_id: str
    part_id: str
    #: The logical node kind this slot becomes.
    node_kind: str
    #: The local handle the assembled plan will use.
    node_id: str
    obligation_id: str
    retrieval_text: str
    #: Structure decided before grounding; the model may not change any of it.
    operator: ConstraintOperator | None = None
    value_text: str | None = None
    value_list: list[str] = field(default_factory=list)
    unit: str | None = None
    negated: bool = False
    bool_group: str | None = None
    direction: str | None = None
    endpoint_text: str | None = None
    #: Slot ids whose concepts join this one as peer subjects of one figure.
    union_slot_ids: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slot_id": self.slot_id,
            "part_id": self.part_id,
            "needs": self.node_kind,
            "for": self.retrieval_text,
        }
        if self.operator is not None:
            payload["operator"] = self.operator.value
        for key, value in (
            ("value", self.value_text),
            ("unit", self.unit),
            ("or_group", self.bool_group),
            ("direction", self.direction),
            ("endpoint", self.endpoint_text),
        ):
            if value:
                payload[key] = value
        if self.value_list:
            payload["values"] = list(self.value_list)
        if self.negated:
            payload["negated"] = True
        if self.union_slot_ids:
            payload["combined_with"] = list(self.union_slot_ids)
        return payload


@dataclass
class SkeletonPart:
    """One answer part whose shape is settled before any grounding call."""

    part_id: str
    request_text: str
    result_kind: str
    limit: int | None = None
    viewer_set: str = "none"
    is_primary_visual: bool = False
    filter_bool_op: str = "and"
    aggregate_function: str | None = None
    order_direction: str | None = None
    order_basis: str | None = None
    evidence_theme: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "part_id": self.part_id,
            "request": self.request_text,
            "result_kind": self.result_kind,
            "viewer_set": self.viewer_set,
        }
        for key, value in (
            ("limit", self.limit),
            ("aggregate", self.aggregate_function),
            ("order", self.order_direction),
            ("theme", self.evidence_theme),
        ):
            if value is not None:
                payload[key] = value
        if self.filter_bool_op != "and":
            payload["filters_combine"] = self.filter_bool_op
        return payload


@dataclass
class PlanSkeleton:
    parts: list[SkeletonPart] = field(default_factory=list)
    slots: list[SkeletonSlot] = field(default_factory=list)

    def slot(self, slot_id: str) -> SkeletonSlot | None:
        return next((s for s in self.slots if s.slot_id == slot_id), None)

    def slots_for(self, part_id: str) -> list[SkeletonSlot]:
        return [s for s in self.slots if s.part_id == part_id]

    def to_payload(self) -> dict[str, Any]:
        return {
            "parts": [p.to_payload() for p in self.parts],
            "slots": [s.to_payload() for s in self.slots],
        }

    def size_report(self) -> dict[str, int]:
        return {"parts": len(self.parts), "slots": len(self.slots)}


#: Operation -> the result shape it produces. This mapping follows from meaning
#: alone, so it is decided here rather than asked of a model that previously got
#: it wrong often enough to block execution.
_RESULT_KIND: dict[IntentOperation, str] = {
    IntentOperation.COUNT: "scalar",
    IntentOperation.LIST: "entity_set",
    IntentOperation.EXISTENCE: "entity_set",
    IntentOperation.VALUE_REPORT: "entity_set",
    IntentOperation.DISTRIBUTION: "distribution",
    IntentOperation.COMPARISON: "distribution",
    IntentOperation.EXTREMUM: "distribution",
    IntentOperation.SAMPLE: "sample",
    IntentOperation.DESCRIPTION: "profile",
    IntentOperation.CONNECTION: "graph_endpoints",
    IntentOperation.CATALOG: "profile",
}


def _result_kind(part: Any, has_grouping: bool, has_relationship: bool) -> str:
    kind = _RESULT_KIND.get(part.operation, "entity_set")
    if part.operation is IntentOperation.DESCRIPTION:
        # A descriptive request about a structured set is qualitative evidence;
        # only a whole-model or thematic summary is a profile.
        if part.evidence_kind in (EvidenceKind.QUALITATIVE, EvidenceKind.MIXED):
            return "qualitative_evidence"
        return "profile"
    if part.operation is IntentOperation.VALUE_REPORT and has_grouping:
        return "distribution"
    if has_relationship and kind == "entity_set":
        return "graph_endpoints"
    return kind


def _viewer_set(part: Any, result_kind: str) -> str:
    if not part.highlightable:
        return "none"
    if result_kind == "sample":
        return "sample"
    if result_kind == "graph_endpoints":
        return "graph_endpoints"
    if result_kind in ("profile", "qualitative_evidence"):
        return "none"
    return "requested"


def build_plan_skeleton(
    intent: ResolvedIntent, obligations: list[Obligation]
) -> PlanSkeleton:
    """Fix every structural decision that follows from meaning alone (§4)."""
    skeleton = PlanSkeleton()
    by_part: dict[str, list[Obligation]] = {}
    for obligation in obligations:
        by_part.setdefault(obligation.part_id, []).append(obligation)

    primary_assigned = False
    for part in intent.parts:
        part_obligations = by_part.get(part.part_id, [])
        groupings = [o for o in part_obligations if o.kind is ObligationKind.GROUPING]
        relationships = [
            o for o in part_obligations if o.kind is ObligationKind.RELATIONSHIP
        ]
        orderings = intent.orderings_for(part.part_id)
        result_kind = _result_kind(part, bool(groupings), bool(relationships))
        viewer_set = _viewer_set(part, result_kind)

        limit = part.limit
        if part.operation is IntentOperation.SAMPLE:
            limit = 1
        elif part.operation is IntentOperation.EXTREMUM and limit is None:
            limit = 1

        aggregate = None
        if result_kind in ("scalar", "distribution"):
            aggregate = "count"

        # An "or" between a part's conditions is expressed by shared groups; a
        # part whose every condition shares one group combines with "or".
        filter_groups = {
            o.or_group
            for o in part_obligations
            if o.kind is ObligationKind.FILTER and o.or_group
        }
        filter_count = len(
            [o for o in part_obligations if o.kind is ObligationKind.FILTER]
        )
        bool_op = "or" if len(filter_groups) == 1 and filter_count > 1 else "and"

        ordering = orderings[0] if orderings else None
        skeleton_part = SkeletonPart(
            part_id=part.part_id,
            request_text=part.request_text,
            result_kind=result_kind,
            limit=limit,
            viewer_set=viewer_set,
            is_primary_visual=(
                viewer_set != "none"
                and (
                    intent.visualization is VisualizationIntent.ALL_RESULTS
                    or not primary_assigned
                )
            ),
            filter_bool_op=bool_op,
            aggregate_function=aggregate,
            order_direction=(
                ordering.direction.value
                if ordering
                else (
                    OrderDirection.DESC.value
                    if result_kind == "distribution" and limit
                    else None
                )
            ),
            order_basis=(
                ordering.basis.value
                if ordering
                else (
                    OrderBasis.AGGREGATE.value
                    if result_kind == "distribution" and limit
                    else None
                )
            ),
            evidence_theme=(
                part.request_text[:200]
                if result_kind in ("profile", "qualitative_evidence")
                else None
            ),
        )
        if skeleton_part.is_primary_visual:
            primary_assigned = True
        skeleton.parts.append(skeleton_part)

        # -- slots, in a stable order with canonical local handles ----------
        counters = {"target": 0, "filter": 0, "scope": 0, "traverse": 0, "group": 0, "report": 0}
        union_members: list[str] = []
        for obligation in part_obligations:
            node_kind = NODE_KIND_FOR.get(obligation.kind)
            if node_kind is None:
                continue
            counters[node_kind] += 1
            prefix = {
                "target": "t",
                "filter": "f",
                "scope": "s",
                "traverse": "v",
                "group": "g",
                "report": "p",
            }[node_kind]
            node_id = f"{prefix}{counters[node_kind]}"
            slot = SkeletonSlot(
                slot_id=f"{part.part_id}.{node_id}",
                part_id=part.part_id,
                node_kind=node_kind,
                node_id=node_id,
                obligation_id=obligation.obligation_id,
                retrieval_text=obligation.retrieval_text,
                operator=obligation.operator,
                value_text=obligation.value_text,
                value_list=list(obligation.value_list),
                unit=obligation.unit,
                negated=obligation.negated,
                bool_group=obligation.or_group,
                direction=obligation.direction,
                endpoint_text=obligation.endpoint_text,
            )
            obligation.slot_id = slot.slot_id
            skeleton.slots.append(slot)
            if (
                obligation.kind is ObligationKind.TARGET
                and obligation.coordination is TargetCoordination.UNION_MEMBER
            ):
                union_members.append(slot.slot_id)

        # Coordinated subjects become one union on the part's first target.
        if len(union_members) > 1:
            head = skeleton.slot(union_members[0])
            if head is not None:
                head.union_slot_ids = union_members[1:]

    return skeleton


def apply_bindings(
    obligations: list[Obligation], bindings: dict[str, Any]
) -> None:
    """Record each slot's satisfaction proof on its obligation (§3).

    `bindings` maps slot_id -> {"semantic_id": ..., "unsupported_reason": ...}.
    An obligation is discharged only by a real identity; anything else is an
    explicit disposition, never silence.
    """
    for obligation in obligations:
        if obligation.slot_id is None:
            continue
        binding = bindings.get(obligation.slot_id)
        if binding is None:
            obligation.disposition = None
            continue
        if binding.get("semantic_id"):
            obligation.disposition = "bound"
            obligation.disposition_note = None
        else:
            obligation.disposition = "unsupported"
            obligation.disposition_note = binding.get("unsupported_reason")


def unsatisfied(obligations: list[Obligation]) -> list[Obligation]:
    """Required obligations that are neither bound nor explicitly disposed."""
    return [
        o
        for o in obligations
        if o.required and not o.satisfied and not o.explicitly_disposed
    ]


# ---------------------------------------------------------------------------
# Retrieval vehicle
# ---------------------------------------------------------------------------

#: Obligation kind -> the recall role whose channels and ranking suit it. This
#: is not reclassification: the resolver already decided the role, and this only
#: tells recall which retrieval strategy to use for a role already fixed.
_RECALL_ROLE = {
    ObligationKind.TARGET: "target",
    ObligationKind.FILTER: "filter",
    ObligationKind.SCOPE: "scope",
    ObligationKind.RELATIONSHIP: "traversal",
    ObligationKind.GROUPING: "group",
    ObligationKind.OUTPUT: "output",
}


def build_recall_ledger(obligations: list[Obligation], question: str) -> Any:
    """A ledger whose requirements ARE the obligations, for recall only (§3).

    Recall's channels, fusion, value linking and floor resolution are unchanged
    and still earn their keep; what changes is that their input is now a typed
    obligation rather than a phrase whose role had to be guessed. The ledger is
    marked typed so no downstream stage treats its text as authority over a role
    the resolver already established.
    """
    from app.query.binding.ledger_v2 import (
        LedgerRequirement,
        LedgerV2,
        RequirementRole,
        ResolutionState,
    )

    ledger = LedgerV2(question=question)
    ledger.typed = True
    for obligation in obligations:
        role = RequirementRole(_RECALL_ROLE[obligation.kind])
        span_kind = None
        if obligation.kind is ObligationKind.SCOPE:
            if obligation.constraint_kind is ConstraintKind.SPATIAL:
                span_kind = "floor_reference"
            elif obligation.constraint_kind is ConstraintKind.PREVIOUS_RESULT:
                span_kind = "previous_result_reference"
            elif obligation.constraint_kind is ConstraintKind.SELECTION:
                span_kind = "selection_reference"
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=obligation.obligation_id,
                source_text=obligation.retrieval_text,
                start=-1,
                end=-1,
                role=role,
                required=obligation.required,
                part_hint=obligation.part_id,
                negated=obligation.negated,
                bool_group=obligation.or_group,
                span_kind=span_kind,
                source="resolved_intent",
                intent_ref=obligation.intent_handle,
                resolution=(
                    ResolutionState.RESOLVABLE
                    if obligation.kind is ObligationKind.ORDERING
                    else ResolutionState.UNRESOLVED
                ),
            )
        )
    return ledger


def candidates_by_slot(
    obligations: list[Obligation], recall: Any
) -> dict[str, list[dict[str, Any]]]:
    """Ranked candidates per slot, keyed by the slot the obligation produced."""
    out: dict[str, list[dict[str, Any]]] = {}
    for obligation in obligations:
        if obligation.slot_id is None:
            continue
        offered = [
            {
                "id": r.concept_id,
                "label": r.label,
                **({"subjects": list(r.applicable_subjects[:4])} if r.applicable_subjects else {}),
                **({"coverage": r.coverage} if r.coverage else {}),
                **({"not_executable": True} if not r.executable else {}),
            }
            for r in recall.for_requirement(obligation.obligation_id)
        ]
        floor_candidates = getattr(recall, "floor_candidates", {}).get(
            obligation.obligation_id
        )
        if floor_candidates:
            offered = [
                {"id": fid, "label": "derived floor band"} for fid in floor_candidates
            ] + offered
        if offered:
            out[obligation.slot_id] = offered
    return out
